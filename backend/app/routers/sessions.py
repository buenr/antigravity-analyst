"""Session management router."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import generate_session_token, get_owned_session, session_token_dependency
from app.database import get_db
from app.models import ChatMessage, UploadedFile, UserSession
from app.schemas import (
    ErrorResponse,
    SessionCreate,
    SessionResponse,
)
from app.services.gcs_service import get_gcs_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post(
    "/",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        500: {"model": ErrorResponse},
    },
)
def create_session(
    request: SessionCreate = SessionCreate(),
    db: Session = Depends(get_db),
    gcs_service=Depends(get_gcs_service),
):
    """Create a new session with isolated workspace."""
    # Generate IDs
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    access_token = generate_session_token()

    # Create session folder in GCS
    gcs_folder_path = gcs_service.create_session_folder(
        tenant_id=request.tenant_id,
        user_id=str(user_id),
        session_id=str(session_id),
    )

    # Create session record
    session = UserSession(
        session_id=session_id,
        user_id=user_id,
        tenant_id=request.tenant_id,
        access_token=access_token,
        gcs_folder_path=gcs_folder_path,
        status="active",
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    return SessionResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        session_token=session.access_token,
        tenant_id=session.tenant_id,
        status=session.status,
        created_at=session.created_at,
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    responses={
        404: {"model": ErrorResponse},
    },
)
def get_session(
    session_id: uuid.UUID,
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
):
    """Get session details."""
    session = get_owned_session(db, session_id, session_token)

    return SessionResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        tenant_id=session.tenant_id,
        status=session.status,
        created_at=session.created_at,
    )


@router.get(
    "/",
    response_model=List[SessionResponse],
)
def list_sessions(
    tenant_id: str = None,
    limit: int = 50,
    offset: int = 0,
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
):
    """List sessions accessible to the supplied session token."""
    query = db.query(UserSession).filter(UserSession.access_token == session_token)

    if tenant_id:
        query = query.filter(UserSession.tenant_id == tenant_id)

    sessions = query.offset(offset).limit(limit).all()

    return [
        SessionResponse(
            session_id=s.session_id,
            user_id=s.user_id,
            tenant_id=s.tenant_id,
            status=s.status,
            created_at=s.created_at,
        )
        for s in sessions
    ]


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse},
    },
)
def delete_session(
    session_id: uuid.UUID,
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
    gcs_service=Depends(get_gcs_service),
):
    """Delete a session and all associated files."""
    session = get_owned_session(db, session_id, session_token)

    # Delete GCS files
    gcs_service.delete_session_files(
        tenant_id=session.tenant_id,
        user_id=str(session.user_id),
        session_id=str(session.session_id),
    )

    # Delete from database
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete(
        synchronize_session=False
    )
    db.query(UploadedFile).filter(UploadedFile.session_id == session_id).delete(
        synchronize_session=False
    )
    db.delete(session)
    db.commit()

    return None
