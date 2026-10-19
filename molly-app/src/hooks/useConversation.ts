import { useCallback, useEffect, useState } from 'react';
import { conversationsApi } from '@/api/conversations';
import { useWebSocket, type WsAttachment, type WsEvent } from '@/context/WebSocketContext';
import type { Message } from '@/types/api';

interface UseConversationResult {
  messages: Message[];
  loading: boolean;
  error: string | null;
  sending: boolean;
  /** True while the agent is actively working on a run for this conversation. */
  agentRunning: boolean;
  reload: () => Promise<void>;
  sendMessage: (text: string, attachments?: WsAttachment[]) => void;
  /** Cancels the agent's current run (WS `stop`). */
  stop: () => void;
}

let localIdCounter = 0;
const nextLocalId = () => `local-${Date.now()}-${localIdCounter++}`;

export function useConversation(conversationId: string | null): UseConversationResult {
  const { addListener, setActiveConversation, sendMessage: sendWsMessage, stop: stopWs } = useWebSocket();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [agentRunning, setAgentRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!conversationId) return;
    setLoading(true);
    setError(null);
    try {
      const history = await conversationsApi.getMessages(conversationId);
      setMessages(history);
    } catch (err: any) {
      setError(err?.message ?? 'Could not load this conversation.');
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    reload();
  }, [reload]);

  // The backend's socket is scoped to a single conversation (no
  // subscribe/unsubscribe) — point the shared connection at this one while
  // it's open, and release it on the way out.
  useEffect(() => {
    setActiveConversation(conversationId);
    return () => setActiveConversation(null);
  }, [conversationId, setActiveConversation]);

  useEffect(() => {
    if (!conversationId) return;

    const handle = (event: WsEvent) => {
      switch (event.type) {
        case 'agent_started':
          setAgentRunning(true);
          setSending(false);
          break;
        case 'agent_completed':
        case 'agent_cancelled':
          setAgentRunning(false);
          // The socket reports outcomes, not full records — refresh from
          // the canonical REST history once a run settles.
          reload();
          break;
        case 'agent_error':
          setAgentRunning(false);
          setError(event.error);
          reload();
          break;
        case 'tool_completed':
        case 'tool_failed':
        case 'tool_error':
        case 'tool_timeout':
          // Pick up the tool call's result/status on the message it belongs to.
          reload();
          break;
        case 'live_transcript':
          // Voice turns are persisted server-side as they finalize; pick
          // them up the same way a completed tool call's result is picked
          // up above, rather than trying to reconstruct them from partial
          // streaming fragments.
          if (event.final) reload();
          break;
        default:
          break;
      }
    };

    return addListener(handle);
  }, [conversationId, addListener, reload]);

  const sendMessage = useCallback(
    (text: string, attachments: WsAttachment[] = []) => {
      if (!conversationId || (!text.trim() && attachments.length === 0)) return;
      const optimistic: Message = {
        id: nextLocalId(),
        conversation_id: conversationId,
        role: 'user',
        content: text,
        content_type: 'text',
        created_at: new Date().toISOString(),
      };
      setMessages((current) => [...current, optimistic]);
      setSending(true);
      setError(null);
      sendWsMessage(text, attachments);
    },
    [conversationId, sendWsMessage],
  );

  const stop = useCallback(() => stopWs(), [stopWs]);

  return { messages, loading, error, sending, agentRunning, reload, sendMessage, stop };
}
