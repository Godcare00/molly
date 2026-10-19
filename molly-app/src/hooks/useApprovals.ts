import { useCallback, useEffect, useState } from 'react';
import { approvalsApi } from '@/api/approvals';
import { useWebSocket, type WsEvent } from '@/context/WebSocketContext';
import type { Approval } from '@/types/api';

export function useApprovals(conversationId?: string) {
  const { addListener, respondToApproval } = useWebSocket();
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await approvalsApi.list(conversationId ? { conversation_id: conversationId } : undefined);
      setApprovals(list);
    } catch (err: any) {
      setError(err?.message ?? 'Could not load approvals.');
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    reload();
  }, [reload]);

  // The socket only carries the fields needed to act on an approval in the
  // moment (approval_id, tool, risk_level, ...) — not the full Approval
  // record the REST list returns. Treat these as "something changed,
  // refetch" signals rather than fabricating an Approval from partial data.
  //
  // Also note: the backend's socket is scoped to a single conversation (no
  // global multiplexed feed), so this only fires while `conversationId`
  // matches whichever conversation currently has the socket open — a
  // conversation-less call (e.g. an activity feed across all conversations)
  // won't get live pushes and should fall back to polling `reload`.
  useEffect(() => {
    if (!conversationId) return;
    const APPROVAL_EVENTS = new Set([
      'approval_required',
      'approval_rejected',
      'approval_corrected',
      'approval_timeout',
      'approval_approved',
      'approval_auto',
    ]);
    const handle = (event: WsEvent) => {
      if (APPROVAL_EVENTS.has(event.type)) reload();
    };
    return addListener(handle);
  }, [conversationId, addListener, reload]);

  // Resolution goes over the websocket, not the REST /approvals endpoints.
  // The running agent is blocked inside AgentExecutor waiting on an
  // approval_response socket message (see resolve_approval in
  // app/agent/executor.py) - the REST endpoints only update the stored
  // record for history/listing and never reach a running task, so calling
  // them here wouldn't actually unblock anything.
  const respond = useCallback(
    (approvalId: string, action: 'approve' | 'approve_all' | 'reject' | 'correct', instruction?: string) => {
      respondToApproval(approvalId, action, instruction);
      // Optimistically drop it from the pending list; the eventual
      // approval_approved/rejected/corrected event (or a reload) reconciles
      // state across other connected clients.
      setApprovals((current) => current.filter((a) => a.id !== approvalId));
    },
    [respondToApproval],
  );

  const pending = approvals.filter((a) => a.status === 'pending');

  return { approvals, pending, loading, error, reload, respond };
}
