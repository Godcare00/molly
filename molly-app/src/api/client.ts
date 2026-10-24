import { secureStorage } from '@/utils/storage';
import type { ApiErrorBody, RefreshResponse } from '@/types/api';

// In fleet/gateway mode, both of these point at the shared gateway, not at
// a VPS directly - see gateway/README.md. In self-hosted/Tailscale mode
// (the original single-tenant deployment), point these at the worker
// itself and leave ACTIVE_WORKER_ID unset; buildUrl/buildWsUrl below then
// add no prefix and everything behaves exactly as before this split.
export const API_BASE_URL = 'https://molly.devs.surf';
export const WS_BASE_URL = 'wss://molly.devs.surf';

export class ApiError extends Error {
  status: number;
  body?: ApiErrorBody;
  constructor(status: number, message: string, body?: ApiErrorBody) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export class NetworkError extends Error {}

// --- fleet mode: which of the tenant's workers this session talks to ---
//
// Set once pairing completes (the pairing-session approval response
// includes default_worker_id - see gateway/app/api/admin_devices.py) and
// persisted so it survives app restarts. Endpoints that are proxied
// through to a specific VPS (conversations, approvals, images, files,
// projects, settings, and the conversation WebSocket) get this prefixed
// onto their path; endpoints the gateway itself answers (auth/refresh,
// device pairing) never do - see workerPrefixedUrl vs gatewayUrl below.
let activeWorkerId: string | null = null;

export async function setActiveWorkerId(workerId: string | null) {
  activeWorkerId = workerId;
  await secureStorage.setActiveWorkerId(workerId);
}

export function getActiveWorkerId(): string | null {
  return activeWorkerId;
}

/** Call once at startup (e.g. from AuthContext) after loading whatever
 * was persisted from the last successful pairing/login. */
export async function restoreActiveWorkerId() {
  activeWorkerId = await secureStorage.getActiveWorkerId();
}

function workerPathPrefix(): string {
  return activeWorkerId ? `/w/${activeWorkerId}` : '';
}

type RefreshWaiter = { resolve: (token: string | null) => void };
let refreshInFlight: Promise<string | null> | null = null;
let waiters: RefreshWaiter[] = [];

async function performRefresh(): Promise<string | null> {
  const { refreshToken } = await secureStorage.getTokens();
  if (!refreshToken) return null;
  try {
    // Token refresh is a gateway-native concern (the gateway owns
    // sessions/JWTs in fleet mode), not proxied to a worker - hence
    // API_BASE_URL directly, with no workerPathPrefix().
    const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      await secureStorage.clearTokens();
      return null;
    }
    const data: RefreshResponse = await res.json();
    await secureStorage.setTokens(data.access_token, data.refresh_token);
    return data.access_token;
  } catch {
    return null;
  }
}

/** De-duplicates concurrent refresh attempts into a single network call. */
async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) {
    return new Promise((resolve) => {
      waiters.push({ resolve });
    });
  }
  refreshInFlight = performRefresh();
  const token = await refreshInFlight;
  refreshInFlight = null;
  waiters.forEach((w) => w.resolve(token));
  waiters = [];
  return token;
}

/** Called by AuthContext when a refresh fails so the app can drop to the pairing screen. */
let onSessionExpired: (() => void) | null = null;
export function setSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler;
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  auth?: boolean; // defaults to true
  isForm?: boolean;
  signal?: AbortSignal;
  /**
   * Set for endpoints the gateway itself answers (/auth/me, /auth/logout,
   * /devices/pair, /auth/refresh). Without it, a signed-in session's
   * worker id gets prefixed and the request is proxied to the worker,
   * which has no such routes.
   */
  gatewayNative?: boolean;
}

function buildUrl(path: string, query?: RequestOptions['query'], gatewayNative = false) {
  const url = new URL((gatewayNative ? '' : workerPathPrefix()) + path, API_BASE_URL);
  if (query) {
    Object.entries(query).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v));
    });
  }
  return url.toString();
}

async function request<T>(path: string, options: RequestOptions = {}, isRetry = false): Promise<T> {
  const { method = 'GET', body, query, auth = true, isForm = false, signal, gatewayNative = false } = options;

  const headers: Record<string, string> = {};
  if (!isForm) headers['Content-Type'] = 'application/json';

  if (auth) {
    const { accessToken } = await secureStorage.getTokens();
    if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query, gatewayNative), {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    throw new NetworkError('Could not reach Molly. Check your connection and try again.');
  }

  if (response.status === 401 && auth && !isRetry) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      return request<T>(path, options, true);
    }
    onSessionExpired?.();
    throw new ApiError(401, 'Session expired');
  }

  if (!response.ok) {
    let parsed: ApiErrorBody | undefined;
    try {
      parsed = await response.json();
    } catch {
      // ignore non-json error bodies
    }
    const detail = parsed?.detail;
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
        ? detail.map((d) => d.msg).join(', ')
        : detail && typeof detail === 'object' && 'message' in detail
        ? detail.message
        : `Request failed (${response.status})`;
    throw new ApiError(response.status, message, parsed);
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'DELETE' }),
};
