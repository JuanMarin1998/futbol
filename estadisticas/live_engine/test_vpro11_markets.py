from types import SimpleNamespace

from django.test import SimpleTestCase

from .opportunity_engine_vpro11 import LiveOpportunityEngineVPro11


class VPro11MarketScanTests(SimpleTestCase):
    def setUp(self):
        self.match = SimpleNamespace(
            is_finished=False,
            minute="38",
            period="1st half",
            home_team="Cagliari",
            away_team="Juventus",
            home_score=1,
            away_score=0,
            mapping_confidence=0.95,
            data_quality=0.9,
            performance={
                "home": {
                    "ball_possession": 28,
                    "total_shots": 3,
                    "shots_on_target": 2,
                    "expected_goals": 0.49,
                    "xgot": 0.58,
                    "big_chances": 1,
                    "touches_in_opposition_box": 3,
                    "expected_assists": 0.49,
                    "corner_kicks": 1,
                    "final_third_passes": 12,
                },
                "away": {
                    "ball_possession": 72,
                    "total_shots": 6,
                    "shots_on_target": 0,
                    "expected_goals": 0.19,
                    "xgot": 0.0,
                    "big_chances": 0,
                    "touches_in_opposition_box": 19,
                    "expected_assists": 0.60,
                    "corner_kicks": 3,
                    "final_third_passes": 19,
                },
            },
            odds=[
                {
                    "market_name": "Doble oportunidad",
                    "name": "Cagliari o Empate",
                    "line": None,
                    "price": 1.364,
                },
                {
                    "market_name": "Total goles",
                    "name": "Menos de 3.5",
                    "line": 3.5,
                    "price": 1.25,
                },
                {
                    "market_name": "Total goles",
                    "name": "Más de 2.5",
                    "line": 2.5,
                    "price": 1.975,
                },
            ],
        )

    def test_scans_double_chance_and_multiple_goal_lines(self):
        candidates = LiveOpportunityEngineVPro11._all_market_candidates(
            self.match, elapsed=38
        )
        selections = {item["selection"] for item in candidates}

        self.assertIn("Cagliari o Empate", selections)
        self.assertIn("Menos de 3.5", selections)
        self.assertIn("Más de 2.5", selections)

    def test_combined_market_is_not_given_simple_double_chance_probability(self):
        self.match.odds.append({
            "market_name": "Doble oportunidad y multigoles",
            "name": "1X & Multigoles 4-5",
            "line": None,
            "price": 31.0,
        })

        candidates = LiveOpportunityEngineVPro11._all_market_candidates(
            self.match, elapsed=38
        )
        selections = {item["selection"] for item in candidates}

        self.assertNotIn("1X & Multigoles 4-5", selections)

    def test_each_candidate_has_market_specific_probability(self):
        candidates = LiveOpportunityEngineVPro11._all_market_candidates(
            self.match, elapsed=38
        )
        by_selection = {item["selection"]: item for item in candidates}

        for selection in ("Cagliari o Empate", "Menos de 3.5", "Más de 2.5"):
            self.assertGreaterEqual(by_selection[selection]["model_probability"], 0)
            self.assertLessEqual(by_selection[selection]["model_probability"], 1)
            self.assertIn("price", by_selection[selection])
