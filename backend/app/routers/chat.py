"""Chat and analysis router with SSE streaming."""

import io
import json
import logging
import os
import tarfile
import uuid
from datetime import datetime

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
5. Save useful outputs such as cleaned data, charts, metrics, model artifacts, or reports when the user asks for deliverables.

User request:
{user_prompt}"""


def build_data_science_prompt(user_prompt: str) -> str:
    """Wrap user requests with lightweight data-science operating instructions."""
    return DATA_SCIENCE_PROMPT_TEMPLATE.format(user_prompt=user_prompt)


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

    output_text = ""
    interaction_id = None

    if session.gemini_environment_id and session.last_interaction_id:
        async for event in gemini_service.continue_interaction_streaming(
            prompt=prompt,
            environment_id=session.gemini_environment_id,
            previous_interaction_id=session.last_interaction_id,
        ):
            if event.event_type == "complete":
                output_text = event.message
                interaction_id = event.data.get("interaction_id")
    else:
        environment_id = None

        async for event in gemini_service.create_interaction_streaming(
            prompt=prompt,
            gcs_input_path=gcs_input_path,
        ):
            if event.event_type == "complete":
                output_text = event.message
                environment_id = event.data.get("environment_id")
                interaction_id = event.data.get("interaction_id")

        if environment_id:
            session.gemini_environment_id = environment_id

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

        return ChatMessageResponse(
            message_id=assistant_message.message_id,
            session_id=assistant_message.session_id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
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

    async def event_generator():
        """Generate SSE events from Gemini streaming response."""
        try:
            output_text = ""
            environment_id = None
            interaction_id = None

            if session.gemini_environment_id and session.last_interaction_id:
                # Continue existing interaction
                async for event in gemini_service.continue_interaction_streaming(
                    prompt=build_data_science_prompt(request.message),
                    environment_id=session.gemini_environment_id,
                    previous_interaction_id=session.last_interaction_id,
                ):
                    # Yield SSE event
                    event_data = json.dumps({
                        "event_type": event.event_type,
                        "message": event.message,
                        "timestamp": event.timestamp.isoformat(),
                        "data": event.data,
                    })
                    yield f"data: {event_data}\n\n"

                    if event.event_type == "complete":
                        output_text = event.message
                        environment_id = session.gemini_environment_id
                        interaction_id = event.data.get("interaction_id")
            else:
                # Create new interaction
                async for event in gemini_service.create_interaction_streaming(
                    prompt=build_data_science_prompt(request.message),
                    gcs_input_path=gcs_input_path,
                ):
                    event_data = json.dumps({
                        "event_type": event.event_type,
                        "message": event.message,
                        "timestamp": event.timestamp.isoformat(),
                        "data": event.data,
                    })
                    yield f"data: {event_data}\n\n"

                    if event.event_type == "complete":
                        output_text = event.message
                        environment_id = event.data.get("environment_id")
                        interaction_id = event.data.get("interaction_id")

            # Update session
            if environment_id and not session.gemini_environment_id:
                session.gemini_environment_id = environment_id
            if interaction_id:
                session.last_interaction_id = interaction_id
            db.commit()

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

    if not session.gemini_environment_id:
        return ReportListResponse(session_id=session_id, reports=[])

    # List files in the output folder
    output_path = f"{session.gcs_folder_path}/output/"
    files = gcs_service.list_files(output_path)

    reports = []
    for f in files:
        # Filter for report types
        if any(f["name"].endswith(ext) for ext in [".pdf", ".html", ".png", ".jpg", ".csv"]):
            reports.append(
                DownloadResponse(
                    file_name=f["name"],
                    download_url=f"/chat/{session_id}/reports/{f['name']}",
                    file_type=os.path.splitext(f["name"])[1],
                    size_bytes=f["size"] or 0,
                )
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
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Download a specific report from the workspace."""
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    # First, try to get from GCS output folder
    output_path = f"{session.gcs_folder_path}/output/{filename}"
    files = gcs_service.list_files(f"{session.gcs_folder_path}/output/")

    if any(f["name"] == filename for f in files):
        content = gcs_service.download_file(output_path)
    elif session.gemini_environment_id:
        # Fall back to downloading workspace snapshot
        tar_content = await gemini_service.download_workspace_snapshot(
            session.gemini_environment_id
        )

        # Extract the specific file
        with tarfile.open(fileobj=io.BytesIO(tar_content), mode="r:*") as tar:
            for member in tar.getmembers():
                if member.name.endswith(filename):
                    f = tar.extractfile(member)
                    if f:
                        content = f.read()
                        break
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Report {filename} not found in workspace",
                )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {filename} not found",
        )

    # Determine content type
    ext = os.path.splitext(filename)[1].lower()
    content_types = {
        ".pdf": "application/pdf",
        ".html": "text/html",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".csv": "text/csv",
        ".json": "application/json",
    }

    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_types.get(ext, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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

    # Download workspace snapshot
    tar_content = await gemini_service.download_workspace_snapshot(
        session.gemini_environment_id
    )

    # Extract and upload to GCS output folder
    with tarfile.open(fileobj=io.BytesIO(tar_content), mode="r:*") as tar:
        for member in tar.getmembers():
            if member.isfile():
                f = tar.extractfile(member)
                if f:
                    content = f.read()
                    output_path = f"{session.gcs_folder_path}/output/{os.path.basename(member.name)}"
                    gcs_service.upload_to_path(
                        file_content=content,
                        gcs_path=output_path,
                    )

    return {"status": "harvested", "message": "Workspace files saved to GCS"}
