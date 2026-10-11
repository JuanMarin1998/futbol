"""Persistencia y análisis descriptivo de patrones de comportamiento LIVE.

Este laboratorio no genera apuestas ni modifica los motores. Solo guarda observaciones
de partidos que ya procesa el recolector y acumula indicadores descriptivos por equipo.
"""
import hashlib
import json
import re
import unicodedata
from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from ..models import MatchBehaviorSnapshot, TeamBehaviorProfile


def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", texto.casefold()).strip("-")


def _minute_number(value):
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def _json_safe(value):
    try:
        return json.loads(json.dumps(value or {}, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return {}


def _side_stats(performance, side):
    if not isinstance(performance, dict):
        return {}
    aliases = ("home", "HOME", "local", "homeTeam") if side == "home" else ("away", "AWAY", "visitante", "awayTeam")
    for key in aliases:
        value = performance.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _number(stats, *needles):
    """Busca una estadística numérica por nombre sin asumir un único proveedor."""
    if not isinstance(stats, dict):
        return None
    for key, value in stats.items():
        normalized = _normalizar(key).replace("-", "")
        if any(_normalizar(n).replace("-", "") in normalized for n in needles):
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                found = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", "."))
                if found:
                    return float(found.group())
    return None


def _pressure(performance, side):
    stats = _side_stats(performance, side)
    shots = _number(stats, "shotsongoal", "shotsontarget", "tirosapuerta", "rematesapuerta") or 0
    dangerous = _number(stats, "dangerousattacks", "ataquespeligrosos") or 0
    corners = _number(stats, "corner", "corners", "cornerskicks", "saquesdeesquina") or 0
    return round(shots * 3 + dangerous * 0.15 + corners * 1.5, 2)


def record_match_snapshot(match):
    """Guarda una observación si cambió el estado relevante y actualiza ambos perfiles."""
    if not match or not match.ecuabet_event_id or not match.home_team or not match.away_team:
        return None

    minute = str(match.minute or "")
    minute_number = _minute_number(minute)
    performance = _json_safe(getattr(match, "performance", {}) or {})
    odds = _json_safe(getattr(match, "odds", []) or [])
    status = str(getattr(match, "match_status", "") or ("FINISHED" if getattr(match, "is_finished", False) else "LIVE"))
    payload = {
        "event": int(match.ecuabet_event_id),
        "minute": minute,
        "period": str(match.period or ""),
        "home_score": match.home_score,
        "away_score": match.away_score,
        "status": status,
        "performance": performance,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()

    previous = MatchBehaviorSnapshot.objects.filter(
        ecuabet_event_id=match.ecuabet_event_id
    ).order_by("-observed_at").first()
    if previous and previous.fingerprint == fingerprint:
        return previous

    snapshot = MatchBehaviorSnapshot.objects.create(
        ecuabet_event_id=int(match.ecuabet_event_id),
        flashscore_event_id=str(match.flashscore_event_id or ""),
        home_team=str(match.home_team)[:180],
        away_team=str(match.away_team)[:180],
        league=str(match.league or "")[:180],
        minute=minute[:40],
        minute_number=minute_number,
        period=str(match.period or "")[:40],
        home_score=match.home_score,
        away_score=match.away_score,
        status=status[:40],
        performance=performance,
        odds=odds,
        fingerprint=fingerprint,
    )

    for side, team_name, goals_for, goals_against in (
        ("home", str(match.home_team), match.home_score, match.away_score),
        ("away", str(match.away_team), match.away_score, match.home_score),
    ):
        key = _normalizar(team_name) or f"equipo-{match.ecuabet_event_id}-{side}"
        profile, _ = TeamBehaviorProfile.objects.get_or_create(
            team_key=key, defaults={"team_name": team_name[:180]}
        )
        profile.team_name = team_name[:180]
        profile.snapshots_count += 1
        behavior = dict(profile.behavior or {})
        states = dict(behavior.get("states") or {})
        if goals_for is not None and goals_against is not None:
            state = "ganando" if goals_for > goals_against else "perdiendo" if goals_for < goals_against else "empatando"
            states[state] = int(states.get(state, 0)) + 1
        behavior["states"] = states

        pressure = _pressure(performance, side)
        previous_side = MatchBehaviorSnapshot.objects.filter(
            ecuabet_event_id=match.ecuabet_event_id
        ).exclude(pk=snapshot.pk).order_by("-observed_at").first()
        previous_pressure = _pressure(previous_side.performance, side) if previous_side else None
        trends = dict(behavior.get("pressure_trends") or {})
        if previous_pressure is not None:
            if pressure > previous_pressure:
                trends["subiendo"] = int(trends.get("subiendo", 0)) + 1
            elif pressure < previous_pressure:
                trends["bajando"] = int(trends.get("bajando", 0)) + 1
            else:
                trends["estable"] = int(trends.get("estable", 0)) + 1
        behavior["pressure_trends"] = trends
        behavior["last_observation"] = {
            "event_id": int(match.ecuabet_event_id),
            "minute": minute,
            "marcador": f"{goals_for if goals_for is not None else '?'}-{goals_against if goals_against is not None else '?'}",
            "estado": states and (state if goals_for is not None and goals_against is not None else "desconocido") or "desconocido",
            "presion": pressure,
            "liga": str(match.league or ""),
        }
        behavior["last_score"] = {"for": goals_for, "against": goals_against}
        profile.behavior = behavior
        profile.last_seen = snapshot.observed_at
        profile.matches_observed = MatchBehaviorSnapshot.objects.filter(
            Q(home_team__iexact=team_name) | Q(away_team__iexact=team_name)
        ).values("ecuabet_event_id").distinct().count()
        profile.save(update_fields=["team_name", "snapshots_count", "matches_observed", "last_seen", "behavior", "updated_at"])
    return snapshot
