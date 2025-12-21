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
PASTA_POSITIVOS = "meus_samples_limpos"   # Onde estão os teus "Hey Fantasma" gravados
PASTA_NEGATIVOS = "meus_negativos"      # Onde estão os ruídos de fundo (opcional se usares o .npy)
OUTPUT_DIR = "meus_modelos_finais"

# Link do dataset gigante de validação (útil para robustez extra)
URL_GENERICOS = "https://huggingface.co/davidscripka/openwakeword/resolve/main/validation_set_embeddings.npy"

# Parâmetros Técnicos (Não mexer a não ser que saibas o que fazes)
STACK_SIZE = 16  # Quantos frames de áudio o modelo vê de uma vez (aprox 1.2s)

# --- 1. PREPARAÇÃO DO MOTOR ---
def get_melspectrogram_model():
    """Carrega o modelo que converte som em imagens (features)"""
    base_path = os.path.dirname(openwakeword.__file__)
    model_path = os.path.join(base_path, "resources", "models", "melspectrogram.onnx")
    sess = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    return sess

def audio_to_features(audio_data, sess):
    """Transforma áudio RAW em vetores matemáticos para o treino"""
    # Normalizar
    if audio_data.dtype == np.int16:
        audio_data = audio_data.astype(np.float32) / 32768.0
    
    # 1. Obter Mel Spectrogram
    mel = sess.run(None, {'input': audio_data[None, :]})[0].squeeze()
    
    features = []
    # 2. Criar janelas deslizantes (Sliding Windows)
    for i in range(0, len(mel) - STACK_SIZE + 1):
        window = mel[i : i + STACK_SIZE]
        features.append(window.flatten())
        
    return np.array(features)

def carregar_positivos(sess):
    print(f"🎤 A carregar positivos de '{PASTA_POSITIVOS}'...")
    wavs = glob.glob(os.path.join(PASTA_POSITIVOS, "*.wav"))
    features_list = []
    
    if not wavs:
        print("❌ ERRO: Nenhuns ficheiros .wav encontrados na pasta de positivos!")
        return None

    for wav in tqdm(wavs):
        try:
            with wave.open(wav, 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                audio = np.frombuffer(frames, dtype=np.int16)
                feats = audio_to_features(audio, sess)
                if len(feats) > 0:
                    features_list.append(feats)
        except Exception as e:
            print(f"⚠️ Ignorado {wav}: {e}")

    if features_list:
        return np.vstack(features_list)
    return None

def carregar_negativos():
    """
    Lógica de prioridade para carregar negativos:
    1. 'negativos_local.npy' (Gerado pelo teu script compactar) -> Mais Rápido e Personalizado
    2. 'negatives.npy' (Dataset Genérico da Internet) -> Bom para encher chouriços
    """
    neg_features = []
    
    # OPÇÃO A: O Teu Ficheiro Compactado (RÁPIDO)
    if os.path.exists("negativos_local.npy"):
        print("⚡ Encontrado 'negativos_local.npy'. A carregar...")
        local_data = np.load("negativos_local.npy")
        neg_features.append(local_data)
        
    # OPÇÃO B: O Dataset Genérico (WEB)
    # Se não existir localmente, tenta baixar
    if not os.path.exists("negatives.npy"):
        print("🌐 A baixar dataset genérico de validação (aprox 100MB)...")
        try:
            r = requests.get(URL_GENERICOS, allow_redirects=True)
            with open("negatives.npy", 'wb') as f:
                f.write(r.content)
        except:
            print("⚠️ Falha ao baixar negativos genéricos. Ignorando.")

    if os.path.exists("negatives.npy"):
        print("📦 A carregar dataset genérico...")
        gen_data = np.load("negatives.npy")
        # Usamos uma amostra aleatória para não usar 100% da RAM se for gigante
        # Mas queremos bastantes. Vamos tentar usar 50.000 se houver.
        if len(gen_data) > 50000:
            idx = np.random.choice(len(gen_data), 50000, replace=False)
            neg_features.append(gen_data[idx])
        else:
            neg_features.append(gen_data)

    if not neg_features:
        print("❌ ERRO FATAL: Sem dados negativos!")
        print("👉 Corre o 'compactar_negativos.py' primeiro ou verifica a internet.")
        return None
        
    return np.vstack(neg_features)

# --- FUNÇÃO PRINCIPAL ---
def main():
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    
    # 1. Iniciar Sessão ONNX
    sess = get_melspectrogram_model()

    # 2. Carregar Dados
    X_pos = carregar_positivos(sess)
    if X_pos is None: return
    
    X_neg = carregar_negativos()
    if X_neg is None: return

    # Criar Labels (1 = Fantasma, 0 = Lixo)
    y_pos = np.ones(len(X_pos))
    y_neg = np.zeros(len(X_neg))

    # Juntar tudo
    X = np.vstack((X_pos, X_neg))
    y = np.concatenate((y_pos, y_neg))

    print(f"\n⚔️  A TREINAR: {len(X_pos)} Positivos vs {len(X_neg)} Negativos")
    print(f"⚖️  Proporção: 1 para {len(X_neg)/len(X_pos):.1f}")

    # 3. Treinar Modelo (Regressão Logística)
    # class_weight='balanced' é CRUCIAL para lidar com a diferença de quantidade
    clf = LogisticRegression(class_weight='balanced', max_iter=5000, C=0.1)
    clf.fit(X, y)

    # 4. Avaliar
    score = clf.score(X, y)
    print(f"🎯 Score (Precisão Matemática): {score:.4f}")
    
    if score == 1.0:
        print("⚠️  AVISO: Score perfeito (1.0) pode indicar overfitting.")
        print("    Testa o modelo na vida real. Se falhar muito, precisas de mais negativos difíceis.")

    # 5. Exportar para ONNX
    print(f"💾 A converter para ONNX...")
    
    # Definir o tipo de entrada (Vector de floats com tamanho STACK_SIZE * 32 mels = 512)
    initial_type = [('float_input', FloatTensorType([None, 512]))]
    
    # Converter
    onnx_model = to_onnx(clf, initial_types=initial_type, target_opset=12)
    
    # Salvar
    output_path = os.path.join(OUTPUT_DIR, f"{NOME_MODELO}.onnx")
    with open(output_path, "wb") as f:
        f.write(onnx_model.SerializeToString())

    print(f"\n✅ SUCESSO! Modelo guardado em:\n   -> {output_path}")
    print("\n👉 Para usar, atualiza o teu assistant.py para apontar para este ficheiro.")

if __name__ == "__main__":
    main()
