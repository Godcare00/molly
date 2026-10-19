from fastapi import WebSocketDisconnect
from typing import Dict, Set, Optional, Protocol, Any, runtime_checkable
import asyncio
import base64
import json
import uuid
from datetime import datetime

from app.agent.executor import AgentExecutor
from app.agent.live_executor import LiveAgentExecutor
from app.storage.conversations import get_conversation, add_message
from app.config import settings
from molly_tunnel_protocol import RelayAuthUser

# Active connections: conversation_id -> set of sockets. Holds
# app.tunnel.channel.TunnelChannel objects - the gateway terminates the
# mobile WebSocket itself and relays over this worker's tunnel, which is
# the only transport this worker answers on now (see
# app/tunnel/client.py). SocketLike below exists so the message loop
# doesn't otherwise need to know anything about that transport.
active_connections: Dict[str, Set["SocketLike"]] = {}


@runtime_checkable
class SocketLike(Protocol):
    """The subset of a transport that handle_conversation_socket needs -
    satisfied by app.tunnel.channel.TunnelChannel."""
    async def send_json(self, data: dict) -> None: ...
    async def receive_json(self) -> dict: ...
    async def close(self, code: int = 1000, reason: str = "") -> None: ...


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[Any]] = {}
        self.running_agents: Dict[str, AgentExecutor] = {}
        self.running_live_agents: Dict[str, LiveAgentExecutor] = {}

    async def connect(self, socket: Any, conversation_id: str):
        if conversation_id not in self.active_connections:
            self.active_connections[conversation_id] = set()
        self.active_connections[conversation_id].add(socket)

    def disconnect(self, socket: Any, conversation_id: str):
        if conversation_id in self.active_connections:
            self.active_connections[conversation_id].discard(socket)
            if not self.active_connections[conversation_id]:
                del self.active_connections[conversation_id]

    async def send_event(self, conversation_id: str, event: dict):
        if conversation_id in self.active_connections:
            dead = set()
            for sock in self.active_connections[conversation_id]:
                try:
                    await sock.send_json(event)
                except Exception:
                    dead.add(sock)
            for sock in dead:
                self.disconnect(sock, conversation_id)

    async def broadcast(self, event: dict):
        for conv_id in list(self.active_connections.keys()):
            await self.send_event(conv_id, event)


manager = ConnectionManager()


async def handle_conversation_socket(socket: Any, conversation_id: str, auth_user: RelayAuthUser) -> None:
    """
    The full realtime message loop for one conversation. Called by
    app.tunnel.client.TunnelClient once it's verified the gateway's relay
    token for an incoming WS_OPEN frame - see ARCHITECTURE.md's "Fleet
    Mode" section. `socket` is an app.tunnel.channel.TunnelChannel; this
    function doesn't accept() or authenticate anything itself, since
    that's already done by the time it's called.
    """
    conv = get_conversation(conversation_id)
    if not conv:
        await socket.close(code=4004, reason="Conversation not found")
        return

    await manager.connect(socket, conversation_id)

    # Send connection established
    await socket.send_json({
        "type": "connected",
        "conversation_id": conversation_id,
        "user_id": auth_user.user_id,
        "timestamp": datetime.utcnow().isoformat(),
    })

    current_agent: Optional[AgentExecutor] = None
    current_live: Optional[LiveAgentExecutor] = None
    live_pump_task: Optional[asyncio.Task] = None

    async def pump_live_events(live: LiveAgentExecutor):
        """Forwards LiveAgentExecutor's events to the socket. Runs as its own
        task, concurrently with the main receive loop below, so audio_chunk
        messages keep flowing in while Molly is mid-turn or waiting on a
        spoken approval - see live_executor.py's module docstring for why
        that concurrency matters."""
        try:
            async for event in live.start():
                await socket.send_json(event)
        except Exception as e:
            try:
                await socket.send_json({"type": "live_error", "error": str(e)})
            except Exception:
                pass

    try:
        while True:
            data = await socket.receive_json()

            msg_type = data.get("type")

            if msg_type == "live_start":
                if current_live is None:
                    current_live = LiveAgentExecutor(conversation_id)
                    manager.running_live_agents[conversation_id] = current_live
                    live_pump_task = asyncio.ensure_future(pump_live_events(current_live))

            elif msg_type == "audio_chunk":
                if current_live:
                    try:
                        await current_live.push_audio_chunk(base64.b64decode(data.get("data", "")))
                    except Exception:
                        pass  # a dropped chunk shouldn't kill the session

            elif msg_type == "audio_stream_end":
                if current_live:
                    await current_live.push_audio_stream_end()

            elif msg_type == "live_stop":
                if current_live:
                    await current_live.stop()
                if live_pump_task:
                    await live_pump_task
                if conversation_id in manager.running_live_agents:
                    del manager.running_live_agents[conversation_id]
                current_live = None
                live_pump_task = None

            elif msg_type == "message":
                # User message
                content = data.get("content", "")
                attachments = data.get("attachments", [])
                image_ids = [a.get("image_id") for a in attachments if a.get("type") == "image"]
                file_ids = [a.get("file_id") for a in attachments if a.get("type") == "file"]

                # Store user message
                add_message(
                    conversation_id,
                    "user",
                    content,
                    content_type="text",
                    metadata={"image_ids": image_ids, "file_ids": file_ids},
                )

                # Create and run agent
                current_agent = AgentExecutor(conversation_id)
                manager.running_agents[conversation_id] = current_agent

                async for event in current_agent.run(content, image_ids, file_ids):
                    await socket.send_json(event)

                    # If agent needs approval, wait for user response
                    if event.get("type") == "approval_required":
                        # Agent will wait internally for resolve_approval call
                        pass

                # Clean up
                if conversation_id in manager.running_agents:
                    del manager.running_agents[conversation_id]
                current_agent = None

            elif msg_type == "approval_response":
                # Handle approval response. A live voice session takes
                # priority since only one of the two is ever active for a
                # given conversation at a time (starting live mode is a
                # deliberate mode switch on the same thread) - this just
                # picks whichever one actually has the pending approval.
                approval_id = data.get("approval_id")
                action = data.get("action")  # approve, reject, correct
                instruction = data.get("instruction")

                if current_live:
                    current_live.resolve_approval_from_app(approval_id, action, instruction)
                elif current_agent:
                    current_agent.resolve_approval(approval_id, action, instruction)

            elif msg_type == "questionnaire_response":
                # Handle the user's answers to an ask_user questionnaire.
                # Same "whichever session actually has it pending" logic as
                # approval_response.
                questionnaire_id = data.get("questionnaire_id")
                answers = data.get("answers")  # list of lists, one per question

                if current_agent:
                    current_agent.resolve_questionnaire(questionnaire_id, answers)

            elif msg_type == "stop":
                # Stop current agent / live session
                if current_agent:
                    current_agent.cancel()
                if conversation_id in manager.running_agents:
                    del manager.running_agents[conversation_id]
                if current_live:
                    current_live.cancel()

            elif msg_type == "ping":
                await socket.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat()})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await socket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass  # socket's already gone (e.g. tunnel dropped mid-turn) - nothing left to tell
    finally:
        manager.disconnect(socket, conversation_id)
        if current_agent:
            current_agent.cancel()
        if conversation_id in manager.running_agents:
            del manager.running_agents[conversation_id]
        if current_live:
            current_live.cancel()
        if live_pump_task:
            live_pump_task.cancel()
        if conversation_id in manager.running_live_agents:
            del manager.running_live_agents[conversation_id]


async def send_approval_event(conversation_id: str, approval_data: dict):
    """Send approval event to all connected clients for a conversation."""
    await manager.send_event(conversation_id, {
        "type": "approval_required",
        **approval_data,
    })