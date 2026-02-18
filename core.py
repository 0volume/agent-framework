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

class MemoryManager:
    """Encrypted agent memory management"""
    
    def __init__(self, memory_dir: Path, config: Dict):
        self.memory_dir = memory_dir
        memory_dir.mkdir(parents=True, exist_ok=True)
        self.encrypted = config.get('memory', {}).get('encrypted', True)
        self.max_history = config.get('memory', {}).get('max_history', 100)
        
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
