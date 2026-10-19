// IMPORTANT: this import must run before `tweetnacl` anywhere in the app,
// so it lives at the top of App.tsx as well as here for safety when this
// module is imported first in tests/tooling.
import 'react-native-get-random-values';
import nacl from 'tweetnacl';
import { encodeBase64, decodeBase64, decodeUTF8 } from 'tweetnacl-util';

// DER prefix for a SubjectPublicKeyInfo wrapping a raw Ed25519 public key.
// SEQUENCE { SEQUENCE { OID 1.3.101.112 }, BIT STRING <32 bytes> }
// This is a fixed 12-byte header for Ed25519 keys specifically.
const SPKI_ED25519_PREFIX = new Uint8Array([
  0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00,
]);

function toPem(publicKey: Uint8Array): string {
  const der = new Uint8Array(SPKI_ED25519_PREFIX.length + publicKey.length);
  der.set(SPKI_ED25519_PREFIX, 0);
  der.set(publicKey, SPKI_ED25519_PREFIX.length);
  const b64 = encodeBase64(der);
  const lines = b64.match(/.{1,64}/g) ?? [b64];
  return ['-----BEGIN PUBLIC KEY-----', ...lines, '-----END PUBLIC KEY-----'].join('\n');
}

function base64UrlEncode(bytes: Uint8Array): string {
  return encodeBase64(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export interface DeviceKeypair {
  publicKeyPem: string;
  secretKeyBase64: string; // 64-byte Ed25519 secret key (seed + pubkey), base64
}

export function generateDeviceKeypair(): DeviceKeypair {
  const pair = nacl.sign.keyPair();
  return {
    publicKeyPem: toPem(pair.publicKey),
    secretKeyBase64: encodeBase64(pair.secretKey),
  };
}

/** Sign a server-issued challenge string with the stored device secret key. */
export function signChallenge(challenge: string, secretKeyBase64: string): string {
  const secretKey = decodeBase64(secretKeyBase64);
  const message = decodeUTF8(challenge);
  const signature = nacl.sign.detached(message, secretKey);
  return base64UrlEncode(signature);
}
