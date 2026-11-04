"""Tests for player selection use cases."""

import unittest

from fantasy_football_ai_analyst.player import Player
from fantasy_football_ai_analyst.analysis import find_players, shortlist_players


class FindPlayersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.players = [
            Player("Alex Example", 1, 3, 7.5, 120),
            Player("Jamie Sample", 2, 2, 6.2, 94),
        ]

    def test_matches_names_without_case_sensitivity(self) -> None:
        found = find_players(self.players, [" alex example ", "JAMIE SAMPLE"])

        self.assertEqual(found, self.players)

    def test_reports_an_unknown_player(self) -> None:
        with self.assertRaisesRegex(ValueError, "No player found"):
            find_players(self.players, ["Unknown Player"])

    def test_reports_an_ambiguous_name(self) -> None:
        duplicate_name = Player("Alex Example", 2, 3, 6.5, 80)

        with self.assertRaisesRegex(ValueError, "More than one player"):
            find_players(self.players + [duplicate_name], ["Alex Example"])

    def test_ids_resolve_ambiguous_names_and_preserve_requested_order(self) -> None:
        first = Player("Alex Example", 1, 3, 7.5, 120, player_id=10)
        second = Player("Alex Example", 2, 3, 6.5, 80, player_id=20)
        with self.assertRaisesRegex(ValueError, "10, 20"):
            find_players([first, second], ["Alex Example"])
        self.assertEqual(find_players([first, second], ["20", "10"]), [second, first])


class ShortlistPlayersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.expensive = Player("Alex Example", 1, 3, 7.5, 120, minutes=1800, team_name="Arsenal")
        self.value = Player("Casey Value", 2, 3, 5, 100, minutes=900, team_name="Chelsea")
        self.defender = Player("Jamie Sample", 3, 2, 6, 110, minutes=1800, team_name="Arsenal")
        self.unknown = Player("Morgan Unknown", 4, 3, 4, 0)
        self.players = [self.expensive, self.value, self.defender, self.unknown]

    def test_combines_filters_before_applying_limit(self) -> None:
        found = shortlist_players(
            self.players, position="mid", max_price=5, min_minutes=900, limit=1
        )
        self.assertEqual(found, [self.value])

    def test_sorting_changes_order_without_changing_input(self) -> None:
        original = self.players.copy()
        expected = {
            "points": [self.expensive, self.defender, self.value, self.unknown],
            "price": [self.unknown, self.value, self.defender, self.expensive],
            "points-per-million": [self.value, self.defender, self.expensive, self.unknown],
            "points-per-90": [self.value, self.expensive, self.defender, self.unknown],
        }
        for sort_by, players in expected.items():
            with self.subTest(sort_by=sort_by):
                self.assertEqual(shortlist_players(self.players, sort_by=sort_by), players)
        self.assertEqual(self.players, original)

    def test_unknown_metric_sorts_after_negative_values(self) -> None:
        negative = Player("Negative Points", 1, 3, 5, -1, minutes=90)
        self.assertEqual(
            shortlist_players([self.unknown, negative], sort_by="points-per-90"),
            [negative, self.unknown],
        )

    def test_ties_are_broken_by_name_then_id(self) -> None:
        first = Player("Alex", 1, 3, 5, 10, player_id=1)
        second = Player("Alex", 1, 3, 5, 10, player_id=2)
        third = Player("Jamie", 1, 3, 5, 10, player_id=3)
        self.assertEqual(shortlist_players([third, second, first]), [first, second, third])

    def test_no_matches_is_an_empty_list(self) -> None:
        self.assertEqual(shortlist_players(self.players, position="GK"), [])

    def test_team_filter_ignores_case_and_surrounding_spaces(self) -> None:
        for team in ("arsenal", "ARSENAL", " ArSeNaL "):
            with self.subTest(team=team):
                self.assertEqual(
                    shortlist_players(self.players, team=team),
                    [self.expensive, self.defender],
                )

    def test_unrecognized_team_keeps_other_filters_sorting_and_limit(self) -> None:
        for team in ("Arsnal", "", "   "):
            with self.subTest(team=team):
                self.assertEqual(
                    shortlist_players(
                        self.players, team=team, position="MID", max_price=6,
                        min_minutes=900, sort_by="price", limit=1,
                    ),
                    [self.value],
                )

    def test_valid_team_does_not_fall_back_when_other_filters_exclude_its_players(self) -> None:
        self.assertEqual(
            shortlist_players(self.players, team="Arsenal", position="MID", max_price=6),
            [],
        )

    def test_unrecognized_team_keeps_players_with_missing_team_names(self) -> None:
        self.assertEqual(shortlist_players([self.unknown], team="Arsenal"), [self.unknown])
        self.assertEqual(shortlist_players([], team="Arsenal"), [])

    def test_invalid_options_produce_useful_errors(self) -> None:
        invalid_options = [
            {"position": "winger"},
            {"max_price": -1},
            {"max_price": float("nan")},
            {"max_price": float("inf")},
            {"min_minutes": -1},
            {"limit": 0},
            {"sort_by": "expected-points"},
        ]
        for options in invalid_options:
            with self.subTest(options=options), self.assertRaises(ValueError):
                shortlist_players(self.players, **options)


if __name__ == "__main__":
    unittest.main()
