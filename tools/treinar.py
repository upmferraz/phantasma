import os
import glob
import wave
import numpy as np
import requests
import openwakeword
import onnxruntime as ort
from sklearn.linear_model import LogisticRegression
from skl2onnx import to_onnx
from skl2onnx.common.data_types import FloatTensorType
from tqdm import tqdm

# --- CONFIGURAÇÃO ---
NOME_MODELO = "hey_fantasma"
PASTA_POSITIVOS = "meus_samples_limpos"  # A tua pasta nova limpa
PASTA_NEGATIVOS = "meus_negativos"     
PASTA_MODELOS = "meus_modelos_finais"

# Link atualizado (davidscripka) e User-Agent para tentar evitar erro 401
URL_NEGATIVOS = "https://huggingface.co/davidscripka/openwakeword/resolve/main/validation_set_embeddings.npy"
STACK_SIZE = 16 

def get_melspectrogram_model_path():
    base_path = os.path.dirname(openwakeword.__file__)
    model_path = os.path.join(base_path, "resources", "models", "melspectrogram.onnx")
    if not os.path.exists(model_path): raise FileNotFoundError(f"ONNX missing: {model_path}")
    return model_path

def read_wav_manually(file_path):
    try:
        with wave.open(file_path, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            return np.frombuffer(frames, dtype=np.int16)
    except: return None

def process_wav_to_features(session, audio_data, input_name):
    try:
        input_tensor = audio_data.astype(np.float32) / 32768.0
        input_tensor = input_tensor[None, :] 
        outputs = session.run(None, {input_name: input_tensor})
        return outputs[0].squeeze()
    except: return None

def window_features(features, stack_size=16):
    if features is None or features.ndim != 2: return []
    if features.shape[0] < stack_size: return []
    windows = []
    for i in range(features.shape[0] - stack_size + 1):
        block = features[i : i + stack_size]
        windows.append(block.flatten())
    return windows

def download_generic_negatives():
    neg_file = "negatives.npy"
    if os.path.exists(neg_file) and os.path.getsize(neg_file) > 1024:
        return neg_file

    print("⬇️ A tentar baixar dataset genérico (correção de link)...")
    try:
        # User-Agent finge ser um browser para evitar bloqueio 401
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(URL_NEGATIVOS, headers=headers, stream=True, timeout=15)
        
        if r.status_code == 200:
            with open(neg_file, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("✅ Download com sucesso!")
            return neg_file
        else:
            print(f"⚠️ Falha no download ({r.status_code}). Vamos usar apenas os teus negativos.")
            return None
    except Exception as e:
        print(f"⚠️ Erro de rede: {e}. A usar negativos locais.")
        return None

def main():
    if not os.path.exists(PASTA_POSITIVOS):
        print(f"❌ ERRO: Pasta '{PASTA_POSITIVOS}' não existe.")
        return

    os.makedirs(PASTA_MODELOS, exist_ok=True)
    
    print("🧠 A carregar motor de features...")
    model_path = get_melspectrogram_model_path()
    session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    input_name = session.get_inputs()[0].name
    
    # --- 1. POSITIVOS ---
    print(f"🎤 A processar POSITIVOS de '{PASTA_POSITIVOS}'...")
    wav_files = glob.glob(os.path.join(PASTA_POSITIVOS, "*.wav"))
    X_pos_list = []
    
    for wav_path in tqdm(wav_files):
        audio = read_wav_manually(wav_path)
        if audio is not None and len(audio) > 1600:
            feat = process_wav_to_features(session, audio, input_name)
            X_pos_list.extend(window_features(feat, STACK_SIZE))
            
    if not X_pos_list: 
        print("⛔ Falha: Sem dados positivos.")
        return
    
    X_pos = np.vstack(X_pos_list)
    y_pos = np.ones(X_pos.shape[0])

    # --- 2. NEGATIVOS ---
    X_neg_list = []
    
    # A) LOCAIS (Crucial!)
    if os.path.exists(PASTA_NEGATIVOS):
        neg_files = glob.glob(os.path.join(PASTA_NEGATIVOS, "*.wav"))
        print(f"🔇 A processar {len(neg_files)} ficheiros de NEGATIVOS locais...")
        for wav_path in tqdm(neg_files):
            audio = read_wav_manually(wav_path)
            if audio is not None and len(audio) > 1600:
                feat = process_wav_to_features(session, audio, input_name)
                windows = window_features(feat, STACK_SIZE)
                X_neg_list.extend(windows)

    # B) GENÉRICOS (Opcional mas recomendado)
    neg_npy = download_generic_negatives()
    if neg_npy and os.path.exists(neg_npy):
        try:
            print("📦 A misturar negativos genéricos...")
            data_neg = np.load(neg_npy, allow_pickle=True).item()
            X_neg_raw = data_neg['X']
            
            # Pega numa quantidade segura para não abafar os teus dados
            # Se tiveres poucos locais, usamos mais genéricos
            qtd_locais = len(X_neg_list)
            qtd_genericos = max(2000, qtd_locais * 2) 
            qtd_genericos = min(len(X_neg_raw), qtd_genericos)

            idx = np.random.choice(len(X_neg_raw), qtd_genericos, replace=False)
            X_neg_list.extend(list(X_neg_raw[idx]))
        except: pass

    if not X_neg_list:
        print("❌ ERRO FATAL: Sem negativos nenhuns.")
        print("👉 Grava barulho de TV/Música com o 'grava_negativos.py'!")
        return

    X_neg = np.vstack(X_neg_list)
    y_neg = np.zeros(X_neg.shape[0])

    # --- 3. TREINO ---
    X = np.vstack((X_pos, X_neg))
    y = np.concatenate((y_pos, y_neg))
    
    print(f"⚔️  A treinar: {len(X_pos)} Positivos vs {len(X_neg)} Negativos")
    
    # Aumentei o max_iter para 5000 para acabar com o aviso de convergência
    clf = LogisticRegression(class_weight='balanced', max_iter=5000, C=0.1)
    clf.fit(X, y)
    
    score = clf.score(X, y)
    print(f"🎯 Score Final: {score:.4f}")
    
    if score == 1.0 and len(X_neg) < 1000:
        print("⚠️ PERIGO: Score 1.0 com poucos negativos = Overfitting garantido.")
    elif score > 0.999:
        print("ℹ️ Score muito alto. Se falhar, grava mais ruído de fundo.")

    # --- 4. EXPORTAR ---
    initial_type = [('input_1', FloatTensorType([None, X.shape[1]]))]
    onx = to_onnx(clf, X[:1].astype(np.float32), initial_types=initial_type, options={'zipmap': False})
    
    out_path = os.path.join(PASTA_MODELOS, f"{NOME_MODELO}.onnx")
    with open(out_path, "wb") as f: f.write(onx.SerializeToString())
    print(f"✅ Modelo salvo: {out_path}")

if __name__ == "__main__":
    main()
