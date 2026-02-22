"""
Database configuration and session management.
Uses SQLAlchemy with SQLite for development and supports Postgres for production.

Production features:
- Connection pool configuration
- Automated SQLite backup
- Alembic-first schema upgrades with create_all fallback
"""
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine, inspect, text, event
from sqlalchemy.orm import sessionmaker, Session, declarative_base

from config.paths import default_database_url

logger = logging.getLogger(__name__)

# Database URL configuration
# Default to app-data SQLite location for standalone runtime.
DATABASE_URL = os.getenv("DATABASE_URL", default_database_url())

# Create database engine
# For SQLite, enable check_same_thread=False for FastAPI compatibility
connect_args = {}
pool_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    # SQLite WAL mode for better concurrent read performance
    pool_kwargs["pool_pre_ping"] = True
else:
    # PostgreSQL connection pool tuning
    pool_kwargs.update({
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    })

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    **pool_kwargs,
)

# Enable WAL mode for SQLite on first connect
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_wal_mode(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for declarative models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency function to get database session.

    Yields:
        Database session

    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Initialize or migrate the database schema.
    Prefer Alembic upgrades; fallback to create_all for local recovery.
    """
    migrated = run_alembic_upgrade_head()
    if migrated:
        return
    logger.warning("Falling back to SQLAlchemy create_all because Alembic upgrade was unavailable")
    from storage import models  # noqa: F401  # Import to register models
    Base.metadata.create_all(bind=engine)


def run_alembic_upgrade_head() -> bool:
    """
    Attempt Alembic `upgrade head`.
    Returns True when migrations were applied successfully.
    """
    backend_dir = Path(__file__).resolve().parent.parent
    alembic_ini = backend_dir / "alembic.ini"
    script_location = backend_dir / "alembic"
    if not alembic_ini.exists() or not script_location.exists():
        logger.warning("Alembic assets not found, skipping migration upgrade")
        return False
    try:
        from alembic import command
        from alembic.config import Config
    except Exception:
        logger.exception("Alembic is not available in runtime environment")
        return False

    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    try:
        command.upgrade(config, "head")
        logger.info("Applied Alembic migrations to head")
        return True
    except Exception:
        logger.exception("Alembic migration upgrade failed")
        return False


def check_db_connection() -> bool:
    """
    Verify database connectivity with a lightweight query.
    Returns True if the database is reachable.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def backup_sqlite_database(backup_dir: str | None = None) -> str:
    """
    Create a timestamped backup of the SQLite database file.

    Args:
        backup_dir: Directory to store backups

    Returns:
        Path to the backup file

    Raises:
        RuntimeError: If the database is not SQLite or backup fails
    """
    if not DATABASE_URL.startswith("sqlite"):
        raise RuntimeError("Backup is only supported for SQLite databases")

    # Extract the database file path from the URL
    # Handle sqlite:///./stocksbot.db and sqlite:///stocksbot.db
    db_path_str = DATABASE_URL.replace("sqlite:///", "")
    db_path = Path(db_path_str).resolve()

    if not db_path.exists():
        raise RuntimeError(f"Database file not found: {db_path}")

    if backup_dir is None:
        from config.paths import resolve_app_data_dir
        backup_path = (resolve_app_data_dir() / "backups").resolve()
    else:
        backup_path = Path(backup_dir).resolve()
    backup_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_path / f"stocksbot_{timestamp}.db"

    # Use SQLite's built-in backup via a raw connection to ensure consistency
    try:
        import sqlite3
        source = sqlite3.connect(str(db_path))
        dest = sqlite3.connect(str(backup_file))
        try:
            source.backup(dest)
            logger.info("Database backed up to %s", backup_file)
        finally:
            dest.close()
            source.close()
    except Exception as exc:
        # Fallback to file copy if sqlite3 backup fails
        try:
            shutil.copy2(str(db_path), str(backup_file))
            logger.info("Database copied to %s (fallback)", backup_file)
        except Exception:
            raise RuntimeError(f"Database backup failed: {exc}") from exc

    # Clean up old backups (keep last 5)
    backups = sorted(backup_path.glob("stocksbot_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old_backup in backups[5:]:
        try:
            old_backup.unlink()
            logger.debug("Removed old backup: %s", old_backup)
        except Exception:
            pass

    return str(backup_file)


def check_integrity() -> tuple[bool, str]:
    """
    Run SQLite PRAGMA integrity_check.
    Returns (ok, result_text).
    """
    if not DATABASE_URL.startswith("sqlite"):
        return True, "not sqlite"
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA integrity_check")).scalar()
            ok = str(result).strip().lower() == "ok"
            if ok:
                logger.info("Database integrity check passed")
            else:
                logger.critical("Database integrity check FAILED: %s", result)
            return ok, str(result)
    except Exception as exc:
        logger.critical("Database integrity check error: %s", exc)
        return False, str(exc)


def ensure_optimization_runs_schema() -> None:
    """
    Best-effort schema self-heal for optimization_runs columns.
    This protects existing SQLite DBs that predate recent optimizer features.

    NOTE: This is a temporary measure. All schema changes should go through
    Alembic migrations. This function will be removed once all deployments
    have been migrated.
    """
    inspector = inspect(engine)
    if not inspector.has_table("optimization_runs"):
        return
    existing_columns = {column.get("name") for column in inspector.get_columns("optimization_runs")}
    required_columns = {
        "run_id": "TEXT",
        "strategy_id": "INTEGER",
        "strategy_name": "TEXT NOT NULL DEFAULT ''",
        "source": "TEXT NOT NULL DEFAULT 'sync'",
        "status": "TEXT NOT NULL DEFAULT 'failed'",
        "job_id": "TEXT",
        "request_payload": "JSON",
        "result_payload": "JSON",
        "error": "TEXT",
        "objective": "TEXT",
        "score": "FLOAT",
        "total_return": "FLOAT",
        "sharpe_ratio": "FLOAT",
        "max_drawdown": "FLOAT",
        "total_trades": "INTEGER",
        "win_rate": "FLOAT",
        "recommended_symbol_count": "INTEGER NOT NULL DEFAULT 0",
        "requested_iterations": "INTEGER",
        "evaluated_iterations": "INTEGER",
        "created_at": "DATETIME",
        "started_at": "DATETIME",
        "completed_at": "DATETIME",
        "updated_at": "DATETIME",
    }
    missing = [
        (name, ddl)
        for name, ddl in required_columns.items()
        if name not in existing_columns
    ]
    if not missing:
        return
    logger.warning(
        "Schema self-heal: adding %d missing column(s) to optimization_runs: %s",
        len(missing),
        ", ".join(name for name, _ in missing),
    )
    with engine.begin() as connection:
        for name, ddl in missing:
            connection.execute(text(f"ALTER TABLE optimization_runs ADD COLUMN {name} {ddl}"))
