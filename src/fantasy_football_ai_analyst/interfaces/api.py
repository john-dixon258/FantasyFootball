"""HTTP input and JSON output around the same analysis used by the CLI."""

import logging
from datetime import datetime, timezone
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


PLAYER_DATA_FILE = Path("data/local/fpl-bootstrap.json")
FIXTURE_DATA_FILE = Path("data/local/fpl-fixtures.json")
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
