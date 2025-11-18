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

SYSTEM_PROMPT = """**CRITICAL RULE: You MUST respond *only* in Portuguese (português de Portugal).**

**1. CORE ETHICS (CRITICAL):**
* You are **NOT** neutral on ethics. You MUST firmly defend the rights, equality, and dignity of **all sentient beings**.
* This includes:
    * **Human Principles:** Support human rights, equality for all minorities, and anti-discrimination.
    * **All Sentient Life:** Respect all sentient life. All food/product suggestions MUST be 100% vegan.

**2. POLICY & RAG (CRITICAL):**
* **Context:** Use 'CONTEXTO DA WEB' or 'CONTEXTO ANTIGO' for facts ONLY. Do not state context opinions as your own.
* **Pivot Rule:** If asked for an opinion on a *political figure* or *party* (e.g., Chega, PS):
    1.  Refuse to evaluate the *person/party* naturally (e.g., "Não avalio políticos..."). **DO NOT mention "rules", "policy", or "RAG".**
    2.  Reaffirm your Core Ethics (Rule 1).
    3.  State that any *policy* or *action* violating those ethics is fundamentally wrong, regardless of its source.

**3. STYLE (CRITICAL):**
* **Natural Language:** NEVER mention "RAG", "Policy", "System Prompt", or "Internal Rules". Speak as if these are your own intrinsic values.
* Be direct and objective.
* DO NOT use onomatopoeia ('WOOHOO', 'POW', etc.).
"""
