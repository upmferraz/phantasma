import psutil
import re

# --- Configuração da Skill ---
TRIGGER_TYPE = "contains"
TRIGGERS = ["sistema", "cpu", "ram", "memória", "disco", "armazenamento", "ocupação", "temperatura"]

# Lista de 'fstype' (sistemas de ficheiros) que queremos IGNORAR.
FSTYPE_IGNORADOS = [
    "squashfs", 
    "tmpfs", 
    "devtmpfs", 
    "loop", 
    "overlay", 
    "iso9660", 
    "autofs"
]

# Lista de 'mountpoint' (pontos de montagem) exatos que queremos IGNORAR.
MOUNTPOINT_IGNORADOS = [
    "/boot/efi"
]

def format_bytes(b):
    """ Converte bytes para GB ou TB de forma legível (formato pedido). """
    if b >= 1024**4: # TB
        val = b / 1024**4
        return f"{val:.1f} Terabaites"
    # GB
    val = b / 1024**3
    return f"{val:.1f} gigas"

# --- NOVO ---
def get_temperature():
    """ Obtém a temperatura mais alta do sistema (ex: CPU Package, PCH). """
    try:
        if not hasattr(psutil, "sensors_temperatures"):
            return "" # Função não suportada neste SO

        temps = psutil.sensors_temperatures()
        if not temps:
            return "" # Nenhum sensor encontrado

        all_current_temps = []
        # Itera todos os 'chips' (ex: 'coretemp', 'pch_cannonlake')
        for sensor_list in temps.values():
            # Itera todas as leituras desse chip
            for sensor in sensor_list:
                if sensor.current:
                    all_current_temps.append(sensor.current)
        
        if not all_current_temps:
            return ""

        # Devolve a temperatura mais alta encontrada, formatada
        max_temp = max(all_current_temps)
        return f"Temperatura {max_temp:.0f}°C" # ex: "Temperatura 44°C"

    except Exception as e:
        print(f"ERRO (Skill System/Temp): {e}")
        return "" # Falha silenciosamente

# --- MODIFICADO ---
def get_cpu_ram_temp():
    """ Helper para obter CPU, RAM e Temperatura (formato pedido). """
    try:
        cpu = psutil.cpu_percent(interval=0.1) 
        ram = psutil.virtual_memory()
        
        # Chama a nova função de temperatura
        temp_info = get_temperature() 

        response = f"Processador a {cpu:.1f}% Memória a {ram.percent}%"
        
        # Adiciona a temperatura à string, se foi encontrada
        if temp_info:
            response += f" {temp_info}" # Adiciona um espaço antes
            
        return response
    except Exception as e:
        print(f"ERRO (Skill System/CPU/RAM): {e}")
        return "Não consegui verificar o estado do CPU e RAM."

def get_disks():
    """ 
    Helper para obter info de discos, usando nomes genéricos
    (Disco 1, Disco 2) e mostrando apenas o espaço livre.
    """
    try:
        response_lines = []
        found_disks = 0
        
        partitions = psutil.disk_partitions()
        
        if not partitions:
             return "Não foi possível encontrar partições de disco."

        for part in partitions:
            # Filtros
            if part.fstype in FSTYPE_IGNORADOS:
                continue
            if part.mountpoint in MOUNTPOINT_IGNORADOS:
                continue
            
            try:
                usage = psutil.disk_usage(part.mountpoint)
                
                if usage.total > 0:
                    found_disks += 1
                    line = (
                        f"Disco {found_disks} {format_bytes(usage.free)} livres"
                    )
                    response_lines.append(line)
            except Exception:
                pass 

        if found_disks == 0:
            return "Não foram encontrados discos físicos monitorizáveis."

        return ", ".join(response_lines)

    except Exception as e:
        print(f"ERRO (Skill System/Disco): {e}")
        return "Desculpa, chefe, não consegui verificar a ocupação dos discos."

# --- MODIFICADO ---
def handle(user_prompt_lower, user_prompt_full):
    """ 
    Fornece estatísticas do sistema (CPU, RAM, Temp, e Discos).
    """
    
    # 1. Pedido específico de DISCO
    if any(trigger in user_prompt_lower for trigger in ["disco", "armazenamento", "ocupação"]):
        print("Skill System: A verificar (só) ocupação dos discos...")
        return get_disks()

    # 2. Pedido específico de CPU/RAM/TEMP
    if any(trigger in user_prompt_lower for trigger in ["cpu", "ram", "memória", "temperatura"]):
        print("Skill System: A verificar (só) CPU, RAM e Temp...")
        return get_cpu_ram_temp()

    # 3. Pedido genérico "sistema" (ou qualquer outro trigger)
    print("Skill System: A verificar o estado completo (CPU, RAM, Temp, Discos)...")
    
    # Chama a função que agora inclui a temperatura
    cpu_ram_temp_info = get_cpu_ram_temp() 
    disk_info = get_disks()
    
    # Junta tudo
    return f"{cpu_ram_temp_info}, {disk_info}"
