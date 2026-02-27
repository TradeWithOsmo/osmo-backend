import asyncio
import httpx

async def check_specific_symbols():
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get("http://127.0.0.1:8000/api/markets/")
        if resp.status_code == 200:
            markets = resp.json().get("markets", [])
            
            # Check Aster symbols
            aster_syms = [m.get("symbol") for m in markets if m.get("source") == "aster"]
            print(f"Aster symbols count: {len(aster_syms)}")
            print(f"Sample Aster: {aster_syms[:5]}")
            
            # Check Vest symbols
            vest_syms = [m.get("symbol") for m in markets if m.get("source") == "vest"]
            print(f"Vest symbols count: {len(vest_syms)}")
            print(f"Sample Vest: {vest_syms[:5]}")
            
            # Specifically check RECALL and MSI
            for sym in ["RECALLUSDT", "RECALL-USD", "RECALL", "RAVEUSDT"]:
                found = [m for m in aster_syms if sym in m]
                if found:
                    print(f"Found Aster match for '{sym}': {found}")
            
            for sym in ["MSI-USD-PERP", "MSI-PERP", "MSI"]:
                found = [m for m in vest_syms if sym in m]
                if found:
                    print(f"Found Vest match for '{sym}': {found}")

if __name__ == "__main__":
    asyncio.run(check_specific_symbols())
