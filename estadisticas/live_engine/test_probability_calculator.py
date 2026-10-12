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
