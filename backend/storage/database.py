"""
Database configuration and session management.
Uses SQLAlchemy with SQLite for development and supports Postgres for production.
"""
import os
from typing import Generator
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session, declarative_base

# Database URL configuration
# Default to SQLite for development
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./stocksbot.db")

# Create database engine
# For SQLite, enable check_same_thread=False for FastAPI compatibility
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true"
)

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
    Initialize database by creating all tables.
    This should be called on application startup.
    
    Note: In production, use Alembic migrations instead.
    """
    from storage import models  # Import to register models
    Base.metadata.create_all(bind=engine)


def ensure_optimization_runs_schema() -> None:
    """
    Best-effort schema self-heal for optimization_runs columns.
    This protects existing SQLite DBs that predate recent optimizer features.
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
    with engine.begin() as connection:
        for name, ddl in missing:
            connection.execute(text(f"ALTER TABLE optimization_runs ADD COLUMN {name} {ddl}"))
