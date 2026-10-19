/**
 * Small, dependency-free codec helpers for hands-free voice mode.
 *
 * Deliberately not using the global `atob`/`btoa` here: Hermes's support for
 * them has varied across React Native versions, and getting this wrong
 * silently corrupts audio rather than throwing, which is a nasty thing to
 * debug. A plain, well-tested base64 implementation removes that variable.
 */

const BASE64_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

export function bytesToBase64(bytes: Uint8Array): string {
  let result = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : undefined;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : undefined;

    result += BASE64_CHARS[b0 >> 2];
    result += BASE64_CHARS[((b0 & 0x03) << 4) | (b1 === undefined ? 0 : b1 >> 4)];
    result += b1 === undefined ? '=' : BASE64_CHARS[((b1 & 0x0f) << 2) | (b2 === undefined ? 0 : b2 >> 6)];
    result += b2 === undefined ? '=' : BASE64_CHARS[b2 & 0x3f];
  }
  return result;
}

export function base64ToBytes(base64: string): Uint8Array {
  const clean = base64.replace(/[^A-Za-z0-9+/]/g, '');
  const byteLength = Math.floor((clean.length * 6) / 8);
  const bytes = new Uint8Array(byteLength);

  let byteIndex = 0;
  let buffer = 0;
  let bitsInBuffer = 0;

  for (let i = 0; i < clean.length; i++) {
    const value = BASE64_CHARS.indexOf(clean[i]);
    if (value === -1) continue;
    buffer = (buffer << 6) | value;
    bitsInBuffer += 6;
    if (bitsInBuffer >= 8) {
      bitsInBuffer -= 8;
      bytes[byteIndex++] = (buffer >> bitsInBuffer) & 0xff;
    }
  }
  return bytes;
}

/** Float32 samples in [-1, 1] (what AudioRecorder/AudioBuffer use) -> little-endian PCM16 bytes (what Gemini expects). */
export function float32ToPcm16Base64(float32: Float32Array): string {
  const bytes = new Uint8Array(float32.length * 2);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < float32.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32[i]));
    const sample = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    view.setInt16(i * 2, sample, true /* little-endian */);
  }
  return bytesToBase64(bytes);
}

/** Little-endian PCM16 base64 (what Gemini sends back) -> Float32 samples in [-1, 1] (what AudioBuffer needs). */
export function pcm16Base64ToFloat32(base64: string): Float32Array {
  const bytes = base64ToBytes(base64);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const float32 = new Float32Array(Math.floor(bytes.length / 2));
  for (let i = 0; i < float32.length; i++) {
    const sample = view.getInt16(i * 2, true);
    float32[i] = sample < 0 ? sample / 0x8000 : sample / 0x7fff;
  }
  return float32;
}
