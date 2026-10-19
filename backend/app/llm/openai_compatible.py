import json
import base64
from typing import Optional, List, Dict, Any, AsyncIterator
import httpx
from PIL import Image

from app.llm.base import LLMProvider, Message, LLMResponse
from app.tools.registry import ToolSchema
from app.config import settings


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI-compatible API provider (OpenAI, Ollama, vLLM, etc.)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.default_temperature = temperature
        self.default_max_tokens = max_tokens
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def supports_images(self) -> bool:
        return True

    def get_model_name(self) -> str:
        return self.model

    def _encode_image(self, image_path: str) -> str:
        """Encode image as base64 data URL."""
        with open(image_path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("utf-8")
        mime_type = self._get_mime_type(image_path)
        return f"data:{mime_type};base64,{b64}"

    def _get_mime_type(self, path: str) -> str:
        ext = path.lower().split(".")[-1]
        return {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
        }.get(ext, "image/png")

    def _convert_messages(self, messages: List[Message], images: Optional[List[str]] = None) -> List[Dict]:
        """Convert internal messages to OpenAI format."""
        openai_messages = []

        for msg in messages:
            if msg.role == "system":
                openai_messages.append({"role": "system", "content": msg.content})
            elif msg.role == "user":
                content = msg.content
                # Add images if this message has them
                if msg.images:
                    content_parts = [{"type": "text", "text": content}]
                    for img_path in msg.images:
                        content_parts.append(
                            {"type": "image_url", "image_url": {"url": self._encode_image(img_path)}}
                        )
                    openai_messages.append({"role": "user", "content": content_parts})
                else:
                    openai_messages.append({"role": "user", "content": content})
            elif msg.role == "assistant":
                if msg.tool_calls:
                    openai_messages.append(
                        {
                            "role": "assistant",
                            "content": msg.content or None,
                            "tool_calls": msg.tool_calls,
                        }
                    )
                else:
                    openai_messages.append({"role": "assistant", "content": msg.content})
            elif msg.role == "tool":
                openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )

        return openai_messages

    def _convert_tools(self, tools: Optional[List[ToolSchema]]) -> Optional[List[Dict]]:
        if not tools:
            return None
        return [tool.to_openai_schema() for tool in tools]

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[ToolSchema]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> LLMResponse:
        client = await self._get_client()

        openai_messages = self._convert_messages(messages)
        openai_tools = self._convert_tools(tools)

        payload = {
            "model": model or self.model,
            "messages": openai_messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens or self.default_max_tokens,
        }
        # Only meaningful for reasoning-capable models (o-series, gpt-5,
        # etc.) - non-reasoning models will typically just ignore an
        # unrecognized field, but some strict backends may reject it, same
        # as sending any other param a given model doesn't support.
        if reasoning_effort and reasoning_effort != "off":
            payload["reasoning_effort"] = reasoning_effort

        if openai_tools:
            payload["tools"] = openai_tools
            payload["tool_choice"] = "auto"

        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = None
        if message.get("tool_calls"):
            tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                for tc in message["tool_calls"]
            ]

        return LLMResponse(
            content=message.get("content", "") or "",
            tool_calls=tool_calls,
            usage=data.get("usage"),
            finish_reason=choice.get("finish_reason"),
        )

    async def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolSchema]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[str]:
        client = await self._get_client()

        openai_messages = self._convert_messages(messages)
        openai_tools = self._convert_tools(tools)

        payload = {
            "model": model or self.model,
            "messages": openai_messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens or self.default_max_tokens,
            "stream": True,
        }
        if reasoning_effort and reasoning_effort != "off":
            payload["reasoning_effort"] = reasoning_effort

        if openai_tools:
            payload["tools"] = openai_tools
            payload["tool_choice"] = "auto"

        async with client.stream("POST", "/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        if "content" in delta and delta["content"]:
                            yield delta["content"]
                    except json.JSONDecodeError:
                        continue