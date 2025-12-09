import subprocess
import glob
import random
import os
import time
import numpy as np
import sounddevice as sd
import webrtcvad
import collections
import config
import hashlib 

# Diretório para guardar os ficheiros de áudio gerados
TTS_CACHE_DIR = "/opt/phantasma/cache/tts"

def clean_old_cache(days=30):
    """
    Remove ficheiros da cache que sejam mais antigos que 'days'.
    """
    if not os.path.exists(TTS_CACHE_DIR):
        return

    print(f"Manutenção: A verificar limpeza de cache TTS (> {days} dias)...")
    now = time.time()
    cutoff = days * 86400
    count = 0

    try:
        for f in os.listdir(TTS_CACHE_DIR):
            f_path = os.path.join(TTS_CACHE_DIR, f)
            if os.path.isfile(f_path):
                t_mod = os.stat(f_path).st_mtime
                if now - t_mod > cutoff:
                    os.remove(f_path)
                    count += 1
        if count > 0:
            print(f"Manutenção: {count} ficheiros de áudio antigos removidos.")
    except Exception as e:
        print(f"ERRO ao limpar cache: {e}")

def play_tts(text, use_cache=True):
    """ 
    Converte texto em voz.
    - use_cache=True: Verifica/Gera ficheiro no disco (Ideal para frases fixas).
    - use_cache=False: Pipeline direto em memória (Ideal para respostas do LLM).
    """
    if not text: return

    text_cleaned = text.replace('**', '').replace('*', '').replace('#', '').replace('`', '').strip()
    print(f"IA: {text_cleaned}")

    # --- LÓGICA 1: COM CACHE (Disco) ---
    if use_cache:
        # 1. Preparar Diretório
        if not os.path.exists(TTS_CACHE_DIR):
            try:
                os.makedirs(TTS_CACHE_DIR, exist_ok=True)
                os.chmod(TTS_CACHE_DIR, 0o777)
            except: pass

        # 2. Hash MD5
        file_hash = hashlib.md5(text_cleaned.encode('utf-8')).hexdigest()
        cache_path = os.path.join(TTS_CACHE_DIR, f"{file_hash}.wav")

        # 3. Cache HIT
        if os.path.exists(cache_path):
            try:
                subprocess.run(
                    ['aplay', '-D', config.ALSA_DEVICE_OUT, '-q', cache_path],
                    check=False
                )
                return
            except Exception as e:
                print(f"Erro ao tocar cache: {e}")

        # 4. Cache MISS (Gerar para disco e tocar)
        try:
            piper_proc = subprocess.Popen(
                ['piper', '--model', config.TTS_MODEL_PATH, '--output-raw'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE
            )
            
            # Sox lê do Piper e escreve no ficheiro WAV
            sox_cmd = [
                'sox',
                '-t', 'raw', '-r', '22050', '-e', 'signed-integer', '-b', '16', '-c', '1', '-',
                cache_path,
                'flanger', '1', '1', '5', '50', '1', 'sin', 'tempo', '0.9'
            ]
            
            sox_proc = subprocess.Popen(
                sox_cmd,
                stdin=piper_proc.stdout, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE
            )
            
            piper_proc.stdin.write(text_cleaned.encode('utf-8'))
            piper_proc.stdin.close()
            sox_proc.wait()
            
            if os.path.exists(cache_path):
                subprocess.run(
                    ['aplay', '-D', config.ALSA_DEVICE_OUT, '-q', cache_path],
                    check=False
                )

        except Exception as e:
            print(f"Erro no pipeline TTS (Cache): {e}")

    # --- LÓGICA 2: SEM CACHE (Streaming/Pipes) ---
    else:
        try:
            # Piper -> stdout
            piper_proc = subprocess.Popen(
                ['piper', '--model', config.TTS_MODEL_PATH, '--output-raw'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE
            )

            # Sox -> lê stdin (do piper), aplica efeitos -> escreve stdout
            sox_proc = subprocess.Popen(
                [
                    'sox',
                    '-t', 'raw', '-r', '22050', '-e', 'signed-integer', '-b', '16', '-c', '1', '-',
                    '-t', 'wav', '-', # Saída WAV para o pipe
                    'flanger', '1', '1', '5', '50', '1', 'sin', 'tempo', '0.9'
                ],
                stdin=piper_proc.stdout,
                stdout=subprocess.PIPE
            )

            # Aplay -> lê stdin (do sox) e toca
            aplay_proc = subprocess.Popen(
                ['aplay', '-D', config.ALSA_DEVICE_OUT, '-q'],
                stdin=sox_proc.stdout
            )

            # Envia o texto e inicia a cascata
            piper_proc.stdin.write(text_cleaned.encode('utf-8'))
            piper_proc.stdin.close()
            
            # Aguarda o fim da reprodução
            aplay_proc.wait()
            sox_proc.wait()

        except Exception as e:
            print(f"Erro no pipeline TTS (Stream): {e}")


def play_random_music_snippet():
    """ Encontra um MP3 aleatório e toca um snippet de 1 segundo (e espera). """
    try:
        music_dir = '/home/media/music'
        mp3_files = glob.glob(os.path.join(music_dir, '**/*.mp3'), recursive=True)
        if not mp3_files:
            return
        random_song = random.choice(mp3_files)
        print(f"A tocar snippet de: {random_song}")
        mp3_proc = subprocess.Popen(
            ['mpg123', '-q', '-n', '45', random_song],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        mp3_proc.wait()
    except: pass

def play_random_song_full():
    """ Encontra um MP3 aleatório e toca a música inteira (em background). """
    try:
        music_dir = '/home/media/music'
        mp3_files = glob.glob(os.path.join(music_dir, '**/*.mp3'), recursive=True)
        if not mp3_files:
            print("AVISO (Música): Nenhum ficheiro MP3 encontrado.")
            return False
        random_song = random.choice(mp3_files)
        print(f"A tocar música: {random_song}")
        subprocess.Popen(
            ['mpg123', '-q', random_song],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except: return False

def record_audio():
    """ 
    Grava áudio dinamicamente usando VAD (Voice Activity Detection).
    Para de gravar automaticamente quando deteta silêncio.
    """
    print("A ouvir...")
    
    # Configurações do VAD
    vad = webrtcvad.Vad(2) # Nível de agressividade (0-3). 2 é equilibrado.
    frame_duration_ms = 30 # Duração do frame em ms (VAD aceita 10, 20 ou 30)
    
    # Cálculos de buffer
    samples_per_frame = int(config.MIC_SAMPLERATE * frame_duration_ms / 1000)
    
    # Limites
    silence_threshold_seconds = 1.5  # Para de gravar após 1.5s de silêncio
    max_duration_seconds = 10.0      # Segurança
    
    # Buffers
    frames = []
    silence_counter = 0
    speech_detected = False
    chunks_per_second = 1000 // frame_duration_ms
    silence_limit_chunks = int(silence_threshold_seconds * chunks_per_second)
    max_chunks = int(max_duration_seconds * chunks_per_second)

    try:
        with sd.InputStream(samplerate=config.MIC_SAMPLERATE, channels=1, dtype='int16') as stream:
            for _ in range(max_chunks):
                # Lê um chunk de áudio
                audio_chunk, overflowed = stream.read(samples_per_frame)
                
                if overflowed:
                    # Ignora overflow silenciosamente para não spammar logs
                    pass

                # Converte para bytes para o VAD
                audio_bytes = audio_chunk.tobytes()
                
                # Verifica se é voz
                is_speech = vad.is_speech(audio_bytes, config.MIC_SAMPLERATE)

                # Lógica de Controlo
                if is_speech:
                    silence_counter = 0
                    speech_detected = True
                else:
                    silence_counter += 1

                # Guarda o frame (convertendo para float32 para o Whisper mais tarde)
                frames.append(audio_chunk.flatten().astype(np.float32) / 32768.0)

                # Condição de paragem: Falou e depois calou-se
                if speech_detected and silence_counter > silence_limit_chunks:
                    print("Fim de fala detetado.")
                    break
        
        print("Gravação terminada.")
        
        # Se não detetou fala nenhuma (apenas ruído de fundo ou silêncio), retorna vazio
        if not speech_detected:
            return np.array([], dtype='float32')

        return np.concatenate(frames)

    except Exception as e:
        print(f"ERRO crítico na gravação VAD: {e}\n{traceback.format_exc()}")
        return np.array([], dtype='float32')
