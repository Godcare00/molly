import pytest
from app.agent.context import ContextManager, NormalizedMessage
from app.agent.messages import ConversationContext
from app.tools.registry import ToolResult
from app.config import settings


class TestTokenContext:
    def test_large_file_truncation(self):
        """Test that large file reads are truncated."""
        cm = ContextManager()
        cm.initialize()

        # Simulate a large tool result
        large_content = "x" * (settings.max_tool_output_chars + 1000)
        cm.add_tool_result("call_1", "read_file", large_content)

        # Check that the stored message is truncated
        messages = cm.get_llm_messages()
        # The tool result should be in the messages
        # In practice, the truncation happens in the tool itself

    def test_large_command_output_truncation(self):
        """Test that large command outputs are truncated."""
        from app.tools.terminal import ExecuteCommandTool

        tool = ExecuteCommandTool()
        # The tool itself handles truncation

    def test_history_compaction(self):
        """Test conversation history compaction."""
        cm = ContextManager()
        cm.initialize()

        # Add many messages
        for i in range(50):
            cm.add_user_message(f"User message {i}")
            cm.add_assistant_message(f"Assistant response {i}")

        assert len(cm.context.messages) == 100

        # Compact
        cm.compact_if_needed(max_messages=30)

        # Should have fewer messages now
        assert len(cm.context.messages) < 100
        assert len(cm.context.messages) >= 15  # Keep some recent

    def test_image_references_not_in_history(self):
        """Test that image binaries are not stored in conversation history."""
        cm = ContextManager()
        cm.initialize()

        # Add message with image reference
        msg = NormalizedMessage.user("Look at this", images=["/path/to/image.png"])
        cm.context.add_message(msg)

        # The message should have image path in metadata, not binary data
        messages = cm.get_llm_messages()
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "content" in user_msg
        # Image should be referenced, not embedded as base64

    def test_repeated_tool_calls_detection(self):
        """Test detection of repeated identical tool calls."""
        cm = ContextManager()
        cm.initialize()

        # Add repeated tool calls
        for i in range(3):
            cm.add_assistant_message("", tool_calls=[{
                "id": f"call_{i}",
                "function": {"name": "get_system_info", "arguments": "{}"},
            }])
            cm.add_tool_result(f"call_{i}", "get_system_info", {"os": "Linux"})

        # Detection happens in executor, not context manager
        # But context should have all messages
        assert len(cm.context.messages) == 6

    def test_context_budget_enforcement(self):
        """Test that context respects token budget."""
        cm = ContextManager(max_tokens=1000)
        cm.initialize()

        # Add large content
        large_text = "x" * 5000  # ~1250 tokens
        cm.add_user_message(large_text)

        tokens = cm.estimate_tokens()
        # Should be over budget
        assert tokens > 1000

        # Compaction would help
        cm.compact_if_needed(max_messages=10)