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
        # Allow longer detail in UI; DB will still cap separately.
        "details": detail_text[:12000] if detail_text else "",
        "full_timestamp": ts_iso,
    })
    # Keep a longer rolling window; the live stream can be bursty.
    d["agents"]["sol"] = d["agents"]["sol"][-2000:]

    # Also persist to SQLite as a durable event
    try:
        append_event(agent="sol", typ=typ, summary=content[:200], detail_text=detail_text[:8000], detail={"source": "openclaw_tailer"}, ts=ts_iso)
    except Exception:
        pass

    # Keep cognitive streams queryable in their own tabs (non-destructive: append-only, capped)
    try:
        if typ in ('thought', 'plan', 'insight', 'reflection', 'risk'):
            d.setdefault('thoughts', [])
            d['thoughts'].append({
                'timestamp': now_ts(),
                'type': typ,
                'content': content[:500],
                'detail_text': detail_text[:12000] if detail_text else content[:2000],
            })
            d['thoughts'] = d['thoughts'][-800:]
        if typ == 'improvement':
            d.setdefault('improvements', [])
            d['improvements'].append({
                'timestamp': now_ts(),
                'title': content[:100],
                'content': (detail_text or '')[:2000] or content[:300],
                'detail_text': detail_text[:12000] if detail_text else content[:2000],
            })
            d['improvements'] = d['improvements'][-300:]
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


def _strip_leading_timestamp(s: str) -> str:
    """Remove leading '[Thu 2026-..]' style prefixes to keep feed clean."""
    s = (s or '').lstrip()
    if s.startswith('[') and ']' in s[:64]:
        # remove first bracket block
        s = s.split(']', 1)[1].lstrip()
    return s


def _topic_summary(s: str) -> str:
    """Heuristic, no-LLM summary for feed titles."""
    t = _strip_leading_timestamp(s)
    low = t.lower()

    # System notices should not be misclassified as dashboard requests.
    if low.startswith('system:'):
        return 'System notice'

    # Dashboard-centric heuristics (be strict: only trigger if explicitly about the dashboard)
    if 'dashboard' in low or 'portal' in low:
        if 'timestamp' in low:
            return 'Dashboard: clean feed (remove timestamps)'
        # Only label "system monitors & graphs" when the request is explicitly about
        # telemetry/metrics rendering (avoid false positives when the text merely mentions "graphs").
        if ('sys.json' in low) or ('telemetry' in low) or ('spark' in low) or ('sparkline' in low) or ('metrics' in low):
            return 'Dashboard: system monitors & graphs'
        if 'tiles' in low or 'history' in low:
            return 'Dashboard: agent tiles & history'
        return 'Dashboard: UX / live feed'

    if 'rapp' in low:
        return 'RAPP: research run'
    # Avoid overloading historical project acronyms (e.g. TAR) in dashboard summaries.

    # Fallback: first sentence-ish
    return _short(t.replace('\n', ' '), 90)


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
        # We do NOT want computer-ish dumps here. Keep only high-signal outcomes.
        out = (aggregated or '').strip()
        if not out:
            return

        # If it's a big command output, drop it unless it looks like an error or a meaningful state change.
        low = out.lower()
        keep = any(k in low for k in ['error', 'failed', 'refused', 'traceback', 'exception'])
        keep = keep or any(k in out for k in ['Started ', 'Stopped ', 'Active: ', 'LISTEN ', 'Connected', 'Disconnected'])

        if not keep:
            return

        # Summarize common patterns
        summary = ''
        if 'LISTEN ' in out:
            summary = 'Confirmed a service is listening on the expected port.'
        elif 'Started ' in out:
            summary = 'Service started successfully.'
        elif 'Active: active (running)' in out:
            summary = 'Service is running.'
        elif any(k in low for k in ['failed', 'error', 'exception', 'traceback']):
            summary = 'An error occurred (see details).'
        else:
            summary = _short(out.replace('\n', ' '), 180)

        self.tool_results.append({'tool': tool_name, 'out': summary})


    def add_thinking(self, snippets: list[str]):
        self.thinking.extend(snippets)

    def add_response(self, text: str):
        if text:
            self.response_text = text

    def build_events(self) -> list[tuple[str, str, str]]:
        """Return a small sequence of high-level, queryable events.

        Policy (per D): this must be human-readable and *grounded*.
        Avoid template filler like "I interpreted this as needing clear UX" unless it is
        genuinely specific to this turn.
        """
        user_clean = _strip_leading_timestamp(self.user_text.strip())
        topic = _topic_summary(user_clean)
        summary = topic or "Activity"

        lines: list[str] = []

        # 1) Request (ground truth)
        lines.append("Request")
        lines.append("- " + _short(user_clean, 1600))

        # 2) Actions (grounded in actual tool usage)
        if self.tool_calls:
            lines.append("")
            lines.append("Actions")
            tool_names = [tc.get('name') for tc in self.tool_calls if tc.get('name')]
            uniq = list(dict.fromkeys(tool_names))

            # One-line overview
            if uniq:
                lines.append(f"- Tools used: {', '.join(uniq[:6])}{'…' if len(uniq) > 6 else ''}")

            # Up to a few concrete, non-repetitive purposes
            seen = set()
            for tc in self.tool_calls:
                name = tc.get('name')
                if not name or name in seen:
                    continue
                seen.add(name)
                why, did = _tool_purpose(name, tc.get('arguments') or {})
                lines.append(f"- {name}: {did}")
                if len(seen) >= 4:
                    break

        # 3) Outputs (only if meaningful)
        if self.tool_results:
            kept = [tr for tr in self.tool_results if tr.get('out')]
            if kept:
                lines.append("")
                lines.append("Notable outputs")
                for tr in kept[:3]:
                    lines.append(f"- {tr['out']}")

        # 4) Response (what the user actually saw)
        if self.response_text:
            lines.append("")
            lines.append("Response")
            import re
            rt = re.sub(r"```.*?```", "[code omitted]", self.response_text or "", flags=re.S)
            rt = ' '.join(rt.split())
            parts = re.split(r"(?<=[.!?])\s+", rt)
            short = ' '.join(parts[:2]).strip() if parts else rt
            lines.append("- " + _short(short, 700))

        detail_text = "\n".join(lines).strip()

        # Emit fewer, higher-signal events.
        events: list[tuple[str, str, str]] = []

        # A single thought event to anchor the turn, but without templated filler.
        events.append(('thought', f"Intent: {summary}", "Request\n- " + _short(user_clean, 800)))

        # Full drill-down event.
        events.append(('activity', summary, detail_text))

        return events


# One accumulator for the current tailed file
ACC = TurnAccumulator()


def event_summary(obj: dict):
    """Consume raw OpenClaw JSONL wrapper and return:

    - None
    - a single (type, summary, detail_text)
    - OR a list of (type, summary, detail_text) for granular streaming
    """
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
        clean = _strip_leading_timestamp(text)
        topic = _topic_summary(clean)
        detail = "What D asked\n- " + _short(clean.strip(), 1200)
        return ('message', f"New request: {topic}", detail)

    if role == 'assistant':
        resp_text, tool_calls, thinking_snips = _extract_assistant_text_blocks(content)
        for tc in tool_calls:
            ACC.add_tool_call(tc.get('name'), tc.get('arguments') or {})
        if thinking_snips:
            # Accuracy policy: do not emit raw "thinking" snippets as telemetry.
            # They can contain speculative/internal text that looks like a workflow update.
            # We only log (a) narrative interpretation, (b) concrete tool actions, (c) final response.
            ACC.add_thinking(thinking_snips)

        if resp_text:
            ACC.add_response(resp_text)
            # Emit granular events when we have a response
            return ACC.build_events()
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


def _load_tailer_state(state_path: Path) -> dict:
    try:
        if state_path.exists():
            return json.loads(state_path.read_text())
    except Exception:
        pass
    return {"last_file": None, "last_pos": 0}


def _save_tailer_state(state_path: Path, last_file: Path | None, last_pos: int):
    try:
        state_path.write_text(json.dumps({
            "last_file": str(last_file) if last_file else None,
            "last_pos": int(last_pos),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2) + "\n")
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dashboard', required=True)
    ap.add_argument('--sessions', required=True)
    ap.add_argument('--poll-ms', type=int, default=500)
    ap.add_argument('--state', default=str(Path(__file__).parent / 'tailer_state.json'))
    args = ap.parse_args()

    dashboard_path = Path(args.dashboard)
    sessions_dir = Path(args.sessions)
    state_path = Path(args.state)

    st = _load_tailer_state(state_path)
    last_file = Path(st['last_file']) if st.get('last_file') else None
    last_pos = int(st.get('last_pos') or 0)

    while True:
        cur = newest_session_file(sessions_dir)
        if cur and (last_file is None or cur != last_file):
            last_file = cur
            last_pos = 0
            d = load_dashboard(dashboard_path)
            append_sol(d, 'action', f"Tailing session: {cur.name}")
            save_dashboard(dashboard_path, d)
            _save_tailer_state(state_path, last_file, last_pos)

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
                    if isinstance(ev, list):
                        for (typ, summary, detail_text) in ev:
                            append_sol(d, typ, summary, detail_text=detail_text)
                    else:
                        typ, summary, detail_text = ev
                        append_sol(d, typ, summary, detail_text=detail_text)
                    save_dashboard(dashboard_path, d)

                # Persist tail position so restarts don't replay old lines
                _save_tailer_state(state_path, last_file, last_pos)

        time.sleep(args.poll_ms / 1000)


if __name__ == '__main__':
    main()
