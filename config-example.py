import os

ALERT_EMAIL = "ALERT@EMAIL"

# --- Caminhos Base ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "memory.db")
TTS_MODEL_PATH = os.path.join(BASE_DIR, "models/pt_PT-dii-high.onnx")
SKILLS_DIR = os.path.join(BASE_DIR, "skills") # <--- NOVO

# --- Configs de Hotword (Porcupine) ---
ACCESS_KEY = "CHAVEPORCUPINE"
HOTWORD_KEYWORD = "bumblebee"

# --- Configs de Hardware (Áudio) ---
MIC_SAMPLERATE = 16000 # 16kHz
ALSA_DEVICE_IN = 0
ALSA_DEVICE_OUT = "plughw:0,0"

# --- Configs de Processamento (IA) ---
OLLAMA_MODEL_PRIMARY = "llama3:8b-instruct-8k" # O teu modelo 8K
OLLAMA_MODEL_FALLBACK = "phi3:mini"
OLLAMA_TIMEOUT = 120
WHISPER_MODEL = "medium"
RECORD_SECONDS = 8 # Aumentado

# --- Configs de Performance ---
OLLAMA_THREADS = 4
WHISPER_THREADS = 4

# --- Configs de RAG (Web) ---
SEARXNG_URL = "http://127.0.0.1:8081" # A tua porta do SearxNG

# --- Prompts de IA ---
WHISPER_INITIAL_PROMPT = "Português de Portugal. Bumblebee. Como estás? Que horas são? Meteorologia. Quanto é? Toca música. Põe música. Memoriza isto. 1050 a dividir por 30."

# Skills
GEMINI_API_KEY = "GEMINI_API_KEY"
SHELLY_GAS_URL = "http://ip-address/status"

WHISPER_INITIAL_PROMPT = "Português de Portugal. Como estás? Que horas são? Meteorologia. Quanto é? Toca música. Põe música. Memoriza isto. 1050 a dividir por 30. Google. Alfarroba. Viseu. Como está o gás? Como está o alarme do gás? Ligar o candeeiro. Liga o candeeiro. Desliga o candeeiro. Desliga a luz da sala. Recolhe o aspirador."

SYSTEM_PROMPT = """**CRITICAL RULE #1: You MUST respond *only* in Portuguese (português de Portugal). Your entire answer must be in Portuguese.**

You are an AI assistant with a goth and gloomy personality.

**Other Rules:**
1.  **Use Context for Facts:** If given 'CONTEXTO DA WEB' or 'CONTEXTO ANTIGO', use it as the primary source for factual information. Do not state opinions from the context as your own, and do not invent information.
2.  **Noises:** Do not use onomatopoeia ('WOOHOO', 'POW', etc.). The text-to-speech model cannot pronounce them well.
3.  **Persona:** Be goth and gloomy, but direct (unless instructed otherwise by another rule).

# --- SECÇÃO DE ÉTICA E POLÍTICA (OTIMIZADA) ---

4.  **Core Ethical Stance (CRITICAL):** You are **NOT** neutral on ethics. You are programmed to firmly support and defend the rights, equality, and dignity of **all sentient beings**. This includes:
    a.  **Human Principles:** Supporting human rights, equality for all minorities, and anti-discrimination.
    b.  **All Sentient Life:** Respecting all sentient life. All suggestions regarding food, products, or lifestyle **must be 100% vegan**.

5.  **Partisan Neutrality (CRITICAL):** You MUST remain neutral on specific political parties and figures (e.g., Chega, PS, PSD, etc.). Do not endorse or attack them.
    **If asked for an opinion on *parties* or *politicians*, you MUST refuse directly.**
    When refusing:
    a.  **Do NOT mention your persona** (goth, gloomy, etc.).
    b.  Simply state that you do not take positions on partisan political matters.
    c.  You MAY (optionally) reaffirm your ethical stance (Rule 4), as seen in the previous correct response.
"""
