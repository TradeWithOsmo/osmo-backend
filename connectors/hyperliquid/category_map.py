
"""
Hyperliquid Category Mapping
Manually curated/heuristic mapping for token categories.
"""

CATEGORY_MAP = {
    # Layer 1
    "BTC": "Layer 1", "ETH": "Layer 1", "SOL": "Layer 1", "BNB": "Layer 1", "ADA": "Layer 1",
    "AVAX": "Layer 1", "TRX": "Layer 1", "TON": "Layer 1", "DOT": "Layer 1", "ALGO": "Layer 1",
    "SUI": "Layer 1", "APT": "Layer 1", "SEI": "Layer 1", "NEAR": "Layer 1", "ATOM": "Layer 1",
    "TIA": "Layer 1", "FTM": "Layer 1", "INJ": "Layer 1", "KAS": "Layer 1", "HBAR": "Layer 1",
    "BCH": "Layer 1", "BSV": "Layer 1", "CELO": "Layer 1", "CFX": "Layer 1", "ETC": "Layer 1",
    "ICP": "Layer 1", "IOTA": "Layer 1", "LTC": "Layer 1", "MINA": "Layer 1", "NEO": "Layer 1",
    "RUNE": "Layer 1", "XLM": "Layer 1", "XMR": "Layer 1", "XRP": "Layer 1", "ZEC": "Layer 1",
    "ZEN": "Layer 1", "ZETA": "Layer 1", "CANTO": "Layer 1", "DYM": "Layer 1", "EGLD": "Layer 1",
    "EOS": "Layer 1", "FLOW": "Layer 1", "KAVA": "Layer 1", "KLAY": "Layer 1", "LSK": "Layer 1",
    "OSMO": "Layer 1", "QTUM": "Layer 1", "ROSE": "Layer 1", "STX": "Layer 1", "WAVES": "Layer 1",
    "XTZ": "Layer 1", "ZIL": "Layer 1", "MON": "Layer 1", "BERA": "Layer 1", "DASH": "Layer 1",
            
    # Layer 2 / Scaling
    "ARB": "Layer 2", "OP": "Layer 2", "MATIC": "Layer 2", "MANTLE": "Layer 2", "STRK": "Layer 2",
    "IMX": "Layer 2", "BLUR": "Layer 2", "METIS": "Layer 2", "SCR": "Layer 2", "BLAST": "Layer 2",
    "LINEA": "Layer 2", "MERL": "Layer 2", "MNT": "Layer 2", "MODE": "Layer 2", "ZORA": "Layer 2",
    "ZK": "Layer 2", "STX": "Layer 2", "LRC": "Layer 2", "MANTA": "Layer 2", "ZRO": "Layer 2",
    "ASTR": "Layer 2", "BOBA": "Layer 2", "GLM": "Layer 2", "OMG": "Layer 2", "POLY": "Layer 2",
    
    # Meme
    "DOGE": "Meme", "SHIB": "Meme", "PEPE": "Meme", "WIF": "Meme", "BONK": "Meme", "FLOKI": "Meme",
    "BOME": "Meme", "MEME": "Meme", "PEOPLE": "Meme", "TRUMP": "Meme", "WLFI": "Meme", "TURBO": "Meme",
    "MEW": "Meme", "POPCAT": "Meme", "BRETT": "Meme", "MYRO": "Meme", "WEN": "Meme", "MOG": "Meme",
    "HPOS": "Meme", "BABY": "Meme", "CHILLGUY": "Meme", "DOOD": "Meme", "FARTCOIN": "Meme",
    "GOAT": "Meme", "GRIFFAIN": "Meme", "HPOS": "Meme", "JELLY": "Meme", "KAITO": "Meme",
    "MANEKI": "Meme", "MELANIA": "Meme", "MOODENG": "Meme", "MOTHER": "Meme", "NEIROETH": "Meme",
    "PENGU": "Meme", "PNUT": "Meme", "PUMP": "Meme", "PURR": "Meme", "SLERF": "Meme",
    "SNAKE": "Meme", "SPX": "Meme", "SUNDOG": "Meme", "TST": "Meme", "VINE": "Meme",
    "VVV": "Meme", "WHY": "Meme", "ZEREBRO": "Meme", "kBONK": "Meme", "kDOGS": "Meme",
    "kFLOKI": "Meme", "kLUNC": "Meme", "kNEIRO": "Meme", "kPEPE": "Meme", "kSHIB": "Meme",
    "FOGO": "Meme", "ANIME": "Meme", "CATI": "Meme", "HMSTR": "Meme",

    # AI & Big Data
    "RNDR": "AI & Big Data", "FET": "AI & Big Data", "TAO": "AI & Big Data", "WLD": "AI & Big Data",
    "ARKM": "AI & Big Data", "AGIX": "AI & Big Data", "OCEAN": "AI & Big Data", "AI": "AI & Big Data",
    "NFP": "AI & Big Data", "NMR": "AI & Big Data", "AI16Z": "AI & Big Data", "AIXBT": "AI & Big Data",
    "GRASS": "AI & Big Data", "IO": "AI & Big Data", "PROMPT": "AI & Big Data", "RENDER": "AI & Big Data",
    "SPEC": "AI & Big Data", "VIRTUAL": "AI & Big Data", "OLAS": "AI & Big Data", "PHB": "AI & Big Data",
    
    # DeFi
    "UNI": "DeFi", "AAVE": "DeFi", "MKR": "DeFi", "LDO": "DeFi", "CRV": "DeFi", "SNX": "DeFi",
    "DYDX": "DeFi", "PENDLE": "DeFi", "JUP": "DeFi", "ENA": "DeFi", "COMP": "DeFi", "RPL": "DeFi",
    "FXS": "DeFi", "GMX": "DeFi", "CAKE": "DeFi", "1INCH": "DeFi", "ALT": "DeFi", "APEX": "DeFi",
    "BADGER": "DeFi", "BANANA": "DeFi", "BNT": "DeFi", "CVX": "DeFi", "EIGEN": "DeFi",
    "ETHFI": "DeFi", "FRIEND": "DeFi", "INIT": "DeFi", "JTO": "DeFi", "LISTA": "DeFi",
    "MAV": "DeFi", "MORPHO": "DeFi", "OMNI": "DeFi", "ORBS": "DeFi", "PENDLE": "DeFi",
    "RAY": "DeFi", "RDNT": "DeFi", "REZ": "DeFi", "REQ": "DeFi", "RSR": "DeFi", "SAFE": "DeFi",
    "SPELL": "DeFi", "SUSHI": "DeFi", "STG": "DeFi", "SYRUP": "DeFi", "UMA": "DeFi",
    "UNIBOT": "DeFi", "USUAL": "DeFi", "VELO": "DeFi", "YFI": "DeFi", "ZK": "DeFi",
    "ZRX": "DeFi", "BAKE": "DeFi", "BAL": "DeFi", "BICO": "DeFi", "BURGER": "DeFi",
    "C98": "DeFi", "CHZ": "DeFi", "COTI": "DeFi", "DODO": "DeFi", "FLM": "DeFi",
    "FRONT": "DeFi", "JOE": "DeFi", "KNC": "DeFi", "LQTY": "DeFi", "PERP": "DeFi",
    "QUICK": "DeFi", "REN": "DeFi", "SRM": "DeFi", "TRB": "DeFi", "WOO": "DeFi",
    "SKY": "DeFi", "AERO": "DeFi", "SKR": "DeFi", "FTT": "DeFi", "BIO": "DeFi",

    # DePIN
    "FIL": "DePIN", "HNT": "DePIN", "THETA": "DePIN", "AR": "DePIN", "AKT": "DePIN",
    "IOTX": "DePIN", "MOBILE": "DePIN", "HONEY": "DePIN", "SHDW": "DePIN", "STRK": "DePIN",
    "GLM": "DePIN", "LPT": "DePIN", "POKT": "DePIN",

    # RWA (Real World Assets)
    "ONDO": "RWA", "TRU": "RWA", "POLYX": "RWA", "CFG": "RWA", "MPL": "RWA", "GFI": "RWA",
    "NXPC": "RWA", "OM": "RWA", "PAXG": "RWA", "PROVE": "RWA", "USTC": "RWA", "WCT": "RWA",
    "RIO": "RWA", "UBXS": "RWA",

    # Gaming / Metaverse
    "GALA": "Gaming", "AXS": "Gaming", "SAND": "Gaming", "MANA": "Gaming", "BEAM": "Gaming",
    "PIXEL": "Gaming", "ILV": "Gaming", "APE": "Gaming", "PRIME": "Gaming", "ACE": "Gaming",
    "BIGTIME": "Gaming", "BLZ": "Gaming", "DAR": "Gaming", "GHST": "Gaming", "GMT": "Gaming",
    "HIGH": "Gaming", "IMX": "Gaming", "MAVIA": "Gaming", "PORTAL": "Gaming", "RON": "Gaming",
    "SUPER": "Gaming", "XAI": "Gaming", "YGG": "Gaming", "ALICE": "Gaming", "COMBO": "Gaming",
    "ENJ": "Gaming", "FLOW": "Gaming", "MAGIC": "Gaming", "MBOX": "Gaming", "PYR": "Gaming",
    "SLP": "Gaming", "WAXP": "Gaming", "ME": "Gaming",

    # Infrastructure / Oracle
    "PYTH": "Infrastructure", "LINK": "Infrastructure", "GRT": "Infrastructure", "W": "Infrastructure",
    "ARK": "Infrastructure", "AVNT": "Infrastructure", "CYBER": "Infrastructure", "ENS": "Infrastructure",
    "GAS": "Infrastructure", "HYPE": "Infrastructure", "JASMY": "Infrastructure", "LIT": "Infrastructure",
    "LOOM": "Infrastructure", "NIL": "Infrastructure", "OGN": "Infrastructure", "ORDI": "Infrastructure",
    "PANDORA": "Infrastructure", "RAD": "Infrastructure", "SAGA": "Infrastructure", "STORJ": "Infrastructure",
    "TNSR": "Infrastructure", "VANRY": "Infrastructure", "WORM": "Infrastructure", "ZETA": "Infrastructure",
    "API3": "Infrastructure", "BAND": "Infrastructure", "BLZ": "Infrastructure", "CTSI": "Infrastructure",
    "DIA": "Infrastructure", "OCEAN": "Infrastructure", "RLC": "Infrastructure", "TRB": "Infrastructure",
    "UMA": "Infrastructure",

    # Other/Uncategorized (Mapping known ones to broad categories or specific niches if valid)
    "0G": "Infrastructure",
    "2Z": "Meme", # Assumption
    "ASTER": "Infrastructure",
    "CC": "Meme",
    "HEMI": "Infrastructure",
    "HYPER": "Infrastructure",
    "IP": "Infrastructure",
    "LAYER": "Infrastructure",
    "MEGA": "Meme",
    "MET": "Infrastructure",
    "MOVE": "Infrastructure",
    "OX": "DeFi",
    "POL": "Layer 2", # Polygon rebranding
    "RESOLV": "DeFi",
    "S": "Infrastructure",
    "SOPH": "Infrastructure",
    "STABLE": "DeFi",
    "STBL": "DeFi",
    "STRAX": "Infrastructure",
    "XPL": "Infrastructure",
    "YZY": "Meme",
    "NOT": "Gaming", # Clicker game
}

# Main category mapping: sub-categories → main frontend category
_MAIN_CATEGORY = {
    "Layer 1": "L1",
    "Layer 2": "L2",
    "Meme": "MEME",
    "AI & Big Data": "AI",
    "DeFi": "DEFI",
    "DePIN": "DEPIN",  # Optional, frontend might map to default Crypto
    "RWA": "RWA",
    "Gaming": "GAMING",
    "Infrastructure": "Crypto",  # No direct match, map to Crypto
    "Crypto": "Crypto",
    "Forex": "Forex",
    "Stocks": "Stocks",
    "Commodities": "Commodities",
    "Index": "Index",
}

def get_subcategory(symbol: str) -> str:
    """Get detailed sub-category for a symbol."""
    clean_symbol = symbol.split("-")[0].replace("/USD", "")
    return CATEGORY_MAP.get(clean_symbol, "Crypto")

def get_category(symbol: str) -> str:
    """Get category for a symbol matching the frontend expected categories."""
    sub = get_subcategory(symbol)
    return _MAIN_CATEGORY.get(sub, "Crypto")
