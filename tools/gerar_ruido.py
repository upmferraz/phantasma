import numpy as np
import scipy.io.wavfile as wav
import os
import random

# CONFIGURAÇÕES
OUTPUT_DIR = "meus_negativos"
FS = 16000
DURATION = 5  # Segundos por clip
QTD = 20      # Quantidade de cada tipo

def save_wav(name, data):
    # Normalizar para 16-bit PCM
    data = data / np.max(np.abs(data)) * 32767
    wav.write(os.path.join(OUTPUT_DIR, name), FS, data.astype(np.int16))

def gerar_white_noise():
    """Ruído tipo TV sem sinal (bom para calibração)"""
    return np.random.normal(0, 1, FS * DURATION)

def gerar_pink_noise():
    """Ruído mais grave (tipo ventoinha ou chuva)"""
    # Aproximação simples de ruído rosa (1/f)
    white = np.random.normal(0, 1, FS * DURATION)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1, -2.494956002, 2.017265875, -0.522189400]
    from scipy.signal import lfilter
    pink = lfilter(b, a, white)
    return pink

def gerar_clicks():
    """Simula estalidos de microfone ou teclado"""
    audio = np.zeros(FS * DURATION)
    num_clicks = random.randint(5, 20)
    for _ in range(num_clicks):
        idx = random.randint(0, len(audio)-100)
        audio[idx:idx+50] = np.random.normal(0, 1, 50) # Burst curto
    return audio

def main():
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    
    print(f"⚡ A gerar ruídos sintéticos em '{OUTPUT_DIR}'...")

    # 1. White Noise (Estática)
    for i in range(QTD):
        save_wav(f"syn_white_{i}.wav", gerar_white_noise())
        
    # 2. Pink Noise (Ambiente grave)
    for i in range(QTD):
        save_wav(f"syn_pink_{i}.wav", gerar_pink_noise())

    # 3. Estalidos (Clicks)
    for i in range(QTD):
        save_wav(f"syn_clicks_{i}.wav", gerar_clicks())

    print(f"✅ Gerados {QTD*3} ficheiros de ruído extra.")
    print("Agora tens: As tuas gravações + Ruído Matemático + (Se baixaste) o Dataset Genérico.")

if __name__ == "__main__":
    main()
