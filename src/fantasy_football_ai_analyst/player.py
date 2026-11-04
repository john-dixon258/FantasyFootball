"""Player types and transformations for FPL player data."""

from collections.abc import Mapping
from dataclasses import dataclass


POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


@dataclass(frozen=True)
class Player:
    """A small, normalized view of a player's core FPL statistics."""

    name: str
    team_id: int
    position_id: int
    price: float
    total_points: int
    player_id: int | None = None
    minutes: int | None = None
    goals: int | None = None
    assists: int | None = None
    team_name : str | None = None

    @property
    def position(self) -> str:
        return POSITIONS[self.position_id]

    @property
    def points_per_million(self) -> float | None:
        """Season points divided by current price in GBP millions."""
        return self.total_points / self.price if self.price > 0 else None

    @property
    def points_per_90(self) -> float | None:
        """Observed points per 90 minutes; unavailable without minutes played."""
        if self.minutes is None or self.minutes == 0:
            return None
        return self.total_points * 90 / self.minutes

def player_from_fpl_record(record: Mapping[str, object]) -> Player:
    """Convert one raw FPL player record into the application's Player type.

    The FPL API reports ``now_cost`` in tenths of a unit, so a value of 75
    becomes a price of 7.5.

    Raises:
        ValueError: If a required field is missing or has an invalid value.
    """
    first_name = _required_string(record, "first_name")
    second_name = _required_string(record, "second_name")
    team_id = _required_integer(record, "team")
    position_id = _required_integer(record, "element_type")
    now_cost = _required_integer(record, "now_cost")
    total_points = _required_integer(record, "total_points")

    if team_id <= 0:
        raise ValueError("FPL field 'team' must be a positive integer.")
    if position_id not in POSITIONS:
        raise ValueError("FPL field 'element_type' must be 1 (GK), 2 (DEF), 3 (MID), or 4 (FWD).")
    if now_cost < 0:
        raise ValueError("FPL field 'now_cost' cannot be negative.")

    return Player(
        name=f"{first_name} {second_name}",
        team_id=team_id,
        position_id=position_id,
        price=now_cost / 10,
        total_points=total_points,
        player_id=_optional_integer(record, "id", minimum=1),
        minutes=_optional_integer(record, "minutes"),
        goals=_optional_integer(record, "goals_scored"),
        assists=_optional_integer(record, "assists"),
    )


def _required_string(record: Mapping[str, object], field: str) -> str:
    value = _required_value(record, field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"FPL field '{field}' must be a non-empty string.")
    return value.strip()


def _required_integer(record: Mapping[str, object], field: str) -> int:
    value = _required_value(record, field)
    # bool is a subclass of int in Python, but True/False are not valid FPL IDs.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"FPL field '{field}' must be an integer.")
    return value


def _optional_integer(
    record: Mapping[str, object], field: str, *, minimum: int = 0
) -> int | None:
    # Missing statistics stay unknown rather than becoming invented zeroes.
    if field not in record:
        return None
    value = _required_integer(record, field)
    if value < minimum:
        raise ValueError(f"FPL field '{field}' must be at least {minimum}.")
    return value


def _required_value(record: Mapping[str, object], field: str) -> object:
    try:
        return record[field]
    except KeyError as error:
        raise ValueError(f"FPL player record is missing required field '{field}'.") from error
