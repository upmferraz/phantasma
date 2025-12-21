import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import time
import os

# CONFIGURAÇÕES
OUTPUT_DIR = "meus_samples"
NUM_SAMPLES = 20
DURATION = 2.5 # Segundos por gravação
FS = 16000 # Sample rate (obrigatório ser 16k para o openWakeWord)

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print(f"\n--- ESTÚDIO DE GRAVAÇÃO PHANTASMA ---")
    print(f"Vamos gravar {NUM_SAMPLES} exemplos da tua voz.")
    print(f"Diz 'Hey Fantasma' (ou só 'Fantasma') de forma natural.")
    print(f"Tenta variar um pouco: diz rápido, devagar, normal.")
    input("Pressiona ENTER para começar...")

    for i in range(NUM_SAMPLES):
        print(f"\n[{i+1}/{NUM_SAMPLES}] Prepara-te...", end="", flush=True)
        time.sleep(1)
        print(" GRAVANDO! (Fala agora) 🔴")
        
        # Grava áudio
        recording = sd.rec(int(DURATION * FS), samplerate=FS, channels=1, dtype='int16')
        sd.wait()  # Espera terminar
        
        print(" Feito.")
        
        # Salva o ficheiro
        filename = os.path.join(OUTPUT_DIR, f"fantasma_sample_{i}.wav")
        wav.write(filename, FS, recording)
        time.sleep(0.5)

    print(f"\n\nSUCESSO! ✅")
    print(f"Os ficheiros estão na pasta '{OUTPUT_DIR}'.")
    print("Agora faz upload desta pasta (ou dos ficheiros wav) para o Google Colab.")

if __name__ == "__main__":
    main()
