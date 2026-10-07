"""Cliente robusto para API-Sports / API-Football v3.

La API usa el fixture_id como entidad central. Este cliente concentra:
- autenticación y transporte HTTP;
- errores de API y límites de cuota;
- caché opcional para datos relativamente estables;
- cobertura por competición/temporada;
- endpoints de LIVE, partidos, equipos, jugadores, tablas, H2H,
  predicciones, cuotas, lesiones y referencias;
- paginación para endpoints que devuelven varias páginas.

Los métodos devuelven el payload original de API-Football para conservar
compatibilidad con el código existente.
"""

import os
import time

import requests


class APIFootballAPIError(RuntimeError):
    """Error devuelto por API-Football o por una respuesta HTTP inválida."""

    def __init__(self, message, *, status_code=None, errors=None):
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors or []


class APIFootballRateLimitError(APIFootballAPIError):
    """La API rechazó una llamada por límite de frecuencia/cuota."""


class APIFootballLiveClient:
    BASE_URL = "https://v3.football.api-sports.io"

    # Tiempos orientativos según la frecuencia de actualización de API-Football.
    CACHE_COVERAGE_SECONDS = 3600
    CACHE_REFERENCE_SECONDS = 86400
    CACHE_LINEUPS_SECONDS = 900
    CACHE_STATS_SECONDS = 60
    CACHE_PLAYERS_SECONDS = 60
    CACHE_PREDICTIONS_SECONDS = 3600
    CACHE_STANDINGS_SECONDS = 3600
    CACHE_TEAM_STATS_SECONDS = 43200
    CACHE_INJURIES_SECONDS = 14400

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

    # ------------------------------------------------------------------
    # Transporte / errores / cuota
    # ------------------------------------------------------------------

    def _request(self, path, params=None):
        """Realiza una petición GET y conserva metadatos útiles de la API."""
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        response = self.session.get(
            url,
            params=params or {},
            timeout=self.timeout,
        )

        rate_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower().startswith("x-ratelimit")
        }

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        errors = payload.get("errors") or []

        if response.status_code == 429:
            raise APIFootballRateLimitError(
                "API-Football alcanzó un límite de solicitudes.",
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

        # No altera response/results/paging; solo agrega metadatos internos.
        payload["_api_meta"] = {
            "status_code": response.status_code,
            "rate_limits": rate_headers,
        }
        return payload

    def _get(self, params=None):
        """Compatibilidad con el cliente anterior: /fixtures."""
        return self._request("fixtures", params)

    def _get_path(self, path, params=None):
        """Compatibilidad con el cliente anterior."""
        return self._request(path, params)

    @staticmethod
    def _cache_get(key):
        try:
            from django.core.cache import cache
            return cache.get(key)
        except Exception:
            return None

    @staticmethod
    def _cache_set(key, value, timeout):
        try:
            from django.core.cache import cache
            cache.set(key, value, timeout)
        except Exception:
            # El cliente también puede utilizarse fuera de Django.
            pass

    def _cached_request(self, cache_key, path, params, timeout):
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload = self._request(path, params)
        self._cache_set(cache_key, payload, timeout)
        return payload

    # ------------------------------------------------------------------
    # Paginación
    # ------------------------------------------------------------------

    def obtener_todas_las_paginas(
        self,
        path,
        params=None,
        *,
        max_pages=100,
        sleep_seconds=0,
    ):
        """Obtiene todas las páginas de un endpoint paginado.

        Se detiene cuando paging.total deja de tener páginas pendientes.
        max_pages protege contra respuestas inesperadas.
        """
        base_params = dict(params or {})
        page = int(base_params.get("page", 1))
        results = []
        first_payload = None

        while page <= max_pages:
            request_params = dict(base_params)
            request_params["page"] = page
            payload = self._request(path, request_params)

            if first_payload is None:
                first_payload = payload

            results.extend(payload.get("response") or [])

            paging = payload.get("paging") or {}
            total_pages = int(paging.get("total") or page)

            if page >= total_pages:
                break

            page += 1
            if sleep_seconds:
                time.sleep(sleep_seconds)

        if first_payload is None:
            return {"results": 0, "paging": {"current": 1, "total": 1}, "response": []}

        merged = dict(first_payload)
        merged["response"] = results
        merged["results"] = len(results)
        merged["paging"] = {
            "current": page,
            "total": page,
        }
        return merged

    # ------------------------------------------------------------------
    # Ligas / cobertura / rondas
    # ------------------------------------------------------------------

    def obtener_ligas(self, **params):
        return self._request("leagues", params)

    def obtener_cobertura_liga(self, league_id, season):
        """Obtiene coverage para una liga y temporada."""
        key = f"api_football_league_coverage_v2_{league_id}_{season}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        payload = self._request(
            "leagues",
            {"id": str(league_id), "season": str(season)},
        )

        coverage = {}
        response = payload.get("response") or []
        if response:
            seasons = response[0].get("seasons") or []
            for item in seasons:
                if str(item.get("year")) == str(season):
                    coverage = item.get("coverage") or {}
                    break

        self._cache_set(key, coverage, self.CACHE_COVERAGE_SECONDS)
        return coverage

    def obtener_rondas(self, league_id, season, current=None):
        params = {
            "league": str(league_id),
            "season": str(season),
        }
        if current is not None:
            params["current"] = str(current).lower()
        return self._request("fixtures/rounds", params)

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def obtener_en_vivo(self, leagues=None):
        params = {"live": "all" if not leagues else "-".join(map(str, leagues))}
        return self._request("fixtures", params)

    def obtener_fixtures(self, **params):
        """Consulta /fixtures con cualquier combinación válida de filtros."""
        return self._request("fixtures", params)

    def obtener_detalle_partido(self, fixture_id):
        """Obtiene fixture + eventos + alineaciones + estadísticas + jugadores."""
        return self._request("fixtures", {"id": str(fixture_id)})

    def obtener_detalles_partidos(self, fixture_ids):
        """Obtiene hasta 20 fixtures en una sola llamada mediante ids=."""
        ids = list(fixture_ids)
        if not ids:
            return {"results": 0, "response": []}
        if len(ids) > 20:
            raise ValueError("API-Football permite como máximo 20 fixture IDs por llamada.")

        return self._request(
            "fixtures",
            {"ids": "-".join(str(fixture_id) for fixture_id in ids)},
        )

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

        key = (
            f"api_football_fixture_stats_v2_{fixture_id}_"
            f"{team_id or 'all'}_{stat_type or 'all'}"
        )
        return self._cached_request(
            key,
            "fixtures/statistics",
            params,
            self.CACHE_STATS_SECONDS,
        )

    def obtener_alineaciones_partido(self, fixture_id):
        key = f"api_football_fixture_lineups_v2_{fixture_id}"
        return self._cached_request(
            key,
            "fixtures/lineups",
            {"fixture": str(fixture_id)},
            self.CACHE_LINEUPS_SECONDS,
        )

    def obtener_jugadores_partido(self, fixture_id):
        key = f"api_football_fixture_players_v2_{fixture_id}"
        return self._cached_request(
            key,
            "fixtures/players",
            {"fixture": str(fixture_id)},
            self.CACHE_PLAYERS_SECONDS,
        )

    # ------------------------------------------------------------------
    # Equipos / jugadores
    # ------------------------------------------------------------------

    def obtener_equipos(self, **params):
        return self._request("teams", params)

    def obtener_equipo(self, team_id):
        return self._request("teams", {"id": str(team_id)})

    def obtener_paises_equipos(self):
        return self._cached_request(
            "api_football_teams_countries_v1",
            "teams/countries",
            {},
            self.CACHE_REFERENCE_SECONDS,
        )

    def obtener_estadisticas_equipo(self, league_id, season, team_id):
        key = f"api_football_team_stats_v1_{league_id}_{season}_{team_id}"
        return self._cached_request(
            key,
            "teams/statistics",
            {
                "league": str(league_id),
                "season": str(season),
                "team": str(team_id),
            },
            self.CACHE_TEAM_STATS_SECONDS,
        )

    def obtener_jugadores(self, **params):
        return self._request("players", params)

    def obtener_todos_los_jugadores(self, **params):
        return self.obtener_todas_las_paginas("players", params)

    # ------------------------------------------------------------------
    # Tablas / goleadores / estadísticas de temporada
    # ------------------------------------------------------------------

    def obtener_tabla(self, league_id, season, team_id=None):
        params = {
            "league": str(league_id),
            "season": str(season),
        }
        if team_id is not None:
            params["team"] = str(team_id)

        key = f"api_football_standings_v1_{league_id}_{season}_{team_id or 'all'}"
        return self._cached_request(
            key,
            "standings",
            params,
            self.CACHE_STANDINGS_SECONDS,
        )

    def obtener_goleadores(self, league_id, season, page=None):
        params = {"league": str(league_id), "season": str(season)}
        if page is not None:
            params["page"] = str(page)
        return self._request("players/topscorers", params)

    def obtener_todos_los_goleadores(self, league_id, season):
        return self.obtener_todas_las_paginas(
            "players/topscorers",
            {"league": str(league_id), "season": str(season)},
        )

    def obtener_asistencias(self, league_id, season, page=None):
        params = {"league": str(league_id), "season": str(season)}
        if page is not None:
            params["page"] = str(page)
        return self._request("players/topassists", params)

    def obtener_tarjetas(self, league_id, season, page=None):
        params = {"league": str(league_id), "season": str(season)}
        if page is not None:
            params["page"] = str(page)
        return self._request("players/topyellowcards", params)

    def obtener_tarjetas_rojas(self, league_id, season, page=None):
        params = {"league": str(league_id), "season": str(season)}
        if page is not None:
            params["page"] = str(page)
        return self._request("players/topredcards", params)

    # ------------------------------------------------------------------
    # H2H / predicciones
    # ------------------------------------------------------------------

    def obtener_enfrentamientos_directos(self, team_a_id, team_b_id, last=None):
        params = {
            "h2h": f"{team_a_id}-{team_b_id}",
        }
        if last is not None:
            params["last"] = str(last)
        return self._request("fixtures/headtohead", params)

    def obtener_prediccion(self, fixture_id):
        key = f"api_football_prediction_v1_{fixture_id}"
        return self._cached_request(
            key,
            "predictions",
            {"fixture": str(fixture_id)},
            self.CACHE_PREDICTIONS_SECONDS,
        )

    # ------------------------------------------------------------------
    # Cuotas
    # ------------------------------------------------------------------

    def obtener_cuotas(self, **params):
        return self._request("odds", params)

    def obtener_cuotas_en_vivo(self, **params):
        return self._request("odds/live", params)

    def obtener_casas_apuestas(self):
        return self._cached_request(
            "api_football_odds_bookmakers_v1",
            "odds/bookmakers",
            {},
            self.CACHE_REFERENCE_SECONDS,
        )

    def obtener_tipos_apuesta(self):
        return self._cached_request(
            "api_football_odds_bets_v1",
            "odds/bets",
            {},
            self.CACHE_REFERENCE_SECONDS,
        )

    def obtener_cuotas_todas_las_paginas(self, **params):
        return self.obtener_todas_las_paginas("odds", params)

    # ------------------------------------------------------------------
    # Lesiones / bajas
    # ------------------------------------------------------------------

    def obtener_lesiones(self, **params):
        return self._request("injuries", params)

    def obtener_lesiones_todas_las_paginas(self, **params):
        return self.obtener_todas_las_paginas("injuries", params)

    def obtener_bajas_jugador(self, player_id, **params):
        params = {"player": str(player_id), **params}
        return self._request("sidelined", params)
