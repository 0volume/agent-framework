#!/usr/bin/env python3
"""
Agent Framework - Terminal Formatter
Version: 1.0.0

Multi-agent output in readable block format (Option B)
"""

import json
from datetime import datetime
from typing import Dict, List, Optional

# ANSI Colors
class Colors:
    HEADER = '\033[95m'    # Purple
    BLUE = '\033[94m'      # Blue
    CYAN = '\033[96m'      # Cyan
    GREEN = '\033[92m'     # Green
    YELLOW = '\033[93m'    # Yellow
    RED = '\033[91m'       # Red
    ENDC = '\033[0m'       # End color
    BOLD = '\033[1m'       # Bold
    UNDERLINE = '\033[4m'   # Underline
    
    # Agent-specific colors
    SEARCH = CYAN
    VERIFY = YELLOW
    SUMMARIZE = GREEN
    SECURITY = RED
    DEFAULT = BLUE

# Agent to color mapping
AGENT_COLORS = {
    'search': Colors.SEARCH,
    'verify': Colors.VERIFY,
    'summarize': Colors.SUMMARIZE,
    'security': Colors.SECURITY,
}

def get_agent_color(agent_name: str) -> str:
    return AGENT_COLORS.get(agent_name, Colors.DEFAULT)

def format_header(agent_name: str, role: str = None) -> str:
    """Format agent header block"""
    color = get_agent_color(agent_name)
    role_str = f" ({role})" if role else ""
    
    header = f"""
{color}{'═' * 60}{Colors.ENDC}
{color}║ {agent_name.upper()}{role_str} {' ' * (50 - len(agent_name) - (len(role_str) if role else 0))}{color}║{Colors.ENDC}
{color}{'═' * 60}{Colors.ENDC}"""
    return header

def format_thought(agent_name: str, thought: str, timestamp: str = None) -> str:
    """Format agent thought/reasoning"""
    color = get_agent_color(agent_name)
    ts = timestamp or datetime.now().strftime("%H:%M")
    
    return f"{color}[{ts}] 💭 {thought}{Colors.ENDC}"

def format_action(agent_name: str, action: str, details: str = None, timestamp: str = None) -> str:
    """Format agent action"""
    color = get_agent_color(agent_name)
    ts = timestamp or datetime.now().strftime("%H:%M")
    
    if details:
        return f"{color}[{ts}] → {action}: {details}{Colors.ENDC}"
    return f"{color}[{ts}] → {action}{Colors.ENDC}"

def format_result(agent_name: str, result: str, timestamp: str = None) -> str:
    """Format agent result"""
    color = get_agent_color(agent_name)
    ts = timestamp or datetime.now().strftime("%H:%M")
    
    # Truncate long results
    if len(result) > 200:
        result = result[:200] + "..."
    
    return f"{color}[{ts}] ← {result}{Colors.ENDC}"

def format_status(agent_name: str, status: str, details: str = None) -> str:
    """Format status message"""
    color = get_agent_color(agent_name)
    
    status_icons = {
        'success': '✓',
        'error': '✗',
        'waiting': '⏳',
        'running': '▶',
        'done': '✓'
    }
    
    icon = status_icons.get(status.lower(), '•')
    
    if details:
        return f"{color}{icon} {status.upper()}: {details}{Colors.ENDC}"
    return f"{color}{icon} {status.upper()}{Colors.ENDC}"

def format_error(agent_name: str, error: str) -> str:
    """Format error message"""
    color = Colors.RED
    ts = datetime.now().strftime("%H:%M")
    
    return f"{color}[{ts}] ⚠ ERROR: {error}{Colors.ENDC}"

def format_divider() -> str:
    """Format divider line"""
    return f"{Colors.BLUE}{'─' * 60}{Colors.ENDC}"

def format_agent_block(agent_name: str, entries: List[Dict]) -> str:
    """Format complete agent block with all entries"""
    if not entries:
        return ""
    
    color = get_agent_color(agent_name)
    output = [format_header(agent_name)]
    
    for entry in entries:
        entry_type = entry.get('type', 'info')
        timestamp = entry.get('timestamp', '')[-5:]  # Just HH:MM
        
        if entry_type == 'thought':
            output.append(format_thought(agent_name, entry.get('content', ''), timestamp))
        elif entry_type == 'action':
            output.append(format_action(agent_name, entry.get('action', ''), entry.get('details'), timestamp))
        elif entry_type == 'result':
            output.append(format_result(agent_name, entry.get('content', ''), timestamp))
        elif entry_type == 'status':
            output.append(format_status(agent_name, entry.get('status', ''), entry.get('details')))
        elif entry_type == 'error':
            output.append(format_error(agent_name, entry.get('message', '')))
    
    return '\n'.join(output)

def format_multi_agent(agent_data: Dict[str, List[Dict]], plain_text: bool = False) -> str:
    """Format multiple agent blocks
    
    Args:
        agent_data: Dict of agent_name -> list of entries
        plain_text: If True, strip ANSI codes for copy-paste
    """
    blocks = []
    
    for agent_name, entries in agent_data.items():
        block = format_agent_block(agent_name, entries)
        if block:
            blocks.append(block)
    
    output = '\n\n'.join(blocks)
    
    # Strip ANSI codes if plain text requested
    if plain_text:
        import re
        ansi_pattern = re.compile(r'\x1b\[[0-9;]*m')
        output = ansi_pattern.sub('', output)
    
    return output

# Example usage
if __name__ == "__main__":
    # Demo output
    demo_data = {
        'search': [
            {'type': 'thought', 'timestamp': '2026-02-18T23:40:00', 'content': 'Analyzing request for AI agent papers on security'},
            {'type': 'action', 'timestamp': '2026-02-18T23:40:01', 'action': 'Query Tavily', 'details': 'agentic AI security papers 2026'},
            {'type': 'result', 'timestamp': '2026-02-18T23:40:02', 'content': 'Found 3 relevant papers'},
            {'type': 'status', 'timestamp': '2026-02-18T23:40:03', 'status': 'success', 'details': '3 papers found'}
        ],
        'verify': [
            {'type': 'thought', 'timestamp': '2026-02-18T23:40:02', 'content': 'Need to validate 3 URLs before passing to summarize'},
            {'type': 'action', 'timestamp': '2026-02-18T23:40:03', 'action': 'Check URLs', 'details': 'arxiv.org, github.com, cltc.berkeley.edu'},
            {'type': 'status', 'timestamp': '2026-02-18T23:40:04', 'status': 'success', 'details': 'All 3 URLs valid'}
        ]
    }
    
    print(format_multi_agent(demo_data))
