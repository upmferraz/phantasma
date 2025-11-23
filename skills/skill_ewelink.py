import config
import asyncio
import json
import os
import time
import threading
import traceback

# --- CONFIGURAÇÃO ---
CACHE_FILE = "/opt/phantasma/ewelink_cache.json"
POLL_INTERVAL = 60  # Consulta a cloud a cada 60 segundos

TRIGGER_TYPE = "contains"
TRIGGERS = ["carregador", "carro", "ewelink", "tomada do carro"]

ACTIONS_ON = ["liga", "ligar", "acende", "ativa", "inicia", "põe a carregar"]
ACTIONS_OFF = ["desliga", "desligar", "apaga", "desativa", "para", "pára"]
STATUS_TRIGGERS = ["consumo", "gastar", "leitura", "quanto", "estado", "como está"]

# Tenta importar a biblioteca (sem patches, usa o constants.py do disco)
try:
    import ewelink
except ImportError:
    ewelink = None
    print("[eWeLink] ERRO: Biblioteca não encontrada.")

# --- Helpers de Cache ---

def _save_cache(data):
    try:
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, 'w') as f: json.dump(data, f)
        os.rename(tmp, CACHE_FILE)
    except Exception as e:
        print(f"[eWeLink] Erro ao escrever cache: {e}")

def _get_cached_data(device_id):
    if not os.path.exists(CACHE_FILE): return None
    try:
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
            return data.get(device_id)
    except: return None

# --- Lógica do Daemon (Polling em Background) ---

async def _poll_task():
    if not ewelink: return

    region = getattr(config, 'EWELINK_REGION', 'eu')
    
    try:
        client = ewelink.Client(
            password=config.EWELINK_PASSWORD, 
            email=config.EWELINK_USERNAME, 
            region=region
        )
        await client.login()
        
        if client.devices:
            cache_data = {}
            for device in client.devices:
                # --- CORREÇÃO CRÍTICA: 4 Formas de encontrar o ID ---
                dev_id = getattr(device, 'deviceid', None)
                if not dev_id: dev_id = getattr(device, 'device_id', None)
                if not dev_id: dev_id = getattr(device, 'id', None)
                if not dev_id and hasattr(device, 'raw_data'):
                    # Fallback final: procurar no dicionário raw_data
                    dev_id = device.raw_data.get('deviceid')
                
                if not dev_id:
                    print(f"[eWeLink] AVISO: Dispositivo '{device.name}' ignorado (sem ID).")
                    continue
                # ----------------------------------------------------

                # Extrair parâmetros do OBJETO Params
                params = getattr(device, 'params', None)
                
                power = getattr(params, 'power', None)
                current = getattr(params, 'current', None)
                voltage = getattr(params, 'voltage', None)

                cache_data[dev_id] = {
                    "name": device.name,
                    "state": "on" if device.state else "off",
                    "online": device.online,
                    "timestamp": time.time(),
                    "power": power,
                    "current": current,
                    "voltage": voltage
                }
            
            if cache_data:
                _save_cache(cache_data)
            
    except Exception as e:
        print(f"[eWeLink Daemon] Erro: {e}")
    finally:
        try:
            if client and client.http and client.http.session and not client.http.session.closed:
                await client.http.session.close()
        except: pass

def _daemon_loop():
    # Executa imediatamente no arranque
    try: asyncio.run(_poll_task())
    except: pass

    while True:
        time.sleep(POLL_INTERVAL)
        try:
            asyncio.run(_poll_task())
        except Exception as e:
            print(f"[eWeLink Daemon] Crash: {e}")

def init_skill_daemon():
    """ Chamado automaticamente pelo assistant.py """
    if ewelink:
        print("[eWeLink] A iniciar polling em background...")
        t = threading.Thread(target=_daemon_loop, daemon=True)
        t.start()

# --- Ações de Controlo (Imediatas) ---

async def _execute_control_action(action, target_id):
    try:
        region = getattr(config, 'EWELINK_REGION', 'eu')
        client = ewelink.Client(password=config.EWELINK_PASSWORD, email=config.EWELINK_USERNAME, region=region)
        await client.login()
        
        device = client.get_device(target_id)
        
        if not device: 
            await client.http.session.close()
            return {"success": False, "error": "Dispositivo não encontrado na cloud."}
        
        if action == "on": await device.on()
        elif action == "off": await device.off()
        
        await asyncio.sleep(0.5)
        await client.http.session.close()
        
        # Força atualização do daemon para a UI refletir a mudança
        threading.Thread(target=lambda: asyncio.run(_poll_task())).start()
        
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- APIs da Skill ---

def get_status_for_device(nickname):
    if nickname not in getattr(config, 'EWELINK_DEVICES', {}): return {"state": "unreachable"}
    
    conf = config.EWELINK_DEVICES[nickname]
    target_id = conf.get("device_id") if isinstance(conf, dict) else None
    
    data = _get_cached_data(target_id)
    if not data: return {"state": "unreachable"}
    
    ui_res = {"state": data.get("state", "off")}
    if data.get("power"):
        try: ui_res["power_w"] = float(data["power"])
        except: pass
    return ui_res

def handle(user_prompt_lower, user_prompt_full):
    if not hasattr(config, 'EWELINK_DEVICES'): return None

    action = None
    if any(x in user_prompt_lower for x in ACTIONS_OFF): action = "off"
    elif any(x in user_prompt_lower for x in ACTIONS_ON): action = "on"
    elif any(x in user_prompt_lower for x in STATUS_TRIGGERS): action = "status"
    
    if not action: return None

    target_conf = None; target_nickname = ""
    for nickname, conf in config.EWELINK_DEVICES.items():
        if nickname.lower() in user_prompt_lower: 
            target_conf = conf; target_nickname = nickname; break
    
    # Fallback "carro"
    if not target_conf and "carro" in user_prompt_lower:
        if config.EWELINK_DEVICES:
            target_nickname = list(config.EWELINK_DEVICES.keys())[0]
            target_conf = config.EWELINK_DEVICES[target_nickname]

    if not target_conf: return None
    target_id = target_conf.get("device_id")

    # 1. Leitura (Cache Local)
    if action == "status":
        data = _get_cached_data(target_id)
        if not data: return f"A recolher dados do {target_nickname}..."
        
        parts = [f"O {target_nickname} está {data.get('state')}"]
        if data.get('power'): parts.append(f"a gastar {data['power']} Watts")
        if data.get('current'): parts.append(f"({data['current']} A)")
        
        return ", ".join(parts) + "."

    # 2. Escrita (Cloud)
    print(f"eWeLink: A executar '{action}' em '{target_nickname}'...")
    res = asyncio.run(_execute_control_action(action, target_id))
    
    if not res.get("success"): return f"Erro: {res.get('error')}"
    return f"{target_nickname.capitalize()} {'ligado' if action=='on' else 'desligado'}."
