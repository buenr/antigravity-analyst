"""Pydantic schemas for request/response validation."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# Inline image limits (base64 expands raw bytes ~33%, so 7 MB b64 ≈ 5 MB raw).
_MAX_IMAGE_B64_BYTES = 7 * 1024 * 1024
_MAX_IMAGES_PER_REQUEST = 4
_ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}


# Session Schemas
class SessionCreate(BaseModel):
    """Request to create a new session."""

    tenant_id: str = Field(default="default", description="Tenant identifier")


class SessionResponse(BaseModel):
    """Response for session creation/retrieval."""

    session_id: uuid.UUID
    user_id: uuid.UUID
    session_token: Optional[str] = None
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
class ImageInput(BaseModel):
    """Inline base64 image input for multimodal prompts."""

    data: str = Field(..., description="Base64-encoded image bytes (no data: prefix)")
    mime_type: str = Field(..., description="Image MIME type, e.g. image/png")

    @field_validator("mime_type")
    @classmethod
    def _validate_mime(cls, v: str) -> str:
        if v not in _ALLOWED_IMAGE_MIME:
            raise ValueError(
                f"Unsupported image MIME type {v!r}. Allowed: {sorted(_ALLOWED_IMAGE_MIME)}"
            )
        return v

    @field_validator("data")
    @classmethod
    def _validate_size(cls, v: str) -> str:
        if len(v) > _MAX_IMAGE_B64_BYTES:
            raise ValueError(
                f"Inline image exceeds limit ({len(v)} > {_MAX_IMAGE_B64_BYTES} base64 bytes)"
            )
        return v


class UsageInfo(BaseModel):
    """Per-turn token usage reported by Gemini's interaction.completed event."""

    total_tokens: Optional[int] = None
    total_input_tokens: Optional[int] = None
    total_output_tokens: Optional[int] = None
    total_cached_tokens: Optional[int] = None
    total_thought_tokens: Optional[int] = None
    total_tool_use_tokens: Optional[int] = None


class ChatRequest(BaseModel):
    """Request to send a chat message."""

    message: str = Field(..., min_length=1, max_length=10000)
    stream: bool = Field(default=True, description="Enable SSE streaming")
    images: List[ImageInput] = Field(
        default_factory=list,
        max_length=_MAX_IMAGES_PER_REQUEST,
        description="Optional inline base64 images to include with the prompt",
    )


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
    usage: Optional[UsageInfo] = Field(
        default=None,
        description="Token usage reported for this turn",
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
