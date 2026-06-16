"""Multi-LLM abstraction layer for the A-share prediction system.

Provides a unified interface for Anthropic Claude, OpenAI GPT, and
Google Gemini with routing, consensus analysis, and key management.
"""

from src.llm.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    LLMToolResponse,
    ProviderName,
    ToolCall,
)

from src.llm.gateway import LLMGateway

__all__ = [
    "BaseLLMProvider",
    "LLMGateway",
    "LLMMessage",
    "LLMProviderError",
    "LLMResponse",
    "LLMToolResponse",
    "ProviderName",
    "ToolCall",
]
