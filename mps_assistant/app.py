from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status as http_status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .config import get_settings
from .database import Database
from .schemas import (
    AnalyticsKpiItem,
    AnalyticsResponse,
    AnalyticsTrendItem,
    ChatRequest,
    ChatResponse,
    ConversationResumeResponse,
    FeedbackRequest,
    FeedbackResponse,
    GapSummaryResponse,
    HandoffRequest,
    HandoffResponse,
    OnboardingActionResponse,
    OnboardingOtpRequest,
    OnboardingOtpVerificationRequest,
    OnboardingPricingRequest,
    OnboardingSubmissionRequest,
    RefreshResponse,
    StatusResponse,
    UploadResponse,
)
from .services.knowledge_base import KnowledgeBaseService
from .services.onboarding import OnboardingService

settings = get_settings()
database = Database(settings.database_path, journal_mode=settings.sqlite_journal_mode)
knowledge_base = KnowledgeBaseService(settings, database)
onboarding = OnboardingService(settings)
knowledge_base.initialize()
scheduler = BackgroundScheduler(timezone=settings.refresh_timezone)


@asynccontextmanager
async def lifespan(_: FastAPI):
    knowledge_base.initialize()
    if settings.enable_scheduler and not scheduler.running:
        scheduler.add_job(
            knowledge_base.start_refresh_background,
            "cron",
            id="daily_kb_refresh",
            replace_existing=True,
            hour=settings.refresh_hour_local,
            minute=settings.refresh_minute_local,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        scheduler.start()
    if settings.auto_refresh_on_startup:
        knowledge_base.start_refresh_background()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.admin_session_secret)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


def _is_admin_authenticated(request: Request) -> bool:
    return bool(request.session.get("is_admin_authenticated"))


def _require_admin(request: Request) -> None:
    if _is_admin_authenticated(request):
        return
    raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "seed_url": settings.seed_url,
            "status": knowledge_base.status(),
        },
    )


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request) -> HTMLResponse:
    if _is_admin_authenticated(request):
        return RedirectResponse(url="/admin/dashboard", status_code=http_status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "error": "",
        },
    )


@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login_submit(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
) -> HTMLResponse:
    if username == settings.admin_dashboard_username and password == settings.admin_dashboard_password:
        request.session["is_admin_authenticated"] = True
        return RedirectResponse(url="/admin/dashboard", status_code=http_status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "error": "Invalid username or password.",
        },
        status_code=http_status.HTTP_401_UNAUTHORIZED,
    )


@app.post("/admin/logout")
async def admin_logout(request: Request) -> RedirectResponse:
    request.session.pop("is_admin_authenticated", None)
    return RedirectResponse(url="/admin/login", status_code=http_status.HTTP_303_SEE_OTHER)


@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request) -> HTMLResponse:
    if not _is_admin_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=http_status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request,
        "admin_dashboard.html",
        {
            "request": request,
            "app_name": settings.app_name,
        },
    )


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        response = knowledge_base.answer_question(request.question, request.messages, request.session_id)

        if request.session_id:
            conversation_id = database.create_or_get_conversation(request.session_id)
            turn_number = database.get_conversation_turn_count(conversation_id) + 1
            database.save_conversation_turn(
                conversation_id=conversation_id,
                turn_number=turn_number,
                user_message=request.question,
                assistant_response=response.direct_answer,
                response_json=response.model_dump_json(),
            )

        return response
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/conversations/{session_id}", response_model=ConversationResumeResponse)
async def get_conversation(session_id: str, limit: int = 60) -> ConversationResumeResponse:
    conversation_id = database.create_or_get_conversation(session_id)
    turns = database.get_conversation_history(conversation_id, limit=max(1, min(limit, 200)))

    messages = []
    for turn in turns:
        user_message = str(turn.get("user_message") or "").strip()
        assistant_response = str(turn.get("assistant_response") or "").strip()
        response_json = turn.get("response_json")

        if user_message:
            messages.append({"role": "user", "content": user_message})

        parsed_response = None
        if isinstance(response_json, str) and response_json.strip():
            try:
                import json

                parsed_response = json.loads(response_json)
            except Exception:
                parsed_response = None

        assistant_payload = {
            "role": "assistant",
            "content": assistant_response,
        }
        if parsed_response is not None:
            assistant_payload["response"] = parsed_response
        messages.append(assistant_payload)

    return ConversationResumeResponse(
        session_id=session_id,
        turn_count=len(turns),
        messages=messages,
    )


@app.post("/api/feedback", response_model=FeedbackResponse)
async def feedback(request: FeedbackRequest) -> FeedbackResponse:
    if not request.answer_id.strip():
        raise HTTPException(status_code=400, detail="answer_id is required")

    database.upsert_answer_feedback(
        answer_id=request.answer_id,
        session_id=request.session_id,
        question=request.question,
        answer=request.answer,
        helpful=request.helpful,
        comment=request.comment,
    )
    return FeedbackResponse(ok=True, message="Feedback recorded")


@app.post("/api/handoff", response_model=HandoffResponse)
async def handoff(request: HandoffRequest) -> HandoffResponse:
    session_id = request.session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    conversation = list(request.conversation or [])
    if not conversation:
        conversation_id = database.create_or_get_conversation(session_id)
        turns = database.get_conversation_history(conversation_id, limit=80)
        for turn in turns:
            user_message = str(turn.get("user_message") or "").strip()
            assistant_response = str(turn.get("assistant_response") or "").strip()
            if user_message:
                conversation.append({"role": "user", "content": user_message})
            if assistant_response:
                conversation.append({"role": "assistant", "content": assistant_response})

    ticket_id = database.create_handoff_request(
        session_id=session_id,
        answer_id=request.answer_id,
        reason=request.reason,
        question=request.question,
        answer=request.answer,
        confidence_score=request.confidence_score,
        confidence_level=request.confidence_level,
        conversation=conversation,
        metadata=request.metadata,
    )
    return HandoffResponse(
        ok=True,
        ticket_id=ticket_id,
        message="Handoff request captured with full session context.",
    )


@app.get("/api/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    return StatusResponse(**knowledge_base.status())


@app.get("/api/analytics", response_model=AnalyticsResponse)
async def analytics(request: Request) -> AnalyticsResponse:
    _require_admin(request)
    status_payload = knowledge_base.status()
    summary = database.analytics_summary()

    return AnalyticsResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        refresh_in_progress=bool(status_payload["refresh_in_progress"]),
        last_refresh_completed_at=status_payload.get("last_refresh_completed_at"),
        kpis=[
            AnalyticsKpiItem(label="Knowledge Base", value=f"{summary['source_count']} sources", delta=f"{summary['chunk_count']} chunks"),
            AnalyticsKpiItem(label="Conversations", value=str(summary["conversation_count"]), delta=f"{summary['message_count']} total turns"),
            AnalyticsKpiItem(label="Helpful feedback", value=f"{summary['helpful_rate']}%", delta=f"{summary['feedback_total']} votes", tone="good" if summary["helpful_rate"] >= 70 else "warn" if summary["feedback_total"] else "neutral"),
            AnalyticsKpiItem(label="Human handoffs", value=str(summary["handoff_total"]), delta=f"{summary['handoff_queued']} queued", tone="warn" if summary["handoff_queued"] else "neutral"),
            AnalyticsKpiItem(label="Gap events", value=str(summary["total_gap_events"]), delta=f"{summary['unresolved_gap_events']} unresolved", tone="warn" if summary["unresolved_gap_events"] else "neutral"),
        ],
        recent_activity=[AnalyticsTrendItem(**item) for item in summary["recent_activity"]],
        top_gap_topics=summary["top_gap_topics"],
    )


@app.get("/api/gaps", response_model=GapSummaryResponse)
async def gaps(request: Request, top: int = 10) -> GapSummaryResponse:
    _require_admin(request)
    summary = database.kb_gap_summary(top_n=top)
    return GapSummaryResponse(**summary)


@app.get("/api/onboarding/config")
async def onboarding_config() -> dict:
    return onboarding.get_config()


@app.post("/api/onboarding/send-otp", response_model=OnboardingActionResponse)
async def onboarding_send_otp(request: OnboardingOtpRequest) -> OnboardingActionResponse:
    try:
        payload = onboarding.send_otp(request.email)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return OnboardingActionResponse(ok=True, message=payload.get("message", "Verification code sent."), payload=payload)


@app.post("/api/onboarding/verify-otp", response_model=OnboardingActionResponse)
async def onboarding_verify_otp(request: OnboardingOtpVerificationRequest) -> OnboardingActionResponse:
    try:
        payload = onboarding.verify_otp(request.email, request.code)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    status_code = 200 if payload.get("verified") else 400
    if not payload.get("verified"):
        raise HTTPException(status_code=status_code, detail=payload.get("message", "Verification failed."))
    return OnboardingActionResponse(ok=True, message=payload.get("message", "Email verified."), payload=payload)


@app.get("/api/onboarding/rate-card")
async def onboarding_rate_card() -> dict:
    try:
        return onboarding.get_rate_card()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/onboarding/quote", response_model=OnboardingActionResponse)
async def onboarding_quote(request: OnboardingPricingRequest) -> OnboardingActionResponse:
    try:
        payload = onboarding.quote(request.gp_category, request.gp_hours_band, request.gp_intrapartum_basis)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return OnboardingActionResponse(ok=True, message="Live quote loaded.", payload=payload)


@app.post("/api/onboarding/submit", response_model=OnboardingActionResponse)
async def onboarding_submit(request: OnboardingSubmissionRequest) -> OnboardingActionResponse:
    try:
        payload = onboarding.submit_application(request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return OnboardingActionResponse(ok=True, message=payload.get("message", "Application submitted."), payload=payload)


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
