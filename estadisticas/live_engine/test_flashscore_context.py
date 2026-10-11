import unittest

from estadisticas.live_engine.flashscore_context import FlashscoreContextProvider


class FlashscoreContextNormalizerTests(unittest.TestCase):
    def test_normalize_lineups_home_away(self):
        data = FlashscoreContextProvider._normalize_lineups({
            "data": {
                "lineups": {
                    "home": {"formation": "4-3-3", "starters": [{"name": "Player A"}]},
                    "away": {"formation": "4-4-2", "starters": [{"name": "Player B"}]},
                }
            }
        })
        self.assertEqual(data["home"]["formation"], "4-3-3")
        self.assertEqual(data["away"]["formation"], "4-4-2")

    def test_normalize_match_rows(self):
        rows = FlashscoreContextProvider._normalize_matches({
            "matches": [{
                "matchId": "abc123",
                "status": "finished",
                "home": {"name": "Home FC"},
                "away": {"name": "Away FC"},
                "scoreHome": 2,
                "scoreAway": 1,
            }]
        })
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["match_id"], "abc123")
        self.assertEqual(rows[0]["home_score"], 2)
        self.assertEqual(rows[0]["away_score"], 1)

    def test_unconfigured_provider_reports_unavailable_without_raising(self):
        provider = FlashscoreContextProvider(base_url="")
        context = provider.obtener_contexto("event123", "home123", "away123")
        self.assertEqual(context["lineups"]["status"], "unavailable")
        self.assertEqual(context["history"]["status"], "unavailable")
        self.assertEqual(context["fixtures"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
