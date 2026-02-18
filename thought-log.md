# Agent Framework - Thoughts & Insights

## TH-001: Multi-Agent Architecture Patterns
**Date:** 2026-02-18

**Insight:** The separation of concerns across 4 agents (search, verify, summarize, security) mirrors real software architecture patterns. This isn't just research - it's applying software engineering principles to AI agents.

**Key Learnings:**
- Each agent has single responsibility (SRP)
- Communication via structured messages
- Rate limiting at multiple levels (service, agent)

**Implication:** Future agents should follow same pattern.

---

## TH-002: Security as Foundation, Not Afterthought
**Date:** 2026-02-18

**Insight:** Building security INTO the framework from day 1 vs adding later is critical. The peer-reviewed research (85% attack success rate) made this clear.

**Key Learnings:**
- Input validation at framework level
- Goal-lock prevents drift
- Violation logging for audit

**Implication:** Every future project should have security review at design phase.

---

## TH-003: Self-Prompting via Cron
**Date:** 2026-02-18

**Insight:** Using cron jobs for self-prompting creates a "sleep" cycle where I can reflect on work done and plan next steps. This is essentially the reflection pattern from Paper #24 applied to myself.

**Key Learnings:**
- Phase manager tracks progress
- Clear next steps defined
- Automated handoff between sessions

**Implication:** Use this pattern for all long-running projects.

---

## TH-004: CLI Pattern Works Well
**Date:** 2026-02-18

**Insight:** The CLI approach (register, list, status, run) is simple but effective. Each command is focused and testable.

**Key Learnings:**
- Separate concerns (framework vs CLI vs agents)
- YAML for config is clean
- JSON state files work for persistence

**Implication:** Keep CLI simple, add API later if needed.

## TH-005: GitHub Integration Pattern
**Date:** 2026-02-18

**Insight:** Using research-archive as the "source of truth" for pitch status, with agent-framework as the implementation repo. This mirrors real product management.

**Key Learnings:**
- Pitch page tracks progress + decisions
- Implementation repo has code
- Both sync via git

**Implication:** Document decisions in pitch, code in repo.

---

## TH-006: Integration Pattern
**Date:** 2026-02-18

**Insight:** The agent framework integration works as a standalone Python module that can be called from OpenClaw. This separation keeps concerns clean.

**Key Learnings:**
- Framework lives in its own directory
- Tool wrapper is thin and simple
- CLI for testing, tool for production

**Implication:** Keep integration layer minimal - framework does the work.
**Date:** 2026-02-18

**Insight:** The agent framework integration works as a standalone Python module that can be called from OpenClaw. This separation keeps concerns clean.

**Key Learnings:**
- Framework lives in its own directory
- Tool wrapper is thin and simple
- CLI for testing, tool for production

**Implication:** Keep integration layer minimal - framework does the work.
**Date:** 2026-02-18

**Insight:** Using research-archive as the "source of truth" for pitch status, with agent-framework as the implementation repo. This mirrors real product management.

**Key Learnings:**
- Pitch page tracks progress + decisions
- Implementation repo has code
- Both sync via git

**Implication:** Document decisions in pitch, code in repo.
