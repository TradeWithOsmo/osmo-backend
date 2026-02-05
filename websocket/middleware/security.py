"""
Security Middleware

Rate limiting and request validation for trading API.
"""

from fastapi import Request, HTTPException
from typing import Dict, List
import time
from config import settings

class SecurityMiddleware:
    """
    API Security Layer
    - Rate limiting per user
    - Address validation
    - Request logging
    """
    
    def __init__(self):
        self.rate_limits: Dict[str, List[float]] = {}  # user_address -> [timestamps]
        self.rate_limit_window = 60  # 60 seconds
        self.max_requests_per_window = settings.RATE_LIMIT_PER_MINUTE
    
    async def verify_user(self, request: Request, user_address: str) -> bool:
        """
        Verify user authenticity and apply rate limiting.
        
        For testnet/development:
        - Just validate address format
        
        For production:
        - Validate signature from session key
        - Validate API key if provided
        """
        
        # Basic address validation (0x + 40 hex chars)
        if not user_address.startswith('0x') or len(user_address) != 42:
            raise HTTPException(status_code=401, detail="Invalid user address format")
        
       # Rate limiting
        now = time.time()
        if user_address not in self.rate_limits:
            self.rate_limits[user_address] = []
        
        # Clean old timestamps
        self.rate_limits[user_address] = [
            ts for ts in self.rate_limits[user_address]
            if now - ts < self.rate_limit_window
        ]
        
        # Check limit
        if len(self.rate_limits[user_address]) >= self.max_requests_per_window:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {self.max_requests_per_window} requests per minute."
            )
        
        # Add current request
        self.rate_limits[user_address].append(now)
        
        return True


# Global instance
security_middleware = SecurityMiddleware()
