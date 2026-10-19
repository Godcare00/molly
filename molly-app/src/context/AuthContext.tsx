import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Platform as RNPlatform } from 'react-native';
import * as Application from 'expo-application';
import { authApi } from '@/api/auth';
import { ApiError, setSessionExpiredHandler } from '@/api/client';
import { secureStorage } from '@/utils/storage';
import { generateDeviceKeypair, signChallenge } from '@/utils/ed25519';
import type { UserResponse } from '@/types/api';

type AuthStatus = 'loading' | 'unauthenticated' | 'pairing' | 'authenticated';

const POLL_INTERVAL_MS = 2000;

interface AuthContextValue {
  status: AuthStatus;
  user: UserResponse | null;
  pairingError: string | null;
  /** The code to show the user while status === 'pairing' — enter this at the server's /connect link. */
  pairingCode: string | null;
  pair: () => Promise<void>;
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
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const cancelledRef = useRef(false);

  const refreshUser = useCallback(async () => {
    const me = await authApi.me();
    setUser(me);
  }, []);

  const bootstrap = useCallback(async () => {
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
   * The Molly backend has no password auth — pairing this device *is* login.
   * Flow: generate an Ed25519 keypair on-device (private key never leaves
   * the device) -> register the public key, which also hands back a short
   * pairing code -> show that code so the user can approve it at the
   * server's /connect link -> once approved, sign the challenge and
   * exchange the signature for a token pair.
   *
   * The device isn't trusted the moment it registers, so step 2 (verify)
   * is polled: it returns 403/pending_approval until the code is approved
   * in a browser, then succeeds.
   */
  const pair = useCallback(async () => {
    setStatus('pairing');
    setPairingError(null);
    setPairingCode(null);
    cancelledRef.current = false;

    try {
      let { privateKey, publicKeyPem } = await secureStorage.getDeviceIdentity();

      if (!privateKey || !publicKeyPem) {
        const kp = generateDeviceKeypair();
        privateKey = kp.secretKeyBase64;
        publicKeyPem = kp.publicKeyPem;
      }

      const deviceName = RNPlatform.OS === 'ios' ? 'iPhone' : RNPlatform.OS === 'android' ? 'Android device' : 'Device';

      const registration = await authApi.registerDevice({
        public_key: publicKeyPem,
        device_name: deviceName,
        platform: devicePlatform(),
        app_version: Application.nativeApplicationVersion ?? undefined,
      });

      setPairingCode(registration.pairing_code);

      const signature = signChallenge(registration.challenge, privateKey);
      const deadline = Date.parse(registration.challenge_expires_at);

      let tokens = null;
      while (!tokens) {
        if (cancelledRef.current) return;

        try {
          tokens = await authApi.verifyDevice({ device_id: registration.device_id, signature });
        } catch (err) {
          const isPending =
            err instanceof ApiError &&
            err.status === 403 &&
            typeof err.body?.detail === 'object' &&
            !Array.isArray(err.body?.detail) &&
            (err.body?.detail as any)?.error_code === 'pending_approval';

          if (!isPending) throw err;

          if (Number.isFinite(deadline) && Date.now() > deadline) {
            throw new Error('The pairing code expired before it was approved. Try again.');
          }

          await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
          continue;
        }
      }

      if (cancelledRef.current) return;

      await secureStorage.setDeviceIdentity(registration.device_id, privateKey, publicKeyPem);
      await secureStorage.setTokens(tokens.access_token, tokens.refresh_token);

      const me = await authApi.me();
      setUser(me);
      setPairingCode(null);
      setStatus('authenticated');
    } catch (err: any) {
      if (cancelledRef.current) return;
      setPairingCode(null);
      setPairingError(err?.message ?? 'Could not pair this device. Try again.');
      setStatus('unauthenticated');
    }
  }, []);

  /** Lets the user back out of the "waiting for approval" screen. */
  const cancelPairing = useCallback(() => {
    cancelledRef.current = true;
    setPairingCode(null);
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
    setUser(null);
    setStatus('unauthenticated');
  }, []);

  const value = useMemo(
    () => ({ status, user, pairingError, pairingCode, pair, cancelPairing, logout, refreshUser }),
    [status, user, pairingError, pairingCode, pair, cancelPairing, logout, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
