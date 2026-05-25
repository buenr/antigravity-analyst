"""Chat and analysis router with SSE streaming."""

import io
import json
import logging
import os
import re
import tarfile
import uuid
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ChatMessage, UploadedFile, UserSession
from app.schemas import (
    ChatMessageResponse,
    ChatRequest,
    ErrorResponse,
    DownloadResponse,
    ReportListResponse,
)
from app.services.gcs_service import get_gcs_service
from app.services.gemini_service import get_gemini_service

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


REPORT_EXTENSIONS = (
    ".pdf",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".csv",
    ".xlsx",
    ".xls",
    ".json",
    ".md",
    ".pptx",
    ".ppt",
    ".docx",
    ".txt",
    ".tar.gz",
    ".zip",
)


ANALYST_BRIEF_PROMPT = """You are a careful data analyst. Inspect the uploaded files mounted at /workspace/data and write a concise first-pass analyst brief.

Include:
- Dataset names, row counts, column counts, and important columns when you can determine them.
- Likely meanings of the columns, but label guesses as guesses.
- Missingness, duplicates, suspicious values, type issues, and potential outliers.
- 3 to 5 useful follow-up questions the user can ask next.

Do not invent conclusions beyond what you can inspect. If a file cannot be read, say which file and why. Keep the brief practical and easy to scan."""


DATA_SCIENCE_PROMPT_TEMPLATE = """You are a rigorous data scientist working in a Python sandbox with the uploaded files in /workspace/data.

Before answering:
1. Inspect the actual files, schemas, row counts, column types, missing values, and sample rows.
2. State assumptions clearly and do not invent conclusions.
3. For ML tasks, identify the target column, check for leakage, choose an appropriate train/test split, build a simple baseline first, then compare better models only if useful.
4. Report metrics appropriate to the task: classification, regression, clustering, or forecasting.
5. Save final requested deliverables inside a directory named `./outputs/` (relative to your current working directory).
   - Create the `./outputs/` directory first if it does not exist.
   - Always place the final user-facing files (e.g., a compiled PDF report, a PowerPoint presentation, or a final clean summary CSV) in `./outputs/`.
   - Leave all raw plotting images, temporary cleanups, and scratchpad files in the root directory or `./tmp/`. Do not put intermediate building blocks in `./outputs/`.
6. When the user asks for a downloadable artifact (PDF, chart image, export, etc.):
   - Save it under `./outputs/` with a clear basename (e.g. `revenue_chart.png`, `analysis_report.pdf`).
   - In your final answer, name each deliverable file exactly as saved (basename only).
   - Do not invent URLs, session IDs, or download links; the application attaches download links automatically.

User request:
{user_prompt}"""


def build_data_science_prompt(user_prompt: str) -> str:
    """Wrap user requests with lightweight data-science operating instructions."""
    return DATA_SCIENCE_PROMPT_TEMPLATE.format(user_prompt=user_prompt)


def is_downloadable_report(filename: str) -> bool:
    """Return whether a file should appear in the generated reports list."""
    lower_name = filename.lower()
    return lower_name.endswith(REPORT_EXTENSIONS)


def content_type_for_filename(filename: str) -> str:
    """Return a useful content type for browser downloads."""
    lower_name = filename.lower()
    if lower_name.endswith(".tar.gz"):
        return "application/gzip"

    ext = os.path.splitext(filename)[1].lower()
    content_types = {
        ".pdf": "application/pdf",
        ".html": "text/html",
        ".htm": "text/html",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".csv": "text/csv",
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".zip": "application/zip",
    }
    return content_types.get(ext, "application/octet-stream")


# User-facing deliverable extensions (only harvested from ./outputs/)
OUTPUT_DELIVERABLE_EXTENSIONS = (
    ".pdf",
    ".pptx",
    ".ppt",
    ".docx",
    ".xlsx",
    ".xls",
    ".zip",
    ".tar.gz",
    ".png",
    ".jpg",
    ".jpeg",
    ".csv",
    ".json",
    ".md",
    ".txt",
    ".html",
    ".htm",
)

# Paths that commonly contain library assets, not user deliverables
NOISE_PATH_FRAGMENTS = (
    "site-packages",
    "dist-packages",
    "matplotlib",
    "node_modules",
    ".venv",
    "venv/",
    "/lib/python",
    "/share/",
)

# Matplotlib ships toolbar icons as tiny PDFs; never show these as user deliverables
EXCLUDED_REPORT_BASENAMES = frozenset(
    {
        "back.pdf",
        "forward.pdf",
        "filesave.pdf",
        "hand.pdf",
        "help.pdf",
        "home.pdf",
        "matplotlib.pdf",
        "move.pdf",
        "qt4_editor_options.pdf",
        "subplots.pdf",
        "zoom_to_rect.pdf",
    }
)

_UUID_XLSX_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.xlsx$",
    re.IGNORECASE,
)


def is_spurious_output_file(filename: str) -> bool:
    """Return True for known library/scratch artifacts stored in output/."""
    lower_name = filename.lower()
    if lower_name in EXCLUDED_REPORT_BASENAMES:
        return True
    if _UUID_XLSX_PATTERN.match(lower_name):
        return True
    return False


def _is_in_outputs_dir(member_path: str) -> bool:
    normalized_path = member_path.lstrip("./")
    return (
        normalized_path.startswith("outputs/")
        or "/outputs/" in normalized_path
    )


def _is_noise_path(member_path: str) -> bool:
    lower_path = member_path.lower()
    return any(fragment in lower_path for fragment in NOISE_PATH_FRAGMENTS)


def is_final_deliverable(member_path: str, filename: str) -> bool:
    """Determine if a file is a final deliverable vs intermediate noise.

    Rules:
    1. Must live under ./outputs/ (never harvest matplotlib icons, temp PDFs, etc.)
    2. Must match a known deliverable extension
    3. Must not come from library/vendor paths inside the sandbox snapshot
    """
    if _is_noise_path(member_path):
        return False

    if not _is_in_outputs_dir(member_path):
        return False

    lower_filename = filename.lower()
    return any(lower_filename.endswith(ext) for ext in OUTPUT_DELIVERABLE_EXTENSIONS)


def extract_mentioned_deliverables(text: str) -> set[str]:
    """Find deliverable basenames explicitly referenced in assistant text."""
    mentioned: set[str] = set()
    if not text:
        return mentioned

    for ext in REPORT_EXTENSIONS:
        if ext == ".tar.gz":
            pattern = re.compile(
                r"(?<![\w./-])([\w][\w.-]*\.tar\.gz)(?![\w.-])",
                re.IGNORECASE,
            )
        else:
            pattern = re.compile(
                rf"(?<![\w./-])([\w][\w.-]*{re.escape(ext)})(?![\w.-])",
                re.IGNORECASE,
            )
        for match in pattern.finditer(text):
            mentioned.add(match.group(1))

    return mentioned


def filter_reports_by_mentioned_files(
    reports: list[DownloadResponse],
    assistant_text: str,
) -> list[DownloadResponse]:
    """Keep only harvested files the assistant named in its reply."""
    mentioned = extract_mentioned_deliverables(assistant_text)
    if not mentioned:
        return []

    mentioned_lower = {name.lower() for name in mentioned}
    return [
        report
        for report in reports
        if report.file_name.lower() in mentioned_lower
    ]


async def harvest_workspace_files(session, gemini_service, gcs_service) -> int:
    """Copy final deliverables from Gemini workspace snapshot to GCS output.

    Filters out intermediate build assets (plot images, temp files, etc.)
    and only harvests user-facing deliverables. Uses streaming download to
    temporary file to avoid OOM with large workspaces.
    """
    if not session.gemini_environment_id:
        return 0

    # Use streaming download to temporary file (memory-efficient)
    tmp = await gemini_service.download_workspace_snapshot_to_tempfile(
        session.gemini_environment_id
    )

    harvested_count = 0
    try:
        with tarfile.open(fileobj=tmp, mode="r:*") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue

                filename = os.path.basename(member.name)
                if not filename:
                    continue

                # Filter: only harvest final deliverables, not intermediate noise
                if not is_final_deliverable(member.name, filename):
                    continue

                f = tar.extractfile(member)
                if not f:
                    continue

                gcs_service.upload_to_path(
                    file_content=f.read(),
                    gcs_path=f"{session.gcs_folder_path}/output/{filename}",
                    content_type=content_type_for_filename(filename),
                )
                harvested_count += 1
    finally:
        tmp.close()

    return harvested_count


def report_download_path(session_id: uuid.UUID, filename: str) -> str:
    """Return app-relative URL for attachment download (no inline preview)."""
    return f"/chat/{session_id}/reports/{quote(filename)}"


def build_download_response(session_id: uuid.UUID, file_info: dict) -> DownloadResponse:
    """Build download metadata for a harvested output file."""
    name = file_info["name"]
    return DownloadResponse(
        file_name=name,
        download_url=report_download_path(session_id, name),
        file_type=os.path.splitext(name)[1],
        size_bytes=file_info.get("size") or 0,
    )


def _output_report_names(gcs_service, gcs_folder_path: str) -> set[str]:
    output_path = f"{gcs_folder_path}/output/"
    return {
        f["name"]
        for f in gcs_service.list_files(output_path)
        if is_downloadable_report(f["name"])
    }


async def list_session_reports(
    session: UserSession,
    gemini_service,
    gcs_service,
    *,
    only_new: bool = False,
) -> tuple[list[DownloadResponse], int]:
    """Harvest workspace deliverables and return downloadable report metadata."""
    output_path = f"{session.gcs_folder_path}/output/"
    existing_names: set[str] = set()
    if only_new:
        existing_names = _output_report_names(gcs_service, session.gcs_folder_path)

    harvested_count = 0
    if session.gemini_environment_id:
        try:
            harvested_count = await harvest_workspace_files(
                session, gemini_service, gcs_service
            )
        except Exception as e:
            logger.warning(f"Unable to harvest workspace reports: {str(e)}")

    reports = []
    for file_info in gcs_service.list_files(output_path):
        name = file_info["name"]
        if not is_downloadable_report(name):
            continue
        if is_spurious_output_file(name):
            continue
        if only_new and name in existing_names:
            continue
        reports.append(build_download_response(session.session_id, file_info))

    return reports, harvested_count


def reports_to_dicts(reports: list[DownloadResponse]) -> list[dict]:
    """Serialize report metadata for SSE JSON payloads."""
    return [report.model_dump() for report in reports]


def build_context_from_history(messages: list[ChatMessage]) -> str:
    """Build a context string from chat history for environment refresh."""
    context_parts = []
    for msg in messages:
        role_prefix = "User" if msg.role == "user" else "Assistant"
        context_parts.append(f"[{role_prefix}]: {msg.content[:500]}")
    return "\n\n".join(context_parts[-5:])  # Keep last 5 messages


async def run_agent_prompt(
    prompt: str,
    session: UserSession,
    db: Session,
    gemini_service,
    gcs_service,
) -> tuple[str, str | None]:
    """Run a prompt against the session's Gemini environment and update session state."""
    gcs_input_path = gcs_service.get_input_folder_path(
        tenant_id=session.tenant_id,
        user_id=str(session.user_id),
        session_id=str(session.session_id),
    )
    gcs_token = gcs_service.get_access_token()

    output_text = ""
    interaction_id = None

    # Check if environment needs refresh due to new file uploads
    needs_refresh = session.environment_needs_refresh and session.gemini_environment_id

    if session.gemini_environment_id and session.last_interaction_id and not needs_refresh:
        # Continue existing interaction
        async for event in gemini_service.continue_interaction_streaming(
            prompt=prompt,
            environment_id=session.gemini_environment_id,
            previous_interaction_id=session.last_interaction_id,
        ):
            if event.event_type == "complete":
                output_text = event.message
                interaction_id = event.data.get("interaction_id")
    else:
        # Create new interaction
        environment_id = None

        # If refreshing, include chat history as context
        full_prompt = prompt
        if needs_refresh and session.gemini_environment_id:
            history = db.query(ChatMessage).filter(
                ChatMessage.session_id == session.session_id
            ).order_by(ChatMessage.created_at.asc()).limit(20).all()
            if history:
                context = build_context_from_history(history)
                full_prompt = f"""Previous conversation context:\n\n{context}\n\n---\n\nNew request: {prompt}"""

        async for event in gemini_service.create_interaction_streaming(
            prompt=full_prompt,
            gcs_input_path=gcs_input_path,
            gcs_token=gcs_token,
        ):
            if event.event_type == "complete":
                output_text = event.message
                environment_id = event.data.get("environment_id")
                interaction_id = event.data.get("interaction_id")

        if environment_id:
            session.gemini_environment_id = environment_id
            session.environment_created_at = datetime.utcnow()
            session.environment_needs_refresh = False

    if interaction_id:
        session.last_interaction_id = interaction_id
    db.commit()

    return output_text, interaction_id


@router.post(
    "/{session_id}",
    response_model=ChatMessageResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def send_message(
    session_id: uuid.UUID,
    request: ChatRequest,
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Send a chat message to the agent (non-streaming)."""
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    # Save user message
    user_message = ChatMessage(
        message_id=uuid.uuid4(),
        session_id=session.session_id,
        role="user",
        content=request.message,
    )
    db.add(user_message)
    db.commit()

    try:
        output_text, interaction_id = await run_agent_prompt(
            prompt=build_data_science_prompt(request.message),
            session=session,
            db=db,
            gemini_service=gemini_service,
            gcs_service=gcs_service,
        )

        # Save assistant message
        assistant_message = ChatMessage(
            message_id=uuid.uuid4(),
            session_id=session.session_id,
            role="assistant",
            content=output_text,
            interaction_id=interaction_id,
        )
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)

        reports, _ = await list_session_reports(
            session=session,
            gemini_service=gemini_service,
            gcs_service=gcs_service,
            only_new=True,
        )
        reports = filter_reports_by_mentioned_files(reports, output_text)

        return ChatMessageResponse(
            message_id=assistant_message.message_id,
            session_id=assistant_message.session_id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            attachments=reports,
        )

    except Exception as e:
        logger.error(f"Error in chat: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/{session_id}/brief",
    response_model=ChatMessageResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def generate_analyst_brief(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Generate a first-pass analyst brief for uploaded session files."""
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    uploaded_file_count = db.query(UploadedFile).filter(
        UploadedFile.session_id == session_id
    ).count()

    if uploaded_file_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload at least one file before generating an analyst brief",
        )

    existing_assistant_message = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.role == "assistant",
    ).order_by(ChatMessage.created_at.asc()).first()

    if existing_assistant_message:
        return ChatMessageResponse(
            message_id=existing_assistant_message.message_id,
            session_id=existing_assistant_message.session_id,
            role=existing_assistant_message.role,
            content=existing_assistant_message.content,
            created_at=existing_assistant_message.created_at,
        )

    try:
        output_text, interaction_id = await run_agent_prompt(
            prompt=ANALYST_BRIEF_PROMPT,
            session=session,
            db=db,
            gemini_service=gemini_service,
            gcs_service=gcs_service,
        )

        assistant_message = ChatMessage(
            message_id=uuid.uuid4(),
            session_id=session.session_id,
            role="assistant",
            content=output_text,
            interaction_id=interaction_id,
        )
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)

        return ChatMessageResponse(
            message_id=assistant_message.message_id,
            session_id=assistant_message.session_id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
        )

    except Exception as e:
        logger.error(f"Error generating analyst brief: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/{session_id}/stream",
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def send_message_stream(
    session_id: uuid.UUID,
    request: ChatRequest,
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Send a chat message and stream the response via SSE."""
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    # Save user message
    user_message = ChatMessage(
        message_id=uuid.uuid4(),
        session_id=session.session_id,
        role="user",
        content=request.message,
    )
    db.add(user_message)
    db.commit()

    # Get GCS input path
    gcs_input_path = gcs_service.get_input_folder_path(
        tenant_id=session.tenant_id,
        user_id=str(session.user_id),
        session_id=str(session.session_id),
    )
    gcs_token = gcs_service.get_access_token()

    async def event_generator():
        """Generate SSE events from Gemini streaming response."""
        try:
            output_text = ""
            environment_id = None
            interaction_id = None
            complete_event_data = {}

            # Check if environment needs refresh due to new file uploads
            needs_refresh = session.environment_needs_refresh and session.gemini_environment_id

            if session.gemini_environment_id and session.last_interaction_id and not needs_refresh:
                # Continue existing interaction
                async for event in gemini_service.continue_interaction_streaming(
                    prompt=build_data_science_prompt(request.message),
                    environment_id=session.gemini_environment_id,
                    previous_interaction_id=session.last_interaction_id,
                ):
                    if event.event_type == "complete":
                        output_text = event.message
                        environment_id = session.gemini_environment_id
                        interaction_id = event.data.get("interaction_id")
                        complete_event_data = event.data or {}
                        continue

                    event_data = json.dumps({
                        "event_type": event.event_type,
                        "message": event.message,
                        "timestamp": event.timestamp.isoformat(),
                        "data": event.data,
                    })
                    yield f"data: {event_data}\n\n"
            else:
                # Create new interaction (or refresh due to new files)
                full_prompt = build_data_science_prompt(request.message)

                # If refreshing, include chat history as context
                if needs_refresh and session.gemini_environment_id:
                    history = db.query(ChatMessage).filter(
                        ChatMessage.session_id == session.session_id
                    ).order_by(ChatMessage.created_at.asc()).limit(20).all()
                    if history:
                        context = build_context_from_history(history)
                        full_prompt = f"""Previous conversation context:

{context}

---

{full_prompt}"""
                    yield f'data: {{"event_type": "refresh", "message": "Refreshing environment with new files...", "timestamp": "{datetime.utcnow().isoformat()}"}}\n\n'

                async for event in gemini_service.create_interaction_streaming(
                    prompt=full_prompt,
                    gcs_input_path=gcs_input_path,
                    gcs_token=gcs_token,
                ):
                    if event.event_type == "complete":
                        output_text = event.message
                        environment_id = event.data.get("environment_id")
                        interaction_id = event.data.get("interaction_id")
                        complete_event_data = event.data or {}
                        continue

                    event_data = json.dumps({
                        "event_type": event.event_type,
                        "message": event.message,
                        "timestamp": event.timestamp.isoformat(),
                        "data": event.data,
                    })
                    yield f"data: {event_data}\n\n"

            # Update session
            if environment_id:
                session.gemini_environment_id = environment_id
                session.environment_created_at = datetime.utcnow()
                session.environment_needs_refresh = False
            if interaction_id:
                session.last_interaction_id = interaction_id
            db.commit()

            reports, harvested_count = await list_session_reports(
                session=session,
                gemini_service=gemini_service,
                gcs_service=gcs_service,
                only_new=True,
            )
            reports = filter_reports_by_mentioned_files(reports, output_text)

            # Save assistant message
            assistant_message = ChatMessage(
                message_id=uuid.uuid4(),
                session_id=session.session_id,
                role="assistant",
                content=output_text,
                interaction_id=interaction_id,
            )
            db.add(assistant_message)
            db.commit()

            complete_payload = {
                "event_type": "complete",
                "message": output_text,
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    **complete_event_data,
                    "interaction_id": interaction_id,
                    "harvested_count": harvested_count,
                    "reports": reports_to_dicts(reports),
                },
            }
            yield f"data: {json.dumps(complete_payload)}\n\n"

        except Exception as e:
            logger.error(f"Error in streaming: {str(e)}")
            error_data = json.dumps({
                "event_type": "error",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            })
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{session_id}/history",
    response_model=list[ChatMessageResponse],
    responses={
        404: {"model": ErrorResponse},
    },
)
def get_chat_history(
    session_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Get chat history for a session."""
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        ChatMessageResponse(
            message_id=m.message_id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.get(
    "/{session_id}/reports",
    response_model=ReportListResponse,
    responses={
        404: {"model": ErrorResponse},
    },
)
async def list_reports(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """List available reports generated in the session workspace."""
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    reports, _ = await list_session_reports(
        session=session,
        gemini_service=gemini_service,
        gcs_service=gcs_service,
        only_new=False,
    )

    return ReportListResponse(session_id=session_id, reports=reports)


@router.get(
    "/{session_id}/reports/{filename}",
    responses={
        404: {"model": ErrorResponse},
    },
)
async def download_report(
    session_id: uuid.UUID,
    filename: str,
    inline: bool = False,
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Download a specific report from the workspace.

    Args:
        inline: If True, serves file inline (for chat images). If False, forces download.
    """
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    content = None

    # First, try to get from GCS output folder
    output_path = f"{session.gcs_folder_path}/output/{filename}"
    files = gcs_service.list_files(f"{session.gcs_folder_path}/output/")

    if any(f["name"] == filename for f in files):
        content = gcs_service.download_file(output_path)
    elif session.gemini_environment_id:
        # Fall back to streaming workspace snapshot to temp file (memory-efficient)
        tmp = await gemini_service.download_workspace_snapshot_to_tempfile(
            session.gemini_environment_id
        )
        try:
            with tarfile.open(fileobj=tmp, mode="r:*") as tar:
                for member in tar.getmembers():
                    if member.name.endswith(filename):
                        f = tar.extractfile(member)
                        if f:
                            content = f.read()
                            break
                else:
                    tmp.close()
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Report {filename} not found in workspace",
                    )
        finally:
            tmp.close()
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {filename} not found",
        )

    headers = {}
    if not inline:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type_for_filename(filename),
        headers=headers,
    )


@router.post(
    "/{session_id}/harvest",
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse},
    },
)
async def harvest_workspace(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Harvest the workspace snapshot and save to GCS for persistence."""
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    if not session.gemini_environment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active Gemini environment for this session",
        )

    harvested_count = await harvest_workspace_files(
        session=session,
        gemini_service=gemini_service,
        gcs_service=gcs_service,
    )

    return {
        "status": "harvested",
        "message": f"{harvested_count} workspace files saved to GCS",
    }
