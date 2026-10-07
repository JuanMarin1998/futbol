"""
Cliente para consumir la API de football-data.org

Documentación oficial: https://www.football-data.org/documentation/quickstart

Códigos de competición que vamos a usar (las 5 ligas principales):
    PD  = La Liga (España)
    PL  = Premier League (Inglaterra)
    BL1 = Bundesliga (Alemania)
    SA  = Serie A (Italia)
    FL1 = Ligue 1 (Francia)
"""

import requests
from django.conf import settings

BASE_URL = "https://api.football-data.org/v4"

LIGAS_PRINCIPALES = {
    "PD": "La Liga",
    "PL": "Premier League",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
}


class FootballDataError(Exception):
    """Error al consultar la API de football-data.org."""


def _headers():
    token = settings.FOOTBALL_DATA_TOKEN
    if not token:
        raise FootballDataError(
            "No se encontró FOOTBALL_DATA_TOKEN. Revisa tu archivo .env."
        )
    return {"X-Auth-Token": token}


def obtener_equipos(codigo_liga: str) -> list[dict]:
    """Trae la lista de equipos de una competición."""
    url = f"{BASE_URL}/competitions/{codigo_liga}/teams"
    resp = requests.get(url, headers=_headers(), timeout=15)
    if resp.status_code != 200:
        raise FootballDataError(f"Error {resp.status_code} al traer equipos de {codigo_liga}: {resp.text}")
    return resp.json().get("teams", [])


def obtener_partidos(codigo_liga: str, estado: str | None = None, fecha_desde=None, fecha_hasta=None) -> list[dict]:
    """
    Trae partidos de una competición.
    estado puede ser: SCHEDULED, LIVE, IN_PLAY, PAUSED, FINISHED, POSTPONED, CANCELLED
    """
    url = f"{BASE_URL}/competitions/{codigo_liga}/matches"
    params = {}
    if estado:
        params["status"] = estado
    if fecha_desde:
        params["dateFrom"] = fecha_desde
    if fecha_hasta:
        params["dateTo"] = fecha_hasta

    resp = requests.get(url, headers=_headers(), params=params, timeout=15)
    if resp.status_code != 200:
        raise FootballDataError(f"Error {resp.status_code} al traer partidos de {codigo_liga}: {resp.text}")
    return resp.json().get("matches", [])


def obtener_equipo(id_equipo: int) -> dict:
    """Trae el detalle de un equipo: datos generales + plantilla de jugadores."""
    url = f"{BASE_URL}/teams/{id_equipo}"
    resp = requests.get(url, headers=_headers(), timeout=15)
    if resp.status_code != 200:
        raise FootballDataError(f"Error {resp.status_code} al traer el equipo {id_equipo}: {resp.text}")
    return resp.json()


def obtener_partidos_equipo(id_equipo: int, limite: int = 10) -> list[dict]:
    """Trae los últimos partidos finalizados de un equipo (para calcular su racha/estadísticas)."""
    url = f"{BASE_URL}/teams/{id_equipo}/matches"
    params = {"status": "FINISHED", "limit": limite}
    resp = requests.get(url, headers=_headers(), params=params, timeout=15)
    if resp.status_code != 200:
        raise FootballDataError(f"Error {resp.status_code} al traer partidos del equipo {id_equipo}: {resp.text}")
    return resp.json().get("matches", [])


def calcular_estadisticas_equipo(id_equipo: int, partidos: list[dict]) -> dict:
    """
    Calcula estadísticas simples de rendimiento a partir de los últimos partidos:
    victorias, empates, derrotas, goles a favor/en contra, racha reciente.
    """
    victorias = empates = derrotas = goles_favor = goles_contra = 0
    racha = []  # lista de "G", "E", "P" del más reciente al más antiguo

    for p in partidos:
        es_local = p["homeTeam"]["id"] == id_equipo
        gf = p["score"]["fullTime"]["home"] if es_local else p["score"]["fullTime"]["away"]
        gc = p["score"]["fullTime"]["away"] if es_local else p["score"]["fullTime"]["home"]

        if gf is None or gc is None:
            continue

        goles_favor += gf
        goles_contra += gc

        if gf > gc:
            victorias += 1
            racha.append("G")
        elif gf == gc:
            empates += 1
            racha.append("E")
        else:
            derrotas += 1
            racha.append("P")

    jugados = victorias + empates + derrotas

    return {
        "jugados": jugados,
        "victorias": victorias,
        "empates": empates,
        "derrotas": derrotas,
        "goles_favor": goles_favor,
        "goles_contra": goles_contra,
        "diferencia_goles": goles_favor - goles_contra,
        "promedio_goles_favor": round(goles_favor / jugados, 2) if jugados else 0,
        "promedio_goles_contra": round(goles_contra / jugados, 2) if jugados else 0,
        "racha": racha,
    }


def obtener_tabla_posiciones(codigo_liga: str) -> list[dict]:
    """Trae la tabla de posiciones de una competición."""
    url = f"{BASE_URL}/competitions/{codigo_liga}/standings"
    resp = requests.get(url, headers=_headers(), timeout=15)
    if resp.status_code != 200:
        raise FootballDataError(f"Error {resp.status_code} al traer la tabla de {codigo_liga}: {resp.text}")
    data = resp.json()
    standings = data.get("standings", [])
    # Tomamos la tabla general (TOTAL), que es la que casi siempre se quiere ver
    for tabla in standings:
        if tabla.get("type") == "TOTAL":
            return tabla.get("table", [])
    return standings[0].get("table", []) if standings else []
