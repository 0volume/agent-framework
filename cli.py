#!/usr/bin/env python3
"""
Agent Framework - CLI Interface
Version: 1.0.1
Purpose: Command-line interface for managing agents
"""

import json
import sys
import argparse
from pathlib import Path

# Add parent to path
sys_path = str(Path(__file__).parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from core import get_framework, AgentStatus
from agents.base import BaseAgent, ResearchAgent, VerifyAgent, SummarizeAgent, SecurityMonitorAgent
import yaml

AGENTS_DIR = Path(__file__).parent / "agents"

def load_agent_yaml(name: str) -> dict:
    """Load agent definition from YAML"""
    yaml_file = AGENTS_DIR / f"{name}.yaml"
    if yaml_file.exists():
        with open(yaml_file) as f:
            return yaml.safe_load(f)
    return None

def cmd_status(args):
    """Show framework status"""
    fw = get_framework()
    print(json.dumps(fw.get_framework_status(), indent=2))

def cmd_list(args):
    """List all registered agents"""
    fw = get_framework()
    if not fw.agents:
        print("No agents registered. Use 'register' command.")
        return
    
    for name, agent in fw.agents.items():
        print(f"{name}: {agent['config'].role} [{agent['status'].value}]")

def cmd_register(args):
    """Register a new agent"""
    fw = get_framework()
    
    # Read system prompt from file if provided
    system_prompt = args.system_prompt
    if args.prompt_file:
        with open(args.prompt_file) as f:
            system_prompt = f.read()
    
    # Try to load from YAML definition
    agent_yaml = None
    if args.yaml_def:
        agent_yaml = load_agent_yaml(args.yaml_def)
    
    if agent_yaml and not args.system_prompt:
        # Use YAML definition
        system_prompt = agent_yaml.get('SYSTEM_PROMPT', '')
        role = agent_yaml.get('ROLE', args.role or 'unknown')
        tools = agent_yaml.get('TOOLS', [])
        max_tokens = agent_yaml.get('MAX_TOKENS', 4000)
        temp = agent_yaml.get('TEMPERATURE', 0.7)
    else:
        role = args.role or 'unknown'
        tools = args.tools.split(',') if args.tools else []
        max_tokens = args.max_tokens
        temp = args.temperature
    
    # Create agent config
    from core import AgentConfig
    config = AgentConfig(
        name=args.name,
        role=role,
        system_prompt=system_prompt,
        tools=tools,
        max_tokens=max_tokens,
        temperature=temp
    )
    
    fw.register_agent(config)
    
    # Save agent definition
    agent_def = {
        'NAME': args.name,
        'ROLE': role,
        'SYSTEM_PROMPT': system_prompt,
        'TOOLS': tools,
        'MAX_TOKENS': max_tokens,
        'TEMPERATURE': temp
    }
    
    def_file = AGENTS_DIR / f"{args.name}.yaml"
    with open(def_file, 'w') as f:
        yaml.dump(agent_def, f, default_flow_style=False)
    
    print(f"Registered: {args.name} ({role})")

def cmd_run(args):
    """Run an agent with input"""
    fw = get_framework()
    
    if args.name not in fw.agents:
        print(f"Agent '{args.name}' not found. Register first.")
        return
    
    agent = fw.agents[args.name]
    
    # In full implementation, this would call the LLM
    print(f"Running agent '{args.name}' with: {args.input[:50]}...")
    
    # Placeholder - would integrate with actual LLM
    result = {
        'agent': args.name,
        'input': args.input,
        'result': 'Agent execution placeholder - needs LLM integration'
    }
    
    print(json.dumps(result, indent=2))

def cmd_rate_limits(args):
    """Show rate limit status"""
    fw = get_framework()
    print(json.dumps(fw.get_rate_status(), indent=2))

def cmd_logs(args):
    """Show agent logs"""
    log_dir = Path(__file__).parent.parent / "logs"
    if args.agent:
        log_file = log_dir / f"{args.agent}.log"
        if log_file.exists():
            with open(log_file) as f:
                lines = f.readlines()
                for line in lines[-args.lines:]:
                    print(line.strip())
        else:
            print(f"No logs for agent '{args.agent}'")
    else:
        if log_dir.exists():
            print("Available logs:", [f.name for f in log_dir.glob("*.log")])
        else:
            print("No logs directory")

def cmd_phase(args):
    """Show phase status"""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from phase_manager import get_phase_manager
    pm = get_phase_manager()
    print(json.dumps(pm.get_status(), indent=2))

def cmd_complete_phase(args):
    """Mark current phase complete"""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from phase_manager import get_phase_manager
    pm = get_phase_manager()
    pm.complete_phase(args.notes or '')
    print(f"Phase complete. Next: {pm.get_current_phase().get('name', 'unknown')}")

def main():
    parser = argparse.ArgumentParser(description="Agent Framework CLI")
    subparsers = parser.add_subparsers()
    
    # status
    sp = subparsers.add_parser('status', help='Show framework status')
    sp.set_defaults(func=cmd_status)
    
    # list
    sp = subparsers.add_parser('list', help='List agents')
    sp.set_defaults(func=cmd_list)
    
    # register
    sp = subparsers.add_parser('register', help='Register an agent')
    sp.add_argument('--name', required=True, help='Agent name')
    sp.add_argument('--role', help='Agent role')
    sp.add_argument('--system-prompt', default='', help='System prompt')
    sp.add_argument('--prompt-file', help='File containing system prompt')
    sp.add_argument('--yaml-def', help='Load from YAML definition')
    sp.add_argument('--tools', default='', help='Comma-separated tools')
    sp.add_argument('--max-tokens', type=int, default=4000)
    sp.add_argument('--temperature', type=float, default=0.7)
    sp.set_defaults(func=cmd_register)
    
    # run
    sp = subparsers.add_parser('run', help='Run an agent')
    sp.add_argument('--name', required=True, help='Agent name')
    sp.add_argument('--input', required=True, help='Input to agent')
    sp.set_defaults(func=cmd_run)
    
    # rate-limits
    sp = subparsers.add_parser('rate-limits', help='Show rate limits')
    sp.set_defaults(func=cmd_rate_limits)
    
    # logs
    sp = subparsers.add_parser('logs', help='Show logs')
    sp.add_argument('--agent', help='Agent name')
    sp.add_argument('--lines', type=int, default=20)
    sp.set_defaults(func=cmd_logs)
    
    # phase
    sp = subparsers.add_parser('phase', help='Show phase status')
    sp.set_defaults(func=cmd_phase)
    
    # complete-phase
    sp = subparsers.add_parser('complete-phase', help='Complete current phase')
    sp.add_argument('--notes', help='Completion notes')
    sp.set_defaults(func=cmd_complete_phase)
    
    args = parser.parse_args()
    
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
