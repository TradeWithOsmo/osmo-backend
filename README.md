# OSMO Backend

Backend services for market streaming, API aggregation, portfolio/leaderboard logic, and agent tooling.

Repository: https://github.com/TradeWithOsmo/osmo-backend

## Services

- `websocket/`: main FastAPI API + WebSocket service
- `agent/`: AI agent service
- `connectors/`: exchange connector logic
- `analysis/`: analytics/support scripts

## Key Features

- Unified markets and symbol normalization pipeline
- Real-time orderbook/trades websocket endpoints
- Portfolio + leaderboard + arena endpoints
- On-chain order placement via session key (Base Sepolia)
- Trading/ledger simulation mode for UI testing
- Optional memory stack (Qdrant/mem0) depending on env/compose profile

## Prerequisites

- Python 3.13+
- Docker Desktop (recommended)

## Local Run (API only)

From `backend/websocket`:

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Local Run (Docker stack)

From `backend` root:

```bash
cp .env.example .env
docker compose up -d --build
```

Default local ports:

- API: `8000`
- Postgres: `5432`
- Redis: `6379`
- Uptime Kuma: `3002`

## Useful Endpoints

- `GET /health`
- `GET /docs`
- `GET /api/markets`
- `GET /api/candles/{symbol}`
- `GET /api/leaderboard/*`
- `GET /api/portfolio/*`
- `POST /api/agent/*`
- `POST /api/orders/place`
- `POST /api/orders/report`
- `GET /api/orders/history`
- `GET /api/orders/positions`

WebSocket examples:

- `/ws/orderbook/{symbol}`
- `/ws/trades/{symbol}`
- `/ws/hyperliquid/{symbol}`
- `/ws/ostium/{symbol}`

## Deployment (VPS)

VPS: `root@76.13.219.146`

```bash
# SSH access
ssh -i d:/WorkingSpace/backend/.deploy/osmo_deploy root@76.13.219.146
```

Two workflows are used:

1. SSH deploy workflow: `.github/workflows/deploy-vps.yml`
2. Self-hosted runner workflow: `.github/workflows/deploy-vps-runner.yml`

For stable operation:

- configure repo secrets (`VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_PRIVATE_KEY`, `DEPLOY_REPO_TOKEN`)
- keep runner online when using self-hosted workflow
- use `backend/websocket/scripts/deploy_stack.sh` for consistent compose deploy

## Health Checks and Logs

```bash
docker compose ps
curl -sS http://127.0.0.1:8000/health
docker compose logs --tail=200 backend
```

Orderbook/trades validation matrix:

```bash
docker exec osmo-backend python3 /app/check_ob_trades_matrix.py
```

## Important Env Vars

From `.env` / `websocket/.env` (depends on run mode):

### General

- `SAVE_TO_DB` — persist orders/positions to DB (`true`/`false`)
- `DATABASE_URL` — Postgres connection string
- `REDIS_URL` — Redis connection string
- `OPENROUTER_API_KEY` — for AI agent
- `SECONDARY_HISTORY_ENABLED`

### Trading Mode

- `FORCE_EXECUTION_MODE` — `onchain` (default, production) or `simulation` (UI testing only)

### On-Chain (Base Sepolia, required when FORCE_EXECUTION_MODE=onchain)

- `CHAIN_ID` — `84532`
- `NETWORK_NAME` — `base_sepolia`
- `ARBITRUM_RPC_URL` — Base Sepolia RPC URL (named for legacy reasons)
- `TRADING_VAULT_ADDRESS` — `0x7D909A44b5eb12cEf16ce4D824e259bC07E2927D`
- `ORDER_ROUTER_ADDRESS` — `0x411985C7f9C64c66A2C2390AbAC7AD9a718da60e`
- `SESSION_KEY_MANAGER_ADDRESS` — `0xc2853D45DA39B36b31cf12D92b6fe2e643c12DD8`
- `POSITION_MANAGER_ADDRESS` — `0xBE46bDB894325cf26A50AecFC0CED7a3c58271a0`
- `SESSION_KEY_PRIVATE_KEY` — backend signing key for session-key transactions

### Fee Collection

Trading fee (0.08% per order) accumulates in AIVault (`0x5aBb786D8fa77D8Cc7c689d78E871dbD57039ad4`).
To cover LZ cross-chain fees, periodically top up the HyperliquidLayerZeroAdapter (`0x009Df011949879ac88392B41B403765b22365BE3`) with ETH.

## Directory Map

- `websocket/main.py`: main entrypoint
- `websocket/routers/`: API route modules
- `websocket/services/`: business logic/services
- `websocket/*/api_client.py`: exchange integration clients
- `connectors/web3_arbitrum/onchain_connector.py`: on-chain order placement (web3.py v6)
- `contracts/addresses.json`: deployed contract addresses (source of truth: `osmo-contracts/.env`)
- `agent/src/`: agent backend

## Notes

- Frontend (`v1-web`) should point `VITE_API_URL` to this backend.
- For production-like deploys, use key-based SSH and avoid password auth.
- `connectors/web3_arbitrum/onchain_connector.py` uses web3.py v6 — all `get_logs()` calls use camelCase kwargs (`fromBlock`, `toBlock`).
- Backend signs onchain transactions using a stored session key, not the user's wallet.
