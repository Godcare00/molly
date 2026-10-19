from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from pydantic import BaseModel

from app.storage.conversations import (
    create_conversation,
    get_conversation,
    list_conversations,
    update_conversation,
    delete_conversation,
    add_message,
    get_messages,
    get_recent_messages,
)
from app.auth.dependencies import get_current_user
from app.llm.client import find_chain_entry_for_model
from app.llm.base import REASONING_EFFORT_LEVELS

router = APIRouter(prefix="/conversations", tags=["conversations"], dependencies=[Depends(get_current_user)])


VALID_MODES = {"general", "bug_bounty"}


class ConversationCreate(BaseModel):
    title: str = ""
    # "general" (default) - operate this server.
    # "bug_bounty" - authorized security testing / vulnerability research
    # persona and workflow (see app/agent/context.py's BUG_BOUNTY_SYSTEM_PROMPT).
    # Tool permissions and the approval flow are identical in both modes;
    # this only changes framing, methodology, and reporting style.
    mode: str = "general"


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    metadata: Optional[dict] = None


class ConversationSettingsUpdate(BaseModel):
    # When true, Molly skips the approval prompt for MODERATE/HIGH_RISK
    # actions in this conversation (file writes/edits, package installs,
    # service restarts, etc). DANGEROUS/CRITICAL actions (destructive
    # commands, sensitive-path access) still always require approval -
    # this setting can't waive that floor.
    allow_all: Optional[bool] = None
    # Switch this conversation's mode - see ConversationCreate.mode above.
    # Takes effect on the next message (mode is read fresh from metadata
    # at the start of each AgentExecutor.run(), same as allow_all).
    mode: Optional[str] = None
    # Pin this conversation to one specific configured model (see GET
    # /settings/available-models) instead of the automatic primary/
    # fallback chain. Must match a model currently in the provider chain -
    # send "" to clear the pin and go back to automatic. `model_provider`
    # only matters if two chain entries share the same model string on
    # different providers; otherwise leave it unset.
    model: Optional[str] = None
    model_provider: Optional[str] = None
    # "off" (default)/"low"/"medium"/"high" - see app/llm/base.py's
    # REASONING_EFFORT_LEVELS. Applied on every LLM call in a run, not just
    # the first - see AgentExecutor.run() and Message.thinking_blocks for
    # how thinking blocks get preserved across the tool-calling loop.
    reasoning_effort: Optional[str] = None


class MessageCreate(BaseModel):
    role: str
    content: str
    content_type: str = "text"
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None
    metadata: Optional[dict] = None


@router.post("")
async def create_conversation_endpoint(request: ConversationCreate):
    """Create a new conversation."""
    mode = request.mode or "general"
    if mode not in VALID_MODES:
        raise HTTPException(400, f"Unknown mode '{mode}'. Valid modes: {sorted(VALID_MODES)}")

    conv = create_conversation(request.title, metadata={"mode": mode})
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "mode": mode,
    }


@router.get("")
async def list_conversations_endpoint(
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
):
    """List conversations."""
    convs = list_conversations(limit, offset)
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
        }
        for c in convs
    ]


@router.get("/{conversation_id}")
async def get_conversation_endpoint(conversation_id: str):
    """Get conversation details."""
    conv = get_conversation(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "metadata": conv.metadata,
        "mode": conv.metadata.get("mode", "general"),
        "model": conv.metadata.get("model"),
        "model_provider": conv.metadata.get("model_provider"),
        "reasoning_effort": conv.metadata.get("reasoning_effort", "off"),
    }


@router.put("/{conversation_id}")
async def update_conversation_endpoint(conversation_id: str, request: ConversationUpdate):
    """Update conversation."""
    conv = get_conversation(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    update_conversation(conversation_id, request.title, request.metadata)
    return {"status": "updated"}


@router.patch("/{conversation_id}/settings")
async def update_conversation_settings(conversation_id: str, request: ConversationSettingsUpdate):
    """Update per-conversation agent settings (currently just allow_all).

    Merges into existing metadata rather than replacing it, unlike the
    generic PUT above, so toggling allow_all can't clobber unrelated
    metadata someone else set on the conversation.
    """
    conv = get_conversation(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    metadata = dict(conv.metadata)
    if request.allow_all is not None:
        metadata["allow_all"] = request.allow_all
    if request.mode is not None:
        if request.mode not in VALID_MODES:
            raise HTTPException(400, f"Unknown mode '{request.mode}'. Valid modes: {sorted(VALID_MODES)}")
        metadata["mode"] = request.mode
    if request.model is not None:
        if request.model == "":
            # Explicit clear - go back to the automatic primary/fallback chain.
            metadata.pop("model", None)
            metadata.pop("model_provider", None)
        else:
            if find_chain_entry_for_model(request.model, request.model_provider) is None:
                raise HTTPException(
                    400,
                    f"'{request.model}' doesn't match any configured model. "
                    "Check GET /settings/available-models for valid options.",
                )
            metadata["model"] = request.model
            if request.model_provider is not None:
                metadata["model_provider"] = request.model_provider
    if request.reasoning_effort is not None:
        if request.reasoning_effort not in REASONING_EFFORT_LEVELS:
            raise HTTPException(400, f"Unknown reasoning_effort '{request.reasoning_effort}'. Valid values: {REASONING_EFFORT_LEVELS}")
        metadata["reasoning_effort"] = request.reasoning_effort

    update_conversation(conversation_id, metadata=metadata)
    return {
        "status": "updated",
        "allow_all": metadata.get("allow_all", False),
        "mode": metadata.get("mode", "general"),
        "model": metadata.get("model"),
        "model_provider": metadata.get("model_provider"),
        "reasoning_effort": metadata.get("reasoning_effort", "off"),
    }


@router.delete("/{conversation_id}")
async def delete_conversation_endpoint(conversation_id: str):
    """Delete a conversation."""
    conv = get_conversation(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    delete_conversation(conversation_id)
    return {"status": "deleted"}


@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    """Get messages for a conversation."""
    conv = get_conversation(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    messages = get_messages(conversation_id, limit, offset)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "content_type": m.content_type,
            "tool_calls": m.tool_calls,
            "tool_call_id": m.tool_call_id,
            "metadata": m.metadata,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


@router.post("/{conversation_id}/messages")
async def add_message_endpoint(conversation_id: str, request: MessageCreate):
    """Add a message to a conversation."""
    conv = get_conversation(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    msg = add_message(
        conversation_id,
        request.role,
        request.content,
        request.content_type,
        request.tool_calls,
        request.tool_call_id,
        request.metadata,
    )

    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "content_type": msg.content_type,
        "created_at": msg.created_at.isoformat(),
    }