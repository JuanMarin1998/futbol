import unittest

from estadisticas.live_engine.match_mapper import MatchMapper


class MatchMapperAliasTests(unittest.TestCase):
    def test_hassania_union_matches_hassania_agadir(self):
        self.assertEqual(
            MatchMapper._team_similarity("Hassania Union", "Hassania Agadir"),
            1.0,
        )

    def test_hassania_d_agadir_matches_hassania_agadir(self):
        self.assertEqual(
            MatchMapper._team_similarity("Hassania d'Agadir", "Hassania Agadir"),
            1.0,
        )

    def test_as_far_rabat_matches_far_rabat(self):
        self.assertEqual(
            MatchMapper._team_similarity("AS FAR Rabat", "FAR Rabat"),
            1.0,
        )

    def test_aliases_do_not_make_unrelated_teams_equal(self):
        self.assertLess(
            MatchMapper._team_similarity("Hassania Union", "Wydad Casablanca"),
            1.0,
        )

    def test_candidate_score_accepts_alias_pair_as_exact_team_names(self):
        event = {
            "competitors": [
                {"name": "Hassania Union"},
                {"name": "AS FAR Rabat"},
            ],
            "startDate": "2026-10-12T19:00:00+00:00",
        }
        candidate = {
            "event_id": "flashscore-test",
            "home_team": "Hassania Agadir",
            "away_team": "FAR Rabat",
            "start_time": "2026-10-12T19:00:00+00:00",
        }

        result = MatchMapper._candidate_score(event, candidate)

        self.assertEqual(result["home_score"], 1.0)
        self.assertEqual(result["away_score"], 1.0)
        self.assertEqual(result["team_score"], 1.0)
        self.assertEqual(result["orientation"], "direct")


if __name__ == "__main__":
    unittest.main()
