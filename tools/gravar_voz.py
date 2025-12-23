import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import time
import os
from datetime import datetime

# CONFIGURAÇÕES
OUTPUT_DIR = "meus_samples"
NUM_SAMPLES = 10     # Quantos queres gravar nesta sessão
DURATION = 2.0       # Duração (2.0s é o ideal para wakewords)
FS = 16000           # Sample rate obrigatório

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print(f"\n--- ESTÚDIO PHANTASMA (Modo Timestamp) ---")
    print(f"📂 Pasta: {OUTPUT_DIR}")
    print(f"🎤 Sessão de {NUM_SAMPLES} gravações.")
    print("💡 Os ficheiros terão a hora no nome. Nunca haverá conflitos.")
    
    input("Pressiona ENTER para começar a sessão...")

    for i in range(NUM_SAMPLES):
        # Gera um nome único baseado na hora atual (Ex: fantasma_20231221_213005.wav)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(OUTPUT_DIR, f"fantasma_{timestamp}.wav")

        print(f"\n[{i+1}/{NUM_SAMPLES}] Prepara-te...", end="", flush=True)
        time.sleep(1) 
        print(" GRAVANDO! 🔴")
        
        # Grava áudio
        recording = sd.rec(int(DURATION * FS), samplerate=FS, channels=1, dtype='int16')
        sd.wait()
        
        print(f" ✅ Salvo: {os.path.basename(filename)}")
        wav.write(filename, FS, recording)
        
        # Pequena pausa para garantir que o segundo muda (evita nomes duplicados se for muito rápido)
        time.sleep(1.1) 

    print(f"\n✨ Sessão concluída!")
    print("👉 Corre o 'compactar_negativos.py' (se tiveres novos ruídos) e depois o 'treinar.py'.")

if __name__ == "__main__":
    main()
