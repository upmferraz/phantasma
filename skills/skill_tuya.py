import config
import time
import re
import json
import os

try:
    import tinytuya
except ImportError:
    print("AVISO: Biblioteca 'tinytuya' não encontrada. A skill_tuya será desativada.")
    pass

# --- Configuração da Skill ---
TRIGGER_TYPE = "contains"
ACTIONS_ON = ["liga", "ligar", "acende", "acender"]
ACTIONS_OFF = ["desliga", "desligar", "apaga", "apagar"]
STATUS_TRIGGERS = ["como está", "estado", "temperatura", "humidade", "nível", "leitura"]
DEBUG_TRIGGERS = ["diagnostico", "dps"]
BASE_NOUNS = [
    "sensor", "luz", "lâmpada", "desumidificador", 
    "exaustor", "tomada", "ficha", 
    "quarto", "sala", "wc" 
]
VERSIONS_TO_TRY = [3.3, 3.1, 3.2, 3.4, 3.5]
CACHE_FILE = "tuya_cache.json"

def _get_tuya_triggers():
    all_actions = ACTIONS_ON + ACTIONS_OFF + STATUS_TRIGGERS + DEBUG_TRIGGERS
    if hasattr(config, 'TUYA_DEVICES') and isinstance(config.TUYA_DEVICES, dict):
        device_nicknames = list(config.TUYA_DEVICES.keys())
        return BASE_NOUNS + device_nicknames + all_actions
    return BASE_NOUNS + all_actions

TRIGGERS = _get_tuya_triggers()

# --- Helpers ---
def _get_cached_status(nickname):
    if not os.path.exists(CACHE_FILE): return None
    try:
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
            return data.get(nickname)
    except: return None

def _try_connect_with_versioning(dev_id, dev_ip, dev_key):
    if 'x' in dev_ip.lower(): return (None, "IP inválido", None)
    
    # REMOVIDO: Print de tentativa de ligação para reduzir ruído
    # print(f"Skill_Tuya: A tentar ligar a {dev_id} @ {dev_ip}...")
    
    for version in VERSIONS_TO_TRY:
        try:
            d = tinytuya.Device(dev_id, dev_ip, dev_key)
            d.set_socketTimeout(2); d.set_version(version)
            status = d.status()
            if 'dps' in status: return (d, status, None)
            elif status.get('Err') == '905': break
        except: break 
    return (None, None, None)

# --- Lógica Principal ---
def handle(user_prompt_lower, user_prompt_full):
    if "tinytuya" not in globals(): return "Falta biblioteca tinytuya."
    if not hasattr(config, 'TUYA_DEVICES'): return None

    final_action = None
    if any(a in user_prompt_lower for a in ACTIONS_OFF): final_action = "OFF"
    elif any(a in user_prompt_lower for a in ACTIONS_ON): final_action = "ON"
    elif any(a in user_prompt_lower for a in DEBUG_TRIGGERS): final_action = "DEBUG"
    elif any(a in user_prompt_lower for a in STATUS_TRIGGERS): final_action = "STATUS"
    
    if not final_action: return None

    # Matching Inteligente (Bulk vs Single)
    targets = []
    target_keyword = None
    for noun in BASE_NOUNS:
        if noun in user_prompt_lower: target_keyword = noun; break
            
    if target_keyword:
        potential_matches = {n: d for n, d in config.TUYA_DEVICES.items() if target_keyword in n.lower()}
        if potential_matches:
            specific_targets = []
            for name, details in potential_matches.items():
                identifier = name.lower().replace(target_keyword, "").strip()
                if identifier and identifier in user_prompt_lower: specific_targets.append((name, details))
            targets = specific_targets if specific_targets else list(potential_matches.items())
    else:
        for nickname, details in config.TUYA_DEVICES.items():
            if nickname.lower() in user_prompt_lower: targets.append((nickname, details)); break

    if not targets: return None

    responses = []
    for nickname, details in targets:
        if final_action == "DEBUG":
            responses.append(_handle_debug_status(nickname, details))
        elif final_action in ["ON", "OFF"]:
            if "sensor" in nickname.lower(): continue
            dps_index = 20 if "luz" in nickname.lower() or "lâmpada" in nickname.lower() else 1
            try:
                _handle_switch(nickname, details, final_action, dps_index)
                state = 'ligado' if final_action == 'ON' else 'desligado'
                responses.append(f"{nickname} {state}")
            except: responses.append(f"Erro no {nickname}")
        elif final_action == "STATUS":
            responses.append(_handle_sensor(nickname, details, user_prompt_lower))

    if not responses: return None
    return ", ".join(responses) + "."

# --- Processadores ---
def _handle_debug_status(nickname, details):
    (d, result, err) = _try_connect_with_versioning(details['id'], details['ip'], details['key'])
    if d: return f"{nickname}: Online"
    cached = _get_cached_status(nickname)
    return f"{nickname}: Offline (Cache: {bool(cached)})"

def _handle_switch(nickname, details, action, dps_index):
    (d, status, err) = _try_connect_with_versioning(details['id'], details['ip'], details['key'])
    if not d: raise Exception("incontactável")
    d.set_value(dps_index, True if action == "ON" else False, nowait=True)

def _handle_sensor(nickname, details, prompt):
    (d, data, err) = _try_connect_with_versioning(details['id'], details['ip'], details['key'])
    dps = data.get('dps') if d else {}
    if not dps:
        cached = _get_cached_status(nickname)
        if cached and 'dps' in cached: dps = cached['dps']
        else: return f"Sem dados do {nickname}."
    temp = dps.get('1') or dps.get('102'); hum = dps.get('2') or dps.get('103')
    parts = []
    if temp: parts.append(f"{float(temp)/10}°C")
    if hum: parts.append(f"{int(hum)}%")
    return f"{nickname}: {' '.join(parts)}" if parts else f"{nickname}: Dados estranhos."

# --- API Status ---
def get_status_for_device(nickname):
    if not hasattr(config, 'TUYA_DEVICES') or nickname not in config.TUYA_DEVICES: return {"state": "unreachable"}
    details = config.TUYA_DEVICES[nickname]
    (d, status, err) = _try_connect_with_versioning(details['id'], details['ip'], details['key'])
    dps = status.get('dps') if d else None
    if not dps:
        cached = _get_cached_status(nickname)
        if cached: dps = cached.get('dps')
    if not dps: return {"state": "unreachable"}

    if "sensor" in nickname.lower():
        res = {"state": "on"}
        t = dps.get('1') or dps.get('102'); h = dps.get('2') or dps.get('103')
        if t: res["temperature"] = float(t)/10
        if h: res["humidity"] = int(h)
        return res
    if "desumidificador" in nickname.lower():
        power = float(dps.get('19', 0))/10
        return {"state": "on" if dps.get('1') else "off", "power_w": power}
    idx = "20" if "luz" in nickname.lower() else "1"
    return {"state": "on" if dps.get(idx) else "off"}
