
"""Ostium Subgraph Client using Official SDK"""
import logging
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
        
        self.subgraph = SubgraphClient(url=self.config.graph_url)
        
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
            logger.error(f"Failed to fetch pairs from Subgraph: {e}")
            return []

    async def close(self):
        pass
