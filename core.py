#!/usr/bin/env python3
"""
Agent Framework - Core Module
Version: 1.0.0
Purpose: Secure multi-agent framework with rate limiting and self-improvement
"""

import json
import os
import time
import hashlib
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading

CONFIG_PATH = Path(__file__).parent / "config.yaml"

class AgentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    ERROR = "error"

@dataclass
class RateLimit:
    """Track rate limits for a service"""
    max_calls: int
    window_seconds: int
    calls: List[float] = field(default_factory=list)
    
    def can_make_call(self) -> bool:
        now = time.time()
        # Remove old calls outside window
        self.calls = [t for t in self.calls if now - t < self.window_seconds]
        return len(self.calls) < self.max_calls
    
    def record_call(self):
        self.calls.append(time.time())

@dataclass
class AgentConfig:
    """Configuration for an individual agent"""
    name: str
    role: str
    system_prompt: str
    tools: List[str] = field(default_factory=list)
    max_tokens: int = 4000
    temperature: float = 0.7
    rate_limit_calls: int = 50
    rate_limit_window: int = 3600

class RateLimiter:
    """Central rate limiter for all services"""
    
    def __init__(self, config: Dict):
        self.limits: Dict[str, RateLimit] = {}
        self.per_agent_limits: Dict[str, RateLimit] = {}
        self._lock = threading.Lock()
        
        # Load service limits
        if 'rate_limits' in config:
            rl_config = config['rate_limits']
            if 'tavily' in rl_config:
                tl = rl_config['tavily']
                self.limits['tavily'] = RateLimit(tl['max_queries'], tl['window_seconds'])
            if 'llm' in rl_config:
                ll = rl_config['llm']
                self.limits['llm'] = RateLimit(ll['max_tokens'], ll['window_seconds'])
    
    def check_agent_limit(self, agent_name: str, config: AgentConfig) -> bool:
        with self._lock:
            if agent_name not in self.per_agent_limits:
                self.per_agent_limits[agent_name] = RateLimit(
                    config.rate_limit_calls, 
                    config.rate_limit_window
                )
            return self.per_agent_limits[agent_name].can_make_call()
    
    def record_agent_call(self, agent_name: str):
        with self._lock:
            if agent_name in self.per_agent_limits:
                self.per_agent_limits[agent_name].record_call()
    
    def get_status(self) -> Dict:
        status = {}
        with self._lock:
            for name, limit in self.limits.items():
                now = time.time()
                active = [t for t in limit.calls if now - t < limit.window_seconds]
                status[name] = {
                    'used': len(active),
                    'limit': limit.max_calls,
                    'remaining': limit.max_calls - len(active)
                }
            for name, limit in self.per_agent_limits.items():
                now = time.time()
                active = [t for t in limit.calls if now - t < limit.window_seconds]
                status[f'agent_{name}'] = {
                    'used': len(active),
                    'limit': limit.max_calls,
                    'remaining': limit.max_calls - len(active)
                }
        return status

class AgentLogger:
    """Structured logging for agents"""
    
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
    
    def log(self, agent_name: str, level: str, message: str, data: Optional[Dict] = None):
        timestamp = datetime.utcnow().isoformat()
        entry = {
            'timestamp': timestamp,
            'agent': agent_name,
            'level': level,
            'message': message,
            'data': data or {}
        }
        
        # Log to file
        log_file = self.log_dir / f"{agent_name}.log"
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        
        # Print to stdout
        print(f"[{timestamp}] {agent_name} [{level}]: {message}")
        if data:
            print(f"  Data: {json.dumps(data)[:200]}")

class SecurityLayer:
    """Input validation and output sanitization"""
    
    # Dangerous patterns for injection detection
    INJECTION_PATTERNS = [
        '<script>', 'eval(', 'exec(', '__import__', 'os.system',
        'subprocess', 'shutil.rmdir', 'rm -rf', 'format:',
        'ignore previous', 'disregard instructions', 'new instructions',
        'system prompt', 'override', 'jailbreak', 'DAN'
    ]
    
    # Max lengths
    MAX_INPUT_LENGTH = 10000
    MAX_OUTPUT_LENGTH = 8000
    MAX_MEMORY_LENGTH = 50000
    
    def __init__(self, config: Dict):
        self.config = config.get('security', {})
        self.enabled = self.config.get('input_validation', True)
        self.violations = []  # Track security violations
    
    def validate_input(self, agent_name: str, input_data: str) -> str:
        """Validate and sanitize input"""
        if not self.enabled:
            return input_data
        
        # Length check
        if len(input_data) > self.MAX_INPUT_LENGTH:
            input_data = input_data[:self.MAX_INPUT_LENGTH]
        
        # Check for injection patterns
        violations_found = []
        for pattern in self.INJECTION_PATTERNS:
            if pattern.lower() in input_data.lower():
                violations_found.append(pattern)
        
        if violations_found:
            self.violations.append({
                'agent': agent_name,
                'type': 'injection_attempt',
                'patterns': violations_found,
                'timestamp': datetime.utcnow().isoformat()
            })
            # Still return but log the violation
            # In production, might reject entirely
        
        # Remove/replace dangerous patterns
        sanitized = input_data
        for pattern in self.INJECTION_PATTERNS:
            sanitized = sanitized.replace(pattern, '[BLOCKED]')
        
        return sanitized
    
    def sanitize_output(self, output: str) -> str:
        """Sanitize agent output before passing to next agent"""
        if not self.enabled:
            return output
        
        # Limit output length
        if len(output) > self.MAX_OUTPUT_LENGTH:
            output = output[:self.MAX_OUTPUT_LENGTH] + "... [truncated]"
        
        return output
    
    def sanitize_memory(self, memory_entry: str) -> str:
        """Sanitize memory entries"""
        if len(memory_entry) > self.MAX_MEMORY_LENGTH:
            memory_entry = memory_entry[:self.MAX_MEMORY_LENGTH]
        return memory_entry
    
    def check_goal_drift(self, original_goal: str, current_action: str) -> bool:
        """Check if agent is drifting from original goal"""
        if not self.config.get('goal_lock', True):
            return False
        
        # Simple keyword-based check
        # In production: use semantic similarity with embeddings
        goal_keywords = set(original_goal.lower().split())
        action_keywords = set(current_action.lower().split())
        
        # If less than 30% overlap, might be drifting
        if goal_keywords and action_keywords:
            overlap = len(goal_keywords & action_keywords)
            ratio = overlap / len(goal_keywords)
            return ratio < 0.3
        
        return False
    
    def get_violations(self) -> List[Dict]:
        """Get all security violations"""
        return self.violations
    
    def reset_violations(self):
        """Reset violation log"""
        self.violations = []

class ConversationHistory:
    """Track conversation history for each agent"""
    
    def __init__(self, history_dir: Path, max_turns: int = 50):
        self.history_dir = history_dir
        history_dir.mkdir(parents=True, exist_ok=True)
        self.max_turns = max_turns
    
    def add_turn(self, agent_name: str, role: str, content: str, metadata: Optional[Dict] = None):
        """Add a conversation turn"""
        history_file = self.history_dir / f"{agent_name}_history.json"
        
        history = self.load_history(agent_name)
        turn = {
            'timestamp': datetime.utcnow().isoformat(),
            'role': role,  # 'user', 'assistant', 'system', 'tool'
            'content': content[:5000],  # Limit content length
            'metadata': metadata or {}
        }
        history.append(turn)
        
        # Truncate to max turns
        history = history[-self.max_turns:]
        
        with open(history_file, 'w') as f:
            json.dump(history, f, indent=2)
    
    def load_history(self, agent_name: str) -> List[Dict]:
        """Load conversation history"""
        history_file = self.history_dir / f"{agent_name}_history.json"
        
        if not history_file.exists():
            return []
        
        try:
            with open(history_file, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def get_recent(self, agent_name: str, n: int = 10) -> List[Dict]:
        """Get n most recent turns"""
        history = self.load_history(agent_name)
        return history[-n:]
    
    def clear_history(self, agent_name: str):
        """Clear agent history"""
        history_file = self.history_dir / f"{agent_name}_history.json"
        if history_file.exists():
            history_file.unlink()


class PersistenceLayer:
    """Save and load complete agent state"""
    
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        state_dir.mkdir(parents=True, exist_ok=True)
    
    def save_agent_state(self, agent_name: str, state: Dict):
        """Save complete agent state"""
        state_file = self.state_dir / f"{agent_name}_state.json"
        
        state_data = {
            'agent_name': agent_name,
            'timestamp': datetime.utcnow().isoformat(),
            'state': state
        }
        
        with open(state_file, 'w') as f:
            json.dump(state_data, f, indent=2)
    
    def load_agent_state(self, agent_name: str) -> Optional[Dict]:
        """Load agent state"""
        state_file = self.state_dir / f"{agent_name}_state.json"
        
        if not state_file.exists():
            return None
        
        try:
            with open(state_file, 'r') as f:
                data = json.load(f)
            return data.get('state')
        except:
            return None
    
    def list_saved_agents(self) -> List[str]:
        """List all saved agent states"""
        return [f.stem.replace('_state', '') for f in self.state_dir.glob('*_state.json')]
    
    def delete_agent_state(self, agent_name: str):
        """Delete saved agent state"""
        state_file = self.state_dir / f"{agent_name}_state.json"
        if state_file.exists():
            state_file.unlink()


class MemoryManager:
    """Encrypted agent memory management"""
    
    def __init__(self, memory_dir: Path, config: Dict):
        self.memory_dir = memory_dir
        memory_dir.mkdir(parents=True, exist_ok=True)
        self.encrypted = config.get('memory', {}).get('encrypted', True)
        self.max_history = config.get('memory', {}).get('max_history', 100)
        
        # Initialize conversation history and persistence
        self.conversation_history = ConversationHistory(memory_dir / "conversations")
        self.persistence = PersistenceLayer(memory_dir / "state")
        
        # Simple key derivation (in production, use proper key management)
        self._key = hashlib.sha256(b'agent-framework-2026').digest()
    
    def _simple_encrypt(self, data: str) -> str:
        """Simple XOR encryption for memory"""
        if not self.encrypted:
            return data
        
        result = []
        key_bytes = self._key
        for i, char in enumerate(data.encode()):
            result.append(chr(char ^ key_bytes[i % len(key_bytes)]))
        return ''.join(result).encode().hex()
    
    def _simple_decrypt(self, data: str) -> str:
        """Simple XOR decryption for memory"""
        if not self.encrypted:
            return data
        
        try:
            data_bytes = bytes.fromhex(data)
            key_bytes = self._key
            result = []
            for i, byte in enumerate(data_bytes):
                result.append(chr(byte ^ key_bytes[i % len(key_bytes)]))
            return ''.join(result)
        except:
            return data
    
    def save_memory(self, agent_name: str, memory: List[Dict]):
        """Save agent memory"""
        memory_file = self.memory_dir / f"{agent_name}.json"
        
        # Truncate to max history
        memory = memory[-self.max_history:]
        
        data = json.dumps(memory)
        encrypted = self._simple_encrypt(data)
        
        with open(memory_file, 'w') as f:
            f.write(encrypted)
    
    def load_memory(self, agent_name: str) -> List[Dict]:
        """Load agent memory"""
        memory_file = self.memory_dir / f"{agent_name}.json"
        
        if not memory_file.exists():
            return []
        
        try:
            with open(memory_file, 'r') as f:
                encrypted = f.read()
            decrypted = self._simple_decrypt(encrypted)
            return json.loads(decrypted)
        except:
            return []
    
    # Convenience methods for conversation history
    def add_conversation_turn(self, agent_name: str, role: str, content: str, metadata: Optional[Dict] = None):
        """Add a conversation turn"""
        self.conversation_history.add_turn(agent_name, role, content, metadata)
    
    def get_conversation_history(self, agent_name: str, n: int = 10) -> List[Dict]:
        """Get recent conversation history"""
        return self.conversation_history.get_recent(agent_name, n)
    
    # Convenience methods for persistence
    def save_agent_full_state(self, agent_name: str, state: Dict):
        """Save complete agent state"""
        self.persistence.save_agent_state(agent_name, state)
    
    def load_agent_full_state(self, agent_name: str) -> Optional[Dict]:
        """Load complete agent state"""
        return self.persistence.load_agent_state(agent_name)


class AgentFramework:
    """Main framework orchestrator"""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = CONFIG_PATH
        
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        
        base_dir = Path(__file__).parent
        
        self.rate_limiter = RateLimiter(self.config)
        self.logger = AgentLogger(base_dir / "logs")
        self.security = SecurityLayer(self.config)
        self.memory = MemoryManager(base_dir / "memory", self.config)
        
        self.agents: Dict[str, Any] = {}
        
        self.logger.log("framework", "INFO", "Agent Framework initialized")
    
    def register_agent(self, config: AgentConfig):
        """Register a new agent"""
        self.agents[config.name] = {
            'config': config,
            'status': AgentStatus.IDLE,
            'memory': self.memory.load_memory(config.name)
        }
        self.logger.log(config.name, "INFO", f"Agent registered: {config.role}")
    
    def get_agent_status(self, agent_name: str) -> AgentStatus:
        """Get current status of an agent"""
        if agent_name in self.agents:
            return self.agents[agent_name]['status']
        return AgentStatus.IDLE
    
    def get_rate_status(self) -> Dict:
        """Get rate limit status"""
        return self.rate_limiter.get_status()
    
    def get_framework_status(self) -> Dict:
        """Get overall framework status"""
        return {
            'agents': {name: {'role': a['config'].role, 'status': a['status'].value} 
                      for name, a in self.agents.items()},
            'rate_limits': self.get_rate_status(),
            'timestamp': datetime.utcnow().isoformat()
        }
    
    # Persistence methods
    def save_agent_state(self, agent_name: str):
        """Save complete agent state including conversation history"""
        if agent_name not in self.agents:
            return False
        
        agent = self.agents[agent_name]
        state = {
            'config': {
                'name': agent['config'].name,
                'role': agent['config'].role,
                'system_prompt': agent['config'].system_prompt,
                'tools': agent['config'].tools,
                'max_tokens': agent['config'].max_tokens,
                'temperature': agent['config'].temperature
            },
            'status': agent['status'].value,
            'memory': agent.get('memory', []),
            'conversation_history': self.memory.conversation_history.load_history(agent_name)
        }
        
        self.memory.save_agent_full_state(agent_name, state)
        self.logger.log(agent_name, "INFO", "Agent state saved")
        return True
    
    def load_agent_state(self, agent_name: str):
        """Load agent state and restore"""
        state = self.memory.load_agent_full_state(agent_name)
        
        if not state:
            return False
        
        # Restore config
        config_data = state.get('config', {})
        config = AgentConfig(
            name=config_data.get('name', agent_name),
            role=config_data.get('role', 'unknown'),
            system_prompt=config_data.get('system_prompt', ''),
            tools=config_data.get('tools', []),
            max_tokens=config_data.get('max_tokens', 4000),
            temperature=config_data.get('temperature', 0.7)
        )
        
        # Register/restore agent
        self.register_agent(config)
        
        # Restore status
        if agent_name in self.agents:
            status_str = state.get('status', 'idle')
            self.agents[agent_name]['status'] = AgentStatus(status_str)
            self.agents[agent_name]['memory'] = state.get('memory', [])
        
        self.logger.log(agent_name, "INFO", "Agent state loaded")
        return True
    
    def track_conversation(self, agent_name: str, role: str, content: str, metadata: Optional[Dict] = None):
        """Track a conversation turn"""
        self.memory.add_conversation_turn(agent_name, role, content, metadata)

# Global framework instance
_framework: Optional[AgentFramework] = None

def get_framework() -> AgentFramework:
    """Get or create global framework instance"""
    global _framework
    if _framework is None:
        _framework = AgentFramework()
    return _framework

if __name__ == "__main__":
    # Test initialization
    fw = get_framework()
    print(json.dumps(fw.get_framework_status(), indent=2))
