"""HTTP input and JSON output around the same analysis used by the CLI."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from fantasy_football_ai_analyst.analysis import (
    add_next_opponent,
    find_players,
    resolve_team_filter,
    shortlist_players,
)
from fantasy_football_ai_analyst.data import load_fixtures, load_players
from fantasy_football_ai_analyst.player import Player
from fantasy_football_ai_analyst.knowledge import load_knowledge, mentioned_players, search_documents


PLAYER_DATA_FILE = Path("data/local/fpl-bootstrap.json")
FIXTURE_DATA_FILE = Path("data/local/fpl-fixtures.json")
KNOWLEDGE_NOTES_FILE = Path("data/local/football-notes.json")
WEB_DIRECTORY = Path(__file__).resolve().parents[1] / "web"
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fantasy Football Analyst",
    description="Explore saved FPL statistics and fixtures. These are not predictions.",
    version="0.1.0",
)
app.mount("/assets", StaticFiles(directory=WEB_DIRECTORY), name="assets")


class PlayerResponse(BaseModel):
    """The JSON contract, including calculated properties on our Player record."""

    model_config = ConfigDict(from_attributes=True)

    player_id: int | None
    name: str
    team_id: int
    team_name: str | None
    position: str
    price: float
    total_points: int
    minutes: int | None
    goals: int | None
    assists: int | None
    next_opponent: str | None
    points_per_million: float | None
    points_per_90: float | None


class PlayerResults(BaseModel):
    players: list[PlayerResponse]
    count: int = Field(description="Number of players returned, after any limit.")
    warnings: list[str] = Field(default_factory=list)


class TeamResponse(BaseModel):
    team_id: int
    name: str


class DatasetResponse(BaseModel):
    player_count: int
    team_count: int
    players_file_saved_at: datetime
    fixtures_file_saved_at: datetime


class EvidenceResponse(BaseModel):
    document_id: str
    source_document_id: str
    chunk_index: int
    title: str
    text: str
    player_id: int | None
    player_name: str | None
    player_names: list[str]
    source_type: Literal["fpl_news", "curated_note"]
    source_name: str
    source_file: str | None
    source_url: str | None
    news_added: datetime | None
    published_at: datetime | None
    retrieved_at: datetime | None
    matched_words: list[str]
    match_count: int
    score: int = Field(description="Keyword ranking score, not a confidence or probability.")


class KnowledgeResults(BaseModel):
    query: str
    results: list[EvidenceResponse]
    count: int
    document_count: int
    matched_players: list[str]
    status: Literal["evidence_found", "insufficient_evidence"]
    retrieval_method: str = "player-aware keyword retrieval"
    warnings: list[str]


def get_data() -> tuple[list[Player], list[dict], dict[int, str]]:
    """Read once per request so replacing a snapshot needs no server restart."""
    try:
        players, team_names = load_players(PLAYER_DATA_FILE)
        fixtures = load_fixtures(FIXTURE_DATA_FILE)
    except ValueError as error:
        logger.error("Cannot load local FPL data: %s", error)
        raise HTTPException(
            status_code=503,
            detail="Local FPL data is unavailable or invalid. Check the saved JSON files and server log.",
        ) from error
    return players, fixtures, team_names


def get_knowledge() -> tuple[list[dict], list[dict]]:
    """Search reads player news independently of fixture-file availability."""
    try:
        return load_knowledge(
            PLAYER_DATA_FILE,
            notes_file=KNOWLEDGE_NOTES_FILE if KNOWLEDGE_NOTES_FILE.exists() else None,
        )
    except ValueError as error:
        logger.error("Cannot load local knowledge: %s", error)
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get(
    "/knowledge/search", response_model=KnowledgeResults,
    responses={503: {"description": "Knowledge source or NLTK corpus unavailable"}},
)
def search_knowledge(
    data: Annotated[tuple[list[dict], list[dict]], Depends(get_knowledge)],
    query: Annotated[str, Query(min_length=1, max_length=400, pattern=r"\S")],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> KnowledgeResults:
    """Retrieve sourced evidence. This endpoint does not generate an LLM answer."""
    documents, players = data
    try:
        results = search_documents(documents, query, limit=limit, players=players)
        names = [player["player_name"] for player in mentioned_players(query, players)]
    except ValueError as error:
        logger.error("Knowledge search unavailable: %s", error)
        raise HTTPException(status_code=503, detail=str(error)) from error
    warnings = [
        "Saved evidence is not a live availability check. Verify the dates and original source.",
        "Keyword scores measure overlap, not factual accuracy or confidence. No LLM answer is generated.",
    ]
    if not results:
        warnings.append("No supporting evidence was found. A missing news note does not confirm fitness.")
    now = datetime.now(timezone.utc)
    dated_news = [result for result in results if result["source_type"] == "fpl_news"]
    if any(not result["news_added"] for result in dated_news):
        warnings.append("At least one FPL note has no news-added timestamp; its age is unknown.")
    if any(result["news_added"] and (
        now - datetime.fromisoformat(result["news_added"].replace("Z", "+00:00"))
    ) > timedelta(days=14) for result in dated_news):
        warnings.append("At least one FPL note was added more than 14 days ago. This is an age flag, not a fitness assessment.")
    return KnowledgeResults(
        query=query.strip(), results=[EvidenceResponse.model_validate(result) for result in results],
        count=len(results), document_count=len(documents), matched_players=names,
        status="evidence_found" if results else "insufficient_evidence", warnings=warnings,
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Check that the server responds; this does not check data availability."""
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """Serve the browser interface alongside the JSON endpoints."""
    return FileResponse(WEB_DIRECTORY / "index.html", media_type="text/html")


@app.get("/teams", response_model=list[TeamResponse])
def list_teams(
    data: Annotated[tuple[list[Player], list[dict], dict[int, str]], Depends(get_data)],
) -> list[TeamResponse]:
    """Return the complete bootstrap team lookup for the browser's dropdown."""
    _, _, team_names = data
    return [
        TeamResponse(team_id=team_id, name=name)
        for team_id, name in sorted(team_names.items(), key=lambda team: team[1].casefold())
    ]


@app.get("/dataset", response_model=DatasetResponse)
def dataset_info(
    data: Annotated[tuple[list[Player], list[dict], dict[int, str]], Depends(get_data)],
) -> DatasetResponse:
    """Describe the saved files; file modification time is not source freshness."""
    players, _, team_names = data
    try:
        players_saved = PLAYER_DATA_FILE.stat().st_mtime
        fixtures_saved = FIXTURE_DATA_FILE.stat().st_mtime
    except OSError as error:
        logger.error("Cannot inspect local FPL snapshots: %s", error)
        raise HTTPException(status_code=503, detail="Local snapshot information is unavailable.") from error
    return DatasetResponse(
        player_count=len(players),
        team_count=len(team_names),
        players_file_saved_at=datetime.fromtimestamp(players_saved, tz=timezone.utc),
        fixtures_file_saved_at=datetime.fromtimestamp(fixtures_saved, tz=timezone.utc),
    )


@app.get(
    "/players",
    response_model=PlayerResults,
    responses={503: {"description": "Local data unavailable"}},
)
def list_players(
    data: Annotated[tuple[list[Player], list[dict], dict[int, str]], Depends(get_data)],
    position: Annotated[
        str | None, Query(pattern="^([Gg][Kk]|[Dd][Ee][Ff]|[Mm][Ii][Dd]|[Ff][Ww][Dd])$")
    ] = None,
    team: str | None = None,
    max_price: Annotated[float | None, Query(ge=0, allow_inf_nan=False)] = None,
    min_minutes: Annotated[int, Query(ge=0)] = 0,
    sort_by: Literal["points", "price", "points-per-million", "points-per-90"] = "points",
    limit: Annotated[int, Query(gt=0, le=1000)] = 20,
) -> PlayerResults:
    """Shortlist players; an unknown team skips that filter and returns a warning."""
    players, fixtures, team_names = data
    warnings = []
    if team is not None and resolve_team_filter(players, team) is None:
        warnings.append(f"Team '{team}' was not recognized; the team filter was skipped.")
    selected = shortlist_players(
        players,
        position=position,
        team=team,
        max_price=max_price,
        min_minutes=min_minutes,
        sort_by=sort_by,
        limit=limit,
    )
    return PlayerResults(
        players=[
            PlayerResponse.model_validate(add_next_opponent(player, fixtures, team_names))
            for player in selected
        ],
        count=len(selected),
        warnings=warnings,
    )


@app.get(
    "/compare",
    response_model=PlayerResults,
    responses={
        404: {"description": "Player ID not found"},
        503: {"description": "Local data unavailable"},
    },
)
def compare_players(
    data: Annotated[tuple[list[Player], list[dict], dict[int, str]], Depends(get_data)],
    player_one: Annotated[int, Query(gt=0)],
    player_two: Annotated[int, Query(gt=0)],
) -> PlayerResults:
    """Return two players in the requested order, selected by their FPL IDs."""
    players, fixtures, team_names = data
    try:
        selected = find_players(players, [str(player_one), str(player_two)])
    except ValueError as error:
        raise HTTPException(
            status_code=404, detail="One or both player IDs were not found."
        ) from error
    return PlayerResults(
        players=[
            PlayerResponse.model_validate(add_next_opponent(player, fixtures, team_names))
            for player in selected
        ],
        count=len(selected),
    )
