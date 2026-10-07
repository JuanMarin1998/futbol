from django.http import JsonResponse
from django.shortcuts import render
from django.core.cache import cache
from django.conf import settings

from .api_football_live import APIFootballLiveClient


def partidos_en_vivo(request):
    poll_seconds = getattr(settings, "LIVE_POLL_SECONDS", 60)
    return render(request, "estadisticas/live.html", {"live_poll_ms": poll_seconds * 1000})


def api_partidos_en_vivo(request):
    try:
        cache_key = "api_football_live_matches_v2"
        payload = cache.get(cache_key)
        if payload is None:
            payload = APIFootballLiveClient().obtener_en_vivo()
            cache.set(cache_key, payload, getattr(settings, "LIVE_CACHE_SECONDS", 50))

        matches = []
        for item in payload.get("response", []):
            fixture = item.get("fixture", {})
            league = item.get("league", {})
            teams = item.get("teams", {})
            goals = item.get("goals", {})
            status = fixture.get("status", {})
            matches.append({
                "id": fixture.get("id"),
                "league": league.get("name", ""),
                "country": league.get("country", ""),
                "home": teams.get("home", {}).get("name", ""),
                "away": teams.get("away", {}).get("name", ""),
                "home_logo": teams.get("home", {}).get("logo", ""),
                "away_logo": teams.get("away", {}).get("logo", ""),
                "home_goals": goals.get("home", 0),
                "away_goals": goals.get("away", 0),
                "elapsed": status.get("elapsed"),
                "extra": status.get("extra"),
                "status": status.get("short", ""),
                "status_long": status.get("long", ""),
            })

        return JsonResponse({"count": len(matches), "matches": matches})
    except Exception as exc:
        return JsonResponse({"error": str(exc), "matches": []}, status=502)


def detalle_partido_en_vivo(request, fixture_id):
    poll_seconds = getattr(settings, "LIVE_POLL_SECONDS", 60)
    return render(
        request,
        "estadisticas/live_detalle.html",
        {"fixture_id": fixture_id, "live_poll_ms": poll_seconds * 1000},
    )


def api_detalle_partido_en_vivo(request, fixture_id):
    try:
        # Versioned key avoids serving an old response after parser/template changes.
        cache_key = f"api_football_live_detail_v4_{fixture_id}"
        payload = cache.get(cache_key)

        if payload is None:
            payload = APIFootballLiveClient().obtener_detalle_partido(fixture_id)
            cache.set(
                cache_key,
                payload,
                getattr(settings, "LIVE_CACHE_SECONDS", 50),
            )

        response = payload.get("response", [])
        if not response:
            return JsonResponse(
                {"error": "No se encontró el partido solicitado."},
                status=404,
            )

        item = response[0]
        fixture = item.get("fixture", {})
        league = item.get("league", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        status = fixture.get("status", {})
        events = item.get("events") or []
        statistics = item.get("statistics") or []
        lineups = item.get("lineups") or []
        players = item.get("players") or []

        # Normalmente /fixtures?id=... ya trae estos bloques.
        # Si una competición omite alguno, consultamos solo el bloque faltante
        # y lo dejamos en caché para no multiplicar llamadas innecesariamente.
        fallback_used = []

        if not statistics:
            statistics = APIFootballLiveClient().obtener_estadisticas_partido(fixture_id)
            fallback_used.append("statistics")

        if not lineups:
            lineups = APIFootballLiveClient().obtener_alineaciones_partido(fixture_id)
            fallback_used.append("lineups")

        if not players:
            players = APIFootballLiveClient().obtener_jugadores_partido(fixture_id)
            fallback_used.append("players")

        # Normalize the data once in the backend. The browser then receives
        # exactly the structures needed by the detail page.
        stats_normalized = []
        for team_stats in statistics:
            team = team_stats.get("team") or {}
            values = {}
            for stat in team_stats.get("statistics") or []:
                stat_type = stat.get("type")
                if stat_type:
                    values[stat_type] = stat.get("value")
            stats_normalized.append({
                "team": team,
                "values": values,
            })

        cards = [
            event for event in events
            if (event.get("type") or "").lower() == "card"
        ]
        goals_events = [
            event for event in events
            if (event.get("type") or "").lower() == "goal"
        ]
        substitutions = [
            event for event in events
            if (event.get("type") or "").lower() in {"subst", "substitution"}
        ]

        return JsonResponse({
            "fixture": {
                "id": fixture.get("id"),
                "date": fixture.get("date"),
                "venue": fixture.get("venue", {}),
                "referee": fixture.get("referee"),
                "status": status,
            },
            "league": league,
            "home": teams.get("home", {}),
            "away": teams.get("away", {}),
            "score": goals,
            "events": events,
            "goals_events": goals_events,
            "cards": cards,
            "substitutions": substitutions,
            "statistics": statistics,
            "statistics_normalized": stats_normalized,
            "lineups": lineups,
            "players": players,
            "meta": {
                "events": len(events),
                "goals": len(goals_events),
                "cards": len(cards),
                "substitutions": len(substitutions),
                "statistics": len(statistics),
                "lineups": len(lineups),
                "players": len(players),
                "fallback_used": fallback_used,
                "source": "fixtures?ids=FIXTURE_ID + fallback endpoints",
                "main_payload": {
                    "results": payload.get("results"),
                    "errors": payload.get("errors") or {},
                    "raw_keys": sorted(item.keys()),
                    "raw_counts": {
                        "events": len(item.get("events") or []),
                        "statistics": len(item.get("statistics") or []),
                        "lineups": len(item.get("lineups") or []),
                        "players": len(item.get("players") or []),
                    },
                },
            },
        })
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=502)
