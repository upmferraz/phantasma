import os
import glob
import numpy as np
import scipy.io.wavfile as wav

# CONFIGURAÇÕES
INPUT_DIR = "meus_samples"
OUTPUT_DIR = "meus_samples_limpos"

# Agressividade (0.1 = 10% do volume máximo, 0.2 = 20%)
# Se continuar a não cortar, sobe para 0.2 ou 0.25
CUT_THRESHOLD_RATIO = 0.15 
PADDING_SEC = 0.1  # Deixa 0.1s de margem antes e depois da fala

def trim_by_peak(audio, fs):
    # Converter para float e normalizar valores absolutos
    abs_audio = np.abs(audio.astype(float))
    max_val = np.max(abs_audio)
    
    # Se o áudio for silêncio absoluto ou muito baixo, ignorar
    if max_val < 100: return audio 

    # Define o nível de corte baseado no PICO deste ficheiro específico
    threshold = max_val * CUT_THRESHOLD_RATIO
    
    # Cria uma máscara booleana: Onde é que o som é mais alto que X?
    mask = abs_audio > threshold
    
    # Se nada passar no filtro (ex: ficheiro vazio), devolve o original
    if not np.any(mask): 
        print("⚠️  Aviso: Áudio muito baixo ou ruído constante.")
        return audio

    # Encontra o primeiro e último índice que supera o limite
    start_idx = np.argmax(mask)
    end_idx = len(mask) - np.argmax(mask[::-1])
    
    # Adiciona margem (padding) para não cortar o "H" ou o "a" final
    padding_samples = int(PADDING_SEC * fs)
    start_idx = max(0, start_idx - padding_samples)
    end_idx = min(len(audio), end_idx + padding_samples)
    
    return audio[start_idx:end_idx]

def main():
    if not os.path.exists(INPUT_DIR):
        print(f"❌ Pasta '{INPUT_DIR}' não encontrada.")
        return

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    files = glob.glob(os.path.join(INPUT_DIR, "*.wav"))
    print(f"🔪 A cortar silêncio (Método de Pico {CUT_THRESHOLD_RATIO*100}%)...")

    count = 0
    for f in files:
        try:
            fs, data = wav.read(f)
            if len(data) == 0: continue
            
            # Executa o corte
            trimmed_data = trim_by_peak(data, fs)
            
            # Só guarda se sobrou áudio suficiente (0.2s mínimo)
            if len(trimmed_data) > (0.2 * fs): 
                out_name = os.path.join(OUTPUT_DIR, os.path.basename(f))
                wav.write(out_name, fs, trimmed_data)
                count += 1
                
                orig_dur = len(data)/fs
                new_dur = len(trimmed_data)/fs
                
                # Feedback visual
                diff = orig_dur - new_dur
                if diff > 0.1:
                    print(f"✂️  {os.path.basename(f)}: {orig_dur:.2f}s -> {new_dur:.2f}s (Cortado)")
                else:
                    print(f"🔹 {os.path.basename(f)}: Sem alteração significativa.")
            else:
                print(f"🗑️  {os.path.basename(f)}: Ficou vazio após corte (Removido)")
                
        except Exception as e:
            print(f"❌ Erro em {f}: {e}")
    
    print(f"\n✅ Concluído! {count} ficheiros processados em '{OUTPUT_DIR}'.")

if __name__ == "__main__":
    main()
