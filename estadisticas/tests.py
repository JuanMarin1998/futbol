# Aquí irán las pruebas del proyecto más adelante.


from types import SimpleNamespace

from django.test import SimpleTestCase

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
