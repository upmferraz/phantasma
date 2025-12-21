import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import time
import os
import random

# --- CONFIGURAÇÕES ---
OUTPUT_DIR = "meus_negativos"
FS = 16000  # Obrigatório ser 16kHz
CHANNELS = 1

def garantir_pasta():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

def gravar_clip(nome_base, duracao, descricao):
    print(f"\n🎙️  A GRAVAR: {descricao}")
    print(f"⏳ {duracao} segundos... (Faz barulho!)")
    
    # Grava
    recording = sd.rec(int(duracao * FS), samplerate=FS, channels=CHANNELS, dtype='int16')
    
    # Barra de progresso visual
    for i in range(duracao):
        time.sleep(1)
        print("." * (i % 3 + 1), end="\r")
    
    sd.wait()
    
    # Gera nome único para não substituir anteriores
    timestamp = int(time.time())
    nome_arquivo = f"{nome_base}_{timestamp}.wav"
    caminho = os.path.join(OUTPUT_DIR, nome_arquivo)
    
    wav.write(caminho, FS, recording)
    print(f"✅ Guardado: {nome_arquivo}")

def modo_cenarios():
    print("\n--- MODO 1: CENÁRIOS GUIADOS ---")
    print("Vou pedir-te para criares ambientes específicos.")
    input("ENTER para começar...")

    gravar_clip("neg_tv", 15, "LIGA UMA TV OU RÁDIO (Som de fundo alto)")
    input("ENTER para o próximo...")
    
    gravar_clip("neg_teclado", 10, "TECLAR E RATO (Usa o PC vigorosamente)")
    input("ENTER para o próximo...")
    
    gravar_clip("neg_conversa", 15, "FALA SOZINHO (Lê isto: 'O tempo hoje está bom mas o código não compila')")
    input("ENTER para o próximo...")
    
    gravar_clip("neg_ambiente", 10, "SILÊNCIO TOTAL (Só ventoinhas e ruído da casa)")
    
    print("\nCenários concluídos!")

def modo_vigilante():
    print("\n--- MODO 2: VIGILANTE (MINERAÇÃO DE DADOS) ---")
    print("Vou gravar continuamente enquanto fazes a tua vida.")
    print("Sugestões: Vê um vídeo no YouTube, tosse, arrasta a cadeira, bate palmas.")
    print("Vou gerar 10 clips de 5 segundos aleatórios.")
    
    qtd = input("Quantos clips de 5s queres gerar? (Recomendado: 20): ")
    try:
        qtd = int(qtd)
    except:
        qtd = 20

    print(f"\n🚀 A começar em 3 segundos... FAZ BARULHO VARIADO!")
    time.sleep(3)

    for i in range(qtd):
        print(f"\n[{i+1}/{qtd}] A capturar som ambiente...")
        # Grava 5 segundos
        recording = sd.rec(int(5 * FS), samplerate=FS, channels=CHANNELS, dtype='int16')
        sd.wait()
        
        # Salva
        nome = f"neg_random_{int(time.time())}_{i}.wav"
        wav.write(os.path.join(OUTPUT_DIR, nome), FS, recording)
        
        # Pausa aleatória entre gravações para apanhar sons diferentes
        pausa = random.uniform(0.5, 2.0)
        print(f"   (Pausa de {pausa:.1f}s - Muda de atividade/som...)")
        time.sleep(pausa)

def main():
    garantir_pasta()
    print("=== GERADOR DE NEGATIVOS PHANTASMA ===")
    print("Precisamos de ensinar ao assistente o que NÃO é a voz dele.")
    print("1. Modo Cenários (4 gravações específicas)")
    print("2. Modo Vigilante (Gravar muita coisa aleatória rápido)")
    
    op = input("\nEscolhe (1 ou 2): ")
    
    if op == "1":
        modo_cenarios()
    elif op == "2":
        modo_vigilante()
    else:
        print("Opção inválida.")

    print(f"\n🏁 Feito! Verifica a pasta '{OUTPUT_DIR}'.")
    print("Agora corre o 'treinar.py' novamente.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
