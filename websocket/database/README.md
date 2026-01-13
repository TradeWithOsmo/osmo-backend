# Database Module

This module handles all database operations including:
- SQLAlchemy models (tables: trades, candles, user_sessions, notifications)
- Connection pooling and session management
- Query builders and CRUD operations
- Data persistence logic

## Status
**Phase 1**: Module structure only (no implementation yet)
**Phase 4**: Full implementation with PostgreSQL/TimescaleDB

## Future Structure
```
database/
├── __init__.py          # This file
├── models.py            # SQLAlchemy table definitions
├── connection.py        # Database session management
├── queries.py           # Common queries
└── migrations/          # Alembic migration scripts
```
