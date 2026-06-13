"""Gemini Antigravity Agent service for interactions."""

import json
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional

import httpx

from app.config import get_settings
from app.schemas import ProgressEvent

settings = get_settings()
logger = logging.getLogger(__name__)


# Step types that surface as user-visible terminal/tool activity.
_TOOL_CALL_STEP_TYPES = {
    "code_execution_call",
    "google_search_call",
    "url_context_call",
    "function_call",
}
_TOOL_RESULT_STEP_TYPES = {
    "code_execution_result",
    "google_search_result",
    "url_context_result",
    "function_result",
}


class GeminiApiError(Exception):
    """Error returned by the Gemini API."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Gemini API error {status_code}: {body}")


def _build_input(prompt: str, images: Optional[list[dict]] = None):
    """Build the Gemini Interactions API ``input`` payload.

    Returns a plain string for text-only prompts and a list of typed content
    parts when one or more inline images are attached.
    """
    if not images:
        return prompt

    parts: list[dict] = [{"type": "text", "text": prompt}]
    for img in images:
        data = img.get("data")
        mime_type = img.get("mime_type") or "image/png"
        if not data:
            continue
        parts.append({"type": "image", "data": data, "mime_type": mime_type})
    return parts


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _agent_config_path() -> Path:
    configured_path = Path(settings.agent_config_dir)
    if configured_path.is_absolute():
        return configured_path
    return _repo_root() / configured_path


_AGENT_CONFIG_SUFFIXES = (".md", ".txt", ".sh")


def _load_agent_sources() -> list[dict[str, str]]:
    """Load versioned Antigravity instructions, skills, and sandbox bootstrap files."""
    config_dir = _agent_config_path()
    if not config_dir.exists():
        logger.warning("Agent config directory not found: %s", config_dir)
        return []

    sources = []
    for path in sorted(config_dir.rglob("*")):
        if not path.is_file() or path.suffix not in _AGENT_CONFIG_SUFFIXES:
            continue

        target = Path(".agents") / path.relative_to(config_dir)
        sources.append(
            {
                "type": "inline",
                "target": target.as_posix(),
                "content": path.read_text(encoding="utf-8"),
            }
        )
    return sources


def _build_environment(gcs_input_path: str, gcs_token: Optional[str] = None) -> dict:
    environment = {
        "type": "remote",
        "sources": [
            *_load_agent_sources(),
            {
                "type": "gcs",
                "source": gcs_input_path,
                "target": "/workspace/data",
            },
        ],
    }

    if gcs_token:
        environment["network"] = {
            "allowlist": [
                {
                    "domain": "storage.googleapis.com",
                    "transform": {"Authorization": f"Bearer {gcs_token}"},
                },
                {"domain": "*"},
            ]
        }

    return environment


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


def _extract_tool_summary(step: dict) -> str:
    """Best-effort short label for a tool-call step.start payload."""
    step_type = step.get("type", "tool")
    name = step.get("name")
    if step_type == "code_execution_call":
        return "Executing code..."
    if step_type == "google_search_call":
        return "Searching the web..."
    if step_type == "url_context_call":
        return "Fetching URL..."
    if step_type == "function_call" and name:
        return f"Calling tool: {name}"
    return f"Running {step_type}"


def _extract_tool_result_output(step: dict, delta: dict) -> str:
    """Best-effort summary of tool result output (stdout/stderr or error flag)."""
    output = delta.get("output") or delta.get("text") or delta.get("result")
    if isinstance(output, dict):
        return output.get("text") or json.dumps(output)[:500]
    if isinstance(output, str):
        return output
    if delta.get("is_error") or step.get("is_error"):
        return "[tool reported error]"
    return ""


async def _iter_sse_events(response: httpx.Response):
    """Yield decoded ProgressEvent objects from the documented Interactions SSE stream.

    Handles the step-based schema:
      interaction.created -> step.start -> step.delta(*) -> step.stop -> interaction.completed
    """
    step_types: dict[int, str] = {}
    step_meta: dict[int, dict] = {}
    output_chunks: list[str] = []
    environment_id: Optional[str] = None
    interaction_id: Optional[str] = None

    async for line in response.aiter_lines():
        if not line:
            continue
        if line.startswith(":") or line.startswith("event:"):
            # Comment lines and the `event:` name header (event_type is also in the data JSON).
            continue
        if not line.startswith("data: "):
            continue

        data_str = line[6:].strip()
        if data_str == "[DONE]":
            break

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            logger.debug("Skipping non-JSON SSE payload: %s", data_str[:120])
            continue

        event_type = data.get("event_type") or data.get("type") or "status"
        interaction = data.get("interaction") or {}

        if not environment_id:
            environment_id = (
                data.get("environment_id")
                or data.get("environment", {}).get("id")
                or interaction.get("environment_id")
            )
        if not interaction_id:
            interaction_id = (
                data.get("interaction_id")
                or data.get("id")
                or interaction.get("id")
            )

        # Documented event flow ----------------------------------------------------
        if event_type == "interaction.created":
            yield ProgressEvent(
                event_type="created",
                message="Interaction created",
                data={**data, "environment_id": environment_id, "interaction_id": interaction_id},
            )
            continue

        if event_type == "interaction.status_update":
            yield ProgressEvent(
                event_type="status",
                message=data.get("status", ""),
                data=data,
            )
            continue

        if event_type == "step.start":
            index = data.get("index", -1)
            step = data.get("step") or {}
            step_type = step.get("type", "")
            step_types[index] = step_type
            step_meta[index] = step

            if step_type in _TOOL_CALL_STEP_TYPES:
                yield ProgressEvent(
                    event_type="code_execution" if step_type == "code_execution_call" else "tool_call",
                    message=_extract_tool_summary(step),
                    data=data,
                )
            elif step_type in _TOOL_RESULT_STEP_TYPES:
                yield ProgressEvent(
                    event_type="tool_result",
                    message=f"{step_type} received",
                    data=data,
                )
            # model_output and thought step.start events are silent; deltas carry content.
            continue

        if event_type == "step.delta":
            index = data.get("index", -1)
            delta = data.get("delta") or {}
            delta_type = delta.get("type", "")
            step_type = step_types.get(index, "")

            if delta_type == "text":
                text = delta.get("text", "")
                if text and step_type in ("model_output", ""):
                    output_chunks.append(text)
                    yield ProgressEvent(event_type="content", message=text, data=data)
                continue

            if delta_type == "thought_summary":
                content = delta.get("content") or {}
                summary_text = content.get("text") if isinstance(content, dict) else ""
                if summary_text:
                    yield ProgressEvent(
                        event_type="thought",
                        message=summary_text,
                        data=data,
                    )
                continue

            if delta_type == "code_execution_call" or step_type == "code_execution_call":
                code = delta.get("code") or delta.get("source") or _extract_tool_summary(
                    step_meta.get(index, {})
                )
                yield ProgressEvent(event_type="code_execution", message=code, data=data)
                continue

            if delta_type == "code_execution_result" or step_type == "code_execution_result":
                output = _extract_tool_result_output(step_meta.get(index, {}), delta)
                yield ProgressEvent(
                    event_type="terminal",
                    message=output or "[no output]",
                    data=data,
                )
                continue

            if delta_type == "google_search_call" or step_type == "google_search_call":
                args = delta.get("arguments") or {}
                queries = args.get("queries") if isinstance(args, dict) else None
                yield ProgressEvent(
                    event_type="tool_call",
                    message=f"google_search: {queries}" if queries else "google_search",
                    data=data,
                )
                continue

            if delta_type == "arguments_delta":
                yield ProgressEvent(
                    event_type="tool_call",
                    message=delta.get("arguments", ""),
                    data=data,
                )
                continue

            # Unknown delta type — log and surface as a generic status event.
            logger.debug("Unhandled step.delta type=%s step_type=%s", delta_type, step_type)
            yield ProgressEvent(event_type="status", message=delta_type or "delta", data=data)
            continue

        if event_type == "step.stop":
            continue

        if event_type == "interaction.completed":
            final_text = (
                interaction.get("output_text")
                or data.get("output_text")
                or "".join(output_chunks)
            )
            usage = interaction.get("usage") or data.get("usage")
            yield ProgressEvent(
                event_type="complete",
                message=final_text,
                data={
                    **data,
                    "environment_id": environment_id,
                    "interaction_id": interaction_id,
                    "usage": usage,
                },
            )
            continue

        if event_type == "error":
            error = data.get("error") or {}
            yield ProgressEvent(
                event_type="error",
                message=error.get("message", data.get("message", "Unknown error")),
                data=data,
            )
            continue

        # Unknown top-level event — log and skip per docs guidance.
        logger.debug("Unhandled SSE event_type=%s", event_type)
        yield ProgressEvent(event_type=event_type, message=data.get("message", ""), data=data)


class GeminiService:
    """Service for interacting with the Gemini Antigravity Agent."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

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
        images: Optional[list[dict]] = None,
        agent_name: Optional[str] = None,
    ) -> tuple[str, str]:
        """Create a new interaction with a fresh sandbox.

        Returns (environment_id, interaction_id).
        """
        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "agent": agent_name or settings.gemini_agent_name,
                "input": _build_input(prompt, images),
                "system_instruction": settings.gemini_system_instruction,
                "environment": _build_environment(gcs_input_path, gcs_token),
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
        environment_id: Optional[str] = None,
        images: Optional[list[dict]] = None,
        agent_name: Optional[str] = None,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Create a new interaction with SSE streaming.

        If ``environment_id`` is provided, the new interaction reuses that sandbox
        (preserving installed packages and tier markers); otherwise a fresh sandbox
        is provisioned with the configured GCS data source mounted.

        Yields ProgressEvent objects parsed from the documented step-based SSE schema.
        """
        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "agent": agent_name or settings.gemini_agent_name,
                "input": _build_input(prompt, images),
                "system_instruction": settings.gemini_system_instruction,
                "environment": (
                    environment_id
                    if environment_id
                    else _build_environment(gcs_input_path, gcs_token)
                ),
                "stream": True,
            }

            url = f"{self.BASE_URL}/interactions"

            async with client.stream(
                "POST",
                url,
                headers=self.headers,
                json=payload,
            ) as response:
                await _raise_for_stream_status_with_body(response)
                async for event in _iter_sse_events(response):
                    yield event

    async def continue_interaction_streaming(
        self,
        prompt: str,
        environment_id: str,
        previous_interaction_id: str,
        images: Optional[list[dict]] = None,
        agent_name: Optional[str] = None,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Continue an existing interaction with SSE streaming.

        Yields ProgressEvent objects parsed from the documented step-based SSE schema.
        """
        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "agent": agent_name or settings.gemini_agent_name,
                "input": _build_input(prompt, images),
                "system_instruction": settings.gemini_system_instruction,
                "environment": environment_id,
                "previous_interaction_id": previous_interaction_id,
                "stream": True,
            }

            url = f"{self.BASE_URL}/interactions"

            async with client.stream(
                "POST",
                url,
                headers=self.headers,
                json=payload,
            ) as response:
                await _raise_for_stream_status_with_body(response)
                async for event in _iter_sse_events(response):
                    # Ensure environment_id propagates back to the caller even when
                    # the API echoes it back as a different shape.
                    if event.event_type == "complete":
                        merged_data = dict(event.data or {})
                        merged_data.setdefault("environment_id", environment_id)
                        event = ProgressEvent(
                            event_type=event.event_type,
                            message=event.message,
                            data=merged_data,
                        )
                    yield event

    async def download_workspace_snapshot(
        self, environment_id: str
    ) -> bytes:
        """Download the workspace snapshot as a tar file (kept for backwards compatibility).

        Note: For large workspaces, use download_workspace_snapshot_to_tempfile() instead
        to avoid loading the entire archive into memory.
        """
        async with httpx.AsyncClient(timeout=120.0) as client:
            url = f"{self.BASE_URL}/files/environment-{environment_id}:download?alt=media"
            response = await client.get(url, headers=self.headers, follow_redirects=True)
            _raise_for_status_with_body(response)
            return response.content

    async def download_workspace_snapshot_to_tempfile(
        self, environment_id: str
    ) -> "tempfile.TemporaryFile":
        """Stream download workspace snapshot to a temporary file on disk.

        This is memory-efficient and prevents OOM errors with large workspaces.
        Returns a TemporaryFile object that must be managed by the caller.
        """
        import tempfile

        async with httpx.AsyncClient(timeout=120.0) as client:
            url = f"{self.BASE_URL}/files/environment-{environment_id}:download?alt=media"
            tmp = tempfile.TemporaryFile()

            async with client.stream("GET", url, headers=self.headers, follow_redirects=True) as response:
                await _raise_for_stream_status_with_body(response)
                async for chunk in response.aiter_bytes():
                    tmp.write(chunk)

            tmp.seek(0)
            return tmp


# Singleton instance
_gemini_service: Optional[GeminiService] = None


def get_gemini_service() -> GeminiService:
    """Get or create Gemini service instance."""
    global _gemini_service
    if _gemini_service is None:
        _gemini_service = GeminiService()
    return _gemini_service
