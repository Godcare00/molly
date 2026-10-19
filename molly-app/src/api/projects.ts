import { api } from './client';
import type { Project, ProjectCreate, ProjectUpdate } from '@/types/api';

export const projectsApi = {
  list: () => api.get<Project[]>('/projects'),

  create: (body: ProjectCreate) => api.post<Project>('/projects', body),

  get: (projectId: string) => api.get<Project>(`/projects/${projectId}`),

  update: (projectId: string, body: ProjectUpdate) => api.put<Project>(`/projects/${projectId}`, body),

  remove: (projectId: string) => api.delete<void>(`/projects/${projectId}`),
};
