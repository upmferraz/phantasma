import discord
import httpx
import asyncio
import threading
import logging
import config
from datetime import datetime

# --- Configuração da Skill ---
# Esta skill não é ativada por voz local, serve apenas para carregar o daemon.
TRIGGER_TYPE = "contains"
TRIGGERS = [] 

# --- Definições de Permissões ---
# Palavras-chave para identificar skills permitidas (Meteorologia e Calculadora)
# Duplicamos aqui os triggers principais para evitar importar outros módulos e causar ciclos.
ALLOWED_SKILL_KEYWORDS = [
    # Meteorologia
    "tempo", "clima", "meteorologia", "previsão", "vai chover", "qualidade do ar",
    # Calculadora
    "quanto é", "calcula", "a dividir", "vezes", "somado", "subtraído", "+", "-", "*", "/"
]

# Cache de Quotas: { user_id: { "date": "YYYY-MM-DD", "count": 0 } }
_USER_QUOTAS = {}

# --- Setup do Logging ---
logger = logging.getLogger("DiscordSkill")

# --- Lógica do Bot Discord ---

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# URL da API local do Phantasma (comunica com o assistant.py via HTTP para thread safety)
PHANTASMA_API_URL = "http://127.0.0.1:5000/comando"

def _check_access(user_id, prompt_lower):
    """
    Retorna (AcessoPermitido: bool, MensagemErro: str)
    """
    # 1. Verificar se é Admin
    if hasattr(config, 'DISCORD_ADMIN_USERS') and user_id in config.DISCORD_ADMIN_USERS:
        return True, ""

    # 2. Verificar se é Standard
    if hasattr(config, 'DISCORD_STANDARD_USERS') and user_id in config.DISCORD_STANDARD_USERS:
        return _process_standard_quota(user_id, prompt_lower)

    # 3. Não autorizado
    return False, "Acesso negado."

def _process_standard_quota(user_id, prompt_lower):
    """
    Gere a lógica de limites para utilizadores standard.
    """
    # A. Verifica se é uma Skill Permitida (Weather/Calc) -> Uso Gratuito/Ilimitado
    is_allowed_skill = any(keyword in prompt_lower for keyword in ALLOWED_SKILL_KEYWORDS)
    if is_allowed_skill:
        return True, ""

    # B. Se for LLM (Pergunta geral), verificar quota diária
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Inicializa ou Reinicia quota se mudou o dia
    if user_id not in _USER_QUOTAS or _USER_QUOTAS[user_id]["date"] != today_str:
        _USER_QUOTAS[user_id] = {"date": today_str, "count": 0}

    current_count = _USER_QUOTAS[user_id]["count"]
    limit = getattr(config, 'DISCORD_DAILY_LLM_LIMIT', 3)

    if current_count < limit:
        _USER_QUOTAS[user_id]["count"] += 1
        return True, ""
    else:
        return False, f"Atingiste o teu limite diário de {limit} perguntas ao cérebro do Phantasma (as ferramentas de tempo e cálculo continuam disponíveis)."

async def _send_to_phantasma(prompt):
    """ Envia o texto para a API local e recebe a resposta """
    async with httpx.AsyncClient(timeout=120) as http_client:
        try:
            payload = {"prompt": prompt}
            # Usa a API local para processar (garante que passa pelo route_and_respond)
            response = await http_client.post(PHANTASMA_API_URL, json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "...")
        except Exception as e:
            return f"Erro de comunicação interna: {e}"

@client.event
async def on_ready():
    print(f"[Discord Skill] Logado como {client.user}")
    await client.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, 
        name="Buu!"
    ))

@client.event
async def on_message(message):
    # Ignorar mensagens do próprio bot
    if message.author == client.user:
        return

    # Lógica de ativação: DM ou Menção
    prompt = ""
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mention = client.user in message.mentions

    if is_dm:
        prompt = message.content
    elif is_mention:
        prompt = message.content.replace(f'<@{client.user.id}>', '').strip()
    else:
        return 

    if not prompt:
        return

    # --- VERIFICAÇÃO DE PERMISSÕES E QUOTAS ---
    allowed, error_msg = _check_access(message.author.id, prompt.lower())

    if not allowed:
        # Se for um user standard bloqueado, avisamos. Se for desconhecido, ignoramos ou logamos.
        if "limite diário" in error_msg:
            await message.channel.send(f"🚫 {error_msg}")
        else:
            print(f"[Discord Skill] Acesso negado para {message.author.name} ({message.author.id})")
        return

    print(f"[Discord Skill] Comando aceite de {message.author.name}: {prompt}")

    async with message.channel.typing():
        response_text = await _send_to_phantasma(prompt)
        
        # Corta a resposta se exceder o limite do Discord (2000 chars)
        if len(response_text) > 2000:
            response_text = response_text[:1990] + "..."

        await message.channel.send(response_text)

# --- Daemon Setup ---

def _run_discord_loop():
    """ 
    Função que corre numa thread separada. 
    Cria um novo event loop asyncio para o Discord.py não colidir com o Flask/Main thread.
    """
    token = getattr(config, 'DISCORD_BOT_TOKEN', None)
    if not token:
        print("[Discord Skill] ERRO: Token não configurado.")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(client.start(token))
    except Exception as e:
        print(f"[Discord Skill] O bot crashou: {e}")
    finally:
        loop.close()

def init_skill_daemon():
    """ Inicia o bot do Discord em background quando o assistente arranca. """
    if not hasattr(config, 'DISCORD_BOT_TOKEN'):
        return

    print("[Discord Skill] A iniciar daemon do Discord...")
    t = threading.Thread(target=_run_discord_loop, daemon=True)
    t.start()

# O handle é obrigatório pela estrutura do assistant.py, mas não faz nada via voz.
def handle(user_prompt_lower, user_prompt_full):
    return None
