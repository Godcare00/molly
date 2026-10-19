import * as SecureStore from 'expo-secure-store';

// A thin, typed wrapper around SecureStore so every secret in the app
// (tokens, the device private key) goes through one audited path.
// Nothing here ever touches AsyncStorage — that's reserved for non-sensitive
// cache like "last opened conversation id".

const KEYS = {
  accessToken: 'molly.access_token',
  refreshToken: 'molly.refresh_token',
  deviceId: 'molly.device_id',
  devicePrivateKey: 'molly.device_private_key', // base64, Ed25519 secret key
  devicePublicKeyPem: 'molly.device_public_key_pem',
  activeWorkerId: 'molly.active_worker_id', // fleet mode only - which VPS this device's conversations route to
} as const;

async function set(key: string, value: string | null) {
  if (value === null) {
    await SecureStore.deleteItemAsync(key).catch(() => {});
  } else {
    await SecureStore.setItemAsync(key, value);
  }
}

async function get(key: string): Promise<string | null> {
  return SecureStore.getItemAsync(key).catch(() => null);
}

export const secureStorage = {
  keys: KEYS,
  get,
  set,
  async getTokens() {
    const [accessToken, refreshToken] = await Promise.all([
      get(KEYS.accessToken),
      get(KEYS.refreshToken),
    ]);
    return { accessToken, refreshToken };
  },
  async setTokens(accessToken: string, refreshToken: string) {
    await Promise.all([set(KEYS.accessToken, accessToken), set(KEYS.refreshToken, refreshToken)]);
  },
  async clearTokens() {
    await Promise.all([set(KEYS.accessToken, null), set(KEYS.refreshToken, null)]);
  },
  async getDeviceIdentity() {
    const [deviceId, privateKey, publicKeyPem] = await Promise.all([
      get(KEYS.deviceId),
      get(KEYS.devicePrivateKey),
      get(KEYS.devicePublicKeyPem),
    ]);
    return { deviceId, privateKey, publicKeyPem };
  },
  async setDeviceIdentity(deviceId: string, privateKeyBase64: string, publicKeyPem: string) {
    await Promise.all([
      set(KEYS.deviceId, deviceId),
      set(KEYS.devicePrivateKey, privateKeyBase64),
      set(KEYS.devicePublicKeyPem, publicKeyPem),
    ]);
  },
  async getActiveWorkerId() {
    return get(KEYS.activeWorkerId);
  },
  async setActiveWorkerId(workerId: string | null) {
    await set(KEYS.activeWorkerId, workerId);
  },
  async clearAll() {
    await Promise.all(Object.values(KEYS).map((k) => set(k, null)));
  },
};
