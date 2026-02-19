#!/usr/bin/env python3
"""openclaw_tailer.py

Tails OpenClaw session JSONL logs and writes a near-real-time *high-level* activity feed.

Design goals (per D):
- High-level, human-readable, cognitive events (topic, plan, key actions, outcomes)
- Avoid low-level noise (do NOT store every tool call / raw outputs)
- Store: short summary for live feed + richer, still human-readable detail for click/expand
- No hidden chain-of-thought dumping
- Read-only. No control channel.

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


def _short(s: str, n: int) -> str:
    s = (s or '').strip()
    return s if len(s) <= n else s[: n - 1] + '…'


def _tool_purpose(tool_name: str, args: dict | None) -> tuple[str, str]:
    """Return (why, accomplished) from best-effort heuristics."""
    if tool_name == 'web_fetch':
        url = (args or {}).get('url')
        return ("to fetch a source page", f"fetched: {_short(str(url), 80)}")
    if tool_name == 'web_search':
        q = (args or {}).get('query')
        return ("to search the web", f"query: {_short(str(q), 80)}")
    if tool_name == 'exec':
        cmd = (args or {}).get('command', '')
        scmd = str(cmd)
        if 'systemctl' in scmd:
            return ("to manage/check services", "checked service status")
        if 'curl' in scmd:
            return ("to check an endpoint", "verified HTTP response")
        if 'git ' in scmd:
            return ("to update repository state", "updated repo")
        if 'df ' in scmd or 'free ' in scmd or 'uptime' in scmd:
            return ("to read system metrics", "collected system stats")
        return ("to run a system command", _short(scmd.replace('\n', ' '), 120))
    if tool_name == 'message':
        return ("to notify you", "sent notification")
    return ("to use a tool", "completed")


def _extract_user_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content and isinstance(content[0], dict):
        return content[0].get('text') or ''
    return ''


def _extract_assistant_text_blocks(content) -> tuple[str, list[dict], list[str]]:
    """Return (response_text, tool_calls, thinking_snippets)."""
    response_text = ''
    tool_calls: list[dict] = []
    thinking_snips: list[str] = []

    if isinstance(content, str):
        return (content, tool_calls, thinking_snips)

    if isinstance(content, list):
        texts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'toolCall':
                tool_calls.append({
                    'name': b.get('name'),
                    'arguments': b.get('arguments') if isinstance(b.get('arguments'), dict) else {},
                })
            elif b.get('type') == 'thinking':
                t = b.get('thinking')
                if isinstance(t, str) and t.strip():
                    # Keep only a small excerpt; no chain-of-thought dumping.
                    thinking_snips.append(_short(t.strip(), 220))
            elif b.get('type') == 'text':
                txt = b.get('text')
                if isinstance(txt, str) and txt.strip():
                    texts.append(txt.strip())
        response_text = '\n'.join(texts).strip()

    return (response_text, tool_calls, thinking_snips)


class TurnAccumulator:
    """Accumulate low-level events into a single high-level log entry per user request."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.user_text = ''
        self.user_ts = ''
        self.tool_calls: list[dict] = []
        self.tool_results: list[dict] = []
        self.thinking: list[str] = []
        self.response_text = ''

    def has_active(self) -> bool:
        return bool(self.user_text)

    def add_user(self, ts_iso: str, text: str):
        self.reset()
        self.user_ts = ts_iso
        self.user_text = text.strip()

    def add_tool_call(self, name: str, args: dict):
        self.tool_calls.append({'name': name, 'arguments': args})

    def add_tool_result(self, tool_name: str, aggregated: str):
        # Keep tiny: just first ~200 chars
        self.tool_results.append({'tool': tool_name, 'out': _short(aggregated, 240)})

    def add_thinking(self, snippets: list[str]):
        self.thinking.extend(snippets)

    def add_response(self, text: str):
        if text:
            self.response_text = text

    def build_event(self) -> tuple[str, str, str]:
        """Return (type, summary, detail_text)."""
        topic = _short(self.user_text.replace('\n', ' '), 90)

        # High-level tools summary
        tools_used = []
        for tc in self.tool_calls:
            n = tc.get('name')
            if n:
                tools_used.append(n)
        tools_used = list(dict.fromkeys(tools_used))  # dedupe preserve order

        # Summary should be human, at-a-glance, not system-ish.
        # Avoid showing tool lists / IDs / timestamps.
        summary = topic or "Activity"
        if self.response_text:
            summary = f"{summary}"

        # Detail text: still human-readable
        lines = []
        lines.append("What D asked")
        lines.append("- " + _short(self.user_text.strip(), 1200))
        if self.thinking:
            lines.append("")
            lines.append("My high-level thinking")
            for s in self.thinking[-3:]:
                lines.append("- " + s)
        if self.tool_calls:
            lines.append("")
            lines.append("Key actions")
            for tc in self.tool_calls[:6]:
                why, acc = _tool_purpose(tc.get('name',''), tc.get('arguments') or {})
                lines.append(f"- Used {tc.get('name')} {why} → {acc}")
        if self.tool_results:
            lines.append("")
            lines.append("Important outputs")
            # Keep this focused: short excerpts only.
            for tr in self.tool_results[:3]:
                lines.append(f"- {tr['tool']}: {tr['out']}")
        if self.response_text:
            lines.append("")
            lines.append("Response summary")
            lines.append("- " + _short(self.response_text.replace('\n',' '), 380))

        detail_text = "\n".join(lines).strip()
        return ('activity', summary, detail_text)


# One accumulator for the current tailed file
ACC = TurnAccumulator()


def event_summary(obj: dict) -> tuple[str, str, str] | None:
    """Consume raw OpenClaw JSONL wrapper, update ACC, and occasionally emit a high-level event."""
    msg = obj.get('message') if isinstance(obj.get('message'), dict) else None
    if not msg:
        return None

    role = msg.get('role')
    content = msg.get('content')
    ts_iso = obj.get('timestamp') or datetime.now(timezone.utc).isoformat()

    if role == 'user':
        text = _extract_user_text(content)
        ACC.add_user(ts_iso, text)
        # Emit one immediate high-level "received" event (topic only)
        topic = _short(text.replace('\n', ' '), 90)
        detail = f"Message topic: {topic}\n\nFull message:\n{text.strip()}"
        return ('message', f"New request: {topic}", detail)

    if role == 'assistant':
        resp_text, tool_calls, thinking_snips = _extract_assistant_text_blocks(content)
        for tc in tool_calls:
            ACC.add_tool_call(tc.get('name'), tc.get('arguments') or {})
        if thinking_snips:
            ACC.add_thinking(thinking_snips)
        if resp_text:
            ACC.add_response(resp_text)
            # Emit one aggregated event when we have a response
            return ACC.build_event()
        return None

    if role == 'toolResult':
        tool_name = msg.get('toolName')
        details = msg.get('details')
        agg = ''
        if isinstance(details, dict):
            agg = details.get('aggregated') or ''
        # We store only a small excerpt as "important output" and do not emit separate event.
        if tool_name and agg:
            ACC.add_tool_result(tool_name, agg)
        return None

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
