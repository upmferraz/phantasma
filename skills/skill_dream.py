import threading
import time
import datetime
import random
import sqlite3
import json
import ollama
import config
from tools import search_with_searxng
from data_utils import save_to_rag

# --- Configuração ---
TRIGGER_TYPE = "contains"
TRIGGERS = ["vai sonhar", "aprende algo", "desenvolve a persona", "vai estudar"]

# Hora a que o assistente vai "sonhar" sozinho (formato 24h)
DREAM_TIME = "02:30" 

# Configuração de Consolidação
MEMORY_CHUNK_SIZE = 5  # Quantas memórias fundir de cada vez

def _get_recent_memories(limit=3):
    """ Lê as últimas entradas para contexto simples. """
    try:
        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT text FROM memories ORDER BY id DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        if not rows: return "No previous memories."
        return "\n".join([r[0] for r in reversed(rows)])
    except Exception as e:
        print(f"ERRO [Dream] Ler DB: {e}")
        return ""

def _consolidate_memories():
    """
    TAREFA DE MANUTENÇÃO:
    Lê as últimas X memórias, funde-as numa única entrada JSON.
    NOTA: Aqui NÃO usamos o SYSTEM_PROMPT do config para evitar forçar o Português.
    """
    print("🧠 [Dream] A iniciar consolidação de memória (Garbage Collection)...")
    
    conn = None
    try:
        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        
        # 1. Verificar se há memórias suficientes para consolidar
        cursor.execute("SELECT id, text FROM memories ORDER BY id DESC LIMIT ?", (MEMORY_CHUNK_SIZE,))
        rows = cursor.fetchall()
        
        if len(rows) < MEMORY_CHUNK_SIZE:
            print("🧠 [Dream] Memórias insuficientes para consolidar. A saltar.")
            return

        # Separa IDs e Textos
        ids_to_delete = [r[0] for r in rows]
        texts_to_merge = [r[1] for r in rows]
        
        # 2. Pedir ao LLM para fundir (PROMPT TÉCNICO, SEM PERSONA)
        consolidation_prompt = f"""
        SYSTEM: You are a strict JSON Data Optimizer. You do NOT chat. You only output JSON.
        
        RAW MEMORY FRAGMENTS:
        {json.dumps(texts_to_merge, ensure_ascii=False)}
        
        TASK: Merge these fragments into a SINGLE JSON object.
        
        RULES:
        1. "tags": Combine into a unique list in Portuguese (Portugal).
        2. "facts": Combine into a unique list in ENGLISH (Subject -> Predicate -> Object).
        3. Remove redundancy.
        
        OUTPUT FORMAT:
        {{
            "tags": ["TagPT1", "TagPT2"],
            "facts": ["Subject -> verb -> Object"]
        }}
        """
        
        client = ollama.Client(timeout=config.OLLAMA_TIMEOUT)
        # Nota: Removemos o SYSTEM_PROMPT daqui propositadamente
        resp = client.chat(model=config.OLLAMA_MODEL_PRIMARY, messages=[{'role': 'user', 'content': consolidation_prompt}])
        merged_json = resp['message']['content'].strip()
        
        # Limpeza básica de markdown
        merged_json = merged_json.replace("```json", "").replace("```", "").strip()
        
        # Validação básica
        json.loads(merged_json) 
        
        # 3. Operação Atómica de BD
        placeholders = ', '.join('?' * len(ids_to_delete))
        cursor.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", ids_to_delete)
        cursor.execute("INSERT INTO memories (timestamp, text) VALUES (?, ?)", (datetime.datetime.now(), merged_json))
        
        conn.commit()
        print(f"🧠 [Dream] Consolidação concluída! {len(ids_to_delete)} memórias fundidas em 1.")
        
    except json.JSONDecodeError:
        print("ERRO [Dream] O LLM gerou JSON inválido durante a consolidação. Abortado.")
    except Exception as e:
        print(f"ERRO [Dream] Falha na consolidação: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

def perform_dreaming():
    """ 
    Ciclo de Sonho Completo.
    """
    print("💤 [Dream] A iniciar processo de aprendizagem noturna...")
    
    # --- FASE 1: APRENDER ---
    recent_context = _get_recent_memories()
    
    # INTROSPEÇÃO: Aqui usamos a PERSONA (SYSTEM_PROMPT) porque queremos que o tema seja "Gótico/Vegan"
    introspection_prompt = f"""
    {config.SYSTEM_PROMPT}
    
    PREVIOUS MEMORIES:
    {recent_context}
    
    TASK: Analyze your knowledge gaps. Based on your ETHICAL CORE and PERSONA, generate a SINGLE search query for a new topic.
    OUTPUT: Write ONLY the search query string. No quotes.
    """
    
    try:
        client = ollama.Client(timeout=config.OLLAMA_TIMEOUT)
        resp_intro = client.chat(model=config.OLLAMA_MODEL_PRIMARY, messages=[{'role': 'user', 'content': introspection_prompt}])
        search_query = resp_intro['message']['content'].strip().replace('"', '')
        
        print(f"💤 [Dream] Tópico: '{search_query}'")
        
        search_results = search_with_searxng(search_query, max_results=3)
        if not search_results or len(search_results) < 10:
            return "Sonho vazio (sem dados)."

        # INTERNALIZAÇÃO: Aqui usamos PROMPT TÉCNICO (sem Persona) para garantir o Inglês
        internalize_prompt = f"""
        SYSTEM: You are a Data Extractor engine. You do NOT have a personality. You output strict JSON.
        
        WEB CONTEXT:
        {search_results}
        
        TASK: Extract pure knowledge into JSON.
        RULES:
        1. CLEAN DATA: NO copyright, NO editorial notes.
        2. TAGS: Array of keywords in PORTUGUESE (for indexing).
        3. FACTS: Array of "Subject -> Predicate -> Object" in ENGLISH.
        
        OUTPUT FORMAT:
        {{ "tags": ["KeywordPT"], "facts": ["Subject(EN) -> verb -> Object(EN)"] }}
        """
        
        resp_final = client.chat(model=config.OLLAMA_MODEL_PRIMARY, messages=[{'role': 'user', 'content': internalize_prompt}])
        
        # Limpeza robusta do JSON
        dense_thought = resp_final['message']['content'].strip()
        if "```" in dense_thought:
            dense_thought = dense_thought.split("```json")[-1].split("```")[0].strip()
        
        # Validar antes de guardar
        try:
            json.loads(dense_thought)
            save_to_rag(dense_thought)
            print(f"💤 [Dream] Novo conhecimento arquivado (EN/PT).")
        except:
            print(f"ERRO [Dream] JSON inválido gerado: {dense_thought}")
            return "Falha ao estruturar o sonho."
        
        # --- FASE 2: CONSOLIDAR ---
        _consolidate_memories()
        
        return f"Conhecimento sobre '{search_query}' assimilado e memória otimizada."

    except Exception as e:
        print(f"ERRO [Dream]: {e}")
        return "Pesadelo de conexão."

# --- Daemon de Agendamento ---

def _daemon_loop():
    print(f"[Dream] Daemon agendado para as {DREAM_TIME}...")
    while True:
        now = datetime.datetime.now()
        current_time = now.strftime("%H:%M")
        
        if current_time == DREAM_TIME:
            try:
                perform_dreaming()
                time.sleep(65)
            except Exception as e:
                print(f"ERRO CRÍTICO [Dream Daemon]: {e}")
                time.sleep(60)
        time.sleep(30)

def init_skill_daemon():
    t = threading.Thread(target=_daemon_loop, daemon=True)
    t.start()

def handle(user_prompt_lower, user_prompt_full):
    return perform_dreaming()
