#!/usr/bin/env python3
"""Weekly Richmond-area restaurant inspection digest → Telegram.

Usage:
    python -m agent.inspections.run_digest              # last 7 days, send
    python -m agent.inspections.run_digest --dry-run    # print, don't send
    python -m agent.inspections.run_digest --days 14
    python -m agent.inspections.run_digest --fixture path.json   # offline render

Environment:
    TELEGRAM_BOT_TOKEN          required to send
    TELEGRAM_CHAT_ID            required to send
    INSPECTIONS_PROXY_TEMPLATE  optional, see transport.py
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

from . import sources
from .digest import build_digest
from .models import Inspection
from .telegram import send_message
from .transport import FetchBlocked, FetchError

STATE_PATH = os.path.join(os.path.dirname(__file__), "seen.json")


def load_seen(path: str) -> set[str]:
    try:
        with open(path) as f:
            return set(json.load(f).get("seen", []))
    except (OSError, ValueError):
        return set()


def save_seen(path: str, seen: set[str], keep: int = 4000) -> None:
    # Bounded so the state file doesn't grow without limit; ids are time-ordered
    # enough that keeping the tail is fine.
    trimmed = sorted(seen)[-keep:]
    with open(path, "w") as f:
        json.dump({"seen": trimmed}, f, indent=1)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=7, help="lookback window (default 7)")
    p.add_argument("--dry-run", action="store_true", help="print the digest instead of sending")
    p.add_argument("--fixture", help="render from a JSON file of inspections instead of fetching")
    p.add_argument("--no-state", action="store_true", help="ignore and don't update seen.json")
    p.add_argument("--send-empty", action="store_true", help="send a digest even with no inspections")
    args = p.parse_args(argv)

    end = date.today()
    start = end - timedelta(days=args.days)

    if args.fixture:
        with open(args.fixture) as f:
            inspections = [Inspection.from_dict(d) for d in json.load(f)]
        inspections = [i for i in inspections if start <= i.inspection_date <= end] or inspections
    else:
        try:
            inspections = sources.fetch_all(start, end)
        except FetchBlocked as e:
            print(f"BLOCKED: {e}", file=sys.stderr)
            return 2
        except FetchError as e:
            print(f"FETCH FAILED: {e}", file=sys.stderr)
            return 1

    seen = set() if args.no_state else load_seen(STATE_PATH)
    fresh = [i for i in inspections if i.id not in seen]
    print(f"{len(inspections)} inspection(s) in window, {len(fresh)} not yet reported",
          file=sys.stderr)

    if not fresh and not args.send_empty:
        print("Nothing new — no message sent.", file=sys.stderr)
        return 0

    text = build_digest(fresh, start, end, source_links=sources.SOURCE_LINKS)

    if args.dry_run:
        print(text)
        return 0

    count = send_message(text)
    print(f"Sent {count} Telegram message(s).", file=sys.stderr)

    if not args.no_state:
        save_seen(STATE_PATH, seen | {i.id for i in fresh})
    return 0


if __name__ == "__main__":
    sys.exit(main())
