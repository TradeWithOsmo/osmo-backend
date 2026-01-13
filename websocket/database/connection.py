from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import text
from config import settings

# Construct Async Database URL
# Example: postgresql+asyncpg://user:pass@host:port/dbname
DB_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Create Async Engine
engine = create_async_engine(
    DB_URL,
    echo=False,
    pool_size=20,
    max_overflow=10
)

# Create Async Session Factory
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

Base = declarative_base()

async def get_db():
    """Dependency for getting async database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    """Initialize database tables"""
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all) # WARNING: Dev only
        await conn.run_sync(Base.metadata.create_all)
        
        # Enable TimescaleDB extension if not exists
        # await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
        
        # Convert candles table to hypertable (ignore if already exists)
        # try:
        #     await conn.execute(text("SELECT create_hypertable('candles', 'timestamp', if_not_exists => TRUE);"))
        # except Exception as e:
        #     # Ignore error if it's about table already being a hypertable (though if_not_exists handles most cases)
        #     print(f"Hypertable creation note: {e}")
