#!/usr/bin/env python3
"""
Agent Framework - Phase Manager
Handles self-prompting and phase progression
Version: 1.0.0
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import yaml

PHASE_FILE = Path(__file__).parent / "phase_state.json"

class PhaseManager:
    """Manages implementation phases with self-prompting"""
    
    PHASES = {
        1: {
            'name': 'Core Framework',
            'description': 'LangGraph setup, config, logging, rate limiting',
            'status': 'complete',
            'completed': '2026-02-18T13:00',
            'next': 'Implement base agent classes'
        },
        2: {
            'name': 'Base Agents',
            'description': 'Search, Verify, Summarize agents with rate limiting',
            'status': 'in_progress',
            'started': '2026-02-18T13:55',
            'tasks': [
                'Create agent base classes',
                'Implement Search Agent',
                'Implement Verify Agent', 
                'Implement Summarize Agent',
                'Test agent communication'
            ],
            'next': 'Add security layer'
        },
        3: {
            'name': 'Security Layer',
            'description': 'Input validation, output sanitization, goal-lock',
            'status': 'pending',
            'next': 'Add memory management'
        },
        4: {
            'name': 'Memory Management',
            'description': 'Encrypted memory, history, state persistence',
            'status': 'pending',
            'next': 'Create OpenClaw integration'
        },
        5: {
            'name': 'OpenClaw Integration',
            'description': 'Tool interface for calling framework',
            'status': 'pending',
            'next': 'Add self-improvement loops'
        },
        6: {
            'name': 'Self-Improvement',
            'description': 'Reflection, learning, iteration',
            'status': 'pending',
            'next': None
        }
    }
    
    def __init__(self):
        self.load_state()
    
    def load_state(self):
        if PHASE_FILE.exists():
            with open(PHASE_FILE) as f:
                self.state = json.load(f)
        else:
            self.state = {'current_phase': 1, 'history': []}
    
    def save_state(self):
        with open(PHASE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def get_current_phase(self) -> dict:
        phase_num = self.state.get('current_phase', 1)
        return self.PHASES.get(phase_num, {})
    
    def get_next_task(self) -> str:
        phase = self.get_current_phase()
        return phase.get('next', 'Continue implementation')
    
    def complete_phase(self, notes: str = ''):
        """Mark current phase complete and advance"""
        phase_num = self.state['current_phase']
        
        if phase_num in self.PHASES:
            self.PHASES[phase_num]['status'] = 'complete'
            self.PHASES[phase_num]['completed'] = datetime.utcnow().isoformat()
        
        # Add to history
        self.state['history'].append({
            'phase': phase_num,
            'completed': datetime.utcnow().isoformat(),
            'notes': notes
        })
        
        # Advance to next phase
        next_phase = phase_num + 1
        if next_phase in self.PHASES:
            self.state['current_phase'] = next_phase
            self.PHASES[next_phase]['status'] = 'in_progress'
            self.PHASES[next_phase]['started'] = datetime.utcnow().isoformat()
        
        self.save_state()
    
    def get_status(self) -> dict:
        return {
            'current_phase': self.state['current_phase'],
            'phase_name': self.get_current_phase().get('name', 'Unknown'),
            'phase_description': self.get_current_phase().get('description', ''),
            'status': self.get_current_phase().get('status', 'unknown'),
            'phases': self.PHASES,
            'history': self.state['history']
        }
    
    def generate_next_prompt(self) -> str:
        """Generate a self-prompt for continuing work"""
        phase = self.get_current_phase()
        phase_num = self.state['current_phase']
        
        prompts = {
            2: """Continue Phase 2 - Base Agents:
1. Create /root/.openclaw/workspace/agent-framework/agents/base.py with Agent base class
2. Implement Search Agent in /root/.openclaw/workspace/agent-framework/agents/search.py
3. Test: python3 cli.py register --name search --role researcher --system-prompt "You search for papers"
4. Report status""",
            
            3: """Continue Phase 3 - Security Layer:
1. Review core.py SecurityLayer class
2. Add input validation rules
3. Add output sanitization
4. Test with sample inputs
5. Report status""",
            
            4: """Continue Phase 4 - Memory Management:
1. Review MemoryManager in core.py
2. Add conversation history tracking
3. Add agent memory persistence
4. Test memory save/load
5. Report status""",
            
            5: """Continue Phase 5 - OpenClaw Integration:
1. Create agent_framework.py tool wrapper
2. Add to AGENTS.md
3. Test calling from main session
4. Report status""",
            
            6: """Continue Phase 6 - Self-Improvement:
1. Add reflection prompts to framework
2. Create self-review cron job
3. Test improvement cycle
4. Final report"""
        }
        
        return prompts.get(phase_num, "Continue implementation. Report status.")

# Global instance
_phase_manager: PhaseManager = None

def get_phase_manager() -> PhaseManager:
    global _phase_manager
    if _phase_manager is None:
        _phase_manager = PhaseManager()
    return _phase_manager

if __name__ == "__main__":
    pm = get_phase_manager()
    print(json.dumps(pm.get_status(), indent=2))
