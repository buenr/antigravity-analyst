"""Register a managed `data-analyst` agent on the Gemini Interactions API.

Two modes:

* **Prewarmed fork (default).** Spin up a fresh Antigravity sandbox with the
  ``.agents/`` skills mounted, run ``bash .agents/bootstrap_packages.sh`` to
  pip-install the requested tiers, then fork that environment via
  ``POST /v1beta/agents`` so each invocation gets a hot sandbox without paying
  the ~30s install cost.

* **Sources-only (--skip-prewarm).** Register the agent with the ``.agents/``
  sources alone — every invocation still pip-installs Tier 1 on first use, but
  registration is free and instant.

The script is idempotent on agent ID: if an agent with the same ID already
exists, you can pass ``--replace`` to delete and recreate it.

Usage::

    cd backend
    .venv/bin/python -m scripts.create_data_analyst_agent --prewarm-tiers 1,2
    .venv/bin/python -m scripts.create_data_analyst_agent --skip-prewarm
    .venv/bin/python -m scripts.create_data_analyst_agent --dry-run

Once registered, set ``GEMINI_AGENT_NAME=data-analyst`` in ``backend/.env`` and
restart the backend; the chat router will start invoking the managed agent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

# Ensure we can import the app package when run as a module from backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.services.gemini_service import _load_agent_sources  # noqa: E402


BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
API_REVISION = "2026-05-20"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
        "Api-Revision": API_REVISION,
    }


def _bootstrap_prompt(tiers: list[str]) -> str:
    """Return a sandbox bootstrap prompt that installs the requested tiers."""
    tier_args = " ".join(tiers) if tiers else "1"
    return (
        "You are bootstrapping a managed sandbox. Run the install script and "
        "verify the imports, but do not produce any deliverables yet.\n\n"
        f"```bash\nfor tier in {tier_args}; do bash .agents/bootstrap_packages.sh $tier; done\n```\n\n"
        "After installation, run `python -c \"import scipy, sklearn, matplotlib, "
        "openpyxl; print('tier1 ok')\"` and reply with exactly: BOOTSTRAP OK."
    )


def _prewarm_environment(
    *,
    api_key: str,
    base_agent: str,
    sources: list[dict],
    tiers: list[str],
    timeout_seconds: float,
) -> str:
    """Provision a sandbox, run the bootstrap, return its environment_id."""
    payload = {
        "agent": base_agent,
        "input": _bootstrap_prompt(tiers),
        "environment": {
            "type": "remote",
            "sources": sources,
        },
    }

    print(f"[prewarm] POST /interactions  (this may take {int(timeout_seconds)}s)")
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(
            f"{BASE_URL}/interactions",
            headers=_headers(api_key),
            json=payload,
        )
        if response.status_code >= 400:
            raise SystemExit(
                f"[prewarm] HTTP {response.status_code}: {response.text}"
            )
        data = response.json()

    env_id = (
        data.get("environment_id")
        or (data.get("environment") or {}).get("id")
        or (data.get("interaction") or {}).get("environment_id")
    )
    if not env_id:
        raise SystemExit(
            f"[prewarm] Could not find environment_id in response: {json.dumps(data)[:500]}"
        )
    print(f"[prewarm] sandbox ready: environment_id={env_id}")
    return env_id


def _delete_agent_if_exists(api_key: str, agent_id: str) -> bool:
    """Delete a managed agent if present. Returns True if deletion happened."""
    with httpx.Client(timeout=30.0) as client:
        response = client.delete(
            f"{BASE_URL}/agents/{agent_id}",
            headers=_headers(api_key),
        )
        if response.status_code in (200, 204):
            print(f"[replace] deleted existing agent '{agent_id}'")
            return True
        if response.status_code == 404:
            return False
        raise SystemExit(
            f"[replace] DELETE failed HTTP {response.status_code}: {response.text}"
        )


def _create_agent(
    *,
    api_key: str,
    agent_id: str,
    description: str,
    base_agent: str,
    system_instruction: str,
    base_environment,
    dry_run: bool,
) -> None:
    payload = {
        "id": agent_id,
        "description": description,
        "base_agent": base_agent,
        "system_instruction": system_instruction,
        "base_environment": base_environment,
    }

    if dry_run:
        print("[dry-run] POST /agents payload:")
        # Truncate large inline contents for readability.
        scrub = json.loads(json.dumps(payload))
        env = scrub.get("base_environment")
        if isinstance(env, dict):
            for src in env.get("sources", []):
                if isinstance(src, dict) and "content" in src:
                    src["content"] = f"<{len(src['content'])} bytes>"
        print(json.dumps(scrub, indent=2))
        return

    print(f"[create] POST /agents  id={agent_id}")
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{BASE_URL}/agents",
            headers=_headers(api_key),
            json=payload,
        )
        if response.status_code >= 400:
            raise SystemExit(
                f"[create] HTTP {response.status_code}: {response.text}"
            )
        result = response.json()
    print(f"[create] success: id={result.get('id', agent_id)}")
    print()
    print("Next steps:")
    print(f"  1. Set GEMINI_AGENT_NAME={agent_id} in backend/.env")
    print("  2. Restart the backend (uvicorn). New chats will use the managed agent.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-id",
        default="data-analyst",
        help="Managed agent identifier (default: %(default)s).",
    )
    parser.add_argument(
        "--description",
        default="Rigorous data scientist/analyst on Antigravity (Tier 1+2 pre-installed).",
        help="Human-readable agent description.",
    )
    parser.add_argument(
        "--base-agent",
        default=None,
        help="Base agent ID. Defaults to GEMINI_AGENT_NAME in settings.",
    )
    parser.add_argument(
        "--prewarm-tiers",
        default="1,2",
        help="Comma-separated tier list to pre-install (default: %(default)s). "
             "Set to empty (--prewarm-tiers='') to skip the prewarm interaction.",
    )
    parser.add_argument(
        "--skip-prewarm",
        action="store_true",
        help="Register from inline sources only; no sandbox prewarm.",
    )
    parser.add_argument(
        "--prewarm-timeout",
        type=float,
        default=600.0,
        help="Seconds to wait for the prewarm interaction (default: %(default)s).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete an existing agent with this ID before recreating.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request payload without calling the API.",
    )
    args = parser.parse_args()

    settings = get_settings()
    api_key = settings.gemini_api_key
    base_agent = args.base_agent or settings.gemini_agent_name
    system_instruction = settings.gemini_system_instruction

    if not api_key and not args.dry_run:
        raise SystemExit("GEMINI_API_KEY is not configured.")

    sources = _load_agent_sources()
    if not sources:
        print(
            "[warn] No .agents/ sources discovered. The managed agent will not "
            "have AGENTS.md/skills bundled — registration will still work but "
            "the agent will need them remounted at interaction time.",
            file=sys.stderr,
        )

    if args.replace and not args.dry_run:
        _delete_agent_if_exists(api_key, args.agent_id)

    if args.skip_prewarm or not args.prewarm_tiers.strip():
        base_environment = {"type": "remote", "sources": sources}
        _create_agent(
            api_key=api_key,
            agent_id=args.agent_id,
            description=args.description,
            base_agent=base_agent,
            system_instruction=system_instruction,
            base_environment=base_environment,
            dry_run=args.dry_run,
        )
        return 0

    tiers = [t.strip() for t in args.prewarm_tiers.split(",") if t.strip()]
    if args.dry_run:
        print(f"[dry-run] Would prewarm sandbox with tiers={tiers}, then fork.")
        _create_agent(
            api_key=api_key,
            agent_id=args.agent_id,
            description=args.description,
            base_agent=base_agent,
            system_instruction=system_instruction,
            base_environment="<env_id_from_prewarm>",
            dry_run=True,
        )
        return 0

    env_id = _prewarm_environment(
        api_key=api_key,
        base_agent=base_agent,
        sources=sources,
        tiers=tiers,
        timeout_seconds=args.prewarm_timeout,
    )

    # Brief sleep so the env reaches an idle/snapshotable state before fork.
    time.sleep(2.0)

    _create_agent(
        api_key=api_key,
        agent_id=args.agent_id,
        description=args.description,
        base_agent=base_agent,
        system_instruction=system_instruction,
        base_environment=env_id,
        dry_run=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
