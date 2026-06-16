"""Agent registry — bootstraps and manages specialist agents.

Reads agent definitions from config/agents.yaml, creates filtered
tool registries per agent, and provides agent lookup + permission checks.

Part of v16.0 Agent Mesh layer.
"""

from __future__ import annotations

from typing import Any

from src.agents.base import AgentCapability, BaseAgent
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("agents.registry")


class AgentRegistry:
    """Registry of specialist agents with filtered tool access.

    Usage::

        registry = AgentRegistry()
        registry.bootstrap(tool_registry=tool_registry, llm_router=llm_router)
        agent = registry.get("analyst")
        result = await agent.execute(message)
    """

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._capabilities: dict[str, AgentCapability] = {}
        self._config: dict[str, Any] = {}
        self._budget_config: dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load agent definitions from config/agents.yaml."""
        try:
            cfg = load_config("agents")
        except Exception:
            logger.warning("Could not load agents config, using defaults")
            cfg = {}

        self._config = cfg
        self._budget_config = cfg.get("budget", {})

        # Parse agent capabilities
        agents_cfg = cfg.get("agents", {})
        for agent_name, agent_cfg in agents_cfg.items():
            cap = AgentCapability(
                name=agent_name,
                description=agent_cfg.get("description", ""),
                tool_whitelist=agent_cfg.get("tools", []),
                max_tokens=agent_cfg.get("max_tokens_per_request", 2048),
                trust_zone_min=agent_cfg.get("trust_zone_min", "LOW"),
                use_llm=agent_cfg.get("use_llm", True),
                temperature=agent_cfg.get("temperature", 0.3),
            )
            self._capabilities[agent_name] = cap

    def bootstrap(
        self,
        tool_registry: Any,
        llm_router: Any,
    ) -> None:
        """Create and register all specialist agents.

        Args:
            tool_registry: The global ToolRegistry instance.
            llm_router: The LLMRouter instance for LLM-backed agents.
        """
        from src.agents.backtest_agent import BacktestAgent
        from src.agents.correlation_agent import CorrelationAgent
        from src.agents.data_qa_agent import DataQAAgent
        from src.agents.evaluator_agent import EvaluatorAgent
        from src.agents.exec_plan_agent import ExecPlanAgent
        from src.agents.portfolio_agent import PortfolioAgent
        from src.agents.prediction_monitor_agent import PredictionMonitorAgent
        from src.agents.regime_agent import RegimeAgent
        from src.agents.report_agent import ReportAgent
        from src.agents.sentiment_agent import SentimentAgent
        from src.agents.trader_agent import TraderAgent

        agent_classes: dict[str, type[BaseAgent]] = {
            # Gate-keeper
            "data_qa": DataQAAgent,
            # Analysis tier
            "sentiment": SentimentAgent,
            "regime": RegimeAgent,
            # Validation tier
            "backtest": BacktestAgent,
            # Risk tier
            "correlation": CorrelationAgent,
            # Construction tier
            "portfolio": PortfolioAgent,
            "exec_plan": ExecPlanAgent,
            # Execution tier
            "trader": TraderAgent,
            # Monitoring tier
            "monitor": PredictionMonitorAgent,
            # Evaluation tier
            "evaluator": EvaluatorAgent,
            # Report tier
            "report": ReportAgent,
        }

        agents_cfg = self._config.get("agents", {})

        for agent_name, agent_cls in agent_classes.items():
            cap = self._capabilities.get(agent_name)
            if not cap:
                logger.warning(
                    "No capability config for agent %s, skipping", agent_name
                )
                continue

            system_role = agents_cfg.get(agent_name, {}).get("system_role", "")

            # Create filtered tool registry for this agent
            filtered_tools = _create_filtered_tool_registry(
                tool_registry, cap.tool_whitelist
            )

            agent = agent_cls(
                capability=cap,
                tool_registry=filtered_tools,
                llm_router=llm_router,
                system_role=system_role,
            )
            self._agents[agent_name] = agent
            logger.info(
                "Registered agent: %s (%d tools, %d max tokens)",
                agent_name,
                len(cap.tool_whitelist),
                cap.max_tokens,
            )

    def get(self, name: str) -> BaseAgent | None:
        """Get a registered agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._agents.keys())

    def get_capability(self, name: str) -> AgentCapability | None:
        """Get capability declaration for an agent."""
        return self._capabilities.get(name)

    def get_budget_config(self) -> dict[str, Any]:
        """Get budget control configuration."""
        return self._budget_config

    def get_master_config(self) -> dict[str, Any]:
        """Get master agent configuration."""
        return self._config.get("master", {})

    @property
    def max_tokens_per_thread(self) -> int:
        """Maximum total tokens per thread across all agents."""
        return self._budget_config.get("max_tokens_per_thread", 50000)

    @property
    def max_tool_calls_per_agent(self) -> int:
        """Maximum tool calls per specialist per delegation."""
        return self._budget_config.get("max_tool_calls_per_agent", 8)


def _create_filtered_tool_registry(
    full_registry: Any,
    whitelist: list[str],
) -> Any:
    """Create a filtered tool registry that only exposes whitelisted tools.

    Returns a lightweight wrapper with get_tool_definitions() and execute()
    that delegates to the full registry but restricts access.
    """
    return FilteredToolRegistry(full_registry, whitelist)


class FilteredToolRegistry:
    """A tool registry view that restricts access to whitelisted tools.

    Delegates to the underlying full registry for execution, but only
    exposes tool definitions for tools in the whitelist.
    """

    def __init__(self, full_registry: Any, whitelist: list[str]) -> None:
        self._full = full_registry
        self._whitelist = set(whitelist)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return only whitelisted tool definitions."""
        return [
            td
            for td in self._full.get_tool_definitions()
            if td["name"] in self._whitelist
        ]

    async def execute(self, name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool, enforcing whitelist."""
        if name not in self._whitelist:
            import json

            return json.dumps(
                {"error": f"Agent does not have permission to use tool: {name}"}
            )
        return await self._full.execute(name, tool_input)
