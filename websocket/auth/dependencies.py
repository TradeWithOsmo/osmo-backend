from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from auth.utils import verify_privy_token
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


def _is_wallet_address(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw.startswith("0x") or len(raw) != 42:
        return False
    try:
        int(raw[2:], 16)
        return True
    except Exception:
        return False


def _extract_wallet_address(payload: Dict[str, Any]) -> Optional[str]:
    if not isinstance(payload, dict):
        return None

    candidates = []
    direct_keys = ("wallet_address", "walletAddress", "address")
    for key in direct_keys:
        value = payload.get(key)
        if isinstance(value, str):
            candidates.append(value)

    nested_keys = ("wallet", "user_wallet", "embedded_wallet")
    for key in nested_keys:
        value = payload.get(key)
        if isinstance(value, dict):
            maybe_address = value.get("address") or value.get("wallet_address")
            if isinstance(maybe_address, str):
                candidates.append(maybe_address)

    linked_accounts = payload.get("linked_accounts") or payload.get("linkedAccounts") or []
    if isinstance(linked_accounts, list):
        for account in linked_accounts:
            if not isinstance(account, dict):
                continue
            maybe_address = account.get("address")
            if isinstance(maybe_address, str):
                candidates.append(maybe_address)

    wallets = payload.get("wallets") or []
    if isinstance(wallets, list):
        for wallet in wallets:
            if not isinstance(wallet, dict):
                continue
            maybe_address = wallet.get("address") or wallet.get("wallet_address")
            if isinstance(maybe_address, str):
                candidates.append(maybe_address)

    sub = payload.get("sub")
    if isinstance(sub, str):
        candidates.append(sub)

    for candidate in candidates:
        if _is_wallet_address(candidate):
            return candidate.lower()

    # Fallback: recursively scan payload for any EVM address-like string.
    # Privy token shapes can vary across SDK/app configurations.
    def _walk(value: Any) -> Optional[str]:
        if isinstance(value, str):
            return value.lower() if _is_wallet_address(value) else None
        if isinstance(value, dict):
            for v in value.values():
                found = _walk(v)
                if found:
                    return found
            return None
        if isinstance(value, list):
            for item in value:
                found = _walk(item)
                if found:
                    return found
            return None
        return None

    return _walk(payload)

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    FastAPI dependency to validate Bearer token and return user info.
    """
    if credentials is None or not str(getattr(credentials, "credentials", "") or "").strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    if str(token).strip().lower() in {"null", "undefined"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = verify_privy_token(token)
        wallet_address = _extract_wallet_address(payload)
        if not wallet_address:
            header_candidates = (
                request.headers.get("x-wallet-address"),
                request.headers.get("x-user-wallet"),
                request.headers.get("x-wallet"),
            )
            for candidate in header_candidates:
                if _is_wallet_address(candidate):
                    wallet_address = str(candidate).strip().lower()
                    break
        if wallet_address:
            payload["wallet_address"] = wallet_address
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
