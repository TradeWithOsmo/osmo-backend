# OSMO Backend

Backend services for market data, trading simulation/on-chain execution routing, AI agent runtime, and arena/leaderboard computation.

Repository: https://github.com/TradeWithOsmo/osmo-backend

## Architecture

The backend repository contains multiple services:

- `websocket/` - main FastAPI service for APIs + WebSocket streams
- `agent/` - AI agent runtime and tools service
- `connectors/` - market/connectivity integrations
- `analysis/` - analytics scripts and support modules

## Mermaid Diagram

```mermaid
%%{init: {
  'theme': 'base',
  'themeVariables': {
    'fontFamily': 'Inter, sans-serif',
    'fontSize': '11px'
  },
  'flowchart': {
    'nodeSpacing': 50,
    'rankSpacing': 80,
    'padding': 30
  }
}}%%

flowchart TD
    subgraph INPUT["INPUT"]
        USER["USER PROMPT"]
        FE["FRONTEND"]
    end

    subgraph REACT["ReACT ORCHESTRATOR"]
        ORCH["ORCHESTRATOR"]
        REASON["REASONING"]
        ACT["ACTION"]
        OBS["OBSERVE"]
    end

    subgraph GATES["PERMISSION GATES"]
        GWRITE{"ENABLE WRITE?"}
        GEXEC{"ENABLE EXECUTION?"}
    end

    subgraph FTOOLS["FRONTEND TOOLS"]
        HINT["HINT/INDICATOR"]
        TF["TIMEFRAME"]
        ATTACH["ATTACHMENT"]
        PHOTO["PHOTO/DOC"]
        TVWRITE["TV WRITE/ADD/GET/NAV"]
        MKTORDER["MARKET ORDER"]
    end

    subgraph STYLES["AI STYLES"]
        SSTYLE{"STYLE TYPE?"}
        CONV["CONVERSATION"]
        TSTYLE["TRADING STYLE"]
        JESSE["JESSE LIVERMORE"]
        DARVAS["NICOLAS DARVAS"]
        OTHERS["OTHERS"]
    end

    subgraph BTOOLS["BACKEND TOOLS"]
        WEB["WEB SEARCH"]
        MEM["MEMORY"]
        TVAPI["TRADINGVIEW API"]
        ENABLE{"ENABLED?"}
    end

    subgraph CONNECTORS["DATA CONNECTORS"]
        HL["HYPERLIQUID"]
        OST["OSTIUM"]
        CHAIN["CHAINLINK"]
        DUNE["DUNE"]
    end

    subgraph KNOWLEDGE["KNOWLEDGE BASE"]
        QDRANT["QDRANT VECTOR DB"]
        EMBED["EMBEDDINGS"]
        KB["KNOWLEDGE DOCS"]
    end

    subgraph CONFIG["CONFIGURATION"]
        MAXCALL["MAX TOOLS CALL"]
        LIMIT["LIMIT CHAIN"]
    end

    subgraph MODELS["MODELS"]
        ROUTER["MODEL ROUTER"]
        OR["OPENROUTER"]
        GPT["GPT-4"]
        CLAUDE["CLAUDE"]
        OTHER["OTHERS"]
    end

    subgraph DOCKER["DOCKER SERVICES"]
        BACKEND["BACKEND API"]
        REDIS["REDIS CACHE"]
        POSTGRES["POSTGRESQL"]
        MEM0["MEM0 SERVICE"]
        INNGEST["INNGEST WORKER"]
    end

    subgraph OUTPUT["OUTPUT"]
        RESULT["RESULT"]
        PLAN["TRADING PLAN"]
    end

    USER --> FE --> ORCH
    ORCH --> REASON --> ACT

    ACT --> SSTYLE
    SSTYLE -->|CONVERSATION| CONV --> REASON
    SSTYLE -->|TRADING| TSTYLE
    TSTYLE --> JESSE & DARVAS & OTHERS
    JESSE & DARVAS & OTHERS --> REASON

    ACT --> GWRITE & GEXEC
    GWRITE -->|YES| TVWRITE --> OBS
    GWRITE -->|NO| REASON
    GEXEC -->|YES| MKTORDER --> OBS
    GEXEC -->|NO| REASON

    ACT --> HINT & TF
    HINT & TF --> ATTACH --> PHOTO

    ACT --> ENABLE
    ENABLE -->|YES| WEB & MEM & TVAPI
    ENABLE -->|NO| REASON
    WEB & MEM & TVAPI --> OBS
    PHOTO --> OBS

    ORCH --> HL & OST & CHAIN & DUNE
    HL & OST & CHAIN & DUNE --> OBS

    MEM --> MEM0
    MEM0 --> QDRANT
    QDRANT --> EMBED --> KB
    KB --> ORCH

    OBS --> REASON

    ORCH --> MAXCALL --> LIMIT
    LIMIT --> REASON

    REASON --> ROUTER
    ROUTER --> OR & GPT & CLAUDE & OTHER
    OR & GPT & CLAUDE & OTHER --> RESULT

    BACKEND -.-> ORCH
    REDIS -.-> BACKEND
    POSTGRES -.-> BACKEND
    INNGEST -.-> BACKEND

    RESULT --> PLAN

    classDef main fill:#19010E,stroke:#420024,color:#FFE4FB,stroke-width:1.5px;
    classDef group fill:#19010E,stroke:#420024,color:#FFE4FB,stroke-width:1.5px;
    class USER,FE,ORCH,REASON,ACT,OBS,GWRITE,GEXEC,HINT,TF,ATTACH,PHOTO,TVWRITE,MKTORDER,SSTYLE,CONV,TSTYLE,JESSE,DARVAS,OTHERS,WEB,MEM,TVAPI,ENABLE,HL,OST,CHAIN,DUNE,QDRANT,EMBED,KB,MAXCALL,LIMIT,ROUTER,OR,GPT,CLAUDE,OTHER,BACKEND,REDIS,POSTGRES,MEM0,INNGEST,RESULT,PLAN main;
    class INPUT,REACT,GATES,FTOOLS,STYLES,BTOOLS,CONNECTORS,KNOWLEDGE,CONFIG,MODELS,DOCKER,OUTPUT group;
    linkStyle default stroke:#FFE4FB,stroke-width:1.5px;
```

## Core Features

- Real-time market streaming (Hyperliquid and Ostium)
- Candle history API with fallback sources
- Portfolio, ledger, and leaderboard services
- Arena endpoints and points tracking
- TradingView command bridge/tooling endpoints
- AI chat/agent orchestration and tool execution
- Optional memory/knowledge stack (Qdrant, mem0, Inngest)

## Prerequisites

- Python 3.13+
- Docker Desktop (recommended for full stack)

## Quick Start (Docker, Recommended)

From `backend/websocket`:

```bash
cp .env.example .env
docker compose up -d --build
```

Default service ports:
- API: `8000`
- Postgres: `5432`
- Redis: `6379`
- Qdrant: `6333`
- Mem0 API: `8888`
- Inngest Dev: `8288`
- Upload UI: `8501`
- Langfuse Web (optional profile): `3001`

## Local Run (API Only)

From `backend/websocket`:

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Local Run (Agent Service)

From `backend/agent`:

```bash
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
```

## Important Environment Variables

Main API (`websocket/.env`):
- `SAVE_TO_DB`
- `DATABASE_URL`
- `REDIS_URL`
- `OPENROUTER_API_KEY`
- `AI_BILLING_ONCHAIN_ENABLED`
- `SECONDARY_HISTORY_ENABLED`
- `SESSION_HISTORY_DAYS`
- contract address vars (e.g. `TRADING_VAULT_ADDRESS`, `ORDER_ROUTER_ADDRESS`, etc.)

Use `websocket/.env.example` as baseline and replace all placeholder/secret values.

## Key Endpoints

- `GET /health`
- `GET /docs`
- `GET /api/markets`
- `GET /api/candles/{symbol}`
- `GET /api/leaderboard/*`
- `GET /api/portfolio/*`
- `POST /api/agent/*`
- `POST /api/tools/*`

WebSocket endpoints include:
- `/ws/hyperliquid/{symbol}`
- `/ws/ostium/{symbol}`
- `/ws/orderbook/{symbol}`
- `/ws/trades/{symbol}`

## Testing

Examples:

```bash
# API and service tests
pytest websocket/tests -q

# E2E tests
pytest websocket/tests/e2e -q
```

## Directory Guide

- `websocket/main.py` - primary app entrypoint
- `websocket/routers/` - REST route groups
- `websocket/services/` - business logic (ledger, order, portfolio, leaderboard, chat)
- `websocket/Ostium/`, `websocket/Hyperliquid/` - market adapters/data pipelines
- `agent/src/` - agent API, LLM factory, prompts, tools config
- `agent/Tools/` - runtime tool implementations

## Notes

- For frontend integration, set `VITE_API_URL` to this backend base URL.
- When running in Docker, confirm all dependent services are healthy before testing chat/tools flows.
