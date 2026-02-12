from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from ..Config.tools_config import TRADE_DECISION_COMPARATORS
from .tool_modes import classify_tool_mode


@dataclass(frozen=True)
class ToolModule:
    name: str
    description: str
    inputs: str
    outputs: str
    snippet: str
    category: str


_TOOL_MODULES: Dict[str, ToolModule] = {
    "list_supported_indicator_aliases": ToolModule(
        name="list_supported_indicator_aliases",
        description="List indicator aliases and canonical TradingView indicator names.",
        inputs="none",
        outputs="aliases[], canonical_names[], alias_map{}",
        snippet="list_supported_indicator_aliases()",
        category="read",
    ),
    "set_symbol": ToolModule(
        name="set_symbol",
        description="Switch chart symbol/source before symbol-scoped actions.",
        inputs="symbol, target_symbol, target_source?",
        outputs="status, data.current_symbol",
        snippet='set_symbol(symbol="BTC-USD", target_symbol="SOL-USD")',
        category="write",
    ),
    "set_timeframe": ToolModule(
        name="set_timeframe",
        description="Set chart timeframe for the active symbol.",
        inputs="symbol, timeframe",
        outputs="status, data.current_timeframe",
        snippet='set_timeframe(symbol="SOL-USD", timeframe="15m")',
        category="write",
    ),
    "add_indicator": ToolModule(
        name="add_indicator",
        description="Add indicator to active chart.",
        inputs="symbol, name, inputs?, force_overlay?",
        outputs="status, data.indicators",
        snippet='add_indicator(symbol="SOL-USD", name="RSI")',
        category="write",
    ),
    "remove_indicator": ToolModule(
        name="remove_indicator",
        description="Remove a single indicator from chart.",
        inputs="symbol, name",
        outputs="status, data.indicators",
        snippet='remove_indicator(symbol="SOL-USD", name="RSI")',
        category="write",
    ),
    "clear_indicators": ToolModule(
        name="clear_indicators",
        description="Clear all chart indicators.",
        inputs="symbol",
        outputs="status, data.indicators=[]",
        snippet='clear_indicators(symbol="SOL-USD")',
        category="write",
    ),
    "get_active_indicators": ToolModule(
        name="get_active_indicators",
        description="Read indicators currently active on chart.",
        inputs="symbol, timeframe?",
        outputs="data.indicators[]",
        snippet='get_active_indicators(symbol="SOL-USD", timeframe="1H")',
        category="read",
    ),
    "get_high_low_levels": ToolModule(
        name="get_high_low_levels",
        description="Compute rolling high/low support-resistance levels.",
        inputs="symbol, timeframe, lookback, limit, asset_type?",
        outputs="data.levels, data.high, data.low",
        snippet='get_high_low_levels(symbol="SOL", timeframe="1H", lookback=7)',
        category="read",
    ),
    "draw": ToolModule(
        name="draw",
        description="Create drawing object on chart.",
        inputs="symbol, tool, points, style?",
        outputs="status, data.drawing_id",
        snippet='draw(symbol="SOL-USD", tool="horizontal_line", points=[...])',
        category="write",
    ),
    "update_drawing": ToolModule(
        name="update_drawing",
        description="Update existing drawing object.",
        inputs="symbol, drawing_id, updates",
        outputs="status, data.drawing_id",
        snippet='update_drawing(symbol="SOL-USD", drawing_id="x", updates={...})',
        category="write",
    ),
    "clear_drawings": ToolModule(
        name="clear_drawings",
        description="Clear drawings from chart.",
        inputs="symbol",
        outputs="status",
        snippet='clear_drawings(symbol="SOL-USD")',
        category="write",
    ),
    "list_supported_draw_tools": ToolModule(
        name="list_supported_draw_tools",
        description="List available draw tools and alias map.",
        inputs="none",
        outputs="tools[], aliases[]",
        snippet="list_supported_draw_tools()",
        category="read",
    ),
    "setup_trade": ToolModule(
        name="setup_trade",
        description=(
            "Place trade setup objects (entry/TP/SL/GP/GL) and map GP->validation, GL->invalidation decisions."
        ),
        inputs=(
            "symbol, side, entry, tp, sl, tp2?, tp3?, trailing_sl?, be?, liq?, "
            "gp?/validation?, gl?/invalidation?"
        ),
        outputs=(
            "status, data.trade_setup, decision.validation, decision.invalidation"
        ),
        snippet=(
            'setup_trade(symbol="SOL-USD", side="long", entry=120, tp=128, sl=116, gp=124, gl=118)'
        ),
        category="write",
    ),
    "place_order": ToolModule(
        name="place_order",
        description="Execute a live trade order (market/limit).",
        inputs="symbol, side, amount_usd, leverage?, order_type?, price?, stop_price?, tp?, sl?, exchange?, tool_states?",
        outputs="status, order_id, fills[]",
        snippet='place_order(symbol="SOL-USD", side="long", amount_usd=100, leverage=5, order_type="market")',
        category="write",
    ),
    "add_price_alert": ToolModule(
        name="add_price_alert",
        description="Create price alert on selected symbol/level.",
        inputs="symbol, condition, price, note?",
        outputs="status, data.alert_id",
        snippet='add_price_alert(symbol="SOL-USD", condition="above", price=130)',
        category="write",
    ),
    "mark_trading_session": ToolModule(
        name="mark_trading_session",
        description="Mark session block (Asia/London/NY) on chart.",
        inputs="symbol, session_name, start_time?, end_time?",
        outputs="status, data.session_marker",
        snippet='mark_trading_session(symbol="SOL-USD", session_name="NY")',
        category="write",
    ),
    "get_price": ToolModule(
        name="get_price",
        description="Fetch latest tradable price for a symbol.",
        inputs="symbol, asset_type?",
        outputs="data.price",
        snippet='get_price(symbol="SOL", asset_type="crypto")',
        category="read",
    ),
    "get_candles": ToolModule(
        name="get_candles",
        description="Fetch OHLCV candle series for timeframe analysis.",
        inputs="symbol, timeframe, limit, asset_type?",
        outputs="data.candles[]",
        snippet='get_candles(symbol="SOL", timeframe="15m", limit=300)',
        category="read",
    ),
    "get_orderbook": ToolModule(
        name="get_orderbook",
        description="Fetch bid/ask depth snapshot for symbol.",
        inputs="symbol, asset_type?",
        outputs="data.bids, data.asks",
        snippet='get_orderbook(symbol="SOL", asset_type="crypto")',
        category="read",
    ),
    "get_funding_rate": ToolModule(
        name="get_funding_rate",
        description="Fetch perp funding-rate context.",
        inputs="symbol, asset_type?",
        outputs="data.funding_rate",
        snippet='get_funding_rate(symbol="SOL", asset_type="crypto")',
        category="read",
    ),
    "get_ticker_stats": ToolModule(
        name="get_ticker_stats",
        description="Fetch ticker stats (volume/change/high/low).",
        inputs="symbol, asset_type?",
        outputs="data.stats",
        snippet='get_ticker_stats(symbol="SOL", asset_type="crypto")',
        category="read",
    ),
    "get_chainlink_price": ToolModule(
        name="get_chainlink_price",
        description="Fetch oracle reference price (Chainlink when available).",
        inputs="symbol",
        outputs="data.price",
        snippet='get_chainlink_price(symbol="SOL")',
        category="read",
    ),
    "get_technical_analysis": ToolModule(
        name="get_technical_analysis",
        description="Compute technical summary/signals for symbol + timeframe.",
        inputs="symbol, timeframe, asset_type?",
        outputs="data.technical",
        snippet='get_technical_analysis(symbol="SOL-USD", timeframe="1H")',
        category="read",
    ),
    "get_patterns": ToolModule(
        name="get_patterns",
        description="Detect chart pattern candidates.",
        inputs="symbol, timeframe, asset_type?",
        outputs="data.patterns[]",
        snippet='get_patterns(symbol="SOL-USD", timeframe="1H")',
        category="read",
    ),
    "get_indicators": ToolModule(
        name="get_indicators",
        description="Fetch indicator numeric values.",
        inputs="symbol, timeframe, asset_type?",
        outputs="data.indicators",
        snippet='get_indicators(symbol="SOL-USD", timeframe="1H")',
        category="read",
    ),
    "get_technical_summary": ToolModule(
        name="get_technical_summary",
        description="Return concise multi-indicator technical summary.",
        inputs="symbol, timeframe, asset_type?",
        outputs="data.summary",
        snippet='get_technical_summary(symbol="SOL-USD", timeframe="1H")',
        category="read",
    ),
    "get_whale_activity": ToolModule(
        name="get_whale_activity",
        description="Fetch large-flow/whale activity snapshots.",
        inputs="symbol, min_size_usd?",
        outputs="data.flows[]",
        snippet='get_whale_activity(symbol="SOL", min_size_usd=100000)',
        category="read",
    ),
    "get_token_distribution": ToolModule(
        name="get_token_distribution",
        description="Fetch token holder concentration/distribution data.",
        inputs="symbol",
        outputs="data.distribution",
        snippet='get_token_distribution(symbol="SOL")',
        category="read",
    ),
    "search_news": ToolModule(
        name="search_news",
        description="Search latest relevant news/headlines.",
        inputs="query, mode?, source?",
        outputs="data.items[]",
        snippet='search_news(query="SOL market news", mode="quality")',
        category="read",
    ),
    "search_sentiment": ToolModule(
        name="search_sentiment",
        description="Fetch social/news sentiment signal for symbol.",
        inputs="symbol",
        outputs="data.sentiment",
        snippet='search_sentiment(symbol="SOL")',
        category="read",
    ),
    "adjust_position_tpsl": ToolModule(
        name="adjust_position_tpsl",
        description="Adjust TP/SL for one open position.",
        inputs="user_address, symbol, tp?, sl?, exchange?",
        outputs="status, data.position_update",
        snippet='adjust_position_tpsl(user_address="0x..", symbol="SOL-USD", tp="130", sl="118")',
        category="read",
    ),
    "adjust_all_positions_tpsl": ToolModule(
        name="adjust_all_positions_tpsl",
        description="Bulk adjust TP/SL across open positions.",
        inputs="user_address, tp?/sl?/tp_pct?/sl_pct?",
        outputs="status, data.bulk_update",
        snippet='adjust_all_positions_tpsl(user_address="0x..", tp_pct=3.0, sl_pct=1.5)',
        category="read",
    ),
    "add_memory": ToolModule(
        name="add_memory",
        description="Store memory fact/snippet for user profile/context.",
        inputs="user_id, text, metadata?",
        outputs="status, data.memory_id",
        snippet='add_memory(user_id="0x..", text="User prefers pullback entries")',
        category="read",
    ),
    "search_memory": ToolModule(
        name="search_memory",
        description="Search long-term memory by semantic query.",
        inputs="user_id, query, limit?",
        outputs="results[]",
        snippet='search_memory(user_id="0x..", query="risk preference", limit=5)',
        category="read",
    ),
    "get_recent_history": ToolModule(
        name="get_recent_history",
        description="Fetch recent chat/action history context.",
        inputs="session_id?, limit?",
        outputs="history[]",
        snippet='get_recent_history(session_id="s-1234", limit=20)',
        category="read",
    ),
    "search_knowledge_base": ToolModule(
        name="search_knowledge_base",
        description="Semantic retrieval from RAG knowledge base.",
        inputs="query, category?, top_k?",
        outputs="results[]",
        snippet='search_knowledge_base(query="risk management", top_k=4)',
        category="read",
    ),
    "get_drawing_guidance": ToolModule(
        name="get_drawing_guidance",
        description="Retrieve drawing best-practice guidance snippets.",
        inputs="tool_name",
        outputs="guidance",
        snippet='get_drawing_guidance(tool_name="trendline")',
        category="read",
    ),
    "get_trade_management_guidance": ToolModule(
        name="get_trade_management_guidance",
        description="Retrieve TP/SL/risk management guidance.",
        inputs="topic",
        outputs="guidance",
        snippet='get_trade_management_guidance(topic="stop loss")',
        category="read",
    ),
    "get_market_context_guidance": ToolModule(
        name="get_market_context_guidance",
        description="Retrieve market regime/context framework guidance.",
        inputs="none",
        outputs="guidance",
        snippet="get_market_context_guidance()",
        category="read",
    ),
    "consult_strategy": ToolModule(
        name="consult_strategy",
        description="Ask strategy KB for setup/playbook guidance.",
        inputs="question",
        outputs="answer",
        snippet='consult_strategy(question="best pullback confirmation?")',
        category="read",
    ),
    "get_screenshot": ToolModule(
        name="get_screenshot",
        description="Capture chart screenshot from current viewport.",
        inputs="symbol?, target?, quality?",
        outputs="status, data.image",
        snippet='get_screenshot(symbol="SOL-USD", target="canvas")',
        category="nav",
    ),
    "focus_chart": ToolModule(
        name="focus_chart",
        description="Focus chart canvas before navigation/drawing inputs.",
        inputs="symbol",
        outputs="status",
        snippet='focus_chart(symbol="SOL-USD")',
        category="nav",
    ),
    "ensure_mode": ToolModule(
        name="ensure_mode",
        description="Ensure current interaction mode (nav/drawing).",
        inputs="symbol, mode",
        outputs="status",
        snippet='ensure_mode(symbol="SOL-USD", mode="nav")',
        category="nav",
    ),
    "mouse_move": ToolModule(
        name="mouse_move",
        description="Move mouse cursor on chart (absolute/relative).",
        inputs="symbol, x, y, relative?",
        outputs="status",
        snippet='mouse_move(symbol="SOL-USD", x=200, y=150, relative=False)',
        category="nav",
    ),
    "mouse_press": ToolModule(
        name="mouse_press",
        description="Simulate mouse press/click on chart.",
        inputs="symbol, state(down|up|click)",
        outputs="status",
        snippet='mouse_press(symbol="SOL-USD", state="click")',
        category="nav",
    ),
    "pan": ToolModule(
        name="pan",
        description="Pan chart along time/price axis.",
        inputs="symbol, axis, direction, amount",
        outputs="status",
        snippet='pan(symbol="SOL-USD", axis="time", direction="left", amount="large")',
        category="nav",
    ),
    "zoom": ToolModule(
        name="zoom",
        description="Zoom chart in/out or set visible candle range.",
        inputs="symbol, mode, amount?",
        outputs="status",
        snippet='zoom(symbol="SOL-USD", mode="range", amount=300)',
        category="nav",
    ),
    "press_key": ToolModule(
        name="press_key",
        description="Send keyboard key command to chart.",
        inputs="symbol, key",
        outputs="status",
        snippet='press_key(symbol="SOL-USD", key="Escape")',
        category="nav",
    ),
    "focus_latest": ToolModule(
        name="focus_latest",
        description="Jump viewport to latest candle.",
        inputs="symbol",
        outputs="status",
        snippet='focus_latest(symbol="SOL-USD")',
        category="nav",
    ),
    "set_crosshair": ToolModule(
        name="set_crosshair",
        description="Enable/disable crosshair mode.",
        inputs="symbol, active",
        outputs="status",
        snippet='set_crosshair(symbol="SOL-USD", active=True)',
        category="nav",
    ),
    "move_crosshair": ToolModule(
        name="move_crosshair",
        description="Move crosshair along time/price axis.",
        inputs="symbol, axis, direction, amount",
        outputs="status",
        snippet='move_crosshair(symbol="SOL-USD", axis="time", direction="left", amount="small")',
        category="nav",
    ),
    "hover_candle": ToolModule(
        name="hover_candle",
        description="Hover specific candle index from right side of chart.",
        inputs="symbol, from_right, price_level?",
        outputs="status",
        snippet='hover_candle(symbol="SOL-USD", from_right=50)',
        category="nav",
    ),
    "inspect_cursor": ToolModule(
        name="inspect_cursor",
        description="Read OHLC/indicator snapshot under cursor/crosshair.",
        inputs="symbol",
        outputs="data.ohlc, data.indicators",
        snippet='inspect_cursor(symbol="SOL-USD")',
        category="nav",
    ),
    "capture_moment": ToolModule(
        name="capture_moment",
        description="Capture screenshot + data snapshot at current state.",
        inputs="symbol, caption?",
        outputs="status, data.snapshot",
        snippet='capture_moment(symbol="SOL-USD", caption="sr_check")',
        category="nav",
    ),
    "get_photo_chart": ToolModule(
        name="get_photo_chart",
        description="Capture PNG chart photo for analysis handoff.",
        inputs="symbol, target?",
        outputs="status, data.image",
        snippet='get_photo_chart(symbol="SOL-USD", target="canvas")',
        category="nav",
    ),
    "get_canvas": ToolModule(
        name="get_canvas",
        description="Get chart canvas selector metadata.",
        inputs="symbol",
        outputs="data.selector",
        snippet='get_canvas(symbol="SOL-USD")',
        category="nav",
    ),
    "get_box": ToolModule(
        name="get_box",
        description="Get chart canvas bounding box coordinates.",
        inputs="symbol",
        outputs="data.box",
        snippet='get_box(symbol="SOL-USD")',
        category="nav",
    ),
    "reset_view": ToolModule(
        name="reset_view",
        description="Reset chart viewport to default.",
        inputs="symbol",
        outputs="status",
        snippet='reset_view(symbol="SOL-USD")',
        category="nav",
    ),
    "research_market": ToolModule(
        name="research_market",
        description="Research a symbol across ALL markets (Hyperliquid + Ostium). Compares prices, technicals, levels.",
        inputs="symbol, timeframe?, include_depth?",
        outputs="status, markets_checked, spread_pct, best_price_market, summary, snapshots[]",
        snippet='research_market(symbol="BTC", timeframe="1H")',
        category="read",
    ),
    "compare_markets": ToolModule(
        name="compare_markets",
        description="Compare multiple symbols across all markets simultaneously. Batch research for screening.",
        inputs="symbols[], timeframe?",
        outputs="status, reports[], combined_summary",
        snippet='compare_markets(symbols=["BTC", "ETH", "SOL"], timeframe="1H")',
        category="read",
    ),
    "scan_market_overview": ToolModule(
        name="scan_market_overview",
        description="Get broad market overview with top movers from Hyperliquid and/or Ostium.",
        inputs="asset_class? (crypto|rwa|all)",
        outputs="status, markets{}",
        snippet='scan_market_overview(asset_class="all")',
        category="read",
    ),
}


_FLOW_TEMPLATES: List[str] = [
    (
        "indicator_inside_symbol: "
        "list_supported_indicator_aliases(optional) -> add_indicator -> get_active_indicators "
        "(use when requested symbol == active chart symbol)."
    ),
    (
        "indicator_outside_symbol: "
        "set_symbol -> list_supported_indicator_aliases(optional) -> add_indicator -> get_active_indicators "
        "(use when requested symbol != active chart symbol)."
    ),
    (
        "write_high_low_inside_symbol: "
        "get_high_low_levels -> draw/update_drawing/setup_trade/add_price_alert/mark_trading_session "
        "(write support/resistance with measured levels)."
    ),
    (
        "write_high_low_outside_symbol: "
        "set_symbol -> get_high_low_levels -> draw/update_drawing/setup_trade/add_price_alert/mark_trading_session "
        "(switch symbol first, then calculate levels, then write)."
    ),
    (
        "setup_trade_validation_invalidation_flow: "
        "setup_trade(side,entry,tp/sl,gp/gl) -> optional add_price_alert(gp/gl) -> "
        "TP/SL remain standard trade-management levels -> "
        "set GP near closest validation point and GL near closest invalidation point -> "
        "if GP/validation touched then generate validation decision -> "
        "if GL/invalidation touched then generate invalidation decision."
    ),
    (
        "setup_trade_trigger_rules: "
        f"long: validation trigger price {TRADE_DECISION_COMPARATORS.get('long', {}).get('validation', '>=')} GP, "
        f"invalidation trigger price {TRADE_DECISION_COMPARATORS.get('long', {}).get('invalidation', '<=')} GL; "
        f"short: validation trigger price {TRADE_DECISION_COMPARATORS.get('short', {}).get('validation', '<=')} GP, "
        f"invalidation trigger price {TRADE_DECISION_COMPARATORS.get('short', {}).get('invalidation', '>=')} GL."
    ),
    (
        "inspect_more_candles_inside_symbol: "
        "set_timeframe -> focus_latest -> zoom(range) -> pan(time,left) -> hover_candle -> inspect_cursor -> capture_moment"
    ),
    (
        "inspect_more_candles_outside_symbol: "
        "set_symbol -> set_timeframe -> focus_latest -> zoom(range) -> pan(time,left) -> hover_candle -> inspect_cursor -> capture_moment"
    ),
]


def get_tool_module(tool_name: str) -> ToolModule:
    module = _TOOL_MODULES.get(tool_name)
    if module is not None:
        return module
    category = classify_tool_mode(tool_name)
    return ToolModule(
        name=tool_name,
        description="Tool action in trading runtime.",
        inputs="see tool schema",
        outputs="tool-defined payload",
        snippet=f"{tool_name}(...)",
        category=category,
    )


def render_tool_modules_for_prompt(available_tool_names: Iterable[str], max_items: int = 80) -> str:
    lines: List[str] = []
    for idx, name in enumerate(sorted({str(n).strip() for n in available_tool_names if str(n).strip()}), start=1):
        if idx > max_items:
            break
        module = get_tool_module(name)
        lines.append(
            f"- {module.name} [{module.category}] | {module.description} | "
            f"in={module.inputs} | out={module.outputs} | ex={module.snippet}"
        )
    return "\n".join(lines)


def render_flow_templates_for_prompt() -> str:
    return "\n".join(f"- {item}" for item in _FLOW_TEMPLATES)
