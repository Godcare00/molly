from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid


@dataclass
class NormalizedMessage:
    """Normalized message format for internal use."""
    id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:8]}")
    role: str = "user"  # system, user, assistant, tool
    content: str = ""
    content_type: str = "text"  # text, image_reference, tool_call, tool_result
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    images: List[str] = field(default_factory=list)  # image paths for multimodal
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    # Raw Anthropic thinking/redacted_thinking blocks for this turn, if any -
    # see app/llm/base.py's Message.thinking_blocks for why these need to
    # round-trip verbatim rather than being dropped.
    thinking_blocks: Optional[List[Dict]] = None

    @classmethod
    def system(cls, content: str) -> "NormalizedMessage":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str, images: List[str] = None) -> "NormalizedMessage":
        return cls(role="user", content=content, images=images or [])

    @classmethod
    def assistant(cls, content: str, tool_calls: List[Dict] = None, thinking_blocks: List[Dict] = None) -> "NormalizedMessage":
        return cls(role="assistant", content=content, tool_calls=tool_calls, thinking_blocks=thinking_blocks)

    @classmethod
    def tool_result(cls, tool_call_id: str, tool_name: str, content: str, success: bool = True) -> "NormalizedMessage":
        return cls(
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            metadata={"success": success},
        )

    @classmethod
    def image_reference(cls, image_id: str, path: str) -> "NormalizedMessage":
        return cls(
            role="user",
            content=f"[Image: {image_id}]",
            content_type="image_reference",
            metadata={"image_id": image_id, "path": path},
        )

    @classmethod
    def file_reference(cls, file_id: str, filename: str, path: str) -> "NormalizedMessage":
        return cls(
            role="user",
            content=f"[File: {filename} ({file_id}) — path: {path}. Call read_file(\"{path}\") to view its contents.]",
            content_type="file_reference",
            metadata={"file_id": file_id, "filename": filename, "path": path},
        )

    def to_llm_message(self) -> Dict:
        """Convert to LLM provider message format."""
        if self.role == "system":
            return {"role": "system", "content": self.content}
        elif self.role == "user":
            if self.images:
                content_parts = [{"type": "text", "text": self.content}]
                for img_path in self.images:
                    content_parts.append({"type": "image_url", "image_url": {"url": img_path}})
                return {"role": "user", "content": content_parts}
            return {"role": "user", "content": self.content}
        elif self.role == "assistant":
            msg = {"role": "assistant", "content": self.content or None}
            if self.tool_calls:
                msg["tool_calls"] = self.tool_calls
            if self.thinking_blocks:
                msg["thinking_blocks"] = self.thinking_blocks
            return msg
        elif self.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": self.tool_call_id,
                "content": self.content,
            }
        return {"role": "user", "content": str(self.content)}


@dataclass
class ConversationContext:
    """Managed conversation context with token budgeting."""
    messages: List[NormalizedMessage] = field(default_factory=list)
    system_prompt: str = ""
    max_tokens: int = 32000
    reserved_tokens: int = 4000  # Reserve for response

    def add_message(self, message: NormalizedMessage) -> None:
        self.messages.append(message)

    def get_messages_for_llm(self, include_system: bool = True) -> List[Dict]:
        """Get messages formatted for LLM, respecting token budget."""
        result = []
        if include_system and self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})

        # Add messages in reverse order (newest first) until token budget
        # This is a simplified version - real implementation would count tokens
        for msg in reversed(self.messages):
            result.insert(0 if include_system else -1, msg.to_llm_message())

        return result

    def compact(self, keep_recent: int = 10, summarize_fn=None) -> None:
        """Compact conversation history."""
        if len(self.messages) <= keep_recent:
            return

        # Keep system prompt and recent messages
        recent = self.messages[-keep_recent:]
        older = self.messages[:-keep_recent]

        # Could summarize older messages here if summarize_fn provided
        if summarize_fn and older:
            summary = summarize_fn(older)
            if summary:
                summary_msg = NormalizedMessage.system(f"Previous conversation summary: {summary}")
                self.messages = [summary_msg] + recent
            else:
                self.messages = recent
        else:
            self.messages = recent