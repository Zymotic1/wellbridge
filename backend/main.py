"""
WellBridge FastAPI application entry point.

Startup sequence:
  1. Load settings (fails fast if env vars missing)
  2. Compile the LangGraph agent graph (done once, reused per request)
  3. Start APScheduler — weekly data sync jobs:
       Sun 02:00 UTC — Epic SMART endpoint directory  (open.epic.com)
       Sun 03:00 UTC — CMS Doctors & Clinicians       (data.cms.gov)
     Each job checks whether the source has been modified since the last
     run; if not, it logs "skipped" and exits immediately (no download).
  4. Register middleware (CORS, tenant context)
  5. Mount routers
"""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from agent.graph import compile_graph
from routers import chat, records, ocr, sharing, appointments, epic, users, speech

log      = logging.getLogger("wellbridge")
settings = get_settings()


# ── Scheduled jobs ────────────────────────────────────────────────────────────

async def _job_sync_epic():
    """Weekly Epic SMART endpoint directory sync (Sun 02:00 UTC)."""
    from services.epic_endpoint_sync import run_sync
    log.info("scheduler: starting Epic endpoint sync")
    result = await run_sync()
    log.info("scheduler: Epic endpoint sync → %s", result)


async def _job_sync_cms():
    """Weekly CMS Doctors & Clinicians sync (Sun 03:00 UTC)."""
    from services.cms_sync import run_sync
    log.info("scheduler: starting CMS DAC sync")
    result = await run_sync()
    log.info("scheduler: CMS DAC sync → %s", result)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Compile LangGraph state machine
    app.state.agent_graph = compile_graph()

    # 2. Start scheduler
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _job_sync_epic,
        CronTrigger(day_of_week="sun", hour=2, minute=0),
        id="sync_epic",
        name="Epic endpoint directory sync",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_sync_cms,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="sync_cms",
        name="CMS Doctors & Clinicians sync",
        replace_existing=True,
    )
    scheduler.start()
    log.info("scheduler: started — CMS sync Sun 03:00 UTC, Epic sync Sun 02:00 UTC")

    app.state.scheduler = scheduler

    yield

    # Shutdown
    scheduler.shutdown(wait=False)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="WellBridge API",
    version="0.1.0",
    description="Safety-first agentic medical record assistant",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────

origins = [
    "http://localhost:3000",
    "https://app.wellbridge.health",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(chat.router)
app.include_router(records.router)
app.include_router(appointments.router)
app.include_router(ocr.router)
app.include_router(sharing.router)
app.include_router(epic.router)
app.include_router(users.router)
app.include_router(speech.router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "wellbridge-backend"}


# ── Admin: manual sync triggers ───────────────────────────────────────────────
# Protected by a static ADMIN_SECRET env var.  Never expose to the frontend.

def _require_admin(request: Request):
    secret = getattr(settings, "admin_secret", None)
    if not secret:
        raise HTTPException(status_code=501, detail="Admin endpoints not configured.")
    token = (request.headers.get("X-Admin-Secret") or "").strip()
    if token != secret:
        raise HTTPException(status_code=403, detail="Forbidden.")


@app.post("/admin/sync/cms", tags=["admin"], status_code=status.HTTP_202_ACCEPTED)
async def trigger_cms_sync(request: Request, force: bool = False):
    """
    Manually trigger a CMS Doctors & Clinicians diff-sync.

    Header:  X-Admin-Secret: <ADMIN_SECRET>
    Param:   ?force=true  skips the "already up to date" check.
    """
    _require_admin(request)
    from services.cms_sync import run_sync
    result = await run_sync(force=force)
    return result


@app.post("/admin/sync/epic", tags=["admin"], status_code=status.HTTP_202_ACCEPTED)
async def trigger_epic_sync(request: Request, force: bool = False):
    """
    Manually trigger an Epic SMART endpoint directory sync.

    Header:  X-Admin-Secret: <ADMIN_SECRET>
    """
    _require_admin(request)
    from services.epic_endpoint_sync import run_sync
    result = await run_sync(force=force)
    return result


@app.get("/admin/sync/status", tags=["admin"])
async def sync_status(request: Request):
    """Return the last 10 sync log entries for both datasets."""
    _require_admin(request)
    from services.supabase_client import get_admin_client
    db = get_admin_client()
    result = (
        db.table("cms_sync_log")
        .select("dataset, status, started_at, finished_at, rows_upserted, rows_deleted, error")
        .order("started_at", desc=True)
        .limit(10)
        .execute()
    )
    return {"logs": result.data or []}


# ── DEBUG — remove before production ─────────────────────────────────────────

@app.get("/debug/token")
async def debug_token(request: Request):
    import jwt as pyjwt
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {"error": "No Bearer token found"}
    token = auth_header.removeprefix("Bearer ")
    try:
        payload = pyjwt.decode(token, options={"verify_signature": False})
        return {"claims": payload}
    except Exception as exc:
        return {"error": str(exc)}
