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
from datetime import datetime, timezone

# Write to SQLite event store (durable history)
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from db.events import append_event


def now_ts():
    return datetime.now(timezone.utc).strftime('%H:%M:%S')


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
    data["last_update"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2))


def append_sol(d: dict, typ: str, content: str, detail_text: str = ""):
    ts_iso = datetime.now(timezone.utc).isoformat()
    d.setdefault("agents", {}).setdefault("sol", [])
    d["agents"]["sol"].append({
        "type": typ,
        "timestamp": now_ts(),
        "content": content[:500],
        "details": detail_text[:2000] if detail_text else "",
        "full_timestamp": ts_iso,
    })
    d["agents"]["sol"] = d["agents"]["sol"][-500:]

    # Also persist to SQLite as a durable event
    try:
        append_event(agent="sol", typ=typ, summary=content[:200], detail_text=detail_text[:2000], detail={"source": "openclaw_tailer"}, ts=ts_iso)
    except Exception:
        pass


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


def event_summary(obj: dict) -> tuple[str, str, str] | None:
    """Extract a high-level, human-readable event.

    Returns: (type, summary, detail_text)
    """

    # OpenClaw session JSONL lines are wrapped like:
    # {"type":"message", "timestamp":..., "message": {"role":..., "content":[...]}}
    msg = obj.get('message') if isinstance(obj.get('message'), dict) else None
    if msg:
        role = msg.get('role')
        content = msg.get('content')

        # User message
        if role == 'user':
            if isinstance(content, str):
                return ('message', f"Message received", content[:400])
            if isinstance(content, list) and content and isinstance(content[0], dict):
                # sometimes content is structured
                text = content[0].get('text') or str(content[0])
                return ('message', f"Message received", str(text)[:400])

        # Assistant message
        if role == 'assistant':
            # content is usually a list with thinking/toolCall blocks
            if isinstance(content, list):
                # Summarize tool calls
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get('type') == 'toolCall':
                        name = block.get('name')
                        args = block.get('arguments')
                        detail = ''
                        if args and isinstance(args, dict):
                            # keep small
                            detail = json.dumps(args)[:500]
                        return ('action', f"Tool call: {name}", detail)
                    if block.get('type') == 'thinking':
                        # We do NOT dump hidden reasoning; we store a short excerpt.
                        thinking = block.get('thinking')
                        if isinstance(thinking, str) and thinking.strip():
                            return ('thinking', 'Thinking (summary)', thinking.strip()[:500])

                # If no tool call, treat as response
                # Try to find text output
                text_bits = []
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text_bits.append(block.get('text',''))
                if text_bits:
                    t = '\n'.join(text_bits).strip()
                    if t:
                        return ('result', 'Response sent', t[:500])

            if isinstance(content, str):
                return ('result', 'Response sent', content[:500])

        # ToolResult lines
        if role == 'toolResult':
            tool_name = msg.get('toolName')
            details = msg.get('details')
            agg = ''
            if isinstance(details, dict):
                agg = details.get('aggregated') or ''
            return ('result', f"Tool result: {tool_name}", str(agg)[:800])

    # Fallback: ignore
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
                    typ, summary, detail_text = ev
                    d = load_dashboard(dashboard_path)
                    append_sol(d, typ, summary, detail_text=detail_text)
                    save_dashboard(dashboard_path, d)

        time.sleep(args.poll_ms / 1000)


if __name__ == '__main__':
    main()
