#!/usr/bin/env python3
"""
Agent Framework - Dashboard Server
Version: 1.0.0

Local web dashboard for monitoring agents.
Serves HTML + JSON data endpoint.
"""

import json
import http.server
import socketserver
import threading
from pathlib import Path
from datetime import datetime
from http.server import SimpleHTTPRequestHandler

# Local event store (SQLite)
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from db.events import append_event, query_events

PORT = 8766
DATA_FILE = Path(__file__).parent / "dashboard_data.json"


def get_sys_metrics():
    """Lightweight system metrics (no external deps)."""
    try:
        import os
        import shutil
        # Load averages
        with open('/proc/loadavg') as f:
            la = f.read().split()[:3]
        # Memory
        mem = {}
        with open('/proc/meminfo') as f:
            for line in f:
                k, v = line.split(':', 1)
                mem[k.strip()] = v.strip()
        # Disk (root)
        du = shutil.disk_usage('/')
        # Uptime
        with open('/proc/uptime') as f:
            up = float(f.read().split()[0])
        return {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'loadavg': {'1m': float(la[0]), '5m': float(la[1]), '15m': float(la[2])},
            'meminfo': {
                'MemTotal': mem.get('MemTotal'),
                'MemAvailable': mem.get('MemAvailable'),
                'SwapTotal': mem.get('SwapTotal'),
                'SwapFree': mem.get('SwapFree'),
            },
            'disk_root': {
                'total_bytes': du.total,
                'used_bytes': du.used,
                'free_bytes': du.free,
            },
            'uptime_seconds': up,
        }
    except Exception as e:
        return {'error': str(e), 'timestamp': datetime.utcnow().isoformat() + 'Z'}


# In-memory data store
dashboard_data = {
    "rate_limits": {
        "tavily": {"used": 0, "limit": 5, "remaining": 5},
        "llm": {"used": 0, "limit": 20, "remaining": 20}
    },
    "agents": {
        "search": [],
        "verify": [],
        "summarize": [],
        "security": []
    },
    "last_update": None
}

def load_data():
    """Load data from file"""
    global dashboard_data
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE) as f:
                dashboard_data = json.load(f)
        except:
            pass

def save_data():
    """Save data to file"""
    dashboard_data["last_update"] = datetime.now().isoformat()
    with open(DATA_FILE, 'w') as f:
        json.dump(dashboard_data, f, indent=2)

class DashboardHandler(SimpleHTTPRequestHandler):
    """Custom handler for dashboard"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).parent), **kwargs)
    
    def do_GET(self):
        # Strip query params for routing
        from urllib.parse import urlparse
        path = urlparse(self.path).path

        if path == '/sys.json':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.end_headers()
            self.wfile.write(json.dumps(get_sys_metrics()).encode())
        elif path == '/data.json':
            load_data()

            # Build a response object so we can filter legacy/junk in the live feed
            # without deleting history from SQLite.
            resp = dict(dashboard_data)

            def _is_legacy_junk(e: dict) -> bool:
                try:
                    typ = str(e.get('type') or '').lower().strip()
                    txt = (e.get('content') or e.get('summary') or '').strip()
                    low = txt.lower()
                except Exception:
                    return False

                # Old template-era / placeholder noise patterns
                if txt in ('…', '-', '--', '—'):
                    return True
                if low.startswith('intent:'):
                    return True
                if low.startswith('plan:') and typ == 'plan':
                    return True
                if low.startswith('highlights:'):
                    return True
                # Older "interpretation"-style cognitive spam (not a real journal)
                if low.startswith('d asked') and 'interpretation' in low:
                    return True
                if 'pre-compaction memory flush' in low:
                    return True
                if 'this data is useless' in low:
                    return True
                return False

            # Filter Sol live stream to be cognitive-only by default.
            # Worklog has its own tab; History remains full-fidelity via SQLite.
            try:
                sol = (resp.get('agents') or {}).get('sol') or []
                keep_types = {'thought','idea','plan','reflection','decision','risk','insight','highlight'}
                sol2 = [x for x in sol if str(x.get('type') or '').lower() in keep_types and not _is_legacy_junk(x)]
                resp.setdefault('agents', {})['sol'] = sol2
            except Exception:
                pass

            # Filter Thoughts tab payload similarly (strict cognitive view)
            try:
                th = resp.get('thoughts') or []
                resp['thoughts'] = [x for x in th if not _is_legacy_junk(x)]
            except Exception:
                pass

            # Include recent events for drill-down/history (DB-backed; unfiltered)
            try:
                resp['events'] = query_events(limit=300)
            except Exception as e:
                resp['events'] = [{'id': -1, 'ts': datetime.utcnow().isoformat()+'Z', 'agent': 'system', 'type': 'error', 'summary': 'events query failed', 'payload': {'error': str(e)}}]

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())
        elif path.endswith('.html'):
            # Disable caching for HTML to avoid stale JS/UI
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.end_headers()
            p = Path(__file__).parent / self.path.lstrip('/')
            if not p.exists():
                p = Path(__file__).parent / 'dashboard.html'
            self.wfile.write(p.read_bytes())
        elif path == '/api/update':
            # API for agents to update status
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        else:
            super().do_GET()
    
    def do_POST(self):
        # Strip query params for routing
        from urllib.parse import urlparse
        path = urlparse(self.path).path

        if path == '/api/agent':
            length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(length)
            try:
                data = json.loads(post_data)
                agent_name = data.get('agent', 'unknown')
                entry = data.get('entry', {})
                
                load_data()
                
                if agent_name in dashboard_data["agents"]:
                    dashboard_data["agents"][agent_name].append(entry)
                    # Keep last 200 entries per agent in JSON (DB is the real history)
                    dashboard_data["agents"][agent_name] = dashboard_data["agents"][agent_name][-200:]

                    # Also append to SQLite for durable history + verbose payload
                    try:
                        typ = entry.get('type', 'status')
                        summary = entry.get('content') or entry.get('details') or str(entry)[:200]
                        detail_text = entry.get('detail_text') or entry.get('details') or ''
                        append_event(agent=agent_name, typ=typ, summary=summary[:200], detail_text=detail_text[:2000], detail=entry)
                    except Exception:
                        pass

                    save_data()
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok"}).encode())
                else:
                    self.send_response(400)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Unknown agent"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress logging"""
        pass

def start_server():
    """Start the dashboard server"""
    load_data()

    # Avoid "Address already in use" on quick restarts (TIME_WAIT)
    socketserver.TCPServer.allow_reuse_address = True

    handler = DashboardHandler
    with socketserver.ThreadingTCPServer(("", PORT), handler) as httpd:
        print(f"Dashboard running at http://localhost:{PORT}/dashboard.html")
        print(f"Data endpoint: http://localhost:{PORT}/data.json")
        httpd.serve_forever()

def add_entry(agent: str, entry_type: str, content: str, details: str = None):
    """Add entry to agent (for testing)"""
    entry = {
        "type": entry_type,
        "content": content,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }
    if details:
        entry["details"] = details
    
    load_data()
    if agent in dashboard_data["agents"]:
        dashboard_data["agents"][agent].append(entry)
        dashboard_data["agents"][agent] = dashboard_data["agents"][agent][-50:]
    save_data()

if __name__ == "__main__":
    start_server()
