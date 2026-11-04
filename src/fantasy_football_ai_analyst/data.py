"""Read normalized players from a local JSON file."""

import json
from collections.abc import Mapping
from json import JSONDecodeError
from pathlib import Path
from dataclasses import replace
from fantasy_football_ai_analyst.player import Player, player_from_fpl_record


def load_players(file_path: str | Path) -> list[Player]:
    """Load a player array or a saved FPL-shaped object containing ``elements``.

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
    
    team_names = {}

    if isinstance(payload, dict):
        for team in payload.get("teams", []):
            team_names[team["id"]] = team["name"]
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

    return players
