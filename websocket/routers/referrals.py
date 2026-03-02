from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from services.user_notification_service import user_notification_service

router = APIRouter(tags=["referrals"])
_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# On-chain helpers
# ---------------------------------------------------------------------------
REFERRAL_REGISTRY_ADDRESS = "0x08DFfff07f8A390f0E9321F28A256D7eb828cB79"
REFERRAL_REGISTRY_ABI = [
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "ownedCodeByUser",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "getReferrer",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "getTradingVolumeUsd",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# keccak256("ReferralBound(address,address,string)") — pre-computed
_REFERRAL_BOUND_TOPIC = "0x54e748de37cfebf3bc25e5f3e1d17e4d838b8f84c56e04e18b0dbf7e15d3b97"


def _get_w3():
    try:
        from web3 import Web3
        from config import settings
        rpc = getattr(settings, "ARBITRUM_RPC_URL", "https://sepolia.base.org")
        return Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
    except Exception:
        return None


def _registry_contract(w3):
    from web3 import Web3
    return w3.eth.contract(
        address=Web3.to_checksum_address(REFERRAL_REGISTRY_ADDRESS),
        abi=REFERRAL_REGISTRY_ABI,
    )


def _read_chain_data(address: str) -> Dict:
    """Read customCode, enteredCode from chain."""
    result: Dict = {"customCode": "", "enteredCode": ""}
    try:
        from web3 import Web3
        w3 = _get_w3()
        if not w3 or not w3.is_connected():
            return result

        checksum = Web3.to_checksum_address(address)
        contract = _registry_contract(w3)

        result["customCode"] = contract.functions.ownedCodeByUser(checksum).call() or ""

        referrer: str = contract.functions.getReferrer(checksum).call()
        zero = "0x0000000000000000000000000000000000000000"
        if referrer and referrer.lower() != zero.lower():
            entered = contract.functions.ownedCodeByUser(
                Web3.to_checksum_address(referrer)
            ).call()
            result["enteredCode"] = entered or ""
    except Exception as exc:
        _log.warning("chain read (summary) failed: %s", exc)
    return result


def _get_referred_users(referrer_address: str) -> List[str]:
    """Return addresses of users who used referrer's code (via ReferralBound events)."""
    try:
        from web3 import Web3
        w3 = _get_w3()
        if not w3 or not w3.is_connected():
            return []

        checksum = Web3.to_checksum_address(referrer_address)
        # Compute the actual event signature hash at runtime for correctness
        event_sig = "0x" + w3.keccak(text="ReferralBound(address,address,string)").hex()
        # referrer is 2nd indexed param → topic index 2
        referrer_topic = "0x" + checksum[2:].lower().zfill(64)

        logs = w3.eth.get_logs({
            "address": Web3.to_checksum_address(REFERRAL_REGISTRY_ADDRESS),
            "topics": [event_sig, None, referrer_topic],
            "fromBlock": 0,
            "toBlock": "latest",
        })

        users: List[str] = []
        for log in logs:
            raw = log["topics"][1].hex()
            users.append(Web3.to_checksum_address("0x" + raw[-40:]))
        return users
    except Exception as exc:
        _log.warning("chain read (events) failed: %s", exc)
        return []


def _get_trading_volume(address: str) -> int:
    try:
        from web3 import Web3
        w3 = _get_w3()
        if not w3 or not w3.is_connected():
            return 0
        contract = _registry_contract(w3)
        return contract.functions.getTradingVolumeUsd(
            Web3.to_checksum_address(address)
        ).call()
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class EnterCodeRequest(BaseModel):
    code: str = Field(..., min_length=2, max_length=32)


class CreateCodeRequest(BaseModel):
    code: str = Field(..., min_length=3, max_length=20)


def _short_addr(addr: str) -> str:
    clean = str(addr or "").strip()
    if len(clean) < 10:
        return clean or "0xUSER"
    return f"{clean[:6]}...{clean[-4:]}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{user_address}/summary")
async def get_referral_summary(user_address: str):
    chain = await asyncio.to_thread(_read_chain_data, user_address)
    referred_users = await asyncio.to_thread(_get_referred_users, user_address)

    # FeeManager defaults: tradingFeeBps=8 (0.08%), tradingRewardBps=300 (3% of fees)
    TRADING_FEE_BPS = 8
    REWARD_BPS = 300

    rewards_earned = 0.0
    for u in referred_users:
        vol_raw = await asyncio.to_thread(_get_trading_volume, u)
        vol_usd = vol_raw / 1_000_000
        fee = vol_usd * TRADING_FEE_BPS / 10_000
        reward = fee * REWARD_BPS / 10_000
        rewards_earned += reward

    return {
        "userAddress": user_address,
        "displayAddress": _short_addr(user_address),
        "customCode": chain["customCode"],
        "enteredCode": chain["enteredCode"],
        "tradersReferred": len(referred_users),
        "rewardsEarned": round(rewards_earned, 4),
        "claimableRewards": 0.0,  # No on-chain claim mechanism yet
    }


@router.get("/{user_address}/referrals")
async def get_referral_rows(
    user_address: str,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=200),
):
    referred_users = await asyncio.to_thread(_get_referred_users, user_address)

    TRADING_FEE_BPS = 8
    REWARD_BPS = 300

    rows: List[Dict] = []
    for u in referred_users:
        vol_raw = await asyncio.to_thread(_get_trading_volume, u)
        vol_usd = vol_raw / 1_000_000
        fee = round(vol_usd * TRADING_FEE_BPS / 10_000, 4)
        reward = round(fee * REWARD_BPS / 10_000, 4)
        rows.append({
            "address": u,
            "dateJoined": "",
            "totalVolume": round(vol_usd, 2),
            "feesPaid": round(fee, 4),
            "yourRewards": round(reward, 4),
        })

    start = (page - 1) * limit
    end = start + limit
    return {"page": page, "limit": limit, "total": len(rows), "rows": rows[start:end]}


@router.get("/{user_address}/legacy")
async def get_legacy_rows(
    user_address: str,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=200),
):
    return {"page": page, "limit": limit, "total": 0, "rows": []}


@router.post("/{user_address}/enter-code")
async def enter_referral_code(user_address: str, payload: EnterCodeRequest):
    code = payload.code.strip().upper()
    await user_notification_service.publish(
        user_address=user_address.lower(),
        event_type="referral_code_entered",
        data={"message": f"Referral code {code} bound on-chain", "code": code},
    )
    return {"success": True, "message": f"Referral code {code} registered", "enteredCode": code}


@router.post("/{user_address}/create-code")
async def create_referral_code(user_address: str, payload: CreateCodeRequest):
    code = payload.code.strip().upper()
    await user_notification_service.publish(
        user_address=user_address.lower(),
        event_type="referral_code_created",
        data={"message": f"Referral code {code} created on-chain", "code": code},
    )
    return {"success": True, "message": f"Referral code {code} created", "customCode": code}


@router.post("/{user_address}/claim")
async def claim_referral_rewards(user_address: str):
    # No on-chain claim mechanism exists yet.
    await user_notification_service.publish(
        user_address=user_address.lower(),
        event_type="referral_reward_claimed",
        data={"message": "On-chain claim not yet available", "claimed_amount": 0, "asset": "USDC"},
    )
    return {
        "success": False,
        "claimedAmount": 0.0,
        "remainingClaimable": 0.0,
        "message": "On-chain claim not yet available",
    }
