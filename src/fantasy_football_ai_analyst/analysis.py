"""Pure player selection and ranking, with no file access or terminal output."""

import math
from collections.abc import Sequence

from fantasy_football_ai_analyst.player import POSITIONS, Player


SORT_OPTIONS = ("points", "price", "points-per-million", "points-per-90")


def find_players(
    players: Sequence[Player], requested_names: Sequence[str]
) -> list[Player]:
    """Match full names case-insensitively, or select by a numeric player ID.

    Raises:
        ValueError: If a name is missing from the data or is ambiguous.
    """
    selected_players: list[Player] = []

    for requested_name in requested_names:
        normalized_name = requested_name.strip().casefold()
        if normalized_name.isdecimal():
            matches = [player for player in players if player.player_id == int(normalized_name)]
        else:
            matches = [
                player for player in players if player.name.casefold() == normalized_name
            ]

        if not matches:
            raise ValueError(f"No player found matching '{requested_name}'. Use 'list' to see players.")
        if len(matches) > 1:
            ids = [str(player.player_id) for player in matches if player.player_id is not None]
            advice = (
                f"Select by player ID instead: {', '.join(ids)}."
                if len(ids) == len(matches)
                else "Add unique 'id' fields to these records, then select by ID."
            )
            raise ValueError(
                f"More than one player is named '{requested_name}'. {advice}"
            )

        selected_players.append(matches[0])

    return selected_players


def resolve_team_filter(players: Sequence[Player], team: str | None) -> str | None:
    """Return a matching normalized team name, or None to skip the team filter."""
    if team is None:
        return None
    normalized_team = team.strip().casefold()
    if not normalized_team:
        return None
    for player in players:
        if player.team_name is not None and player.team_name.casefold() == normalized_team:
            return normalized_team
    return None


def shortlist_players(
    players: Sequence[Player],
    *,
    position: str | None = None,
    max_price: float | None = None,
    min_minutes: int = 0,
    sort_by: str = "points",
    limit: int | None = None,
    team: str | None = None,
) -> list[Player]:
    """Filter, then rank descending (price ascending); break ties by name and ID.

    Unknown metrics sort last. A positive minimum-minutes filter excludes players
    whose minutes are unknown. Input players are never reordered in place.
    Team names match without case sensitivity; surrounding input spaces are ignored.
    Team names absent from the full input dataset leave the team filter unapplied.
    """
    if position is not None:
        position = position.upper()
        if position not in POSITIONS.values():
            raise ValueError("Position must be GK, DEF, MID, or FWD.")
    if max_price is not None and (not math.isfinite(max_price) or max_price < 0):
        raise ValueError("Maximum price must be a finite, non-negative number.")
    if min_minutes < 0:
        raise ValueError("Minimum minutes cannot be negative.")
    if limit is not None and limit <= 0:
        raise ValueError("Limit must be greater than zero.")
    if sort_by not in SORT_OPTIONS:
        raise ValueError(f"Sort must be one of: {', '.join(SORT_OPTIONS)}.")
    team = resolve_team_filter(players, team)

    selected = [
        player
        for player in players
        if (position is None or player.position == position)
        and (max_price is None or player.price <= max_price)
        and (min_minutes == 0 or (player.minutes is not None and player.minutes >= min_minutes))
        and (
            team is None
            or (player.team_name is not None and player.team_name.casefold() == team)
        )
    ]

    def ranking_key(player: Player) -> tuple[bool, float, str, int]:
        metrics = {
            "points": player.total_points,
            "price": player.price,
            "points-per-million": player.points_per_million,
            "points-per-90": player.points_per_90,
        }
        value = metrics[sort_by]
        if value is None:
            return (True, 0, player.name.casefold(), player.player_id or 0)
        order = value if sort_by == "price" else -value
        return (False, order, player.name.casefold(), player.player_id or 0)

    return sorted(selected, key=ranking_key)[:limit]
