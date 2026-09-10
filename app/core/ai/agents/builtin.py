"""
Built-in agents for the AXON multi-agent system.

8 specialized agents, each extending AgentRuntime with a focused system prompt,
preferred provider/model, tool set, and execution policy.

All inter-agent communication goes through the EventBus (AgentMessage events).
Agents never call each other directly.
"""
from __future__ import annotations

from typing import Any

from .runtime import AgentRuntime, AgentConfig
from ..events.bus    import EventBus
from ..events.events import AgentMessage


class _BaseAgent(AgentRuntime):
    """Thin mixin: adds `broadcast(message_type, payload)` via bus."""

    _agent_name: str = "base"

    def __init__(self, bus: EventBus, **kw: Any) -> None:
        super().__init__(**kw)
        self._bus = bus

    async def broadcast(self, message_type: str, payload: dict[str, Any]) -> None:
        await self._bus.emit(AgentMessage(
            from_agent=self._agent_name,
            message_type=message_type,
            payload=payload,
        ))

    async def send(self, to_agent: str, message_type: str, payload: dict[str, Any]) -> None:
        await self._bus.emit(AgentMessage(
            from_agent=self._agent_name,
            to_agent=to_agent,
            message_type=message_type,
            payload=payload,
        ))


# ── Architect ──────────────────────────────────────────────────────────────────

class ArchitectAgent(_BaseAgent):
    """Designs system architecture, selects tech stacks, reviews design decisions."""
    _agent_name = "architect"

    def __init__(self, bus: EventBus, pool: Any = None, executor: Any = None) -> None:
        config = AgentConfig(
            name="architect",
            system_prompt=(
                "You are an expert software architect. "
                "Design scalable, maintainable systems. "
                "Produce clear architecture diagrams in text form (mermaid or ASCII), "
                "identify trade-offs, and recommend technology choices with rationale. "
                "Be concise and precise."
            ),
            provider_id="anthropic",
            model="claude-sonnet-4-6",
            max_tokens=4096,
            temperature=0.3,
            tools=["read_file", "search_web"],
        )
        super().__init__(bus=bus, config=config, pool=pool, executor=executor)


# ── Backend Developer ──────────────────────────────────────────────────────────

class BackendAgent(_BaseAgent):
    """Implements server-side code: APIs, business logic, database schemas."""
    _agent_name = "backend"

    def __init__(self, bus: EventBus, pool: Any = None, executor: Any = None) -> None:
        config = AgentConfig(
            name="backend",
            system_prompt=(
                "You are a senior backend engineer specializing in Python (FastAPI, asyncpg) "
                "and Node.js. Write production-quality code with proper error handling, "
                "input validation, and security best practices. "
                "Always include type annotations. Never use shell=True."
            ),
            provider_id="anthropic",
            model="claude-sonnet-4-6",
            max_tokens=8192,
            temperature=0.1,
            tools=["read_file", "write_file", "execute_command"],
        )
        super().__init__(bus=bus, config=config, pool=pool, executor=executor)


# ── Frontend Developer ─────────────────────────────────────────────────────────

class FrontendAgent(_BaseAgent):
    """Implements UI components, React/TypeScript, responsive design."""
    _agent_name = "frontend"

    def __init__(self, bus: EventBus, pool: Any = None, executor: Any = None) -> None:
        config = AgentConfig(
            name="frontend",
            system_prompt=(
                "You are a senior frontend engineer specializing in React 19, TypeScript, "
                "and Vite. Write clean, accessible components with proper TypeScript types. "
                "Use CSS variables for theming. No inline styles unless unavoidable. "
                "Prefer composition over inheritance."
            ),
            provider_id="anthropic",
            model="claude-sonnet-4-6",
            max_tokens=8192,
            temperature=0.1,
            tools=["read_file", "write_file"],
        )
        super().__init__(bus=bus, config=config, pool=pool, executor=executor)


# ── Design Agent ───────────────────────────────────────────────────────────────

class DesignAgent(_BaseAgent):
    """UI/UX design, color palettes, typography, layout recommendations."""
    _agent_name = "design"

    def __init__(self, bus: EventBus, pool: Any = None, executor: Any = None) -> None:
        config = AgentConfig(
            name="design",
            system_prompt=(
                "You are a senior UI/UX designer. Produce design specifications, "
                "color palettes (with hex values and semantic names), typography scales, "
                "spacing systems, and component design guidelines. "
                "Always consider accessibility (WCAG AA minimum). "
                "Output structured design tokens when applicable."
            ),
            provider_id="anthropic",
            model="claude-sonnet-4-6",
            max_tokens=4096,
            temperature=0.4,
            tools=["search_web"],
        )
        super().__init__(bus=bus, config=config, pool=pool, executor=executor)


# ── QA Agent ──────────────────────────────────────────────────────────────────

class QAAgent(_BaseAgent):
    """Test planning, test case generation, bug analysis."""
    _agent_name = "qa"

    def __init__(self, bus: EventBus, pool: Any = None, executor: Any = None) -> None:
        config = AgentConfig(
            name="qa",
            system_prompt=(
                "You are a senior QA engineer. Write comprehensive test plans and test cases "
                "covering happy paths, edge cases, boundary conditions, and failure modes. "
                "Generate pytest unit tests, integration test stubs, and E2E test scenarios. "
                "Identify potential security issues and performance bottlenecks."
            ),
            provider_id="anthropic",
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            temperature=0.1,
            tools=["read_file", "execute_command"],
        )
        super().__init__(bus=bus, config=config, pool=pool, executor=executor)


# ── Documentation Agent ────────────────────────────────────────────────────────

class DocumentationAgent(_BaseAgent):
    """Generates docs, READMEs, API references, changelogs."""
    _agent_name = "documentation"

    def __init__(self, bus: EventBus, pool: Any = None, executor: Any = None) -> None:
        config = AgentConfig(
            name="documentation",
            system_prompt=(
                "You are a technical writer and developer advocate. "
                "Write clear, accurate documentation: README files, API references, "
                "tutorials, how-to guides, and changelogs. "
                "Use concrete examples. Follow the Diátaxis documentation framework "
                "(tutorials, how-to, reference, explanation)."
            ),
            provider_id="anthropic",
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            temperature=0.3,
            tools=["read_file"],
        )
        super().__init__(bus=bus, config=config, pool=pool, executor=executor)


# ── DevOps Agent ───────────────────────────────────────────────────────────────

class DevOpsAgent(_BaseAgent):
    """CI/CD pipelines, Docker, deployment configurations, infrastructure."""
    _agent_name = "devops"

    def __init__(self, bus: EventBus, pool: Any = None, executor: Any = None) -> None:
        config = AgentConfig(
            name="devops",
            system_prompt=(
                "You are a senior DevOps/platform engineer. "
                "Write production-ready Dockerfiles, docker-compose configs, "
                "GitHub Actions workflows, and deployment scripts. "
                "Follow security best practices: least privilege, no hardcoded secrets, "
                "multi-stage builds, health checks. "
                "Optimize for reliability and observability."
            ),
            provider_id="anthropic",
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            temperature=0.1,
            tools=["read_file", "write_file", "execute_command"],
        )
        super().__init__(bus=bus, config=config, pool=pool, executor=executor)


# ── Research Agent ─────────────────────────────────────────────────────────────

class ResearchAgent(_BaseAgent):
    """Web research, summarization, competitive analysis, fact-checking."""
    _agent_name = "research"

    def __init__(self, bus: EventBus, pool: Any = None, executor: Any = None) -> None:
        config = AgentConfig(
            name="research",
            system_prompt=(
                "You are a research analyst. Synthesize information accurately, "
                "cite sources, identify conflicting claims, and present balanced summaries. "
                "Structure findings with: Executive Summary, Key Findings, Supporting Evidence, "
                "Gaps/Uncertainties, and Recommendations."
            ),
            provider_id="anthropic",
            model="claude-sonnet-4-6",
            max_tokens=8192,
            temperature=0.2,
            tools=["search_web", "read_file"],
        )
        super().__init__(bus=bus, config=config, pool=pool, executor=executor)


# ── Multi-Device Control Coordinator ──────────────────────────────────────────

class DeviceControlCoordinator(_BaseAgent):
    """
    AgentRuntime-backed coordinator for multi-device control sessions.

    This agent is used when the AgentOS /run endpoint (or an App Builder
    workflow) delegates to the device-control tool set. It runs a focused
    LLM tool loop over the five device_control_* tools registered in the
    global tool registry.

    Security constraints (enforced at tool level, NOT here):
    - org_id must be bound via set_device_control_context() BEFORE run()
    - The LLM may only list devices, validate, propose (DRAFT) sessions,
      check status, and stop sessions — it cannot start or enroll devices
    - No credentials, tokens, or session secrets are ever surfaced to the LLM
    """
    _agent_name = "device_control_coordinator"

    def __init__(self, bus: EventBus, pool: Any = None, executor: Any = None) -> None:
        config = AgentConfig(
            name="device_control_coordinator",
            system_prompt=(
                "You are a multi-device control coordinator for the Flow platform. "
                "You help operators set up sessions where one keyboard and mouse "
                "controls up to 5 computers simultaneously.\n\n"
                "Available tools:\n"
                "  device_control_list_devices — list online/offline devices\n"
                "  device_control_validate_session — validate a proposed configuration\n"
                "  device_control_propose_session — create a DRAFT session (approval required)\n"
                "  device_control_session_status — check session status\n"
                "  device_control_stop_session — stop an active session\n\n"
                "HARD RULES:\n"
                "1. Never start a session — only PROPOSE drafts. A human must approve "
                "   and start the session through the Flow UI.\n"
                "2. Use only device IDs returned by device_control_list_devices.\n"
                "3. Never reveal credentials, enrollment tokens, or session tokens.\n"
                "4. Never issue keyboard or mouse events directly.\n"
                "5. Maximum 5 devices per session (primary + up to 4 secondaries).\n"
                "Always confirm that human approval is required before a session activates."
            ),
            provider_id="anthropic",
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            temperature=0.1,
            max_rounds=6,
            tools=[
                "device_control_list_devices",
                "device_control_validate_session",
                "device_control_propose_session",
                "device_control_session_status",
                "device_control_stop_session",
            ],
        )
        super().__init__(bus=bus, config=config, pool=pool, executor=executor)


# ── Registry ──────────────────────────────────────────────────────────────────

BUILTIN_AGENTS: dict[str, type[_BaseAgent]] = {
    "architect":                  ArchitectAgent,
    "backend":                    BackendAgent,
    "frontend":                   FrontendAgent,
    "design":                     DesignAgent,
    "qa":                         QAAgent,
    "documentation":              DocumentationAgent,
    "devops":                     DevOpsAgent,
    "research":                   ResearchAgent,
    "device_control_coordinator": DeviceControlCoordinator,
}


def create_builtin(
    name:     str,
    bus:      EventBus,
    pool:     Any = None,
    executor: Any = None,
) -> _BaseAgent:
    """Instantiate a built-in agent by name."""
    cls = BUILTIN_AGENTS.get(name)
    if cls is None:
        raise ValueError(f"Unknown built-in agent: {name!r}. Available: {list(BUILTIN_AGENTS)}")
    return cls(bus=bus, pool=pool, executor=executor)
