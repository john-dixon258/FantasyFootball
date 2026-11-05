"""Verify terminal retrieval uses the shared core and reports failures clearly."""

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from fantasy_football_ai_analyst.interfaces import cli


class KnowledgeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "bootstrap.json"
        self.path.write_text(json.dumps({"elements": [
            {"id": 1, "first_name": "Alex", "second_name": "Example", "news": None},
            {"id": 2, "first_name": "Jamie", "second_name": "Sample", "news": "Fictional ankle injury note."},
        ]}), encoding="utf-8")
        for name, value in (("PLAYER_DATA_FILE", self.path),
                            ("FIXTURE_DATA_FILE", self.path.with_name("absent-fixtures.json")),
                            ("KNOWLEDGE_NOTES_FILE", self.path.with_name("optional-notes.json"))):
            patcher = patch.object(cli, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        stop_patcher = patch("fantasy_football_ai_analyst.knowledge.get_stop_words",
                             return_value=frozenset({"any", "updates", "on", "is"}))
        stop_patcher.start()
        self.addCleanup(stop_patcher.stop)

    def test_search_displays_evidence_sources_and_unknown_date_without_fixtures(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            code = cli.main(["search", "Any updates on Jamie Sample?", "--limit", "1"])
        self.assertEqual(code, 0)
        self.assertIn("Jamie Sample", output.getvalue())
        self.assertIn("Date", output.getvalue().title())
        self.assertIn("unknown", output.getvalue())
        self.assertIn("https://fantasy.premierleague.com/", output.getvalue())
        self.assertIn("not an LLM answer", output.getvalue())

    def test_named_player_without_news_gets_insufficient_evidence(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            code = cli.main(["search", "Is Alex Example injured?"])
        self.assertEqual(code, 0)
        self.assertIn("Insufficient evidence", output.getvalue())
        self.assertNotIn("ankle", output.getvalue())

    def test_invalid_limit_returns_clean_error(self) -> None:
        errors, output = StringIO(), StringIO()
        with redirect_stderr(errors), redirect_stdout(output):
            code = cli.main(["search", "injury", "--limit", "0"])
        self.assertEqual(code, 1)
        self.assertIn("positive integer", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
