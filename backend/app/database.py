"""SQLAlchemy async engine and session management with SQLite."""

from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

# Ensure database parent directory exists
db_path = Path(settings.db_path)
db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """Dependency that provides an async database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _ensure_columns(conn, table: str, columns: list[tuple[str, str]]):
    """Idempotently add missing columns to an existing SQLite table.

    Introspects ``PRAGMA table_info`` and runs ``ALTER TABLE ADD COLUMN``
    for any column not yet present. Safe to re-run (no-op when all columns
    exist). Swallows "duplicate column" errors for extra safety.
    """
    result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    existing_cols = {row[1] for row in result.fetchall()}
    for col_name, col_type in columns:
        if col_name not in existing_cols:
            try:
                await conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"
                )
            except Exception:
                # Column may have been added concurrently; safe to ignore.
                pass


async def init_db():
    """Create all tables and enable WAL mode."""
    # Import all models to ensure they are registered with Base.metadata
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        # Enable WAL mode for better concurrent read/write
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
        # Idempotent column migration: create_all only creates missing tables,
        # not missing columns on existing tables. This adds new columns to
        # pre-existing dev DBs. No-op on fresh DBs (columns already present).
        await _ensure_columns(
            conn,
            "positions",
            [
                ("estimated_change_pct", "FLOAT"),
                ("estimated_nav", "FLOAT"),
                ("estimated_at", "DATETIME"),
            ],
        )
