import { api } from './client';
import type {
  GatewayMeResponse,
  PairRequest,
  PairResponse,
  DeviceListResponse,
  DeviceResponse,
  UserResponse,
  UserRole,
} from '@/types/api';

export const authApi = {
  /**
   * Fleet pairing: exchange the one-time code printed by `molly connect`
   * on the worker for an access/refresh token pair. No prior auth.
   */
  pairDevice: (body: PairRequest) =>
    api.post<PairResponse>('/devices/pair', body, { auth: false, gatewayNative: true }),

  /**
   * Gateway-native identity. The gateway returns a device/session shape,
   * not the backend's user shape, so normalize it here for the UI.
   */
  me: async (): Promise<UserResponse> => {
    const r = await api.get<GatewayMeResponse>('/auth/me', { gatewayNative: true });
    const handle = r.email ? r.email.split('@')[0] : null;
    return {
      id: r.user_id ?? r.device_id,
      email: r.email,
      username: handle,
      display_name: handle ?? r.device_name,
      avatar_url: null,
      role: (r.role as UserRole) || 'member',
      is_active: true,
      created_at: '',
      last_login_at: null,
    };
  },

  logout: () => api.post<void>('/auth/logout', undefined, { gatewayNative: true }),

  // --- Self-hosted backend only ---------------------------------------
  // The gateway has no device list/trust routes; these 404 in fleet mode
  // and are kept so the self-hosted target still compiles.
  listDevices: () => api.get<DeviceListResponse>('/auth/devices'),

  getDevice: (deviceId: string) => api.get<DeviceResponse>(`/auth/devices/${deviceId}`),

  revokeDevice: (deviceId: string, reason?: string) =>
    api.post<DeviceResponse>(`/auth/devices/${deviceId}/revoke`, { reason }),

  setDeviceTrust: (deviceId: string, isTrusted: boolean) =>
    api.post<DeviceResponse>(`/auth/devices/${deviceId}/trust`, { is_trusted: isTrusted }),

  logoutAll: () => api.post<void>('/auth/logout-all'),
};
