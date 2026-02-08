import asyncio
import json
import logging
import math
from typing import Any, Dict, Optional, Tuple

from web3 import Web3

try:
    from backend.websocket.config import settings
except ImportError:
    try:
        from websocket.config import settings
    except ImportError:
        from config import settings

from connectors.web3_arbitrum.connector import web3_connector

logger = logging.getLogger(__name__)


class AIBillingService:
    """Compute AI usage fee and charge it to on-chain AI Vault."""

    USDC_BASE = 1_000_000

    def _markup_multiplier(self) -> float:
        pct = max(0.0, float(getattr(settings, "AI_MARKUP_PERCENT", 5.0)))
        return 1.0 + (pct / 100.0)

    def _load_groq_pricing(self) -> Dict[str, Dict[str, float]]:
        raw = getattr(settings, "GROQ_MODEL_PRICING_USD_PER_1M", "") or ""
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            logger.warning("Invalid GROQ_MODEL_PRICING_USD_PER_1M JSON: %s", exc)
        return {}

    def _resolve_rate_per_million(
        self,
        model_id: str,
        model_info: Optional[Dict[str, Any]] = None
    ) -> Tuple[float, float, bool]:
        model_info = model_info or {}
        input_cost = float(model_info.get("input_cost") or 0.0)
        output_cost = float(model_info.get("output_cost") or 0.0)

        includes_markup = model_info.get("includes_markup")
        if includes_markup is None:
            includes_markup = not model_id.startswith("groq/")
        includes_markup = bool(includes_markup)

        if model_id.startswith("groq/"):
            normalized = model_id.replace("groq/", "", 1)
            overrides = self._load_groq_pricing()
            selected = overrides.get(normalized) or overrides.get(model_id)
            if isinstance(selected, dict):
                input_cost = float(selected.get("input", input_cost) or input_cost)
                output_cost = float(selected.get("output", output_cost) or output_cost)

            if input_cost <= 0:
                input_cost = float(
                    getattr(settings, "GROQ_DEFAULT_INPUT_COST_PER_1M", 0.0)
                )
            if output_cost <= 0:
                output_cost = float(
                    getattr(settings, "GROQ_DEFAULT_OUTPUT_COST_PER_1M", 0.0)
                )

        return input_cost, output_cost, includes_markup

    async def calculate_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        model_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        in_tok = max(0, int(input_tokens or 0))
        out_tok = max(0, int(output_tokens or 0))

        in_rate, out_rate, includes_markup = self._resolve_rate_per_million(
            model_id=model_id,
            model_info=model_info
        )

        if not includes_markup:
            mul = self._markup_multiplier()
            in_rate *= mul
            out_rate *= mul

        total_usd = (in_tok / 1_000_000 * in_rate) + (out_tok / 1_000_000 * out_rate)
        total_usd = float(max(0.0, total_usd))

        return {
            "model_id": model_id,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "input_rate_per_1m": in_rate,
            "output_rate_per_1m": out_rate,
            "total_cost_usd": total_usd,
            "includes_markup": True,
        }

    async def deduct_onchain(
        self,
        user_address: str,
        total_cost_usd: float
    ) -> Dict[str, Any]:
        cost = float(total_cost_usd or 0.0)
        if cost <= 0:
            return {"charged": False, "reason": "zero_cost", "amount_usdc": 0}

        if not getattr(settings, "AI_BILLING_ONCHAIN_ENABLED", True):
            return {"charged": False, "reason": "billing_disabled", "amount_usdc": 0}

        if not settings.AI_VAULT_ADDRESS:
            return {"charged": False, "reason": "missing_ai_vault_address", "amount_usdc": 0}

        if not settings.TREASURY_PRIVATE_KEY or not web3_connector.account:
            return {"charged": False, "reason": "missing_treasury_signer", "amount_usdc": 0}

        amount_usdc = max(1, int(math.ceil(cost * self.USDC_BASE)))
        try:
            ai_vault = web3_connector.get_contract("AIVault")
            treasury = web3_connector.account
            user_checksum = Web3.to_checksum_address(user_address)

            nonce = await asyncio.to_thread(
                web3_connector.w3.eth.get_transaction_count,
                treasury.address,
                "pending",
            )
            tx = await asyncio.to_thread(
                ai_vault.functions.deductFeeAmount(
                    user_checksum,
                    amount_usdc
                ).build_transaction,
                {
                    "from": treasury.address,
                    "nonce": nonce,
                    "gas": 220000,
                    "chainId": settings.CHAIN_ID,
                },
            )
            signed = web3_connector.w3.eth.account.sign_transaction(
                tx,
                settings.TREASURY_PRIVATE_KEY,
            )
            tx_hash = await asyncio.to_thread(
                web3_connector.w3.eth.send_raw_transaction,
                signed.raw_transaction,
            )
            return {
                "charged": True,
                "amount_usdc": amount_usdc,
                "tx_hash": tx_hash.hex(),
            }
        except Exception as exc:
            logger.warning(
                "AIVault deduction failed for %s amount=%s: %s",
                user_address,
                amount_usdc,
                exc
            )
            return {
                "charged": False,
                "amount_usdc": amount_usdc,
                "reason": str(exc),
            }

    async def bill_usage(
        self,
        user_address: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        model_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        pricing = await self.calculate_cost(
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_info=model_info
        )
        chain = await self.deduct_onchain(
            user_address=user_address,
            total_cost_usd=pricing["total_cost_usd"]
        )
        pricing["onchain"] = chain
        return pricing


ai_billing_service = AIBillingService()
