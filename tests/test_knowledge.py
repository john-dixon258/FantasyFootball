"""Offline retrieval checks using fictional player notes, independent of live data."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fantasy_football_ai_analyst import knowledge


STOP_WORDS = frozenset({"any", "updates", "update", "on", "the", "a", "an", "is", "what", "how", "does", "please", "news"})


class KnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stop_words = patch.object(knowledge, "get_stop_words", return_value=STOP_WORDS)
        self.stop_words.start()
        self.addCleanup(self.stop_words.stop)
        self.payload = {"elements": [
            {"id": 1, "first_name": "Alex", "second_name": "Example", "news": "Thigh injury. Return date unknown.", "news_added": "2020-01-01T12:00:00Z"},
            {"id": 2, "first_name": "Jamie", "second_name": "Sample", "news": "Ankle injury, returned to training."},
            {"id": 3, "first_name": "Casey", "second_name": "Value", "news": "   "},
            {"id": 4, "first_name": "Martin", "second_name": "Ødegaard", "news": "Returned to training."},
            {"id": 5, "first_name": "Taylor", "second_name": "Example", "news": "Suspension."},
        ]}
        self.documents = knowledge.news_documents_from_bootstrap(self.payload)
        self.players = [{"player_id": player["id"], "player_name": f"{player['first_name']} {player['second_name']}"} for player in self.payload["elements"]]

    def test_conversion_preserves_attribution_and_optional_dates(self) -> None:
        self.assertEqual(len(self.documents), 4)
        document = self.documents[0]
        self.assertEqual(document["document_id"], "fpl-news-1")
        self.assertEqual(document["player_name"], "Alex Example")
        self.assertEqual(document["news_added"], "2020-01-01T12:00:00Z")
        self.assertIsNone(document["published_at"])
        self.assertEqual(document["source_file"], "data/local/fpl-bootstrap.json")
        self.assertTrue(document["source_url"].startswith("https://"))
        self.assertIsNone(self.documents[1]["news_added"])

    def test_missing_null_and_blank_news_are_excluded(self) -> None:
        for news in (None, "", "   "):
            with self.subTest(news=news):
                record = {**self.payload["elements"][0], "news": news}
                self.assertEqual(knowledge.news_documents_from_bootstrap({"elements": [record]}), [])
        record.pop("news")
        self.assertEqual(knowledge.news_documents_from_bootstrap({"elements": [record]}), [])

    def test_invalid_bootstrap_records_report_errors(self) -> None:
        cases = [{}, {"elements": None}, {"elements": [None]}]
        for field, value in (("id", True), ("id", 0), ("first_name", ""), ("news", 12),
                             ("news_added", "yesterday"), ("news_added", "2020-01-01T12:00:00")):
            cases.append({"elements": [{**self.payload["elements"][0], field: value}]})
        cases.append({"elements": [self.payload["elements"][0]] * 2})
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                knowledge.news_documents_from_bootstrap(payload)

    def test_retrieval_evaluation_cases(self) -> None:
        cases = [
            ("Any updates on Jamie Sample?", [2]),
            ("JAMIE injury?", [2]),
            ("Alex Example thigh injury", [1]),
            ("any updates on Casey Value?", []),
            ("Odegaard", [4]),
            ("ØDEGAARD training", [4]),
            ("who won Wimbledon?", []),
            ("updates on the", []),
            ("", []),
            ("   ", []),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                results = knowledge.search_documents(self.documents, query, players=self.players)
                self.assertEqual([result["player_id"] for result in results], expected)

    def test_player_without_news_does_not_receive_someone_elses_injury(self) -> None:
        results = knowledge.search_documents(self.documents, "Is Casey Value injured?", players=self.players)
        self.assertEqual(results, [])

    def test_curated_player_attribution_uses_the_same_accent_normalization(self) -> None:
        document = {
            "document_id": "curated-martin", "title": "Training note", "text": "Muscle injury.",
            "player_id": None, "player_name": None, "player_names": ["Martin Odegaard"],
        }
        result = knowledge.search_documents([document], "Odegaard injury", players=self.players)
        self.assertEqual(result[0]["document_id"], "curated-martin")

    def test_more_question_terms_beat_a_name_only_match_in_a_title(self) -> None:
        generic = {**self.documents[0], "text": "Training update."}
        specific = {
            **self.documents[0], "document_id": "specific-article", "title": "Training note",
            "text": "Thigh injury update.",
        }
        results = knowledge.search_documents([generic, specific], "Alex injury", players=self.players)
        self.assertEqual(results[0]["document_id"], "specific-article")

    def test_full_name_takes_priority_over_shared_surname(self) -> None:
        results = knowledge.search_documents(self.documents, "Alex Example injury", players=self.players)
        self.assertEqual([result["player_id"] for result in results], [1])
        shared = knowledge.search_documents(self.documents, "Example", players=self.players)
        self.assertEqual({result["player_id"] for result in shared}, {1, 5})

    def test_shared_words_and_ranking_do_not_modify_source_documents(self) -> None:
        original = copy.deepcopy(self.documents)
        result = knowledge.search_documents(self.documents, "Jamie injury", players=self.players)[0]
        self.assertEqual(result["matched_words"], ["injury", "jamie"])
        self.assertEqual(result["match_count"], 2)
        self.assertGreater(result["score"], result["match_count"])
        self.assertEqual(self.documents, original)

    def test_generic_query_ranks_overlap_and_uses_deterministic_ties(self) -> None:
        results = knowledge.search_documents(self.documents, "injury training", players=[])
        self.assertEqual(results[0]["player_id"], 2)
        reverse = knowledge.search_documents(list(reversed(self.documents)), "injury training", players=[])
        self.assertEqual([r["document_id"] for r in results], [r["document_id"] for r in reverse])

    def test_limits_duplicates_and_whole_word_matching(self) -> None:
        results = knowledge.search_documents(self.documents * 2, "injury", limit=1, players=[])
        self.assertEqual(len(results), 1)
        self.assertEqual(knowledge.search_documents(self.documents, "exam", players=[]), [])
        for limit in (0, -1, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                knowledge.search_documents(self.documents, "injury", limit=limit)

    def test_chunking_preserves_text_overlap_and_source(self) -> None:
        document = {**self.documents[0], "text": "one two three four five six seven eight nine"}
        chunks = knowledge.chunk_documents([document], max_words=5, overlap_words=2)
        self.assertEqual([chunk["text"] for chunk in chunks], [
            "one two three four five", "four five six seven eight", "seven eight nine",
        ])
        self.assertEqual(len({chunk["document_id"] for chunk in chunks}), 3)
        self.assertTrue(all(chunk["source_document_id"] == document["document_id"] for chunk in chunks))
        self.assertTrue(all(chunk["news_added"] == document["news_added"] for chunk in chunks))
        with self.assertRaises(ValueError):
            knowledge.chunk_documents([document], max_words=5, overlap_words=5)
        with self.assertRaises(ValueError):
            knowledge.chunk_documents([document, document])

    def test_bundled_notes_are_real_methodology_not_fictional_football_updates(self) -> None:
        documents = knowledge.load_curated_documents(knowledge.BUNDLED_NOTES_FILE)
        self.assertEqual(len(documents), 6)
        self.assertTrue(all(document["source_name"] == "Touchline methodology" for document in documents))
        self.assertTrue(all(document["player_id"] is None for document in documents))
        self.assertIsNone(documents[0]["published_at"])
        result = knowledge.search_documents(documents, "points per million", players=[])[0]
        self.assertEqual(result["document_id"], "guide-value")

    def test_optional_curated_import_validates_dates_sources_and_schema(self) -> None:
        note = {"document_id": "article-1", "title": "Example source", "text": "Training news.",
                "source_name": "Example publisher", "source_url": "https://example.org/news",
                "published_at": "2020-01-01T12:00:00Z", "player_names": ["Jamie Sample"]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            path.write_text(json.dumps([note]), encoding="utf-8")
            documents = knowledge.load_curated_documents(path)
            self.assertEqual(documents[0]["player_names"], ["Jamie Sample"])
            for changes in ({"source_url": "javascript:alert(1)"}, {"published_at": "yesterday"},
                            {"text": " "}, {"player_names": [""]}, {"soruce": "typo"}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    path.write_text(json.dumps([{**note, **changes}]), encoding="utf-8")
                    knowledge.load_curated_documents(path)

    def test_load_reports_file_failures_and_does_not_require_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bootstrap.json"
            with self.assertRaisesRegex(ValueError, "Could not load knowledge"):
                knowledge.load_knowledge(path)
            path.write_text(json.dumps(self.payload), encoding="utf-8")
            documents, players = knowledge.load_knowledge(path)
            self.assertEqual(len(documents), 10)
            self.assertEqual(len(players), 5)


class StopWordSetupTests(unittest.TestCase):
    def tearDown(self) -> None:
        knowledge.get_stop_words.cache_clear()

    def test_stop_words_are_loaded_once_and_preserve_negation(self) -> None:
        knowledge.get_stop_words.cache_clear()
        with patch.object(knowledge, "_nltk_words", return_value=["the", "no", "nor", "not"]) as loader:
            words = knowledge.get_stop_words()
            knowledge.get_stop_words()
        self.assertEqual(loader.call_count, 1)
        self.assertIn("updates", words)
        self.assertNotIn("not", words)

    def test_missing_corpus_has_actionable_error_instead_of_downloading(self) -> None:
        knowledge.get_stop_words.cache_clear()
        with patch.object(knowledge, "_nltk_words", side_effect=LookupError("not installed")):
            with self.assertRaisesRegex(ValueError, "nltk.downloader"):
                knowledge.get_stop_words()


if __name__ == "__main__":
    unittest.main()
