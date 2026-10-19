import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { conversationsApi } from '@/api/conversations';
import type { Conversation } from '@/types/api';

interface ConversationsContextValue {
  conversations: Conversation[];
  loading: boolean;
  error: string | null;
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  refresh: () => Promise<void>;
  createConversation: (title?: string, projectId?: string) => Promise<Conversation>;
}

const ConversationsContext = createContext<ConversationsContextValue | null>(null);

export function ConversationsProvider({ children }: { children: React.ReactNode }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await conversationsApi.list();
      setConversations(list);
      setActiveId((current) => current ?? list[0]?.id ?? null);
    } catch (err: any) {
      setError(err?.message ?? 'Could not load conversations.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const createConversation = useCallback(async (title?: string, projectId?: string) => {
    const conversation = await conversationsApi.create({ title, project_id: projectId });
    setConversations((prev) => [conversation, ...prev]);
    setActiveId(conversation.id);
    return conversation;
  }, []);

  const value = useMemo(
    () => ({ conversations, loading, error, activeId, setActiveId, refresh, createConversation }),
    [conversations, loading, error, activeId, refresh, createConversation],
  );

  return <ConversationsContext.Provider value={value}>{children}</ConversationsContext.Provider>;
}

export function useConversations() {
  const ctx = useContext(ConversationsContext);
  if (!ctx) throw new Error('useConversations must be used within ConversationsProvider');
  return ctx;
}
