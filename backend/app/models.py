"""SQLAlchemy models for the application."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class UserSession(Base):
    """Model for tracking user sessions and their associated Gemini environments."""

    __tablename__ = "user_sessions"

    session_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    user_id = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    tenant_id = Column(String(100), nullable=False, default="default")
    gemini_environment_id = Column(String(255), nullable=True)
    last_interaction_id = Column(String(255), nullable=True)
    gcs_folder_path = Column(String(512), nullable=False)
    status = Column(String(50), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserSession {self.session_id}>"


class UploadedFile(Base):
    """Model for tracking uploaded files within a session."""

    __tablename__ = "uploaded_files"

    file_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    file_size = Column(String(50), nullable=False)
    gcs_path = Column(String(512), nullable=False)
    mime_type = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<UploadedFile {self.original_filename}>"


class ChatMessage(Base):
    """Model for storing chat history within a session."""

    __tablename__ = "chat_messages"

    message_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    interaction_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ChatMessage {self.message_id} role={self.role}>"
