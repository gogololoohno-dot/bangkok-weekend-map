"""Fetch every source and bank the rows. Usage:

    python scrape.py            # all sources
    python scrape.py --only gm  # one source (second daily gm run)

Each source is isolated: a failure is logged and the rest still commit. Exit code is 1 if
any source failed, so the scheduled task shows red instead of silently writing gaps.
"""

import argparse
import sys
import traceback

import store
from sources import SOURCES


def select(sources, only: str | None):
    if not only:
        return list(sources)
    return [s for s in sources if s.__name__.rsplit(".", 1)[-1] == only]


def run(sources, conn) -> list[str]:
    failed = []
    for src in sources:
        name = src.__name__
        try:
            rows = src.fetch()
            store.upsert_daily(conn, src.PLAYER, rows)
            print(f"ok    {name:<28} {len(rows)} rows")
        except Exception:
            failed.append(name)
            print(f"FAIL  {name}", file=sys.stderr)
            traceback.print_exc()
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run a single source module, e.g. gm")
    args = ap.parse_args()
    conn = store.connect()
    failed = run(select(SOURCES, args.only), conn)
    if failed:
        print(f"{len(failed)} source(s) failed: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
