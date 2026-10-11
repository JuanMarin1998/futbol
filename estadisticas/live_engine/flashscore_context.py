"""Contexto prepartido de Flashscore: alineaciones, forma reciente y calendario.

La adquisición ampliada usa un adaptador HTTP compatible con la API del scraper
Flashscore descrita en README (endpoints /matches/lineups, /matches/h2h,
 /teams/results y /teams/fixtures). No inventa datos: si no se configura
FLASHSCORE_CONTEXT_API_URL o el proveedor falla, devuelve estado no disponible.
Los resultados se almacenan en caché en memoria para evitar consultas por ciclo LIVE.
"""
import os
import time
import unicodedata
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests


class FlashscoreContextProvider:
    """Proveedor opcional de contexto con caché TTL y errores aislados por fuente."""

    _shared_cache = {}
    DEFAULT_TTL = {
        "lineups": 300,
        "history": 6 * 60 * 60,
        "fixtures": 3 * 60 * 60,
    }

    def __init__(self, base_url=None, timeout=6, session=None):
        self.base_url = (base_url if base_url is not None else
                         os.getenv("FLASHSCORE_CONTEXT_API_URL", "")).strip().rstrip("/")
        self.timeout = int(timeout or os.getenv("FLASHSCORE_CONTEXT_TIMEOUT", "6"))
        self.session = session or requests.Session()
        self._cache = self._shared_cache

    @staticmethod
    def _as_list(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("matches", "events", "results", "fixtures", "lineups", "data", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    nested = FlashscoreContextProvider._as_list(value)
                    if nested:
                        return nested
        return []

    def _get(self, path, params, cache_key, ttl):
        if not self.base_url:
            raise RuntimeError(
                "FLASHSCORE_CONTEXT_API_URL no está configurado; "
                "se requiere un adaptador Flashscore compatible."
            )
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and now - cached["time"] < ttl:
            return cached["data"]
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("ok") is False:
            raise RuntimeError(str(payload.get("error") or "El proveedor no devolvió datos"))
        self._cache[cache_key] = {"time": now, "data": payload}
        return payload

    @staticmethod
    def _source_result(status="unavailable", data=None, error=None, cached=False):
        return {
            "status": status,
            "data": data if data is not None else {},
            "error": error,
            "cached": bool(cached),
        }

    def _safe_get(self, path, params, key, ttl, normalizer):
        try:
            payload = self._get(path, params, key, ttl)
            data = normalizer(payload)
            if data:
                return self._source_result("available", data)
            return self._source_result("empty", {}, "La fuente respondió sin datos normalizables")
        except Exception as exc:
            return self._source_result("unavailable", {}, str(exc))

    @staticmethod
    def _unwrap_payload(payload):
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        return data

    @staticmethod
    def _player_name_key(value):
        value = unicodedata.normalize("NFKD", str(value or ""))
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return " ".join(value.casefold().split())

    @classmethod
    def _player_rows(cls, payload):
        """Acepta las formas de respuesta usadas por distintas versiones del scraper."""
        data = cls._unwrap_payload(payload)
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if not isinstance(data, dict):
            return []
        for key in ("players", "player_statistics", "playerStatistics", "statistics", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                rows = cls._player_rows(value)
                if rows:
                    return rows
        return []

    @classmethod
    def _lineup_player_rows(cls, payload):
        data = cls._unwrap_payload(payload)
        if not isinstance(data, dict):
            return [], []
        nested = data.get("lineups") or data.get("lineup")
        if isinstance(nested, dict):
            data = nested
        home = data.get("home") or data.get("homeTeam") or data.get("home_lineup") or data.get("homeLineup") or {}
        away = data.get("away") or data.get("awayTeam") or data.get("away_lineup") or data.get("awayLineup") or {}
        if not isinstance(home, dict):
            home = {}
        if not isinstance(away, dict):
            away = {}
        def flatten(team):
            starters, substitutes = [], []
            for group in team.get("groups") or []:
                if not isinstance(group, dict):
                    continue
                title = cls._player_name_key(group.get("name"))
                target = substitutes if ("substitut" in title or "bench" in title or "reserve" in title) else starters
                players = group.get("players") or []
                if isinstance(players, list):
                    target.extend(player for player in players if isinstance(player, dict))
            # Soporta también respuestas ya separadas por listas.
            if not starters:
                for key in ("starters", "startingXI", "starting_xi", "starting", "players", "lineup"):
                    if isinstance(team.get(key), list):
                        starters.extend(team[key])
                        break
            if not substitutes:
                for key in ("substitutes", "bench", "reserves", "substitutePlayers"):
                    if isinstance(team.get(key), list):
                        substitutes.extend(team[key])
                        break
            return starters, substitutes
        hs, hb = flatten(home)
        aws, awb = flatten(away)
        return (hs + hb + aws + awb), [
            data,
            home,
            away,
        ]

    @classmethod
    def _normalize_lineups(cls, payload, statistics_payload=None, details_payload=None):
        if not isinstance(payload, dict):
            return {}
        data = cls._unwrap_payload(payload)
        if not isinstance(data, dict):
            return {"raw": data}
        nested = data.get("lineups") or data.get("lineup")
        if isinstance(nested, dict):
            data = nested
        raw_home = data.get("home") or data.get("homeTeam") or data.get("home_lineup") or data.get("homeLineup") or {}
        raw_away = data.get("away") or data.get("awayTeam") or data.get("away_lineup") or data.get("awayLineup") or {}
        if not isinstance(raw_home, dict):
            raw_home = {}
        if not isinstance(raw_away, dict):
            raw_away = {}

        # Indexa la ficha de alineaciones para rescatar dorsal, incidentes y rating.
        lineup_by_id, lineup_by_name = {}, {}
        for player in cls._lineup_player_rows(payload)[0]:
            person = player.get("player") if isinstance(player.get("player"), dict) else player
            pid = str(person.get("id") or player.get("id") or "").strip()
            name = person.get("name") or player.get("name") or player.get("playerName")
            if pid:
                lineup_by_id[pid] = player
            if name:
                lineup_by_name[cls._player_name_key(name)] = player

        rows = cls._player_rows(statistics_payload)
        rosters = {"home": {"starters": [], "substitutes": []}, "away": {"starters": [], "substitutes": []}}
        for row in rows:
            person = row.get("player") if isinstance(row.get("player"), dict) else {}
            team = row.get("team") if isinstance(row.get("team"), dict) else {}
            side = str(row.get("side") or team.get("side") or "").lower()
            team_id = str(team.get("id") or "")
            if side not in ("home", "away"):
                if team_id and details_payload:
                    details = cls._unwrap_payload(details_payload)
                    if isinstance(details, dict):
                        for side_name in ("home", "away"):
                            team_obj = details.get(side_name)
                            if isinstance(team_obj, dict) and str(team_obj.get("id") or "") == team_id:
                                side = side_name
                                break
            if side not in rosters:
                continue
            pid = str(person.get("id") or row.get("player_id") or "").strip()
            name = person.get("name") or row.get("name") or row.get("playerName") or ""
            lineup = lineup_by_id.get(pid) if pid else None
            if lineup is None and name:
                lineup = lineup_by_name.get(cls._player_name_key(name))
            lineup = lineup or {}
            lineup_person = lineup.get("player") if isinstance(lineup.get("player"), dict) else {}
            merged = dict(lineup)
            merged.update({
                "player": {
                    **lineup_person,
                    "id": pid or lineup_person.get("id"),
                    "name": name or lineup_person.get("name") or lineup.get("name") or "Jugador",
                },
                "name": name or lineup_person.get("name") or lineup.get("name") or "Jugador",
                "shirt_number": lineup.get("shirt_number", lineup.get("number", lineup.get("shirtNumber", ""))),
                "rating": row.get("rating") if row.get("rating") is not None else lineup.get("rating"),
                "position": row.get("position") or lineup.get("position") or lineup.get("role"),
                "is_starter": bool(row.get("is_starter", False)),
                "is_captain": bool(lineup.get("is_captain", False)),
            })
            bucket = "starters" if merged["is_starter"] else "substitutes"
            rosters[side][bucket].append(merged)

        # Cuando hay estadísticas de jugadores, sus team.side/is_starter son la fuente fiable.
        has_rosters = bool(rosters["home"]["starters"] or rosters["away"]["starters"])
        formation_home = raw_home.get("formation") or data.get("formation_home") or data.get("homeFormation")
        formation_away = raw_away.get("formation") or data.get("formation_away") or data.get("awayFormation")
        if has_rosters:
            home = {**rosters["home"], "formation": formation_home, "team": (cls._unwrap_payload(details_payload) or {}).get("home", {}) if isinstance(cls._unwrap_payload(details_payload), dict) else {}}
            away = {**rosters["away"], "formation": formation_away, "team": (cls._unwrap_payload(details_payload) or {}).get("away", {}) if isinstance(cls._unwrap_payload(details_payload), dict) else {}}
        else:
            # No clasificar listas combinadas si el proveedor no aporta side fiable.
            home, away = raw_home, raw_away
        return {
            "home": home,
            "away": away,
            "formation_home": formation_home,
            "formation_away": formation_away,
            "missing_players": data.get("missing_players") or data.get("missingPlayers") or [],
            "lineups_joined_with_player_statistics": has_rosters,
            "raw": data,
        } if raw_home or raw_away or data else {}

    @classmethod
    def _normalize_h2h(cls, payload):
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            return {"raw": data}
        rows = cls._as_list(data)
        if not rows:
            for key in ("h2h", "head_to_head", "meetings", "matches"):
                if isinstance(data.get(key), list):
                    rows = data[key]
                    break
        nested_h2h = data.get("h2h") or data.get("head_to_head")
        if isinstance(nested_h2h, dict):
            rows = rows or cls._as_list(nested_h2h)
            data = {**data, **nested_h2h}
        home_form = data.get("home_form") or data.get("homeForm") or data.get("home_recent_matches") or []
        away_form = data.get("away_form") or data.get("awayForm") or data.get("away_recent_matches") or []
        if not home_form and not away_form and not rows:
            # Mantener datos sin interpretar; no inferir forma a partir de campos desconocidos.
            return {"raw": data} if data else {}
        return {"meetings": rows, "home_form": home_form, "away_form": away_form, "raw": data}

    @classmethod
    def _normalize_matches(cls, payload):
        rows = cls._as_list(payload)
        normalized = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or row.get("stage") or "").lower()
            normalized.append({
                "match_id": row.get("matchId") or row.get("id") or row.get("event_id"),
                "date": row.get("start_time") or row.get("startTime") or row.get("date"),
                "status": status,
                "home": row.get("home") or row.get("home_team"),
                "away": row.get("away") or row.get("away_team"),
                "home_score": row.get("home_score", row.get("scoreHome")),
                "away_score": row.get("away_score", row.get("scoreAway")),
                "competition": row.get("competition") or row.get("tournament"),
                "raw": row,
            })
        return normalized

    def obtener_contexto(self, event_id: str, home_team_id=None, away_team_id=None) -> Dict[str, Any]:
        """Obtiene las tres fuentes en paralelo lógico; un fallo no bloquea las demás."""
        event_id = str(event_id or "").strip()
        result = {
            "provider": "flashscore_context_api",
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "lineups": self._source_result(),
            "history": self._source_result(),
            "fixtures": self._source_result(),
        }
        if not event_id:
            for key in ("lineups", "history", "fixtures"):
                result[key] = self._source_result("unavailable", {}, "Falta el ID de partido Flashscore")
            return result

        # Consultar las tres fuentes por separado: el scraper puede agrupar todos los
        # jugadores en los grupos de alineación, mientras player-statistics sí identifica
        # team.side e is_starter. Si falla una fuente, las otras siguen disponibles.
        lineup_payload = statistics_payload = details_payload = None
        lineup_error = None
        try:
            lineup_payload = self._get(
                "matches/lineups", {"match": event_id}, "lineups:" + event_id,
                self.DEFAULT_TTL["lineups"],
            )
        except Exception as exc:
            lineup_error = str(exc)
        try:
            statistics_payload = self._get(
                "matches/player-statistics", {"match": event_id},
                "player-statistics:" + event_id, self.DEFAULT_TTL["lineups"],
            )
        except Exception:
            pass
        try:
            details_payload = self._get(
                "matches/details", {"match": event_id},
                "details:" + event_id, self.DEFAULT_TTL["lineups"],
            )
        except Exception:
            pass

        try:
            normalized = self._normalize_lineups(lineup_payload, statistics_payload, details_payload) if lineup_payload is not None else {}
            if normalized:
                result["lineups"] = self._source_result("available", normalized)
            else:
                result["lineups"] = self._source_result(
                    "unavailable" if lineup_error else "empty", {},
                    lineup_error or "La fuente respondió sin alineaciones normalizables",
                )
        except Exception as exc:
            result["lineups"] = self._source_result("unavailable", {}, str(exc))
        result["history"] = self._safe_get(
            "matches/h2h", {"match": event_id}, "h2h:" + event_id,
            self.DEFAULT_TTL["history"], self._normalize_h2h,
        )

        team_ids = [("home", home_team_id), ("away", away_team_id)]
        fixtures = {}
        errors = []
        for side, team_id in team_ids:
            if not team_id:
                fixtures[side] = {"past": [], "future": []}
                continue
            side_data = {}
            for kind, path in (("past", "teams/results"), ("future", "teams/fixtures")):
                source = self._safe_get(
                    path, {"team": str(team_id), "page": 1},
                    f"{kind}:{team_id}", self.DEFAULT_TTL["fixtures"], self._normalize_matches,
                )
                side_data[kind] = source["data"] if source["status"] == "available" else []
                if source.get("error"):
                    errors.append(f"{side} {kind}: {source['error']}")
            fixtures[side] = side_data
        if any(v.get("past") or v.get("future") for v in fixtures.values()):
            result["fixtures"] = self._source_result("available", fixtures)
        else:
            result["fixtures"] = self._source_result(
                "unavailable", fixtures,
                "; ".join(errors) if errors else "No hay IDs de equipo para consultar calendario",
            )
        return result
