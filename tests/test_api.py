"""Exercise HTTP behavior against temporary snapshots, without a live server."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from fantasy_football_ai_analyst.interfaces import api


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.players_file = Path(temporary_directory.name) / "players.json"
        self.fixtures_file = Path(temporary_directory.name) / "fixtures.json"
        self.payload = {
            "teams": [{"id": 1, "name": "Arsenal"}, {"id": 2, "name": "Man City"}],
            "elements": [
                {"id": 1, "first_name": "Alex", "second_name": "Example", "team": 1,
                 "element_type": 3, "now_cost": 75, "total_points": 120, "minutes": 1800},
                {"id": 2, "first_name": "Jamie", "second_name": "Sample", "team": 2,
                 "element_type": 4, "now_cost": 62, "total_points": 94},
                {"id": 3, "first_name": "Casey", "second_name": "Value", "team": 1,
                 "element_type": 3, "now_cost": 60, "total_points": 100, "minutes": 900},
            ],
        }
        self.players_file.write_text(json.dumps(self.payload), encoding="utf-8")
        self.fixtures_file.write_text(json.dumps([
            {"team_h": 1, "team_a": 2, "finished": False, "started": False,
             "kickoff_time": "2026-11-06T20:00:00Z"},
        ]), encoding="utf-8")
        for name, path in (("PLAYER_DATA_FILE", self.players_file),
                           ("FIXTURE_DATA_FILE", self.fixtures_file)):
            patcher = patch.object(api, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def test_health_does_not_require_data_files(self) -> None:
        self.players_file.unlink()
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_shortlist_filters_ranks_and_enriches_players(self) -> None:
        response = self.client.get("/players", params={
            "team": " ARSENAL ", "position": "mid", "max_price": 8,
            "min_minutes": 450, "sort_by": "points-per-million", "limit": 1,
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["warnings"], [])
        player = result["players"][0]
        self.assertEqual(player["player_id"], 3)
        self.assertEqual(player["team_name"], "Arsenal")
        self.assertEqual(player["next_opponent"], "Man City")
        self.assertEqual(player["points_per_90"], 10)
        self.assertAlmostEqual(player["points_per_million"], 100 / 6)

    def test_unknown_or_blank_team_warns_and_retains_other_filters(self) -> None:
        for team in ("Arsenl", " "):
            with self.subTest(team=team):
                response = self.client.get("/players", params={"team": team, "position": "FWD"})
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual([p["player_id"] for p in result["players"]], [2])
                self.assertIn("skipped", result["warnings"][0])

    def test_recognized_team_with_no_matching_players_stays_empty(self) -> None:
        result = self.client.get("/players", params={"team": "Arsenal", "position": "GK"}).json()
        self.assertEqual(result, {"players": [], "count": 0, "warnings": []})

    def test_comparison_preserves_requested_order_and_null_statistics(self) -> None:
        response = self.client.get("/compare", params={"player_one": 2, "player_two": 1})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["count"], 2)
        self.assertEqual([p["player_id"] for p in result["players"]], [2, 1])
        self.assertEqual(result["players"][0]["next_opponent"], "Arsenal")
        self.assertIsNone(result["players"][0]["points_per_90"])
        self.assertIsNone(result["players"][0]["goals"])

    def test_unknown_player_id_returns_404(self) -> None:
        response = self.client.get("/compare", params={"player_one": 999, "player_two": 1})
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"])

    def test_invalid_query_values_return_422(self) -> None:
        cases = [
            ("/players", {"position": "CB"}),
            ("/players", {"max_price": -1}),
            ("/players", {"max_price": "nan"}),
            ("/players", {"max_price": "inf"}),
            ("/players", {"min_minutes": -1}),
            ("/players", {"limit": 0}),
            ("/players", {"limit": 1001}),
            ("/players", {"sort_by": "predictions"}),
            ("/compare", {"player_one": 0, "player_two": 1}),
            ("/compare", {"player_one": "Alex", "player_two": 1}),
            ("/compare", {"player_one": 1}),
        ]
        for endpoint, params in cases:
            with self.subTest(endpoint=endpoint, params=params):
                response = self.client.get(endpoint, params=params)
                self.assertEqual(response.status_code, 422)

    def test_missing_or_invalid_snapshots_return_503_and_log_reason(self) -> None:
        for path in (self.players_file, self.fixtures_file):
            original = path.read_text(encoding="utf-8")
            for content in (None, "invalid json"):
                with self.subTest(path=path.name, content=content):
                    if content is None:
                        path.unlink()
                    else:
                        path.write_text(content, encoding="utf-8")
                    with self.assertLogs(api.logger, level="ERROR"):
                        response = self.client.get("/players")
                    self.assertEqual(response.status_code, 503)
                    self.assertIn("Local FPL data", response.json()["detail"])
                    path.write_text(original, encoding="utf-8")

    def test_empty_fixtures_leave_opponent_null(self) -> None:
        self.fixtures_file.write_text("[]", encoding="utf-8")
        response = self.client.get("/players", params={"limit": 1})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["players"][0]["next_opponent"])

    def test_invalid_team_and_fixture_fields_return_503(self) -> None:
        for teams in (None, [{"id": 1}], [{"id": True, "name": "Arsenal"}]):
            with self.subTest(teams=teams):
                self.players_file.write_text(json.dumps({"elements": [], "teams": teams}), encoding="utf-8")
                with self.assertLogs(api.logger, level="ERROR"):
                    response = self.client.get("/players")
                self.assertEqual(response.status_code, 503)
        self.players_file.write_text(json.dumps(self.payload), encoding="utf-8")
        self.fixtures_file.write_text('[{"team_h": 1}]', encoding="utf-8")
        with self.assertLogs(api.logger, level="ERROR"):
            response = self.client.get("/compare", params={"player_one": 1, "player_two": 2})
        self.assertEqual(response.status_code, 503)

    def test_replacing_snapshot_is_visible_on_next_request(self) -> None:
        self.assertEqual(self.client.get("/players").json()["count"], 3)
        self.payload["elements"] = []
        self.players_file.write_text(json.dumps(self.payload), encoding="utf-8")
        self.assertEqual(self.client.get("/players").json()["count"], 0)

    def test_docs_and_openapi_describe_the_endpoints(self) -> None:
        self.assertEqual(self.client.get("/docs").status_code, 200)
        schema = self.client.get("/openapi.json").json()
        self.assertEqual(set(schema["paths"]), {"/health", "/players", "/compare", "/teams", "/dataset"})
        self.assertIn("PlayerResponse", schema["components"]["schemas"])

    def test_dashboard_and_assets_work_without_snapshot_files(self) -> None:
        self.players_file.unlink()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Touchline", response.text)
        for asset in ("app.js", "styles.css", "favicon.svg"):
            with self.subTest(asset=asset):
                self.assertEqual(self.client.get(f"/assets/{asset}").status_code, 200)
        self.assertEqual(self.client.get("/assets/missing.js").status_code, 404)
        self.assertEqual(self.client.get("/assets/%2e%2e/player.py").status_code, 404)

    def test_teams_return_complete_lookup_sorted_by_name(self) -> None:
        self.payload["teams"].append({"id": 9, "name": "Aston Villa"})
        self.players_file.write_text(json.dumps(self.payload), encoding="utf-8")
        response = self.client.get("/teams")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [
            {"team_id": 1, "name": "Arsenal"},
            {"team_id": 9, "name": "Aston Villa"},
            {"team_id": 2, "name": "Man City"},
        ])

    def test_dataset_reports_counts_and_actual_file_save_times(self) -> None:
        response = self.client.get("/dataset")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["player_count"], 3)
        self.assertEqual(result["team_count"], 2)
        for field, path in (("players_file_saved_at", self.players_file),
                            ("fixtures_file_saved_at", self.fixtures_file)):
            reported = datetime.fromisoformat(result[field].replace("Z", "+00:00"))
            self.assertIsNotNone(reported.tzinfo)
            self.assertAlmostEqual(reported.timestamp(), path.stat().st_mtime, places=3)

    def test_new_data_endpoints_preserve_useful_unavailable_errors(self) -> None:
        self.players_file.unlink()
        for endpoint in ("/teams", "/dataset"):
            with self.subTest(endpoint=endpoint), self.assertLogs(api.logger, level="ERROR"):
                self.assertEqual(self.client.get(endpoint).status_code, 503)


if __name__ == "__main__":
    unittest.main()
