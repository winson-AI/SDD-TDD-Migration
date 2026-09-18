from typing import Type, Dict, Any, Optional


class AgentFactory:
    """
    Factory class for managing and creating agent instances.
    Uses a registry pattern to allow agents to register themselves.
    """
    _registry: Dict[str, Type] = {}

    @classmethod
    def register(cls, name: str):
        """
        Decorator to register an agent class with a specific provider name.

        Args:
            name: The provider name to register the agent under (e.g., 'glm', 'general').
        """

        def decorator(wrapped_class: Type):
            cls._registry[name] = wrapped_class
            return wrapped_class

        return decorator

    @classmethod
    def get_agent_class(cls, provider: str) -> Type:
        """
        Retrieve the agent class for a given provider.

        Args:
            provider: The name of the provider.

        Returns:
            The agent class.
        """
        if not cls._registry:
            cls._load_builtin_agents()

        agent_cls = cls._registry.get(provider)

        # Fallback logic to match original behavior:
        # If provider is not found, default to 'general' (GeneralAgent)
        if not agent_cls:
            agent_cls = cls._registry.get("general")

        if not agent_cls:
            # Should not happen if builtin agents are loaded correctly
            raise ValueError(f"No agent found for provider '{provider}' and default 'general' not available.")

        return agent_cls

    @classmethod
    def create(cls, provider: str = "glm", *args, **kwargs) -> Any:
        """
        Create an instance of an agent.

        Args:
            provider: The provider name.
            *args, **kwargs: Arguments passed to the agent constructor.

        Returns:
            An instance of the agent.
        """
        agent_cls = cls.get_agent_class(provider)
        return agent_cls(*args, **kwargs)

    @classmethod
    def _load_builtin_agents(cls):
        """
        Load built-in agents to ensure they are registered.
        Import inside method to avoid circular imports at module level.
        """
        # We use local imports to trigger the decorators in these modules
        from .glm.agent import GLMAgent
        from .general.agent import GeneralAgent
        from .mcp_agent.agent import MCPAgent
        from .hypium_mcp_agent.agent import HypiumMCPAgent


def create_agent(provider: str = "glm") -> Type:
    """
    Legacy factory function to get agent class.

    Args:
        provider: The provider name.

    Returns:
        The agent class.
    """
    return AgentFactory.get_agent_class(provider)
