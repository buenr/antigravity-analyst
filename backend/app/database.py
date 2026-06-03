"""Database configuration for SQLite."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

# SQLite database URL
DATABASE_URL = f"sqlite:///./{settings.app_name.lower().replace(' ', '_')}.db"

# Create engine with check_same_thread=False for SQLite
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=settings.debug,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _run_migrations():
    """Run lightweight SQLite migrations for schema changes."""
    with engine.connect() as conn:
        # Get existing columns in user_sessions
        result = conn.execute(text("PRAGMA table_info(user_sessions)"))
        existing_columns = {row[1] for row in result}

        # Add missing environment_created_at column
        if "environment_created_at" not in existing_columns:
            conn.execute(text(
                "ALTER TABLE user_sessions ADD COLUMN environment_created_at DATETIME"
            ))
            conn.commit()
            print("Migration: added environment_created_at to user_sessions")

        # Add missing environment_needs_refresh column
        if "environment_needs_refresh" not in existing_columns:
            conn.execute(text(
                "ALTER TABLE user_sessions ADD COLUMN environment_needs_refresh BOOLEAN DEFAULT 0"
            ))
            conn.commit()
            print("Migration: added environment_needs_refresh to user_sessions")

        # Add missing access_token column for session ownership checks
        if "access_token" not in existing_columns:
            conn.execute(text(
                "ALTER TABLE user_sessions ADD COLUMN access_token VARCHAR(255)"
            ))
            conn.commit()
            print("Migration: added access_token to user_sessions")


def init_db():
    """Initialize database tables and run migrations."""
    Base.metadata.create_all(bind=engine)
    _run_migrations()
