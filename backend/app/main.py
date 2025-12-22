from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.ingest import router as ingest_router
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="TwinMind Second Brain prototype project")

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(ingest_router)
app.include_router(chat_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).resolve().parent / "static"
frontend_index = Path(__file__).resolve().parents[2] / "frontend" / "app" / "index.html"

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", include_in_schema=False)
def index():
    if static_dir.exists() and (static_dir / "index.html").exists():
        return FileResponse(static_dir / "index.html")
    if frontend_index.exists():
        return FileResponse(frontend_index)
    raise HTTPException(status_code=404, detail="UI not found")
