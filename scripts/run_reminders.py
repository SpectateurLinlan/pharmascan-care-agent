"""Explicit administrative worker, independent of FastAPI/browser lifecycle.

Run once per minute using an external scheduler, or --loop while this process is
supervised. Never imported or selected as a normal patient repository fallback.
"""

import argparse
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import Settings
from app.transport.worker_container import build_worker_dispatch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--limit", type=int, default=50, choices=range(1, 51))
    parser.add_argument("--budget", type=float, default=20)
    args = parser.parse_args()
    settings = Settings.from_env()
    if not settings.enable_web_push or not all(
        (settings.vapid_public_key, settings.vapid_private_key, settings.vapid_subject)
    ):
        print("Web Push disabled or incomplete VAPID configuration; no jobs sent.")
        return 2
    dispatch = build_worker_dispatch(settings, synthetic_only=args.synthetic_only)
    while True:
        result = dispatch.run(limit=args.limit, budget_seconds=args.budget)
        print(
            result.model_dump_json()
            if args.json
            else f"Reminder worker processed {result.processed} deliveries ({result.status})."
        )
        if not args.loop:
            return 0
        time.sleep(30)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (psycopg.Error, ValueError):
        print("Reminder configuration or database unavailable; no delivery success is claimed.")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(0) from None
