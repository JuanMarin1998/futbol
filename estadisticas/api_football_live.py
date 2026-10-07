"""Cliente API-Football dedicado exclusivamente a datos LIVE.

La aplicación usa football-data.org + PostgreSQL para históricos y temporadas.
Este cliente queda deliberadamente limitado al flujo LIVE de API-Football:
- partidos en vivo;
- detalle de un fixture;
- eventos;
- estadísticas de equipos;
- alineaciones;
- estadísticas de jugadores.

No realiza consultas por liga/temporada ni endpoints históricos, evitando
restricciones de planes Free sobre temporadas.
"""

import os

import requests


class APIFootballAPIError(RuntimeError):
    """Error devuelto por API-Football o por una respuesta HTTP inválida."""

    def __init__(self, message, *, status_code=None, errors=None):
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors or {}


class APIFootballRateLimitError(APIFootballAPIError):
    """La API rechazó la petición por límite de cuota/frecuencia."""


class APIFootballLiveClient:
    BASE_URL = "https://v3.football.api-sports.io"
    CACHE_LINEUPS_SECONDS = 900
    CACHE_STATS_SECONDS = 60
    CACHE_PLAYERS_SECONDS = 60

    def __init__(self, api_key=None, timeout=10, session=None):
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY", "")
        self.timeout = timeout
        self.session = session or requests.Session()

        if not self.api_key:
            raise ValueError("Falta API_FOOTBALL_KEY. Configúralo en .env.")

        self.session.headers.update(
            {
                "x-apisports-key": self.api_key,
                "Accept": "application/json",
            }
        )

    def _request(self, path, params=None):
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        response = self.session.get(
            url,
            params=params or {},
            timeout=self.timeout,
        )

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        errors = payload.get("errors") or {}

        if response.status_code == 429:
            raise APIFootballRateLimitError(
                "API-Football alcanzó el límite de solicitudes.",
                status_code=response.status_code,
                errors=errors,
            )

        if response.status_code >= 400:
            raise APIFootballAPIError(
                f"API-Football respondió HTTP {response.status_code}.",
                status_code=response.status_code,
                errors=errors,
            )

        if errors:
            raise APIFootballAPIError(
                f"API-Football devolvió errores: {errors}",
                status_code=response.status_code,
                errors=errors,
            )

        payload["_api_meta"] = {
            "status_code": response.status_code,
            "rate_limits": {
                key: value
                for key, value in response.headers.items()
                if key.lower().startswith("x-ratelimit")
            },
        }
        return payload

    def _cache_get(self, key):
        try:
            from django.core.cache import cache
            return cache.get(key)
        except Exception:
            return None

    def _cache_set(self, key, value, timeout):
        try:
            from django.core.cache import cache
            cache.set(key, value, timeout)
        except Exception:
            pass

    def _cached_request(self, key, path, params, timeout):
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        payload = self._request(path, params)
        self._cache_set(key, payload, timeout)
        return payload

    # ------------------------------------------------------------------
    # LIVE
    # ------------------------------------------------------------------

    def obtener_en_vivo(self, leagues=None):
        """Obtiene exclusivamente partidos actualmente en juego."""
        live_value = "all" if not leagues else "-".join(map(str, leagues))
        return self._request("fixtures", {"live": live_value})

    def obtener_detalle_partido(self, fixture_id):
        """Obtiene el bloque completo disponible para un fixture LIVE.

        /fixtures?id=... puede incluir fixture, eventos, alineaciones,
        estadísticas de equipos y estadísticas de jugadores.
        """
        return self._request("fixtures", {"id": str(fixture_id)})

    def obtener_eventos_partido(self, fixture_id):
        return self._request(
            "fixtures/events",
            {"fixture": str(fixture_id)},
        )

    def obtener_estadisticas_partido(self, fixture_id, team_id=None, stat_type=None):
        params = {"fixture": str(fixture_id)}
        if team_id is not None:
            params["team"] = str(team_id)
        if stat_type:
            params["type"] = str(stat_type)

        return self._cached_request(
            f"api_football_live_stats_{fixture_id}_{team_id or 'all'}_{stat_type or 'all'}",
            "fixtures/statistics",
            params,
            self.CACHE_STATS_SECONDS,
        )

    def obtener_alineaciones_partido(self, fixture_id):
        return self._cached_request(
            f"api_football_live_lineups_{fixture_id}",
            "fixtures/lineups",
            {"fixture": str(fixture_id)},
            self.CACHE_LINEUPS_SECONDS,
        )

    def obtener_jugadores_partido(self, fixture_id):
        return self._cached_request(
            f"api_football_live_players_{fixture_id}",
            "fixtures/players",
            {"fixture": str(fixture_id)},
            self.CACHE_PLAYERS_SECONDS,
        )
