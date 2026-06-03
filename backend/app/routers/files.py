"""File upload and management router."""

import os
import uuid
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import get_owned_session, session_token_dependency
from app.config import get_settings
from app.database import get_db
from app.models import UploadedFile, UserSession
from app.schemas import (
    ErrorResponse,
    FileUploadResponse,
    FileInfo,
    FileListResponse,
)
from app.services.gcs_service import get_gcs_service

router = APIRouter(prefix="/files", tags=["files"])
settings = get_settings()


def validate_file_extension(filename: str) -> bool:
    """Check if file extension is allowed."""
    ext = os.path.splitext(filename)[1].lower()
    return ext in settings.allowed_extensions_list


@router.post(
    "/upload/{session_id}",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
    },
)
async def upload_file(
    session_id: uuid.UUID,
    file: UploadFile = File(...),
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
    gcs_service=Depends(get_gcs_service),
):
    """Upload a CSV or Excel file to a session."""
    session = get_owned_session(db, session_id, session_token)

    # Validate file extension
    if not validate_file_extension(file.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed types: {settings.allowed_extensions}",
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Check file size
    if file_size > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size ({file_size / 1024 / 1024:.2f} MB) exceeds limit ({settings.max_file_size_mb} MB)",
        )

    # Upload to GCS
    gcs_path, stored_filename = gcs_service.upload_file(
        file_content=content,
        original_filename=file.filename,
        tenant_id=session.tenant_id,
        user_id=str(session.user_id),
        session_id=str(session.session_id),
        content_type=file.content_type,
    )

    # Save file record
    uploaded_file = UploadedFile(
        file_id=uuid.uuid4(),
        session_id=session.session_id,
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_size=f"{file_size / 1024:.2f} KB",
        gcs_path=gcs_path,
        mime_type=file.content_type,
    )

    db.add(uploaded_file)

    # Mark session for environment refresh if already initialized
    if session.gemini_environment_id:
        session.environment_needs_refresh = True

    db.commit()
    db.refresh(uploaded_file)

    return FileUploadResponse(
        file_id=uploaded_file.file_id,
        original_filename=uploaded_file.original_filename,
        file_size=uploaded_file.file_size,
        gcs_path=uploaded_file.gcs_path,
        created_at=uploaded_file.created_at,
    )


@router.get(
    "/{session_id}",
    response_model=FileListResponse,
    responses={
        404: {"model": ErrorResponse},
    },
)
def list_files(
    session_id: uuid.UUID,
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
):
    """List all files uploaded to a session."""
    get_owned_session(db, session_id, session_token)

    files = db.query(UploadedFile).filter(
        UploadedFile.session_id == session_id
    ).all()

    return FileListResponse(
        session_id=session_id,
        files=[
            FileInfo(
                file_id=f.file_id,
                original_filename=f.original_filename,
                file_size=f.file_size,
                created_at=f.created_at,
            )
            for f in files
        ],
    )


@router.get(
    "/download/{file_id}",
    responses={
        404: {"model": ErrorResponse},
    },
)
async def download_file(
    file_id: uuid.UUID,
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
    gcs_service=Depends(get_gcs_service),
):
    """Download a file by its ID."""
    uploaded_file = db.query(UploadedFile).filter(
        UploadedFile.file_id == file_id
    ).first()

    if not uploaded_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File {file_id} not found",
        )

    get_owned_session(db, uploaded_file.session_id, session_token)

    # Download from GCS
    content = gcs_service.download_file(uploaded_file.gcs_path)

    # Stream response
    return StreamingResponse(
        BytesIO(content),
        media_type=uploaded_file.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{uploaded_file.original_filename}"'
        },
    )


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse},
    },
)
def delete_file(
    file_id: uuid.UUID,
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
    gcs_service=Depends(get_gcs_service),
):
    """Delete a specific file."""
    uploaded_file = db.query(UploadedFile).filter(
        UploadedFile.file_id == file_id
    ).first()

    if not uploaded_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File {file_id} not found",
        )

    get_owned_session(db, uploaded_file.session_id, session_token)

    # Delete from GCS
    gcs_service.delete_file(uploaded_file.gcs_path)

    # Delete from database
    db.delete(uploaded_file)
    db.commit()

    return None
