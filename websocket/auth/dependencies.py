from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from auth.utils import verify_privy_token
import logging

logger = logging.getLogger(__name__)
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    FastAPI dependency to validate Bearer token and return user info.
    """
    token = credentials.credentials
    # DEBUG: Local Testing Bypass
    if token.startswith("mock-"):
        return {"sub": token.replace("mock-", "0x"), "name": "Test User"}

    try:
        payload = verify_privy_token(token)
        return payload
    except ValueError as e:
        logger.error(f"Auth Config Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication configuration error"
        )
    except Exception as e:
        logger.warning(f"Invalid token attempt: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
