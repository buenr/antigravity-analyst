# Antigravity Data Analyst

AI-powered data analysis agent using the Gemini Antigravity Managed Agent. Upload CSV/Excel files, ask questions about your data, generate visualizations, and download reports.

## Architecture

- **Backend**: FastAPI (Python) with SQLite database
- **Frontend**: React + Vite + Tailwind CSS
- **AI Agent**: Gemini Antigravity (`antigravity-preview-05-2026`) running in a Google-managed sandbox
- **Storage**: Google Cloud Storage for file persistence

## Prerequisites

- Python 3.11+
- Node.js 18+
- Google Cloud Project with:
  - GCS bucket created
  - Gemini API access
  - Service account or Application Default Credentials

## Setup

### 1. Backend Configuration

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
```

Required environment variables:
- `GCP_PROJECT_ID` - Your Google Cloud project ID
- `GCS_BUCKET_NAME` - Your GCS bucket name
- `GEMINI_API_KEY` - Your Gemini API key
- `GOOGLE_APPLICATION_CREDENTIALS` (optional) - Path to service account JSON

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install
```

## Running Locally

### Start Backend

```bash
cd backend

# Activate virtual environment if not already
source venv/bin/activate

# Start server
uvicorn app.main:app --reload --port 8000
```

The API will be available at http://localhost:8000

### Start Frontend

```bash
cd frontend

# Start development server
npm run dev
```

The app will be available at http://localhost:5173

## Usage

1. Open http://localhost:5173
2. Click "Create New Session"
3. Upload CSV or Excel files (max 50MB)
4. Switch to "Chat" tab
5. Ask questions about your data, e.g.:
   - "Summarize the data and find outliers"
   - "Create a scatter plot of column A vs column B"
   - "Generate a PDF report with key statistics"
6. View generated reports in the "Reports" tab

## API Endpoints

### Sessions
- `POST /sessions/` - Create new session
- `GET /sessions/{session_id}` - Get session details
- `DELETE /sessions/{session_id}` - Delete session

### Files
- `POST /files/upload/{session_id}` - Upload file
- `GET /files/{session_id}` - List session files
- `GET /files/download/{file_id}` - Download file

### Chat
- `POST /chat/{session_id}` - Send message (non-streaming)
- `POST /chat/{session_id}/stream` - Send message (SSE streaming)
- `GET /chat/{session_id}/history` - Get chat history
- `GET /chat/{session_id}/reports` - List generated reports
- `GET /chat/{session_id}/reports/{filename}` - Download report

## Project Structure

```
antigravity-agent/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Environment settings
│   │   ├── database.py          # SQLite setup
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── schemas.py           # Pydantic schemas
│   │   ├── routers/
│   │   │   ├── sessions.py      # Session management
│   │   │   ├── files.py         # File upload/download
│   │   │   └── chat.py          # Gemini interactions
│   │   └── services/
│   │       ├── gcs_service.py   # GCS operations
│   │       └── gemini_service.py # Gemini API client
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── App.jsx
│   ├── package.json
│   └── vite.config.js
└── README.md
```

## Notes

- Sessions and files are stored in isolated GCS paths: `gs://{bucket}/tenants/{tenant}/users/{user}/sessions/{session}/`
- The Gemini sandbox has 4 CPU cores and 16GB RAM
- Environments expire after 15 minutes of inactivity
- Maximum file upload size: 50MB

## License

MIT
