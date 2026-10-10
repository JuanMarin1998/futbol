import re
from typing import Any, Dict, List, Optional

from .opportunity_engine_v2 import LiveOpportunityEngineV2


class LiveOpportunityEngineVPro:
    """V.Pro: rastrea al favorito detectado al inicio de su seguimiento LIVE y
    busca valor con estadísticas coherentes. No asume que dominar posesión
    garantice goles; si faltan datos o hay señales contradictorias, no apuesta.
    """

    MIN_FAVORITE_ODDS = 1.05
    MAX_FAVORITE_ODDS = 1.70
    MIN_POSSESSION_GAP = 11.0
    MIN_EDGE = 0.035
    MIN_CONFIDENCE = 0.52

    @staticmethod
    def _num(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            if isinstance(value, dict):
                value = value.get("value", value.get("raw_value"))
            return float(str(value).replace("%", "").replace(",", ".").strip())
        except (TypeError, ValueError):
            return None

    @classmethod
    def _stat(cls, performance: Dict[str, Any], side: str, *keys: str) -> Optional[float]:
        """Lee estadísticas normalizadas o crudas, incluidas etiquetas de xG."""
        values = performance.get(side) or {}
        if not isinstance(values, dict):
            return None

        def key_norm(value):
            return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

        wanted = {key_norm(key) for key in keys}
        aliases = {
            "expectedgoals": {"expectedgoals", "xg", "expectedgoalsgeneral", "golesesperados"},
            "expectedgoalsontarget": {"expectedgoalsontarget", "xgot", "xgontarget", "xgapuerta"},
            "expectedassists": {"expectedassists", "xa", "asistenciasesperadas"},
            "ballpossession": {"ballpossession", "possession", "posesion", "posesiondelbalon"},
            "goalattempts": {"goalattempts", "totalshots", "rematestotales", "shots"},
            "shotsongoal": {"shotsongoal", "shotsontarget", "rematesapuerta"},
            "shotsoffgoal": {"shotsoffgoal", "shotsofftarget", "rematesfuera"},
            "blockedshots": {"blockedshots", "blocked", "rematesbloqueados", "rematesrechazados"},
            "bigchances": {"bigchances", "bigchancescreated", "grandesocasiones"},
            "bigchancesmissed": {"bigchancesmissed", "grandesocasionesfalladas"},
            "touchesinoppositionbox": {"touchesinoppositionbox", "touchesoppositionbox", "toquesenelarearival"},
            "cornerkicks": {"cornerkicks", "corners", "corner", "corners", "tirosdeesquina"},
            "accuratethroughpasses": {"accuratethroughpasses", "throughpasses", "pasesfiltradosprecisos", "pasesentrelineascompletados"},
            "finalthirdpasses": {"finalthirdpasses", "passesfinalthird", "pasesenelterciofinal"},
            "keypasses": {"keypasses", "pasesclave"},
            "crosses": {"crosses", "centros"},
            "goalkeepersaves": {"goalkeepersaves", "saves", "paradas", "paradasdelportero"},
            "goalsprevented": {"goalsprevented", "golesevitados"},
            "redcards": {"redcards", "tarjetasrojas"},
            "yellowcards": {"yellowcards", "tarjetasamarillas"},
            "errorsleadingtoshot": {"errorsleadingtoshot", "errorsleadingtogoal", "erroresconducentesa remate", "erroresconducentearemate", "erroresconducentegol"},
            "offsides": {"offsides", "fuerasdejuego"},
            "fouls": {"fouls", "faltas"},
            "tackles": {"tackles", "entradas"},
            "interceptions": {"interceptions", "intercepciones"},
            "clearances": {"clearances", "despejes"},
            "duelswon": {"duelswon", "duelosganados"},
        }
        expanded = set(wanted)
        for alias_group in aliases.values():
            if wanted.intersection(alias_group):
                expanded.update(alias_group)

        for raw_key, raw_value in values.items():
            candidates = {key_norm(raw_key)}
            if isinstance(raw_value, dict):
                candidates.update(key_norm(raw_value.get(k)) for k in ("name", "label", "stat_type", "type"))
            if candidates.intersection(expanded):
                value = cls._num(raw_value)
                if value is not None:
                    return value
        return None

    @classmethod
    def _estimate_xg(cls, performance: Dict[str, Any], side: str) -> Optional[float]:
        """Estimación agregada de baja confianza; no equivale al xG por disparo."""
        shots = cls._stat(performance, side, "goal_attempts", "total_shots", "shots", "remates totales")
        on_target = cls._stat(performance, side, "shots_on_goal", "shots_on_target", "shots on target", "remates a puerta")
        off_target = cls._stat(performance, side, "shots_off_goal", "shots_off_target", "shots off target", "remates fuera")
        blocked = cls._stat(performance, side, "blocked_shots", "blocked", "remates bloqueados")
        big = cls._stat(performance, side, "big_chances", "big_chances_created", "grandes ocasiones")
        if shots is None:
            parts = [v for v in (on_target, off_target, blocked) if v is not None]
            if not parts:
                return None
            shots = sum(parts)
        if shots <= 0:
            return 0.0
        estimate = 0.08 * shots
        if on_target is not None:
            estimate += 0.10 * on_target
        if off_target is not None:
            estimate -= 0.025 * off_target
        if blocked is not None:
            estimate -= 0.01 * blocked
        if big is not None:
            estimate += 0.12 * big
        return round(max(0.0, min(6.0, estimate)), 2)

    @classmethod
    def _xg_check(cls, match) -> Dict[str, Any]:
        """Prioriza xG oficial; si falta, calcula una estimación agregada etiquetada."""
        performance = match.performance or {}
        home_xg = cls._stat(performance, "home", "expected_goals", "xg", "expected_goals__general", "Expected goals (xG)", "Goles esperados (xG)")
        away_xg = cls._stat(performance, "away", "expected_goals", "xg", "expected_goals__general", "Expected goals (xG)", "Goles esperados (xG)")
        home_estimated = home_xg is None
        away_estimated = away_xg is None
        if home_estimated:
            home_xg = cls._estimate_xg(performance, "home")
        if away_estimated:
            away_xg = cls._estimate_xg(performance, "away")
        if home_xg is None and away_xg is None:
            status = "no_disponible"
            detail = "faltan estadísticas de remates para estimar xG"
        elif home_estimated or away_estimated:
            status = "estimado" if home_xg is not None and away_xg is not None else "parcial"
            labels = []
            if home_estimated and home_xg is not None:
                labels.append("local estimado")
            if away_estimated and away_xg is not None:
                labels.append("visitante estimado")
            detail = "xG aproximado calculado con estadísticas agregadas (" + ", ".join(labels) + "); fiabilidad baja, no es xG oficial"
        else:
            status = "disponible"
            detail = "xG oficial recibido para ambos equipos"
        return {"status": status, "home": home_xg, "away": away_xg,
                "home_estimated": home_estimated, "away_estimated": away_estimated,
                "detail": detail}

    @staticmethod
    def _norm(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    @classmethod
    def _is_1x2(cls, opportunity: Dict[str, Any]) -> bool:
        text = f'{opportunity.get("market", "")} {opportunity.get("selection", "")}'.lower()
        return any(term in text for term in ("1x2", "resultado", "ganador", "match winner"))

    @classmethod
    def _selection_side(cls, selection: str, match) -> Optional[str]:
        value = cls._norm(selection)
        home = cls._norm(match.home_team)
        away = cls._norm(match.away_team)
        if value in {"1", "local", "home"} or (home and (value == home or value in home or home in value)):
            return "home"
        if value in {"2", "visitante", "away"} or (away and (value == away or value in away or away in value)):
            return "away"
        return None

    @classmethod
    def _reference(cls, match) -> Optional[Dict[str, Any]]:
        saved = getattr(match, "vpro_reference_odds", None)
        if isinstance(saved, dict) and saved.get("side") in {"home", "away"}:
            try:
                price = float(saved.get("price"))
            except (TypeError, ValueError):
                price = 0
            if cls.MIN_FAVORITE_ODDS <= price <= cls.MAX_FAVORITE_ODDS:
                return saved

        # Respaldo para partidos que aún no tengan referencia persistida:
        # solo se usa la cuota 1X2 observada ahora y se marca como referencia LIVE.
        candidates = []
        for odd in match.odds or []:
            market = str(odd.get("market_name") or "").lower()
            if not any(term in market for term in ("1x2", "resultado", "ganador", "match winner")):
                continue
            side = cls._selection_side(str(odd.get("name") or ""), match)
            price = cls._num(odd.get("price"))
            if side and price and cls.MIN_FAVORITE_ODDS <= price <= cls.MAX_FAVORITE_ODDS:
                candidates.append({"side": side, "team": match.home_team if side == "home" else match.away_team,
                                   "price": price, "source": "cuota_live_observada"})
        return min(candidates, key=lambda item: item["price"]) if candidates else None

    @classmethod
    def _current_price(cls, match, market: str, selection: str) -> Optional[float]:
        wanted_market = cls._norm(market)
        wanted_selection = cls._norm(selection)
        for odd in match.odds or []:
            if cls._norm(odd.get("market_name")) == wanted_market and cls._norm(odd.get("name")) == wanted_selection:
                return cls._num(odd.get("price"))
        return None

    @classmethod
    def _extended_market_key(cls, odd: Dict[str, Any], match) -> Optional[str]:
        """Reconoce líneas de total adicionales y doble oportunidad en texto natural."""
        market = str(odd.get("market_name") or "")
        selection = str(odd.get("name") or "")
        text = f"{market} {selection}".lower()
        normalized = cls._norm(text)
        # No reinterpretar mercados de "gol del equipo/jugador" como total del partido.
        if any(term in normalized for term in ("tercergol", "proximogol", "primeranotador", "marcadorcorrecto")):
            return None

        if any(term in normalized for term in ("dobleoportunidad", "doublechance")):
            sel = cls._norm(selection)
            home = cls._norm(match.home_team)
            away = cls._norm(match.away_team)
            has_home = bool(home and home in sel)
            has_away = bool(away and away in sel)
            has_draw = any(term in sel for term in ("empate", "draw"))
            if has_home and has_draw:
                return "dc_1x"
            if has_home and has_away:
                return "dc_12"
            if has_away and has_draw:
                return "dc_x2"

        if any(term in normalized for term in ("total", "over", "under", "masde", "menosde", "mas", "menos")):
            line_text = f"{odd.get('line') or ''} {market} {selection}"
            found = re.search(r"(\d+(?:[\.,]\d+)?)", line_text)
            if not found:
                return None
            try:
                line = float(found.group(1).replace(",", "."))
            except ValueError:
                return None
            # Las líneas asiáticas enteras tienen posibilidad de push y requieren
            # una función de liquidación específica; por seguridad solo medias líneas.
            if abs(line * 2 - round(line * 2)) > 0.01 or abs(line - round(line)) < 0.01:
                return None
            is_over = any(term in cls._norm(selection) for term in ("over", "mas", "masde", "masde"))
            is_under = any(term in cls._norm(selection) for term in ("under", "menos", "menosde"))
            if not is_over and not is_under:
                return None
            return ("over_" if is_over else "under_") + str(line).replace(".", "_")
        return None

    @classmethod
    def _extended_market_probability(cls, key: str, match, elapsed: float) -> Optional[float]:
        performance = match.performance or {}
        h = LiveOpportunityEngineV2._features(performance, "home")
        a = LiveOpportunityEngineV2._features(performance, "away")
        hs, aw = int(match.home_score or 0), int(match.away_score or 0)
        lh, la = LiveOpportunityEngineV2._lambdas(h, a, elapsed)
        base = LiveOpportunityEngineV2._probabilities(hs, aw, lh, la)
        if key in base:
            return base[key]
        if key == "dc_1x":
            return base["home"] + base["draw"]
        if key == "dc_12":
            return base["home"] + base["away"]
        if key == "dc_x2":
            return base["draw"] + base["away"]
        found = re.fullmatch(r"(over|under)_(\d+)_([05])", key)
        if not found:
            return None
        line = float(f"{found.group(2)}.{found.group(3)}")
        goals_now = hs + aw
        needed = math.floor(line - goals_now) + 1
        over = 1.0 if needed <= 0 else 1.0 - LiveOpportunityEngineV2._poisson_cdf(needed - 1, lh + la)
        return over if found.group(1) == "over" else 1.0 - over

    @classmethod
    def _extended_opportunities(cls, match, elapsed: float) -> List[Dict[str, Any]]:
        """Crea oportunidades solo para mercados adicionales con liquidación clara."""
        output = []
        seen = set()
        for odd in match.odds or []:
            price = cls._num(odd.get("price"))
            if not price or price <= 1:
                continue
            # Deja que V2 gestione los mercados que ya conoce.
            if LiveOpportunityEngineV2._market_key(
                odd.get("market_name"), odd.get("name"), odd.get("line"),
                match.home_team, match.away_team
            ):
                continue
            key = cls._extended_market_key(odd, match)
            if not key:
                continue
            identity = (cls._norm(odd.get("market_name")), cls._norm(odd.get("name")), round(price, 4))
            if identity in seen:
                continue
            seen.add(identity)
            model_p = cls._extended_market_probability(key, match, elapsed)
            if model_p is None:
                continue
            # Para doble oportunidad sí existen señales comparables en V2.
            signal_key = key if key in {"dc_1x", "dc_12", "dc_x2"} else None
            if signal_key:
                h = LiveOpportunityEngineV2._features(match.performance or {}, "home")
                a = LiveOpportunityEngineV2._features(match.performance or {}, "away")
                support, contra, coverage, strength = LiveOpportunityEngineV2._signals(
                    signal_key, h, a, int(match.home_score or 0), int(match.away_score or 0), elapsed
                )
            else:
                support, contra, coverage, strength = [], [], 0.0, 0.5
            implied = 1.0 / price
            output.append({
                "market": odd.get("market_name", ""),
                "selection": odd.get("name", ""),
                "line": odd.get("line"),
                "price": price,
                "model_probability": round(model_p, 4),
                "implied_probability": round(implied, 4),
                "edge": round(model_p - implied, 4),
                "edge_pct": round((model_p - implied) * 100, 2),
                "confidence": round(min(.82, .30 + .35 * coverage + .20 * strength), 3),
                "signal_strength": "moderada" if strength >= .55 else "débil",
                "supporting_factors": support,
                "contradicting_factors": contra,
                "data_coverage": round(coverage, 3),
                "model": "vpro_extended_live_market",
                "reason": "V.Pro calculó la probabilidad de este mercado compatible con el modelo de goles LIVE.",
            })
        return output

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        if getattr(match, "is_finished", False):
            return []
        try:
            elapsed = LiveOpportunityEngineV2._elapsed(match.minute, match.period)
        except Exception:
            return []
        if elapsed < 12:
            return []

        reference = cls._reference(match)
        if not reference:
            return []

        xg_check = cls._xg_check(match)
        home = {
            "possession": cls._stat(match.performance or {}, "home", "ball_possession", "possession"),
            "shots": cls._stat(match.performance or {}, "home", "total_shots", "goal_attempts"),
            "shots_on": cls._stat(match.performance or {}, "home", "shots_on_target", "shots_on_goal"),
            "xg": xg_check["home"],
            "big": cls._stat(match.performance or {}, "home", "big_chances", "big_chances_created"),
            "red": cls._stat(match.performance or {}, "home", "red_cards"),
        }
        away = {
            "possession": cls._stat(match.performance or {}, "away", "ball_possession", "possession"),
            "shots": cls._stat(match.performance or {}, "away", "total_shots", "goal_attempts"),
            "shots_on": cls._stat(match.performance or {}, "away", "shots_on_target", "shots_on_goal"),
            "xg": xg_check["away"],
            "big": cls._stat(match.performance or {}, "away", "big_chances", "big_chances_created"),
            "red": cls._stat(match.performance or {}, "away", "red_cards"),
        }
        baseline_side = reference["side"]
        fav, rival = (home, away) if baseline_side == "home" else (away, home)
        supporting, contradicting = [], []
        score = 0.0
        coverage = 0

        possession_gap = None
        if home["possession"] is not None and away["possession"] is not None:
            possession_gap = home["possession"] - away["possession"]
            coverage += 1
            fav_gap = possession_gap if baseline_side == "home" else -possession_gap
            if fav_gap >= cls.MIN_POSSESSION_GAP:
                supporting.append(f"Ventaja de posesión del favorito: {fav_gap:.0f} puntos porcentuales (umbral {cls.MIN_POSSESSION_GAP:.0f})")
                score += 0.22
            elif fav_gap <= -cls.MIN_POSSESSION_GAP:
                contradicting.append(f"El rival supera al favorito en posesión por {abs(fav_gap):.0f} puntos")
                score -= 0.18

        for key, label, weight in (("shots_on", "remates a puerta", 0.20), ("xg", "xG", 0.22),
                                   ("big", "grandes ocasiones", 0.16), ("shots", "remates totales", 0.10)):
            fv, rv = fav[key], rival[key]
            if fv is None or rv is None:
                continue
            coverage += 1
            if fv > rv:
                supporting.append(f"Favorito superior en {label}: {fv:g} vs {rv:g}")
                score += weight
            elif fv < rv:
                contradicting.append(f"Rival superior en {label}: {rv:g} vs {fv:g}")
                score -= weight

        # Señales adicionales del feed LIVE. Se ponderan con cautela para
        # evitar contar como independientes métricas que describen la misma jugada.
        extra_specs = (
            ("xgot", "expected_goals_on_target", "xGOT", 0.14, True),
            ("xa", "expected_assists", "xA", 0.09, True),
            ("touches_box", "touches_in_opposition_box", "toques en área rival", 0.07, True),
            ("corners", "corner_kicks", "córneres", 0.035, True),
            ("final_third", "final_third_passes", "pases en último tercio", 0.035, True),
            ("through", "accurate_through_passes", "pases filtrados", 0.045, True),
            ("key_passes", "key_passes", "pases clave", 0.035, True),
            ("crosses", "crosses", "centros", 0.015, True),
            ("shots_off", "shots_off_goal", "remates fuera", 0.01, True),
            ("blocked", "blocked_shots", "remates bloqueados", 0.01, True),
        )
        for key, stat_name, label, weight, higher_is_better in extra_specs:
            fv = cls._stat(match.performance or {}, "home" if baseline_side == "home" else "away",
                           stat_name, key, label)
            rv = cls._stat(match.performance or {}, "away" if baseline_side == "home" else "home",
                           stat_name, key, label)
            if fv is None or rv is None:
                continue
            coverage += 1
            if abs(fv - rv) < 0.01:
                continue
            if (fv > rv) == higher_is_better:
                supporting.append(f"Favorito superior en {label}: {fv:g} vs {rv:g}")
                score += weight
            else:
                contradicting.append(f"Rival superior en {label}: {rv:g} vs {fv:g}")
                score -= weight

        # Algunas métricas se usan como contexto defensivo/disciplina, no como
        # prueba directa de que un equipo vaya a marcar.
        contextual_stats = (
            ("yellow_cards", "tarjetas amarillas"),
            ("fouls", "faltas"),
            ("goalkeeper_saves", "paradas"),
            ("goals_prevented", "goles evitados"),
            ("tackles", "entradas"),
            ("interceptions", "intercepciones"),
            ("clearances", "despejes"),
            ("offsides", "fueras de juego"),
            ("errors_leading_to_shot", "errores que provocan remate"),
            ("errors_leading_to_goal", "errores que provocan gol"),
        )
        observed_context = []
        for stat_name, label in contextual_stats:
            hv = cls._stat(match.performance or {}, "home", stat_name, label)
            av = cls._stat(match.performance or {}, "away", stat_name, label)
            if hv is not None or av is not None:
                observed_context.append(f"{label}: {hv if hv is not None else 's/d'}-{av if av is not None else 's/d'}")
        if observed_context:
            supporting.append("Contexto adicional: " + "; ".join(observed_context[:5]))

        if fav["red"] is not None and fav["red"] > 0:
            contradicting.append("El favorito tiene al menos una tarjeta roja")
            score -= 0.35
        if rival["red"] is not None and rival["red"] > 0:
            supporting.append("El rival tiene al menos una tarjeta roja")
            score += 0.15

        hs, aw = int(match.home_score or 0), int(match.away_score or 0)
        fav_score = hs if baseline_side == "home" else aw
        rival_score = aw if baseline_side == "home" else hs
        if fav_score < rival_score:
            supporting.append(f"El favorito pierde {hs}-{aw}; se revisa valor en doble oportunidad/empate, no se asume remontada")
        elif fav_score > rival_score:
            supporting.append(f"El favorito va ganando {hs}-{aw}")
            score += 0.05

        if coverage < 2:
            return []

        base = LiveOpportunityEngineV2.evaluate(match)
        base.extend(cls._extended_opportunities(match, elapsed))
        results = []
        for source in base:
            market = str(source.get("market") or "")
            selection = str(source.get("selection") or "")
            text = f"{market} {selection}".lower()
            side = cls._selection_side(selection, match)
            is_double = any(x in text for x in ("doble oportunidad", "double chance"))
            is_btts = any(x in text for x in ("ambos marcan", "both teams", "btts"))
            is_total = any(x in text for x in ("total", "más", "menos", "over", "under"))
            if not (side in {baseline_side, "home" if baseline_side == "away" else "away"} or is_double or is_btts or is_total):
                continue

            favorite_name = cls._norm(reference.get("team"))
            selection_norm = cls._norm(selection)
            covers_favorite = side == baseline_side or (favorite_name and favorite_name in selection_norm)
            if is_double:
                if "1x" in selection_norm:
                    covers_favorite = baseline_side == "home"
                elif "x2" in selection_norm:
                    covers_favorite = baseline_side == "away"
            selected_favorite = bool(covers_favorite)
            local_support = list(source.get("supporting_factors") or []) + supporting
            local_contra = list(source.get("contradicting_factors") or []) + contradicting
            model_p = float(source.get("model_probability") or 0)
            implied = float(source.get("implied_probability") or 0)
            edge = model_p - implied

            # No se permite que una señal de posesión aislada convierta una
            # apuesta en oportunidad: exigimos consenso estadístico y edge mínimo.
            stat_score = score if selected_favorite else -score
            if is_btts or is_total:
                stat_score = score * 0.55
            coherence = max(0.0, min(1.0, 0.50 + stat_score))
            confidence = min(0.91, 0.38 + 0.12 * min(4, coverage) + 0.22 * coherence)
            if len(local_contra) >= 3:
                confidence -= 0.06
            confidence = max(0.30, confidence)

            # El rival solo se recomienda si sus estadísticas realmente
            # superan al favorito o existe una señal contextual fuerte.
            if side and side != baseline_side and score > -0.12:
                continue
            if edge < cls.MIN_EDGE or confidence < cls.MIN_CONFIDENCE:
                continue

            current_favorite_price = None
            for live_odd in match.odds or []:
                live_side = cls._selection_side(str(live_odd.get("name") or ""), match)
                market_name = str(live_odd.get("market_name") or "").lower()
                if live_side == baseline_side and any(term in market_name for term in ("1x2", "resultado", "ganador", "match winner")):
                    candidate_price = cls._num(live_odd.get("price"))
                    if candidate_price and candidate_price > 1:
                        current_favorite_price = candidate_price
                        break
            quota_change_pct = None
            if current_favorite_price is not None:
                baseline_price = float(reference.get("price") or 0)
                if baseline_price > 0:
                    quota_change_pct = (current_favorite_price / baseline_price - 1.0) * 100
                    if quota_change_pct >= 12:
                        local_support.append(f"Cuota LIVE del favorito subió {quota_change_pct:.1f}% desde la referencia")
                    elif quota_change_pct <= -8:
                        local_support.append(f"Cuota LIVE del favorito bajó {abs(quota_change_pct):.1f}% desde la referencia")

            opportunity = dict(source)
            opportunity.update({
                "model": "vpro_live_favorite_tracker",
                "vpro_xg_status": xg_check["status"],
                "vpro_xg_home": xg_check["home"],
                "vpro_xg_away": xg_check["away"],
                "vpro_xg_home_estimated": xg_check.get("home_estimated", False),
                "vpro_xg_away_estimated": xg_check.get("away_estimated", False),
                "vpro_xg_detail": xg_check["detail"],
                "vpro_reference_team": reference.get("team"),
                "vpro_reference_price": float(reference.get("price")),
                "vpro_reference_source": reference.get("source", "cuota_base_guardada"),
                "vpro_current_favorite_price": current_favorite_price,
                "vpro_favorite_quota_change_pct": round(quota_change_pct, 2) if quota_change_pct is not None else None,
                "vpro_possession_gap_points": round(possession_gap, 2) if possession_gap is not None else None,
                "vpro_statistical_score": round(score, 3),
                "vpro_stats_analyzed": [
                    key for key in (
                        "expected_goals", "expected_goals_on_target", "expected_assists",
                        "ball_possession", "goal_attempts", "shots_on_goal", "shots_off_goal",
                        "blocked_shots", "big_chances", "big_chances_missed",
                        "touches_in_opposition_box", "corner_kicks", "accurate_through_passes",
                        "final_third_passes", "key_passes", "crosses", "goalkeeper_saves",
                        "goals_prevented", "yellow_cards", "red_cards", "fouls", "tackles",
                        "interceptions", "clearances", "offsides", "errors_leading_to_shot",
                        "errors_leading_to_goal", "duels_won"
                    )
                    if cls._stat(match.performance or {}, "home", key) is not None
                    or cls._stat(match.performance or {}, "away", key) is not None
                ],
                "vpro_stats_count": len([
                    key for key in (
                        "expected_goals", "expected_goals_on_target", "expected_assists",
                        "ball_possession", "goal_attempts", "shots_on_goal", "shots_off_goal",
                        "blocked_shots", "big_chances", "big_chances_missed",
                        "touches_in_opposition_box", "corner_kicks", "accurate_through_passes",
                        "final_third_passes", "key_passes", "crosses", "goalkeeper_saves",
                        "goals_prevented", "yellow_cards", "red_cards", "fouls", "tackles",
                        "interceptions", "clearances", "offsides", "errors_leading_to_shot",
                        "errors_leading_to_goal", "duels_won"
                    )
                    if cls._stat(match.performance or {}, "home", key) is not None
                    or cls._stat(match.performance or {}, "away", key) is not None
                ]),
                "model_probability": round(model_p, 4),
                "implied_probability": round(implied, 4),
                "edge": round(edge, 4),
                "edge_pct": round(edge * 100, 2),
                "confidence": round(confidence, 3),
                "supporting_factors": local_support[:12],
                "contradicting_factors": local_contra[:12],
                "data_coverage": round(min(1.0, coverage / 5), 3),
                "reason": (
                    f"V.Pro: favorito de referencia {reference.get('team')} (cuota base {float(reference.get('price')):.2f}); "
                    f"minuto {match.minute or 'desconocido'}, marcador {hs}-{aw}. "
                    f"Señales a favor: {len(local_support)}; contradicciones: {len(local_contra)}; "
                    f"ventaja estadística estimada {edge*100:.1f} puntos. Umbral de posesión: {cls.MIN_POSSESSION_GAP:.0f} puntos."
                ),
            })
            results.append(opportunity)

        results.sort(key=lambda x: (float(x.get("selection_score") or 0), float(x.get("edge") or 0),
                                    float(x.get("confidence") or 0)), reverse=True)
        return results[:5]
