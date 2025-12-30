# vim assistant.py

import os
import sys
import time
import glob
import re
import importlib.util
import numpy as np
import whisper
import ollama
import threading
import subprocess
import uuid 
import sounddevice as sd
from flask import Flask, request, jsonify
from datetime import datetime
import traceback
import config

# --- FALLBACKS ---
try: from audio_utils import play_tts, record_audio, clean_old_cache
except ImportError: 
    def play_tts(t, **k): print(f"[TTS] {t}")
    def record_audio(): return np.zeros(16000, dtype=np.int16)
try: from data_utils import setup_database, retrieve_from_rag, get_cached_response, save_cached_response
except ImportError: 
    def setup_database(): pass
    def retrieve_from_rag(p): return ""
    def get_cached_response(p): return None
    def save_cached_response(p, r): pass
try: from tools import search_with_searxng
except ImportError: 
    def search_with_searxng(p): return ""

# --- GLOBAIS ---
CURRENT_REQUEST_ID = None  
IS_SPEAKING = False
app = Flask(__name__)
whisper_model = None
ollama_client = None
SKILLS_LIST = []

# --- UTILITÁRIOS ---
def stop_audio_output():
    global IS_SPEAKING
    IS_SPEAKING = False
    subprocess.run(['pkill', '-f', 'aplay'], check=False, stderr=subprocess.DEVNULL)
    subprocess.run(['pkill', '-f', 'mpg123'], check=False, stderr=subprocess.DEVNULL)

def is_quiet_time():
    if not hasattr(config, 'QUIET_START'): return False
    now = datetime.now().hour
    if config.QUIET_START > config.QUIET_END: return now >= config.QUIET_START or now < config.QUIET_END
    return config.QUIET_START <= now < config.QUIET_END

def safe_play_tts(text, use_cache=True, request_id=None, speak=True):
    global CURRENT_REQUEST_ID, IS_SPEAKING
    if not speak: return
    if request_id and request_id != "API_REQ" and request_id != CURRENT_REQUEST_ID: return
    stop_audio_output()
    IS_SPEAKING = True
    play_tts(text, use_cache=use_cache)
    IS_SPEAKING = False

def force_volume_down(card_index):
    """ 
    Aplica o volume definido no config APENAS aos canais de Captura (Mic).
    Tenta também DESATIVAR o AGC (Auto Gain Control) para evitar falsos positivos
    causados pela flutuação do ruído de fundo.
    """
    # Baixei o default de 80 para 60. 80% num Jabra é demasiado "quente".
    target = getattr(config, 'ALSA_VOLUME_PERCENT', 60)
    print(f"🎚️ A verificar volumes no Card {card_index} (Alvo: {target}%)...")
    
    try:
        # Lista todos os controlos do cartão
        cmd = ['amixer', '-c', str(card_index), 'scontrols']
        result = subprocess.run(cmd, capture_output=True, text=True)
        # Regex para apanhar o nome entre plicas simples 'Nome'
        controls = re.findall(r"Simple mixer control '([^']+)'", result.stdout)
        
        if not controls: return

        for ctrl in controls:
            # FILTRO DE SEGURANÇA: Ignora saídas de som
            if any(x in ctrl for x in ['PCM', 'Master', 'Speaker', 'Headphone', 'Playback']):
                continue
            
            # 1. Ajuste de Volume (Capture/Mic)
            if 'Capture' in ctrl or 'Mic' in ctrl:
                print(f"   ↘ Ajustando entrada: '{ctrl}' -> {target}%")
                subprocess.run(['amixer', '-c', str(card_index), 'sset', ctrl, f'{target}%', 'unmute', 'cap'], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 2. CRÍTICO: Desativar AGC (Auto Gain Control)
            # Isto impede que o microfone aumente a sensibilidade no silêncio
            if 'AGC' in ctrl or 'Auto Gain' in ctrl:
                print(f"   🚫 A desativar AGC: '{ctrl}'")
                subprocess.run(['amixer', '-c', str(card_index), 'sset', ctrl, 'off'], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    except Exception as e: 
        print(f"⚠️ Erro ao ajustar volumes: {e}")

def find_working_samplerate(device_index):
    candidates = [48000, 44100, 32000, 16000]
    print(f"🕵️ A negociar Sample Rate para o device {device_index}...")
    for rate in candidates:
        try:
            with sd.InputStream(device=device_index, channels=1, samplerate=rate, dtype='int16'):
                pass 
            print(f"✅ Hardware aceitou: {rate} Hz")
            return rate
        except: pass
    return 16000

# --- MOTOR PHANTASMA ---
class PhantasmaEngine:
    def __init__(self, model_paths):
        self.ready = False
        try:
            from openwakeword.model import Model
            self.model = Model(wakeword_models=model_paths, inference_framework="onnx")
            self.ready = True
            print(f"👻 Motor Phantasma: ONLINE")
            print(f"   Modelos: {model_paths}")
        except Exception as e:
            print(f"❌ Erro Motor: {e}")

    def predict(self, audio_chunk_int16):
        if not self.ready: return 0.0
        prediction = self.model.predict(audio_chunk_int16)
        if prediction: return max(prediction.values())
        return 0.0

    def reset(self):
        if self.ready: self.model.reset()

# --- SKILLS & STT ---
def load_skills():
    global SKILLS_LIST
    SKILLS_LIST = []
    if not os.path.exists(config.SKILLS_DIR): return
    sys.path.append(config.SKILLS_DIR)
    for f in glob.glob(os.path.join(config.SKILLS_DIR, "skill_*.py")):
        try:
            name = os.path.basename(f)[:-3]
            spec = importlib.util.spec_from_file_location(name, f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, 'register_routes'): mod.register_routes(app)
            SKILLS_LIST.append({
                "name": name, "handle": getattr(mod, 'handle', None),
                "triggers": getattr(mod, 'TRIGGERS', []), "trigger_type": getattr(mod, 'TRIGGER_TYPE', 'contains'),
                "module": mod, "get_status": getattr(mod, 'get_status_for_device', None)
            })
        except: pass

def transcribe_audio(audio_data):
    if audio_data.size == 0 or whisper_model is None: return ""
    try:
        initial = getattr(config, 'WHISPER_INITIAL_PROMPT', None)
        res = whisper_model.transcribe(audio_data, language='pt', fp16=False, initial_prompt=initial)
        text = res['text'].strip()
        hallucinations = [".", "?", "Obrigado", "Sous-titres"]
        if any(h in text for h in hallucinations) and len(text) < 5: return ""
        if hasattr(config, 'PHONETIC_FIXES'):
            for k, v in config.PHONETIC_FIXES.items():
                if k in text.lower(): text = re.sub(re.escape(k), v, text, flags=re.IGNORECASE)
        return text
    except: return ""

def route_and_respond(prompt, req_id, speak=True):
    global CURRENT_REQUEST_ID
    if req_id == "API_REQ": CURRENT_REQUEST_ID = "API_REQ"; stop_audio_output()
    elif req_id != CURRENT_REQUEST_ID: return

    p_low = prompt.lower()
    
    # 1. Skills (COM FALLTHROUGH - PASSA A BATATA QUENTE)
    for s in SKILLS_LIST:
        trigs = [t.lower() for t in s['triggers']]
        match = any(p_low.startswith(t) for t in trigs) if s['trigger_type'] == 'startswith' else any(t in p_low for t in trigs)
        
        if match and s['handle']:
            try:
                # Tenta executar a skill
                resp = s['handle'](p_low, prompt)
                
                if req_id != CURRENT_REQUEST_ID: return

                # CRÍTICO: Se a skill devolveu None/Vazio, IGNORA e continua o loop!
                if not resp:
                    print(f"⏩ Skill '{s['name']}' ignorou o pedido.")
                    continue
                
                txt = resp.get("response", "") if isinstance(resp, dict) else resp
                
                # Se a resposta for vazia, também continua
                if not txt:
                    continue

                # Se chegámos aqui, é porque a skill resolveu!
                print(f"🔧 Skill '{s['name']}' resolveu.")
                safe_play_tts(txt, False, req_id, speak)
                return txt
            except Exception as e:
                print(f"⚠️ Erro Skill {s['name']}: {e}")
                pass 

    # 2. Cache
    cached = get_cached_response(prompt)
    if cached:
        safe_play_tts(cached, True, req_id, speak)
        return cached

    # 3. LLM
    safe_play_tts("Deixa ver...", True, req_id, speak)
    rag = retrieve_from_rag(prompt)
    web = search_with_searxng(prompt)
    try:
        if req_id != CURRENT_REQUEST_ID: return
        model = getattr(config, 'OLLAMA_MODEL_PRIMARY', 'llama3')
        full_p = f"{getattr(config,'SYSTEM_PROMPT','')}\nContext:{rag}\n{web}\nUser:{prompt}"
        resp = ollama_client.chat(model=model, messages=[{'role':'user','content':full_p}])
        ans = resp['message']['content']
        if req_id != CURRENT_REQUEST_ID: return
        save_cached_response(prompt, ans)
        safe_play_tts(ans, False, req_id, speak)
        return ans
    except Exception as e: return f"Erro: {e}"

def process_command_thread(audio, req_id):
    txt = transcribe_audio(audio)
    if txt:
        print(f"🗣️  Ouvi: {txt}")
        route_and_respond(txt, req_id, speak=True)
    else: print("🤷 Nada ouvido.")

# --- API ---
@app.route("/comando", methods=['POST'])
def api_cmd():
    return jsonify({"status":"ok", "response": route_and_respond(request.json.get('prompt',''), "API_REQ", False)})

@app.route("/get_devices")
def api_devs():
    toggles, status = [], []
    def keys(attr): return list(getattr(config, attr).keys()) if hasattr(config, attr) else []
    for n in keys('TUYA_DEVICES'):
        if any(x in n.lower() for x in ['sensor','temp']): status.append(n)
        else: toggles.append(n)
    for n in keys('MIIO_DEVICES') + keys('EWELINK_DEVICES'): toggles.append(n)
    for n in keys('CLOOGY_DEVICES'):
        if 'casa' in n.lower(): status.append(n)
        else: toggles.append(n)
    if hasattr(config, 'SHELLY_GAS_URL'): status.append("Sensor de Gás")
    return jsonify({"status":"ok", "devices": {"toggles": toggles, "status": status}})

@app.route("/device_status")
def api_status():
    nick = request.args.get('nickname')
    for s in SKILLS_LIST:
        if s.get("get_status"):
            try:
                res = s["get_status"](nick)
                if res and res.get('state') != 'unreachable': return jsonify(res)
            except: continue
    return jsonify({"state": "unreachable"})

@app.route("/device_action", methods=['POST'])
def api_action():
    d = request.json
    return jsonify({"status":"ok", "response": route_and_respond(f"{d.get('action')} o {d.get('device')}", "API_REQ", False)})

@app.route("/help")
def get_help():
    cmds = {"diz": "TTS"}
    for s in SKILLS_LIST:
        triggers = s.get("triggers", [])
        cmds[s["name"]] = ", ".join(triggers[:3]) + "..." if triggers else "Ativo"
    return jsonify({"status": "ok", "commands": cmds})

# --- MAIN LOOP ---
def main():
    global CURRENT_REQUEST_ID, IS_SPEAKING
    
    # Import local para não mexer no topo do ficheiro
    import queue 

    if not config.WAKEWORD_MODELS: print("❌ WAKEWORD_MODELS vazio!"); return
    
    engine = PhantasmaEngine(config.WAKEWORD_MODELS)
    if not engine.ready: return

    # Config Audio
    device_in = getattr(config, 'ALSA_DEVICE_IN', 0)
    force_volume_down(device_in) 
    DETECTED_RATE = find_working_samplerate(device_in)
    
    # Lógica de Downsample
    if DETECTED_RATE > 32000: DOWNSAMPLE_FACTOR = 3
    elif DETECTED_RATE > 24000: DOWNSAMPLE_FACTOR = 2
    else: DOWNSAMPLE_FACTOR = 1
        
    CHUNK_SIZE = 1280
    READ_SIZE = CHUNK_SIZE * DOWNSAMPLE_FACTOR
    
    debug = getattr(config, 'DEBUG_MODE', False)
    thresh = getattr(config, 'WAKEWORD_CONFIDENCE', 0.6)
    persistence = getattr(config, 'WAKEWORD_PERSISTENCE', 3)

    print(f"👻 A ouvir no device {device_in} @ {DETECTED_RATE}Hz -> Fator {DOWNSAMPLE_FACTOR}x")

    streak = 0
    cooldown = 0
    log_counter = 0
    
    # Fila para desacoplar a leitura
    audio_queue = queue.Queue()

    def audio_callback(indata, frames, time, status):
        """Callback do sistema de som (Thread separada)"""
        if status:
            print(f"⚠️ Audio Status: {status}", file=sys.stderr)
        audio_queue.put(indata.copy())
    
    while True:
        try:
            # blocksize=READ_SIZE garante pacotes do tamanho certo
            with sd.InputStream(device=device_in, channels=1, samplerate=DETECTED_RATE, 
                                dtype='int16', blocksize=READ_SIZE, callback=audio_callback):
                
                print(f"👂 Stream Ativo")
                
                while True:
                    # Lê da fila (bloqueia na RAM, não no driver)
                    chunk = audio_queue.get()
                    
                    audio_raw = np.frombuffer(chunk, dtype=np.int16)

                    # Processamento de Audio
                    if DOWNSAMPLE_FACTOR > 1: audio_resampled = audio_raw[::DOWNSAMPLE_FACTOR]
                    else: audio_resampled = audio_raw

                    audio_float = audio_resampled.astype(np.float32)
                    audio_float -= np.mean(audio_float)
                    audio_np = np.clip(audio_float, -32767, 32767).astype(np.int16)

                    if IS_SPEAKING or time.time() < cooldown: streak=0; continue

                    # Previsão
                    score = engine.predict(audio_np)
                    amplitude = np.max(np.abs(audio_np))

                    # --- SILENT DEBUG LOGIC ---
                    # 1. Calculamos sempre a string (mantém CPU/Timing ativo como no debug)
                    stat = "🔴 CLIP" if amplitude > 32500 else "🟢 SOM"
                    bar = "█" * int(score * 20)
                    debug_str = f"[{stat}] Vol:{amplitude:<5} | Score:{score:.4f} {bar}"
                    
                    log_counter += 1
                    
                    # 2. Mostramos SÓ se o score for interessante (> 0.2) ou se estivermos em debug total
                    # Isto permite-te ver se ele te está a ouvir "baixo" (0.3, 0.4) sem encher o log de lixo
                    if debug or (score > 0.2):
                         # Limita o spam visual mesmo quando deteta algo
                         if log_counter % 2 == 0 or score > thresh:
                            print(debug_str)
                    
                    # 3. Pequeno yield para garantir que a thread de áudio respira
                    if not debug:
                        time.sleep(0.002) 
                    # --------------------------

                    if score > thresh: streak += 1
                    else: streak = 0

                    if streak >= persistence:
                        print(f"\n⚡ WAKEWORD DETETADA! (Score: {score:.2f})")
                        stop_audio_output()
                        if is_quiet_time(): streak=0; engine.reset(); continue
                        break
            
            # --- Fora do Stream (Ação) ---
            with audio_queue.mutex: audio_queue.queue.clear()
            
            req_id = str(uuid.uuid4())[:8]
            CURRENT_REQUEST_ID = req_id
            engine.reset(); streak=0
            
            print("🎤 Fala...")
            safe_play_tts("Sim?", speak=True)
            
            audio_cmd = record_audio() 
            
            t = threading.Thread(target=process_command_thread, args=(audio_cmd, req_id))
            t.daemon=True; t.start()
            cooldown = time.time() + 2.0

        except Exception as e:
            print(f"❌ Erro Main: {e}")
            time.sleep(1)

if __name__ == "__main__":
    setup_database(); load_skills()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000), daemon=True).start()
    try: whisper_model = whisper.load_model(getattr(config, 'WHISPER_MODEL', 'base')); ollama_client = ollama.Client()
    except: pass
    for s in SKILLS_LIST: 
        if hasattr(s['module'], 'init_skill_daemon'): 
            try: s['module'].init_skill_daemon()
            except: pass
    try: main()
    except KeyboardInterrupt: stop_audio_output()
