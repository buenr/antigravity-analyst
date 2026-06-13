"""Chat and analysis router with SSE streaming."""

import base64
import io
import json
import logging
import os
import re
import tarfile
import uuid
from datetime import datetime
from typing import AsyncGenerator
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import get_owned_session, session_token_dependency
from app.config import get_settings
from app.database import get_db, SessionLocal
from app.models import ChatMessage, UploadedFile, UserSession
from app.schemas import (
    ChatMessageResponse,
    ChatRequest,
    ErrorResponse,
    AnalysisContract,
    DownloadResponse,
    ImageInput,
    ProgressEvent,
    ReportListResponse,
    UsageInfo,
)
from app.services.gcs_service import get_gcs_service
from app.services.gemini_service import GeminiApiError, get_gemini_service

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)
settings = get_settings()


ANALYSIS_CONTRACT_SECTIONS = (
    "findings",
    "assumptions",
    "data_quality",
    "methods",
    "limitations",
    "artifacts",
)


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


ANALYST_BRIEF_PROMPT = """You are a careful business analyst and data scientist. Inspect the uploaded files mounted at /workspace/data and write a concise first-pass analyst brief.

Before inspecting data: ensure Tier 1 packages are installed by running `bash .agents/bootstrap_packages.sh 1` if needed (see `.agents/AGENTS.md`). Do not mention bootstrap in the brief unless installation failed.

Include:
- Dataset names, row counts, column counts, and important columns when you can determine them.
- Likely meanings of the columns, but label guesses as guesses.
- Missingness, duplicates, suspicious values, type issues, and potential outliers.
- Apparent business grain (for example, customer, order, transaction, product, date, event), likely keys, and likely join paths.
- Likely KPI candidates, measures, dimensions, date fields, and segments that could support business analysis.
- Data-readiness risks that could affect conclusions, such as missing definitions, inconsistent categories, incomplete time windows, duplicate entities, or questionable outliers.
- Practical next analyses, such as KPI profiling, driver analysis, segmentation, churn/risk analysis, forecasting, or executive reporting when relevant.
- 3 to 5 useful follow-up questions the user can ask next.

Do not invent conclusions beyond what you can inspect. If a file cannot be read, say which file and why. Keep the brief practical and easy to scan.

End your response with this exact markdown analysis contract, using every heading even when the value is "None":
## Findings
## Assumptions
## Data Quality
## Methods
## Limitations
## Artifacts"""


DATA_SCIENCE_PROMPT_TEMPLATE = """You are a rigorous business analyst, data scientist, and report writer working in a Python sandbox with the uploaded files in /workspace/data.

Before answering:
1. Ensure required Python packages are installed per `.agents/AGENTS.md` (Tier 1 always; higher tiers on demand via `bash .agents/bootstrap_packages.sh <tier>`).
2. Inspect the actual files before drawing conclusions: schemas, row counts, column types, missing values, duplicates, suspicious values, outliers, sample rows, likely keys, and apparent business grain.
3. Identify the user's business question, audience, decision, KPI, or success metric when available. If essential context is missing, ask a concise clarification; otherwise proceed with explicit assumptions.
4. Clean, wrangle, filter, join, or aggregate data only as needed for the request, and state important transformations or exclusions.
5. Choose methods that fit the question and data: descriptive analysis, statistical tests, segmentation, visualization, forecasting, or machine learning.
6. For statistical work, report uncertainty, effect size, and practical significance when possible; avoid causal claims unless the data supports them.
7. For ML tasks, identify the target column, prediction unit, business metric, leakage risks, validation strategy, and simple baseline before comparing better models.
8. For forecasting tasks, use chronological validation, baseline forecasts, horizon assumptions, and uncertainty intervals where feasible.
9. Create clear, accurate, accessible visualizations when they help: know the audience, choose the right chart type, keep visuals simple, label axes and units, use legends when needed, use color strategically, avoid relying on color alone, start bar charts at zero unless clearly justified, avoid misleading scales or clutter, and use annotations to guide attention to key takeaways.
10. Communicate like a business analyst: lead with findings, explain the business impact, connect results to practical actions, and preserve caveats and limitations.
11. State assumptions clearly and do not invent conclusions, data values, filenames, metrics, citations, URLs, or download links.
12. Save final requested deliverables inside a directory named `./outputs/` (relative to your current working directory).
   - Create the `./outputs/` directory first if it does not exist.
   - Always place the final user-facing files (e.g., a compiled PDF report, a PowerPoint presentation, or a final clean summary CSV) in `./outputs/`.
   - Leave all raw plotting images, temporary cleanups, and scratchpad files in the root directory or `./tmp/`. Do not put intermediate building blocks in `./outputs/`.
13. When the user asks for a downloadable artifact (PDF, chart image, export, etc.):
   - Save it under `./outputs/` with a clear basename (e.g. `revenue_chart.png`, `analysis_report.pdf`).
   - In your final answer, name each deliverable file exactly as saved (basename only).
   - Do not invent URLs, session IDs, or download links; the application attaches download links automatically.
14. End every final response with this exact markdown analysis contract, using every heading even when the value is "None":
   ## Findings
   ## Assumptions
   ## Data Quality
   ## Methods
   ## Limitations
   ## Artifacts

User request:
{user_prompt}"""


def build_data_science_prompt(user_prompt: str) -> str:
    """Wrap user requests with lightweight data-science operating instructions."""
    return DATA_SCIENCE_PROMPT_TEMPLATE.format(user_prompt=user_prompt)


def _configured_agent_name(agent_name: str | None) -> str:
    return agent_name or settings.gemini_agent_name


def select_specialist_agent(user_prompt: str, *, is_brief: bool = False) -> tuple[str, str]:
    """Route a request to a specialist managed agent when one is configured."""
    prompt = user_prompt.lower()
    if is_brief:
        return "data-profiler", _configured_agent_name(settings.gemini_data_profiler_agent_name)

    deliverable_terms = (
        "report", "pdf", "powerpoint", "ppt", "slide", "docx", "word",
        "export", "download", "dashboard", "chart", "visualization", "plot",
    )
    forecasting_terms = (
        "forecast", "time series", "timeseries", "seasonal", "seasonality",
        "backtest", "trend", "future", "projection",
    )
    ml_terms = (
        "model", "predict", "classification", "classifier", "regression",
        "cluster", "clustering", "feature importance", "auc", "accuracy",
        "train", "test split", "leakage",
    )
    stats_terms = (
        "correlation", "hypothesis", "significant", "p-value",
        "confidence interval", "anova", "t-test", "statistical", "segment",
        "compare",
    )
    profile_terms = (
        "profile", "summarize", "summary", "missing", "duplicates",
        "outliers", "schema", "columns", "quality", "brief",
    )

    if any(term in prompt for term in deliverable_terms):
        return "deliverable-builder", _configured_agent_name(settings.gemini_deliverable_builder_agent_name)
    if any(term in prompt for term in forecasting_terms):
        return "forecasting-reviewer", _configured_agent_name(settings.gemini_forecasting_reviewer_agent_name)
    if any(term in prompt for term in ml_terms):
        return "ml-reviewer", _configured_agent_name(settings.gemini_ml_reviewer_agent_name)
    if any(term in prompt for term in stats_terms):
        return "statistician", _configured_agent_name(settings.gemini_statistician_agent_name)
    if any(term in prompt for term in profile_terms):
        return "data-profiler", _configured_agent_name(settings.gemini_data_profiler_agent_name)
    return "data-analyst", settings.gemini_agent_name


def _normalize_contract_heading(heading: str) -> str | None:
    normalized = re.sub(r"[^a-z_ ]", "", heading.lower()).strip().replace(" ", "_")
    return normalized if normalized in ANALYSIS_CONTRACT_SECTIONS else None


def _section_items(section_text: str) -> list[str]:
    items: list[str] = []
    for raw_line in section_text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        if line and line.lower() not in {"none", "n/a", "na"}:
            items.append(line)
    return items


def parse_analysis_contract(text: str) -> AnalysisContract:
    """Extract the required markdown analysis contract from assistant text."""
    sections: dict[str, list[str]] = {name: [] for name in ANALYSIS_CONTRACT_SECTIONS}
    matches = list(re.finditer(r"(?m)^#{2,3}\s+(.+?)\s*$", text or ""))

    for index, match in enumerate(matches):
        section_name = _normalize_contract_heading(match.group(1))
        if not section_name:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[section_name] = _section_items(text[start:end])

    present = {
        _normalize_contract_heading(match.group(1))
        for match in matches
        if _normalize_contract_heading(match.group(1))
    }
    missing = [name for name in ANALYSIS_CONTRACT_SECTIONS if name not in present]
    return AnalysisContract(
        **sections,
        valid=not missing,
        missing_sections=missing,
    )


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


def _usage_from_event_data(data: dict | None) -> UsageInfo | None:
    """Pull a usage payload out of an interaction.completed event."""
    if not data:
        return None
    usage = data.get("usage")
    if not usage and isinstance(data.get("interaction"), dict):
        usage = data["interaction"].get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        return UsageInfo(**{k: v for k, v in usage.items() if k in UsageInfo.model_fields})
    except Exception:
        logger.debug("Could not coerce usage payload: %s", usage)
        return None


_EXPIRED_INTERACTION_MARKERS = (
    "not found",
    "interaction",
    "expired",
    "previous_interaction",
    "invalid_argument",
)


def _is_expired_interaction_error(exc: BaseException) -> bool:
    """Heuristic: does this Gemini error mean ``previous_interaction_id`` is no longer valid?

    The Interactions API retains interactions 1 day (free tier) / 55 days (paid).
    Once retention expires the API returns 404 NOT_FOUND or 400 INVALID_ARGUMENT
    referencing the missing interaction; on those we silently restart the conversation.
    """
    if not isinstance(exc, GeminiApiError):
        return False
    if exc.status_code not in (400, 404):
        return False
    body = (exc.body or "").lower()
    return any(marker in body for marker in _EXPIRED_INTERACTION_MARKERS)


# Text-decodable extensions that we will inline into the prompt for the agent
# to write into /workspace/data when reusing an existing sandbox.
_TEXT_INLINE_EXTENSIONS = frozenset(
    {".csv", ".tsv", ".json", ".jsonl", ".txt", ".md", ".log", ".yaml", ".yml"}
)
_IMAGE_INLINE_MIME_PREFIX = "image/"
_INLINE_TEXT_MAX_BYTES = 500_000      # ~500 KB per text file
_INLINE_IMAGE_MAX_BYTES = 4_000_000   # ~4 MB raw image (≈5.5 MB base64)


def _files_uploaded_since_environment(
    db: Session, session: UserSession
) -> list[UploadedFile]:
    """Return uploads created after the current sandbox was provisioned."""
    if not session.gemini_environment_id or not session.environment_created_at:
        return []
    return (
        db.query(UploadedFile)
        .filter(
            UploadedFile.session_id == session.session_id,
            UploadedFile.created_at > session.environment_created_at,
        )
        .order_by(UploadedFile.created_at.asc())
        .all()
    )


def _prepare_inline_new_files(
    new_files: list[UploadedFile],
    gcs_service,
) -> tuple[list[str], list[dict], list[str]]:
    """Try to inline each new upload so the existing sandbox can pick it up
    without losing installed packages.

    Returns ``(text_blocks, image_inputs, oversized)`` where:
      * ``text_blocks`` is a list of fenced code blocks to splice into the prompt,
        each prefixed with an instruction to ``Save the contents below to
        /workspace/data/<filename>``.
      * ``image_inputs`` is a list of multimodal image parts (base64).
      * ``oversized`` lists files that couldn't be inlined and therefore require
        the caller to fall back to recreating the sandbox.
    """
    text_blocks: list[str] = []
    image_inputs: list[dict] = []
    oversized: list[str] = []

    for uf in new_files:
        try:
            content = gcs_service.download_file(uf.gcs_path)
        except Exception as e:
            logger.warning("Could not read %s from GCS: %s", uf.original_filename, e)
            oversized.append(uf.original_filename)
            continue

        mime = (uf.mime_type or "").lower()
        ext = os.path.splitext(uf.original_filename)[1].lower()

        if mime.startswith(_IMAGE_INLINE_MIME_PREFIX):
            if len(content) > _INLINE_IMAGE_MAX_BYTES:
                oversized.append(uf.original_filename)
                continue
            image_inputs.append({
                "data": base64.b64encode(content).decode("ascii"),
                "mime_type": mime or "image/png",
            })
            continue

        if ext in _TEXT_INLINE_EXTENSIONS and len(content) <= _INLINE_TEXT_MAX_BYTES:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = content.decode("utf-8", errors="replace")
                except Exception:
                    oversized.append(uf.original_filename)
                    continue
            safe_name = uf.original_filename.replace("`", "\\`")
            text_blocks.append(
                f"### New uploaded file `{safe_name}`\n"
                f"Save the verbatim contents below to `/workspace/data/{safe_name}` "
                f"using Python (e.g. `Path(...).write_text(...)` or `write_bytes`) "
                f"before processing.\n\n"
                f"```\n{text}\n```"
            )
            continue

        oversized.append(uf.original_filename)

    return text_blocks, image_inputs, oversized


def _augment_prompt_with_new_files(prompt: str, text_blocks: list[str]) -> str:
    """Splice inline file blocks into the prompt as a NEW FILES preamble."""
    if not text_blocks:
        return prompt
    preamble = (
        "[SYSTEM] The user uploaded new files since the sandbox was last refreshed. "
        "Save each one into /workspace/data/ exactly as named before answering, "
        "then continue with the user's request below.\n\n"
        + "\n\n".join(text_blocks)
        + "\n\n---\n\n"
    )
    return preamble + prompt


async def drive_agent_interaction(
    prompt: str,
    session: UserSession,
    db: Session,
    gemini_service,
    gcs_service,
    images: list[dict] | None = None,
    agent_name: str | None = None,
    agent_role: str | None = None,
) -> AsyncGenerator[ProgressEvent, None]:
    """Single source of truth for routing a prompt to Gemini.

    Yields raw ProgressEvent objects from the underlying SSE stream and handles
    three concerns transparently:

      1. **Continue when possible.** If the session has an active env + interaction
         and no new uploads pending, continue the existing interaction.
      2. **Expired interaction retry.** A 400/404 from the continue path is treated
         as an expired ``previous_interaction_id`` (Gemini retains interactions for
         1 day / 55 days). The conversation restarts on a fresh interaction with
         prior chat history as context, transparently to the caller.
      3. **Soft refresh on new uploads.** When new files were uploaded since the
         sandbox was provisioned, inline them into the prompt (text files) or as
         multimodal images so the existing sandbox can pick them up without
         discarding installed packages. Only if a new file is too large or binary
         to inline do we recreate the sandbox.

    Session state (``gemini_environment_id``, ``last_interaction_id``,
    ``environment_needs_refresh``, ``environment_created_at``) is updated on
    completion.
    """
    # Re-attach session to database session in case it became detached
    session = db.merge(session)

    gcs_input_path = gcs_service.get_input_folder_path(
        tenant_id=session.tenant_id,
        user_id=str(session.user_id),
        session_id=str(session.session_id),
    )
    gcs_token = gcs_service.get_access_token()
    selected_agent = agent_name or settings.gemini_agent_name
    selected_role = agent_role or "data-analyst"

    needs_refresh = bool(
        session.environment_needs_refresh and session.gemini_environment_id
    )

    # Try a soft refresh first (preserve sandbox + installed tiers) when possible.
    inline_text_blocks: list[str] = []
    inline_image_inputs: list[dict] = []
    force_recreate = False
    if needs_refresh:
        new_files = _files_uploaded_since_environment(db, session)
        if new_files:
            inline_text_blocks, inline_image_inputs, oversized = (
                _prepare_inline_new_files(new_files, gcs_service)
            )
            if oversized:
                force_recreate = True
                logger.info(
                    "Recreating sandbox because new uploads are not inline-safe: %s",
                    oversized,
                )

    can_continue = (
        session.gemini_environment_id
        and session.last_interaction_id
        and (not needs_refresh or not force_recreate)
    )

    combined_images = list(images or []) + inline_image_inputs

    output_text = ""
    interaction_id: str | None = None
    new_environment_id: str | None = None
    usage: UsageInfo | None = None

    async def _run_continue() -> AsyncGenerator[ProgressEvent, None]:
        nonlocal output_text, interaction_id, usage
        continue_prompt = _augment_prompt_with_new_files(prompt, inline_text_blocks)
        async for event in gemini_service.continue_interaction_streaming(
            prompt=continue_prompt,
            environment_id=session.gemini_environment_id,
            previous_interaction_id=session.last_interaction_id,
            images=combined_images,
            agent_name=selected_agent,
        ):
            if event.event_type == "complete":
                output_text = event.message
                interaction_id = event.data.get("interaction_id")
                usage = _usage_from_event_data(event.data)
                event.data["agent_name"] = selected_agent
                event.data["agent_role"] = selected_role
            yield event

    async def _run_create(with_history: bool) -> AsyncGenerator[ProgressEvent, None]:
        nonlocal output_text, interaction_id, new_environment_id, usage
        full_prompt = prompt
        if with_history:
            history = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == session.session_id)
                .order_by(ChatMessage.created_at.asc())
                .limit(20)
                .all()
            )
            if history:
                context = build_context_from_history(history)
                full_prompt = (
                    f"Previous conversation context:\n\n{context}\n\n---\n\n"
                    f"New request: {prompt}"
                )
        async for event in gemini_service.create_interaction_streaming(
            prompt=full_prompt,
            gcs_input_path=gcs_input_path,
            gcs_token=gcs_token,
            images=images,
            agent_name=selected_agent,
        ):
            if event.event_type == "complete":
                output_text = event.message
                new_environment_id = event.data.get("environment_id")
                interaction_id = event.data.get("interaction_id")
                usage = _usage_from_event_data(event.data)
                event.data["agent_name"] = selected_agent
                event.data["agent_role"] = selected_role
            yield event

    expired_fallback = False
    if can_continue:
        try:
            async for event in _run_continue():
                yield event
        except GeminiApiError as e:
            if not _is_expired_interaction_error(e):
                raise
            logger.info(
                "previous_interaction_id %s appears expired (%s); restarting with history",
                session.last_interaction_id,
                e.status_code,
            )
            session.last_interaction_id = None
            expired_fallback = True

    if not can_continue or expired_fallback:
        # Tell the client we are restarting so the UI can show a refresh chip.
        if expired_fallback:
            yield ProgressEvent(
                event_type="status",
                message="Previous interaction expired — starting a fresh sandbox with conversation history.",
                data={"reason": "expired_interaction"},
            )
        async for event in _run_create(with_history=needs_refresh or expired_fallback):
            yield event

    if new_environment_id:
        session.gemini_environment_id = new_environment_id
        session.environment_created_at = datetime.utcnow()
    # Mark refresh consumed regardless of whether we recreated or inlined.
    if needs_refresh:
        session.environment_needs_refresh = False
    if interaction_id:
        session.last_interaction_id = interaction_id
    db.flush()  # Flush changes without closing the session
    db.commit()


async def run_agent_prompt(
    prompt: str,
    session: UserSession,
    db: Session,
    gemini_service,
    gcs_service,
    images: list[dict] | None = None,
    agent_name: str | None = None,
    agent_role: str | None = None,
) -> tuple[str, str | None, UsageInfo | None]:
    """Run a prompt against the session's Gemini environment and update session state.

    Returns (output_text, interaction_id, usage). Drains the underlying SSE stream
    via :func:`drive_agent_interaction`.
    """
    output_text = ""
    interaction_id: str | None = None
    usage: UsageInfo | None = None

    async for event in drive_agent_interaction(
        prompt=prompt,
        session=session,
        db=db,
        gemini_service=gemini_service,
        gcs_service=gcs_service,
        images=images,
        agent_name=agent_name,
        agent_role=agent_role,
    ):
        if event.event_type == "complete":
            output_text = event.message
            interaction_id = event.data.get("interaction_id") or interaction_id
            usage = _usage_from_event_data(event.data) or usage

    return output_text, interaction_id, usage


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
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Send a chat message to the agent (non-streaming)."""
    session = get_owned_session(db, session_id, session_token)

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
        agent_role, agent_name = select_specialist_agent(request.message)
        output_text, interaction_id, usage = await run_agent_prompt(
            prompt=build_data_science_prompt(request.message),
            session=session,
            db=db,
            gemini_service=gemini_service,
            gcs_service=gcs_service,
            images=[img.model_dump() for img in request.images],
            agent_name=agent_name,
            agent_role=agent_role,
        )
        analysis_contract = parse_analysis_contract(output_text)

        # Re-attach session to database session after async operations
        merged_session = db.merge(session)

        # Save assistant message
        assistant_message = ChatMessage(
            message_id=uuid.uuid4(),
            session_id=merged_session.session_id,
            role="assistant",
            content=output_text,
            interaction_id=interaction_id,
        )
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)

        reports, _ = await list_session_reports(
            session=merged_session,
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
            usage=usage,
            analysis_contract=analysis_contract,
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
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Generate a first-pass analyst brief for uploaded session files."""
    session = get_owned_session(db, session_id, session_token)

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
            analysis_contract=parse_analysis_contract(existing_assistant_message.content),
        )

    try:
        agent_role, agent_name = select_specialist_agent("analyst brief", is_brief=True)
        output_text, interaction_id, usage = await run_agent_prompt(
            prompt=ANALYST_BRIEF_PROMPT,
            session=session,
            db=db,
            gemini_service=gemini_service,
            gcs_service=gcs_service,
            agent_name=agent_name,
            agent_role=agent_role,
        )
        analysis_contract = parse_analysis_contract(output_text)

        # Re-attach session to database session after async operations
        merged_session = db.merge(session)

        assistant_message = ChatMessage(
            message_id=uuid.uuid4(),
            session_id=merged_session.session_id,
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
            usage=usage,
            analysis_contract=analysis_contract,
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
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Send a chat message and stream the response via SSE."""
    session = get_owned_session(db, session_id, session_token)

    # Save user message
    user_message = ChatMessage(
        message_id=uuid.uuid4(),
        session_id=session.session_id,
        role="user",
        content=request.message,
    )
    db.add(user_message)
    db.commit()

    images_payload = [img.model_dump() for img in request.images]
    agent_role, agent_name = select_specialist_agent(request.message)

    async def event_generator():
        """Generate SSE events from Gemini streaming response."""
        db_inner = SessionLocal()
        try:
            session_inner = get_owned_session(db_inner, session_id, session_token)
            output_text = ""
            interaction_id: str | None = None
            complete_event_data: dict = {}

            async for event in drive_agent_interaction(
                prompt=build_data_science_prompt(request.message),
                session=session_inner,
                db=db_inner,
                gemini_service=gemini_service,
                gcs_service=gcs_service,
                images=images_payload,
                agent_name=agent_name,
                agent_role=agent_role,
            ):
                if event.event_type == "complete":
                    output_text = event.message
                    interaction_id = (event.data or {}).get("interaction_id") or interaction_id
                    complete_event_data = event.data or {}
                    continue

                payload = json.dumps({
                    "event_type": event.event_type,
                    "message": event.message,
                    "timestamp": event.timestamp.isoformat(),
                    "data": event.data,
                })
                yield f"data: {payload}\n\n"

            reports, harvested_count = await list_session_reports(
                session=session_inner,
                gemini_service=gemini_service,
                gcs_service=gcs_service,
                only_new=True,
            )
            reports = filter_reports_by_mentioned_files(reports, output_text)
            usage = _usage_from_event_data(complete_event_data)
            analysis_contract = parse_analysis_contract(output_text)

            assistant_message = ChatMessage(
                message_id=uuid.uuid4(),
                session_id=session_inner.session_id,
                role="assistant",
                content=output_text,
                interaction_id=interaction_id,
            )
            db_inner.add(assistant_message)
            db_inner.commit()

            complete_payload = {
                "event_type": "complete",
                "message": output_text,
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    **complete_event_data,
                    "interaction_id": interaction_id,
                    "harvested_count": harvested_count,
                    "reports": reports_to_dicts(reports),
                    "usage": usage.model_dump() if usage else None,
                    "analysis_contract": analysis_contract.model_dump(),
                    "agent_name": agent_name,
                    "agent_role": agent_role,
                },
            }
            yield f"data: {json.dumps(complete_payload)}\n\n"

        except Exception as e:
            db_inner.rollback()
            logger.error(f"Error in streaming: {str(e)}")
            error_data = json.dumps({
                "event_type": "error",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            })
            yield f"data: {error_data}\n\n"
        finally:
            db_inner.close()

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
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
):
    """Get chat history for a session."""
    get_owned_session(db, session_id, session_token)

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
            analysis_contract=(
                parse_analysis_contract(m.content) if m.role == "assistant" else None
            ),
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
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """List available reports generated in the session workspace."""
    session = get_owned_session(db, session_id, session_token)

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
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Download a specific report from the workspace.

    Args:
        inline: If True, serves file inline (for chat images). If False, forces download.
    """
    session = get_owned_session(db, session_id, session_token)

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
                    member_filename = os.path.basename(member.name)
                    if (
                        member_filename == filename
                        and is_final_deliverable(member.name, member_filename)
                        and not is_spurious_output_file(member_filename)
                    ):
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
    session_token: str = Depends(session_token_dependency),
    db: Session = Depends(get_db),
    gemini_service=Depends(get_gemini_service),
    gcs_service=Depends(get_gcs_service),
):
    """Harvest the workspace snapshot and save to GCS for persistence."""
    session = get_owned_session(db, session_id, session_token)

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
