import { api } from './client';
import type { ProviderSettings, ProviderChainSettings } from '@/types/api';

export const settingsApi = {
  getProvider: () => api.get<ProviderSettings & { api_key: string }>('/settings/provider'),

  updateProvider: (body: ProviderSettings) => api.put<void>('/settings/provider', body),

  testProvider: (body: ProviderSettings) =>
    api.post<{ ok: boolean; message?: string }>('/settings/provider/test', body),

  getProviderChain: () => api.get<ProviderChainSettings>('/settings/providers'),

  updateProviderChain: (body: ProviderChainSettings) =>
    api.put<ProviderChainSettings & { status: string; message: string }>('/settings/providers', body),
};
