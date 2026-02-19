#!/usr/bin/env python3
"""openclaw_tailer.py

Tails OpenClaw session JSONL logs and writes a near-real-time activity feed into dashboard_data.json.

Goal: show message received / tool calls / responses as they happen.
Read-only. No control channel.

Notes:
- This does NOT expose hidden chain-of-thought. It logs observable events + short high-level summaries.
- It watches for the newest session file and continues tailing.

Usage:
  python3 openclaw_tailer.py --dashboard /root/.openclaw/workspace/agent-framework/dashboard_data.json \
    --sessions /root/.openclaw/agents/main/sessions
"""

import argparse
import json
import os
import time
from pathlib import Path
from datetime import datetime


def now_ts():
    return datetime.utcnow().strftime('%H:%M:%S')


def load_dashboard(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {
        "rate_limits": {"tavily": {"used": 0, "limit": 5, "remaining": 5}, "llm": {"used": 0, "limit": 20, "remaining": 20}},
        "agents": {"search": [], "verify": [], "summarize": [], "security": [], "sol": []},
        "thoughts": [],
        "memories": [],
        "improvements": [],
        "system": {"phase": "--", "cron_jobs": "--"},
        "last_update": None,
    }


def save_dashboard(path: Path, data: dict):
    data["last_update"] = datetime.utcnow().isoformat()
    path.write_text(json.dumps(data, indent=2))


def append_sol(d: dict, typ: str, content: str):
    d.setdefault("agents", {}).setdefault("sol", [])
    d["agents"]["sol"].append({
        "type": typ,
        "timestamp": now_ts(),
        "content": content[:500],
        "full_timestamp": datetime.utcnow().isoformat(),
    })
    d["agents"]["sol"] = d["agents"]["sol"][-500:]


def newest_session_file(sessions_dir: Path) -> Path | None:
    files = list(sessions_dir.glob('*.jsonl'))
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def tail_file(path: Path, start_pos: int):
    with path.open('r', encoding='utf-8', errors='ignore') as f:
        f.seek(start_pos)
        while True:
            line = f.readline()
            if not line:
                break
            yield line


def event_summary(obj: dict) -> tuple[str, str] | None:
    # We try to extract safe, high-level events.
    # OpenClaw JSONL structure may vary; we guard heavily.

    # Heuristic fields
    role = obj.get('role') or obj.get('type')
    content = obj.get('content')

    # User message
    if obj.get('role') == 'user' and isinstance(content, str):
        return ('message', f"Message received: {content[:120]}")

    # Assistant message
    if obj.get('role') == 'assistant' and isinstance(content, str):
        return ('result', f"Response sent: {content[:120]}")

    # Tool call / tool result (best-effort)
    if 'tool' in obj and obj.get('tool'):
        tool = obj.get('tool')
        status = obj.get('status')
        return ('action', f"Tool: {tool} ({status or 'call'})")

    if obj.get('name') and obj.get('arguments') and obj.get('type') == 'tool_call':
        return ('action', f"Tool call: {obj['name']}")

    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dashboard', required=True)
    ap.add_argument('--sessions', required=True)
    ap.add_argument('--poll-ms', type=int, default=500)
    args = ap.parse_args()

    dashboard_path = Path(args.dashboard)
    sessions_dir = Path(args.sessions)

    last_file = None
    last_pos = 0

    while True:
        cur = newest_session_file(sessions_dir)
        if cur and cur != last_file:
            last_file = cur
            last_pos = 0
            d = load_dashboard(dashboard_path)
            append_sol(d, 'action', f"Tailing session: {cur.name}")
            save_dashboard(dashboard_path, d)

        if last_file:
            # Tail new lines
            for line in tail_file(last_file, last_pos):
                last_pos += len(line.encode('utf-8', errors='ignore'))
                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                ev = event_summary(obj)
                if ev:
                    d = load_dashboard(dashboard_path)
                    append_sol(d, ev[0], ev[1])
                    save_dashboard(dashboard_path, d)

        time.sleep(args.poll_ms / 1000)


if __name__ == '__main__':
    main()
