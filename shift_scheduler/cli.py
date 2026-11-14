"""Command-line entry point: load a config, solve, and print the schedule."""
from __future__ import annotations
import argparse
import sys
from typing import Sequence
from .config import ConfigError, load_config
from .report import format_result
from .scheduler import solve
EXIT_OK = 0
EXIT_INFEASIBLE = 1  # no schedule, or the schedule leaves staffing gaps
EXIT_CONFIG_ERROR = 2
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimise team shift assignments from a JSON config file.")
    parser.add_argument(
        "-c",
        "--config",
        default="config.json",
        help="Path to the JSON config file (default: %(default)s)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat minimum staffing as a hard constraint and report conflicting rules if no schedule exists",
    )
    return parser
def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    result = solve(config, strict=args.strict)
    print(format_result(config, result))
    if not result.feasible or result.shortfalls:
        return EXIT_INFEASIBLE
    return EXIT_OK
