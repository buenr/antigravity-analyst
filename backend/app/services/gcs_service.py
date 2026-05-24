"""Google Cloud Storage service for file operations."""

import os
import uuid
from datetime import timedelta
from typing import Optional

from google.auth import default
from google.auth.transport.requests import Request
from google.cloud import storage
from google.cloud.storage import Blob

from app.config import get_settings

settings = get_settings()


class GCSService:
    """Service for interacting with Google Cloud Storage."""

    def __init__(self):
        """Initialize GCS client."""
        self.project_id = settings.gcp_project_id
        self.bucket_name = settings.gcs_bucket_name

        # Use service account credentials if provided, otherwise use ADC
        if settings.google_application_credentials:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = (
                settings.google_application_credentials
            )

        self.client = storage.Client(project=self.project_id)
        self.bucket = self.client.bucket(self.bucket_name)
        self.credentials = self.client._credentials

    def _get_session_path(self, tenant_id: str, user_id: str, session_id: str) -> str:
        """Generate the GCS path for a session."""
        return f"tenants/{tenant_id}/users/{user_id}/sessions/{session_id}"

    def create_session_folder(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> str:
        """Create a session folder structure in GCS.

        Returns the base path for the session.
        """
        base_path = self._get_session_path(tenant_id, user_id, session_id)
        # Create a placeholder to ensure folder exists
        placeholder = self.bucket.blob(f"{base_path}/input/.keep")
        placeholder.upload_from_string(b"")
        return base_path

    def upload_file(
        self,
        file_content: bytes,
        original_filename: str,
        tenant_id: str,
        user_id: str,
        session_id: str,
        content_type: Optional[str] = None,
    ) -> tuple[str, str]:
        """Upload a file to GCS.

        Returns (gcs_path, stored_filename).
        """
        base_path = self._get_session_path(tenant_id, user_id, session_id)

        # Generate unique filename
        file_extension = os.path.splitext(original_filename)[1]
        stored_filename = f"{uuid.uuid4()}{file_extension}"

        # Full GCS path
        gcs_path = f"{base_path}/input/{stored_filename}"

        blob = self.bucket.blob(gcs_path)
        blob.upload_from_string(file_content, content_type=content_type)

        return gcs_path, stored_filename

    def upload_to_path(
        self,
        file_content: bytes,
        gcs_path: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Upload a file to a specific GCS object path."""
        blob = self.bucket.blob(gcs_path)
        blob.upload_from_string(file_content, content_type=content_type)
        return gcs_path

    def get_input_folder_path(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> str:
        """Get the GCS input folder path for mounting to sandbox."""
        base_path = self._get_session_path(tenant_id, user_id, session_id)
        return f"gs://{self.bucket_name}/{base_path}/input"

    def get_access_token(self) -> str:
        """Get an OAuth access token for private GCS source mounts."""
        if not self.credentials.valid:
            self.credentials.refresh(Request())
        return self.credentials.token

    def download_file(self, gcs_path: str) -> bytes:
        """Download a file from GCS."""
        blob = self.bucket.blob(gcs_path)
        return blob.download_as_bytes()

    def delete_file(self, gcs_path: str):
        """Delete a file from GCS."""
        blob = self.bucket.blob(gcs_path)
        blob.delete()

    def list_files(self, gcs_folder: str) -> list[dict]:
        """List files in a GCS folder."""
        blobs = self.client.list_blobs(self.bucket, prefix=gcs_folder)

        files = []
        for blob in blobs:
            if not blob.name.endswith("/"):
                files.append(
                    {
                        "name": os.path.basename(blob.name),
                        "path": blob.name,
                        "size": blob.size,
                        "updated": blob.updated.isoformat() if blob.updated else None,
                    }
                )
        return files

    def generate_signed_url(
        self, gcs_path: str, expiration_minutes: int = 60
    ) -> str:
        """Generate a signed URL for downloading a file."""
        blob = self.bucket.blob(gcs_path)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
        )

    def delete_session_files(self, tenant_id: str, user_id: str, session_id: str):
        """Delete all files for a session."""
        base_path = self._get_session_path(tenant_id, user_id, session_id)
        blobs = self.client.list_blobs(self.bucket, prefix=base_path)

        for blob in blobs:
            blob.delete()


# Singleton instance
_gcs_service: Optional[GCSService] = None


def get_gcs_service() -> GCSService:
    """Get or create GCS service instance."""
    global _gcs_service
    if _gcs_service is None:
        _gcs_service = GCSService()
    return _gcs_service
