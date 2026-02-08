from backend.agent.Tools.data.market import _normalize_symbol_candidates, _select_market


def test_normalize_symbol_candidates_handles_fiat_pairs():
    candidates = _normalize_symbol_candidates("usd/chf")
    assert "USD-CHF" in candidates
    assert "USDCHF" in candidates
    assert "USD/CHF" in candidates


def test_select_market_matches_condensed_fiat_symbol():
    markets = [
        {"symbol": "USDCHF", "price": "0.77258"},
        {"symbol": "EURUSD", "price": "1.18562"},
    ]
    row = _select_market(markets, "USD-CHF")
    assert row is not None
    assert row.get("symbol") == "USDCHF"
