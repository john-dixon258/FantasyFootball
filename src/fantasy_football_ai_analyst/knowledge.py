"""Turn saved sources into documents and retrieve inspectable text evidence.

Documents stay plain dictionaries. This module performs lexical retrieval, not
LLM generation or live availability checks. No network requests happen here.
"""

import json
import re
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, ValidationError


BUNDLED_NOTES_FILE = Path(__file__).with_name("knowledge_notes.json")
FPL_SOURCE_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"


class CuratedNote(BaseModel):
    """Validate manually imported JSON notes before they become documents."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_url: HttpUrl | None = None
    source_file: str | None = None
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime | None = None
    player_names: list[str] = Field(default_factory=list)


def _read_json(path: str | Path):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load knowledge source '{path}': {error}") from error


def _nltk_words() -> list[str]:
    from nltk.corpus import stopwords

    return stopwords.words("english")


@lru_cache(maxsize=1)
def get_stop_words() -> frozenset[str]:
    """Load once, when search is used; never download during app startup."""
    try:
        words = set(_nltk_words())
    except LookupError as error:
        raise ValueError(
            "NLTK stopwords are missing. Run your virtual environment's Python with "
            "'-m nltk.downloader -d .venv/nltk_data stopwords' from the project root."
        ) from error
    words.update({"update", "updates", "news", "please", "tell", "know"})
    words.difference_update({"no", "nor", "not"})
    return frozenset(words)


def _tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text.casefold().replace("ø", "o"))
    text = "".join(character for character in text if not unicodedata.combining(character))
    words = set(re.findall(r"\w+", text))
    # A small explicit vocabulary, not a claim of semantic understanding.
    synonyms = {"injuries": "injury", "injured": "injury", "suspensions": "suspension"}
    return {synonyms.get(word, word) for word in words}


def news_documents_from_bootstrap(
    payload: dict, *, source_file: str = "data/local/fpl-bootstrap.json"
) -> list[dict]:
    """Preserve non-blank FPL notes and their original news-added timestamps."""
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError("Knowledge bootstrap must contain an 'elements' array.")
    documents = []
    seen_ids = set()
    for index, entry in enumerate(payload["elements"], start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Knowledge player record {index} must be an object.")
        player_id = entry.get("id")
        if type(player_id) is not int or player_id <= 0:
            raise ValueError(f"Knowledge player record {index} needs a positive integer ID.")
        if player_id in seen_ids:
            raise ValueError(f"Duplicate knowledge player ID {player_id}.")
        seen_ids.add(player_id)
        for field in ("first_name", "second_name"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"Knowledge player {player_id} needs a non-empty '{field}'.")
        news = entry.get("news")
        if news is None:
            continue
        if not isinstance(news, str):
            raise ValueError(f"Knowledge player {player_id}: 'news' must be text or null.")
        news = news.strip()
        if not news:
            continue
        news_added = entry.get("news_added")
        if news_added is not None:
            try:
                parsed = datetime.fromisoformat(news_added.replace("Z", "+00:00"))
                if parsed.utcoffset() is None:
                    raise ValueError("Timezone required.")
            except (AttributeError, ValueError) as error:
                raise ValueError(f"Knowledge player {player_id}: invalid 'news_added' timestamp.") from error
        name = f"{entry['first_name'].strip()} {entry['second_name'].strip()}"
        documents.append({
            "document_id": f"fpl-news-{player_id}",
            "player_id": player_id,
            "player_name": name,
            "player_names": [name],
            "title": f"{name}: saved FPL news",
            "text": news,
            "source_type": "fpl_news",
            "source_name": "Saved FPL snapshot",
            "source_file": source_file,
            "source_url": FPL_SOURCE_URL,
            "news_added": news_added,
            "published_at": None,
            "retrieved_at": None,
        })
    return documents


def load_curated_documents(path: str | Path) -> list[dict]:
    """Read original notes/summaries with attribution, dates, and optional players."""
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"Curated knowledge file '{path}' must contain an array.")
    documents = []
    for index, record in enumerate(payload, start=1):
        try:
            note = CuratedNote.model_validate(record)
        except ValidationError as error:
            raise ValueError(f"Invalid curated note {index} in '{path}': {error}") from error
        if not note.source_url and not note.source_file:
            raise ValueError(f"Curated note {index} needs a source URL or source file.")
        if any(not name.strip() for name in note.player_names):
            raise ValueError(f"Curated note {index} contains a blank player name.")
        documents.append({
            **note.model_dump(mode="json"),
            "player_id": None,
            "player_name": None,
            "source_type": "curated_note",
            "news_added": None,
        })
    return documents


def chunk_documents(
    documents: list[dict], *, max_words: int = 160, overlap_words: int = 30
) -> list[dict]:
    """Split long documents at word boundaries, retaining context and attribution."""
    if max_words <= 0 or not 0 <= overlap_words < max_words:
        raise ValueError("Chunk size must be positive and overlap smaller than chunk size.")
    chunks = []
    seen_ids = set()
    for document in documents:
        source_id = document["document_id"]
        if source_id in seen_ids:
            raise ValueError(f"Duplicate knowledge document ID '{source_id}'.")
        seen_ids.add(source_id)
        words = list(re.finditer(r"\S+", document["text"]))
        if not words:
            raise ValueError(f"Knowledge document '{source_id}' has no text.")
        for index, start in enumerate(range(0, len(words), max_words - overlap_words)):
            end = min(start + max_words, len(words))
            chunks.append({
                **document,
                "document_id": source_id if len(words) <= max_words else f"{source_id}:chunk-{index + 1}",
                "source_document_id": source_id,
                "chunk_index": index,
                "text": document["text"][words[start].start():words[end - 1].end()],
            })
            if end == len(words):
                break
    return chunks


def load_knowledge(
    bootstrap_file: str | Path, *, notes_file: str | Path | None = None
) -> tuple[list[dict], list[dict]]:
    """Load saved news, bundled methodology, and an optional local notes file."""
    payload = _read_json(bootstrap_file)
    documents = news_documents_from_bootstrap(payload, source_file=str(bootstrap_file))
    players = [{
        "player_id": player["id"],
        "player_name": f"{player['first_name'].strip()} {player['second_name'].strip()}",
        "alias": player.get("web_name") if isinstance(player.get("web_name"), str) else "",
    } for player in payload["elements"]]
    documents.extend(load_curated_documents(BUNDLED_NOTES_FILE))
    if notes_file is not None:
        documents.extend(load_curated_documents(notes_file))
    return chunk_documents(documents), players


def mentioned_players(query: str, players: list[dict]) -> list[dict]:
    """Prefer full names, otherwise expose all players sharing a matched name token."""
    raw_words = _tokens(query)
    full_matches = [player for player in players if _tokens(player["player_name"]) <= raw_words]
    if full_matches:
        return full_matches
    meaningful_words = raw_words - get_stop_words()
    return [player for player in players if meaningful_words & {
        word for word in _tokens(f"{player['player_name']} {player.get('alias', '')}")
        if len(word) >= 3
    }]


def search_documents(
    documents: list[dict], query: str, *, limit: int = 5, players: list[dict] | None = None
) -> list[dict]:
    """Rank name matches and keyword overlap; scores are not confidence values."""
    if not isinstance(query, str):
        raise ValueError("Search query must be text.")
    if type(limit) is not int or limit <= 0:
        raise ValueError("Search limit must be a positive integer.")
    if not query.strip():
        return []
    query_words = _tokens(query) - get_stop_words()
    if not query_words:
        return []
    if players is None:
        players = [{"player_id": entry.get("player_id"), "player_name": entry["player_name"]}
                   for entry in documents if entry.get("player_name")]
    named_players = mentioned_players(query, players)
    named_ids = {player["player_id"] for player in named_players if player.get("player_id") is not None}
    named_names = {frozenset(_tokens(player["player_name"])) for player in named_players}
    matches = []
    seen_ids = set()
    for entry in documents:
        document_id = entry["document_id"]
        if document_id in seen_ids:
            continue
        seen_ids.add(document_id)
        names = entry.get("player_names") or ([entry["player_name"]] if entry.get("player_name") else [])
        if named_players and not (
            entry.get("player_id") in named_ids
            or named_names & {frozenset(_tokens(name)) for name in names}
        ):
            continue
        name_words = _tokens(" ".join(names))
        document_words = _tokens(f"{entry.get('title', '')} {entry['text']}") | name_words
        shared_words = query_words & document_words
        if shared_words:
            name_matches = len(query_words & name_words)
            matches.append({
                **entry,
                "matched_words": sorted(shared_words),
                "match_count": len(shared_words),
                "name_match_count": name_matches,
                "score": 5 * len(shared_words) + 3 * name_matches
                + 2 * len(query_words & _tokens(entry.get("title", ""))),
            })
    return sorted(matches, key=lambda result: (
        -result["score"], -result["name_match_count"], result["document_id"]
    ))[:limit]
