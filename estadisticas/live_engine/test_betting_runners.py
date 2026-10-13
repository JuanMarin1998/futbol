from decimal import Decimal

from django.test import TestCase

from estadisticas.live_engine.betting_runners import BettingRunnerLab
from estadisticas.models import BettingRunner, BettingRunnerBet


class BettingRunnerLabTests(TestCase):
    def setUp(self):
        BettingRunnerLab.seed_runners()
        self.payload = {
            "ok": True,
            "partido": {
                "id": 123456,
                "local": "Always Ready",
                "visitante": "Independiente Petrolero",
                "minuto": "Descanso",
                "marcador": [1, 0],
            },
            "etapas": {
                "contexto": {"favorito": "Always Ready"},
                "monitoreo": {
                    "detonante": True,
                    "ultimo_detonante": {
                        "tipo": "GOL",
                        "marcador": [1, 0],
                        "registrado_en": "2026-10-13T12:00:00-05:00",
                    },
                },
                "probabilidad": {
                    "confianza_calculador": 0.80,
                    "calidad_datos": 0.80,
                    "cantidad_estadisticas_utilizadas": 3,
                },
                "calculo": {
                    "mercados": [
                        {
                            "clave": "under_3_5",
                            "mercado": "Menos de 3.5 goles",
                            "probabilidad": 79.84,
                            "probabilidad_decimal": 0.7984,
                            "cuota_ecuabet": 1.525,
                            "estado_cuota_ecuabet": "DISPONIBLE",
                            "estado_live": "ABIERTO",
                        },
                        {
                            "clave": "home",
                            "mercado": "Victoria local",
                            "probabilidad": 77.28,
                            "probabilidad_decimal": 0.7728,
                            "cuota_ecuabet": 1.313,
                            "estado_cuota_ecuabet": "DISPONIBLE",
                            "estado_live": "ABIERTO",
                        },
                        {
                            "clave": "away",
                            "mercado": "Victoria visitante",
                            "probabilidad": 0.5,
                            "probabilidad_decimal": 0.005,
                            "cuota_ecuabet": None,
                            "estado_cuota_ecuabet": "NO_ENCONTRADA_EN_ECUABET",
                            "estado_live": "ABIERTO",
                        },
                    ]
                },
            },
        }

    def test_six_runners_record_at_most_one_bet_per_match(self):
        first = BettingRunnerLab.process_payload(123456, self.payload)
        second = BettingRunnerLab.process_payload(123456, self.payload)
        self.assertEqual(first["bets_placed"], 6)
        self.assertEqual(second["bets_placed"], 0)
        self.assertEqual(BettingRunnerBet.objects.filter(ecuabet_event_id=123456).count(), 6)
        for runner in BettingRunner.objects.all():
            self.assertEqual(
                BettingRunnerBet.objects.filter(runner=runner, ecuabet_event_id=123456).count(),
                1,
            )

    def test_lives_follow_engine_ledger_accounting(self):
        runner = BettingRunner.objects.get(key="valor")
        bet = BettingRunnerBet.objects.create(
            runner=runner,
            ecuabet_event_id=777,
            home_team="Local",
            away_team="Visitante",
            market_key="home",
            market="resultado",
            selection="local",
            price=Decimal("2.0000"),
            model_probability=0.60,
            confidence=0.70,
            edge=0.20,
            stake=Decimal("2.0000"),
            potential_profit=Decimal("2.0000"),
            status="OPEN",
            reason="Prueba",
        )
        self.assertEqual(BettingRunnerLab.lives(runner), Decimal("98.0000"))
        bet.status = "WON"
        bet.pnl = Decimal("2.0000")
        bet.save(update_fields=["status", "pnl"])
        self.assertEqual(BettingRunnerLab.lives(runner), Decimal("102.0000"))

    def test_unavailable_ecuabet_price_never_creates_a_bet(self):
        payload = dict(self.payload)
        payload["etapas"] = {
            **self.payload["etapas"],
            "calculo": {"mercados": [{
                "clave": "home",
                "mercado": "Victoria local",
                "probabilidad": 99,
                "probabilidad_decimal": 0.99,
                "cuota_ecuabet": None,
                "estado_cuota_ecuabet": "NO_ENCONTRADA_EN_ECUABET",
                "estado_live": "ABIERTO",
            }]},
        }
        result = BettingRunnerLab.process_payload(987654, payload)
        self.assertEqual(result["bets_placed"], 0)
        self.assertEqual(BettingRunnerBet.objects.filter(ecuabet_event_id=987654).count(), 0)

    def test_no_trigger_globally_blocks_every_runner(self):
        payload = dict(self.payload)
        payload["etapas"] = {
            **self.payload["etapas"],
            "monitoreo": {
                "detonante": False,
                "ultimo_detonante": None,
            },
            "probabilidad": {
                "confianza_calculador": 0.45,
                "calidad_datos": 0.20,
                "cantidad_estadisticas_utilizadas": 0,
            },
            "calculo": {"mercados": [{
                "clave": "under_3_5",
                "mercado": "Menos de 3.5 goles",
                "probabilidad": 79.84,
                "probabilidad_decimal": 0.7984,
                "cuota_ecuabet": 1.525,
                "estado_cuota_ecuabet": "DISPONIBLE",
                "estado_live": "ABIERTO",
            }]},
        }
        result = BettingRunnerLab.process_payload(555555, payload)
        self.assertEqual(result["bets_placed"], 0)
        self.assertEqual(result["status"], "WAITING_TRIGGER")
        self.assertEqual(BettingRunnerBet.objects.filter(ecuabet_event_id=555555).count(), 0)

    def test_settlement_updates_pnl_and_is_idempotent(self):
        BettingRunnerLab.process_payload(123456, self.payload)
        settled = BettingRunnerLab.settle_event(123456, 4, 0, True)
        self.assertEqual(settled, 6)
        self.assertEqual(BettingRunnerBet.objects.filter(
            ecuabet_event_id=123456, status="LOST"
        ).count(), 6)
        for runner in BettingRunner.objects.all():
            self.assertEqual(BettingRunnerLab.lives(runner), Decimal("90.0000"))
        self.assertEqual(BettingRunnerLab.settle_event(123456, 4, 0, True), 0)
