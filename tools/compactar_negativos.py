import os
import glob
import wave
import numpy as np
import openwakeword
import onnxruntime as ort
from tqdm import tqdm

# --- CONFIGURAÇÃO ---
PASTA_NEGATIVOS = "meus_negativos"
OUTPUT_FILE = "negativos_local.npy"
STACK_SIZE = 16 

def get_melspectrogram_model():
    base_path = os.path.dirname(openwakeword.__file__)
    model_path = os.path.join(base_path, "resources", "models", "melspectrogram.onnx")
    sess = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    return sess

def audio_to_mels(audio_data, sess):
    audio_data = audio_data.astype(np.float32) / 32768.0
    mel_output = sess.run(None, {'input': audio_data[None, :]})[0]
    return mel_output.squeeze()

def main():
    if not os.path.exists(PASTA_NEGATIVOS):
        print(f"❌ Pasta '{PASTA_NEGATIVOS}' não encontrada.")
        return

    # 1. Verificar ficheiro existente (A Base de Dados Atual)
    existing_data = None
    if os.path.exists(OUTPUT_FILE):
        print(f"📚 Encontrado '{OUTPUT_FILE}' existente.")
        try:
            existing_data = np.load(OUTPUT_FILE)
            print(f"   -> Contém {existing_data.shape[0]} amostras antigas.")
        except:
            print("   -> Erro ao ler ficheiro antigo. Vamos começar do zero.")

    # 2. Procurar NOVOS ficheiros
    wav_files = glob.glob(os.path.join(PASTA_NEGATIVOS, "*.wav"))
    
    if len(wav_files) == 0:
        print("🤷 Nenhum ficheiro WAV novo para processar.")
        return

    print(f"🆕 Encontrados {len(wav_files)} novos WAVs para adicionar.")
    
    # 3. Processar
    print("🧠 A carregar modelo e processar áudio...")
    sess = get_melspectrogram_model()
    new_features = []

    for wav_file in tqdm(wav_files):
        try:
            with wave.open(wav_file, 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                audio = np.frombuffer(frames, dtype=np.int16)
                if len(audio) < 16000: continue 

                mels = audio_to_mels(audio, sess)
                
                for i in range(0, len(mels) - STACK_SIZE, 4): 
                    window = mels[i : i + STACK_SIZE]
                    if window.shape[0] == STACK_SIZE:
                        new_features.append(window.flatten())
        except Exception as e:
            print(f"⚠️ Erro em {wav_file}: {e}")

    # 4. Juntar Tudo (Merge)
    if new_features:
        new_array = np.vstack(new_features).astype(np.float32)
        print(f"✅ Processados {new_array.shape[0]} novos fragmentos.")

        if existing_data is not None:
            final_array = np.vstack((existing_data, new_array))
            print("🔗 A unir Antigos + Novos...")
        else:
            final_array = new_array
        
        # 5. Guardar
        np.save(OUTPUT_FILE, final_array)
        print(f"💾 Guardado '{OUTPUT_FILE}' com um total de {final_array.shape[0]} amostras.")
        
        # 6. Limpeza Opcional
        resp = input("🗑️  Queres APAGAR os ficheiros .wav processados para libertar espaço? (s/N): ")
        if resp.lower() == 's':
            print("🧹 A limpar ficheiros WAV...")
            for f in wav_files:
                os.remove(f)
            print("✨ Pasta limpa!")
        else:
            print("🆗 Ficheiros WAV mantidos.")

    else:
        print("❌ Não foi possível extrair dados úteis dos novos ficheiros.")

if __name__ == "__main__":
    main()
