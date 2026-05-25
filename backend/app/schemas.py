"""Pydantic schemas for request/response validation."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# Session Schemas
class SessionCreate(BaseModel):
    """Request to create a new session."""

    tenant_id: str = Field(default="default", description="Tenant identifier")


class SessionResponse(BaseModel):
    """Response for session creation/retrieval."""

    session_id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# File Schemas
class FileUploadResponse(BaseModel):
    """Response after successful file upload."""

    file_id: uuid.UUID
    original_filename: str
    file_size: str
    gcs_path: str
    created_at: datetime

    class Config:
        from_attributes = True


class FileInfo(BaseModel):
    """Information about an uploaded file."""

    file_id: uuid.UUID
    original_filename: str
    file_size: str
    created_at: datetime

    class Config:
        from_attributes = True


class FileListResponse(BaseModel):
    """Response listing all files in a session."""

    session_id: uuid.UUID
    files: List[FileInfo]


# Download Schemas
class DownloadResponse(BaseModel):
    """Response with download information."""

    file_name: str
    download_url: str
    file_type: str
    size_bytes: int


class ReportListResponse(BaseModel):
    """Response listing available reports for download."""

    session_id: uuid.UUID
    reports: List[DownloadResponse]


# Chat Schemas
class ChatRequest(BaseModel):
    """Request to send a chat message."""

    message: str = Field(..., min_length=1, max_length=10000)
    stream: bool = Field(default=True, description="Enable SSE streaming")


class ChatMessageResponse(BaseModel):
    """Response for a chat message."""

    message_id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    attachments: List[DownloadResponse] = Field(
        default_factory=list,
        description="Downloadable deliverables produced for this turn",
    )

    class Config:
        from_attributes = True


# Progress/Streaming Schemas
class ProgressEvent(BaseModel):
    """SSE event for streaming progress updates.

    On ``complete``, ``data`` may include ``interaction_id``, ``reports`` (list of
    DownloadResponse dicts), and ``harvested_count``.
    """

    event_type: str  # 'status', 'terminal', 'error', 'complete'
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: Optional[dict] = None


# Error Schemas
class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
