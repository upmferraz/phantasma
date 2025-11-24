import re
import httpx
import unicodedata
import config  

# --- Configuração da Skill ---
TRIGGER_TYPE = "contains"
TRIGGERS = ["tempo", "clima", "meteorologia", "previsão", "vai chover", "vai estar", "qualidade do ar"]

# --- Caches em memória ---
_IPMA_LOCATIONS_CACHE = {}
_IPMA_WEATHER_TYPES_CACHE = {}

def _normalize(text):
    """ Remove acentos e põe em minúsculas. """
    try:
        nfkd = unicodedata.normalize('NFKD', text)
        return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()
    except:
        return text.lower().strip()

def _get_ipma_locations():
    """ Cache de locais do IPMA. """
    global _IPMA_LOCATIONS_CACHE
    if _IPMA_LOCATIONS_CACHE: return _IPMA_LOCATIONS_CACHE
    try:
        url = "https://api.ipma.pt/open-data/distrits-islands.json"
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        for entry in data.get('data', []):
            name = entry.get('local')
            global_id = entry.get('globalIdLocal')
            if name and global_id:
                _IPMA_LOCATIONS_CACHE[_normalize(name)] = global_id
        return _IPMA_LOCATIONS_CACHE
    except Exception as e:
        print(f"ERRO IPMA (Locations): {e}")
        return {}

def _get_weather_type_desc(type_id):
    """ Cache de descrições do tempo do IPMA. """
    global _IPMA_WEATHER_TYPES_CACHE
    if not _IPMA_WEATHER_TYPES_CACHE:
        try:
            url = "https://api.ipma.pt/open-data/weather-type-classe.json"
            resp = httpx.get(url, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                for entry in data.get('data', []):
                    _IPMA_WEATHER_TYPES_CACHE[entry['idWeatherType']] = entry['descIdWeatherTypePT']
        except: pass

    fallback = {
        1: "céu limpo", 2: "céu pouco nublado", 3: "céu parcialmente nublado",
        4: "céu muito nublado", 5: "céu encoberto", 6: "chuva",
        7: "aguaceiros fracos", 8: "aguaceiros fortes", 9: "chuva",
        10: "chuva fraca", 11: "chuva forte", 16: "nevoeiro"
    }
    return _IPMA_WEATHER_TYPES_CACHE.get(type_id, fallback.get(type_id, "estado incerto"))

def _get_uv_desc(uv):
    if uv is None: return ""
    if uv < 3: return "baixo"
    if uv < 6: return "moderado"
    if uv < 8: return "alto"
    if uv < 11: return "muito alto"
    return "extremo"

def _get_iqair_desc(aqi_us):
    """ Escala US AQI da IQAir. """
    if aqi_us is None: return ""
    if aqi_us <= 50: return "boa"
    if aqi_us <= 100: return "moderada"
    if aqi_us <= 150: return "insalubre para grupos sensíveis"
    if aqi_us <= 200: return "insalubre"
    if aqi_us <= 300: return "muito insalubre"
    return "perigosa"

def handle(user_prompt_lower, user_prompt_full):
    """ Skill Meteorologia (IPMA + OpenMeteo UV + IQAir). """
    
    # 1. Detetar Localização
    target_city_norm = "porto"
    target_id = 1131200 
    
    match = re.search(r'\b(no|na|em|para)\s+(?!(?:hoje|amanhã)\b)([A-Za-zÀ-ú\s]+)', user_prompt_lower)
    if match:
        city_extracted = _normalize(match.group(2))
        locations = _get_ipma_locations()
        if city_extracted in locations:
            target_city_norm = city_extracted
            target_id = locations[city_extracted]
        else:
            print(f"IPMA: Cidade '{city_extracted}' não encontrada. A usar Porto.")

    # 2. Determinar dia
    day_index = 0
    day_name = "hoje"
    if "amanhã" in user_prompt_lower:
        day_index = 1
        day_name = "amanhã"

    try:
        client = httpx.Client(timeout=10.0)

        # 3. Pedir Meteorologia (IPMA)
        url_ipma = f"https://api.ipma.pt/open-data/forecast/meteorology/cities/daily/{target_id}.json"
        resp_ipma = client.get(url_ipma)
        resp_ipma.raise_for_status()
        data_ipma = resp_ipma.json()
        
        forecast = data_ipma['data'][day_index]
        t_min = forecast.get('tMin')
        t_max = forecast.get('tMax')
        precip = float(forecast.get('precipitaProb', '0'))
        w_desc = _get_weather_type_desc(forecast.get('idWeatherType')).lower()
        lat = forecast.get('latitude')
        lon = forecast.get('longitude')

        # 4. Pedir UV (Open-Meteo) e AQI (IQAir)
        uv_val = None
        aqi_val = None
        aqi_desc = ""

        # A) Open-Meteo SÓ para UV
        try:
            url_om = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=uv_index"
            resp_om = client.get(url_om, timeout=2.0)
            if resp_om.status_code == 200:
                uv_val = resp_om.json().get('current', {}).get('uv_index')
        except: pass

        # B) IQAir para Qualidade do Ar (Se tiver chave)
        if hasattr(config, 'IQAIR_KEY') and config.IQAIR_KEY:
            try:
                # Usa as coordenadas do IPMA para encontrar a estação mais próxima (ex: Paranhos)
                url_iq = f"http://api.airvisual.com/v2/nearest_city?lat={lat}&lon={lon}&key={config.IQAIR_KEY}"
                resp_iq = client.get(url_iq, timeout=4.0)
                if resp_iq.status_code == 200:
                    iq_data = resp_iq.json().get('data', {})
                    # AQI US é o padrão internacional da IQAir
                    aqi_val = iq_data.get('current', {}).get('pollution', {}).get('aqius')
                    aqi_desc = _get_iqair_desc(aqi_val)
            except Exception as e:
                print(f"Erro IQAir: {e}")
        else:
            if "qualidade do ar" in user_prompt_lower:
                print("Aviso: Chave IQAir não configurada no config.py")

        # 5. Construir Resposta
        
        # A) Pergunta rápida sobre chuva
        wants_rain = any(x in user_prompt_lower for x in ["chover", "chuva", "molhar", "água"])
        if wants_rain:
            if precip >= 70: txt = f"Sim, é quase certo ({precip}%). "
            elif precip >= 30: txt = f"Talvez, há {precip}% de hipóteses. "
            elif precip > 0: txt = f"Pouco provável, apenas {precip}%. "
            else: txt = "Não, não se prevê chuva. "
            return txt + f"Em {target_city_norm.title()} espera-se {w_desc}."

        # B) Resposta Geral
        response = (
            f"Previsão para {day_name} em {target_city_norm.title()}: "
            f"{w_desc}, máxima {t_max}° e mínima {t_min}°."
        )
        if precip > 0:
            response += f" Probabilidade de chuva: {precip}%."

        if uv_val is not None:
            desc = _get_uv_desc(uv_val)
            response += f" Índice UV {uv_val} ({desc})."
            
        if aqi_val is not None:
            response += f" Qualidade do ar: {aqi_desc} ({aqi_val})."

        return response

    except Exception as e:
        print(f"ERRO skill_weather: {e}")
        return "Não consegui aceder à meteorologia."
