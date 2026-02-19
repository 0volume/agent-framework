#!/usr/bin/env python3
"""
Agent Framework - Dashboard Data Manager
Handles feeding data into the dashboard from various sources.
"""

import json
from pathlib import Path
from datetime import datetime
import os

DASHBOARD_DATA = Path(__file__).parent / "dashboard_data.json"
MEMORY_DIR = Path("/root/.openclaw/workspace/memory")
THOUGHT_LOG = Path(__file__).parent / "thought-log.md"

def load_dashboard_data() -> dict:
    """Load current dashboard data"""
    if DASHBOARD_DATA.exists():
        with open(DASHBOARD_DATA) as f:
            return json.load(f)
    return {
        "rate_limits": {"tavily": {"used": 0, "limit": 5, "remaining": 5}, "llm": {"used": 0, "limit": 20, "remaining": 20}},
        "agents": {"search": [], "verify": [], "summarize": [], "security": []},
        "thoughts": [],
        "memories": [],
        "improvements": [],
        "system": {"phase": "6/6 complete", "cron_jobs": "6"}
    }

def save_dashboard_data(data: dict):
    """Save dashboard data"""
    data["last_update"] = datetime.now().isoformat()
    with open(DASHBOARD_DATA, 'w') as f:
        json.dump(data, f, indent=2)

def add_thought(content: str, thought_type: str = "insight"):
    """Add a thought to the dashboard (append-only, non-destructive).

    Note: the live dashboard tailer is the primary source of thoughts.
    This helper should never truncate or overwrite existing streams.
    """
    data = load_dashboard_data()

    thought = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "type": thought_type,
        "content": content[:500],
        "detail_text": content[:2000],
    }

    data.setdefault("thoughts", [])
    data["thoughts"].append(thought)
    # Keep a generous window; avoid wiping useful history.
    data["thoughts"] = data["thoughts"][-800:]

    save_dashboard_data(data)

def add_memory(title: str, content: str, category: str = "general"):
    """Add a memory to the dashboard"""
    data = load_dashboard_data()
    
    memory = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "title": title[:100],
        "content": content[:300],
        "preview": content[:150] + "..." if len(content) > 150 else content,
        "category": category
    }
    
    data["memories"] = data.get("memories", [])
    data["memories"].append(memory)
    data["memories"] = data["memories"][-10:]  # Keep last 10
    
    save_dashboard_data(data)

def add_improvement(title: str, content: str):
    """Add an improvement to the dashboard (append-only, non-destructive)."""
    data = load_dashboard_data()

    improvement = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "title": title[:100],
        "content": content[:300],
        "detail_text": content[:2000],
    }

    data.setdefault("improvements", [])
    data["improvements"].append(improvement)
    data["improvements"] = data["improvements"][-300:]

    save_dashboard_data(data)

def sync_memories():
    """Sync memory headings from memory/YYYY-MM-DD.md into dashboard_data.json.

    Non-destructive: only appends missing items; keeps a reasonable window.
    """
    data = load_dashboard_data()

    today = datetime.now().strftime("%Y-%m-%d")
    memory_file = MEMORY_DIR / f"{today}.md"

    if not memory_file.exists():
        return

    content = memory_file.read_text()
    lines = content.split('\n')
    key_points = [l.replace('##', '').strip() for l in lines if l.startswith('##')]
    if not key_points:
        return

    data.setdefault('memories', [])
    existing_titles = {m.get('title') for m in data['memories'] if isinstance(m, dict)}

    for point in key_points[:10]:
        if point in existing_titles:
            continue
        data['memories'].append({
            'date': today,
            'title': point[:100],
            'preview': point[:150],
            'category': 'daily',
            'content': point[:300],
        })

    data['memories'] = data['memories'][-200:]
    save_dashboard_data(data)

def add_thought_from_log():
    """Add recent thought from thought-log.md"""
    data = load_dashboard_data()
    
    if THOUGHT_LOG.exists():
        with open(THOUGHT_LOG) as f:
            content = f.read()
        
        # Get last thought (between ## TH-XXX and next ##)
        import re
        thoughts = re.findall(r'## TH-\d+:.*?\n.*?\*\*Insight:\*\* (.*?)\n', content, re.DOTALL)
        
        if thoughts:
            last_thought = thoughts[-1][:200]
            data["thoughts"] = data.get("thoughts", [])
            
            # Check if already added
            existing = [t for t in data["thoughts"] if last_thought in t.get("content", "")]
            if not existing:
                data["thoughts"].append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "type": "reflection",
                    "content": last_thought
                })
                data["thoughts"] = data["thoughts"][-20:]
                save_dashboard_data(data)

if __name__ == "__main__":
    # Non-destructive sync only (do not inject sample/test entries)
    sync_memories()
    add_thought_from_log()
    print("Dashboard data synced")
