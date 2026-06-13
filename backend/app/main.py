"""Main FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models import ChatMessage, UploadedFile, UserSession
from app.routers import chat, files, sessions
from app.services.gcs_service import get_gcs_service

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if get_settings().debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None


async def cleanup_expired_sessions():
    """Clean up expired sessions and their resources."""
    settings = get_settings()
    db = SessionLocal()
    gcs_service = None

    try:
        # Find expired sessions using dialect-agnostic datetime comparison.
        timeout_delta = timedelta(minutes=settings.session_timeout_minutes)
        cutoff_time = datetime.utcnow() - timeout_delta

        expired_sessions = db.query(
            UserSession.session_id,
            UserSession.tenant_id,
            UserSession.user_id,
            UserSession.gcs_folder_path
        ).filter(
            UserSession.updated_at < cutoff_time,
            UserSession.status == 'active'
        ).all()

        if not expired_sessions:
            return

        gcs_service = get_gcs_service()
        cleaned_count = 0

        for row in expired_sessions:
            session_id = row.session_id
            tenant_id = row.tenant_id
            user_id = row.user_id
            gcs_folder_path = row.gcs_folder_path

            try:
                # Delete GCS files
                gcs_service.delete_session_files(
                    tenant_id=tenant_id,
                    user_id=str(user_id),
                    session_id=str(session_id),
                )

                # Delete related database records
                # Convert UUID to string for SQLite compatibility
                session_id_str = str(session_id)
                db.execute(
                    text("DELETE FROM chat_messages WHERE session_id = :sid"),
                    {"sid": session_id_str},
                )
                db.execute(
                    text("DELETE FROM uploaded_files WHERE session_id = :sid"),
                    {"sid": session_id_str},
                )
                db.execute(
                    text("DELETE FROM user_sessions WHERE session_id = :sid"),
                    {"sid": session_id_str},
                )

                db.commit()
                cleaned_count += 1
                logger.info(f"Cleaned up expired session: {session_id}")

            except Exception as e:
                db.rollback()
                logger.error(f"Error cleaning up session {session_id}: {e}")

        if cleaned_count > 0:
            logger.info(f"Session cleanup completed. Cleaned {cleaned_count} expired sessions.")

    except Exception as e:
        logger.error(f"Error during session cleanup: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    global scheduler

    # Startup
    logger.info("Starting up Antigravity Data Analyst API...")
    init_db()
    logger.info("Database initialized")

    # Start background scheduler for session cleanup
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        cleanup_expired_sessions,
        trigger=IntervalTrigger(minutes=5),
        id="session_cleanup",
        name="Clean up expired sessions",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Session cleanup scheduler started (runs every 5 minutes)")

    yield

    # Shutdown
    logger.info("Shutting down Antigravity Data Analyst API...")
    if scheduler:
        scheduler.shutdown()
        logger.info("Scheduler shut down")


# Create FastAPI app
app = FastAPI(
    title=get_settings().app_name,
    description="AI-powered data analysis agent using Gemini Antigravity",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(sessions.router)
app.include_router(files.router)
app.include_router(chat.router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": get_settings().app_name,
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
