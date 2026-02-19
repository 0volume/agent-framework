#!/usr/bin/env python3
"""openclaw_tailer.py

Tails OpenClaw session JSONL logs and writes a near-real-time *high-level* activity feed.

Design goals (per D):
- High-level, human-readable monitoring
- Separate *cognition* from *worklog*
- Cognition must be explicitly authored (no inferred mind-reading)
- Avoid low-level noise (do NOT store every tool call / raw outputs)
- Store: short summary for live feed + richer, still human-readable detail for click/expand
- No hidden chain-of-thought dumping
- Read-only. No control channel.

Usage:
  python3 openclaw_tailer.py --dashboard /root/.openclaw/workspace/agent-framework/dashboard_data.json \
    --sessions /root/.openclaw/agents/main/sessions

Multi-agent usage (all agents):
  python3 openclaw_tailer.py --dashboard ... --sessions-glob '/root/.openclaw/agents/*/sessions'
"""

import argparse
import json
import time
from pathlib import Path
from datetime import datetime, timezone

# Write to SQLite event store (durable history)
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from db.events import append_event


def now_ts() -> str:
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
        "worklog": [],
        "memories": [],
        "improvements": [],
        "system": {"phase": "--", "cron_jobs": "--"},
        "last_update": None,
    }


def save_dashboard(path: Path, data: dict):
    data["last_update"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2))


def append_sol(d: dict, typ: str, content: str, detail_text: str = "", agent: str = "sol"):
    """Append a Sol (or subagent) event to the dashboard data."""
    ts_iso = datetime.now(timezone.utc).isoformat()
    d.setdefault("agents", {}).setdefault(agent, [])
    d["agents"][agent].append({
        "type": typ,
        "timestamp": now_ts(),
        "content": (content or '')[:500],
        # Allow longer detail in UI; DB will still cap separately.
        "details": detail_text[:12000] if detail_text else "",
        "full_timestamp": ts_iso,
    })

    # Keep a longer rolling window; the live stream can be bursty.
    d["agents"][agent] = d["agents"][agent][-2000:]

    # Also persist to SQLite as a durable event
    try:
        append_event(agent=agent, typ=typ, summary=(content or '')[:200], detail_text=(detail_text or '')[:8000], detail={"source": "openclaw_tailer"}, ts=ts_iso)
    except Exception:
        pass

    # Keep streams queryable in their own tabs (non-destructive: append-only, capped)
    try:
        if typ in ('thought', 'idea', 'plan', 'reflection', 'decision', 'risk', 'insight', 'highlight'):
            d.setdefault('thoughts', [])
            d['thoughts'].append({
                'timestamp': now_ts(),
                'type': typ,
                'content': (content or '')[:500],
                'detail_text': (detail_text[:12000] if detail_text else (content or '')[:2000]),
            })
            d['thoughts'] = d['thoughts'][-800:]

        if typ == 'worklog':
            d.setdefault('worklog', [])
            d['worklog'].append({
                'timestamp': now_ts(),
                'type': 'worklog',
                'content': (content or '')[:500],
                'detail_text': (detail_text[:12000] if detail_text else (content or '')[:2000]),
            })
            d['worklog'] = d['worklog'][-800:]

        if typ == 'improvement':
            d.setdefault('improvements', [])
            d['improvements'].append({
                'timestamp': now_ts(),
                'title': (content or '')[:100],
                'content': (detail_text or '')[:2000] or (content or '')[:300],
                'detail_text': detail_text[:12000] if detail_text else (content or '')[:2000],
            })
            d['improvements'] = d['improvements'][-300:]
    except Exception:
        pass


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
    """Best-effort user text extraction.

    OpenClaw sessions often encode messages as a list of blocks.
    We prefer concatenating all text blocks (not just the first one).
    If there is no text, but there is media, return a short placeholder so
    the dashboard doesn't show an empty request.
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts: list[str] = []
        has_media = False
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get('type')
            if t == 'text':
                txt = b.get('text')
                if isinstance(txt, str) and txt.strip():
                    texts.append(txt.strip())
            if t in ('image', 'input_image') or ('image' in b) or ('media' in b):
                has_media = True

        if texts:
            return "\n".join(texts).strip()
        if has_media:
            return "[media attached]"

    return ''


def _strip_leading_timestamp(s: str) -> str:
    """Remove leading '[Thu 2026-..]' style prefixes to keep feed clean."""
    s = (s or '').lstrip()
    if s.startswith('[') and ']' in s[:64]:
        s = s.split(']', 1)[1].lstrip()
    return s


def _topic_summary(s: str) -> str:
    """Heuristic, no-LLM summary for feed titles."""
    t = _strip_leading_timestamp(s)
    low = t.lower()

    if low.startswith('system:'):
        return 'System notice'

    if 'dashboard' in low or 'portal' in low:
        if 'timestamp' in low:
            return 'Dashboard: clean feed (remove timestamps)'
        if ('sys.json' in low) or ('telemetry' in low) or ('spark' in low) or ('sparkline' in low) or ('metrics' in low):
            return 'Dashboard: system monitors & graphs'
        if 'tiles' in low or 'history' in low:
            return 'Dashboard: agent tiles & history'
        return 'Dashboard: UX / live feed'

    if 'rapp' in low:
        return 'RAPP: research run'

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
                    thinking_snips.append(_short(t.strip(), 220))
            elif b.get('type') == 'text':
                txt = b.get('text')
                if isinstance(txt, str) and txt.strip():
                    texts.append(txt.strip())
        response_text = '\n'.join(texts).strip()

    return (response_text, tool_calls, thinking_snips)


def _parse_cognitive_log(text: str) -> list[tuple[str, str]]:
    """Parse an explicitly-authored cognitive footer from assistant text.

    Supported headers:
      Cognitive log
      Journal

    Supported bullet formats:
      - Thought: ...
      - Idea: ...
      - Plan: ...
      - Reflection: ...
      - Decision: ...
      - Risk: ...
      - Insight: ...

    IMPORTANT: We ONLY emit these if the assistant explicitly writes them.
    This keeps telemetry grounded and avoids inferred "mind-reading".
    """
    if not isinstance(text, str) or not text.strip():
        return []

    lines = [ln.rstrip() for ln in text.splitlines()]

    # Find header
    start = None
    for i, ln in enumerate(lines):
        head = (ln or '').strip().lower()
        if head in ("cognitive log", "cognitive-log", "cognitive_log", "journal", "journal log", "journal-log"):
            start = i + 1
            break
    if start is None:
        return []

    out: list[tuple[str, str]] = []
    allowed = {"thought", "idea", "plan", "reflection", "decision", "risk", "insight", "highlight"}

    for ln in lines[start:start + 40]:
        raw = (ln or '').strip()
        if not raw:
            if out:
                break
            continue
        if not raw.startswith('-'):
            if out:
                break
            continue

        item = raw.lstrip('-').strip()
        if ':' not in item:
            continue
        k, v = item.split(':', 1)
        typ = k.strip().lower()
        content = v.strip()

        if typ not in allowed:
            continue

        # Drop placeholders / empty-ish values
        if not content:
            continue
        if content.strip().lower() in ("-", "--", "—", "…", "n/a", "na"):
            continue
        if len(content.strip()) < 8:
            continue

        # guardrails against code-ish content
        if '`' in content or '()' in content or content.strip().startswith('_'):
            continue

        out.append((typ, _short(content, 420)))
        if len(out) >= 12:
            break

    return out


def _derive_journal_from_summary(text: str, user_request: str) -> list[tuple[str, str]]:
    """Best-effort *grounded* journal derivation for automated runs.

    Strict mode normally requires an explicit Journal/Cognitive log footer.
    For scheduled runs (RAPP/TAR/dashboard review) we still want cognitive entries even if
    the model forgot the Journal footer.

    Policy:
    - ONLY derive from *explicit* statements in the assistant text.
    - No invented emotions, no claims about user reactions.
    - Keep it short.
    """
    if not isinstance(text, str) or not text.strip():
        return []

    low = text.lower()
    req_low = (user_request or '').lower()

    # Only attempt on clearly-automated prompts
    automated = ('[cron:' in req_low) or req_low.startswith('tar task') or req_low.startswith('research task')
    if not automated:
        return []

    out: list[tuple[str, str]] = []

    # TAR summary parsing (most structured)
    if 'tar summary' in low:
        import re

        m = re.search(r"\*\*paper selected:\*\*\s*(.+)", text, flags=re.I)
        if m:
            out.append(('thought', _short(f"TAR ran: {m.group(1).strip()}", 420)))

        # Key insights (take up to 2)
        if 'key insights extracted' in low:
            # capture numbered list lines after the header
            block = text.split('**Key insights extracted:**', 1)[1] if '**Key insights extracted:**' in text else ''
            for ln in block.splitlines():
                ln = ln.strip()
                if not ln or not ln[0].isdigit():
                    if out and len(out) >= 3:
                        break
                    continue
                # "1. **X** - Y" -> take the Y-ish part
                ln = re.sub(r"^\d+\.\s*", '', ln)
                ln = re.sub(r"\*\*(.*?)\*\*", r"\1", ln)
                out.append(('thought', _short(ln, 420)))
                if sum(1 for t,_ in out if t=='thought') >= 3:
                    break

        # Decision from Pitch line
        m = re.search(r"\*\*pitch:\*\*\s*(.+)", text, flags=re.I)
        if m:
            out.append(('decision', _short(m.group(1).strip(), 420)))

        # Plan from suggested dashboard changes
        if '**Dashboard changes suggested:**' in text:
            block = text.split('**Dashboard changes suggested:**', 1)[1]
            for ln in block.splitlines():
                ln = ln.strip()
                if ln.startswith('- '):
                    out.append(('plan', _short(ln[2:].strip(), 420)))
                    break

        # Risk: novelty / repetition (only if hinted by the text)
        if 'deeper insights needed' in low:
            out.append(('risk', _short('Early-stage note: deeper stages still needed before pitching/acting.', 420)))

    # RAPP-style parsing (less structured)
    elif 'rapp' in low or 'research task' in low:
        out.append(('thought', _short('Automated research run completed; see activity detail for sources and changes.', 420)))

    # Cap to a small number
    return out[:6]


def _worklog_from_tool_calls(tool_calls: list[dict]) -> list[str]:
    """Derive a small set of human-readable worklog lines from tool calls.

    This is NOT cognition. It's an audit/worklog stream.
    Keep it high-signal and capped.
    """
    out: list[str] = []
    if not tool_calls:
        return out

    for tc in tool_calls:
        name = (tc.get('name') or '').strip()
        args = tc.get('arguments') or {}
        if name != 'exec':
            continue
        cmd = str(args.get('command') or '')
        one = ' '.join(cmd.split())
        low = one.lower()

        if 'git commit' in low:
            msg = None
            if ' -m ' in one:
                try:
                    msg = one.split(' -m ', 1)[1].strip().strip('"').strip("'")
                except Exception:
                    msg = None
            out.append('Git: commit' + (f" — {msg}" if msg else ''))
        elif 'git push' in low:
            out.append('Git: push')
        elif 'systemctl restart' in low:
            out.append('Service: restarted')
        elif 'systemctl status' in low:
            out.append('Service: status checked')

        if len(out) >= 3:
            break

    if len(out) < 3:
        for tc in tool_calls:
            name = (tc.get('name') or '').strip()
            args = tc.get('arguments') or {}
            if name in ('edit', 'write'):
                p = args.get('path') or args.get('file_path')
                if p:
                    out.append(f"File updated: {p}")
                    break

    dedup = []
    seen = set()
    for x in out:
        if x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup[:3]


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

    def add_user(self, ts_iso: str, text: str):
        self.reset()
        self.user_ts = ts_iso
        self.user_text = (text or '').strip()

    def add_tool_call(self, name: str, args: dict):
        self.tool_calls.append({'name': name, 'arguments': args or {}})

    def add_tool_result(self, tool_name: str, aggregated: str):
        out = (aggregated or '').strip()
        if not out:
            return

        low = out.lower()
        keep = any(k in low for k in ['error', 'failed', 'refused', 'traceback', 'exception'])
        keep = keep or any(k in out for k in ['Started ', 'Stopped ', 'Active: ', 'LISTEN ', 'Connected', 'Disconnected'])

        if not keep:
            return

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
        self.thinking.extend(snippets or [])

    def add_response(self, text: str):
        if text:
            self.response_text = text

    def build_events(self) -> list[tuple[str, str, str]]:
        user_clean = _strip_leading_timestamp((self.user_text or '').strip())
        if not user_clean:
            user_clean = "[no text — possibly media-only message]"
        topic = _topic_summary(user_clean)
        summary = topic or "Activity"

        lines: list[str] = []

        lines.append("Request")
        lines.append("- " + _short(user_clean, 1600))

        if self.tool_calls:
            lines.append("")
            lines.append("Actions")
            tool_names = [tc.get('name') for tc in self.tool_calls if tc.get('name')]
            uniq = list(dict.fromkeys(tool_names))
            if uniq:
                lines.append(f"- Tools used: {', '.join(uniq[:6])}{'…' if len(uniq) > 6 else ''}")

            seen = set()
            for tc in self.tool_calls:
                name = tc.get('name')
                if not name or name in seen:
                    continue
                seen.add(name)
                _, did = _tool_purpose(name, tc.get('arguments') or {})
                lines.append(f"- {name}: {did}")
                if len(seen) >= 4:
                    break

        if self.tool_results:
            kept = [tr for tr in self.tool_results if tr.get('out')]
            if kept:
                lines.append("")
                lines.append("Notable outputs")
                for tr in kept[:3]:
                    lines.append(f"- {tr['out']}")

        highlights: list[str] = []
        cog: list[tuple[str, str]] = []
        if self.response_text:
            lines.append("")
            lines.append("Response")
            import re
            rt = re.sub(r"```.*?```", "[code omitted]", self.response_text or "", flags=re.S)

            cog = _parse_cognitive_log(rt)
            if not cog:
                cog = _derive_journal_from_summary(rt, user_clean)

            rt_lines = [ln.strip() for ln in (rt or '').splitlines() if ln.strip()]
            allow_prefixes = (
                'fixed', 'added', 'changed', 'deployed', 'committed', 'pushed', 'restarted',
                'result', 'root cause', 'next', 'note', 'risk', 'decision'
            )
            for ln in rt_lines[:60]:
                if not ln.startswith('- '):
                    continue
                item = ln[2:].strip()
                low = item.lower()
                if '`' in item:
                    continue
                if '(' in item and ')' in item and any(ch.isalnum() for ch in item.split('(')[0]):
                    continue
                if item.startswith('_') or '()' in item or item.count('_') >= 2:
                    continue
                if not any(low.startswith(p) for p in allow_prefixes):
                    continue
                highlights.append(_short(item, 140))
                if len(highlights) >= 3:
                    break

            flat = ' '.join(rt.split())
            parts = re.split(r"(?<=[.!?])\s+", flat)
            short = ' '.join(parts[:2]).strip() if parts else flat
            lines.append("- " + _short(short, 700))

        if highlights:
            lines.append("")
            lines.append("Highlights")
            for h in highlights[:3]:
                lines.append(f"- {h}")

        detail_text = "\n".join(lines).strip()

        events: list[tuple[str, str, str]] = []

        # STRICT: do NOT infer cognition.
        for (typ, content) in (cog or [])[:12]:
            events.append((typ, content, f"Journal\n- {typ}: {content}"))

        # Worklog (derived; separate from cognition)
        for wl in _worklog_from_tool_calls(self.tool_calls)[:3]:
            events.append(('worklog', wl, "Worklog\n- " + wl))

        # Full drill-down (History)
        events.append(('activity', summary, detail_text))

        return events


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
            ACC.add_thinking(thinking_snips)

        if resp_text:
            ACC.add_response(resp_text)
            return ACC.build_events()
        return None

    if role == 'toolResult':
        tool_name = msg.get('toolName')
        details = msg.get('details')
        agg = ''
        if isinstance(details, dict):
            agg = details.get('aggregated') or ''
        if tool_name and agg:
            ACC.add_tool_result(tool_name, agg)
        return None

    return None


def _load_tailer_state(state_path: Path) -> dict:
    """Load state. Backward compatible with older single-file state."""
    try:
        if state_path.exists():
            st = json.loads(state_path.read_text())
            if isinstance(st, dict) and 'files' in st and isinstance(st['files'], dict):
                return st
            # Back-compat
            lf = st.get('last_file') if isinstance(st, dict) else None
            lp = st.get('last_pos') if isinstance(st, dict) else 0
            if lf:
                return {"files": {str(lf): int(lp or 0)}}
    except Exception:
        pass
    return {"files": {}}


def _save_tailer_state(state_path: Path, files: dict[str, int]):
    try:
        state_path.write_text(json.dumps({
            "files": {k: int(v) for k, v in (files or {}).items()},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2) + "\n")
    except Exception:
        pass


def _iter_session_files(sessions_arg: str | None, sessions_glob: str | None) -> list[Path]:
    """Return candidate session jsonl files."""
    files: list[Path] = []

    if sessions_glob:
        for d in sorted(Path('/').glob(sessions_glob.lstrip('/'))):
            if d.is_dir():
                files.extend(sorted(d.glob('*.jsonl')))

    if sessions_arg:
        d = Path(sessions_arg)
        if d.is_dir():
            files.extend(sorted(d.glob('*.jsonl')))

    # Dedup
    uniq = {}
    for p in files:
        uniq[str(p)] = p

    out = list(uniq.values())
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    # Only keep reasonably recent files to avoid scanning ancient history.
    now = time.time()
    recent = [p for p in out if (now - p.stat().st_mtime) < (24 * 3600)]
    return recent[:30]


def _tail_new_lines(path: Path, start_pos: int, max_lines: int = 400):
    with path.open('r', encoding='utf-8', errors='ignore') as f:
        f.seek(start_pos)
        n = 0
        while True:
            line = f.readline()
            if not line:
                break
            yield line
            n += 1
            if n >= max_lines:
                break


def _detect_agent_from_session(path: Path) -> str:
    """Detect agent name from session file.
    
    Looks at the session filename and content to determine which agent
    this session belongs to. Returns 'sol' as default.
    """
    fname = path.name.lower()
    
    # Check filename for known subagent patterns
    # Sessions created via sessions_spawn have labels embedded in session keys
    # We scan the first few lines to find user prompts that identify the agent
    
    try:
        with path.open('r', encoding='utf-8', errors='ignore') as f:
            for i, line in enumerate(f):
                if i > 20:  # Only check first 20 lines
                    break
                try:
                    obj = json.loads(line)
                    msg = obj.get('message')
                    if not msg:
                        continue
                    content = msg.get('content')
                    
                    # Handle content as string or list
                    if isinstance(content, str):
                        text_to_check = content
                    elif isinstance(content, list):
                        # Extract text from list blocks
                        texts = []
                        for block in content:
                            if isinstance(block, dict) and block.get('type') == 'text':
                                texts.append(block.get('text', ''))
                        text_to_check = ' '.join(texts)
                    else:
                        continue
                    
                    low = text_to_check.lower()
                    if 'portal-architect' in low:
                        return 'portal-architect'
                    if 'code-agent' in low or 'code agent' in low:
                        return 'code'
                    if 'planner' in low and 'agent' in low:
                        return 'planner'
                    if 'reviewer' in low and 'agent' in low:
                        return 'reviewer'
                    if 'researcher' in low and 'agent' in low:
                        return 'researcher'
                except Exception:
                    continue
    except Exception:
        pass
    
    # Default to sol
    return 'sol'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dashboard', required=True)
    ap.add_argument('--sessions', default=None, help='Single sessions dir (backward compatible)')
    ap.add_argument('--sessions-glob', default='/root/.openclaw/agents/*/sessions', help='Glob of sessions dirs (default: all agents)')
    ap.add_argument('--poll-ms', type=int, default=500)
    ap.add_argument('--state', default=str(Path(__file__).parent / 'tailer_state.json'))
    args = ap.parse_args()

    dashboard_path = Path(args.dashboard)
    state_path = Path(args.state)

    st = _load_tailer_state(state_path)
    pos_map: dict[str, int] = dict(st.get('files') or {})

    while True:
        files = _iter_session_files(args.sessions, args.sessions_glob)

        # Cache agent detection per file (don't re-scan on every poll)
        agent_cache: dict[str, str] = {}

        for fpath in files:
            key = str(fpath)
            last_pos = int(pos_map.get(key, 0))

            # Detect agent for this session (cached)
            if key not in agent_cache:
                agent_cache[key] = _detect_agent_from_session(fpath)
            agent_name = agent_cache[key]

            # If file shrank (rotated), reset
            try:
                size = fpath.stat().st_size
                if last_pos > size:
                    last_pos = 0
            except Exception:
                continue

            changed = False
            for line in _tail_new_lines(fpath, last_pos, max_lines=500):
                # Position in bytes; approximate by encoded length.
                last_pos += len(line.encode('utf-8', errors='ignore'))
                changed = True

                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                ev = event_summary(obj)
                if ev:
                    d = load_dashboard(dashboard_path)
                    if isinstance(ev, list):
                        for (typ, summary, detail_text) in ev:
                            append_sol(d, typ, summary, detail_text=detail_text, agent=agent_name)
                    else:
                        typ, summary, detail_text = ev
                        append_sol(d, typ, summary, detail_text=detail_text, agent=agent_name)
                    save_dashboard(dashboard_path, d)

            if changed:
                pos_map[key] = last_pos

        _save_tailer_state(state_path, pos_map)
        time.sleep(args.poll_ms / 1000)


if __name__ == '__main__':
    main()
