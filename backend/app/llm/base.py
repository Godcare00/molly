from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, AsyncIterator
from dataclasses import dataclass
from app.tools.registry import ToolSchema

# Valid values for `reasoning_effort` across the app (chat(), the
# conversation-settings API, and the mobile model/reasoning picker).
# "off" means no reasoning requested at all - distinct from None, which
# means "caller didn't specify" and is treated the same as "off".
REASONING_EFFORT_LEVELS = ("off", "low", "medium", "high")


@dataclass
class Message:
    role: str  # system, user, assistant, tool
    content: str = ""
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    images: Optional[List[str]] = None  # image paths for multimodal
    # Raw thinking/redacted_thinking blocks from a prior Anthropic response,
    # to be replayed verbatim (see AnthropicProvider._convert_messages) when
    # this assistant turn is resent as history. Anthropic requires the
    # thinking block that preceded a tool_use to be preserved unmodified on
    # every subsequent request that includes that turn - dropping it (the
    # previous behavior) breaks reasoning on any turn after the first
    # tool call in a conversation. Opaque/provider-specific: other
    # providers just ignore this field entirely.
    thinking_blocks: Optional[List[Dict]] = None


@dataclass
class LLMResponse:
    content: str
    tool_calls: Optional[List[Dict]] = None
    usage: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None
    # Populated by FallbackLLMProvider so callers (metrics, logging) know
    # which provider in the chain actually served the request, and what it
    # had to fail past to get there. None when there's no fallback wrapper.
    provider: Optional[str] = None
    model_used: Optional[str] = None
    provider_attempts: Optional[List[Dict[str, str]]] = None
    # Raw thinking/redacted_thinking blocks this response included (see
    # Message.thinking_blocks) - None if reasoning wasn't requested/used.
    thinking_blocks: Optional[List[Dict]] = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[ToolSchema]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        `reasoning_effort`: None/"off" - no reasoning/thinking requested.
        "low"/"medium"/"high" - ask the model to reason before answering
        (Anthropic extended thinking, or an OpenAI-style reasoning_effort
        param, depending on the provider). Only meaningful for models that
        actually support it - see each provider's implementation.
        """
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolSchema]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response."""
        pass

    @abstractmethod
    def supports_images(self) -> bool:
        """Check if provider supports multimodal image input."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the configured model name."""
        pass