from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .database import Database
from .schemas import ChatRequest, ChatResponse, RefreshResponse, StatusResponse, UploadResponse
from .services.knowledge_base import KnowledgeBaseService

settings = get_settings()
database = Database(settings.database_path, journal_mode=settings.sqlite_journal_mode)
knowledge_base = KnowledgeBaseService(settings, database)
knowledge_base.initialize()
scheduler = BackgroundScheduler(timezone="Africa/Johannesburg")


@asynccontextmanager
async def lifespan(_: FastAPI):
    knowledge_base.initialize()
    if settings.enable_scheduler and not scheduler.running:
        scheduler.add_job(knowledge_base.start_refresh_background, "interval", hours=settings.refresh_interval_hours)
        scheduler.start()
    if settings.auto_refresh_on_startup and not knowledge_base.has_content():
        knowledge_base.start_refresh_background()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "seed_url": settings.seed_url,
            "status": knowledge_base.status(),
        },
    )


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        return knowledge_base.answer_question(request.question)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    return StatusResponse(**knowledge_base.status())


@app.post("/api/refresh", response_model=RefreshResponse)
async def refresh() -> RefreshResponse:
    started = knowledge_base.start_refresh_background()
    if started:
        return RefreshResponse(started=True, message="Website refresh started.")
    return RefreshResponse(started=False, message="A refresh is already in progress.")


@app.post("/api/upload", response_model=UploadResponse)
async def upload(files: List[UploadFile] = File(...)) -> UploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    ingested_source_keys = []
    for upload_file in files:
        suffix = Path(upload_file.filename or "").suffix.lower()
        if suffix not in settings.resource_extensions:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix or 'unknown'}")

        temp_path = settings.upload_dir / f"tmp-{upload_file.filename}"
        temp_path.write_bytes(await upload_file.read())
        source_key = knowledge_base.ingest_upload(temp_path, upload_file.filename or "uploaded-file")
        temp_path.unlink(missing_ok=True)
        ingested_source_keys.append(source_key)

    return UploadResponse(ingested_files=len(ingested_source_keys), source_keys=ingested_source_keys)
