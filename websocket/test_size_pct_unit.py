"""
Standalone test for size_pct logic — pure Python, no imports needed.
"""

def _resolve_amount_usd(amount_usd, size_pct, tool_states):
    if size_pct is not None:
        try:
            pct = float(size_pct)
        except (TypeError, ValueError):
            return 0.0, "size_pct must be a number between 0 and 1."
        if pct <= 0 or pct > 1:
            return 0.0, f"size_pct must be between 0 and 1. Got {pct}."
        free_collateral = float(
            tool_states.get("free_collateral_usd")
            or tool_states.get("trading_balance_usd")
            or 0
        )
        if free_collateral <= 0:
            return 0.0, "free_collateral_usd is 0 or not available."
        computed = round(free_collateral * pct, 2)
        if computed < 10:
            return 0.0, f"Computed ${computed:.2f} is below minimum $10."
        return computed, None
    if amount_usd is None:
        return 0.0, "Provide either amount_usd or size_pct."
    try:
        val = float(amount_usd)
    except (TypeError, ValueError):
        return 0.0, "amount_usd must be a number."
    if val <= 0:
        return 0.0, "amount_usd must be greater than 0."
    return val, None


BALANCE = {"free_collateral_usd": 1000.0}
EMPTY   = {}
PASS = FAIL = 0

def test(label, *args, expect_ok):
    global PASS, FAIL
    amt, err = _resolve_amount_usd(*args)
    ok = err is None
    if ok == expect_ok:
        icon = "✅ PASS"
        PASS += 1
    else:
        icon = "❌ FAIL"
        FAIL += 1
    detail = f"→ ${amt}" if ok else f"→ ERROR: {err}"
    print(f"  {icon}  {label}  {detail}")

print("\n=== size_pct resolution tests ===\n")
test("25% of $1000 = $250",   None, 0.25, BALANCE, expect_ok=True)
test("50% of $1000 = $500",   None, 0.5,  BALANCE, expect_ok=True)
test("75% of $1000 = $750",   None, 0.75, BALANCE, expect_ok=True)
test("100% of $1000 = $1000", None, 1.0,  BALANCE, expect_ok=True)
test("size_pct=0 invalid",    None, 0.0,  BALANCE, expect_ok=False)
test("size_pct=1.5 invalid",  None, 1.5,  BALANCE, expect_ok=False)
test("size_pct no balance",   None, 0.5,  EMPTY,   expect_ok=False)
test("explicit $200 ok",      200,  None, BALANCE, expect_ok=True)
test("explicit $0 invalid",   0,    None, BALANCE, expect_ok=False)
test("no args → error",       None, None, BALANCE, expect_ok=False)

# Verify exact values
for pct, expected in [(0.25, 250.0), (0.5, 500.0), (0.75, 750.0), (1.0, 1000.0)]:
    amt, _ = _resolve_amount_usd(None, pct, BALANCE)
    assert amt == expected, f"FAIL: {pct} → {amt} != {expected}"

print(f"\n=== {PASS} passed, {FAIL} failed ===\n")
if FAIL:
    raise SystemExit(1)
print("All tests passed! ✅")
