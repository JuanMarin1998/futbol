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
        cache_key = "api_football_live_matches_v3"
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

        return JsonResponse({
            "count": len(matches),
            "matches": matches,
            "source": "API-Football /fixtures?live=all",
        })
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
        # Solo datos LIVE. No consultamos liga/temporada/coverage porque
        # el plan Free puede bloquear temporadas aunque el fixture esté LIVE.
        cache_key = f"api_football_live_detail_v5_{fixture_id}"
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

        client = APIFootballLiveClient()
        fallback_used = []

        # /fixtures?id=... normalmente ya trae estos cuatro bloques.
        # Solo hacemos llamadas adicionales para los bloques ausentes.
        if not events:
            try:
                events_payload = client.obtener_eventos_partido(fixture_id)
                events = events_payload.get("response") or []
                if events:
                    fallback_used.append("events")
            except Exception:
                pass

        if not statistics:
            try:
                stats_payload = client.obtener_estadisticas_partido(fixture_id)
                statistics = stats_payload.get("response") or []
                if statistics:
                    fallback_used.append("statistics")
            except Exception:
                pass

        if not lineups:
            try:
                lineups_payload = client.obtener_alineaciones_partido(fixture_id)
                lineups = lineups_payload.get("response") or []
                if lineups:
                    fallback_used.append("lineups")
            except Exception:
                pass

        if not players:
            try:
                players_payload = client.obtener_jugadores_partido(fixture_id)
                players = players_payload.get("response") or []
                if players:
                    fallback_used.append("players")
            except Exception:
                pass

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
                "source": "API-Football LIVE fixture + missing-block fallbacks",
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


def ecuabet_live(request):
    poll_seconds = 5
    return render(
        request,
        "estadisticas/ecuabet_live.html",
        {"live_poll_ms": poll_seconds * 1000},
    )


def api_ecuabet_live(request):
    """Devuelve todos los eventos LIVE de Ecuabet con todos sus mercados y cuotas."""
    try:
        cache_key = "ecuabet_live_all_v1"
        payload = cache.get(cache_key)

        if payload is None:
            client = __import__("estadisticas.ecuabet_client", fromlist=["EcuabetClient"]).EcuabetClient()
            payload = client._request("GET", "GetLivenow", {
                "eventCount": 0,
                "sportId": 0,
            })
            cache.set(cache_key, payload, 3)

        events = payload.get("events", []) or []
        markets = payload.get("markets", []) or []
        odds = payload.get("odds", []) or []
        competitors = payload.get("competitors", []) or []
        sports = payload.get("sports", []) or []
        categories = payload.get("categories", []) or []
        champs = payload.get("champs", []) or []

        markets_by_id = {
            int(item["id"]): item
            for item in markets
            if isinstance(item, dict) and item.get("id") is not None
        }
        odds_by_id = {
            int(item["id"]): item
            for item in odds
            if isinstance(item, dict) and item.get("id") is not None
        }
        competitors_by_id = {
            int(item["id"]): item
            for item in competitors
            if isinstance(item, dict) and item.get("id") is not None
        }
        sports_by_id = {
            int(item["id"]): item
            for item in sports
            if isinstance(item, dict) and item.get("id") is not None
        }
        categories_by_id = {
            int(item["id"]): item
            for item in categories
            if isinstance(item, dict) and item.get("id") is not None
        }
        champs_by_id = {
            int(item["id"]): item
            for item in champs
            if isinstance(item, dict) and item.get("id") is not None
        }

        result = []
        for event in events:
            if not isinstance(event, dict):
                continue

            market_list = []
            for market_id in event.get("marketIds", []) or []:
                market = markets_by_id.get(int(market_id))
                if not market:
                    continue

                selections = []
                for odd_id in market.get("oddIds", []) or []:
                    odd = odds_by_id.get(int(odd_id))
                    if not odd:
                        continue
                    selections.append({
                        "id": int(odd["id"]),
                        "type_id": odd.get("typeId"),
                        "name": odd.get("name", ""),
                        "price": odd.get("price"),
                        "odd_status": odd.get("oddStatus"),
                        "competitor_id": odd.get("competitorId"),
                        "is_mb": odd.get("isMB", False),
                        "is_dbb": odd.get("isDBB", False),
                    })

                if selections:
                    market_list.append({
                        "id": int(market["id"]),
                        "type_id": market.get("typeId"),
                        "sport_market_id": market.get("sportMarketId"),
                        "name": market.get("name", ""),
                        "line": market.get("sv") or market.get("sn"),
                        "selections": selections,
                    })

            competitor_ids = event.get("competitorIds", []) or []
            event_sport_id = event.get("sportId")
            event_cat_id = event.get("catId")
            event_champ_id = event.get("champId")

            result.append({
                "id": event.get("id"),
                "name": event.get("name", ""),
                "live_time": event.get("liveTime"),
                "live_status": event.get("ls"),
                "score": event.get("score", [None, None]),
                "timer": event.get("timer", {}),
                "status": event.get("status"),
                "start_date": event.get("startDate"),
                "has_stream": event.get("hasStream", False),
                "competitors": [
                    competitors_by_id.get(int(cid), {"id": cid, "name": str(cid)})
                    for cid in competitor_ids
                ],
                "sport": sports_by_id.get(int(event_sport_id), {"id": event_sport_id, "name": ""})
                if event_sport_id is not None else {},
                "category": categories_by_id.get(int(event_cat_id), {"id": event_cat_id, "name": ""})
                if event_cat_id is not None else {},
                "champ": champs_by_id.get(int(event_champ_id), {"id": event_champ_id, "name": ""})
                if event_champ_id is not None else {},
                "markets": market_list,
            })

        return JsonResponse({
            "ok": True,
            "count": len(result),
            "events": result,
            "source": "Ecuabet GetLivenow",
            "updated_at": payload.get("updatedAt") or payload.get("lastUpdate"),
        })
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc), "events": []},
            status=502,
        )
