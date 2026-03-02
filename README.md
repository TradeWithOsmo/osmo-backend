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
- Trading/ledger simulation and API orchestration
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

WebSocket examples:

- `/ws/orderbook/{symbol}`
- `/ws/trades/{symbol}`
- `/ws/hyperliquid/{symbol}`
- `/ws/ostium/{symbol}`

## Deployment (VPS)

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

- `SAVE_TO_DB`
- `DATABASE_URL`
- `REDIS_URL`
- `FORCE_EXECUTION_MODE`
- `OPENROUTER_API_KEY`
- `SECONDARY_HISTORY_ENABLED`
- contract addresses (`TRADING_VAULT_ADDRESS`, `ORDER_ROUTER_ADDRESS`, etc.)

## Directory Map

- `websocket/main.py`: main entrypoint
- `websocket/routers/`: API route modules
- `websocket/services/`: business logic/services
- `websocket/*/api_client.py`: exchange integration clients
- `agent/src/`: agent backend

## Notes

- Frontend (`v1-web`) should point `VITE_API_URL` to this backend.
- For production-like deploys, use key-based SSH and avoid password auth.
