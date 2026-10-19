import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.executor import AgentExecutor
from app.agent.state import AgentState, TaskStatus
from app.agent.context import ContextManager
from app.llm.base import LLMResponse, Message as LLMMessage
from app.tools.registry import ToolResult
from app.storage.conversations import create_conversation
from app.agent.tasks import create_task


class TestAgentLoop:
    @pytest.fixture
    def mock_provider(self):
        provider = AsyncMock()
        provider.chat = AsyncMock()
        provider.chat_stream = AsyncMock()
        return provider

    @pytest.fixture
    def context_manager(self):
        return ContextManager()

    @pytest.mark.asyncio
    async def test_simple_conversation(self, mock_provider, conversation_id):
        """Test user -> LLM -> final response."""
        # Mock LLM to return final response (no tool calls)
        mock_provider.chat.return_value = LLMResponse(
            content="Hello! I'm Molly, your DevOps assistant.",
            tool_calls=None,
        )

        with patch("app.agent.executor.get_llm_provider", return_value=mock_provider):
            with patch("app.agent.executor.create_task") as mock_create_task:
                mock_state = AgentState(
                    task_id="task_test",
                    conversation_id=conversation_id,
                    status=TaskStatus.RUNNING,
                )
                mock_create_task.return_value = mock_state

                executor = AgentExecutor(conversation_id)

                events = []
                async for event in executor.run("Hello"):
                    events.append(event)

                # Should have agent_started and agent_completed
                assert events[0]["type"] == "agent_started"
                assert events[-1]["type"] == "agent_completed"
                assert "Hello! I'm Molly" in events[-1]["response"]

    @pytest.mark.asyncio
    async def test_agent_cancellation_sets_flag(self, mock_provider, conversation_id):
        """Test agent cancel() method sets cancelled flag."""
        with patch("app.agent.executor.get_llm_provider", return_value=mock_provider):
            with patch("app.agent.executor.create_task") as mock_create_task:
                mock_state = AgentState(
                    task_id="task_test",
                    conversation_id=conversation_id,
                    status=TaskStatus.RUNNING,
                )
                mock_create_task.return_value = mock_state

                executor = AgentExecutor(conversation_id)
                
                # Initially not cancelled
                assert executor._cancelled is False
                
                # Call cancel
                executor.cancel()
                
                # Should be cancelled
                assert executor._cancelled is True


class TestContextManager:
    def test_add_messages(self):
        cm = ContextManager()
        cm.initialize()

        cm.add_user_message("Hello")
        cm.add_assistant_message("Hi there!")
        cm.add_tool_result("call_1", "get_system_info", {"os": "Linux"})

        messages = cm.get_llm_messages()
        assert len(messages) >= 3  # system + user + assistant + tool

    def test_compact_context(self):
        cm = ContextManager()
        cm.initialize()

        # Add many messages
        for i in range(40):
            cm.add_user_message(f"Message {i}")

        assert len(cm.context.messages) == 40
        cm.compact_if_needed(max_messages=30)
        # Should compact to ~15 messages
        assert len(cm.context.messages) < 40
        assert len(cm.context.messages) >= 15  # Keep some recent

    def test_token_estimation(self):
        cm = ContextManager()
        cm.initialize()

        cm.add_user_message("Hello world")
        tokens = cm.estimate_tokens()
        assert tokens > 0


class TestTokenBudget:
    def test_context_respects_token_limit(self):
        cm = ContextManager(max_tokens=1000)
        cm.initialize()

        # Add content that exceeds budget
        large_text = "x" * 5000  # ~1250 tokens
        cm.add_user_message(large_text)

        tokens = cm.estimate_tokens()
        assert tokens > 1000

    def test_compaction_reduces_messages(self):
        cm = ContextManager()
        cm.initialize()

        # Add many messages
        for i in range(100):
            cm.add_user_message(f"User message {i}")
            cm.add_assistant_message(f"Response {i}")

        original_count = len(cm.context.messages)
        cm.compact_if_needed(max_messages=20)
        
        assert len(cm.context.messages) < original_count
        assert len(cm.context.messages) <= 20