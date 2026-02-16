
"""Ostium Subgraph Client using Official SDK"""
import logging
import os
import time
from typing import Dict, Any, List
from ostium_python_sdk import NetworkConfig, OstiumSDK
from decimal import Decimal

logger = logging.getLogger(__name__)

class OstiumSubgraphClient:
    """Wrapper around Official Ostium SDK"""
     
    def __init__(self):
        # Use Mainnet config from SDK
        self.config = NetworkConfig.mainnet()
        # Initialize full SDK (requires some args, can pass None for unneeded ones like private_key)
        # Based on user input: sdk = OstiumSDK(config, private_key, rpc_url)
        # We only need read access, so let's try passing None/Dummy for credentials if allowed
        # Or better: Just replicate the logic using SubgraphClient directly if SDK init is heavy.
        
        # ACTUALLY, checking the user provided code again:
        # "SubGraphClient menggunakan URL dari config"
        # "Implementasi Anda berhasil mereplikasi fungsi... dengan pendekatan yang lebih sederhana"
        
        # The user seems to suggest using OstiumSDK is better ("Perbandingan dengan SDK"), 
        # but also previously said my custom implementation was "concise alternative".
        # BUT the error 'SubgraphClient' object has no attribute 'get_formatted_pairs_details' 
        # confirms that `get_formatted_pairs_details` is on the SDK class, not SubgraphClient.
        
        # So we must use OstiumSDK class to get that convenience method.
        # However, OstiumSDK requires RPC URL and Key. We might not have them.
        
        # Alternative: Re-implement the logic manually on top of SubgraphClient like the SDK snippet shown.
        # This avoids needing an RPC or Private Key just to read the graph.
        
        self.sdk = None # Not using full SDK to avoid auth requirements
        
        # Initialize SubgraphClient directly
        from ostium_python_sdk.subgraph import SubgraphClient
         
        # SDK default graph URL can go stale (e.g. 404 "Subgraph not found").
        # Allow overriding without code changes.
        self.graph_url = os.getenv("OSTIUM_SUBGRAPH_URL") or self.config.graph_url
        self.subgraph = SubgraphClient(url=self.graph_url)

        # Rate-limit repeated network/config errors to avoid log spam.
        self._last_error_log_at: float = 0.0
        self._last_error_sig: str | None = None
         
        # We also need PriceClient for the SDK's get_formatted_pairs_details logic
        # But we only care about VOLUME/OI here.
         
    async def get_formatted_pairs_details(self) -> List[Dict[str, Any]]:
        """
        Fetch pair details manually using SubgraphClient, optimizing to avoid sequential requests
        """
        try:
            # 1. Get all pairs - this already contains OI and maxOI fields
            pairs = await self.subgraph.get_pairs()
            formatted = []
            
            PRECISION_18 = Decimal("1000000000000000000")
            PRECISION_6 = Decimal("1000000")
            
            for pair_details in pairs:
                try:
                    # Calculate stats (logic from SDK)
                    long_oi = Decimal(pair_details.get('longOI', 0)) / PRECISION_18
                    short_oi = Decimal(pair_details.get('shortOI', 0)) / PRECISION_18
                    max_oi = Decimal(pair_details.get('maxOI', 0)) / PRECISION_6
                    
                    total_oi = long_oi + short_oi
                    
                    # Avoid zero division
                    if max_oi > 0:
                        utilization = (total_oi / max_oi) * 100
                    else:
                        utilization = Decimal(0)

                    formatted.append({
                        "symbol": f"{pair_details['from']}-{pair_details['to']}",
                        "longOI": float(long_oi),
                        "shortOI": float(short_oi),
                        "totalOI": float(total_oi), 
                        "utilization": float(utilization),
                        "totalOpenTrades": int(pair_details.get('totalOpenTrades', 0))
                    })
                except Exception as inner_e:
                    logger.warning(f"Error parsing pair {pair_details.get('id')}: {inner_e}")
                    continue
                    
            return formatted
            
        except Exception as e:
            msg = str(e)
            # Goldsky/graph endpoint missing is common when the SDK default URL is outdated.
            is_missing = ("404" in msg) or ("Not Found" in msg) or ("Subgraph not found" in msg)

            # Avoid spamming the same error every poll tick.
            now = time.time()
            sig = ("missing" if is_missing else "error") + ":" + msg[:200]
            should_log = (sig != self._last_error_sig) or ((now - self._last_error_log_at) > 600)

            if should_log:
                self._last_error_log_at = now
                self._last_error_sig = sig
                if is_missing:
                    logger.warning(
                        "Ostium subgraph endpoint returned 404/missing. "
                        f"Set OSTIUM_SUBGRAPH_URL to override. url={self.graph_url!r} err={msg}"
                    )
                else:
                    logger.error(f"Failed to fetch pairs from Subgraph: {e}")
            return []

    async def close(self):
        pass
