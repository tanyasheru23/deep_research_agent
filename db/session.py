from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from db.models import Base

DATABASE_URL = "sqlite+aiosqlite:///./deep_research.db"

engine  = create_async_engine(DATABASE_URL, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)

# ── DB setup (called in lifespan) ─────────────────────────────────────────
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── FastAPI dependency ────────────────────────────────────────────────────
async def get_session():
    async with Session() as session:
        yield session