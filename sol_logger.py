#!/usr/bin/env python3
"""
Sol Activity Logger - Pushes Sol's activity to dashboard in real-time
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import os

DASHBOARD_DATA = Path(__file__).parent / "dashboard_data.json"

def log_activity(activity_type: str, content: str, details: str = None):
    """Log Sol's activity to dashboard"""
    
    # Load current data
    data = {}
    if DASHBOARD_DATA.exists():
        with open(DASHBOARD_DATA) as f:
            data = json.load(f)
    
    if 'agents' not in data:
        data['agents'] = {}
    if 'sol' not in data['agents']:
        data['agents']['sol'] = []
    
    # Add new entry
    entry = {
        'type': activity_type,
        'content': content[:300],
        'timestamp': datetime.now().strftime("%H:%M:%S"),
        'full_timestamp': datetime.now().isoformat()
    }
    
    if details:
        entry['details'] = details[:200]
    
    data['agents']['sol'].append(entry)
    
    # Keep last 100 entries
    data['agents']['sol'] = data['agents']['sol'][-100:]
    
    data['last_activity'] = datetime.now().isoformat()
    
    with open(DASHBOARD_DATA, 'w') as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    if len(sys.argv) > 2:
        log_activity(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print("Usage: python3 sol_logger.py <type> <content> [details]")
