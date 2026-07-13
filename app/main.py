"""FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"

app = FastAPI(title="Minimal Agent Runtime")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def read_index() -> FileResponse:
    """Serve the temporary web entry page."""
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    """Report that the service is available."""
    return {"status": "ok", "service": "minimal-agent-runtime"}
