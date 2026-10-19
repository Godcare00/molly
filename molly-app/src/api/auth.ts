import { api } from './client';
import type {
  DeviceRegisterRequest,
  DeviceRegisterResponse,
  DeviceVerifyRequest,
  TokenPair,
  DeviceListResponse,
  DeviceResponse,
  UserResponse,
} from '@/types/api';

export const authApi = {
  registerDevice: (body: DeviceRegisterRequest) =>
    api.post<DeviceRegisterResponse>('/auth/device/register', body, { auth: false }),

  verifyDevice: (body: DeviceVerifyRequest) =>
    api.post<TokenPair>('/auth/device/verify', body, { auth: false }),

  me: () => api.get<UserResponse>('/auth/me'),

  listDevices: () => api.get<DeviceListResponse>('/auth/devices'),

  getDevice: (deviceId: string) => api.get<DeviceResponse>(`/auth/devices/${deviceId}`),

  revokeDevice: (deviceId: string, reason?: string) =>
    api.post<DeviceResponse>(`/auth/devices/${deviceId}/revoke`, { reason }),

  setDeviceTrust: (deviceId: string, isTrusted: boolean) =>
    api.post<DeviceResponse>(`/auth/devices/${deviceId}/trust`, { is_trusted: isTrusted }),

  logout: () => api.post<void>('/auth/logout'),

  logoutAll: () => api.post<void>('/auth/logout-all'),
};
