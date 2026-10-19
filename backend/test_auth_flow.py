"""
Test script to verify auth flow works end-to-end.
"""
import asyncio
import base64
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from app.auth.database import init_auth_db, get_auth_session
from app.auth.models import User
from app.auth.device_keys import DeviceKeyManager, PendingApprovalError
from app.auth.connect import ConnectManager
from app.auth.jwt import jwt_manager


async def test_auth_flow():
    await init_auth_db()

    async with get_auth_session() as db:
        # Create or get default user
        user = await db.get(User, "default")
        if not user:
            user = User(
                id="default",
                username="operator",
                display_name="VPS Operator",
                role="operator",
                is_active=True,
            )
            db.add(user)
            await db.flush()

        print("=== Device Key Registration ===")
        # Generate Ed25519 keypair (simulating mobile app)
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

        print(f"Public key:\n{public_key_pem}")

        # Register device
        device, challenge, pairing_code, pairing_code_expires_at = await DeviceKeyManager.register_device(
            db,
            user_id=user.id,
            public_key_pem=public_key_pem,
            device_name="Test iPhone 15",
            platform="ios",
            platform_version="17.2",
            app_version="1.0.0",
        )
        print(f"\nDevice registered: {device.id}")
        print(f"Challenge: {challenge}")
        print(f"Pairing code: {pairing_code}")

        # Sign challenge with private key (simulating mobile app)
        signature = private_key.sign(challenge.encode())
        signature_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")
        print(f"Signature: {signature_b64}")

        # A valid signature alone isn't enough yet — the device is still
        # unapproved, so this should raise PendingApprovalError.
        print("\n=== Verify before approval (should be rejected) ===")
        try:
            await DeviceKeyManager.verify_device_challenge(db, device.id, signature_b64)
            print("ERROR: expected PendingApprovalError, but verification succeeded")
        except PendingApprovalError:
            print("Correctly rejected: device not yet approved")

        # Simulate `molly connect` (CLI) + the browser approval step
        print("\n=== Simulating /connect approval ===")
        connect_session = await ConnectManager.create_session(db)
        print(f"Connect session token: {connect_session.token}")
        _, approved_device = await ConnectManager.approve(db, connect_session.token, pairing_code)
        print(f"Device approved via browser: is_trusted={approved_device.is_trusted}")

        # Now the same signature succeeds
        verified_device = await DeviceKeyManager.verify_device_challenge(db, device.id, signature_b64)
        print(f"\nDevice verified: {verified_device.is_trusted}")

        # Issue tokens
        access_token, access_jti, access_expires = jwt_manager.create_access_token(
            subject=user.id,
            device_id=device.id,
            role=user.role,
        )
        refresh_token, refresh_hash, refresh_expires = jwt_manager.create_refresh_token(
            subject=user.id,
            device_id=device.id,
        )

        print(f"\nAccess token (first 50 chars): {access_token[:50]}...")
        print(f"Refresh token (first 50 chars): {refresh_token[:50]}...")

        # Verify access token
        payload = jwt_manager.verify_token(access_token, expected_type="access")
        print(f"\nAccess token payload: sub={payload['sub']}, device_id={payload['device_id']}, role={payload['role']}")

        # Verify refresh token
        payload = jwt_manager.verify_token(refresh_token, expected_type="refresh")
        print(f"Refresh token payload: sub={payload['sub']}, device_id={payload['device_id']}")

        # Test JWKS
        jwks = jwt_manager.get_jwks()
        print(f"\nJWKS: {jwks}")

        print("\n=== All tests passed! ===")


if __name__ == "__main__":
    asyncio.run(test_auth_flow())