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
