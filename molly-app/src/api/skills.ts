import { api } from './client';
import type { Skill, SkillInfo, SkillWrite } from '@/types/api';

export const skillsApi = {
  list: () => api.get<{ skills: SkillInfo[] }>('/skills'),

  get: (name: string) => api.get<Skill>(`/skills/${encodeURIComponent(name)}`),

  // Same endpoint creates or overwrites - the backend only distinguishes
  // by whether the name already exists, so there's no separate create().
  put: (name: string, body: SkillWrite) =>
    api.put<Skill & { status: string }>(`/skills/${encodeURIComponent(name)}`, body),

  remove: (name: string) => api.delete<{ status: string }>(`/skills/${encodeURIComponent(name)}`),
};
