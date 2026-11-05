"""Command-line interface and command dispatcher."""

import argparse
import sys
from collections.abc import Sequence
from importlib.resources import as_file, files
from pathlib import Path

from fantasy_football_ai_analyst.analysis import (
    SORT_OPTIONS,
    add_next_opponent,
    find_players,
    resolve_team_filter,
    shortlist_players,
)
from fantasy_football_ai_analyst.data import load_fixtures, load_players
from fantasy_football_ai_analyst.player import POSITIONS, Player


PLAYER_DATA_FILE = Path("data/local/fpl-bootstrap.json")
FIXTURE_DATA_FILE = Path("data/local/fpl-fixtures.json")

METRIC_NOTE = (
    "Pts/m = season points / current price (GBP millions). "
    "Pts/90 = season points * 90 / minutes played.\n"
    "N/A means unavailable. These describe past performance, not predicted points; "
    "small minute samples can mislead."
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpl-analyst",
        description="Inspect and compare Fantasy Premier League player data.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    demo_command = commands.add_parser(
        "demo", help="Try the bundled fictional dataset; no file or network needed."
    )
    demo_command.set_defaults(demo=True)

    list_command = commands.add_parser("list", help="List players in a JSON data file.")
    list_command.add_argument("--position", type=str.upper, choices=list(POSITIONS.values()))
    list_command.add_argument("--max-price", type=float, help="Maximum current price in GBP millions.")
    list_command.add_argument("--min-minutes", type=int, default=0, help="Minimum minutes played.")
    list_command.add_argument("--sort", choices=SORT_OPTIONS, default="points")
    list_command.add_argument("--limit", type=int, help="Show at most this many players.")
    list_command.add_argument("--team", type=str, help="Filter by team name (case-insensitive); unrecognized names skip this filter.")

    compare_command = commands.add_parser(
        "compare", help="Compare two players' statistics and observed value."
    )
    compare_command.add_argument(
        "player_names",
        nargs=2,
        metavar=("PLAYER_ONE", "PLAYER_TWO"),
        help="Two full player names (case-insensitive) or numeric player IDs.",
    )

    for command in (list_command, compare_command):
        command.add_argument(
            "--demo", action="store_true", help="Use bundled fictional players instead of local data."
        )

    return parser


def _format_players(players: Sequence[Player]) -> str:
    if not players:
        return "No players found."

    name_width = max(20, max(len(player.name) for player in players))
    rows = [
        f"{'ID':>5}  {'PLAYER':<{name_width}} {'POS':<4} {'GBP m':>7} "
        f"{'POINTS':>7} {'MINUTES':>8} {'Pts/m':>7} {'Pts/90':>7} "
        f"{'TEAM':>20} {'NEXT OPPONENT':>20}"
    ]
    for player in players:
        rows.append(
            f"{_format_value(player.player_id):>5}  {player.name:<{name_width}} "
            f"{player.position:<4} {player.price:>7.1f} {player.total_points:>7} "
            f"{_format_value(player.minutes):>8} {_format_value(player.points_per_million):>7} "
            f"{_format_value(player.points_per_90):>7} {_format_value(player.team_name):>20} "
            f"{_format_value(player.next_opponent):>20}"
        )
    return "\n".join(rows)


def _format_value(value: int | float | str | None) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _format_comparison(first: Player, second: Player) -> str:
    width = max(16, len(first.name), len(second.name))
    rows = [f"{'STATISTIC':<20} {first.name:>{width}} {second.name:>{width}}"]
    statistics = [
        ("Player ID", first.player_id, second.player_id),
        ("Team ID", first.team_id, second.team_id),
        ("Position", first.position, second.position),
        ("Price (GBP m)", f"{first.price:.1f}", f"{second.price:.1f}"),
        ("Total points", first.total_points, second.total_points),
        ("Minutes", first.minutes, second.minutes),
        ("Goals", first.goals, second.goals),
        ("Assists", first.assists, second.assists),
        ("Pts/m", first.points_per_million, second.points_per_million),
        ("Pts/90", first.points_per_90, second.points_per_90),
        ("Team name", first.team_name, second.team_name),
        ("Next Opponent", first.next_opponent, second.next_opponent),
    ]
    for label, first_value, second_value in statistics:
        rows.append(
            f"{label:<20} {_format_value(first_value):>{width}} "
            f"{_format_value(second_value):>{width}}"
        )
    return "\n".join(rows)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse a user command, load its data, and dispatch the requested action."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)

    try:
        if arguments.demo:
            sample = files("fantasy_football_ai_analyst").joinpath("sample_players.json")
            with as_file(sample) as data_path:
                players, team_names  = load_players(data_path)
            fixtures = []
            print("DEMO: fictional players and statistics, not current FPL data.\n")
        else:
            players, team_names = load_players(PLAYER_DATA_FILE)
            fixtures = load_fixtures(FIXTURE_DATA_FILE)

        if arguments.command == "demo":
            print(_format_players(shortlist_players(players)))
            print(f"\n{METRIC_NOTE}")
            return 0

        # This is the small input/action router: each command calls a focused function.
        if arguments.command == "list":
            team = resolve_team_filter(players, arguments.team)
            if arguments.team is not None and team is None:
                print(
                    f"Warning: team '{arguments.team}' was not found in this data; "
                    "team filter skipped.",
                    file=sys.stderr,
                )
            selected_players = shortlist_players(
                players,
                position=arguments.position,
                max_price=arguments.max_price,
                min_minutes=arguments.min_minutes,
                sort_by=arguments.sort,
                limit=arguments.limit,
                team=team,
            )
            players_with_opponents: list[Player] = []
            for player in selected_players:
                updated_player = add_next_opponent(player, fixtures, team_names)
                players_with_opponents.append(updated_player)
            print(_format_players(players_with_opponents))
            print(f"\n{METRIC_NOTE}")
            return 0

        if arguments.command == "compare":
            first, second = find_players(players, arguments.player_names)
            first = add_next_opponent(first, fixtures, team_names)
            second = add_next_opponent(second, fixtures, team_names)
            print(_format_comparison(first, second))
            print(f"\n{METRIC_NOTE}")
            return 0

        parser.error(f"Unknown command: {arguments.command}")
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    return 0
