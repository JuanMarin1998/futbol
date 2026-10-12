import unittest
from types import SimpleNamespace

from estadisticas.live_engine.probability_calculator import LiveProbabilityCalculator


class LiveProbabilityCalculatorTimeTests(unittest.TestCase):
    def make_match(self, minute, home_score=0, away_score=0):
        return SimpleNamespace(
            performance={"home": {}, "away": {}},
            home_score=home_score,
            away_score=away_score,
            minute=minute,
        )

    def test_halftime_text_means_45_minutes(self):
        self.assertEqual(LiveProbabilityCalculator._minute("Descanso"), 45)
        self.assertEqual(LiveProbabilityCalculator._minute("Half Time"), 45)

    def test_halftime_does_not_calculate_as_if_full_match_remains(self):
        result = LiveProbabilityCalculator.calculate(
            self.make_match("Descanso"),
            pre_match_context={
                "home_odds": 1.65,
                "draw_odds": 3.8,
                "away_odds": 4.2,
            },
        )
        self.assertLess(result["probabilidades"]["home"], 1.0)
        self.assertLess(result["minutos_restantes_estimados"], 90)

    def test_calculates_both_teams_to_score_and_goal_totals(self):
        result = LiveProbabilityCalculator.calculate(
            self.make_match(45, home_score=1, away_score=0),
            pre_match_context={"home_odds": 1.65, "draw_odds": 3.8, "away_odds": 4.2},
        )
        markets = {item["clave"]: item for item in result["mercados_probables"]}
        for key in ("btts_yes", "btts_no", "over_0_5", "under_0_5", "over_1_5", "under_1_5", "over_2_5", "under_2_5", "over_3_5", "under_3_5"):
            self.assertIn(key, markets)
            self.assertGreaterEqual(markets[key]["probabilidad"], 0)
            self.assertLessEqual(markets[key]["probabilidad"], 100)
        self.assertAlmostEqual(markets["over_1_5"]["probabilidad"] + markets["under_1_5"]["probabilidad"], 100.0, places=2)

    def test_btts_yes_is_closed_once_both_teams_have_scored(self):
        result = LiveProbabilityCalculator.calculate(self.make_match(70, home_score=1, away_score=1))
        markets = {item["clave"]: item for item in result["mercados_probables"]}
        self.assertEqual(markets["btts_yes"]["estado_live"], "CERRADO_RESULTADO_DETERMINADO")

    def test_red_card_changes_live_goal_context(self):
        match = self.make_match(70, home_score=1, away_score=1)
        match.performance = {
            "home": {"red_cards": {"value": 1, "label": "Tarjetas rojas"}},
            "away": {"red_cards": {"value": 0, "label": "Tarjetas rojas"}},
        }
        result = LiveProbabilityCalculator.calculate(
            match, pre_match_context={"home_odds": 2.0, "draw_odds": 3.4, "away_odds": 3.5}
        )
        self.assertTrue(any("inferioridad numérica local" in item for item in result["estadisticas_utilizadas"]))

    def test_minute_97_does_not_force_draw_to_certain_x2(self):
        result = LiveProbabilityCalculator.calculate(
            self.make_match("97'", home_score=2, away_score=2),
            pre_match_context={
                "home_odds": 4.5,
                "draw_odds": 2.85,
                "away_odds": 1.89,
            },
        )
        self.assertLess(result["probabilidades"]["dc_x2"], 1.0)
        self.assertGreater(result["probabilidades"]["home"], 0.0)


if __name__ == "__main__":
    unittest.main()
