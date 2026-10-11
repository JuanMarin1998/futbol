"""Contexto prepartido de Flashscore: alineaciones, forma reciente y calendario.

La adquisición ampliada usa un adaptador HTTP compatible con la API del scraper
Flashscore descrita en README (endpoints /matches/lineups, /matches/h2h,
 /teams/results y /teams/fixtures). No inventa datos: si no se configura
FLASHSCORE_CONTEXT_API_URL o el proveedor falla, devuelve estado no disponible.
Los resultados se almacenan en caché en memoria para evitar consultas por ciclo LIVE.
"""
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests


class FlashscoreContextProvider:
    """Proveedor opcional de contexto con caché TTL y errores aislados por fuente."""

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
        self._cache = {}

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

    @classmethod
    def _normalize_lineups(cls, payload):
        if not isinstance(payload, dict):
            return {}
        # Preserva la estructura original del proveedor y expone campos comunes.
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            return {"raw": data}
        nested = data.get("lineups") or data.get("lineup")
        if isinstance(nested, dict):
            data = nested
        home = data.get("home") or data.get("homeTeam") or data.get("home_lineup") or data.get("homeLineup")
        away = data.get("away") or data.get("awayTeam") or data.get("away_lineup") or data.get("awayLineup")
        if home is None and away is None:
            # Diferentes versiones del scraper pueden devolver la ficha bajo match.
            match = data.get("match")
            if isinstance(match, dict):
                home = match.get("homeLineup") or match.get("home_lineup")
                away = match.get("awayLineup") or match.get("away_lineup")
        return {
            "home": home or {},
            "away": away or {},
            "formation_home": data.get("formation_home") or data.get("homeFormation"),
            "formation_away": data.get("formation_away") or data.get("awayFormation"),
            "missing_players": data.get("missing_players") or data.get("missingPlayers") or [],
            "raw": data,
        } if home is not None or away is not None or data else {}

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

        result["lineups"] = self._safe_get(
            "matches/lineups", {"match": event_id}, "lineups:" + event_id,
            self.DEFAULT_TTL["lineups"], self._normalize_lineups,
        )
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
