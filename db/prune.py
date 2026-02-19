#!/usr/bin/env python3
"""prune.py

Keeps the SQLite event store small.
Policy:
- Keep last N events overall (default 20k)
- Also optionally keep last N days (not enabled by default)

We avoid storing high-frequency system telemetry long-term.
"""

import argparse
from pathlib import Path

import sqlite3


def prune(db_path: Path, keep_last: int = 20000):
    con = sqlite3.connect(str(db_path))
    try:
        # Delete everything older than the newest keep_last ids
        row = con.execute("SELECT id FROM events ORDER BY id DESC LIMIT 1 OFFSET ?", (keep_last,)).fetchone()
        if row and row[0]:
            cutoff = int(row[0])
            con.execute("DELETE FROM events WHERE id < ?", (cutoff,))
            con.commit()
            con.execute("VACUUM")
            con.commit()
            return cutoff
        return None
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--keep-last', type=int, default=20000)
    args = ap.parse_args()
    cutoff = prune(Path(args.db), args.keep_last)
    print({'cutoff': cutoff, 'keep_last': args.keep_last})


if __name__ == '__main__':
    main()
