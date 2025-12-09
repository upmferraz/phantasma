import threading
import time
import datetime
import random
import sqlite3
import json
import re
import os
import glob
import ast
import ollama
import config
from tools import search_with_searxng
from data_utils import save_to_rag, retrieve_from_rag

# --- Configuração ---
TRIGGER_TYPE = "contains"
TRIGGERS = ["vai sonhar", "aprende algo", "desenvolve a persona", "programa", "melhora o código", "sonho lúcido"]

# Hora a que o assistente vai "sonhar" sozinho (formato 24h)
DREAM_TIME = "02:30" 
LUCID_DREAM_CHANCE = 0.3

# Caminho para a skill MESTRA que vai evoluir
AUTOGEN_SKILL_PATH = os.path.join(config.SKILLS_DIR, "skill_lucid.py")

# Configuração de Consolidação
MEMORY_CHUNK_SIZE = 5

# --- Utils de Memória e JSON (Mantidos) ---

def _get_recent_memories(limit=3):
    try:
        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT text FROM memories ORDER BY id DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        if not rows: return "No previous memories."
        return "\n".join([r[0] for r in reversed(rows)])
    except Exception as e: return ""

def _repair_malformed_json(text):
    pattern = r'\{\s*"(.*?)"\s*->\s*"(.*?)"\s*->\s*"(.*?)"\s*\}'
    text = re.sub(pattern, r'"\1 -> \2 -> \3"', text)
    return text

def _extract_json(text):
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        candidate = match.group(0) if match else text
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            return json.loads(_repair_malformed_json(candidate))
        except: return None
    except: return None

def _consolidate_memories():
    print("🧠 [Dream] A iniciar consolidação de memória...")
    try:
        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, text FROM memories ORDER BY id DESC LIMIT ?", (MEMORY_CHUNK_SIZE,))
        rows = cursor.fetchall()
        
        if len(rows) < MEMORY_CHUNK_SIZE: return

        ids_to_delete = [r[0] for r in rows]
        processed_texts = []
        for r in rows:
            try: json.loads(r[1]); processed_texts.append(r[1])
            except: processed_texts.append(f"RAW: {r[1]}")

        prompt = f"""
        SYSTEM: You are a Data Optimizer.
        INPUT: {json.dumps(processed_texts, ensure_ascii=False)}
        TASK: Merge into SINGLE JSON. Tags (PT), Facts (EN, Strings).
        OUTPUT: {{ "tags": [], "facts": [] }}
        """
        
        client = ollama.Client(timeout=config.OLLAMA_TIMEOUT)
        resp = client.chat(model=config.OLLAMA_MODEL_PRIMARY, messages=[{'role': 'user', 'content': prompt}])
        merged = _extract_json(resp['message']['content'])
        
        if merged:
            pl = ','.join('?'*len(ids_to_delete))
            cursor.execute(f"DELETE FROM memories WHERE id IN ({pl})", ids_to_delete)
            cursor.execute("INSERT INTO memories (timestamp, text) VALUES (?, ?)", (datetime.datetime.now(), json.dumps(merged, ensure_ascii=False)))
            conn.commit()
            print("🧠 [Dream] Consolidação concluída.")
    except Exception as e: print(f"ERRO Consolidação: {e}")
    finally: 
        if conn: conn.close()

# --- MOTOR DE SONHO LÚCIDO (CODING) ---

def _validate_python_code(code_str):
    """ Valida sintaxe e estrutura básica. """
    try:
        ast.parse(code_str)
        if "def handle" not in code_str or "TRIGGERS" not in code_str:
            return False, "Falta handle ou TRIGGERS."
        return True, "Válido."
    except SyntaxError as e:
        return False, f"Erro Sintaxe: {e}"
    except Exception as e:
        return False, f"Erro: {e}"

def _perform_coding_dream():
    """ 
    O Agente Evolutivo:
    Lê a skill existente e ADICIONA novas funções baseadas na memória.
    """
    print("👾 [Lucid Dream] A iniciar evolução de código...")
    
    # 1. Preparar Base de Código
    current_code = ""
    
    if os.path.exists(AUTOGEN_SKILL_PATH):
        try:
            with open(AUTOGEN_SKILL_PATH, 'r') as f:
                current_code = f.read()
        except: pass
    
    if not current_code:
        # Template inicial se o ficheiro não existir
        current_code = """
import config
import random
# Initial Template
TRIGGER_TYPE = "contains"
TRIGGERS = ["lucid status"]

def handle(user_prompt_lower, user_prompt_full):
    return "A skill lúcida está ativa e à espera de evolução."
"""

    # 2. Ler Memórias (Inspiração)
    recent_memories = _get_recent_memories(limit=10)
    
    # 3. Prompt de Evolução Cumulativa
    dev_prompt = f"""
    SYSTEM: You are an expert Python Developer for 'Phantasma'.
    You are EVOLVING an existing file (`skill_lucid.py`).
    
    CURRENT CODE:
    ```python
    {current_code}
    ```
    
    MEMORY CONTEXT (Inspiration for NEW features):
    {recent_memories}
    
    TASK: Evolve the `skill_lucid.py` file.
    1. **ANALYZE**: Understand existing functions. DO NOT DELETE THEM (unless redundant).
    2. **INNOVATE**: Create a NEW helper function based on a topic in MEMORY CONTEXT (e.g., if 'Space', add `calculate_orbit()`).
    3. **INTEGRATE**: 
       - Update the `TRIGGERS` list to include keywords for the new feature.
       - Update the `handle()` function to route to the new helper function based on the user prompt.
    4. **OUTPUT**: The COMPLETE, updated Python code.
    
    RULES:
    - Output ONLY Python code.
    - Keep imports.
    - Ensure `handle` can route to ALL features (old and new).
    """
    
    try:
        client = ollama.Client(timeout=config.OLLAMA_TIMEOUT * 3) # Tempo extra para processar código grande
        print("👾 [Lucid Dream] A codificar nova funcionalidade na mesma skill...")
        resp = client.chat(model=config.OLLAMA_MODEL_PRIMARY, messages=[{'role': 'user', 'content': dev_prompt}])
        new_code = resp['message']['content'].replace("```python", "").replace("```", "").strip()
        
        # 4. Validar
        is_valid, message = _validate_python_code(new_code)
        if not is_valid:
            print(f"👾 [Lucid Dream] Código inválido: {message}")
            return f"Tentei evoluir, mas falhei na sintaxe: {message}"
        
        # 5. Gravar (Overwrite com a versão evoluída)
        with open(AUTOGEN_SKILL_PATH, 'w') as f:
            f.write(new_code)
            
        print(f"👾 [Lucid Dream] Sucesso! skill_lucid.py evoluída.")
        
        # 6. Log
        log = json.dumps({
            "tags": ["Dev", "Evolution", "Skill Lucid"],
            "facts": ["I added -> new function -> to skill_lucid.py", "Skill -> grew -> larger"]
        }, ensure_ascii=False)
        save_to_rag(log)
        
        return "Evoluí o meu código interno. Adicionei novas funções à minha skill base."

    except Exception as e:
        print(f"ERRO [Lucid Dream]: {e}")
        return "Erro na evolução."

# --- MOTOR WEB (Mantido) ---

def _perform_web_dream():
    print("💤 [Dream] A iniciar aprendizagem Web...")
    recent_context = _get_recent_memories()
    introspection_prompt = f"{config.SYSTEM_PROMPT}\nMEMORIES: {recent_context}\nTASK: Generate ONE search query based on interests.\nOUTPUT: Query string ONLY."
    
    try:
        client = ollama.Client(timeout=config.OLLAMA_TIMEOUT)
        resp = client.chat(model=config.OLLAMA_MODEL_PRIMARY, messages=[{'role': 'user', 'content': introspection_prompt}])
        query = resp['message']['content'].strip().replace('"', '')
        print(f"💤 [Dream] Tópico: '{query}'")
        
        results = search_with_searxng(query, max_results=3)
        if not results or len(results) < 10: return "Sonho vazio."
        
        internalize_prompt = f"SYSTEM: Data Extractor. JSON ONLY.\nCONTEXT: {results}\nTASK: Extract tags(PT) and facts(EN S->P->O)."
        resp_final = client.chat(model=config.OLLAMA_MODEL_PRIMARY, messages=[{'role': 'user', 'content': internalize_prompt}])
        json_data = _extract_json(resp_final['message']['content'])
        
        if json_data:
            save_to_rag(json.dumps(json_data, ensure_ascii=False))
            _consolidate_memories()
            return f"Aprendi sobre '{query}'."
        return "Falha ao processar sonho."
        
    except Exception as e: return "Pesadelo."

# --- ROUTER ---

def perform_dreaming(mode="auto"):
    if mode == "code": return _perform_coding_dream()
    elif mode == "web": return _perform_web_dream()
    else:
        return _perform_coding_dream() if random.random() < LUCID_DREAM_CHANCE else _perform_web_dream()

# --- DAEMON ---

def _daemon_loop():
    print(f"[Dream] Daemon agendado para as {DREAM_TIME}...")
    while True:
        now = datetime.datetime.now()
        if now.strftime("%H:%M") == DREAM_TIME:
            threading.Thread(target=perform_dreaming, args=("auto",)).start()
            time.sleep(65)
        time.sleep(30)

def init_skill_daemon():
    t = threading.Thread(target=_daemon_loop, daemon=True)
    t.start()

def handle(user_prompt_lower, user_prompt_full):
    print(f"💤 [Dream] Comando manual: '{user_prompt_lower}'")
    mode = "auto"
    if any(x in user_prompt_lower for x in ["program", "código", "lúcido", "skill", "melhora"]): mode = "code"
    elif any(x in user_prompt_lower for x in ["aprende", "estuda", "web", "pesquisa"]): mode = "web"
    
    threading.Thread(target=perform_dreaming, args=(mode,)).start()
    return "A iniciar processo onírico..."
