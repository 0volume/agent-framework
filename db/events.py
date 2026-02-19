#!/usr/bin/env python3
"""events.py

SQLite event store for the dashboard.
Goal: scalable, queryable history across all agents and system events.

Schema: events(id, ts, agent, type, summary, detail_json)
- summary: short string for live feed
- detail_json: verbose payload for drill-down

No external deps (uses stdlib sqlite3).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = Path(__file__).resolve().parent / "events.sqlite3"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          agent TEXT NOT NULL,
          type TEXT NOT NULL,
          summary TEXT NOT NULL,
          detail_json TEXT NOT NULL
        );
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_agent_ts ON events(agent, ts);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(type, ts);")
    con.commit()


def append_event(
    agent: str,
    typ: str,
    summary: str,
    detail: Optional[Dict[str, Any]] = None,
    ts: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> int:
    """Append a new event. Returns inserted event id."""
    if ts is None:
        ts = utc_now_iso()
    if detail is None:
        detail = {}

    payload = {
        "ts": ts,
        "agent": agent,
        "type": typ,
        "summary": summary,
        "detail": detail,
    }

    con = connect(db_path)
    try:
        init_db(con)
        cur = con.execute(
            "INSERT INTO events(ts, agent, type, summary, detail_json) VALUES(?,?,?,?,?)",
            (ts, agent, typ, summary, json.dumps(payload, ensure_ascii=False)),
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def query_events(
    limit: int = 200,
    agent: Optional[str] = None,
    typ: Optional[str] = None,
    text: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    """Query recent events (newest first)."""
    con = connect(db_path)
    try:
        init_db(con)
        clauses = []
        params: List[Any] = []

        if agent:
            clauses.append("agent = ?")
            params.append(agent)
        if typ:
            clauses.append("type = ?")
            params.append(typ)
        if text:
            clauses.append("(summary LIKE ? OR detail_json LIKE ?)")
            t = f"%{text}%"
            params.extend([t, t])

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        rows = con.execute(
            f"SELECT id, ts, agent, type, summary, detail_json FROM events {where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r["detail_json"])
            except Exception:
                payload = {"raw": r["detail_json"]}
            out.append(
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "agent": r["agent"],
                    "type": r["type"],
                    "summary": r["summary"],
                    "payload": payload,
                }
            )
        return out
    finally:
        con.close()
