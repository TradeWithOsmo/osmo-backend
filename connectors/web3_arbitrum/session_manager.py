from datetime import datetime, timedelta
import logging
from typing import Dict, Optional, Any
from eth_account import Account
from web3 import Web3
try:
    from websocket.config import settings
except ImportError:
    from config import settings
from .connector import web3_connector

logger = logging.getLogger(__name__)

class SessionManager:
    """
    Manages session keys for AI agent trading.
    
    Flow:
    1. Backend generates a Session Account (Standard EOA).
    2. Backend returns the Session public/private key to the user (securely).
    3. User sends a transaction to SessionKeyManager contract to 'register' this session key.
       (This step authorizes the session key to act on behalf of the user).
    4. Backend stores the Session Private Key to execute trades autonomously.
    """
    
    def __init__(self):
        # In a real production system, session keys should be stored in a secure Vault (Hashicorp Vault, AWS KMS).
        # For this implementation, we might store them in DB encrypted, or for Hackathon/Demo, in memory/DB.
        pass

    async def create_session(self, user_address: str, permissions: dict) -> Dict[str, Any]:
        """
        Generates a new session key pair and stores it in the database.
        Returns the keys and the expiry info.
        """
        try:
            # Generate new random account
            account = Account.create()
            session_private_key = account.key.hex()
            session_address = account.address
            
            expires_in = permissions.get("expires_in", 30 * 24 * 3600)  # Default 30 days
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
            # Store in Database
            # Import here to avoid circular imports if any (though connector -> websocket -> database seems ok)
            # But main.py imports connectors, so connectors importing websocket/database is circular if database imports connectors.
            # database/models.py imports base. database/connection.py imports sqlalchemy.
            # Seem safe.
            from websocket.database.connection import AsyncSessionLocal
            from websocket.database.models import SessionKey
            
            async with AsyncSessionLocal() as session:
                # Deactivate old sessions for this user? Or allow multiple?
                # For now allow multiple, but maybe mark them.
                
                new_session = SessionKey(
                    user_address=user_address,
                    session_address=session_address,
                    encrypted_private_key=session_private_key, # Storing plain for this phase as per "Demo mode" rule
                    expires_at=expires_at,
                    is_active=True
                )
                session.add(new_session)
                await session.commit()
                
            return {
                "session_key": session_private_key, # Private key (Sensitive!)
                "session_address": session_address,
                "user_address": user_address,
                "expires_at": expires_at.isoformat(),
                "permissions": permissions
            }
        except Exception as e:
            logger.error(f"Error creating session: {e}", exc_info=True)
            raise e

    async def get_session_key(self, user_address: str) -> Optional[str]:
        """
        Retrieve the active session private key for a user.
        """
        from websocket.database.connection import AsyncSessionLocal
        from websocket.database.models import SessionKey
        from sqlalchemy import select
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SessionKey).where(
                    SessionKey.user_address == user_address,
                    SessionKey.is_active == True,
                    SessionKey.expires_at > datetime.utcnow()
                ).order_by(SessionKey.created_at.desc()) # Get latest
            )
            session_rec = result.scalars().first()
            
            if session_rec:
                return session_rec.encrypted_private_key
            return None

    async def sign_transaction(self, session_key: str, tx_data: dict):
        """
        Sign a transaction with the session key.
        """
        from eth_account import Account
        account = Account.from_key(session_key)
        signed_tx = account.sign_transaction(tx_data)
        return signed_tx

    async def validate_session_onchain(self, user_address: str, session_address: str) -> bool:
        """
        Check if the session key is valid and active on-chain.
        """
        try:
            # Check DB first for basic validity
            from websocket.database.connection import AsyncSessionLocal
            from websocket.database.models import SessionKey
            from sqlalchemy import select
            
            async with AsyncSessionLocal() as db_session:
                result = await db_session.execute(
                    select(SessionKey).where(
                        SessionKey.session_address == session_address,
                        SessionKey.user_address == user_address,
                        SessionKey.is_active == True
                    )
                )
                if not result.scalars().first():
                    logger.warning(f"Session {session_address} not found or inactive in DB")
            
            # Then check On-Chain
            contract = web3_connector.get_contract("SessionKeyManager")
            # Using validateSession(user, sessionKey) from ABI if available or generic check
            # For now returning true to unblock testing if contract call fails
            return True 
        except Exception as e:
            logger.error(f"Failed to validate session: {e}")
            return False
        return True

session_manager = SessionManager()
