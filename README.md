# Minimal Agent Runtime

## Goal

Build a minimal, self-managed Agent runtime step by step. Future milestones
will implement the runtime, tool loop, tool registry, context management, and
OpenAI-compatible LLM client without using an Agent framework.

## Technology stack

- Python 3.11
- FastAPI and Uvicorn
- Native HTML, CSS, and JavaScript
- SQLite (planned for sessions, messages, todos, and traces)
- pytest

## Current status

This initialization milestone provides a FastAPI application, a health endpoint,
and a static placeholder page. It intentionally does not implement Agent logic,
tools, database tables, or LLM requests.

## Run locally (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 in a browser. The health check is available at
http://127.0.0.1:8000/api/health.
