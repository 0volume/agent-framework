#!/usr/bin/env python3
"""
Agent Framework - Search Agent
Version: 1.0.0
Purpose: Research agent for finding papers and information
"""

import json
import time
import os
from typing import Dict, List, Optional, Any

from .base import BaseAgent, AgentResult


class SearchAgent(BaseAgent):
    """Research agent for finding papers and information using Tavily"""
    
    def __init__(self, name: str = "search", role: str = "researcher", 
                 system_prompt: str = "", config=None):
        if not system_prompt:
            system_prompt = """You are a Research Search Agent. Your role is to find relevant 
papers and resources on AI agents and related topics.

Guidelines:
- Use Tavily API for searching (rate limited)
- Always verify URLs before returning
- Return structured results with title, URL, and summary
- Check rate limits before making calls
- Report your findings clearly"""
        
        super().__init__(name, role, system_prompt, config)
        self._init_tavily()
    
    def _init_tavily(self):
        """Initialize Tavily API client"""
        # Load Tavily key from environment or credentials file
        tavily_key = os.environ.get('TAVILY_API_KEY')
        
        if not tavily_key:
            creds_path = '/root/.openclaw/credentials/tavily.env'
            if os.path.exists(creds_path):
                with open(creds_path) as f:
                    for line in f:
                        if line.startswith('TAVILY_API_KEY='):
                            tavily_key = line.split('=', 1)[1].strip()
                            break
        
        self.tavily_key = tavily_key
        self.tavily_available = bool(tavily_key)
        
        if not self.tavily_available:
            self.logger.log(self.name, "WARNING", "Tavily API key not found")
    
    def execute(self, task: str, context: Optional[Dict] = None) -> AgentResult:
        """
        Execute search task using Tavily API
        
        Args:
            task: Search query string
            context: Optional context dict with max_results, etc.
        
        Returns:
            AgentResult with search results
        """
        start_time = time.time()
        context = context or {}
        
        max_results = context.get('max_results', 5)
        
        if not self.tavily_available:
            return AgentResult(
                success=False,
                error="Tavily API key not configured",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        
        try:
            # Make Tavily API request
            import urllib.request
            import urllib.parse
            
            url = "https://api.tavily.com/search"
            data = json.dumps({
                "api_key": self.tavily_key,
                "query": task,
                "max_results": max_results
            }).encode('utf-8')
            
            req = urllib.request.Request(
                url,
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                results = json.loads(response.read().decode('utf-8'))
            
            # Parse results into structured format
            parsed_results = []
            for r in results.get('results', []):
                parsed_results.append({
                    'title': r.get('title', ''),
                    'url': r.get('url', ''),
                    'content': r.get('content', '')[:500],
                    'score': r.get('score', 0)
                })
            
            duration = int((time.time() - start_time) * 1000)
            
            self.logger.log(self.name, "INFO", f"Found {len(parsed_results)} results for: {task[:50]}")
            
            return AgentResult(
                success=True,
                output=parsed_results,
                duration_ms=duration,
                metadata={
                    'query': task,
                    'num_results': len(parsed_results)
                }
            )
            
        except Exception as e:
            self.logger.log(self.name, "ERROR", f"Search failed: {str(e)}")
            return AgentResult(
                success=False,
                error=f"Search failed: {str(e)}",
                duration_ms=int((time.time() - start_time) * 1000)
            )
    
    def search(self, query: str, max_results: int = 5) -> AgentResult:
        """Convenience method for searching"""
        return self.run(query, {'max_results': max_results})


# For CLI registration compatibility
def create_search_agent():
    """Factory function to create search agent"""
    return SearchAgent()


# Module test
if __name__ == "__main__":
    agent = SearchAgent()
    print(f"Created: {agent}")
    print(f"Status: {agent.get_status()}")
    print(f"Tavily available: {agent.tavily_available}")
