import { api } from './client';
import type { Approval, CorrectRequest } from '@/types/api';

export const approvalsApi = {
  list: (filters?: { conversation_id?: string; task_id?: string; status?: string; limit?: number }) =>
    api.get<Approval[]>('/approvals', { query: filters }),

  get: (approvalId: string) => api.get<Approval>(`/approvals/${approvalId}`),

  approve: (approvalId: string) => api.post<Approval>(`/approvals/${approvalId}/approve`),

  reject: (approvalId: string) => api.post<Approval>(`/approvals/${approvalId}/reject`),

  correct: (approvalId: string, body: CorrectRequest) =>
    api.post<Approval>(`/approvals/${approvalId}/correct`, body),
};
