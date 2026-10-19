import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { WS_BASE_URL, getActiveWorkerId } from '@/api/client';
import { secureStorage } from '@/utils/storage';

/**
 * Matches the backend's WebSocket schema (app/agent/executor.py,
 * app/agent/live_executor.py, app/api/websocket.py). Unlike the old
 * placeholder protocol, this one has NO subscribe/unsubscribe multiplexing —
 * a socket is scoped to a single conversation for the life of the
 * connection (the `connected` event confirms this by echoing back
 * `conversation_id`). So this provider holds one real connection to
 * whichever conversation is "active" and tears it down/reconnects when that
 * changes, instead of one global socket fanning out to many conversations.
 *
 * The connect URL is `/ws/conversations/{id}` (verified against
 * app/api/websocket.py's `@router.websocket(...)` decorator directly — a
 * prior version of this file guessed `/conversations/{id}/ws`, which was
 * wrong and would have 404'd every connection attempt).
 *
 * Hands-free voice mode reuses this exact same socket rather than opening a
 * second connection: `live_start` flips the current conversation into a
 * Gemini Live session on the backend, `audio_chunk` frames stream mic audio
 * up, and `audio_output` frames stream Gemini's speech back down — all
 * multiplexed alongside the regular text/approval events, so a tool call
 * Molly makes mid-voice-session still shows the exact same approval card.
 */

import type { MessageAttachment } from '@/types/api';

export type WsAttachment = { type: 'image'; image_id: string } | { type: 'file'; file_id: string };

export type WsEvent =
  | { type: 'connected'; conversation_id: string; user_id: string; timestamp: string }
  | { type: 'agent_started'; task: Record<string, unknown> } // full AgentState — see app/agent/state.py
  | { type: 'agent_completed'; response: string; attachments?: MessageAttachment[] }
  | { type: 'agent_error'; error: string }
  | { type: 'agent_cancelled' }
  | { type: 'tool_started'; tool_call_id: string; tool: string; arguments: Record<string, unknown> }
  | {
      type: 'tool_completed';
      tool_call_id: string;
      tool: string;
      result: unknown;
      truncated: boolean;
      // Only present for a share_file call — see
      // AgentExecutor._register_shared_attachment in app/agent/executor.py.
      attachment?: MessageAttachment;
    }
  | { type: 'tool_failed'; tool_call_id: string; tool: string; error: string }
  | { type: 'tool_error'; tool_call_id: string; tool: string; error: string }
  | { type: 'tool_timeout'; tool_call_id: string; tool: string }
  | {
      type: 'approval_required';
      approval_id: string;
      tool: string;
      risk_level: string;
      reason: string;
      arguments: Record<string, unknown>;
    }
  | { type: 'approval_rejected'; approval_id: string }
  | { type: 'approval_corrected'; approval_id: string; instruction: string }
  | { type: 'approval_timeout'; approval_id: string }
  | { type: 'approval_approved'; approval_id: string; tool: string; scope: 'once' | 'task' }
  // Skipped the prompt entirely - conversation allow_all or a prior
  // "approve all" trusted this tool for the task. Still shown as an
  // (already-resolved) approval so the activity feed has a record of it.
  | { type: 'approval_auto'; approval_id: string; tool: string; risk_level: string; reason: 'allow_all' | 'trusted_for_task' }
  // --- Hands-free voice mode (app/agent/live_executor.py) ---
  | { type: 'live_started'; task_id: string }
  | { type: 'audio_output'; data: string } // base64 PCM16 mono 24kHz
  | { type: 'live_transcript'; role: 'user' | 'assistant'; text: string; final: boolean }
  | { type: 'live_interrupted' } // person started talking over Molly — flush queued playback
  | { type: 'live_stopped' }
  | { type: 'live_error'; error: string }
  | { type: 'pong'; timestamp: string }
  | { type: 'error'; error: string };

type ConnectionState = 'idle' | 'connecting' | 'open' | 'closed';

interface WebSocketContextValue {
  state: ConnectionState;
  /** Connects the socket to this conversation (and disconnects the previous one). Pass null to disconnect. */
  setActiveConversation: (conversationId: string | null) => void;
  sendMessage: (content: string, attachments?: WsAttachment[]) => void;
  respondToApproval: (approvalId: string, action: 'approve' | 'approve_all' | 'reject' | 'correct', instruction?: string) => void;
  stop: () => void;
  addListener: (fn: (event: WsEvent) => void) => () => void;
  // --- Hands-free voice mode ---
  startLive: () => void;
  stopLive: () => void;
  /** `pcm16Base64` is a base64-encoded PCM16 mono 16kHz chunk. */
  sendAudioChunk: (pcm16Base64: string) => void;
  sendAudioStreamEnd: () => void;
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null);

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 15000];

export function WebSocketProvider({
  enabled,
  children,
}: {
  enabled: boolean;
  children: React.ReactNode;
}) {
  const [state, setState] = useState<ConnectionState>('idle');
  const socketRef = useRef<WebSocket | null>(null);
  const listenersRef = useRef<Set<(event: WsEvent) => void>>(new Set());
  const conversationIdRef = useRef<string | null>(null);
  const attemptRef = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedByUsRef = useRef(false);

  const send = useCallback((payload: object) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  }, []);

  const teardown = useCallback(() => {
    closedByUsRef.current = true;
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    socketRef.current?.close();
    socketRef.current = null;
    setState('idle');
  }, []);

  const connect = useCallback(async () => {
    const conversationId = conversationIdRef.current;
    if (!enabled || !conversationId) return;
    const { accessToken } = await secureStorage.getTokens();
    if (!accessToken) return;

    closedByUsRef.current = false;
    setState('connecting');
    // In fleet mode this is `/w/{worker_id}/ws/conversations/{id}` - see
    // gateway/app/api/mobile_ws.py, which deliberately kept the suffix
    // identical so nothing else about this socket's message handling
    // below has to change between self-hosted and fleet mode.
    const workerId = getActiveWorkerId();
    const prefix = workerId ? `/w/${workerId}` : '';
    const socket = new WebSocket(
      `${WS_BASE_URL}${prefix}/ws/conversations/${conversationId}?token=${encodeURIComponent(accessToken)}`,
    );
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      setState('open');
    };

    socket.onmessage = (event) => {
      try {
        const parsed: WsEvent = JSON.parse(event.data);
        listenersRef.current.forEach((fn) => fn(parsed));
      } catch {
        // Ignore malformed frames rather than crash the connection.
      }
    };

    socket.onerror = () => {
      // onclose follows and handles reconnection.
    };

    socket.onclose = () => {
      setState('closed');
      socketRef.current = null;
      // Don't reconnect if we closed it on purpose, the provider was
      // disabled, or the active conversation moved on while we were open.
      if (closedByUsRef.current || !enabled || conversationIdRef.current !== conversationId) return;
      const delay = RECONNECT_DELAYS_MS[Math.min(attemptRef.current, RECONNECT_DELAYS_MS.length - 1)];
      attemptRef.current += 1;
      reconnectTimer.current = setTimeout(connect, delay);
    };
  }, [enabled]);

  const setActiveConversation = useCallback(
    (conversationId: string | null) => {
      if (conversationIdRef.current === conversationId) return;
      teardown();
      conversationIdRef.current = conversationId;
      attemptRef.current = 0;
      if (conversationId) connect();
    },
    [connect, teardown],
  );

  useEffect(() => {
    if (!enabled) teardown();
    return teardown;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // Lightweight heartbeat so idle connections aren't reaped by intermediaries.
  useEffect(() => {
    if (state !== 'open') return;
    const interval = setInterval(() => send({ type: 'ping' }), 25000);
    return () => clearInterval(interval);
  }, [state, send]);

  const sendMessage = useCallback(
    (content: string, attachments: WsAttachment[] = []) => {
      send({ type: 'message', content, attachments });
    },
    [send],
  );

  const respondToApproval = useCallback(
    (approvalId: string, action: 'approve' | 'approve_all' | 'reject' | 'correct', instruction?: string) => {
      send({ type: 'approval_response', approval_id: approvalId, action, instruction });
    },
    [send],
  );

  const stop = useCallback(() => send({ type: 'stop' }), [send]);

  const startLive = useCallback(() => send({ type: 'live_start' }), [send]);
  const stopLive = useCallback(() => send({ type: 'live_stop' }), [send]);
  const sendAudioChunk = useCallback((pcm16Base64: string) => send({ type: 'audio_chunk', data: pcm16Base64 }), [send]);
  const sendAudioStreamEnd = useCallback(() => send({ type: 'audio_stream_end' }), [send]);

  const addListener = useCallback((fn: (event: WsEvent) => void) => {
    listenersRef.current.add(fn);
    return () => listenersRef.current.delete(fn);
  }, []);

  return (
    <WebSocketContext.Provider
      value={{
        state,
        setActiveConversation,
        sendMessage,
        respondToApproval,
        stop,
        addListener,
        startLive,
        stopLive,
        sendAudioChunk,
        sendAudioStreamEnd,
      }}
    >
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocket() {
  const ctx = useContext(WebSocketContext);
  if (!ctx) throw new Error('useWebSocket must be used within WebSocketProvider');
  return ctx;
}
