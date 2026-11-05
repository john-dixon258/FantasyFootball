"""Tests for loading player data from JSON files."""

import json
import tempfile
import unittest
from pathlib import Path

from fantasy_football_ai_analyst.data import load_fixtures, load_players


class PlayerDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.data_file = Path(self.temporary_directory.name) / "players.json"
        self.record = {
            "first_name": "Alex", "second_name": "Example", "team": 1,
            "element_type": 3, "now_cost": 75, "total_points": 120, "id": 1,
        }

    def test_loads_and_normalizes_json_records(self) -> None:
        raw_record = {
            "first_name": "Alex",
            "second_name": "Example",
            "team": 1,
            "element_type": 3,
            "now_cost": 75,
            "total_points": 120,
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            data_file = Path(temporary_directory) / "players.json"
            data_file.write_text(json.dumps([raw_record]), encoding="utf-8")

            players, team_names = load_players(data_file)

        self.assertEqual(len(players), 1)
        self.assertEqual(players[0].name, "Alex Example")
        self.assertEqual(team_names, {})

    def test_rejects_a_non_array_json_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_file = Path(temporary_directory) / "players.json"
            data_file.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must contain a JSON array"):
                load_players(data_file)

    def test_loads_saved_elements_object_and_ignores_unrelated_fields(self) -> None:
        self.data_file.write_text(
            json.dumps({"elements": [self.record], "events": [],
                        "teams": [{"id": 1, "name": "Arsenal"}]}), encoding="utf-8"
        )
        players, team_names = load_players(self.data_file)
        self.assertEqual(players[0].player_id, 1)
        self.assertEqual(players[0].team_name, "Arsenal")
        self.assertEqual(team_names, {1: "Arsenal"})

    def test_reads_utf8_with_byte_order_mark(self) -> None:
        self.data_file.write_text(json.dumps([self.record]), encoding="utf-8-sig")
        players, _ = load_players(self.data_file)
        self.assertEqual(players[0].name, "Alex Example")

    def test_missing_file_reports_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "Could not read player data file"):
            load_players(self.data_file)

    def test_malformed_json_reports_line(self) -> None:
        self.data_file.write_text("[\ninvalid]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid JSON at line 2"):
            load_players(self.data_file)

    def test_non_utf8_file_reports_encoding_problem(self) -> None:
        self.data_file.write_bytes(b"\xff")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            load_players(self.data_file)

    def test_array_entries_must_be_objects(self) -> None:
        self.data_file.write_text('["not a record"]', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "record 1.*JSON object"):
            load_players(self.data_file)

    def test_duplicate_ids_are_rejected_with_record_number(self) -> None:
        self.data_file.write_text(json.dumps([self.record, self.record]), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "record 2.*Duplicate player ID 1"):
            load_players(self.data_file)

    def test_empty_dataset_is_supported(self) -> None:
        self.data_file.write_text("[]", encoding="utf-8")
        self.assertEqual(load_players(self.data_file), ([], {}))

    def test_duplicate_team_ids_are_rejected(self) -> None:
        self.data_file.write_text(json.dumps({
            "elements": [],
            "teams": [{"id": 1, "name": "Arsenal"}, {"id": 1, "name": "Other"}],
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate team ID"):
            load_players(self.data_file)

    def test_reports_the_record_number_when_a_record_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_file = Path(temporary_directory) / "players.json"
            data_file.write_text(json.dumps([{}]), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "record 1"):
                load_players(data_file)


class FixtureDataTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.data_file = Path(temporary_directory.name) / "fixtures.json"
        self.fixture = {
            "team_h": 1, "team_a": 2, "started": False, "finished": False,
            "kickoff_time": "2026-11-06T20:00:00Z",
        }

    def test_accepts_scheduled_and_undated_fixtures(self) -> None:
        for kickoff in ("2026-11-06T20:00:00Z", "2026-11-06T21:00:00+01:00", None):
            with self.subTest(kickoff=kickoff):
                fixture = {**self.fixture, "kickoff_time": kickoff}
                self.data_file.write_text(json.dumps([fixture]), encoding="utf-8")
                self.assertEqual(load_fixtures(self.data_file), [fixture])

    def test_rejects_invalid_consumed_fields_with_record_number(self) -> None:
        for field, value in (("team_h", True), ("team_a", 0), ("started", "false"),
                             ("finished", 1), ("kickoff_time", 123),
                             ("kickoff_time", "tomorrow"), ("kickoff_time", "2026-11-06T20:00:00")):
            with self.subTest(field=field, value=value):
                fixture = {**self.fixture, field: value}
                self.data_file.write_text(json.dumps([fixture]), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, f"record 1.*{field}"):
                    load_fixtures(self.data_file)


if __name__ == "__main__":
    unittest.main()
