import os
import sys
import time
import numpy as np
import whisper
import ollama
import torch 
import httpx
import traceback
import random
import glob
import importlib.util
import webrtcvad
import threading
import logging
from flask import Flask, request, jsonify
import pvporcupine
import sounddevice as sd 

# --- NOSSOS MÓDULOS ---
import config
from audio_utils import *
from data_utils import *
from tools import search_with_searxng

# --- Carregamento Dinâmico de Skills ---
SKILLS_LIST = []

def load_skills():
    print("A carregar skills...")
    skill_files = glob.glob(os.path.join(config.SKILLS_DIR, "skill_*.py"))
    for f in skill_files:
        try:
            skill_name = os.path.basename(f)[:-3]
            spec = importlib.util.spec_from_file_location(skill_name, f)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            SKILLS_LIST.append({
                "name": skill_name,
                "trigger_type": getattr(module, 'TRIGGER_TYPE', 'contains'),
                "triggers": getattr(module, 'TRIGGERS', []),
                "handle": module.handle,
                "get_status": getattr(module, 'get_status_for_device', None)
            })
            print(f"  -> Skill '{skill_name}' carregada.")
        except Exception as e:
            print(f"AVISO: Falha ao carregar {f}: {e}")

# --- Globais ---
whisper_model = None
ollama_client = None
conversation_history = []
volatile_cache = {}

# --- IA Core ---
def transcribe_audio(audio_data):
    if audio_data.size == 0: return ""
    print(f"A transcrever (Modelo: {config.WHISPER_MODEL})...")
    try:
        res = whisper_model.transcribe(audio_data, language='pt', fp16=False, initial_prompt=config.WHISPER_INITIAL_PROMPT, no_speech_threshold=0.6)
        return res['text'].strip()
    except Exception as e: print(f"Erro transcrição: {e}"); return ""

def process_with_ollama(prompt):
    global conversation_history
    if not prompt: return "Não percebi."
    rag = retrieve_from_rag(prompt); web = search_with_searxng(prompt)
    final = f"{web}\n{rag}\nPERGUNTA: {prompt}"
    conversation_history.append({'role': 'user', 'content': final})
    try:
        print(f"A pensar ({config.OLLAMA_MODEL_PRIMARY})...")
        cli = ollama.Client(timeout=config.OLLAMA_TIMEOUT)
        resp = cli.chat(model=config.OLLAMA_MODEL_PRIMARY, messages=conversation_history)
        content = resp['message']['content']
        conversation_history.append({'role': 'assistant', 'content': content})
        return content
    except: return "Erro no cérebro."

def route_and_respond(user_prompt, speak_response=True):
    try:
        resp = None; prompt_low = user_prompt.lower()
        for s in SKILLS_LIST:
            is_trig = False
            if s["trigger_type"]=="startswith": is_trig=any(prompt_low.startswith(t) for t in s["triggers"])
            else: is_trig=any(t in prompt_low for t in s["triggers"])
            if is_trig:
                print(f"Skill '{s['name']}' ativada.")
                resp = s["handle"](prompt_low, user_prompt)
                if resp: break
        
        if resp is None:
            if speak_response: play_tts(random.choice(["Deixa ver...", "Um momento..."]))
            resp = process_with_ollama(prompt=user_prompt)
            
        if isinstance(resp, dict) and resp.get("stop_processing"): return resp.get("response", "")
        if speak_response: play_tts(resp)
        return resp
    except Exception as e: return f"Erro crítico: {e}"

def process_user_query():
    try:
        text = transcribe_audio(record_audio())
        print(f"User: {text}")
        if text: route_and_respond(text)
    except: pass

# --- API Server ---
app = Flask(__name__)

@app.route("/comando", methods=['POST'])
def api_command():
    d = request.json; p = d.get('prompt')
    if not p: return jsonify({"status":"err"}), 400
    if p.lower().startswith("diz "): play_tts(p[4:].strip()); return jsonify({"status":"ok"})
    return jsonify({"status":"ok", "response": route_and_respond(p, False)})

@app.route("/device_status")
def api_status():
    nick = request.args.get('nickname')
    
    for s in SKILLS_LIST:
        if s['get_status']:
            # --- PROTEÇÃO CONTRA FUGA DE GÁS ---
            # Se for a skill do Shelly Gas, SÓ responde se o nome tiver "gás".
            # Isto impede que o valor do gás apareça na Sala/Quarto.
            if s["name"] == "skill_shellygas" and "gás" not in nick.lower():
                continue 

            try:
                res = s['get_status'](nick)
                if res and res.get('state') != 'unreachable': return jsonify(res)
            except: pass
            
    return jsonify({"state": "unreachable"})

@app.route("/device_action", methods=['POST'])
def api_action():
    d = request.json
    return jsonify({"status":"ok", "response": route_and_respond(f"{d.get('action')} o {d.get('device')}", False)})

@app.route("/get_devices")
def api_devices():
    toggles = []; status = []
    
    # Lógica Estrita: Lê apenas do config.py
    if hasattr(config, 'TUYA_DEVICES'):
        for n in config.TUYA_DEVICES:
            if any(x in n.lower() for x in ['sensor','temperatura','humidade']): status.append(n)
            else: toggles.append(n)
    if hasattr(config, 'MIIO_DEVICES'):
        for n in config.MIIO_DEVICES: toggles.append(n)
    if hasattr(config, 'CLOOGY_DEVICES'):
        for n in config.CLOOGY_DEVICES:
            if 'casa' in n.lower(): status.append(n)
            else: toggles.append(n)
    if hasattr(config, 'SHELLY_GAS_URL') and config.SHELLY_GAS_URL: status.append("Sensor de Gás")
    
    return jsonify({"status":"ok", "devices": {"toggles": toggles, "status": status}})

@app.route("/help", methods=['GET'])
def get_help():
    try:
        commands = {}
        commands["diz"] = "TTS. Ex: diz olá"
        for skill in SKILLS_LIST: commands[skill["name"].replace("skill_", "")] = "Comando ativo"
        return jsonify({"status": "ok", "commands": commands})
    except: return jsonify({"status": "erro"}), 500

@app.route("/")
def ui():
    return """<!DOCTYPE html><html lang="pt"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Phantasma UI</title><style>
    :root{--bg:#121212;--chat:#1e1e1e;--usr:#2d2d2d;--ia:#005a9e;--txt:#e0e0e0}
    body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--txt);display:flex;flex-direction:column;height:100vh;margin:0;overflow:hidden}
    
    #head{display:flex;align-items:center;background:#181818;border-bottom:1px solid #333;height:85px;flex-shrink:0}
    #brand{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:0 15px;min-width:70px;height:100%;border-right:1px solid #333;background:#151515;cursor:pointer;user-select:none;z-index:10}
    #brand-logo{font-size:1.8rem;animation:float 3s ease-in-out infinite}
    #brand-name{font-size:0.7rem;font-weight:bold;color:#666;margin-top:2px;letter-spacing:1px}
    #bar{flex:1;display:flex;align-items:center;overflow-x:auto;white-space:nowrap;height:100%;padding-left:10px;gap:10px}
    
    /* WIDGETS */
    .dev,.sens{display:inline-flex;flex-direction:column;align-items:center;justify-content:center;background:#222;padding:4px;border-radius:8px;min-width:60px;transition:opacity 0.3s;margin-top:5px;position:relative}
    .sens{background:#252525;border:1px solid #333;height:52px}
    .dev.active .ico{filter:grayscale(0%)}
    .ico{font-size:1.2rem;margin-bottom:2px;filter:grayscale(100%);transition:filter 0.3s}
    .lbl,.slbl{font-size:0.65rem;color:#aaa;max-width:65px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}
    .sdat{font-size:0.75rem;color:#4db6ac;font-weight:bold}
    
    /* TOOLTIP */
    .dev:hover::after,.sens:hover::after{content:attr(title);position:absolute;top:100%;left:50%;transform:translateX(-50%);background:#000;color:#fff;padding:4px 8px;border-radius:4px;font-size:12px;white-space:nowrap;z-index:100;pointer-events:none;margin-top:5px;border:1px solid #333}

    /* SWITCH */
    .sw{position:relative;display:inline-block;width:36px;height:20px}
    .sw input{opacity:0;width:0;height:0}
    .sl{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background-color:#444;transition:.4s;border-radius:34px}
    .sl:before{position:absolute;content:"";height:14px;width:14px;left:3px;bottom:3px;background-color:white;transition:.4s;border-radius:50%}
    input:checked+.sl{background-color:var(--ia)}
    input:checked+.sl:before{transform:translateX(16px)}
    
    /* CHAT */
    #main{flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative}
    #log{flex:1;padding:15px;overflow-y:auto;display:flex;flex-direction:column;gap:15px;scroll-behavior:smooth}
    .row{display:flex;width:100%;align-items:flex-end}
    .row.usr{justify-content:flex-end}
    .av{font-size:1.5rem;margin-right:8px;margin-bottom:5px;animation:float 4s ease-in-out infinite}
    .msg{max-width:80%;padding:10px 14px;border-radius:18px;line-height:1.4;font-size:1rem;word-wrap:break-word}
    .msg.usr{background:var(--usr);color:#fff;border-bottom-right-radius:2px}
    .msg.ia{background:var(--chat);color:#ddd;border-bottom-left-radius:2px;border:1px solid #333}
    
    #box{padding:10px;background:#181818;border-top:1px solid #333;display:flex;gap:10px}
    #in{flex:1;background:#2a2a2a;color:#fff;border:none;padding:12px;border-radius:25px;outline:none;font-size:16px}
    #btn{background:var(--ia);color:white;border:none;padding:0 20px;border-radius:25px;font-weight:bold;cursor:pointer}
    
    #egg{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:99;display:flex;align-items:center;justify-content:center;visibility:hidden}
    #big{font-size:15rem;opacity:0;transform:scale(0.5);transition:all 0.3s}
    .boo #egg{visibility:visible} .boo #big{opacity:1;transform:scale(1.2)}
    @keyframes float{0%{transform:translateY(0px)}50%{transform:translateY(-5px)}100%{transform:translateY(0px)}}
    </style></head><body>
    <div id="egg"><div id="big">👻</div></div>
    <div id="head"><div id="brand" onclick="document.body.classList.add('boo');setTimeout(()=>document.body.classList.remove('boo'),1200)"><div id="brand-logo">👻</div><div id="brand-name">pHantasma</div></div><div id="bar"></div></div>
    <div id="main"><div id="log"></div><div id="box"><input id="in" placeholder="..."><button id="btn">></button></div></div>
    <script>
    const log=document.getElementById('log'),bar=document.getElementById('bar'),devs=new Set();
    function add(t,s){const r=document.createElement('div');r.className=`row ${s}`;if(s=='ia')r.innerHTML='<div class="av">👻</div>';
    const m=document.createElement('div');m.className=`msg ${s}`;m.innerText=t;r.appendChild(m);log.appendChild(r);log.scrollTop=log.scrollHeight}
    async function cmd(){const i=document.getElementById('in'),v=i.value.trim();if(!v)return;add(v,'usr');i.value='';try{const r=await fetch('/comando',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:v})});const d=await r.json();if(d.response)add(d.response,'ia')}catch{add('Erro','ia')}}
    document.getElementById('btn').onclick=cmd;document.getElementById('in').onkeypress=e=>{if(e.key=='Enter')cmd()};
    
    // --- EMOJIS CORRETOS ---
    function ico(n){
        n=n.toLowerCase();
        if(n.includes('aspirador')||n.includes('robot'))return'🤖';
        if(n.includes('luz')||n.includes('candeeiro')||n.includes('abajur')||n.includes('lâmpada'))return'💡';
        if(n.includes('exaustor')||n.includes('ventoinha'))return'💨';
        if(n.includes('desumidificador'))return'💧';
        if(n.includes('gás')||n.includes('incêndio')||n.includes('fumo'))return'🔥';
        if(n.includes('tomada')||n.includes('ficha')||n.includes('forno'))return'⚡';
        return'⚡';
    }
    
    function clean(n) { return n.replace(/(sensor|luz|candeeiro|exaustor|desumidificador|alarme|tomada)( de| da| do)?/gi, "").trim().substring(0,12); }

    function w(d,s){
        const e=document.createElement('div');e.id='d-'+d.replace(/[^a-z0-9]/gi,''); e.title=d;
        if(s){e.className='sens';e.innerHTML=`<span class="sdat">...</span><span class="slbl">${clean(d)}</span>`}
        else{e.className='dev';e.innerHTML=`<span class="ico">${ico(d)}</span><label class="sw"><input type="checkbox" disabled><div class="sl"></div></label><span class="lbl">${clean(d)}</span>`;
        e.querySelector('input').onchange=function(){fetch('/device_action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device:d,action:this.checked?'liga':'desligar'})})}}
        bar.appendChild(e);devs.add({n:d,s:s,id:e.id});upd(d,s,e.id)}
    
    async function upd(n,s,id){const el=document.getElementById(id);if(!el)return;try{const r=await fetch(`/device_status?nickname=${encodeURIComponent(n)}`);const d=await r.json();
    if(d.state=='unreachable'){el.style.opacity=0.4;if(s)el.querySelector('.sdat').innerText='?';return}el.style.opacity=1;
    if(s){let t='';const v=el.querySelector('.sdat');
    if(d.power_w!==undefined){t=Math.round(d.power_w)+'W';v.style.color='#ffb74d'}
    else if(d.temperature!==undefined){t=Math.round(d.temperature)+'°';v.style.color='#4db6ac'}
    else if(d.ppm!==undefined){t=d.ppm+' ppm';v.style.color=(d.status!='normal'&&d.status!='unknown')?'#ff5252':'#4db6ac'}
    v.innerText=t||'ON'}
    else{const i=el.querySelector('input');i.disabled=false;i.checked=(d.state=='on');
    if(d.state=='on')el.classList.add('active');else el.classList.remove('active');
    if(d.power_w!==undefined){const l=el.querySelector('.lbl');l.innerText=Math.round(d.power_w)+'W';l.style.color='#ffb74d'}}}catch{}}
    
    function loop(){devs.forEach(d=>upd(d.n,d.s,d.id))}
    fetch('/get_devices').then(r=>r.json()).then(d=>{bar.innerHTML='';d.devices.status.forEach(x=>w(x,true));d.devices.toggles.forEach(x=>w(x,false));add('Nas sombras, aguardo...','ia')});setInterval(loop,5000);
    </script></body></html>"""

def start_api_server(host='0.0.0.0', port=5000):
    logging.getLogger('werkzeug').setLevel(logging.ERROR); app.run(host=host, port=port)

def main():
    pv=None; pa=os.path.dirname(pvporcupine.__file__); vad=webrtcvad.Vad(1)
    try:
        pv=pvporcupine.create(access_key=config.ACCESS_KEY, keyword_paths=['/opt/phantasma/models/ei-fantasma_pt_linux_v3_0_0.ppn'], model_path=f'{pa}/lib/common/porcupine_params_pt.pv', sensitivities=[0.4])
        with sd.InputStream(device=config.ALSA_DEVICE_IN, channels=1, samplerate=pv.sample_rate, dtype='int16', blocksize=pv.frame_length) as st:
            while True:
                c,_=st.read(pv.frame_length)
                if vad.is_speech(c[:480].tobytes(),16000) and pv.process(c.flatten())==0:
                    play_tts(random.choice(["Sim?","Diz."])); process_user_query()
    except KeyboardInterrupt: pass
    finally: 
        if pv: pv.delete()

if __name__=="__main__":
    setup_database(); load_skills(); 
    try: whisper_model=whisper.load_model(config.WHISPER_MODEL,device="cpu"); ollama_client=ollama.Client()
    except: pass
    conversation_history=[{'role':'system','content':config.SYSTEM_PROMPT}]
    threading.Thread(target=start_api_server, daemon=True).start()
    main()
