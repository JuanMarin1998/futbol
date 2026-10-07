import requests
from django.conf import settings

BASE_URL = "https://v3.football.api-sports.io"

LIGAS_API_FOOTBALL = {
    "PD": {"id": 140, "nombre": "La Liga", "pais": "España"},
    "PL": {"id": 39, "nombre": "Premier League", "pais": "Inglaterra"},
    "BL1": {"id": 78, "nombre": "Bundesliga", "pais": "Alemania"},
    "SA": {"id": 135, "nombre": "Serie A", "pais": "Italia"},
    "FL1": {"id": 61, "nombre": "Ligue 1", "pais": "Francia"},
}

class APIFootballError(Exception):
    pass

def _headers():
    key = settings.API_FOOTBALL_KEY
    if not key:
        raise APIFootballError("No se encontró API_FOOTBALL_KEY en .env.")
    return {"x-apisports-key": key}

def _get(endpoint, params=None):
    response = requests.get(f"{BASE_URL}/{endpoint}", headers=_headers(), params=params or {}, timeout=20)
    if response.status_code != 200:
        raise APIFootballError(f"API-Football HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if data.get("errors"):
        raise APIFootballError(f"API-Football: {data['errors']}")
    return data.get("response", [])

def obtener_liga(codigo, temporada):
    return _get("leagues", {"id": LIGAS_API_FOOTBALL[codigo]["id"], "season": temporada})

def obtener_equipos(codigo, temporada):
    return _get("teams", {"league": LIGAS_API_FOOTBALL[codigo]["id"], "season": temporada})

def obtener_partidos(codigo, temporada, fecha_desde=None, fecha_hasta=None):
    params = {"league": LIGAS_API_FOOTBALL[codigo]["id"], "season": temporada}
    if fecha_desde: params["from"] = fecha_desde
    if fecha_hasta: params["to"] = fecha_hasta
    return _get("fixtures", params)

def obtener_estadisticas_partido(fixture_id):
    return _get("fixtures/statistics", {"fixture": fixture_id})

def obtener_alineaciones(fixture_id):
    return _get("fixtures/lineups", {"fixture": fixture_id})

def obtener_eventos(fixture_id):
    return _get("fixtures/events", {"fixture": fixture_id})

def obtener_jugadores_equipo(team_id, temporada, pagina=1):
    return _get("players", {"team": team_id, "season": temporada, "page": pagina})

def obtener_lesiones(temporada, codigo=None):
    params = {"season": temporada}
    if codigo: params["league"] = LIGAS_API_FOOTBALL[codigo]["id"]
    return _get("injuries", params)
