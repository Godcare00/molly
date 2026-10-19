import { api } from './client';
import type { Conversation, ConversationCreate, Message, MessageCreate } from '@/types/api';

export const conversationsApi = {
  list: (limit = 50, offset = 0) =>
    api.get<Conversation[]>('/conversations', { query: { limit, offset } }),

  create: (body: ConversationCreate) => api.post<Conversation>('/conversations', body),

  get: (conversationId: string) => api.get<Conversation>(`/conversations/${conversationId}`),

  update: (conversationId: string, body: { title?: string; metadata?: Record<string, unknown> }) =>
    api.put<Conversation>(`/conversations/${conversationId}`, body),

  // Merges into existing metadata server-side rather than replacing it -
  // see PATCH /conversations/{id}/settings in app/api/routes.py.
  updateSettings: (conversationId: string, body: { allow_all?: boolean }) =>
    api.patch<{ status: string; allow_all: boolean }>(`/conversations/${conversationId}/settings`, body),

  remove: (conversationId: string) => api.delete<void>(`/conversations/${conversationId}`),

  getMessages: (conversationId: string, limit = 100, offset = 0) =>
    api.get<Message[]>(`/conversations/${conversationId}/messages`, { query: { limit, offset } }),

  addMessage: (conversationId: string, body: MessageCreate) =>
    api.post<Message>(`/conversations/${conversationId}/messages`, body),
};
