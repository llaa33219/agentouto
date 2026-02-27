from __future__ import annotations


class AgentOutOError(Exception):
    """Base exception for AgentOutO SDK."""


class ProviderError(AgentOutOError):
    """Raised when a provider encounters an error during LLM calls."""

    def __init__(self, provider_name: str, message: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"[{provider_name}] {message}")


class AgentError(AgentOutOError):
    """Raised when an agent encounters an error during execution."""

    def __init__(self, agent_name: str, message: str) -> None:
        self.agent_name = agent_name
        super().__init__(f"[{agent_name}] {message}")


class ToolError(AgentOutOError):
    """Raised when a tool execution fails."""

    def __init__(self, tool_name: str, message: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"[{tool_name}] {message}")


class RoutingError(AgentOutOError):
    """Raised when message routing fails (e.g. unknown agent name)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AuthError(AgentOutOError):
    """Raised when authentication fails (e.g. OAuth token refresh failure)."""

    def __init__(self, provider_name: str, message: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"[{provider_name}] {message}")
