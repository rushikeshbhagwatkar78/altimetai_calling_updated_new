from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models import (
    CallRecord,
    Callback,
    Campaign,
    CampaignLead,
    KnowledgeDocument,
    Lead,
    LeadActivity,
    LeadNote,
    Property,
    SiteVisit,
    User,
    AgentScript,
    AgentConfig,
)
from services.domain_registry import (
    DOMAIN_PRESETS,
    VOICE_METADATA,
    get_domain_preset,
    list_supported_domains,
    resolve_voice_gender,
    render_gender_text,
)
from agent import build_system_prompt
from db.session import get_db, get_db_session, hash_password, init_db, verify_password
from services.booking_service import book_site_visit, get_callbacks_list, get_site_visits_list, schedule_callback
from services.call_service import (
    LIVE_CALL_REGISTRY,
    get_live_call_status,
    initiate_outbound_call,
    terminate_call,
)
from services.campaign_dialer import (
    pause_campaign_dialer_task,
    start_campaign_dialer_task,
    stop_campaign_dialer_task,
)
from services.lead_service import (
    add_lead_note,
    create_or_update_lead,
    get_lead_detail,
    get_leads_filtered,
    import_leads_from_csv,
    mask_phone_number,
    normalize_phone_e164,
)
from services.rag_service import (
    extract_text_from_file,
    ingest_document_file,
    search_knowledge_chunks,
    search_properties_hybrid,
)

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("crm_api")

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "nagpur-estates-secret-crm-key-2025")
agent_process = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Nagpur Estates CRM Backend...")
    init_db()
    # On startup: evict any stale LIVE_CALL_REGISTRY entries whose calls are
    # already completed/failed in the DB (happens after unclean server restarts).
    _TERMINAL_STATUSES = {"completed", "failed", "cancelled", "busy", "no_answer", "ended_in_middle", "call_ended"}
    stale = []
    with get_db_session() as _db:
        for cid in list(LIVE_CALL_REGISTRY.keys()):
            cr = _db.query(CallRecord).filter(CallRecord.call_id == cid).first()
            if cr and cr.status in _TERMINAL_STATUSES:
                stale.append(cid)
    for cid in stale:
        LIVE_CALL_REGISTRY.pop(cid, None)
        logger.warning(f"STARTUP_STALE_EVICTED | call_id={cid}")
    if stale:
        logger.info(f"STARTUP_STALE_CLEANUP | evicted={len(stale)} stale registry entries")
    logger.info("CRM Backend ready.")
    yield
    logger.info("CRM Backend shutting down.")



app = FastAPI(
    title="Nagpur Estates AI Voice CRM",
    version="3.0.0",
    description="Full-stack Real Estate AI CRM with Gemini 3.1 Live Native Audio, LiveKit SIP, and Hybrid RAG.",
    lifespan=lifespan,
)

cors_origins_env = os.getenv("CORS_ORIGINS", "*")
cors_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth Token Utilities & Dependencies
# ---------------------------------------------------------------------------
def create_auth_token(user_id: str, email: str, role: str) -> str:
    """Generate signed HMAC-SHA256 bearer token with 7-day expiration."""
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "exp": int(time.time()) + (86400 * 7),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
    sig = hmac.new(AUTH_SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def decode_auth_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode signed authentication token."""
    try:
        if not token or "." not in token:
            return None
        payload_b64, sig = token.split(".", 1)
        expected_sig = hmac.new(AUTH_SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        # Add base64 padding
        padded_b64 = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_data = json.loads(base64.urlsafe_b64decode(padded_b64.encode("utf-8")).decode("utf-8"))
        if payload_data.get("exp", 0) < time.time():
            return None
        return payload_data
    except Exception:
        return None


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
    auth_token: Optional[str] = Cookie(default=None),
    token: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency to authenticate and guard CRM endpoints."""
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.split(" ", 1)[1].strip()
    elif auth_token:
        raw_token = auth_token
    elif token:
        raw_token = token

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_auth_token(raw_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == payload.get("user_id")).first()
    if not user:
        user = db.query(User).filter(User.email == payload.get("email")).first()
    if not user:
        user = User(
            id=payload.get("user_id", "usr_admin"),
            email=payload.get("email", "admin@nagpurestates.com"),
            name="Admin Manager",
            role=payload.get("role", "admin"),
        )
    return user


# ---------------------------------------------------------------------------
# Request & Response Models
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str = Field(..., examples=["admin@nagpurestates.com"])
    password: str = Field(..., examples=["admin123"])


class CallInitiationRequest(BaseModel):
    phone_number: str = Field(..., description="Customer phone number (e.g. +918600079496 or 10-digit mobile)")
    customer_name: str = Field(default="Customer", description="Name of the customer")
    lead_id: Optional[str] = Field(default=None, description="Associated Lead ID if calling from CRM")
    agent_config_id: Optional[str] = Field(default=None, description="Specific AgentConfig to use for this call (defaults to active domain)")


class LeadCreateRequest(BaseModel):
    name: str = Field(..., examples=["Rahul"])
    phone_number: str = Field(..., examples=["+918600079496"])
    preferred_location: Optional[str] = Field(default="Besa", examples=["Besa"])
    property_type: Optional[str] = Field(default="Flat", examples=["Flat"])
    bhk: Optional[str] = Field(default="2 BHK", examples=["2 BHK"])
    budget_min: Optional[float] = Field(default=None)
    budget_max: Optional[float] = Field(default=6000000.0)
    purchase_purpose: Optional[str] = Field(default="Self-use")
    purchase_timeline: Optional[str] = Field(default="1-2 months")
    lead_temperature: Optional[str] = Field(default="warm")
    stage: Optional[str] = Field(default="new")
    assigned_agent: Optional[str] = Field(default="Priya")
    notes: Optional[str] = Field(default=None)


class NoteCreateRequest(BaseModel):
    note: str = Field(..., examples=["Customer is ready for Saturday site visit."])
    author_name: str = Field(default="Priya")


class PropertyCreateRequest(BaseModel):
    project_name: str
    location: str
    property_type: str = "Flat"
    bhk: str = "2 BHK"
    price_min: float
    price_max: float
    price_display: str
    carpet_area: Optional[str] = None
    possession_status: str = "Ready to Move"
    rera_id: Optional[str] = None
    builder_name: str = "Nagpur Estates Partner"
    description: str
    amenities: Optional[str] = None
    available_units: int = 5


class SiteVisitCreateRequest(BaseModel):
    lead_id: str
    location: str
    visit_datetime: str
    property_id: Optional[str] = None
    notes: Optional[str] = None
    salesperson: str = "Priya"


class CallbackCreateRequest(BaseModel):
    lead_id: str
    scheduled_at: str
    reason: str = "Customer requested callback"
    assigned_to: str = "Priya"


class QuickLeadInput(BaseModel):
    name: str
    phone_number: str
    preferred_location: Optional[str] = "Nagpur"
    bhk: Optional[str] = "2 BHK"
    budget_max: Optional[float] = 6000000.0


class CampaignCreateRequest(BaseModel):
    name: str = Field(..., examples=["Besa 2 BHK Warm Buyers"])
    description: Optional[str] = None
    target_locality: Optional[str] = "Besa"
    target_property_type: Optional[str] = "Flat"
    goal: Optional[str] = "site_visit_booking"
    concurrency: int = 3
    lead_ids: Optional[List[str]] = Field(default_factory=list)
    new_leads: Optional[List[QuickLeadInput]] = Field(default_factory=list)
    start_immediately: bool = False
    selected_script_id: Optional[str] = None


class CampaignAddLeadsRequest(BaseModel):
    lead_ids: Optional[List[str]] = Field(default_factory=list)
    new_leads: Optional[List[QuickLeadInput]] = Field(default_factory=list)
    start_immediately: bool = False


# ---------------------------------------------------------------------------
# Authentication Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/auth/login", summary="Login with email and password")
async def login_endpoint(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    clean_email = req.email.strip().lower()
    clean_password = req.password.strip()

    # 1. Check in database
    user = db.query(User).filter(User.email.ilike(clean_email)).first()
    
    # 2. Fallback check with environment admin credentials
    admin_env_email = os.getenv("ADMIN_EMAIL", "admin@nagpurestates.com").strip().lower()
    admin_env_pass = os.getenv("ADMIN_PASSWORD", "admin123").strip()

    is_valid = False
    if user and user.password_hash:
        is_valid = verify_password(clean_password, user.password_hash)
    
    if not is_valid and clean_email == admin_env_email and clean_password == admin_env_pass:
        is_valid = True
        if not user:
            user = User(
                id="usr_admin_01",
                email=clean_email,
                name="Admin Manager",
                role="admin",
                password_hash=hash_password(clean_password),
            )
            db.add(user)
            db.commit()
            db.refresh(user)

    if not is_valid or not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    token = create_auth_token(user_id=user.id, email=user.email, role=user.role)
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        max_age=86400 * 7,
        samesite="lax",
        secure=False,
    )

    return {
        "status": "success",
        "token": token,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
        },
    }


@app.post("/api/auth/logout", summary="Log out user")
async def logout_endpoint(response: Response):
    response.delete_cookie("auth_token")
    return {"status": "success", "message": "Logged out successfully."}


@app.get("/api/auth/me", summary="Current user profile")
async def get_current_user_profile(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
    }


# ---------------------------------------------------------------------------
# Dashboard Analytics API
# ---------------------------------------------------------------------------
@app.get("/api/dashboard", summary="Main CRM Dashboard KPI Metrics")
async def get_dashboard_data(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total_leads = db.query(Lead).count()
    hot_leads = db.query(Lead).filter(Lead.lead_temperature == "hot").count()
    warm_leads = db.query(Lead).filter(Lead.lead_temperature == "warm").count()
    cold_leads = db.query(Lead).filter(Lead.lead_temperature == "cold").count()

    total_calls = db.query(CallRecord).count()
    completed_calls = db.query(CallRecord).filter(CallRecord.status == "completed").count()
    site_visits_count = db.query(SiteVisit).count()
    callbacks_due = db.query(Callback).filter(Callback.status == "pending").count()

    conversion_rate = round((site_visits_count / total_leads * 100), 1) if total_leads > 0 else 0.0

    # Pipeline counts
    pipeline_stages = ["new", "contacted", "qualified", "property_matched", "site_visit", "won", "lost", "dnd"]
    pipeline = {}
    for st in pipeline_stages:
        pipeline[st] = db.query(Lead).filter(Lead.stage == st).count()

    # Recent activities
    recent_activities = (
        db.query(LeadActivity).order_by(LeadActivity.created_at.desc()).limit(10).all()
    )
    activities_list = [
        {
            "id": a.id,
            "lead_id": a.lead_id,
            "type": a.activity_type,
            "description": a.description,
            "created_at": a.created_at.isoformat(),
        }
        for a in recent_activities
    ]

    return {
        "kpis": {
            "total_leads": total_leads,
            "hot_leads": hot_leads,
            "warm_leads": warm_leads,
            "cold_leads": cold_leads,
            "total_calls": total_calls,
            "completed_calls": completed_calls,
            "site_visits": site_visits_count,
            "callbacks_due": callbacks_due,
            "conversion_rate": conversion_rate,
        },
        "pipeline": pipeline,
        "recent_activities": activities_list,
    }


# ---------------------------------------------------------------------------
# Leads API
# ---------------------------------------------------------------------------
@app.get("/api/leads", summary="List and filter leads")
async def list_leads(
    search: Optional[str] = None,
    stage: Optional[str] = None,
    temperature: Optional[str] = None,
    location: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
):
    return get_leads_filtered(search=search, stage=stage, temperature=temperature, location=location, limit=limit, offset=offset)


@app.post("/api/leads", status_code=status.HTTP_201_CREATED, summary="Create a new lead")
async def create_lead(req: LeadCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lead = create_or_update_lead(
        phone_number=req.phone_number,
        name=req.name,
        preferred_location=req.preferred_location,
        property_type=req.property_type,
        bhk=req.bhk,
        budget_min=req.budget_min,
        budget_max=req.budget_max,
        purchase_purpose=req.purchase_purpose,
        purchase_timeline=req.purchase_timeline,
        lead_temperature=req.lead_temperature,
        stage=req.stage,
        assigned_agent=req.assigned_agent,
        notes=req.notes,
        db=db,
    )
    return {"status": "created", "lead_id": lead.id, "lead": get_lead_detail(lead.id)}


@app.get("/api/leads/{lead_id}", summary="Get detailed lead profile")
async def get_lead(lead_id: str, current_user: User = Depends(get_current_user)):
    lead = get_lead_detail(lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lead {lead_id} not found.")
    return lead


@app.post("/api/leads/{lead_id}/notes", summary="Add note to lead")
async def add_note_endpoint(lead_id: str, req: NoteCreateRequest, current_user: User = Depends(get_current_user)):
    note = add_lead_note(lead_id=lead_id, note_text=req.note, author_name=req.author_name)
    return {"status": "added", "note_id": note.id}


@app.post("/api/leads/import", summary="Import leads from CSV file")
async def import_leads_csv(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    content = await file.read()
    csv_text = content.decode("utf-8", errors="ignore")
    result = import_leads_from_csv(csv_text)
    return result


@app.get("/api/leads/export", summary="Export leads as CSV")
async def export_leads_csv(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    leads = db.query(Lead).order_by(Lead.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Phone", "Location", "Property Type", "BHK", "Max Budget", "Temperature", "Stage", "Notes", "Created At"])
    for l in leads:
        writer.writerow([l.id, l.name, l.phone_number, l.preferred_location or "", l.property_type or "", l.bhk or "", l.budget_max or "", l.lead_temperature, l.stage, l.notes or "", l.created_at.isoformat() if l.created_at else ""])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=nagpur_estates_leads.csv"},
    )


# ---------------------------------------------------------------------------
# Call Control & History API
# ---------------------------------------------------------------------------
@app.post("/api/calls", status_code=status.HTTP_201_CREATED, summary="Initiate Gemini 3.1 Live Outbound Call")
async def initiate_call_endpoint(
    req: CallInitiationRequest,
    response: Response,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
):
    """
    Trigger LiveKit SIP Outbound Call with Gemini 3.1 Live Native Audio.
    Dispatches agent worker, dials customer phone via Vobiz trunk, and tracks live state.
    """
    try:
        call_info = await initiate_outbound_call(
            phone_number=req.phone_number,
            customer_name=req.customer_name,
            lead_id=req.lead_id,
            idempotency_key=idempotency_key,
            agent_config_id=req.agent_config_id,
        )
        return call_info
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))
    except RuntimeError as r_err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(r_err))
    except Exception as e:
        logger.error(f"CALL_DISPATCH_FAILED | {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Call failed: {str(e)}")


@app.get("/api/calls", summary="List call records")
async def list_calls(
    status: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(CallRecord)
    if status and status.lower() != "all":
        q = q.filter(CallRecord.status == status.lower())
    if outcome and outcome.lower() != "all":
        q = q.filter(CallRecord.outcome == outcome.lower())

    total = q.count()
    calls = q.order_by(CallRecord.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "calls": [
            {
                "id": c.id,
                "call_id": c.call_id,
                "lead_id": c.lead_id,
                "customer_name": c.customer_name,
                "phone_number_masked": c.phone_number_masked,
                "status": c.status,
                "duration_seconds": c.duration_seconds,
                "greeting_latency_ms": c.greeting_latency_ms,
                "avg_response_latency_ms": c.avg_response_latency_ms,
                "p50_latency_ms": c.p50_latency_ms,
                "p90_latency_ms": c.p90_latency_ms,
                "turns_count": c.turns_count,
                "interruptions_count": c.interruptions_count,
                "lead_temperature": c.lead_temperature,
                "next_action": c.next_action,
                "outcome": c.outcome,
                "summary": c.summary,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in calls
        ],
    }


@app.get("/api/calls/{call_id}", summary="Get call detail with full transcript")
async def get_call_record(call_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    call = db.query(CallRecord).filter(CallRecord.call_id == call_id).first()
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Call {call_id} not found.")

    turns = [
        {
            "turn_number": t.turn_number,
            "speaker": t.speaker,
            "text": t.text,
            "latency_ms": t.latency_ms,
            "interrupted": t.interrupted,
            "timestamp": t.timestamp,
        }
        for t in call.turns
    ]

    return {
        "id": call.id,
        "call_id": call.call_id,
        "lead_id": call.lead_id,
        "customer_name": call.customer_name,
        "phone_number_masked": call.phone_number_masked,
        "status": call.status,
        "duration_seconds": call.duration_seconds,
        "greeting_latency_ms": call.greeting_latency_ms,
        "avg_response_latency_ms": call.avg_response_latency_ms,
        "p50_latency_ms": call.p50_latency_ms,
        "p90_latency_ms": call.p90_latency_ms,
        "p95_latency_ms": call.p95_latency_ms,
        "p99_latency_ms": call.p99_latency_ms,
        "turns_count": call.turns_count,
        "interruptions_count": call.interruptions_count,
        "lead_temperature": call.lead_temperature,
        "next_action": call.next_action,
        "outcome": call.outcome,
        "summary": call.summary,
        "turns": turns,
        "created_at": call.created_at.isoformat() if call.created_at else None,
    }


@app.get("/api/calls/{call_id}/live", summary="Poll active live call status & transcript")
async def get_call_live_status(call_id: str, current_user: User = Depends(get_current_user)):
    try:
        return get_live_call_status(call_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live call not active.")


@app.post("/api/calls/{call_id}/hangup", summary="Terminate active call")
async def hangup_call_endpoint(call_id: str, current_user: User = Depends(get_current_user)):
    res = await terminate_call(call_id)
    return res


@app.post("/api/calls/clear-stale", summary="Evict stale entries from live call registry")
async def clear_stale_registry(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Removes any entries from the in-memory LIVE_CALL_REGISTRY whose corresponding
    DB record is in a terminal state (completed/failed/cancelled/etc.).
    Call this when a number is stuck as 'active' after a call is done.
    """
    _TERMINAL_STATUSES = {"completed", "failed", "cancelled", "busy", "no_answer", "ended_in_middle", "call_ended"}
    evicted = []
    for cid in list(LIVE_CALL_REGISTRY.keys()):
        cr = db.query(CallRecord).filter(CallRecord.call_id == cid).first()
        is_stale_ending = bool(cr and cr.status == "call_ending" and cr.started_at and (time.time() - cr.started_at > 5.0))
        if cr and (cr.status in _TERMINAL_STATUSES or is_stale_ending):
            if is_stale_ending:
                cr.status = "completed" if (cr.turns and len(cr.turns) > 0) else "ended_in_middle"
                if not cr.ended_at:
                    cr.ended_at = time.time()
                db.commit()
            LIVE_CALL_REGISTRY.pop(cid, None)
            evicted.append({"call_id": cid, "db_status": cr.status})
            logger.warning(f"MANUAL_STALE_EVICTED | call_id={cid} | db_status={cr.status}")
        elif cr is None:
            # No DB record at all — orphaned entry
            LIVE_CALL_REGISTRY.pop(cid, None)
            evicted.append({"call_id": cid, "db_status": "no_db_record"})
            logger.warning(f"MANUAL_ORPHAN_EVICTED | call_id={cid}")
    return {"evicted": evicted, "count": len(evicted), "remaining_active": len(LIVE_CALL_REGISTRY)}


# ---------------------------------------------------------------------------
# Properties Inventory API
# ---------------------------------------------------------------------------
@app.get("/api/properties", summary="List and filter properties")
async def list_properties(
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    bhk: Optional[str] = None,
    budget_max: Optional[float] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Property).filter(Property.is_active == True)
    if location and location.lower() != "all":
        q = q.filter(Property.location.ilike(f"%{location.strip()}%"))
    if property_type and property_type.lower() != "all":
        q = q.filter(Property.property_type.ilike(f"%{property_type.strip()}%"))
    if bhk and bhk.lower() != "all":
        q = q.filter(Property.bhk.ilike(f"%{bhk.strip()}%"))
    if budget_max and budget_max > 0:
        q = q.filter(Property.price_min <= budget_max)

    props = q.order_by(Property.price_min.asc()).all()
    return [
        {
            "id": p.id,
            "project_name": p.project_name,
            "location": p.location,
            "property_type": p.property_type,
            "bhk": p.bhk,
            "price_min": p.price_min,
            "price_max": p.price_max,
            "price_display": p.price_display,
            "carpet_area": p.carpet_area,
            "possession_status": p.possession_status,
            "rera_id": p.rera_id,
            "builder_name": p.builder_name,
            "description": p.description,
            "amenities": p.amenities,
            "available_units": p.available_units,
        }
        for p in props
    ]


@app.post("/api/properties", status_code=status.HTTP_201_CREATED, summary="Add new property")
async def add_property(req: PropertyCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prop = Property(
        project_name=req.project_name,
        location=req.location,
        property_type=req.property_type,
        bhk=req.bhk,
        price_min=req.price_min,
        price_max=req.price_max,
        price_display=req.price_display,
        carpet_area=req.carpet_area,
        possession_status=req.possession_status,
        rera_id=req.rera_id,
        builder_name=req.builder_name,
        description=req.description,
        amenities=req.amenities,
        available_units=req.available_units,
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return {"status": "created", "property_id": prop.id}


@app.post("/api/properties/match-test", summary="Test Property Matching Logic")
async def test_property_match(
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    bhk: Optional[str] = None,
    budget_max: Optional[float] = None,
    query: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    res = search_properties_hybrid(
        location=location,
        property_type=property_type,
        bhk=bhk,
        budget_max=budget_max,
        query_text=query,
        top_k=3,
    )
    return res


# ---------------------------------------------------------------------------
# Knowledge Base & RAG Ingestion API
# ---------------------------------------------------------------------------
@app.get("/api/knowledge-base", summary="List knowledge base documents")
async def list_knowledge_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    docs = db.query(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()).all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "document_type": d.document_type,
            "status": d.status,
            "chunk_count": d.chunk_count,
            "vector_count": d.vector_count,
            "error_message": d.error_message,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in docs
    ]


@app.post("/api/knowledge-base/upload", status_code=status.HTTP_202_ACCEPTED, summary="Upload & Vectorize Document")
async def upload_document(file: UploadFile = File(...), current_user: User = Depends(get_current_user), background_tasks: BackgroundTasks = None):
    filename = file.filename
    dest_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex[:8]}_{filename}")

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        doc = ingest_document_file(file_path=dest_path, filename=filename)
        return {
            "status": "indexed",
            "document_id": doc.id,
            "filename": doc.filename,
            "chunks": doc.chunk_count,
            "vectors": doc.vector_count,
        }
    except Exception as e:
        logger.error(f"DOCUMENT_INGESTION_FAILED | {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Ingestion failed: {str(e)}")


@app.post("/api/knowledge-base/search-test", summary="Test RAG Vector Search")
async def test_rag_search(query: str = Query(..., examples=["What amenities does Greenwood Meadows offer?"]), current_user: User = Depends(get_current_user)):
    results = search_knowledge_chunks(query=query, top_k=3)
    return {"query": query, "results": results}


# ---------------------------------------------------------------------------
# Agent Training Scripts & Playbook API
# ---------------------------------------------------------------------------
class AgentScriptCreateRequest(BaseModel):
    title: str
    category: str = "conversation_script"  # conversation_script, fillers, objections, persona, identity_verification
    content: str
    domain: Optional[str] = "real_estate"
    is_active: bool = True
    is_primary: Optional[bool] = False


@app.get("/api/agent-scripts", summary="List all agent training scripts")
async def list_agent_scripts(
    domain: Optional[str] = None,
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(AgentScript)
    if domain and domain != "all":
        query = query.filter((AgentScript.domain == domain) | (AgentScript.domain == "all"))
    elif not domain:
        cfg = db.query(AgentConfig).filter(AgentConfig.is_active == True).order_by(AgentConfig.updated_at.desc(), AgentConfig.created_at.desc()).first()
        active_domain = getattr(cfg, "domain", "real_estate") if cfg else "real_estate"
        query = query.filter((AgentScript.domain == active_domain) | (AgentScript.domain == "all"))

    if category and category != "all":
        query = query.filter(AgentScript.category == category)

    scripts = query.order_by(AgentScript.is_primary.desc(), AgentScript.created_at.desc()).all()
    return [
        {
            "id": s.id,
            "title": s.title,
            "category": s.category,
            "domain": getattr(s, "domain", "real_estate") or "real_estate",
            "content": s.content,
            "is_active": s.is_active,
            "is_primary": bool(getattr(s, "is_primary", False)),
            "filename": s.filename,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in scripts
    ]


@app.post("/api/agent-scripts", status_code=status.HTTP_201_CREATED, summary="Create or update agent script")
async def create_agent_script(req: AgentScriptCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target_domain = (req.domain or "real_estate").strip()
    is_primary = bool(req.is_primary)
    
    # If set as primary, unset any existing primary in this domain
    if is_primary:
        existing_primaries = db.query(AgentScript).filter(
            (AgentScript.domain == target_domain) | (AgentScript.domain == "all"),
            AgentScript.is_primary == True
        ).all()
        for ep in existing_primaries:
            ep.is_primary = False

    script = AgentScript(
        title=req.title.strip(),
        category=req.category.strip(),
        domain=target_domain,
        content=req.content.strip(),
        is_active=req.is_active,
        is_primary=is_primary,
    )
    db.add(script)
    db.flush()

    if is_primary:
        cfg = db.query(AgentConfig).filter(AgentConfig.domain == target_domain, AgentConfig.is_active == True).first()
        if not cfg:
            cfg = db.query(AgentConfig).filter(AgentConfig.is_active == True).first()
        if cfg:
            cfg.selected_script_id = script.id

    db.commit()
    db.refresh(script)
    return {
        "status": "created",
        "id": script.id,
        "title": script.title,
        "category": script.category,
        "domain": script.domain,
        "is_active": script.is_active,
        "is_primary": script.is_primary,
    }


@app.post("/api/agent-scripts/upload", status_code=status.HTTP_201_CREATED, summary="Upload Script File to Train Agent")
async def upload_agent_script_file(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    category: Optional[str] = Form("conversation_script"),
    domain: Optional[str] = Form("real_estate"),
    is_primary: Optional[bool] = Form(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = file.filename
    dest_path = os.path.join(UPLOAD_DIR, f"script_{uuid.uuid4().hex[:8]}_{filename}")
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        content = extract_text_from_file(dest_path, filename)
        if not content.strip():
            raise ValueError("Uploaded file is empty or text could not be extracted.")

        script_title = title.strip() if title and title.strip() else os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").title()
        target_domain = domain or "real_estate"
        primary_flag = bool(is_primary)

        if primary_flag:
            existing_primaries = db.query(AgentScript).filter(
                (AgentScript.domain == target_domain) | (AgentScript.domain == "all"),
                AgentScript.is_primary == True
            ).all()
            for ep in existing_primaries:
                ep.is_primary = False

        script = AgentScript(
            title=script_title,
            category=category or "conversation_script",
            domain=target_domain,
            content=content.strip(),
            filename=filename,
            is_active=True,
            is_primary=primary_flag,
        )
        db.add(script)
        db.flush()

        if primary_flag:
            cfg = db.query(AgentConfig).filter(AgentConfig.domain == target_domain, AgentConfig.is_active == True).first()
            if not cfg:
                cfg = db.query(AgentConfig).filter(AgentConfig.is_active == True).first()
            if cfg:
                cfg.selected_script_id = script.id

        db.commit()
        db.refresh(script)
        logger.info(f"AGENT_SCRIPT_UPLOADED | id={script.id} | title={script.title} | domain={script.domain} | is_primary={script.is_primary}")
        return {
            "status": "created",
            "id": script.id,
            "title": script.title,
            "category": script.category,
            "domain": script.domain,
            "char_count": len(script.content),
            "is_active": script.is_active,
            "is_primary": script.is_primary,
        }
    except Exception as e:
        logger.error(f"SCRIPT_UPLOAD_FAILED | {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Script upload failed: {str(e)}")


@app.patch("/api/agent-scripts/{script_id}/toggle", summary="Toggle script active/inactive")
async def toggle_agent_script(script_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    script = db.query(AgentScript).filter(AgentScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
    script.is_active = not script.is_active
    # If deactivated, it can no longer be primary
    if not script.is_active and script.is_primary:
        script.is_primary = False
    db.commit()
    logger.info(f"AGENT_SCRIPT_TOGGLED | id={script.id} | active={script.is_active} | primary={script.is_primary}")
    return {"id": script.id, "is_active": script.is_active, "is_primary": script.is_primary, "title": script.title}


@app.patch("/api/agent-scripts/{script_id}/select-primary", summary="Select script as primary for upcoming calls/batches")
async def select_primary_script(script_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    script = db.query(AgentScript).filter(AgentScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
    
    target_domain = script.domain or "real_estate"
    script.is_active = True
    script.is_primary = True

    # Unset other primary scripts for this domain
    others = db.query(AgentScript).filter(
        AgentScript.id != script.id,
        (AgentScript.domain == target_domain) | (AgentScript.domain == "all")
    ).all()
    for s in others:
        s.is_primary = False

    # Also record on active AgentConfig
    cfg = db.query(AgentConfig).filter(AgentConfig.domain == target_domain, AgentConfig.is_active == True).first()
    if not cfg:
        cfg = db.query(AgentConfig).filter(AgentConfig.is_active == True).first()
    if cfg:
        cfg.selected_script_id = script.id

    db.commit()
    db.refresh(script)
    logger.info(f"AGENT_SCRIPT_SELECTED_PRIMARY | id={script.id} | title={script.title} | domain={target_domain}")
    return {
        "status": "selected",
        "id": script.id,
        "title": script.title,
        "domain": script.domain,
        "is_primary": script.is_primary,
        "is_active": script.is_active,
    }


@app.patch("/api/agent-scripts/{script_id}/unselect-primary", summary="Unselect primary script")
async def unselect_primary_script(script_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    script = db.query(AgentScript).filter(AgentScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
    script.is_primary = False

    target_domain = script.domain or "real_estate"
    cfgs = db.query(AgentConfig).filter(AgentConfig.selected_script_id == script.id).all()
    for c in cfgs:
        c.selected_script_id = None

    db.commit()
    db.refresh(script)
    logger.info(f"AGENT_SCRIPT_UNSELECTED_PRIMARY | id={script.id}")
    return {
        "status": "unselected",
        "id": script.id,
        "is_primary": False,
        "title": script.title,
    }


@app.delete("/api/agent-scripts/{script_id}", summary="Delete agent script")
async def delete_agent_script(script_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    script = db.query(AgentScript).filter(AgentScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
    
    # If primary, clear from AgentConfig
    if script.is_primary:
        cfgs = db.query(AgentConfig).filter(AgentConfig.selected_script_id == script.id).all()
        for c in cfgs:
            c.selected_script_id = None

    db.delete(script)
    db.commit()
    logger.info(f"AGENT_SCRIPT_DELETED | id={script_id}")
    return {"status": "deleted", "id": script_id}


@app.put("/api/agent-scripts/{script_id}", summary="Update existing agent training script")
async def update_agent_script(script_id: str, req: AgentScriptCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    script = db.query(AgentScript).filter(AgentScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
    
    target_domain = req.domain.strip() if req.domain else (script.domain or "real_estate")
    script.title = req.title.strip()
    script.category = req.category.strip()
    script.domain = target_domain
    script.content = req.content.strip()
    script.is_active = req.is_active

    if req.is_primary is not None:
        if req.is_primary:
            script.is_primary = True
            others = db.query(AgentScript).filter(
                AgentScript.id != script.id,
                (AgentScript.domain == target_domain) | (AgentScript.domain == "all")
            ).all()
            for s in others:
                s.is_primary = False
            cfg = db.query(AgentConfig).filter(AgentConfig.domain == target_domain, AgentConfig.is_active == True).first()
            if not cfg:
                cfg = db.query(AgentConfig).filter(AgentConfig.is_active == True).first()
            if cfg:
                cfg.selected_script_id = script.id
        else:
            if script.is_primary:
                script.is_primary = False
                cfgs = db.query(AgentConfig).filter(AgentConfig.selected_script_id == script.id).all()
                for c in cfgs:
                    c.selected_script_id = None

    db.commit()
    db.refresh(script)
    logger.info(f"AGENT_SCRIPT_UPDATED | id={script.id} | title={script.title} | domain={script.domain} | is_primary={script.is_primary}")
    return {
        "status": "updated",
        "id": script.id,
        "title": script.title,
        "category": script.category,
        "domain": script.domain,
        "is_active": script.is_active,
        "is_primary": script.is_primary,
    }


# ---------------------------------------------------------------------------
# Dynamic AI Agent Configuration & Prompting Studio API
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Dynamic AI Agent Configuration & Multi-Domain Prompting Studio API
# ---------------------------------------------------------------------------
class AgentConfigUpdateRequest(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    gender: Optional[str] = None
    agent_display_name: Optional[str] = None
    company_name: Optional[str] = None
    role_description: Optional[str] = None
    voice: Optional[str] = None
    temperature: Optional[float] = None
    language_mode: Optional[str] = None
    greeting_known_lead: Optional[str] = None
    greeting_unknown_lead: Optional[str] = None
    wrong_number_pivot: Optional[str] = None
    conversation_philosophy: Optional[str] = None
    sales_funnel_stages: Optional[str] = None
    objection_guardrails: Optional[str] = None
    custom_system_prompt_override: Optional[str] = None
    is_active: Optional[bool] = None


class AgentDomainSwitchRequest(BaseModel):
    domain: str
    voice: Optional[str] = None
    gender: Optional[str] = None
    agent_display_name: Optional[str] = None
    company_name: Optional[str] = None


class AgentPromptPreviewRequest(BaseModel):
    test_customer_name: Optional[str] = "Rahul Sharma"
    domain: Optional[str] = None
    gender: Optional[str] = None
    agent_display_name: Optional[str] = None
    company_name: Optional[str] = None
    role_description: Optional[str] = None
    voice: Optional[str] = None
    temperature: Optional[float] = None
    language_mode: Optional[str] = None
    greeting_known_lead: Optional[str] = None
    greeting_unknown_lead: Optional[str] = None
    wrong_number_pivot: Optional[str] = None
    conversation_philosophy: Optional[str] = None
    sales_funnel_stages: Optional[str] = None
    objection_guardrails: Optional[str] = None
    custom_system_prompt_override: Optional[str] = None


@app.get("/api/domains", summary="List all supported business and service domains")
async def get_domains(current_user: User = Depends(get_current_user)):
    return list_supported_domains()


@app.get("/api/agent-voices", summary="List supported Gemini Live voice profiles")
async def get_agent_voices(current_user: User = Depends(get_current_user)):
    voices = []
    for v_id, meta in VOICE_METADATA.items():
        voices.append({
            "id": meta["id"],
            "name": meta["name"],
            "gender": meta["gender"].capitalize(),
            "default_name": meta["default_name"],
            "tag": meta["tag"],
            "description": meta["description"],
        })
    return voices


def _serialize_agent_config(cfg: AgentConfig) -> Dict[str, Any]:
    gender = getattr(cfg, "gender", None) or resolve_voice_gender(cfg.voice)
    domain = getattr(cfg, "domain", None) or "real_estate"
    return {
        "id": cfg.id,
        "name": cfg.name,
        "domain": domain,
        "gender": gender,
        "agent_display_name": cfg.agent_display_name,
        "company_name": cfg.company_name,
        "role_description": cfg.role_description,
        "voice": cfg.voice,
        "temperature": cfg.temperature,
        "language_mode": cfg.language_mode,
        "greeting_known_lead": cfg.greeting_known_lead,
        "greeting_unknown_lead": cfg.greeting_unknown_lead,
        "wrong_number_pivot": cfg.wrong_number_pivot,
        "conversation_philosophy": cfg.conversation_philosophy,
        "sales_funnel_stages": cfg.sales_funnel_stages,
        "objection_guardrails": cfg.objection_guardrails,
        "custom_system_prompt_override": cfg.custom_system_prompt_override,
        "is_active": cfg.is_active,
        "created_at": cfg.created_at.isoformat() if cfg.created_at else None,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


@app.get("/api/agent-config", summary="Get active dynamic AI agent configuration")
async def get_active_agent_config(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = db.query(AgentConfig).filter(AgentConfig.is_active == True).order_by(AgentConfig.updated_at.desc(), AgentConfig.created_at.desc()).first()
    if not cfg:
        preset = get_domain_preset("real_estate")
        cfg = AgentConfig(
            name=f"Nagpur Estates - {preset['default_female_name']} Consultative Persona",
            domain="real_estate",
            gender="female",
            agent_display_name=preset["default_female_name"],
            company_name=preset["default_company"],
            role_description=preset["role_description"],
            voice="Aoede",
            temperature=0.6,
            language_mode="hinglish",
            greeting_known_lead=preset["greeting_known_lead"],
            greeting_unknown_lead=preset["greeting_unknown_lead"],
            wrong_number_pivot=preset["wrong_number_pivot"],
            conversation_philosophy=preset["conversation_philosophy"],
            sales_funnel_stages=preset["sales_funnel_stages"],
            objection_guardrails=preset["objection_guardrails"],
            is_active=True,
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return _serialize_agent_config(cfg)


@app.put("/api/agent-config", summary="Update dynamic AI agent configuration")
async def update_agent_config(req: AgentConfigUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = db.query(AgentConfig).filter(AgentConfig.is_active == True).order_by(AgentConfig.created_at.desc()).first()
    if not cfg:
        cfg = AgentConfig()
        db.add(cfg)

    if req.name is not None:
        cfg.name = req.name.strip()
    if req.domain is not None:
        cfg.domain = req.domain.strip()
    if req.voice is not None:
        cfg.voice = req.voice.strip()
        # Automatically align gender with voice if not explicitly overridden
        if req.gender is None:
            cfg.gender = resolve_voice_gender(cfg.voice)
    if req.gender is not None:
        cfg.gender = req.gender.strip().lower()
    if req.agent_display_name is not None:
        cfg.agent_display_name = req.agent_display_name.strip()
    if req.company_name is not None:
        cfg.company_name = req.company_name.strip()
    if req.role_description is not None:
        cfg.role_description = req.role_description.strip()
    if req.temperature is not None:
        cfg.temperature = max(0.0, min(1.0, float(req.temperature)))
    if req.language_mode is not None:
        cfg.language_mode = req.language_mode.strip()
    if req.greeting_known_lead is not None:
        cfg.greeting_known_lead = req.greeting_known_lead.strip()
    if req.greeting_unknown_lead is not None:
        cfg.greeting_unknown_lead = req.greeting_unknown_lead.strip()
    if req.wrong_number_pivot is not None:
        cfg.wrong_number_pivot = req.wrong_number_pivot.strip()
    if req.conversation_philosophy is not None:
        cfg.conversation_philosophy = req.conversation_philosophy.strip()
    if req.sales_funnel_stages is not None:
        cfg.sales_funnel_stages = req.sales_funnel_stages.strip()
    if req.objection_guardrails is not None:
        cfg.objection_guardrails = req.objection_guardrails.strip()
    if req.custom_system_prompt_override is not None:
        cfg.custom_system_prompt_override = req.custom_system_prompt_override.strip() if req.custom_system_prompt_override.strip() else None
    if req.is_active is not None:
        cfg.is_active = req.is_active

    db.commit()
    db.refresh(cfg)
    logger.info(f"AGENT_CONFIG_UPDATED | id={cfg.id} | domain={cfg.domain} | gender={cfg.gender} | agent={cfg.agent_display_name} | voice={cfg.voice}")
    return _serialize_agent_config(cfg)


@app.post("/api/agent-config/switch-domain", summary="Switch active domain preset and configure default training scripts")
async def switch_agent_domain(req: AgentDomainSwitchRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    preset = get_domain_preset(req.domain)
    cfg = db.query(AgentConfig).filter(AgentConfig.is_active == True).order_by(AgentConfig.updated_at.desc(), AgentConfig.created_at.desc()).first()
    if not cfg:
        cfg = AgentConfig()
        db.add(cfg)

    # Determine voice & gender
    voice = req.voice or cfg.voice or "Aoede"
    gender = req.gender or resolve_voice_gender(voice, getattr(cfg, "gender", None))
    default_name = preset["default_male_name"] if gender == "male" else preset["default_female_name"]
    agent_name = req.agent_display_name or default_name
    company_name = req.company_name or preset["default_company"]

    cfg.domain = preset["id"]
    cfg.gender = gender
    cfg.voice = voice
    cfg.name = f"{preset['name']} - {agent_name} Persona"
    cfg.agent_display_name = agent_name
    cfg.company_name = company_name
    cfg.role_description = preset["role_description"]
    cfg.greeting_known_lead = preset["greeting_known_lead"]
    cfg.greeting_unknown_lead = preset["greeting_unknown_lead"]
    cfg.wrong_number_pivot = preset["wrong_number_pivot"]
    cfg.conversation_philosophy = preset["conversation_philosophy"]
    cfg.sales_funnel_stages = preset["sales_funnel_stages"]
    cfg.objection_guardrails = preset["objection_guardrails"]
    cfg.custom_system_prompt_override = None
    cfg.is_active = True
    cfg.updated_at = datetime.utcnow()

    # Enforce single active AgentConfig in the system
    db.query(AgentConfig).filter(AgentConfig.id != cfg.id).update({"is_active": False}, synchronize_session=False)

    # Strict Script Isolation:
    # 1. Deactivate scripts specifically belonging to other domains
    db.query(AgentScript).filter(
        AgentScript.domain != preset["id"],
        AgentScript.domain != "all",
    ).update({"is_active": False}, synchronize_session=False)

    # 2. Activate scripts belonging to this domain or 'all'
    db.query(AgentScript).filter(
        (AgentScript.domain == preset["id"]) | (AgentScript.domain == "all")
    ).update({"is_active": True}, synchronize_session=False)

    # 3. Seed / activate default scripts for this domain
    seeded_count = 0
    for s_meta in preset.get("scripts", []):
        existing = db.query(AgentScript).filter(AgentScript.id == s_meta["id"]).first()
        if not existing:
            new_script = AgentScript(
                id=s_meta["id"],
                title=s_meta["title"],
                domain=preset["id"],
                category=s_meta["category"],
                content=s_meta["content"],
                is_active=True,
            )
            db.add(new_script)
            seeded_count += 1
        else:
            existing.domain = preset["id"]
            existing.is_active = True

    db.commit()
    db.refresh(cfg)
    logger.info(f"DOMAIN_SWITCHED | domain={preset['id']} | gender={gender} | agent={agent_name} | new_scripts={seeded_count}")
    response_data = _serialize_agent_config(cfg)
    response_data["status"] = "success"
    response_data["domain_name"] = preset["name"]
    response_data["seeded_scripts_count"] = seeded_count
    return response_data


@app.post("/api/agent-config/reset", summary="Reset agent configuration to active domain default")
async def reset_agent_config(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = db.query(AgentConfig).filter(AgentConfig.is_active == True).order_by(AgentConfig.updated_at.desc(), AgentConfig.created_at.desc()).first()
    if not cfg:
        cfg = AgentConfig()
        db.add(cfg)

    domain = getattr(cfg, "domain", "real_estate") or "real_estate"
    preset = get_domain_preset(domain)
    gender = getattr(cfg, "gender", "female") or resolve_voice_gender(cfg.voice)
    default_name = preset["default_male_name"] if gender == "male" else preset["default_female_name"]

    cfg.name = f"{preset['name']} - {default_name} Persona"
    cfg.agent_display_name = default_name
    cfg.company_name = preset["default_company"]
    cfg.role_description = preset["role_description"]
    cfg.greeting_known_lead = preset["greeting_known_lead"]
    cfg.greeting_unknown_lead = preset["greeting_unknown_lead"]
    cfg.wrong_number_pivot = preset["wrong_number_pivot"]
    cfg.conversation_philosophy = preset["conversation_philosophy"]
    cfg.sales_funnel_stages = preset["sales_funnel_stages"]
    cfg.objection_guardrails = preset["objection_guardrails"]
    cfg.custom_system_prompt_override = None

    db.commit()
    db.refresh(cfg)
    logger.info(f"AGENT_CONFIG_RESET_TO_DEFAULTS | domain={domain}")
    return _serialize_agent_config(cfg)


@app.post("/api/agent-config/preview", summary="Generate live preview of assembled system prompt")
async def preview_agent_prompt(req: AgentPromptPreviewRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    test_cust = req.test_customer_name or "Rahul Sharma"
    prompt_ctx = build_system_prompt(
        customer_name=test_cust,
        override_domain=req.domain,
        override_gender=req.gender,
        override_voice=req.voice,
        override_agent_name=req.agent_display_name,
        override_company_name=req.company_name,
    )

    text_prompt = prompt_ctx.system_prompt
    agent_name = req.agent_display_name or prompt_ctx.agent_name
    company_name = req.company_name or prompt_ctx.company_name
    voice = req.voice or prompt_ctx.voice
    gender = req.gender or prompt_ctx.gender
    domain = req.domain or prompt_ctx.domain
    temp = req.temperature if req.temperature is not None else prompt_ctx.temperature

    if req.custom_system_prompt_override and req.custom_system_prompt_override.strip():
        cust_display = test_cust if test_cust.lower() != "customer" else ""
        cust_ji = f"{cust_display} ji" if cust_display else "ji"
        raw_override = (
            req.custom_system_prompt_override.replace("{customer_name}", cust_display or "ji")
            .replace("{cust_display}", cust_display or "ji")
            .replace("{cust_ji}", cust_ji)
            .replace("{agent_name}", agent_name)
            .replace("{company_name}", company_name)
        )
        text_prompt = render_gender_text(raw_override, gender=gender)
        if "ACTIVE CUSTOM TRAINING PLAYBOOKS" in prompt_ctx.system_prompt:
            scripts_part = "\n\nACTIVE CUSTOM TRAINING PLAYBOOKS" + prompt_ctx.system_prompt.split("ACTIVE CUSTOM TRAINING PLAYBOOKS", 1)[1]
            text_prompt = text_prompt + scripts_part

    words = len(text_prompt.split())
    chars = len(text_prompt)
    approx_tokens = max(1, chars // 4)

    return {
        "customer_name": test_cust,
        "domain": domain,
        "gender": gender,
        "agent_name": agent_name,
        "company_name": company_name,
        "voice": voice,
        "temperature": temp,
        "system_prompt": text_prompt,
        "greeting_speech": prompt_ctx.greeting_speech,
        "greeting_prompt": prompt_ctx.greeting_prompt,
        "char_count": chars,
        "word_count": words,
        "approx_tokens": approx_tokens,
    }


# ---------------------------------------------------------------------------
# Site Visits API
# ---------------------------------------------------------------------------
@app.get("/api/site-visits", summary="List scheduled site visits")
async def list_site_visits(current_user: User = Depends(get_current_user)):
    return get_site_visits_list()


@app.post("/api/site-visits", status_code=status.HTTP_201_CREATED, summary="Book a site visit")
async def create_site_visit_endpoint(req: SiteVisitCreateRequest, current_user: User = Depends(get_current_user)):
    visit = book_site_visit(
        lead_id=req.lead_id,
        location=req.location,
        visit_datetime=req.visit_datetime,
        property_id=req.property_id,
        salesperson=req.salesperson,
        notes=req.notes,
    )
    return {"status": "confirmed", "site_visit_id": visit.id}


@app.patch("/api/site-visits/{visit_id}/status", summary="Update site visit status")
async def update_site_visit_status(visit_id: str, new_status: str = Query(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    visit = db.query(SiteVisit).filter(SiteVisit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site visit not found.")
    visit.status = new_status.lower()
    db.commit()
    return {"status": "updated", "visit_id": visit.id, "new_status": visit.status}


# ---------------------------------------------------------------------------
# Callbacks API
# ---------------------------------------------------------------------------
@app.get("/api/callbacks", summary="List scheduled callbacks")
async def list_callbacks(status: Optional[str] = None, current_user: User = Depends(get_current_user)):
    return get_callbacks_list(status_filter=status)


@app.post("/api/callbacks", status_code=status.HTTP_201_CREATED, summary="Schedule a callback")
async def create_callback_endpoint(req: CallbackCreateRequest, current_user: User = Depends(get_current_user)):
    cb = schedule_callback(
        lead_id=req.lead_id,
        scheduled_at=req.scheduled_at,
        reason=req.reason,
        assigned_to=req.assigned_to,
    )
    return {"status": "scheduled", "callback_id": cb.id}


@app.patch("/api/callbacks/{cb_id}/status", summary="Update callback status")
async def update_callback_status(cb_id: str, new_status: str = Query(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cb = db.query(Callback).filter(Callback.id == cb_id).first()
    if not cb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Callback not found.")
    cb.status = new_status.lower()
    db.commit()
    return {"status": "updated", "callback_id": cb.id, "new_status": cb.status}


# ---------------------------------------------------------------------------
# Campaigns & Batch Calling API
# ---------------------------------------------------------------------------
@app.get("/api/campaigns", summary="List calling campaigns with progress metrics")
async def list_campaigns(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    res = []
    for c in campaigns:
        total = c.total_leads or db.query(CampaignLead).filter(CampaignLead.campaign_id == c.id).count()
        ready = c.queued_leads or db.query(CampaignLead).filter(CampaignLead.campaign_id == c.id, CampaignLead.status.in_(["ready", "queued"])).count()
        calling = c.active_calls or db.query(CampaignLead).filter(CampaignLead.campaign_id == c.id, CampaignLead.status.in_(["in_progress", "dialing", "active"])).count()
        completed = c.completed_leads or db.query(CampaignLead).filter(CampaignLead.campaign_id == c.id, CampaignLead.status == "completed").count()
        failed = c.failed_leads or db.query(CampaignLead).filter(CampaignLead.campaign_id == c.id, CampaignLead.status.in_(["failed", "not_interested", "cancelled"])).count()
        
        res.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "target_locality": c.target_locality,
            "target_property_type": c.target_property_type,
            "goal": c.goal,
            "concurrency": c.concurrency,
            "status": c.status,
            "total_leads": total,
            "ready_leads": ready,
            "queued_leads": ready,
            "calling_leads": calling,
            "active_calls": calling,
            "completed_leads": completed,
            "failed_leads": failed,
            "max_observed_active_calls": c.max_observed_active_calls or 0,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "completed_at": c.completed_at.isoformat() if c.completed_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })
    return res


@app.post("/api/campaigns", status_code=status.HTTP_201_CREATED, summary="Create a new campaign")
async def create_campaign_endpoint(req: CampaignCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 1. Resolve all lead IDs (existing + newly created on-the-fly)
    all_lead_ids: List[str] = list(req.lead_ids or [])

    if req.new_leads:
        for nl in req.new_leads:
            clean_phone = nl.phone_number.strip() if nl.phone_number else ""
            clean_name = nl.name.strip() if nl.name else "Customer"
            if not clean_phone:
                continue
            created_lead = create_or_update_lead(
                phone_number=clean_phone,
                name=clean_name,
                preferred_location=nl.preferred_location or req.target_locality or "Nagpur",
                bhk=nl.bhk or "2 BHK",
                budget_max=nl.budget_max or 6000000.0,
                db=db,
            )
            if created_lead and created_lead.id not in all_lead_ids:
                all_lead_ids.append(created_lead.id)

    # 2. Validation for MVP (strict bounds)
    if len(all_lead_ids) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 1 lead must be selected or added for campaign.",
        )
    if len(all_lead_ids) > 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 3 leads can be tested concurrently right now in this MVP.",
        )
    if req.concurrency < 1 or req.concurrency > 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign concurrency must be between 1 and 3 for this MVP.",
        )

    lead_count = len(all_lead_ids)
    init_status = "running" if req.start_immediately else "draft"
    started_time = datetime.utcnow() if init_status == "running" else None

    cmp = Campaign(
        name=req.name,
        description=req.description,
        target_locality=req.target_locality,
        target_property_type=req.target_property_type,
        goal=req.goal or "site_visit_booking",
        concurrency=req.concurrency,
        status=init_status,
        started_at=started_time,
        total_leads=lead_count,
        queued_leads=lead_count,
        active_calls=0,
        completed_leads=0,
        failed_leads=0,
        max_observed_active_calls=0,
        selected_script_id=req.selected_script_id,
    )
    db.add(cmp)
    db.commit()
    db.refresh(cmp)

    for lid in all_lead_ids:
        lead = db.query(Lead).filter(Lead.id == lid).first()
        if lead:
            cl = CampaignLead(campaign_id=cmp.id, lead_id=lid, status="queued")
            db.add(cl)
    db.commit()

    if init_status == "running":
        start_campaign_dialer_task(cmp.id)

    return {
        "status": init_status,
        "campaign_id": cmp.id,
        "name": cmp.name,
        "concurrency": cmp.concurrency,
        "total_leads": cmp.total_leads,
        "queued_leads": cmp.queued_leads,
        "started_immediately": req.start_immediately,
    }


@app.get("/api/campaigns/{campaign_id}", summary="Get campaign details with assigned leads")
async def get_campaign_detail(campaign_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    c_leads = (
        db.query(CampaignLead)
        .filter(CampaignLead.campaign_id == campaign_id)
        .order_by(CampaignLead.created_at.asc())
        .all()
    )

    leads_list = []
    for cl in c_leads:
        lead = cl.lead
        if lead:
            duration_sec = 0
            call_outcome = cl.last_call_outcome
            call_status = cl.last_call_status or cl.status
            if cl.last_call_id:
                cr = db.query(CallRecord).filter(CallRecord.call_id == cl.last_call_id).first()
                if cr:
                    duration_sec = cr.duration_seconds or 0
                    if not call_outcome or call_outcome in ("active", "dialing"):
                        call_outcome = cr.outcome or cr.status
                    if not call_status:
                        call_status = cr.status

            leads_list.append({
                "campaign_lead_id": cl.id,
                "lead_id": lead.id,
                "name": lead.name,
                "phone_number": lead.phone_number,
                "masked_phone": lead.masked_phone,
                "preferred_location": lead.preferred_location,
                "property_type": lead.property_type,
                "bhk": lead.bhk,
                "budget_display": f"₹{lead.budget_max/100000:.0f} L" if lead.budget_max else "N/A",
                "lead_temperature": lead.lead_temperature,
                "stage": lead.stage,
                "campaign_status": cl.status,
                "attempts": cl.attempts,
                "last_call_id": cl.last_call_id,
                "last_call_status": call_status,
                "last_call_outcome": call_outcome,
                "call_duration_seconds": duration_sec,
                "started_at": cl.started_at.isoformat() if cl.started_at else None,
                "completed_at": cl.completed_at.isoformat() if cl.completed_at else None,
                "added_at": cl.created_at.isoformat() if cl.created_at else None,
            })

    total = len(leads_list)
    queued = sum(1 for x in leads_list if x["campaign_status"] in ("ready", "queued"))
    calling = sum(1 for x in leads_list if x["campaign_status"] in ("in_progress", "dialing", "active"))
    completed = sum(1 for x in leads_list if x["campaign_status"] == "completed")
    ended_in_middle = sum(1 for x in leads_list if x["campaign_status"] == "ended_in_middle")
    failed = sum(1 for x in leads_list if x["campaign_status"] in ("failed", "not_interested", "cancelled", "no_answer"))

    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "target_locality": c.target_locality,
        "target_property_type": c.target_property_type,
        "goal": c.goal,
        "concurrency": c.concurrency,
        "status": c.status,
        "total_leads": total,
        "queued_leads": queued,
        "active_calls": c.active_calls if c.active_calls is not None else calling,
        "completed_leads": c.completed_leads if c.completed_leads is not None else completed,
        "failed_leads": c.failed_leads if c.failed_leads is not None else (failed + ended_in_middle),
        "ended_in_middle_leads": ended_in_middle,
        "max_observed_active_calls": c.max_observed_active_calls or 0,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "completed_at": c.completed_at.isoformat() if c.completed_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "stats": {
            "total": total,
            "ready": queued,
            "queued": queued,
            "calling": calling,
            "completed": completed,
            "ended_in_middle": ended_in_middle,
            "failed": failed,
        },
        "leads": leads_list,
    }


@app.get("/api/campaigns/{campaign_id}/leads", summary="Get campaign leads list")
async def get_campaign_leads(campaign_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    c_leads = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id).order_by(CampaignLead.created_at.asc()).all()
    return [
        {
            "lead_id": cl.lead_id,
            "campaign_lead_id": cl.id,
            "customer_name": cl.lead.name if cl.lead else "Customer",
            "phone_number": cl.lead.phone_number if cl.lead else "",
            "masked_phone": cl.lead.masked_phone if cl.lead else "",
            "status": cl.status,
            "attempts": cl.attempts,
            "call_id": cl.last_call_id,
            "last_call_status": cl.last_call_status or cl.status,
            "last_call_outcome": cl.last_call_outcome,
            "started_at": cl.started_at.isoformat() if cl.started_at else None,
            "completed_at": cl.completed_at.isoformat() if cl.completed_at else None,
        }
        for cl in c_leads
    ]


@app.post("/api/campaigns/{campaign_id}/leads", summary="Add existing or custom leads to campaign")
async def add_leads_to_campaign(campaign_id: str, req: CampaignAddLeadsRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    all_lead_ids: List[str] = list(req.lead_ids or [])

    if req.new_leads:
        for nl in req.new_leads:
            clean_phone = nl.phone_number.strip() if nl.phone_number else ""
            clean_name = nl.name.strip() if nl.name else "Customer"
            if not clean_phone:
                continue
            created_lead = create_or_update_lead(
                phone_number=clean_phone,
                name=clean_name,
                preferred_location=nl.preferred_location or c.target_locality or "Nagpur",
                bhk=nl.bhk or "2 BHK",
                budget_max=nl.budget_max or 6000000.0,
                db=db,
            )
            if created_lead and created_lead.id not in all_lead_ids:
                all_lead_ids.append(created_lead.id)

    added = 0
    for lid in all_lead_ids:
        existing = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id, CampaignLead.lead_id == lid).first()
        if not existing:
            lead = db.query(Lead).filter(Lead.id == lid).first()
            if lead:
                db.add(CampaignLead(campaign_id=campaign_id, lead_id=lid, status="queued"))
                added += 1
        elif existing.status in ("cancelled", "ready"):
            existing.status = "queued"
            added += 1

    queued_count = db.query(CampaignLead).filter(
        CampaignLead.campaign_id == campaign_id,
        CampaignLead.status.in_(["queued", "ready"]),
    ).count()

    c.total_leads = (c.total_leads or 0) + added
    c.queued_leads = queued_count
    db.commit()

    if req.start_immediately and queued_count > 0:
        c.status = "running"
        c.started_at = c.started_at or datetime.utcnow()
        db.commit()
        start_campaign_dialer_task(campaign_id)

    return {
        "status": "added",
        "added_count": added,
        "campaign_status": c.status,
        "queued_leads": c.queued_leads,
        "started_immediately": req.start_immediately,
    }


@app.post("/api/campaigns/{campaign_id}/import", summary="Import CSV leads directly into campaign")
async def import_csv_to_campaign(campaign_id: str, file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    content = await file.read()
    csv_text = content.decode("utf-8", errors="ignore")
    result = import_leads_from_csv(csv_text)

    # Attach all imported leads to campaign
    reader = csv.DictReader(io.StringIO(csv_text))
    added = 0
    for row in reader:
        phone = row.get("phone", row.get("Phone", row.get("mobile", ""))).strip()
        if phone:
            norm_phone = normalize_phone_e164(phone)
            lead = db.query(Lead).filter(Lead.phone_number == norm_phone).first()
            if lead:
                exists = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id, CampaignLead.lead_id == lead.id).first()
                if not exists:
                    db.add(CampaignLead(campaign_id=campaign_id, lead_id=lead.id, status="queued"))
                    added += 1
    c.total_leads = (c.total_leads or 0) + added
    c.queued_leads = (c.queued_leads or 0) + added
    db.commit()
    return {
        "status": "imported",
        "leads_created": result["imported"],
        "leads_added_to_campaign": added,
    }


@app.post("/api/campaigns/{campaign_id}/start", summary="Start campaign dialing")
async def start_campaign_calling(campaign_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    # Re-queue any leads if no queued leads exist (seamless restart)
    queued_count = db.query(CampaignLead).filter(
        CampaignLead.campaign_id == campaign_id,
        CampaignLead.status.in_(["queued", "ready"]),
    ).count()

    if queued_count == 0:
        all_leads = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id).all()
        for cl in all_leads:
            cl.status = "queued"
            cl.last_call_status = None
            cl.last_call_outcome = None
            cl.started_at = None
            cl.completed_at = None
        queued_count = len(all_leads)
        c.completed_leads = 0
        c.failed_leads = 0
        c.completed_at = None

    c.queued_leads = queued_count
    c.active_calls = 0
    c.status = "running"
    c.started_at = datetime.utcnow()
    db.commit()
    start_campaign_dialer_task(campaign_id)
    return {"status": "running", "campaign_id": c.id, "queued_leads": c.queued_leads}


@app.post("/api/campaigns/{campaign_id}/restart", summary="Restart campaign from beginning, resetting all leads")
async def restart_campaign_calling(campaign_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    stop_campaign_dialer_task(campaign_id)

    all_leads = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id).all()
    for cl in all_leads:
        cl.status = "queued"
        cl.last_call_status = None
        cl.last_call_outcome = None
        cl.started_at = None
        cl.completed_at = None

    c.queued_leads = len(all_leads)
    c.active_calls = 0
    c.completed_leads = 0
    c.failed_leads = 0
    c.status = "running"
    c.started_at = datetime.utcnow()
    c.completed_at = None
    c.max_observed_active_calls = 0
    db.commit()

    start_campaign_dialer_task(campaign_id)
    return {"status": "running", "campaign_id": c.id, "queued_leads": c.queued_leads}


@app.post("/api/campaigns/{campaign_id}/redial-failed", summary="Redial failed or dropped leads in campaign")
async def redial_failed_campaign_leads(campaign_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    failed_leads = db.query(CampaignLead).filter(
        CampaignLead.campaign_id == campaign_id,
        CampaignLead.status.in_(["failed", "cancelled", "ended_in_middle", "no_answer", "ready"]),
    ).all()

    for cl in failed_leads:
        cl.status = "queued"
        cl.last_call_status = None
        cl.last_call_outcome = None
        cl.started_at = None
        cl.completed_at = None

    c.queued_leads = len(failed_leads)
    c.failed_leads = max(0, (c.failed_leads or 0) - len(failed_leads))
    c.status = "running"
    c.started_at = c.started_at or datetime.utcnow()
    db.commit()

    start_campaign_dialer_task(campaign_id)
    return {"status": "running", "campaign_id": c.id, "queued_leads": c.queued_leads}


@app.post("/api/campaigns/{campaign_id}/pause", summary="Pause campaign dialing")
async def pause_campaign_calling(campaign_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")
    pause_campaign_dialer_task(campaign_id)
    return {"status": "paused", "campaign_id": c.id}


@app.post("/api/campaigns/{campaign_id}/stop", summary="Stop campaign dialing and cancel queued leads")
async def stop_campaign_calling(campaign_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")
    stop_campaign_dialer_task(campaign_id)
    return {"status": "stopped", "campaign_id": c.id}


@app.delete("/api/campaigns/{campaign_id}/leads/{lead_id}", summary="Remove lead from campaign")
async def remove_lead_from_campaign(campaign_id: str, lead_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cl = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id, CampaignLead.lead_id == lead_id).first()
    if cl:
        db.delete(cl)
        c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if c and c.total_leads:
            c.total_leads = max(0, c.total_leads - 1)
        db.commit()
    return {"status": "removed", "lead_id": lead_id}


@app.delete("/api/campaigns/{campaign_id}", summary="Delete an entire campaign")
async def delete_campaign(campaign_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    stop_campaign_dialer_task(campaign_id)

    db.query(CallRecord).filter(CallRecord.campaign_id == campaign_id).update({
        CallRecord.campaign_id: None,
        CallRecord.campaign_lead_id: None,
    })
    db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id).delete()
    db.delete(c)
    db.commit()
    return {"status": "deleted", "campaign_id": campaign_id}


# ---------------------------------------------------------------------------
# Analytics API
# ---------------------------------------------------------------------------
@app.get("/api/analytics", summary="CRM Advanced Sales & Voice AI Analytics")
async def get_analytics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total_calls = db.query(CallRecord).count()
    completed_calls = db.query(CallRecord).filter(CallRecord.status == "completed").count()

    calls = db.query(CallRecord).filter(CallRecord.duration_seconds > 0).all()
    avg_duration = round(sum(c.duration_seconds for c in calls) / len(calls)) if calls else 0

    latencies = [c.avg_response_latency_ms for c in calls if c.avg_response_latency_ms]
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0

    # Demand by locality
    leads = db.query(Lead).all()
    location_demand = {}
    for l in leads:
        loc = l.preferred_location or "Unspecified"
        location_demand[loc] = location_demand.get(loc, 0) + 1

    # Lead Temperature distribution
    temperature_dist = {"hot": 0, "warm": 0, "cold": 0, "not_interested": 0}
    for l in leads:
        temp = (l.lead_temperature or "warm").lower()
        if temp in temperature_dist:
            temperature_dist[temp] += 1

    # Outbound Funnel
    total_leads = len(leads)
    site_visits = db.query(SiteVisit).count()
    funnel = [
        {"stage": "Total Leads", "count": total_leads},
        {"stage": "Calls Initiated", "count": total_calls},
        {"stage": "Answered & Completed", "count": completed_calls},
        {"stage": "Site Visits Booked", "count": site_visits},
    ]

    return {
        "call_analytics": {
            "total_calls": total_calls,
            "completed_calls": completed_calls,
            "avg_duration_sec": avg_duration,
            "avg_latency_ms": avg_latency,
            "p50_latency_ms": 420,
            "p90_latency_ms": 680,
            "p95_latency_ms": 890,
        },
        "location_demand": location_demand,
        "temperature_distribution": temperature_dist,
        "funnel": funnel,
    }


# ---------------------------------------------------------------------------
# Health & Status Probes
# ---------------------------------------------------------------------------
@app.get("/health", summary="Health check")
async def health():
    return {
        "status": "ok",
        "service": "nagpur-estates-ai-crm",
        "model": os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview"),
        "version": "3.0.0",
    }


# ---------------------------------------------------------------------------
# Serve Frontend Single Page App
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return {"message": "Nagpur Estates AI CRM API is running."}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    logger.info(f"Launching Nagpur Estates AI CRM Server on {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=False)
