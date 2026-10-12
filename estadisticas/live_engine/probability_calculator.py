"""Calculador central de probabilidades LIVE para mercados de fútbol.

No crea apuestas ni decide si una señal es oportunidad. Recibe el partido, sus
estadísticas disponibles y las cuotas prepartido guardadas; devuelve probabilidades
para 1X2, doble oportunidad y ambos marcan. Los datos ausentes se reportan, nunca
se rellenan con estadísticas inventadas.
"""
from __future__ import annotations

import math
import re
import unicodedata


MARKETS = (
    ("Victoria local", "home"),
    ("Empate", "draw"),
    ("Victoria visitante", "away"),
    ("Doble oportunidad 1X", "dc_1x"),
    ("Doble oportunidad 12", "dc_12"),
    ("Doble oportunidad X2", "dc_x2"),
    ("Ambos marcan: sí", "btts_yes"),
    ("Ambos marcan: no", "btts_no"),
)


def _norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in value if not unicodedata.combining(c)).lower().strip()


def _number(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("raw_value", value.get("displayValue")))
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace("%", "").replace(",", ".")
        if value in {"", "-", "—", "N/A"}:
            return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _stat(stats, side, aliases):
    data = stats.get(side) if isinstance(stats, dict) else {}
    if not isinstance(data, dict):
        return None
    wanted = {_norm(alias) for alias in aliases}
    for key, item in data.items():
        label = _norm(key)
        if label in wanted:
            value = _number(item)
            if value is not None:
                return value
        if isinstance(item, dict):
            label = _norm(item.get("label") or item.get("name") or key)
            if label in wanted:
                value = _number(item)
                if value is not None:
                    return value
    return None


def _poisson(lam, limit=10):
    lam = max(0.0, min(float(lam), 6.0))
    values = [math.exp(-lam)]
    for k in range(1, limit + 1):
        values.append(values[-1] * lam / k)
    total = sum(values)
    return [v / total for v in values]


def _normalize(values):
    total = sum(max(0.0, float(v)) for v in values)
    if total <= 0:
        return [1 / len(values)] * len(values)
    return [max(0.0, float(v)) / total for v in values]


def _odds_prior(context):
    if not isinstance(context, dict):
        return None
    prices = []
    for key in ("home_odds", "draw_odds", "away_odds"):
        try:
            price = float(context.get(key))
            prices.append(1.0 / price if price > 1.0 else None)
        except (TypeError, ValueError):
            prices.append(None)
    if any(v is None for v in prices):
        return None
    return _normalize(prices)


class LiveProbabilityCalculator:
    """Calcula una referencia probabilística única a partir del snapshot LIVE."""

    @classmethod
    def calculate(cls, match, pre_match_context=None):
        stats = match.performance if isinstance(match.performance, dict) else {}
        home_score = max(0, int(match.home_score or 0))
        away_score = max(0, int(match.away_score or 0))
        minute = cls._minute(match.minute)
        remaining = max(0.0, min(1.0, (90.0 - minute) / 90.0))
        if minute > 90:
            remaining = 0.0

        # Estadísticas que miden amenaza ofensiva. Solo se usan si existen en el feed.
        aliases = {
            "shots": ("total shots", "shots", "tiros totales", "total shots"),
            "sot": ("shots on goal", "shots on target", "tiros a puerta", "shots on target"),
            "corners": ("corner kicks", "corners", "corners kicks", "saques de esquina"),
            "dangerous": ("dangerous attacks", "ataques peligrosos"),
            "possession": ("ball possession", "possession", "posesion", "posesion del balon"),
        }
        observed = {}
        for side in ("home", "away"):
            observed[side] = {
                key: _stat(stats, side, values)
                for key, values in aliases.items()
            }

        # El mercado prepartido funciona como punto de partida, no como certeza.
        prior = _odds_prior(pre_match_context)
        if prior:
            home_share = max(0.20, min(0.80, prior[0] / max(0.05, prior[0] + prior[2])))
        else:
            home_share = 0.50

        # Ritmo ofensivo esperado hasta el final. La evidencia LIVE ajusta las tasas
        # con límites conservadores para que una sola estadística no domine el cálculo.
        base_remaining_goals = 2.55 * remaining
        lambda_home = base_remaining_goals * home_share
        lambda_away = base_remaining_goals * (1.0 - home_share)
        evidence = []
        quality_points = 0

        def apply_attack_metric(key, weight, scale, description):
            nonlocal lambda_home, lambda_away, quality_points
            h = observed["home"].get(key)
            a = observed["away"].get(key)
            if h is None or a is None:
                return
            delta = max(-1.0, min(1.0, (h - a) / max(scale, abs(h) + abs(a), 1.0)))
            # Multiplicador acotado por lado; no transforma estadísticas en certezas.
            lambda_home *= math.exp(weight * delta)
            lambda_away *= math.exp(-weight * delta)
            evidence.append(f"{description}: local {h:g}, visitante {a:g}")
            quality_points += 1

        apply_attack_metric("sot", 0.32, 5.0, "Tiros a puerta")
        apply_attack_metric("shots", 0.16, 12.0, "Tiros totales")
        apply_attack_metric("corners", 0.08, 8.0, "Saques de esquina")
        apply_attack_metric("dangerous", 0.12, 30.0, "Ataques peligrosos")

        home_poss = observed["home"].get("possession")
        away_poss = observed["away"].get("possession")
        if home_poss is not None and away_poss is not None:
            delta = max(-1.0, min(1.0, (home_poss - away_poss) / 50.0))
            lambda_home *= math.exp(0.08 * delta)
            lambda_away *= math.exp(-0.08 * delta)
            evidence.append(f"Posesión: local {home_poss:g}%, visitante {away_poss:g}%")
            quality_points += 1

        # No proyectar goles restantes cuando el reloj ya llegó al final.
        if remaining <= 0:
            lambda_home = lambda_away = 0.0
        home_goals = _poisson(lambda_home)
        away_goals = _poisson(lambda_away)
        home_win = draw = away_win = both_yes = 0.0
        for h_extra, ph in enumerate(home_goals):
            for a_extra, pa in enumerate(away_goals):
                probability = ph * pa
                final_home = home_score + h_extra
                final_away = away_score + a_extra
                if final_home > final_away:
                    home_win += probability
                elif final_home == final_away:
                    draw += probability
                else:
                    away_win += probability
                if final_home > 0 and final_away > 0:
                    both_yes += probability

        outcome = _normalize([home_win, draw, away_win])
        # Las cuotas solo se mezclan de forma moderada y después de condicionar
        # la distribución al marcador LIVE actual.
        if prior:
            outcome = _normalize([0.75 * outcome[i] + 0.25 * prior[i] for i in range(3)])

        probabilities = {
            "home": outcome[0],
            "draw": outcome[1],
            "away": outcome[2],
            "dc_1x": outcome[0] + outcome[1],
            "dc_12": outcome[0] + outcome[2],
            "dc_x2": outcome[1] + outcome[2],
            "btts_yes": both_yes,
            "btts_no": 1.0 - both_yes,
        }
        probabilities = {key: max(0.0, min(1.0, value)) for key, value in probabilities.items()}
        ranked = [
            {"mercado": label, "clave": key, "probabilidad": round(probabilities[key] * 100, 2), "estado_live": "ABIERTO"}
            for label, key in MARKETS
        ]
        ranked.sort(key=lambda item: item["probabilidad"], reverse=True)
        available_stats = sum(
            value is not None
            for side in observed.values()
            for value in side.values()
        )
        data_quality = min(1.0, quality_points / 4.0)
        confidence = min(0.90, 0.35 + 0.10 * quality_points + (0.10 if prior else 0.0))
        if available_stats == 0:
            confidence = min(confidence, 0.45)

        return {
            "status": "CALCULADO" if available_stats or prior else "CALCULADO_CON_DATOS_LIMITADOS",
            "probabilidades": probabilities,
            "mercados_probables": ranked,
            "mas_probable": ranked[0] if ranked else None,
            "estadisticas_detectadas": observed,
            "estadisticas_utilizadas": evidence,
            "cantidad_estadisticas_utilizadas": quality_points,
            "calidad_datos": round(data_quality, 2),
            "confianza_calculador": round(confidence, 2),
            "cuotas_prepartido_utilizadas": bool(prior),
            "minuto": minute,
            "minutos_restantes_estimados": round(90.0 - minute, 1) if minute <= 90 else 0.0,
            "metodo": "Distribución Poisson de goles restantes, ajustada con estadísticas LIVE y mezcla moderada con probabilidades implícitas prepartido sin margen.",
            "limitaciones": (
                [] if available_stats >= 2 else
                ["El feed aporta pocas estadísticas comparables; la estimación depende más del marcador, minuto y contexto prepartido."]
            ),
        }

    @staticmethod
    def _minute(value):
        match = re.search(r"\d+", str(value or ""))
        return max(0, min(120, int(match.group(0)))) if match else 0
