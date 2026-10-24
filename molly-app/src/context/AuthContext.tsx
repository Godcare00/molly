import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Platform as RNPlatform } from 'react-native';
import { authApi } from '@/api/auth';
import { restoreActiveWorkerId, setActiveWorkerId, setSessionExpiredHandler } from '@/api/client';
import { secureStorage } from '@/utils/storage';
import type { UserResponse } from '@/types/api';

type AuthStatus = 'loading' | 'unauthenticated' | 'pairing' | 'authenticated';

interface AuthContextValue {
  status: AuthStatus;
  user: UserResponse | null;
  pairingError: string | null;
  /** Exchange the one-time code printed by `molly connect` for a session. */
  pair: (code: string) => Promise<void>;
  cancelPairing: () => void;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function devicePlatform(): 'ios' | 'android' | 'web' {
  if (RNPlatform.OS === 'ios') return 'ios';
  if (RNPlatform.OS === 'android') return 'android';
  return 'web';
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<UserResponse | null>(null);
  const [pairingError, setPairingError] = useState<string | null>(null);
  const cancelledRef = useRef(false);

  const refreshUser = useCallback(async () => {
    const me = await authApi.me();
    setUser(me);
  }, []);

  const bootstrap = useCallback(async () => {
    // Restore the fleet worker id before any proxied request so
    // /w/{worker_id}/... URLs are built correctly after a relaunch.
    await restoreActiveWorkerId();
    const { accessToken } = await secureStorage.getTokens();
    if (!accessToken) {
      setStatus('unauthenticated');
      return;
    }
    try {
      const me = await authApi.me();
      setUser(me);
      setStatus('authenticated');
    } catch {
      setStatus('unauthenticated');
    }
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setUser(null);
      setStatus('unauthenticated');
    });
    bootstrap();
  }, [bootstrap]);

  /**
   * Fleet pairing: `molly connect` on the worker asks the gateway for a
   * short one-time code and prints it. The user types that code here; the
   * gateway exchanges it for a token pair and tells us which worker this
   * device's conversations route to.
   *
   * Whoever can read the code on the worker's own terminal is trusted to
   * pair a device - the same proximity model `molly connect` always used,
   * with no browser approval step.
   */
  const pair = useCallback(async (rawCode: string) => {
    const code = rawCode.replace(/[^0-9a-z]/gi, '').toUpperCase();
    if (!code) {
      setPairingError('Enter the code printed by `molly connect`.');
      return;
    }

    setStatus('pairing');
    setPairingError(null);
    cancelledRef.current = false;

    try {
      const deviceName =
        RNPlatform.OS === 'ios' ? 'iPhone' : RNPlatform.OS === 'android' ? 'Android device' : 'Device';

      const tokens = await authApi.pairDevice({
        code,
        name: deviceName,
        platform: devicePlatform(),
      });

      if (cancelledRef.current) return;

      await secureStorage.setTokens(tokens.access_token, tokens.refresh_token);
      await setActiveWorkerId(tokens.default_worker_id ?? null);

      const me = await authApi.me();
      setUser(me);
      setStatus('authenticated');
    } catch (err: any) {
      if (cancelledRef.current) return;
      setPairingError(err?.message ?? 'Could not pair this device. Try again.');
      setStatus('unauthenticated');
    }
  }, []);

  /** Lets the user back out while a pairing request is in flight. */
  const cancelPairing = useCallback(() => {
    cancelledRef.current = true;
    setPairingError(null);
    setStatus('unauthenticated');
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Best-effort — clear local state regardless.
    }
    await secureStorage.clearTokens();
    await setActiveWorkerId(null);
    setUser(null);
    setStatus('unauthenticated');
  }, []);

  const value = useMemo(
    () => ({ status, user, pairingError, pair, cancelPairing, logout, refreshUser }),
    [status, user, pairingError, pair, cancelPairing, logout, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
