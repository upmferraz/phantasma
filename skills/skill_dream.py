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
MIN_MEMORIES_TO_TRIGGER = 6 # Mínimo para ativar a consolidação

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
    Lê as últimas X memórias, funde-as numa única entrada JSON sem duplicados,
    remove as antigas e insere a nova.
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
        
        # 2. Pedir ao LLM para fundir
        consolidation_prompt = f"""
        {config.SYSTEM_PROMPT}
        
        RAW MEMORY FRAGMENTS:
        {json.dumps(texts_to_merge, ensure_ascii=False)}
        
        TASK: You are a Knowledge Graph Database Optimizer.
        These fragments contain redundant or overlapping JSON data.
        Merge them into a SINGLE, optimized JSON object.
        
        RULES:
        1. Combine "tags" arrays into one unique list (remove duplicates).
        2. Combine "facts" arrays. If facts contradict, keep the most recent/detailed.
        3. Remove noise. Keep only valid JSON.
        
        OUTPUT FORMAT:
        {{
            "tags": ["Tag1", "Tag2"],
            "facts": ["A -> is -> B", "C -> causes -> D"]
        }}
        """
        
        client = ollama.Client(timeout=config.OLLAMA_TIMEOUT)
        resp = client.chat(model=config.OLLAMA_MODEL_PRIMARY, messages=[{'role': 'user', 'content': consolidation_prompt}])
        merged_json = resp['message']['content'].strip()
        
        # Limpeza básica de markdown
        merged_json = merged_json.replace("```json", "").replace("```", "").strip()
        
        # Validação básica (se falhar o parse, aborta para não perder dados)
        json.loads(merged_json) 
        
        # 3. Operação Atómica de BD (Apagar Velhas -> Inserir Nova)
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
    Ciclo de Sonho Completo:
    1. Contexto -> Introspeção
    2. Pesquisa
    3. Internalização (Novo conhecimento)
    4. Consolidação (Limpeza de memória)
    """
    print("💤 [Dream] A iniciar processo de aprendizagem noturna...")
    
    # --- FASE 1: APRENDER (Mantida da versão anterior) ---
    recent_context = _get_recent_memories()
    
    introspection_prompt = f"""
    {config.SYSTEM_PROMPT}
    
    PREVIOUS MEMORIES:
    {recent_context}
    
    TASK: Analyze your knowledge gaps. Based on your ETHICAL CORE (Veganism) and PERSONA (Phantom), generate a SINGLE search query for a new topic.
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

        internalize_prompt = f"""
        {config.SYSTEM_PROMPT}
        
        WEB CONTEXT:
        {search_results}
        
        TASK: Extract pure knowledge into JSON.
        RULES:
        1. CLEAN DATA: NO copyright, NO editorial notes.
        2. TAGS (PT): Array of keywords.
        3. FACTS (EN): Array of "Subject -> Predicate -> Object".
        4. JSON ONLY.
        
        OUTPUT FORMAT:
        {{ "tags": ["A", "B"], "facts": ["X -> y -> Z"] }}
        """
        
        resp_final = client.chat(model=config.OLLAMA_MODEL_PRIMARY, messages=[{'role': 'user', 'content': internalize_prompt}])
        dense_thought = resp_final['message']['content'].strip().replace("```json", "").replace("```", "").strip()
        
        save_to_rag(dense_thought)
        print(f"💤 [Dream] Novo conhecimento arquivado.")
        
        # --- FASE 2: CONSOLIDAR (Nova) ---
        # Só corre se não tiver havido erros na fase 1
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
