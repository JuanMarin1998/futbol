# Aquí irán las pruebas del proyecto más adelante.


from types import SimpleNamespace

from django.test import SimpleTestCase

from .live_engine.opportunity_engine import LiveOpportunityEngine
from .live_engine.opportunity_engine_v3 import LiveOpportunityEngineV3
from .live_engine.experiment import LiveExperimentManager
from .live_engine.models import LiveMatch
from .live_engine.opportunity_engine_v2_ultra import LiveOpportunityEngineV2Ultra
from .live_engine.opportunity_engine_v11_ultra import LiveOpportunityEngineV11Ultra


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




class UltraMotorTests(SimpleTestCase):
    def setUp(self):
        self.match = LiveMatch(
            home_team="Home FC",
            away_team="Away FC",
            minute="65",
            period="2nd half",
            home_score=1,
            away_score=0,
            data_quality=0.9,
            mapping_confidence=0.95,
            performance={
                "home": {
                    "expected_goals": 1.4, "xg": 1.4, "xg_on_target": 1.0,
                    "total_shots": 10, "shots_on_target": 4, "big_chances": 2,
                    "touches_in_opposition_box": 20, "final_third_passes": 40,
                    "expected_assists": 0.6, "ball_possession": 58,
                },
                "away": {
                    "expected_goals": 0.5, "xg": 0.5, "xg_on_target": 0.2,
                    "total_shots": 4, "shots_on_target": 1, "big_chances": 0,
                    "touches_in_opposition_box": 7, "final_third_passes": 18,
                    "expected_assists": 0.1, "ball_possession": 42,
                },
            },
            odds=[
                {"market_name": "1X2", "name": "Home", "price": 1.70, "odd_status": "active"},
                {"market_name": "Total Goals", "name": "Over 3.5", "line": "3.5", "price": 2.40, "odd_status": "active"},
                {"market_name": "Home Team Total Goals", "name": "Over 0.5", "line": "0.5", "price": 1.55, "odd_status": "active"},
                {"market_name": "Asian Handicap", "name": "Home", "line": "-0.5", "price": 1.80, "odd_status": "active"},
                {"market_name": "Player to Score", "name": "Anytime", "price": 2.00, "odd_status": "active"},
                {"market_name": "First Half Result", "name": "Home", "price": 1.90, "odd_status": "active"},
                {"market_name": "1X2", "name": "Away", "price": 3.90, "odd_status": "suspended"},
            ],
        )

    def test_v2_ultra_scans_score_modelable_markets_and_audits_unsupported_ones(self):
        result = LiveOpportunityEngineV2Ultra.evaluate(self.match)
        markets = {(x["market"], x["selection"]) for x in result}
        self.assertIn(("1X2", "Home"), markets)
        self.assertIn(("Total Goals", "Over 3.5"), markets)
        self.assertIn(("Home Team Total Goals", "Over 0.5"), markets)
        self.assertIn(("Asian Handicap", "Home"), markets)
        unsupported = next(x for x in result if x["market"] == "Player to Score")
        self.assertTrue(unsupported["unsupported_market"])
        half_time = next(x for x in result if x["market"] == "First Half Result")
        self.assertTrue(half_time["unsupported_market"])
        self.assertNotIn(("1X2", "Away"), markets)

    def test_v11_ultra_uses_calibration_and_temporal_metadata(self):
        result = LiveOpportunityEngineV11Ultra.evaluate(self.match)
        home = next(x for x in result if x["market"] == "1X2" and x["selection"] == "Home")
        self.assertEqual(home["calibration"], "shrink_to_50_v1_1_ultra")
        self.assertIn("temporal_factor", home)
        self.assertGreaterEqual(home["model_probability"], 0.03)
        self.assertLessEqual(home["model_probability"], 0.97)

    def test_ultra_stakes_respect_level_and_motor_specific_maximums(self):
        from decimal import Decimal
        very_strong = {"level": 1, "confidence": 1.0, "edge": 0.30}
        strong = {"level": 2, "confidence": 1.0, "edge": 0.20}
        self.assertEqual(LiveExperimentManager._stake(very_strong, Decimal("100"), "V2U"), Decimal("20.00"))
        self.assertEqual(LiveExperimentManager._stake(strong, Decimal("100"), "V11U"), Decimal("15.00"))
        self.assertEqual(LiveExperimentManager._stake(strong, Decimal("100"), "V2U"), Decimal("0"))
        self.assertEqual(LiveExperimentManager._stake(very_strong, Decimal("100"), "V11U"), Decimal("0"))

    def test_ultra_motors_have_independent_registry_and_market_sources(self):
        self.assertIn("V2U", LiveExperimentManager.MOTORS)
        self.assertIn("V11U", LiveExperimentManager.MOTORS)
        self.assertEqual(LiveExperimentManager.LABELS["V2U"], "V2.Ultra")
        self.assertEqual(LiveExperimentManager.LABELS["V11U"], "V1.1 Ultra")
        self.assertEqual(LiveExperimentManager.OPPORTUNITY_ATTRS["V2U"], "opportunities_v2_ultra")
        self.assertEqual(LiveExperimentManager.OPPORTUNITY_ATTRS["V11U"], "opportunities_v11_ultra")



from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from .models import LiveExperiment, LiveExperimentEntry


class FinishedExperimentReconciliationTests(TestCase):
    def setUp(self):
        self.experiment = LiveExperiment.objects.create(
            ecuabet_event_id=987654321,
            home_team="Home FC",
            away_team="Away FC",
            status="FINISHED",
            final_home_score=0,
            final_away_score=1,
        )

    def _entry(self, motor, selection, status, pnl, stake="2.00"):
        return LiveExperimentEntry.objects.create(
            experiment=self.experiment,
            motor=motor,
            opportunity_key=f"{motor}|{selection}",
            market="1X2",
            selection=selection,
            price="2.00",
            model_probability=0.70,
            implied_probability=0.50,
            edge=0.20,
            level=1,
            level_name="Muy fuerte",
            stake=stake,
            potential_profit="2.00",
            reason="Prueba de liquidación",
            status=status,
            pnl=pnl,
            settled_at=timezone.now() if status != "OPEN" else None,
        )

    def test_reconcile_does_not_rewrite_already_settled_results_for_any_motor(self):
        # El marcador final favorece Away; una apuesta Home ya registrada como
        # WON debe permanecer intacta: el refresco no puede reescribir el pasado.
        for motor in LiveExperimentManager.MOTORS:
            with self.subTest(motor=motor):
                entry = self._entry(motor, "Home", "WON", "2.00")
                LiveExperimentManager.reconcile_finished(self.experiment.id)
                entry.refresh_from_db()
                self.assertEqual(entry.status, "WON")
                self.assertEqual(entry.pnl, Decimal("2.00"))
                entry.delete()

    def test_reconcile_settles_open_entries_but_preserves_existing_wins_and_losses(self):
        settled_win = self._entry("ESP", "Home", "WON", "2.00")
        settled_loss = self._entry("V22", "Home", "LOST", "-2.00")
        open_entry = self._entry("V11", "Away", "OPEN", "0.00")
        LiveExperimentManager.reconcile_finished(self.experiment.id)
        settled_win.refresh_from_db()
        settled_loss.refresh_from_db()
        open_entry.refresh_from_db()
        self.assertEqual(settled_win.status, "WON")
        self.assertEqual(settled_win.pnl, Decimal("2.00"))
        self.assertEqual(settled_loss.status, "LOST")
        self.assertEqual(settled_loss.pnl, Decimal("-2.00"))
        self.assertEqual(open_entry.status, "WON")
        self.assertEqual(open_entry.pnl, Decimal("2.00"))
