"""Tests for converting raw records into Player values."""

import unittest

from fantasy_football_ai_analyst.player import Player, player_from_fpl_record


class PlayerConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_record = {
            "first_name": "Alex",
            "second_name": "Example",
            "team": 1,
            "element_type": 3,
            "now_cost": 75,
            "total_points": 120,
        }

    def test_converts_raw_fields_and_price(self) -> None:
        player = player_from_fpl_record(self.raw_record)

        self.assertEqual(
            player,
            Player(
                name="Alex Example",
                team_id=1,
                position_id=3,
                price=7.5,
                total_points=120,
            ),
        )

    def test_reports_a_missing_field(self) -> None:
        del self.raw_record["team"]

        with self.assertRaisesRegex(ValueError, "missing required field 'team'"):
            player_from_fpl_record(self.raw_record)

    def test_rejects_boolean_for_integer_field(self) -> None:
        self.raw_record["team"] = True

        with self.assertRaisesRegex(ValueError, "'team' must be an integer"):
            player_from_fpl_record(self.raw_record)

    def test_rejects_invalid_values_at_the_data_boundary(self) -> None:
        invalid_fields = [
            ("first_name", "  "),
            ("second_name", None),
            ("team", 0),
            ("team", -1),
            ("element_type", 99),
            ("now_cost", -1),
            ("now_cost", "75"),
            ("total_points", 1.5),
            ("id", 0),
            ("id", True),
            ("minutes", -1),
            ("minutes", None),
            ("goals_scored", -1),
            ("assists", "3"),
        ]
        for field, value in invalid_fields:
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, field):
                    player_from_fpl_record({**self.raw_record, field: value})

    def test_normalizes_names_and_retains_optional_statistics(self) -> None:
        player = player_from_fpl_record({
            **self.raw_record,
            "first_name": "  Alex ",
            "id": 42,
            "minutes": 1800,
            "goals_scored": 8,
            "assists": 6,
        })
        self.assertEqual(player.name, "Alex Example")
        self.assertEqual(player.player_id, 42)
        self.assertEqual(player.position, "MID")
        self.assertEqual((player.minutes, player.goals, player.assists), (1800, 8, 6))
        self.assertAlmostEqual(player.points_per_million, 16)
        self.assertAlmostEqual(player.points_per_90, 6)

    def test_missing_statistics_remain_unknown(self) -> None:
        player = player_from_fpl_record(self.raw_record)
        self.assertIsNone(player.minutes)
        self.assertIsNone(player.goals)
        self.assertIsNone(player.assists)
        self.assertIsNone(player.points_per_90)

    def test_zero_denominators_produce_unavailable_metrics(self) -> None:
        player = player_from_fpl_record({**self.raw_record, "now_cost": 0, "minutes": 0})
        self.assertIsNone(player.points_per_million)
        self.assertIsNone(player.points_per_90)

    def test_negative_points_are_preserved(self) -> None:
        player = player_from_fpl_record({**self.raw_record, "total_points": -2})
        self.assertEqual(player.total_points, -2)


if __name__ == "__main__":
    unittest.main()
