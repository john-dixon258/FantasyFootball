"""Tests for loading player data from JSON files."""

import json
import tempfile
import unittest
from pathlib import Path

from fantasy_football_ai_analyst.data import load_players


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

            players = load_players(data_file)

        self.assertEqual(len(players), 1)
        self.assertEqual(players[0].name, "Alex Example")

    def test_rejects_a_non_array_json_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_file = Path(temporary_directory) / "players.json"
            data_file.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must contain a JSON array"):
                load_players(data_file)

    def test_loads_saved_elements_object_and_ignores_unrelated_fields(self) -> None:
        self.data_file.write_text(
            json.dumps({"elements": [self.record], "events": []}), encoding="utf-8"
        )
        self.assertEqual(load_players(self.data_file)[0].player_id, 1)

    def test_reads_utf8_with_byte_order_mark(self) -> None:
        self.data_file.write_text(json.dumps([self.record]), encoding="utf-8-sig")
        self.assertEqual(load_players(self.data_file)[0].name, "Alex Example")

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
        self.assertEqual(load_players(self.data_file), [])

    def test_reports_the_record_number_when_a_record_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_file = Path(temporary_directory) / "players.json"
            data_file.write_text(json.dumps([{}]), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "record 1"):
                load_players(data_file)


if __name__ == "__main__":
    unittest.main()
