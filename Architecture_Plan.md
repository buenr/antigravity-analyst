# Architecture Plan: Gemini Antigravity Data Analyst Agent

This document outlines the architectural blueprint, data flow, security model, and implementation guidelines for developing an enterprise-ready Data Analyst Agent utilizing the **Gemini Antigravity Managed Agent** (`antigravity-preview-05-2026`).

---

## 1. Executive Summary

Traditional LLM integrations struggle with large tabular datasets due to token context window limits, lack of persistent execution state, and inability to run custom code securely. 

This architecture leverages the **Gemini Antigravity Agent**, which executes in an isolated, stateful, and Google-managed remote sandbox (4 CPU cores, 16 GB RAM). The sandbox has pre-installed data science tools (Python 3.12, `pandas`, `numpy`, `matplotlib`, `seaborn`). 

Our application acts as a secure orchestrator/proxy, mapping web-based user sessions to distinct, isolated sandboxes. This allows users to upload Excel/CSV files, run analysis prompts, visualize data, and download generated PDF/HTML reports, all within a conversational framework.

---

## 2. Core Capabilities

The Data Analyst Agent supports the following operations within the isolated sandbox environment:
*   **File Ingestion:** Reads uploaded CSV or Excel binaries directly using standard Python libraries, bypassing direct LLM input limitations.
*   **Programmatic Analysis & Outlier Detection:** Automatically writes and executes Python scripts to filter data, calculate aggregates, and identify anomalies.
*   **Data Cleansing:** Standardizes dates, formats, handles missing values, and allows downloading the modified datasets.
*   **Dynamic Visualizations:** Generates rich graphics (scatter plots, line charts, heatmaps) saved directly as `.png` or `.jpg`.
*   **Formatted Document Generation:** Builds PDF summaries or HTML/Markdown reports in the sandbox workspace.

---

## 3. High-Level System Architecture

The following diagram illustrates the relationship between the client frontend, our orchestration backend, Google Cloud Storage, and the Google-managed Antigravity Sandboxes:
┌────────────────┐ (1) Upload File ┌─────────────────┐
│ ├──────────────────────────>│ │
│ User Browser │ │ Application │
│ (Frontend) │<──────────────────────────┤ Backend │
└───────┬────────┘ (5) Stream Progress │ (Node/Python) │
│ └─┬─────────────┬─┘
│ │ │
│ (6) Download │(2) Save File│ (3) Call Interactions API
│ Reports │ │ with GCS Mount
▼ ▼ ▼
┌───────────────┐ ┌───────────┐ ┌───────────────────────────┐
│ Application │ │ Google │ │ Gemini API Platform │
│ File Storage │ │ Cloud │ │ │
│ (S3 / GCS DB) │ │ Storage │ │ ┌─────────────────────┐ │
└───────▲───────┘ │ (GCS) │ │ │ Antigravity Sandbox │ │
│ └─────┬─────┘ │ │ (4 CPU, 16GB RAM) │ │
│ (4.3) Extract Snapshot & Save │ │ │ │ │
└─────────────────────────────────────┼─────────┼─>│ - runs python code │ │
│ │ │ - writes visual.png │ │
└─────────┼─>│ - reads data.csv │ │
(Mount) │ └─────────────────────┘ │
└───────────────────────────┘
code
Code
---

## 4. Multi-User and Multi-Tenant Isolation

To ensure that User A cannot access User B's files, computational variables, or historical contexts, isolation is enforced across three planes:

### 4.1. The Control Plane (Database Mapping)
The application backend acts as a strict proxy. No end-user communicates with the Gemini API directly. A relational table tracks user-to-environment associations:

```sql
CREATE TABLE user_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    gemini_environment_id VARCHAR(255) NULL, -- Stores Google's remote env ID
    last_interaction_id VARCHAR(255) NULL,   -- Keeps conversational continuity
    gcs_folder_path VARCHAR(512) NOT NULL,    -- Isolated folder for inputs/outputs
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
4.2. The Data Plane (Storage Isolation)
Uploads are saved in user-specific, logically isolated subfolders on Google Cloud Storage (GCS).
Path format: gs://[app-bucket]/tenants/[tenant_id]/users/[user_id]/sessions/[session_id]/input/
The sandbox is only configured to mount this specific folder, preventing cross-directory directory traversal.
4.3. The Compute Plane (Sandbox Boundaries)
Every user session is allocated a separate environment instance by the Gemini API. There is no sharing of runtime environments, execution memory, or local disk space across different user sessions.
5. End-to-End Execution Lifecycles
Phase 1: Ingestion & Sandbox Setup
When a user initiates a session and uploads a file:
The frontend sends the raw file and initial prompt to the backend.
The backend writes the file to the user's isolated GCS path.
The backend calls the Gemini Interactions API with environment.type = "remote" and the specific GCS mount target:
code
JSON
POST https://generativelanguage.googleapis.com/v1beta/interactions
{
  "agent": "antigravity-preview-05-2026",
  "input": "Read the uploaded CSV, generate a summary of outliers, and write a PDF report to '/workspace/outliers_report.pdf'.",
  "environment": {
    "type": "remote",
    "sources": [
      {
        "type": "gcs",
        "source": "gs://my-app-bucket/tenants/t1/users/u1/sessions/s1/input/",
        "target": "/workspace/data"
      }
    ],
    "network": {
      "allowlist": [
        { 
          "domain": "storage.googleapis.com", 
          "transform": { "Authorization": "Bearer <SHORT_LIVED_GCS_TOKEN>" } 
        }
      ]
    }
  }
}
The API returns the newly created environment_id and the first interaction_id. The backend saves these to user_sessions.
Phase 2: Execution and Progress Streaming
Because the agent runs in a loop (write script -> execute -> read terminal -> debug), the run can take up to 60 seconds or more.
Implementation Requirement: The backend should initiate the API call with stream=true.
The backend processes the incoming streaming chunks (specifically filtering for terminal logs and execution traces) and forwards them to the frontend via WebSockets or Server-Sent Events (SSE) to update the UI (e.g., "Generating visualization... done").
Phase 3: Harvesting Output Reports
The remote sandbox does not support direct single-file streaming downloads. Instead, outputs must be retrieved as a workspace snapshot:
Once the interaction completes, the backend calls the Gemini Files API:
code
Code
GET https://generativelanguage.googleapis.com/v1beta/files/environment-{environment_id}:download?alt=media
The API returns a .tar snapshot of /workspace.
The backend extracts the .tar in memory (or a temp folder), retrieves the generated .pdf, .png, or clean .csv files, saves them to our secure storage, and returns the download links to the frontend UI.
Phase 4: Chat Continuation (Multi-Turn)
When the user submits a follow-up question:
The backend fetches the gemini_environment_id and last_interaction_id from the database.
The backend calls the Interactions API, pointing to the existing environment to maintain session history:
code
JSON
POST https://generativelanguage.googleapis.com/v1beta/interactions
{
  "agent": "antigravity-preview-05-2026",
  "environment": "env_abc123_retrieved_from_db",
  "previous_interaction_id": "interaction_xyz456_retrieved_from_db",
  "input": "Now change the color of the plot to blue and regenerate the PDF."
}
6. Engineering Requirements & Constraints
Developers must build defensive mechanisms to handle the unique constraints of the Antigravity API:
Cost Control & Token Usage: Autonomous loops can consume a high volume of tokens. Since heavy executions can cost $0.70 to $3.25+ per run depending on complexity, the system should implement user rate limits (e.g., maximum 10 prompts/day per free tier user).
Startup Latency: Provisioning a cold remote sandbox environment can take several seconds. The frontend should display a structured loading sequence while initializing the sandbox.
Sandbox Expiry: Environments go idle after 15 minutes of inactivity, saving an offline snapshot. They are deleted entirely after 7 days. If a user interacts with a 3-day-old session, expect an extended load time of several seconds as the snapshot is restored from cold state.
Secure Downscoping: Do not pass global administrative GCP service account keys in the network.allowlist headers. Always use GCP's token broker pattern to generate short-lived, downscoped GCS authorization tokens restricted specifically to the folder matching session_id.