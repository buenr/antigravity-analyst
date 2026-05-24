"""Gemini Antigravity Agent service for interactions."""

import json
import logging
from typing import AsyncGenerator, Optional

import httpx

from app.config import get_settings
from app.schemas import ProgressEvent

settings = get_settings()
logger = logging.getLogger(__name__)


class GeminiApiError(Exception):
    """Error returned by the Gemini API."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Gemini API error {status_code}: {body}")


def _text_input(prompt: str) -> str:
    return prompt


def _raise_for_status_with_body(response: httpx.Response) -> None:
    """Raise httpx errors while preserving Gemini's error details in logs."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        body = response.text
        logger.error(
            "Gemini API request failed: status=%s body=%s",
            response.status_code,
            body,
        )
        raise GeminiApiError(response.status_code, body) from None


async def _raise_for_stream_status_with_body(response: httpx.Response) -> None:
    """Raise httpx stream errors while preserving Gemini's error details in logs."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        body = (await response.aread()).decode(errors="replace")
        logger.error(
            "Gemini API request failed: status=%s body=%s",
            response.status_code,
            body,
        )
        raise GeminiApiError(response.status_code, body) from None


class GeminiService:
    """Service for interacting with the Gemini Antigravity Agent."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    AGENT_NAME = "antigravity-preview-05-2026"

    def __init__(self):
        """Initialize Gemini service."""
        self.api_key = settings.gemini_api_key
        self.headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
            "Api-Revision": "2026-05-20",
        }

    async def create_interaction(
        self,
        prompt: str,
        gcs_input_path: str,
        gcs_token: Optional[str] = None,
    ) -> tuple[str, str]:
        """Create a new interaction with a fresh sandbox.

        Returns (environment_id, interaction_id).
        """
        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "agent": self.AGENT_NAME,
                "input": _text_input(prompt),
                "environment": {
                    "type": "remote",
                    "sources": [
                        {
                            "type": "gcs",
                            "source": gcs_input_path,
                            "target": "/workspace/data",
                        }
                    ],
                },
            }

            # Add network allowlist if token provided
            if gcs_token:
                payload["environment"]["network"] = {
                    "allowlist": [
                        {
                            "domain": "storage.googleapis.com",
                            "transform": {"Authorization": f"Bearer {gcs_token}"},
                        },
                        {"domain": "*"},
                    ]
                }

            response = await client.post(
                f"{self.BASE_URL}/interactions",
                headers=self.headers,
                json=payload,
            )
            _raise_for_status_with_body(response)
            data = response.json()

            environment_id = data.get("environment_id") or data.get("environment", {}).get("id")
            interaction_id = data.get("interaction_id") or data.get("id")

            return environment_id, interaction_id

    async def create_interaction_streaming(
        self,
        prompt: str,
        gcs_input_path: str,
        gcs_token: Optional[str] = None,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Create a new interaction with SSE streaming.

        Yields ProgressEvent objects for terminal output, status updates, etc.
        """
        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "agent": self.AGENT_NAME,
                "input": _text_input(prompt),
                "environment": {
                    "type": "remote",
                    "sources": [
                        {
                            "type": "gcs",
                            "source": gcs_input_path,
                            "target": "/workspace/data",
                        }
                    ],
                },
            }

            if gcs_token:
                payload["environment"]["network"] = {
                    "allowlist": [
                        {
                            "domain": "storage.googleapis.com",
                            "transform": {"Authorization": f"Bearer {gcs_token}"},
                        },
                        {"domain": "*"},
                    ]
                }

            payload["stream"] = True
            url = f"{self.BASE_URL}/interactions"

            environment_id = None
            interaction_id = None
            output_chunks = []

            async with client.stream(
                "POST",
                url,
                headers=self.headers,
                json=payload,
            ) as response:
                await _raise_for_stream_status_with_body(response)

                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            data = json.loads(data_str)

                            interaction = data.get("interaction", {})

                            # Extract IDs from current Interactions API events.
                            if not environment_id:
                                environment_id = data.get("environment_id") or data.get(
                                    "environment", {}
                                ).get("id") or interaction.get("environment_id")
                            if not interaction_id:
                                interaction_id = (
                                    data.get("interaction_id")
                                    or data.get("id")
                                    or data.get("interaction_id")
                                    or interaction.get("id")
                                )

                            delta = data.get("delta", {})
                            if delta.get("type") == "text" and delta.get("text"):
                                output_chunks.append(delta["text"])
                                yield ProgressEvent(
                                    event_type="content",
                                    message=delta["text"],
                                    data=data,
                                )
                                continue

                            # Parse different event types
                            event_type = data.get("event_type") or data.get("type", "status")
                            message = data.get("message", data.get("text", ""))

                            # Check for terminal output
                            if "terminal" in data:
                                yield ProgressEvent(
                                    event_type="terminal",
                                    message=data["terminal"].get("output", message),
                                    data=data,
                                )
                            elif "code_execution" in data:
                                yield ProgressEvent(
                                    event_type="code_execution",
                                    message=f"Executing code...",
                                    data=data,
                                )
                            elif event_type == "complete" or "output_text" in data:
                                output = data.get("output_text", message)
                                yield ProgressEvent(
                                    event_type="complete",
                                    message=output,
                                    data={
                                        "environment_id": environment_id,
                                        "interaction_id": interaction_id,
                                        **data,
                                    },
                                )
                            elif event_type == "interaction.completed":
                                output = interaction.get("output_text") or "".join(output_chunks)
                                yield ProgressEvent(
                                    event_type="complete",
                                    message=output,
                                    data={
                                        "environment_id": environment_id,
                                        "interaction_id": interaction_id,
                                        **data,
                                    },
                                )
                            elif event_type == "error":
                                error = data.get("error", {})
                                yield ProgressEvent(
                                    event_type="error",
                                    message=error.get("message", message),
                                    data=data,
                                )
                            else:
                                yield ProgressEvent(
                                    event_type=event_type,
                                    message=message,
                                    data=data,
                                )

                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse SSE data: {data_str}")
                            continue

    async def continue_interaction_streaming(
        self,
        prompt: str,
        environment_id: str,
        previous_interaction_id: str,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Continue an existing interaction with SSE streaming.

        Yields ProgressEvent objects.
        """
        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "agent": self.AGENT_NAME,
                "input": _text_input(prompt),
                "environment": environment_id,
                "previous_interaction_id": previous_interaction_id,
                "stream": True,
            }

            url = f"{self.BASE_URL}/interactions"

            new_interaction_id = None
            output_chunks = []

            async with client.stream(
                "POST",
                url,
                headers=self.headers,
                json=payload,
            ) as response:
                await _raise_for_stream_status_with_body(response)

                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            data = json.loads(data_str)

                            interaction = data.get("interaction", {})

                            if not new_interaction_id:
                                new_interaction_id = (
                                    data.get("interaction_id")
                                    or data.get("id")
                                    or interaction.get("id")
                                )

                            delta = data.get("delta", {})
                            if delta.get("type") == "text" and delta.get("text"):
                                output_chunks.append(delta["text"])
                                yield ProgressEvent(
                                    event_type="content",
                                    message=delta["text"],
                                    data=data,
                                )
                                continue

                            event_type = data.get("event_type") or data.get("type", "status")
                            message = data.get("message", data.get("text", ""))

                            if "terminal" in data:
                                yield ProgressEvent(
                                    event_type="terminal",
                                    message=data["terminal"].get("output", message),
                                    data=data,
                                )
                            elif "code_execution" in data:
                                yield ProgressEvent(
                                    event_type="code_execution",
                                    message=f"Executing code...",
                                    data=data,
                                )
                            elif event_type == "complete" or "output_text" in data:
                                output = data.get("output_text", message)
                                yield ProgressEvent(
                                    event_type="complete",
                                    message=output,
                                    data={
                                        "environment_id": environment_id,
                                        "interaction_id": new_interaction_id,
                                        **data,
                                    },
                                )
                            elif event_type == "interaction.completed":
                                output = interaction.get("output_text") or "".join(output_chunks)
                                yield ProgressEvent(
                                    event_type="complete",
                                    message=output,
                                    data={
                                        "environment_id": environment_id,
                                        "interaction_id": new_interaction_id,
                                        **data,
                                    },
                                )
                            elif event_type == "error":
                                error = data.get("error", {})
                                yield ProgressEvent(
                                    event_type="error",
                                    message=error.get("message", message),
                                    data=data,
                                )
                            else:
                                yield ProgressEvent(
                                    event_type=event_type,
                                    message=message,
                                    data=data,
                                )

                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse SSE data: {data_str}")
                            continue

    async def download_workspace_snapshot(
        self, environment_id: str
    ) -> bytes:
        """Download the workspace snapshot as a tar file."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            url = f"{self.BASE_URL}/files/environment-{environment_id}:download?alt=media"
            response = await client.get(url, headers=self.headers, follow_redirects=True)
            _raise_for_status_with_body(response)
            return response.content


# Singleton instance
_gemini_service: Optional[GeminiService] = None


def get_gemini_service() -> GeminiService:
    """Get or create Gemini service instance."""
    global _gemini_service
    if _gemini_service is None:
        _gemini_service = GeminiService()
    return _gemini_service
