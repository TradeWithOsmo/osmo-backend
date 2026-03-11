import asyncio
import json
import logging
import math
from typing import Any, Dict, Optional, Tuple

from web3 import Web3
from web3.exceptions import TimeExhausted

try:
    from backend.websocket.config import settings
except ImportError:
    try:
        from websocket.config import settings
    except ImportError:
        from config import settings

from connectors.web3_arbitrum.connector import web3_connector
from database.connection import AsyncSessionLocal
from database.models import SessionKey
from sqlalchemy import select, func

logger = logging.getLogger(__name__)


class AIBillingService:
    """Compute AI usage fee and charge it to on-chain AI Vault."""

    USDC_BASE = 1_000_000

    @staticmethod
    def _normalize_private_key(raw_key: Optional[str]) -> Optional[str]:
        value = str(raw_key or "").strip()
        if not value:
            return None
        if value.startswith("0x"):
            value = value[2:]
        return value or None

    def _configured_signer(self) -> Tuple[Optional[str], Optional[Any], Optional[str]]:
        pk = self._normalize_private_key(
            getattr(settings, "AI_BILLING_SIGNER_PRIVATE_KEY", None)
        )
        if not pk:
            return None, None, None

        try:
            account = web3_connector.w3.eth.account.from_key(pk)
            return pk, account, "billing_signer"
        except Exception as exc:
            logger.warning("Invalid AI_BILLING_SIGNER_PRIVATE_KEY: %s", exc)
            return None, None, None

    async def _latest_session_signer(self, user_key: str) -> Tuple[Optional[str], Optional[Any], Optional[str]]:
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SessionKey).where(
                        func.lower(SessionKey.user_address) == user_key,
                        SessionKey.is_active == True
                    ).order_by(SessionKey.created_at.desc())
                )
                sk_record = result.scalars().first()
                if not sk_record or not sk_record.encrypted_private_key:
                    return None, None, None

                pk = self._normalize_private_key(sk_record.encrypted_private_key)
                if not pk:
                    return None, None, None

                account = web3_connector.w3.eth.account.from_key(pk)
                return pk, account, "session_key"
        except Exception as exc:
            logger.warning("Failed to load session signer for %s: %s", user_key, exc)
            return None, None, None

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
        user_key = str(user_address or "").strip().lower()
        if not user_key:
            return {"charged": False, "reason": "missing_user_address", "amount_usdc": 0}

        cost = float(total_cost_usd or 0.0)
        if cost <= 0:
            return {"charged": False, "reason": "zero_cost", "amount_usdc": 0}

        if not getattr(settings, "AI_BILLING_ONCHAIN_ENABLED", True):
            return {"charged": True, "reason": "billing_disabled", "amount_usdc": 0}

        if not settings.AI_VAULT_ADDRESS:
            return {"charged": False, "reason": "missing_ai_vault_address", "amount_usdc": 0}

        # 1. Look for user session key first
        s_pk, s_acc, s_src = await self._latest_session_signer(user_key)
        
        # 2. Check if we have the user-side deduction function in ABI
        try:
            ai_vault = web3_connector.get_contract("AIVault")
        except Exception as e:
            return {"charged": False, "reason": f"vault_not_found: {e}", "amount_usdc": 0}

        function_names = {
            entry.get("name")
            for entry in (ai_vault.abi or [])
            if isinstance(entry, dict) and entry.get("type") == "function"
        }
        has_user_deduct = "deductFeeAmountByUser" in function_names

        # 3. Decide which signer to use
        # If we have deductFeeAmountByUser, we prefer session keys or user's own address.
        # Otherwise, we MUST use the configured operator signer.
        use_user_side_path = has_user_deduct and s_acc and (
            s_src == "session_key" or s_acc.address.lower() == user_key
        )

        if not use_user_side_path:
            # Fallback to configured operator
            signer_pk, signer_account, signer_source = self._configured_signer()
            if signer_account:
                logger.info("Using configured AI billing operator %s (source: %s)", signer_account.address, signer_source)
            else:
                logger.warning("No fallback operator available for on-chain billing")
        else:
            signer_pk, signer_account, signer_source = s_pk, s_acc, s_src
            logger.info("Using user-side signer %s (source: %s)", signer_account.address, signer_source)

        if not signer_pk or not signer_account:
            return {"charged": False, "reason": "missing_billing_signer", "amount_usdc": 0}

        amount_usdc = max(1, int(math.ceil(cost * self.USDC_BASE)))
        try:
            user_checksum = Web3.to_checksum_address(user_key)
            signer_checksum = Web3.to_checksum_address(signer_account.address)

            if use_user_side_path:
                tx_fn = ai_vault.functions.deductFeeAmountByUser(
                    user_checksum,
                    amount_usdc
                )
            else:
                if "deductFeeAmount" not in function_names:
                    return {
                        "charged": False,
                        "amount_usdc": amount_usdc,
                        "reason": "contract_missing_deduct_function",
                        "signer": signer_account.address,
                        "signer_source": signer_source,
                    }

                if bool(getattr(settings, "AI_BILLING_REQUIRE_OPERATOR_ROLE", True)):
                    operator_role = await asyncio.to_thread(ai_vault.functions.OPERATOR_ROLE().call)
                    has_role = await asyncio.to_thread(
                        ai_vault.functions.hasRole(
                            operator_role,
                            signer_checksum,
                        ).call
                    )
                    if not has_role:
                        return {
                            "charged": False,
                            "amount_usdc": amount_usdc,
                            "reason": "signer_missing_operator_role",
                            "signer": signer_account.address,
                            "signer_source": signer_source,
                            "operator_role": operator_role.hex() if isinstance(operator_role, (bytes, bytearray)) else str(operator_role),
                        }
                tx_fn = ai_vault.functions.deductFeeAmount(
                    user_checksum,
                    amount_usdc
                )

            # Dry-run to catch reverts before spending gas.
            await asyncio.to_thread(
                tx_fn.call,
                {"from": signer_account.address},
            )

            nonce = await asyncio.to_thread(
                web3_connector.w3.eth.get_transaction_count,
                signer_account.address,
                "pending",
            )

            tx = await asyncio.to_thread(
                tx_fn.build_transaction,
                {
                    "from": signer_account.address,
                    "nonce": nonce,
                    "gas": 300000,
                    "chainId": settings.CHAIN_ID,
                },
            )
            signed = web3_connector.w3.eth.account.sign_transaction(
                tx,
                signer_pk,
            )
            # Handle different web3 versions: raw_transaction vs rawTransaction
            raw_tx = getattr(signed, "raw_transaction", getattr(signed, "rawTransaction", None))
            if not raw_tx:
                raise AttributeError("SignedTransaction object has no 'raw_transaction' or 'rawTransaction'")

            tx_hash = await asyncio.to_thread(
                web3_connector.w3.eth.send_raw_transaction,
                raw_tx,
            )
            timeout_seconds = max(
                15,
                int(getattr(settings, "AI_BILLING_RECEIPT_TIMEOUT_SECONDS", 90) or 90),
            )
            receipt = await asyncio.to_thread(
                web3_connector.w3.eth.wait_for_transaction_receipt,
                tx_hash,
                timeout=timeout_seconds,
                poll_latency=1,
            )

            if not receipt or int(getattr(receipt, "status", 0) or 0) != 1:
                return {
                    "charged": False,
                    "amount_usdc": amount_usdc,
                    "tx_hash": tx_hash.hex(),
                    "reason": "tx_reverted",
                    "signer": signer_account.address,
                    "signer_source": signer_source,
                }

            return {
                "charged": True,
                "amount_usdc": amount_usdc,
                "tx_hash": tx_hash.hex(),
                "signer": signer_account.address,
                "signer_source": signer_source,
                "billing_mode": "user_side" if use_user_side_path else "operator",
                "block_number": int(getattr(receipt, "blockNumber", 0) or 0),
                "gas_used": int(getattr(receipt, "gasUsed", 0) or 0),
            }
        except TimeExhausted:
            logger.warning(
                "AIVault deduction timed out for %s amount=%s",
                user_address,
                amount_usdc,
            )
            return {
                "charged": False,
                "amount_usdc": amount_usdc,
                "reason": "tx_timeout",
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
