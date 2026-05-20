"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from tp_icu_sync.config import Config
from tp_icu_sync.icu.client import IcuApiError, IcuAuthError
from tp_icu_sync.sync import run_sync
from tp_icu_sync.tp.client import TPApiError, TPAuthError


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="tp-icu-sync",
        description="Mirror planned TrainingPeaks workouts to intervals.icu calendar.",
    )
    p.add_argument(
        "--days",
        type=int,
        default=14,
        help="Rolling window in days from today (default: 14).",
    )
    p.add_argument(
        "--activity-lookback",
        type=int,
        default=14,
        help="Look this many days into the past for paired-activity description sync (default: 14, 0 disables).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to intervals.icu.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG-level logging.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )

    try:
        cfg = Config.load()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        result = run_sync(
            cfg,
            days=args.days,
            activity_lookback=args.activity_lookback,
            dry_run=args.dry_run,
        )
    except (TPAuthError, IcuAuthError) as exc:
        print(f"AUTH ERROR: {exc}", file=sys.stderr)
        return 2
    except (TPApiError, IcuApiError) as exc:
        print(f"API ERROR: {exc}", file=sys.stderr)
        return 2

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(
        f"\n[{mode}] created={len(result.created)} updated={len(result.updated)} "
        f"deleted={len(result.deleted)} unchanged={len(result.unchanged)} "
        f"activity_desc={len(result.activity_updates)}"
    )
    if result.errors:
        print(f"ERRORS ({len(result.errors)}):", file=sys.stderr)
        for e in result.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
