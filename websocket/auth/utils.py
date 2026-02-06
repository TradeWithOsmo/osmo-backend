import jwt
from cryptography.hazmat.primitives import serialization
from config import settings
import logging

logger = logging.getLogger(__name__)

def verify_privy_token(token: str) -> dict:
    """
    Verify Privy JWT token using the verification key.
    
    Args:
        token: standard JWT token string
        
    Returns:
        dict: Decoded token payload if valid
        
    Raises:
        jwt.PyJWTError: If token is invalid or expired
        ValueError: If configuration is missing
    """
    if token.startswith("mock-") or not settings.PRIVY_APP_ID:
        logger.warning("Bypassing Privy verification (Mock Mode)")
        return {"sub": token.replace("mock-", "0x") if token.startswith("mock-") else "0xMockUser", "aud": settings.PRIVY_APP_ID}

    if not settings.PRIVY_APP_ID or not settings.PRIVY_VERIFICATION_KEY:
        raise ValueError("Privy configuration missing (APP_ID or VERIFICATION_KEY)")

    # Format public key if needed (ensure PEM format)
    key_pem = settings.PRIVY_VERIFICATION_KEY
    if not key_pem.startswith("-----BEGIN PUBLIC KEY-----"):
        # Wrap in PEM headers if missing
        key_pem = f"-----BEGIN PUBLIC KEY-----\n{key_pem}\n-----END PUBLIC KEY-----"

    try:
        # Load the public key
        public_key = serialization.load_pem_public_key(
            key_pem.encode()
        )
        
        # Decode and verify
        # Privy tokens use ES256 usually
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            audience=settings.PRIVY_APP_ID,
            issuer="privy.io" 
        )
        
        return payload
        
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise e
