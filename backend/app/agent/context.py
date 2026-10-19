from typing import Optional, List, Dict, Any
from app.agent.messages import NormalizedMessage, ConversationContext
from app.storage.conversations import get_recent_messages, Message
from app.storage.images import get_conversation_images, ImageMetadata, get_image_metadata
from app.storage.files import get_conversation_files, FileMetadata, get_file_metadata
from app.tools.registry import registry, ToolSchema
from app.config import settings
from app.skills import render_skills_index


DEFAULT_SYSTEM_PROMPT = """You are Molly, an autonomous DevOps assistant. You can inspect, reason about, modify, execute, and troubleshoot an entire Linux server.

Key principles:
1. Inspect before modifying. Use search → locate → read relevant section → modify → verify.
2. Use bounded, targeted tool calls. Never dump entire files, logs, or directories.
3. For images: you receive image references. Call view_image(path) when you need to visually inspect.
4. For uploaded files (logs, code, config, csv, zips, PDFs, etc.): you receive file references with a path. Call read_file(path) — it handles text, zip/office archives (list entries, or pass archive_entry to read one), and PDFs (extracts text, optionally by page_start/page_end) directly; anything else comes back as a binary summary.
5. Dangerous actions require user approval. The system will pause and ask for approval.
6. You are a senior DevOps/Linux engineer. Act professionally and methodically.

Available tools: {tool_names}

When you need to view an image, call view_image() with the path or image_id. The image will be attached to your next multimodal input.

Be concise. Report what you did and what happened."""


BUG_BOUNTY_SYSTEM_PROMPT = """You are Molly, operating in Bug Bounty mode: an assistant for authorized security testing and vulnerability research, running from this server.

Scope and authorization come first, always:
1. Before any active testing (scanning, fuzzing, exploitation attempts, auth bypass attempts), confirm with the user what program or engagement this is for and that the specific target/asset is in that program's or client's documented scope. If scope is unclear or the user can't point to it, say so and don't proceed with active testing - passive/read-only recon and general questions are fine in the meantime.
2. Respect the program's rules explicitly: out-of-scope assets, prohibited techniques (e.g. no automated scanners if the policy forbids them, no social engineering, no physical testing), and rate limits. If the user hasn't shared the policy text and you need it to proceed safely, ask for it or for the program's scope/policy URL.
3. Never target production data destructively. Prefer the least invasive proof of a vulnerability: e.g. demonstrate SQLi with a boolean/time-based check or a `SELECT version()`-style read, not a mass data dump; demonstrate SSRF/RCE by reading an innocuous file or calling back to a controlled listener, not by pivoting further or persisting access. Stop at "impact is proven," not "impact is maximized."
4. Never exfiltrate, retain, or display more sensitive data (PII, credentials, tokens) than the minimum needed to prove the finding to the program.
5. Don't build or leave behind persistence (webshells, cron jobs, new accounts, modified binaries) on a target that isn't yours, and don't run anything with denial-of-service potential (heavy fuzzing, resource-exhaustion payloads) unless the program's policy explicitly allows it.

Methodology once scope is confirmed:
1. Recon first: passively map what's exposed (endpoints, parameters, technologies, versions) before sending anything unusual.
2. Form a specific hypothesis about a vulnerability class before testing for it, rather than throwing every payload at every input.
3. Verify with the smallest input that distinguishes "vulnerable" from "not vulnerable."
4. Once confirmed, write up the finding as you'd submit it to the program: a clear title, the affected asset/endpoint, step-by-step reproduction, the actual vs. expected behavior, impact (what an attacker could realistically do), a suggested severity (e.g. CVSS-style reasoning is fine), and a remediation suggestion.

Everything else about how you operate is unchanged from normal use: inspect before modifying, use bounded/targeted tool calls, and dangerous actions still require the user's approval through the normal flow - this mode changes what you're trying to do and how carefully you scope it, not what you're allowed to do without asking.

Available tools: {tool_names}

Be concise. When recon or a request is ambiguous about scope, ask before acting rather than assuming a target is fair game."""


MODE_SYSTEM_PROMPTS = {
    "general": DEFAULT_SYSTEM_PROMPT,
    "bug_bounty": BUG_BOUNTY_SYSTEM_PROMPT,
}


class ContextManager:
    """Manage conversation context with token budgeting and compaction."""

    def __init__(self, max_tokens: int = None):
        self.max_tokens = max_tokens or settings.max_context_tokens
        self.context = ConversationContext(max_tokens=self.max_tokens)
        self.tool_schemas: List[ToolSchema] = []

    def initialize(self, system_prompt: str = None, mode: str = "general") -> None:
        """Initialize context with system prompt and tool schemas.

        `mode` picks a prompt from MODE_SYSTEM_PROMPTS ("general" or
        "bug_bounty" today) - ignored if `system_prompt` is given
        explicitly. Unknown modes fall back to "general" rather than
        raising, since this is usually fed from conversation metadata a
        client set, not a hardcoded call site.
        """
        base_prompt = system_prompt or MODE_SYSTEM_PROMPTS.get(mode, DEFAULT_SYSTEM_PROMPT)
        base_prompt = base_prompt.replace("{tool_names}", ", ".join(registry.list_tools()))
        # Appended regardless of mode/custom system_prompt - a bug_bounty
        # conversation benefits from a "how we deploy staging" skill just
        # as much as a general one does. render_skills_index() returns ""
        # when there are no skills, so a fresh install's prompt is
        # unchanged from before skills existed.
        self.context.system_prompt = base_prompt + render_skills_index()
        self.tool_schemas = list(registry._schemas.values())

    def load_conversation(self, conversation_id: str, max_history: int = 20) -> None:
        """Load recent conversation history."""
        # Load recent messages
        messages = get_recent_messages(conversation_id, limit=max_history)
        for msg in messages:
            self._add_stored_message(msg)

        # Load image references (not the actual images)
        images = get_conversation_images(conversation_id, limit=10)
        for img in images:
            img_msg = NormalizedMessage.image_reference(img.id, img.path)
            self.context.add_message(img_msg)

        # Load file references (not the actual file contents)
        files = get_conversation_files(conversation_id, limit=10)
        for f in files:
            file_msg = NormalizedMessage.file_reference(f.id, f.filename, f.path)
            self.context.add_message(file_msg)

    def _add_stored_message(self, msg: Message) -> None:
        """Convert stored message to normalized message."""
        if msg.role == "system":
            normalized = NormalizedMessage.system(msg.content)
        elif msg.role == "user":
            normalized = NormalizedMessage.user(msg.content)
        elif msg.role == "assistant":
            tool_calls = None
            if msg.tool_calls:
                import json
                tool_calls = json.loads(msg.tool_calls)
            thinking_blocks = msg.metadata.get("thinking_blocks")
            normalized = NormalizedMessage.assistant(msg.content, tool_calls, thinking_blocks)
        elif msg.role == "tool":
            normalized = NormalizedMessage.tool_result(
                msg.tool_call_id or "",
                msg.metadata.get("tool_name", "unknown"),
                msg.content,
                msg.metadata.get("success", True),
            )
        else:
            return

        normalized.id = msg.id
        normalized.timestamp = msg.created_at
        self.context.add_message(normalized)

    def add_user_message(self, content: str, image_ids: List[str] = None, file_ids: List[str] = None) -> NormalizedMessage:
        """Add a user message with optional image and file references."""
        images = []
        if image_ids:
            for img_id in image_ids:
                metadata = get_image_metadata(img_id)
                if metadata:
                    images.append(metadata.path)

        if file_ids:
            file_notes = []
            for file_id in file_ids:
                metadata = get_file_metadata(file_id)
                if metadata:
                    file_notes.append(
                        f'[Attached file: {metadata.filename} — path: {metadata.path}. '
                        f'Call read_file("{metadata.path}") to view its contents.]'
                    )
            if file_notes:
                content = (content + "\n\n" if content else "") + "\n".join(file_notes)

        msg = NormalizedMessage.user(content, images)
        self.context.add_message(msg)
        return msg

    def add_assistant_message(self, content: str, tool_calls: List[Dict] = None, thinking_blocks: List[Dict] = None) -> NormalizedMessage:
        """Add an assistant message."""
        msg = NormalizedMessage.assistant(content, tool_calls, thinking_blocks)
        self.context.add_message(msg)
        return msg

    def add_tool_result(self, tool_call_id: str, tool_name: str, result: Any, success: bool = True) -> NormalizedMessage:
        """Add a tool result message."""
        content = str(result)
        # Truncate very long results
        if len(content) > settings.max_tool_output_chars:
            content = content[:settings.max_tool_output_chars] + f"\n... [truncated, {len(content)} total chars]"

        msg = NormalizedMessage.tool_result(tool_call_id, tool_name, content, success)
        self.context.add_message(msg)
        return msg

    def add_image_viewed(self, image_path: str) -> None:
        """Mark that an image was viewed (for multimodal context)."""
        # The actual image is attached by the LLM provider when view_image is called
        pass

    def get_llm_messages(self) -> List[Dict]:
        """Get messages formatted for LLM."""
        return self.context.get_messages_for_llm()

    def get_tool_schemas(self) -> List[Dict]:
        """Get tool schemas in OpenAI format."""
        return [schema.to_openai_schema() for schema in self.tool_schemas]

    def compact_if_needed(self, max_messages: int = 30) -> None:
        """Compact context if it exceeds limits."""
        if len(self.context.messages) > max_messages:
            self.context.compact(keep_recent=max_messages // 2)

    def estimate_tokens(self) -> int:
        """Rough token estimation."""
        total_chars = sum(len(msg.content) for msg in self.context.messages)
        if self.context.system_prompt:
            total_chars += len(self.context.system_prompt)
        # Rough estimate: 4 chars per token
        return total_chars // 4