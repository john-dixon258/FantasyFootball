"""Read normalized players from a local JSON file."""

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path

from fantasy_football_ai_analyst.player import Player, player_from_fpl_record


def load_players(file_path: str | Path) -> tuple[list[Player], dict[int, str]]:
    """Return normalized players and the team-name lookup from saved JSON.

    Keeping file access here means the CLI and player-selection logic do not
    need to know how the data was stored.
    """
    path = Path(file_path)

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise ValueError(f"Could not read player data file '{path}': {error}") from error
    except JSONDecodeError as error:
        raise ValueError(
            f"Player data file '{path}' contains invalid JSON at line {error.lineno}."
        ) from error
    except UnicodeDecodeError as error:
        raise ValueError(f"Player data file '{path}' must use UTF-8 encoding.") from error

    team_names: dict[int, str] = {}

    if isinstance(payload, dict):
        teams = payload.get("teams", [])
        if not isinstance(teams, list):
            raise ValueError(f"Player data file '{path}' must contain a 'teams' array.")
        for record_number, team in enumerate(teams, start=1):
            if (
                not isinstance(team, Mapping)
                or type(team.get("id")) is not int
                or team["id"] <= 0
                or not isinstance(team.get("name"), str)
                or not team["name"].strip()
            ):
                raise ValueError(
                    f"Invalid team record {record_number} in '{path}': "
                    "positive ID and non-empty name required."
                )
            if team["id"] in team_names:
                raise ValueError(f"Duplicate team ID {team['id']} in '{path}'.")
            team_names[team["id"]] = team["name"].strip()
        payload = payload.get("elements")

    if not isinstance(payload, list):
        raise ValueError(
            f"Player data file '{path}' must contain a JSON array "
            "or an object with an 'elements' array."
        )

    players: list[Player] = []
    seen_ids: set[int] = set()
    for record_number, record in enumerate(payload, start=1):
        if not isinstance(record, Mapping):
            raise ValueError(
                f"Player record {record_number} in '{path}' must be a JSON object."
            )

        try:
            player = player_from_fpl_record(record)
            player = replace(
                player,
                team_name=team_names.get(player.team_id),
            )
            if player.player_id is not None:
                if player.player_id in seen_ids:
                    raise ValueError(f"Duplicate player ID {player.player_id}.")
                seen_ids.add(player.player_id)
            players.append(player)
        except ValueError as error:
            raise ValueError(
                f"Invalid player record {record_number} in '{path}': {error}"
            ) from error

    return players, team_names


def load_fixtures(file_path: str | Path) -> list[dict]:
    """Load fixtures and validate the fields consumed by opponent analysis.

    Keeping file access here means the CLI and fixture logic do not
    need to know how the data was stored.
    """
    path = Path(file_path)

    try:
        fixtures = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise ValueError(f"Could not read fixture data file '{path}': {error}") from error
    except JSONDecodeError as error:
        raise ValueError(
            f"Fixture data file '{path}' contains invalid JSON at line {error.lineno}."
        ) from error
    except UnicodeDecodeError as error:
        raise ValueError(f"Fixture data file '{path}' must use UTF-8 encoding.") from error

    if not isinstance(fixtures, list):
        raise ValueError(f"Fixture data file '{path}' must contain a JSON array.")

    for record_number, fixture in enumerate(fixtures, start=1):
        if not isinstance(fixture, Mapping):
            raise ValueError(
                f"Fixture record {record_number} in '{path}' must be a JSON object."
            )
        for field in ("team_h", "team_a"):
            if type(fixture.get(field)) is not int or fixture[field] <= 0:
                raise ValueError(
                    f"Fixture record {record_number} in '{path}': "
                    f"'{field}' must be a positive integer."
                )
        for field in ("started", "finished"):
            if field not in fixture or (
                fixture[field] is not None and type(fixture[field]) is not bool
            ):
                raise ValueError(
                    f"Fixture record {record_number} in '{path}': "
                    f"'{field}' must be a boolean or null."
                )
        kickoff = fixture.get("kickoff_time")
        if kickoff is not None:
            try:
                if not isinstance(kickoff, str):
                    raise ValueError("Expected an ISO timestamp.")
                parsed = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
                if parsed.utcoffset() is None:
                    raise ValueError("Timezone is required.")
            except ValueError as error:
                raise ValueError(
                    f"Fixture record {record_number} in '{path}': "
                    "'kickoff_time' must be an ISO timestamp with a timezone or null."
                ) from error

    return fixtures
