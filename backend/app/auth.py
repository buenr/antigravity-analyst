"""Session ownership helpers."""

import secrets
import uuid
from typing import Optional

from fastapi import Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models import UserSession


def generate_session_token() -> str:
    """Generate an unguessable capability token for a user session."""
    return secrets.token_urlsafe(32)


def session_token_dependency(
    x_session_token: Optional[str] = Header(default=None, alias="X-Session-Token"),
    session_token: Optional[str] = Query(default=None),
) -> str:
    """Read a session token from header or query string."""
    token = x_session_token or session_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing session token",
        )
    return token


def get_owned_session(
    db: Session,
    session_id: uuid.UUID,
    session_token: str,
) -> UserSession:
    """Return a session only when the caller presents its access token."""
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    if not session.access_token or not secrets.compare_digest(
        session.access_token,
        session_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid session token",
        )

    return session
