"""Tests for the command-line input/action/output flow."""

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from fantasy_football_ai_analyst.interfaces.cli import main


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_players = [
            {
                "first_name": "Alex",
                "second_name": "Example",
                "team": 1,
                "element_type": 3,
                "now_cost": 75,
                "total_points": 120,
                "id": 1,
                "minutes": 1800,
                "goals_scored": 8,
                "assists": 6,
            },
            {
                "first_name": "Jamie",
                "second_name": "Sample",
                "team": 2,
                "element_type": 2,
                "now_cost": 62,
                "total_points": 94,
                "id": 2,
            },
        ]
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.data_file = Path(self.temporary_directory.name) / "players.json"
        self.data_file.write_text(json.dumps(self.raw_players), encoding="utf-8")
        self.fixtures_file = Path(self.temporary_directory.name) / "fixtures.json"
        self.fixtures_file.write_text("[]", encoding="utf-8")
        # Use temporary local datasets so tests never depend on downloaded files.
        for target, value in (
            ("fantasy_football_ai_analyst.interfaces.cli.PLAYER_DATA_FILE", self.data_file),
            ("fantasy_football_ai_analyst.interfaces.cli.FIXTURE_DATA_FILE", self.fixtures_file),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_compare_command_routes_input_and_prints_results(self) -> None:
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(
                [
                    "compare",
                    "Alex Example",
                    "Jamie Sample",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Alex Example", output.getvalue())
        self.assertIn("Jamie Sample", output.getvalue())
        self.assertIn("120", output.getvalue())

    def test_compare_command_reports_unknown_names(self) -> None:
        errors = StringIO()

        with redirect_stderr(errors):
            exit_code = main(
                [
                    "compare",
                    "Unknown Player",
                    "Jamie Sample",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("No player found", errors.getvalue())

    def test_demo_works_without_a_user_data_file(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["demo"])
        self.assertEqual(exit_code, 0)
        self.assertIn("fictional", output.getvalue())
        self.assertIn("Casey Value", output.getvalue())
        self.assertIn("N/A", output.getvalue())

    def test_list_filters_players_and_prints_value_metrics(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main([
                "list", "--position", "mid",
                "--max-price", "7.5", "--min-minutes", "900", "--limit", "1",
                "--sort", "points-per-million",
            ])
        self.assertEqual(exit_code, 0)
        self.assertIn("Alex Example", output.getvalue())
        self.assertIn("16.00", output.getvalue())
        self.assertNotIn("Jamie Sample", output.getvalue())

    def test_compare_by_id_shows_missing_statistics_as_unavailable(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["compare", "1", "2"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Minutes", output.getvalue())
        self.assertIn("Goals", output.getvalue())
        self.assertIn("N/A", output.getvalue())
        self.assertIn("6.00", output.getvalue())
        self.assertIn("not predicted points", output.getvalue())

    def test_list_displays_opponent_from_a_team_outside_the_shortlist(self) -> None:
        self.data_file.write_text(json.dumps({
            "elements": self.raw_players,
            "teams": [{"id": 1, "name": "Arsenal"}, {"id": 2, "name": "Man City"}],
        }), encoding="utf-8")
        self.fixtures_file.write_text(json.dumps([
            {
                "id": 10, "team_h": 1, "team_a": 2,
                "kickoff_time": "2026-11-07T15:00:00Z", "started": False, "finished": False,
            },
        ]), encoding="utf-8")
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["list", "--team", "arsenal", "--limit", "1"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Alex Example", output.getvalue())
        self.assertNotIn("Jamie Sample", output.getvalue())
        player_row = next(line for line in output.getvalue().splitlines() if "Alex Example" in line)
        self.assertTrue(player_row.rstrip().endswith("Man City"))

    def test_compare_displays_home_and_away_opponents_from_the_earliest_unstarted_match(self) -> None:
        self.data_file.write_text(json.dumps({
            "elements": self.raw_players,
            "teams": [{"id": 1, "name": "Arsenal"}, {"id": 2, "name": "Man City"}],
        }), encoding="utf-8")
        self.fixtures_file.write_text(json.dumps([
            {
                "id": 11, "team_h": 1, "team_a": 99,
                "kickoff_time": "2026-11-14T15:00:00Z", "started": False, "finished": False,
            },
            {
                "id": 9, "team_h": 1, "team_a": 99,
                "kickoff_time": "2026-11-06T15:00:00Z", "started": True, "finished": False,
            },
            {
                "id": 10, "team_h": 1, "team_a": 2,
                "kickoff_time": "2026-11-07T15:00:00Z", "started": False, "finished": False,
            },
        ]), encoding="utf-8")
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["compare", "1", "2"])
        self.assertEqual(exit_code, 0)
        row = next(line for line in output.getvalue().splitlines() if line.startswith("Next Opponent"))
        self.assertLess(row.index("Man City"), row.index("Arsenal"))

    def test_no_upcoming_fixture_displays_unavailable_opponents(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["compare", "1", "2"])
        self.assertEqual(exit_code, 0)
        row = next(line for line in output.getvalue().splitlines() if line.startswith("Next Opponent"))
        self.assertEqual(row.count("N/A"), 2)

    def test_missing_data_file_is_a_clean_error(self) -> None:
        errors, output = StringIO(), StringIO()
        with patch(
            "fantasy_football_ai_analyst.interfaces.cli.PLAYER_DATA_FILE", self.data_file.with_name("missing.json")
        ), redirect_stderr(errors), redirect_stdout(output):
            exit_code = main(["list"])
        self.assertEqual(exit_code, 1)
        self.assertIn("Could not read", errors.getvalue())
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn("Traceback", errors.getvalue())

    def test_missing_fixture_file_is_a_clean_error(self) -> None:
        errors, output = StringIO(), StringIO()
        with patch(
            "fantasy_football_ai_analyst.interfaces.cli.FIXTURE_DATA_FILE",
            self.fixtures_file.with_name("missing-fixtures.json"),
        ), redirect_stderr(errors), redirect_stdout(output):
            exit_code = main(["list"])
        self.assertEqual(exit_code, 1)
        self.assertIn("Could not read fixture data file", errors.getvalue())
        self.assertEqual(output.getvalue(), "")

    def test_empty_shortlist_is_explained(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["list", "--position", "GK"])
        self.assertEqual(exit_code, 0)
        self.assertIn("No players found", output.getvalue())

    def test_unrecognized_team_warns_and_preserves_other_filters(self) -> None:
        self.data_file.write_text(json.dumps({
            "elements": self.raw_players,
            "teams": [{"id": 1, "name": "Arsenal"}, {"id": 2, "name": "Man City"}],
        }), encoding="utf-8")
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            exit_code = main([
                "list", "--team", "Arsnal",
                "--position", "MID", "--max-price", "7.5", "--min-minutes", "900",
                "--limit", "1",
            ])
        self.assertEqual(exit_code, 0)
        self.assertIn("Alex Example", output.getvalue())
        self.assertNotIn("Jamie Sample", output.getvalue())
        self.assertIn("Arsnal", errors.getvalue())
        self.assertIn("team filter skipped", errors.getvalue())

    def test_recognized_team_with_no_matching_players_is_not_skipped(self) -> None:
        self.data_file.write_text(json.dumps({
            "elements": self.raw_players,
            "teams": [{"id": 1, "name": "Arsenal"}, {"id": 2, "name": "Man City"}],
        }), encoding="utf-8")
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            exit_code = main([
                "list", "--team", "ARSENAL",
                "--position", "DEF",
            ])
        self.assertEqual(exit_code, 0)
        self.assertIn("No players found", output.getvalue())
        self.assertEqual(errors.getvalue(), "")

    def test_invalid_filter_returns_failure(self) -> None:
        errors = StringIO()
        with redirect_stderr(errors):
            exit_code = main(["list", "--max-price", "nan"])
        self.assertEqual(exit_code, 1)
        self.assertIn("finite", errors.getvalue())

    def test_incomplete_compare_arguments_return_usage_error(self) -> None:
        errors = StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            main(["compare", "Alex Example"])
        self.assertEqual(raised.exception.code, 2)

    def test_demo_can_be_filtered_or_compared(self) -> None:
        for arguments in [
            ["list", "--demo", "--position", "MID", "--limit", "2"],
            ["compare", "--demo", "1", "5"],
        ]:
            with self.subTest(arguments=arguments):
                output = StringIO()
                with redirect_stdout(output):
                    exit_code = main(arguments)
                self.assertEqual(exit_code, 0)
                self.assertIn("fictional", output.getvalue())
                self.assertIn("Casey Value", output.getvalue())

    def test_removed_file_arguments_are_rejected(self) -> None:
        for arguments in [
            ["list", "--data-file", str(self.data_file)],
            ["list", "--fixtures-file", str(self.fixtures_file)],
        ]:
            with self.subTest(arguments=arguments):
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
                    main(arguments)
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
