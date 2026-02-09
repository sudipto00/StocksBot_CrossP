"""
Database configuration and session management.
Uses SQLAlchemy with SQLite for development and supports Postgres for production.
"""
import os
from typing import Generator
from sqlalchemy import create_engine
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
