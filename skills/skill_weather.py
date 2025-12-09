import re
import httpx
import unicodedata
import config
import json
import os
import time
import threading
import tempfile
from datetime import datetime

# --- Configuração ---
TRIGGER_TYPE = "contains"
TRIGGERS = ["tempo", "clima", "meteorologia", "previsão", "vai chover", "vai estar", "qualidade do ar", "lua"]

CACHE_FILE = "/opt/phantasma/cache/weather_cache.json"
POLL_INTERVAL = 1800  # 30 minutos

# ID Padrão (Porto) se não houver config
DEFAULT_CITY_ID = getattr(config, 'IPMA_GLOBAL_ID', 1131200)
DEFAULT_CITY_NAME = getattr(config, 'CITY_NAME', "Porto")

# --- Helpers ---

def _normalize(text):
    try:
        return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8').lower()
    except:
        return text.lower()

def _get_moon_phase():
    try:
        known_new_moon = datetime(2000, 1, 6)
        lunar_cycle = 29.53058867
        now = datetime.now()
        days_passed = (now - known_new_moon).total_seconds() / 86400
        current_pos = days_passed % lunar_cycle
        
        if current_pos < 1.84: return "Lua Nova"
        if current_pos < 5.53: return "Crescente"
        if current_pos < 9.22: return "Quarto Crescente"
        if current_pos < 12.91: return "Crescente Gibosa"
        if current_pos < 16.61: return "Lua Cheia"
        if current_pos < 20.30: return "Minguante Gibosa"
        if current_pos < 23.99: return "Quarto Minguante"
        if current_pos < 27.68: return "Minguante"
        return "Lua Nova"
    except: return ""

def _fetch_city_data(global_id):
    result = {"timestamp": time.time(), "city_id": global_id}
    client = httpx.Client(timeout=10.0)
    
    try:
        # 1. IPMA
        url = f"https://api.ipma.pt/open-data/forecast/meteorology/cities/daily/{global_id}.json"
        data = client.get(url).json()
        result['forecast'] = data.get('data', [])
        
        if result['forecast']:
            lat = result['forecast'][0].get('latitude')
            lon = result['forecast'][0].get('longitude')
            
            # 2. AQI (Open-Meteo Fallback)
            try:
                url_aqi = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=us_aqi"
                aqi_data = client.get(url_aqi, timeout=5.0).json()
                result['aqi'] = aqi_data['current']['us_aqi']
            except: pass

        result['moon_phase'] = _get_moon_phase()
        return result

    except Exception as e:
        print(f"[Weather] Erro fetch: {e}")
        return None
    finally:
        client.close()

# --- Daemon ---

def _save_cache(data):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        # Escrita atómica para evitar ficheiros corrompidos
        with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(CACHE_FILE), delete=False) as tf:
            json.dump(data, tf)
            temp_name = tf.name
        os.replace(temp_name, CACHE_FILE)
        os.chmod(CACHE_FILE, 0o666)
    except Exception as e:
        print(f"[Weather] Erro cache: {e}")

def _daemon_loop():
    while True:
        data = _fetch_city_data(DEFAULT_CITY_ID)
        if data: _save_cache(data)
        time.sleep(POLL_INTERVAL)

def init_skill_daemon():
    print("[Weather] Daemon iniciado.")
    threading.Thread(target=_daemon_loop, daemon=True).start()

# --- Handler ---

def handle(user_prompt_lower, user_prompt_full):
    try:
        if not os.path.exists(CACHE_FILE):
            return "Ainda estou a recolher dados meteorológicos. Aguarda um momento."
            
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
            
        if not data or not data.get('forecast'):
            return "Não tenho dados de previsão disponíveis."

        # Seleciona dia (hoje/amanhã)
        idx = 1 if "amanhã" in user_prompt_lower else 0
        if len(data['forecast']) <= idx: return "Previsão indisponível."
        
        day = data['forecast'][idx]
        
        # --- CORREÇÃO: ARREDONDAMENTO PARA INTEIROS ---
        t_max = round(float(day.get('tMax', 0)))
        t_min = round(float(day.get('tMin', 0)))
        
        # Resposta Base
        resp = f"Previsão: Máxima de {t_max} e mínima de {t_min} graus."
        
        # Chuva (converter para int para remover casa decimal)
        precip = int(float(day.get('precipitaProb', 0)))
        
        if precip > 50: resp += f" Leva guarda-chuva, probabilidade de chuva é {precip}%."
        elif precip > 0: resp += f" Possibilidade de chuva ({precip}%)."
        
        # Extras (só se relevante)
        if 'aqi' in data:
            aqi = data['aqi']
            if aqi > 100: resp += f" Atenção, a qualidade do ar está má ({aqi})."
            
        return resp

    except Exception as e:
        print(f"[Weather] Erro handle: {e}")
        return "Ocorreu um erro ao verificar a meteorologia."
