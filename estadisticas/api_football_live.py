"""Cliente para datos de fútbol en vivo con API-Sports / API-Football v3."""

import os
import requests


class APIFootballLiveClient:
    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self, api_key=None, timeout=10):
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY", "")
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("Falta API_FOOTBALL_KEY. Configúralo en .env.")

    def _get(self, params):
        response = requests.get(
            f"{self.BASE_URL}/fixtures",
            params=params,
            headers={"x-apisports-key": self.api_key},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def obtener_en_vivo(self):
        return self._get({"live": "all"})

    def _get_path(self, path, params):
        response = requests.get(
            f"{self.BASE_URL}/{path}",
            params=params,
            headers={"x-apisports-key": self.api_key},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def obtener_detalle_partido(self, fixture_id):
        """Obtiene fixture + eventos + alineaciones + estadísticas + jugadores en una sola llamada."""
        return self._get({"id": str(fixture_id)})

    def obtener_cobertura_liga(self, league_id, season):
        """Obtiene la cobertura de datos de una liga/temporada."""
        from django.core.cache import cache
        key = f"api_football_league_coverage_v1_{league_id}_{season}"
        cached = cache.get(key)
        if cached is not None:
            return cached

        payload = self._get_path(
            "leagues",
            {"id": str(league_id), "season": str(season)},
        )
        response = payload.get("response") or []
        coverage = {}
        if response:
            seasons = response[0].get("seasons") or []
            for item in seasons:
                if str(item.get("year")) == str(season):
                    coverage = item.get("coverage") or {}
                    break

        cache.set(key, coverage, 3600)
        return coverage

    def obtener_estadisticas_partido(self, fixture_id):
        from django.core.cache import cache
        key = f"api_football_fixture_stats_v1_{fixture_id}"
        cached = cache.get(key)
        if cached is not None:
            return cached
        payload = self._get_path("fixtures/statistics", {"fixture": str(fixture_id)})
        data = payload.get("response") or []
        cache.set(key, data, 60)
        return data

    def obtener_alineaciones_partido(self, fixture_id):
        from django.core.cache import cache
        key = f"api_football_fixture_lineups_v1_{fixture_id}"
        cached = cache.get(key)
        if cached is not None:
            return cached
        payload = self._get_path("fixtures/lineups", {"fixture": str(fixture_id)})
        data = payload.get("response") or []
        cache.set(key, data, 900)
        return data

    def obtener_jugadores_partido(self, fixture_id):
        from django.core.cache import cache
        key = f"api_football_fixture_players_v1_{fixture_id}"
        cached = cache.get(key)
        if cached is not None:
            return cached
        payload = self._get_path("fixtures/players", {"fixture": str(fixture_id)})
        data = payload.get("response") or []
        cache.set(key, data, 60)
        return data
