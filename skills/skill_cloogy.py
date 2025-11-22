import logging
import httpx
import time
import threading
import json
import os
import config

# --- Configuração ---
TRIGGER_TYPE = "contains"
BASE_TRIGGERS = ["cloogy", "kiome", "lista", "listar", "consumo", "gastar", "leitura", "quanto"]
CACHE_FILE = "/opt/phantasma/cloogy_cache.json"

def _get_triggers():
    if hasattr(config, 'CLOOGY_DEVICES') and isinstance(config.CLOOGY_DEVICES, dict):
        return BASE_TRIGGERS + list(config.CLOOGY_DEVICES.keys())
    return BASE_TRIGGERS

TRIGGERS = _get_triggers()

# --- Gestão de Cache ---

def _fix_permissions():
    """ Garante que toda a gente consegue ler o ficheiro """
    try:
        if os.path.exists(CACHE_FILE):
            os.chmod(CACHE_FILE, 0o666)
    except: pass

def _load_cache():
    if not os.path.exists(CACHE_FILE):
        print(f"DEBUG Cloogy: Ficheiro {CACHE_FILE} não existe.")
        return {}
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"DEBUG Cloogy: Erro a ler JSON: {e}")
        return {}

def _update_single_value(device_id, watts):
    if watts is None: return
    try:
        # Lê existente para não apagar outros sensores
        data = _load_cache()
        
        # Força ID a string e guarda
        data[str(device_id)] = {"val": watts, "ts": time.time()}
        
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f)
        
        _fix_permissions() # Garante que a Web UI consegue ler a seguir
        # print(f"DEBUG Cloogy: Gravado ID={device_id} W={watts}")
    except Exception as e:
        print(f"DEBUG Cloogy: Erro a gravar JSON: {e}")

# --- API ---
CURRENT_TOKEN = None

def _get_headers():
    return {"Authorization": f"VPS {CURRENT_TOKEN}", "Accept": "application/json"}

def _login():
    global CURRENT_TOKEN
    user = getattr(config, 'CLOOGY_USERNAME', None)
    pwd = getattr(config, 'CLOOGY_PASSWORD', None)
    if not user or not pwd: return False
    try:
        resp = httpx.post("https://api.cloogy.com/api/1.4/sessions", json={"Login": user, "Password": pwd}, headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=15, verify=False)
        if resp.status_code in [200, 201]:
            CURRENT_TOKEN = resp.json().get("Token")
            return True
    except: pass
    return False

def _ensure_auth():
    if not CURRENT_TOKEN: return _login()
    return True

def _fetch_reading(device_id):
    if not _ensure_auth(): return None
    try:
        now = int(time.time() * 1000)
        start = now - (60 * 60 * 1000)
        url = "https://api.cloogy.com/api/1.4/consumptions/instant"
        params = {"from": start, "to": now, "tags": f"[{device_id}]", "includeForecast": "False"}
        resp = httpx.get(url, params=params, headers=_get_headers(), timeout=20, verify=False)
        
        if resp.status_code == 401:
            if _login(): resp = httpx.get(url, params=params, headers=_get_headers(), timeout=20, verify=False)
        
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                kw = data[-1].get("Read")
                if kw is not None: return float(kw) * 1000
    except: pass
    return None

# --- Daemon Interno ---
def _poll_loop():
    """ Atualiza a cache em background """
    # print("DEBUG Cloogy: Daemon interno a arrancar...")
    while True:
        try:
            if hasattr(config, 'CLOOGY_DEVICES'):
                for name, dev_id in config.CLOOGY_DEVICES.items():
                    val = _fetch_reading(dev_id)
                    if val is not None: _update_single_value(dev_id, val)
        except: pass
        time.sleep(60)

threading.Thread(target=_poll_loop, daemon=True).start()

# --- Interface Web UI ---
def get_status_for_device(nickname):
    # Debug crítico para o log
    # print(f"DEBUG UI: Pedido status para '{nickname}'")
    
    if not hasattr(config, 'CLOOGY_DEVICES') or nickname not in config.CLOOGY_DEVICES:
        print(f"DEBUG UI: '{nickname}' não encontrado no config.")
        return {"state": "unreachable"}
    
    dev_id = str(config.CLOOGY_DEVICES[nickname])
    cache = _load_cache()
    
    if dev_id in cache:
        watts = cache[dev_id]["val"]
        if "forno" in nickname.lower():
            return {"state": "on" if watts > 0 else "off"}
        else:
            return {"state": "on", "power_w": round(watts, 1)}
            
    print(f"DEBUG UI: ID {dev_id} não está na cache. Chaves disponíveis: {list(cache.keys())}")
    return {"state": "unreachable"}

# --- Interface Voz ---
def _set_state(device_id, state_on):
    # (Código de controlo mantém-se igual, omitido por brevidade mas necessário manter)
    # Se precisar desta parte para o forno, copie do anterior.
    # Para o sensor "casa", o código de leitura é o relevante.
    return False 

def handle(user_prompt_lower, user_prompt_full):
    if not hasattr(config, 'CLOOGY_DEVICES'): return None
    target_id = None; target_name = ""
    for name, dev_id in config.CLOOGY_DEVICES.items():
        if name in user_prompt_lower: target_id = dev_id; target_name = name; break
    if not target_id and any(x in user_prompt_lower for x in ["gastar", "consumo", "casa"]):
        if "casa" in config.CLOOGY_DEVICES: target_id = config.CLOOGY_DEVICES["casa"]; target_name = "casa"
    if not target_id: return None

    if any(x in user_prompt_lower for x in ["quanto", "consumo", "leitura", "gastar"]):
        val = _fetch_reading(target_id)
        if val is None:
            cache = _load_cache()
            if str(target_id) in cache: val = cache[str(target_id)]["val"]
        if val is not None:
            _update_single_value(target_id, val)
            return f"Está a gastar {int(val)} Watts."
        return f"Não consegui ler o {target_name}."
    return None
