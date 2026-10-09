# Aquí irán las pruebas del proyecto más adelante.


from types import SimpleNamespace

from django.test import SimpleTestCase

from .live_engine.opportunity_engine import LiveOpportunityEngine
from .live_engine.opportunity_engine_v3 import LiveOpportunityEngineV3
from .live_engine.experiment import LiveExperimentManager


class LiveOpportunityEngineV3Tests(SimpleTestCase):
    def test_rejects_match_without_verified_score(self):
        match = SimpleNamespace(
            is_finished=False, home_score=None, away_score=None,
            odds=[{"market_name": "1X2", "name": "Home", "price": 1.80}],
        )
        self.assertEqual(LiveOpportunityEngineV3.evaluate(match), [])

    def test_market_margin_is_removed_when_all_outcomes_are_available(self):
        odds = [
            {"market_name": "1X2", "name": "Home", "line": None, "price": 1.80},
            {"market_name": "1X2", "name": "Draw", "line": None, "price": 3.40},
            {"market_name": "1X2", "name": "Away", "line": None, "price": 4.50},
        ]
        fair = LiveOpportunityEngineV3._market_fair_probabilities(odds)
        self.assertAlmostEqual(sum(fair.values()), 1.0, places=6)

    def test_suspended_odds_are_not_active(self):
        self.assertFalse(LiveOpportunityEngineV3._active_odd({"odd_status": "suspended"}))
        self.assertTrue(LiveOpportunityEngineV3._active_odd({"odd_status": "active"}))
        self.assertTrue(LiveOpportunityEngineV3._active_odd({"price": 1.75}))

    def test_correlated_markets_share_a_family(self):
        total = LiveExperimentManager._v3_market_family({"market": "Total goles", "selection": "Over 2.5"})
        btts = LiveExperimentManager._v3_market_family({"market": "Ambos equipos marcan", "selection": "Sí"})
        self.assertEqual(total, btts)

    def test_result_markets_share_a_family(self):
        result = LiveExperimentManager._v3_market_family({"market": "1X2", "selection": "Home"})
        double_chance = LiveExperimentManager._v3_market_family({"market": "Doble oportunidad", "selection": "1X"})
        self.assertEqual(result, double_chance)



class LiveOpportunityCalculationAuditTests(SimpleTestCase):
    def test_non_v3_edge_is_recomputed_from_model_and_decimal_odds(self):
        opportunities = LiveExperimentManager._prepare_opportunities("V2", [{
            "market": "1X2", "selection": "Home", "price": 1.70,
            "model_probability": 0.80, "implied_probability": 0.588,
            "edge": 0.254, "confidence": 0.80,
        }])
        self.assertEqual(len(opportunities), 1)
        item = opportunities[0]
        self.assertAlmostEqual(item["implied_probability"], 1 / 1.70, places=6)
        self.assertAlmostEqual(item["edge"], 0.80 - 1 / 1.70, places=6)
        self.assertAlmostEqual(item["edge_pct"], (0.80 - 1 / 1.70) * 100, places=2)
        self.assertEqual(item["edge_basis"], "probabilidad_implícita_de_cuota")

    def test_v3_keeps_conservative_edge_against_fair_market_probability(self):
        opportunities = LiveExperimentManager._prepare_opportunities("V3", [{
            "market": "1X2", "selection": "Home", "price": 1.70,
            "model_probability": 0.80, "implied_probability": 1 / 1.70,
            "market_fair_probability": 0.55, "edge": 0.20,
            "edge_pct": 20.0, "confidence": 0.80,
        }])
        self.assertEqual(len(opportunities), 1)
        item = opportunities[0]
        self.assertAlmostEqual(item["implied_probability"], 1 / 1.70, places=6)
        self.assertAlmostEqual(item["edge"], 0.20, places=6)
        self.assertEqual(item["edge_basis"], "probabilidad_justa_de_mercado")



class LivePoissonTotalsTests(SimpleTestCase):
    def test_totals_already_reached_are_certain(self):
        result = LiveOpportunityEngine._probabilities(2, 1, 0.0, 0.0)
        self.assertEqual(result["over_0_5"], 1.0)
        self.assertEqual(result["over_1_5"], 1.0)
        self.assertEqual(result["over_2_5"], 1.0)
        self.assertEqual(result["under_2_5"], 0.0)

    def test_one_current_goal_only_guarantees_over_half(self):
        result = LiveOpportunityEngine._probabilities(1, 0, 0.0, 0.0)
        self.assertEqual(result["over_0_5"], 1.0)
        self.assertEqual(result["over_1_5"], 0.0)
        self.assertEqual(result["over_2_5"], 0.0)
        self.assertEqual(result["under_2_5"], 1.0)

    def test_scoreless_match_with_no_remaining_goals(self):
        result = LiveOpportunityEngine._probabilities(0, 0, 0.0, 0.0)
        self.assertEqual(result["over_0_5"], 0.0)
        self.assertEqual(result["over_1_5"], 0.0)
        self.assertEqual(result["over_2_5"], 0.0)
        self.assertEqual(result["under_2_5"], 1.0)


class LiveEngineCalibrationAndDedupTests(SimpleTestCase):
    def test_all_six_original_and_derived_motors_recompute_edge(self):
        # Verifica la capa de laboratorio de cada motor sin alterar sus algoritmos.
        for motor in ("V1", "V11", "V12", "V2", "V21", "V22"):
            with self.subTest(motor=motor):
                items = LiveExperimentManager._prepare_opportunities(motor, [{
                    "market": "1X2", "selection": "Home", "price": 2.00,
                    "model_probability": 0.80, "implied_probability": 0.10,
                    "edge": 0.99, "confidence": 0.80,
                }])
                self.assertEqual(len(items), 1)
                self.assertAlmostEqual(items[0]["implied_probability"], 0.50, places=6)
                self.assertAlmostEqual(items[0]["edge"], 0.30, places=6)
                self.assertEqual(items[0]["edge_basis"], "probabilidad_implícita_de_cuota")

    def test_duplicate_key_normalizes_market_aliases_accents_and_decimal_line(self):
        first = LiveExperimentManager._key({
            "market": "Total goles", "selection": "Over 2.50", "line": None,
        })
        repeated = LiveExperimentManager._key({
            "market": "Goles totales", "selection": "Más de 2,5", "line": "",
        })
        self.assertEqual(first, repeated)

    def test_different_total_lines_are_not_collapsed_into_one_duplicate(self):
        first = LiveExperimentManager._key({
            "market": "Total goles", "selection": "Over 1.5", "line": None,
        })
        second = LiveExperimentManager._key({
            "market": "Total goles", "selection": "Over 2.5", "line": None,
        })
        self.assertNotEqual(first, second)

    def test_historical_calibration_summary_reports_brier_and_reliability_gap(self):
        result = LiveExperimentManager._calibration_summary([
            (0.80, "WON"),
            (0.80, "LOST"),
        ])
        self.assertEqual(result["sample_size"], 2)
        self.assertEqual(result["win_rate"], 50.0)
        self.assertEqual(result["mean_probability"], 80.0)
        self.assertAlmostEqual(result["brier_score"], 0.34, places=6)
        self.assertEqual(result["expected_calibration_error"], 30.0)

    def test_calibration_summary_ignores_open_and_invalid_rows(self):
        result = LiveExperimentManager._calibration_summary([
            (0.75, "WON"),
            (0.25, "OPEN"),
            ("invalid", "LOST"),
        ])
        self.assertEqual(result["sample_size"], 1)
        self.assertEqual(result["win_rate"], 100.0)

