# Agent Framework

**Version:** 1.0.0
**Created:** 2026-02-18
**Purpose:** Secure multi-agent research system

## Architecture

```
agent-framework/
├── config.yaml         # Framework configuration
├── core.py             # Core framework classes
├── cli.py             # Command-line interface
├── phase_manager.py   # Phase progression & self-prompting
├── agents/            # Agent definitions
│   └── search_agent.yaml
├── logs/              # Agent execution logs
└── memory/            # Encrypted agent memory
```

## Current Phase

**Phase 2: Base Agents** (in progress)
- [ ] Create agent base classes
- [ ] Implement Search Agent
- [ ] Implement Verify Agent
- [ ] Implement Summarize Agent
- [ ] Test agent communication

## Security Features

- Rate limiting (per service + per agent)
- Input validation
- Output sanitization  
- Goal-lock (prevent drift)
- Encrypted memory
- Human-in-loop for high-cost actions

## Rate Limits

| Service | Limit | Window |
|---------|-------|--------|
| Tavily | 50 queries | 1 hour |
| LLM | 100k tokens | 1 hour |
| Per Agent | 50 calls | 1 hour |

## Usage

```bash
# Check status
python3 cli.py status

# List agents
python3 cli.py list

# Register agent
python3 cli.py register --name search --role researcher --system-prompt "You search"

# View logs
python3 cli.py logs --agent search --lines 20

# Check phase
python3 phase_manager.py
```

## Integration

This framework is designed to integrate with OpenClaw. Phase 5 will add the integration layer.

## Research

Based on:
- Paper #7: MAC-AMP (specialists beat generalists)
- Paper #21: 85% attack success rate (security imperative)
- Paper #22: Berkeley CLTC risk framework
- Paper #23: Multi-agent frameworks (CrewAI, LangGraph)
- Paper #24: Reflective workflows
