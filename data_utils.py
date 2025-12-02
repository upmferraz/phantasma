import sqlite3
import time
import re
import unicodedata
from datetime import datetime
import config

# --- Funções Auxiliares ---
def _normalize_key(text):
    """ 
    Normaliza o texto para usar como chave de cache.
    Remove acentos, pontuação e coloca em minúsculas para aumentar a taxa de 'hits'.
    """
    try:
        # Remove acentos
        nfkd = unicodedata.normalize('NFKD', text)
        text = "".join([c for c in nfkd if not unicodedata.combining(c)])
        # Remove caracteres especiais (mantém apenas letras e números)
        text = re.sub(r'[^a-zA-Z0-9\s]', '', text)
        return text.lower().strip()
    except:
        return text.lower().strip()

def setup_database():
    """ Cria as tabelas necessárias na BD se não existirem. """
    try:
        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        
        # 1. Tabela de Memórias (RAG - Longa Duração)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            text TEXT NOT NULL
        );
        """)
        
        # 2. Tabela de Cache de Respostas (Curta/Média Duração)
        # Evita perguntar ao Ollama a mesma coisa duas vezes seguidas
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS response_cache (
            normalized_key TEXT PRIMARY KEY,
            response TEXT NOT NULL,
            timestamp REAL NOT NULL
        );
        """)
        
        conn.commit()
        conn.close()
        print(f"Base de dados '{config.DB_PATH}' verificada e inicializada.")
    except Exception as e:
        print(f"ERRO: Falha ao inicializar a base de dados SQLite: {e}")

# --- RAG (Memória de Longo Prazo) ---

def save_to_rag(transcription_text):
    """ Guarda um pensamento ou facto na memória permanente. """
    if not transcription_text: return 
    try:
        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memories (timestamp, text) VALUES (?, ?)",
            (datetime.now(), transcription_text)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"ERRO RAG Save: {e}")

def retrieve_from_rag(prompt, max_results=3):
    """ Recupera memórias baseadas em palavras-chave do prompt. """
    try:
        # Extrai palavras com mais de 3 letras para pesquisa
        keywords = [word for word in prompt.lower().split() if len(word) > 3]
        if not keywords: return "" 

        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        
        query_parts = []
        params = []
        for word in keywords:
            query_parts.append("text LIKE ?")
            params.append(f"%{word}%")
            
        sql_query = f"SELECT text FROM memories WHERE {' OR '.join(query_parts)} ORDER BY id DESC LIMIT {max_results}"
        
        cursor.execute(sql_query, params)
        results = cursor.fetchall()
        conn.close()

        if results:
            context_str = "CONTEXTO MEMÓRIA (Usa se relevante):\n"
            for row in results:
                context_str += f"- {row[0]}\n"
            return context_str
        else:
            return ""

    except Exception as e:
        print(f"ERRO RAG Retrieve: {e}")
        return ""

# --- Cache de Respostas (NOVO) ---

def get_cached_response(prompt):
    """ 
    Verifica se já respondemos a esta pergunta recentemente.
    Retorna o texto da resposta ou None.
    """
    try:
        key = _normalize_key(prompt)
        if not key: return None

        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT response FROM response_cache WHERE normalized_key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            # print(f"DEBUG: Cache hit para '{key}'")
            return row[0]
            
        return None
    except Exception as e:
        print(f"ERRO Cache Get: {e}")
        return None

def save_cached_response(prompt, response):
    """ Guarda a resposta do LLM para uso futuro. """
    try:
        if not response or "erro" in response.lower(): return

        key = _normalize_key(prompt)
        if not key: return

        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        
        # REPLACE insere ou atualiza se a chave já existir
        cursor.execute(
            "REPLACE INTO response_cache (normalized_key, response, timestamp) VALUES (?, ?, ?)",
            (key, response, time.time())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"ERRO Cache Save: {e}")
