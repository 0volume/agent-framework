#!/usr/bin/env python3
"""
Agent Framework - Self-Improvement Module
Version: 1.0.0

Adds reflection and learning capabilities to agents.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class SelfImprover:
    """Agent self-improvement through reflection"""
    
    def __init__(self, agent_name: str, memory_dir: Path):
        self.agent_name = agent_name
        self.memory_dir = memory_dir
        self.reflections_dir = memory_dir / "reflections"
        self.reflections_dir.mkdir(parents=True, exist_ok=True)
        
        self.reflection_file = self.reflections_dir / f"{agent_name}_reflections.json"
        self.improvements_file = self.reflections_dir / f"{agent_name}_improvements.json"
        
        self.reflections = self._load_json(self.reflection_file, [])
        self.improvements = self._load_json(self.improvements_file, [])
    
    def _load_json(self, path: Path, default) -> List:
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except:
                pass
        return default
    
    def _save_json(self, path: Path, data: List):
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def reflect(self, task: str, result: str, feedback: str = None) -> Dict:
        """Reflect on a task execution"""
        
        reflection = {
            "timestamp": datetime.utcnow().isoformat(),
            "task": task[:200],
            "result_summary": result[:200],
            "feedback": feedback,
            "insights": [],
            "improvements_identified": []
        }
        
        # Simple reflection prompts (would use LLM in full version)
        if "error" in result.lower() or "fail" in result.lower():
            reflection["insights"].append("Task had errors - review approach")
            reflection["improvements_identified"].append("Add error handling")
        
        if len(result) < 50:
            reflection["insights"].append("Result was minimal - may need more context")
        
        # Store reflection
        self.reflections.append(reflection)
        
        # Keep only last 50
        self.reflections = self.reflections[-50:]
        
        self._save_json(self.reflection_file, self.reflections)
        
        return reflection
    
    def suggest_improvements(self) -> List[str]:
        """Analyze reflections and suggest improvements"""
        
        suggestions = []
        
        # Count error patterns
        error_count = sum(1 for r in self.reflections if "error" in r.get("result_summary", "").lower())
        
        if error_count > 5:
            suggestions.append("High error rate - review error handling")
        
        # Check for repeated tasks
        tasks = [r.get("task", "") for r in self.reflections[-10:]]
        if len(set(tasks)) < 3:
            suggestions.append("Repetitive tasks - consider batching")
        
        # Store improvements
        if suggestions:
            improvement = {
                "timestamp": datetime.utcnow().isoformat(),
                "suggestions": suggestions
            }
            self.improvements.append(improvement)
            self._save_json(self.improvements_file, self.improvements)
        
        return suggestions
    
    def get_stats(self) -> Dict:
        """Get improvement statistics"""
        return {
            "total_reflections": len(self.reflections),
            "total_improvements": len(self.improvements),
            "last_reflection": self.reflections[-1]["timestamp"] if self.reflections else None,
            "suggestions": self.suggest_improvements()
        }

class ReflectionCron:
    """Cron-like reflection scheduler"""
    
    def __init__(self, framework_dir: Path):
        self.framework_dir = framework_dir
        self.memory_dir = framework_dir / "memory"
        self.state_file = framework_dir / "reflection_state.json"
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return {
            "last_reflection": None,
            "reflection_interval_hours": 6,
            "enabled": True
        }
    
    def _save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def should_reflect(self) -> bool:
        """Check if it's time for reflection"""
        if not self.state.get("enabled"):
            return False
        
        last = self.state.get("last_reflection")
        if not last:
            return True
        
        last_time = datetime.fromisoformat(last)
        interval = timedelta(hours=self.state.get("reflection_interval_hours", 6))
        
        return datetime.utcnow() - last_time > interval
    
    def trigger_reflection(self, agent_name: str = None) -> Dict:
        """Trigger reflection for agent(s)"""
        
        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "agents_reflected": [],
            "insights": []
        }
        
        # Get all agent memories
        if agent_name:
            agents = [agent_name]
        else:
            agents = ["search", "verify", "summarize", "security"]
        
        for agent in agents:
            improver = SelfImprover(agent, self.memory_dir)
            stats = improver.get_stats()
            result["agents_reflected"].append(agent)
            result["insights"].extend(stats.get("suggestions", []))
        
        self.state["last_reflection"] = datetime.utcnow().isoformat()
        self._save_state()
        
        return result

def run_reflection(framework_dir: str = None):
    """CLI for running reflection"""
    if framework_dir is None:
        framework_dir = Path(__file__).parent
    
    cron = ReflectionCron(Path(framework_dir))
    
    if cron.should_reflect():
        result = cron.trigger_reflection()
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({"status": "no_reflection_needed", "next_in_hours": 6}, indent=2))

if __name__ == "__main__":
    run_reflection()
