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
        cache_key = "api_football_live_matches"
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
                "home_goals": goals.get("home", 0),
                "away_goals": goals.get("away", 0),
                "elapsed": status.get("elapsed"),
                "status": status.get("short", ""),
            })

        return JsonResponse({"count": len(matches), "matches": matches})
    except Exception as exc:
        return JsonResponse({"error": str(exc), "matches": []}, status=502)