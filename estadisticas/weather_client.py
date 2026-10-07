import requests
from datetime import datetime

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

class OpenMeteoError(Exception):
    pass

def buscar_coordenadas(nombre, pais=None):
    params = {"name": nombre, "count": 5, "language": "es", "format": "json"}
    if pais: params["countryCode"] = pais
    r = requests.get(GEOCODING_URL, params=params, timeout=15)
    if r.status_code != 200: raise OpenMeteoError(f"Open-Meteo geocoding HTTP {r.status_code}")
    resultados = r.json().get("results", [])
    return resultados[0] if resultados else None

def obtener_clima_historico(latitud, longitud, fecha, hora_utc):
    params = {
        "latitude": latitud, "longitude": longitud, "start_date": fecha, "end_date": fecha,
        "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,precipitation_probability,wind_speed_10m,weather_code",
        "timezone": "UTC",
    }
    r = requests.get(ARCHIVE_URL, params=params, timeout=20)
    if r.status_code != 200: raise OpenMeteoError(f"Open-Meteo archive HTTP {r.status_code}")
    hourly = r.json().get("hourly", {})
    times = hourly.get("time", [])
    if not times: return None
    target = datetime.fromisoformat(f"{fecha}T{hora_utc[:5]}").timestamp()
    idx = min(range(len(times)), key=lambda i: abs(datetime.fromisoformat(times[i]).timestamp() - target))
    return {key: values[idx] for key, values in hourly.items() if values}
