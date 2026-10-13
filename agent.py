from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import contextlib
import websockets
from websockets.asyncio import client as ws_async_client
import google.genai.live as g_live

# 1. Prioritize IPv4 DNS resolution for Google APIs to prevent Windows/ISP IPv6 WebSocket handshake timeouts
_orig_getaddrinfo = socket.getaddrinfo
def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    if host and isinstance(host, str) and ("googleapis.com" in host or "google.com" in host):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    return _orig_getaddrinfo(host, port, family, type, proto, flags)
socket.getaddrinfo = _getaddrinfo_ipv4

# 2. Patch websockets connect default open_timeout to 35.0s and disable ping_interval to prevent keepalive drops
_orig_ws_connect = g_live.ws_connect
def _robust_ws_connect(uri, *args, **kwargs):
    kwargs.setdefault("open_timeout", 35.0)
    kwargs.setdefault("close_timeout", 15.0)
    # Google Gemini Live does not echo WebSocket ping/pong control frames; disabling client pings prevents false 1011 keepalive drops
    kwargs["ping_interval"] = None
    kwargs["ping_timeout"] = None
    return _orig_ws_connect(uri, *args, **kwargs)
g_live.ws_connect = _robust_ws_connect

# 3. Patch AsyncLive.connect with automatic retry & exponential backoff on handshake timeout
_orig_async_live_connect = g_live.AsyncLive.connect
@contextlib.asynccontextmanager
async def _robust_async_live_connect(self, *args, **kwargs):
    max_handshake_retries = 3
    for attempt in range(1, max_handshake_retries + 1):
        try:
            async with _orig_async_live_connect(self, *args, **kwargs) as session:
                yield session
                return
        except (TimeoutError, asyncio.TimeoutError, websockets.exceptions.WebSocketException) as e:
            if attempt < max_handshake_retries:
                logging.getLogger("gemini_live_agent").warning(
                    f"GEMINI_LIVE_HANDSHAKE_TIMEOUT | attempt={attempt}/{max_handshake_retries} | "
                    f"error={e} | Retrying WebSocket handshake in {attempt * 1.5}s..."
                )
                await asyncio.sleep(attempt * 1.5)
            else:
                logging.getLogger("gemini_live_agent").error(
                    f"GEMINI_LIVE_HANDSHAKE_FATAL | Handshake failed after {max_handshake_retries} attempts: {e}"
                )
                raise
g_live.AsyncLive.connect = _robust_async_live_connect

import numpy as np
from dotenv import load_dotenv
from google.genai import types as genai_types
import livekit.api as lapi
from livekit import rtc
from livekit.agents import (
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents import voice
from livekit.plugins import google

from db.models import Lead, Property, AgentScript, AgentConfig, Campaign
from db.session import get_db_session, init_db
from services.booking_service import book_site_visit, schedule_callback as schedule_crm_callback
from services.call_service import add_call_turn_record, hangup_call, update_live_call_state
from services.lead_service import create_or_update_lead, mask_phone_number
from services.rag_service import search_properties_hybrid
from services.domain_registry import (
    DOMAIN_PRESETS,
    get_domain_preset,
    resolve_voice_gender,
    render_gender_text,
)

# Load environment variables
load_dotenv()

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("gemini_live_agent")

COMPANY_NAME = os.getenv("COMPANY_NAME", "Nagpur Estates")
AGENT_DISPLAY_NAME = os.getenv("AGENT_DISPLAY_NAME", "Priya")
BENCHMARK_MODE = os.getenv("BENCHMARK_MODE", "true").lower() in ("true", "1")
MAX_CALL_DURATION_SECONDS = int(os.getenv("MAX_CALL_DURATION_SECONDS", "600"))


def calculate_percentile(data: List[float], pct: float) -> Optional[float]:
    """Calculate percentile from numeric list. Returns None if insufficient data."""
    if not data:
        return None
    sd = sorted(data)
    k = (len(sd) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    return sd[f] + (k - f) * (sd[c] - sd[f]) if c < len(sd) else sd[f]


# ---------------------------------------------------------------------------
# Call State Machine
# ---------------------------------------------------------------------------
class CallState(Enum):
    INITIALIZING = "initializing"
    ROOM_CONNECTED = "room_connected"
    WAITING_FOR_CUSTOMER = "waiting_for_customer"
    CUSTOMER_CONNECTED = "customer_connected"
    GREETING_STARTED = "greeting_started"
    CONVERSATION_ACTIVE = "conversation_active"
    CALL_ENDING = "call_ending"
    CALL_ENDED = "call_ended"


# ---------------------------------------------------------------------------
# Structured Lead State & Domain Representation
# ---------------------------------------------------------------------------
@dataclass
@dataclass
class LeadState:
    lead_id: Optional[str] = None
    customer_name: str = "Customer"
    phone_number: str = ""
    domain: str = "real_estate"
    # Real estate specific
    preferred_location: Optional[str] = None
    property_type: Optional[str] = None
    bhk: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    purchase_purpose: Optional[str] = None
    purchase_timeline: Optional[str] = None
    loan_required: Optional[bool] = None
    site_visit_interested: bool = False
    site_visit_datetime: Optional[str] = None
    # Healthcare / Clinic specific
    patient_concern: Optional[str] = None
    specialty: Optional[str] = None
    appointment_datetime: Optional[str] = None
    doctor_name: Optional[str] = None
    # E-commerce specific
    order_id: Optional[str] = None
    order_issue: Optional[str] = None
    # Education specific
    course_name: Optional[str] = None
    academic_qualification: Optional[str] = None
    counseling_datetime: Optional[str] = None
    # General & Call tracking
    service_inquiry: Optional[str] = None
    callback_required: bool = False
    callback_datetime: Optional[str] = None
    whatsapp_followup: bool = False
    dnd_requested: bool = False
    lead_temperature: Optional[str] = "warm"
    next_action: Optional[str] = "qualify"
    matched_properties: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Multi-Domain Consultative System Prompt for Gemini 3.1 Live
# ---------------------------------------------------------------------------
@dataclass
class AgentPromptContext:
    system_prompt: str
    greeting_speech: str
    greeting_prompt: str
    voice: str
    temperature: float
    agent_name: str
    company_name: str
    domain: str = "real_estate"
    gender: str = "female"


def build_system_prompt(
    customer_name: str,
    agent_config_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    override_domain: Optional[str] = None,
    override_gender: Optional[str] = None,
    override_voice: Optional[str] = None,
    override_agent_name: Optional[str] = None,
    override_company_name: Optional[str] = None,
) -> AgentPromptContext:
    """
    Compiles dynamic system prompt, opening greetings, and voice model parameters:
    1. Loads active or campaign-specific AgentConfig from database.
    2. Resolves domain preset (Real Estate, Healthcare, E-Commerce, Education, etc.).
    3. Resolves voice and gender with automatic Hindi/Hinglish grammatical alignment.
    4. Loads active modular training playbooks (AgentScript) for the active domain.
    5. Interpolates dynamic variables ({customer_name}, {agent_name}, {company_name}).
    6. Ensures strict audio speech purity (preventing leaked tokens like 'get response').
    """
    cust_display = customer_name if customer_name and customer_name.lower() != "customer" else ""
    cust_ji = f"{cust_display} ji" if cust_display else "ji"
    name_clause = f"The customer's name is {cust_display}." if cust_display else ""

    cfg = None
    custom_scripts_section = ""
    domain = override_domain or "real_estate"
    voice = override_voice or os.getenv("GEMINI_VOICE", "Aoede").strip()
    gender = override_gender or "female"
    temperature = 0.6
    agent_name = override_agent_name
    company_name = override_company_name

    raw_role_desc = None
    raw_philosophy = None
    raw_funnel = None
    raw_guardrails = None
    raw_override = None
    known_raw = None
    unknown_raw = None
    pivot_raw = None

    try:
        with get_db_session() as db:
            # 1. Fetch AgentConfig
            if agent_config_id:
                cfg = db.query(AgentConfig).filter(AgentConfig.id == agent_config_id).first()
            elif campaign_id:
                cmp = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if cmp and cmp.agent_config_id:
                    cfg = db.query(AgentConfig).filter(AgentConfig.id == cmp.agent_config_id).first()

            if not cfg:
                cfg = db.query(AgentConfig).filter(AgentConfig.is_active == True).order_by(AgentConfig.updated_at.desc(), AgentConfig.created_at.desc()).first()

            if cfg:
                domain = override_domain or getattr(cfg, "domain", "real_estate") or "real_estate"
                voice = override_voice or getattr(cfg, "voice", "Aoede") or voice
                gender = override_gender or getattr(cfg, "gender", None) or resolve_voice_gender(voice)
                agent_name = override_agent_name or cfg.agent_display_name
                company_name = override_company_name or cfg.company_name
                temperature = cfg.temperature if cfg.temperature is not None else temperature
                raw_role_desc = cfg.role_description
                raw_philosophy = cfg.conversation_philosophy
                raw_funnel = cfg.sales_funnel_stages
                raw_guardrails = cfg.objection_guardrails
                raw_override = cfg.custom_system_prompt_override
                known_raw = cfg.greeting_known_lead
                unknown_raw = cfg.greeting_unknown_lead
                pivot_raw = cfg.wrong_number_pivot
            else:
                gender = override_gender or resolve_voice_gender(voice)

            # 2. Fetch active training scripts and resolve primary script for this domain
            primary_script = None
            # Check campaign explicit selected_script_id first
            if campaign_id:
                cmp_obj = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if cmp_obj and getattr(cmp_obj, "selected_script_id", None):
                    primary_script = db.query(AgentScript).filter(AgentScript.id == cmp_obj.selected_script_id, AgentScript.is_active == True).first()

            # Then check cfg.selected_script_id
            if not primary_script and cfg and getattr(cfg, "selected_script_id", None):
                primary_script = db.query(AgentScript).filter(AgentScript.id == cfg.selected_script_id, AgentScript.is_active == True).first()

            active_scripts = (
                db.query(AgentScript)
                .filter(AgentScript.is_active == True)
                .filter((AgentScript.domain == domain) | (AgentScript.domain == "all"))
                .order_by(AgentScript.is_primary.desc(), AgentScript.created_at.asc())
                .all()
            )

            # If still no primary_script, check if any active_script has is_primary == True
            if not primary_script:
                for s in active_scripts:
                    if getattr(s, "is_primary", False):
                        primary_script = s
                        break

            primary_part = ""
            if primary_script:
                primary_part = (
                    f"================================================================================\n"
                    f"🚨 CRITICAL PRIMARY DIALOGUE SCRIPT (HIGHEST PRIORITY - STRICT ADHERENCE REQUIRED)\n"
                    f"Playbook: \"{primary_script.title}\" (Category: {primary_script.category})\n\n"
                    f"CRITICAL INSTRUCTIONS FOR VOICE SPEECH & STT (SPEECH-TO-TEXT) UNDERSTANDING:\n"
                    f"1. BLUEPRINT EXECUTION: You MUST strictly adhere to the conversation sequence, dialogue turns, and objections defined below as your primary operating blueprint.\n"
                    f"2. STT & VOCABULARY TUNING: Listen specifically for the customer keywords, phrases, and expected responses outlined in this script.\n"
                    f"3. STEP PROGRESSION: Move sequentially through the steps (Opener -> Hook -> Objections -> Close) as instructed.\n"
                    f"4. HIGHEST PRECEDENCE: If any general sales guideline or philosophy conflicts with this specific primary script, THIS SCRIPT TAKES HIGHEST PRECEDENCE.\n\n"
                    f"[PRIMARY SCRIPT BLUEPRINT]\n"
                    f"{primary_script.content}\n"
                    f"================================================================================"
                )

            secondary_scripts = [s for s in active_scripts if not primary_script or s.id != primary_script.id]
            secondary_part = ""
            if secondary_scripts:
                parts = [f"### Supporting Playbook: {s.title} (Category: {s.category})\n{s.content}" for s in secondary_scripts]
                secondary_part = "### SUPPORTING TRAINING PLAYBOOKS & GUIDELINES:\n" + "\n\n".join(parts)

            combined_scripts = "\n\n".join(p for p in [primary_part, secondary_part] if p).strip()
            if combined_scripts:
                custom_scripts_section = "\n\nACTIVE CUSTOM TRAINING PLAYBOOKS (Configured in Studio):\n" + combined_scripts
    except Exception as e:
        logger.warning(f"Could not load dynamic prompt config/scripts from DB: {e}")

    # Fallback to domain preset if unconfigured
    preset = get_domain_preset(domain)
    gender = gender or resolve_voice_gender(voice)
    default_name = preset["default_male_name"] if gender == "male" else preset["default_female_name"]
    agent_name = agent_name or default_name
    company_name = company_name or preset["default_company"]

    raw_role_desc = raw_role_desc or preset["role_description"]
    raw_philosophy = raw_philosophy or preset["conversation_philosophy"]
    raw_funnel = raw_funnel or preset["sales_funnel_stages"]
    raw_guardrails = raw_guardrails or preset["objection_guardrails"]
    known_raw = known_raw or preset["greeting_known_lead"]
    unknown_raw = unknown_raw or preset["greeting_unknown_lead"]
    pivot_raw = pivot_raw or preset["wrong_number_pivot"]

    # Variable replacer and gender grammar renderer
    def render_template(tmpl: str) -> str:
        if not tmpl:
            return ""
        rendered = (
            tmpl.replace("{customer_name}", cust_display or "ji")
            .replace("{cust_display}", cust_display or "ji")
            .replace("{cust_ji}", cust_ji)
            .replace("{agent_name}", agent_name)
            .replace("{company_name}", company_name)
        )
        return render_gender_text(rendered, gender=gender)

    known_speech = render_template(known_raw)
    unknown_speech = render_template(unknown_raw)
    pivot_speech = render_template(pivot_raw)
    if custom_scripts_section:
        custom_scripts_section = render_template(custom_scripts_section)

    domain_intro_map = {
        "real_estate": f"Great! Main {agent_name} {{v_bol}} {company_name} se. Aapne property ke liye enquiry ki thi, toh kya abhi do minute baat ho sakti hai?",
        "clinic_hospital": f"Great! Main {agent_name} {{v_bol}} {company_name} se. Aapne doctor consultation ya healthcare guidance ke liye enquiry ki thi, toh kya abhi do minute baat ho sakti hai?",
        "ecommerce": f"Great! Main {agent_name} {{v_bol}} {company_name} se. Main aapke order ya delivery update ke regarding call {{v_kar_rahi}} hoon, kya abhi do minute baat ho sakti hai?",
        "education": f"Great! Main {agent_name} {{v_bol}} {company_name} se. Aapne course admission aur campus counseling ke liye enquiry ki thi, toh kya abhi do minute baat ho sakti hai?",
        "general_business": f"Great! Main {agent_name} {{v_bol}} {company_name} se. Aapne hamare business solutions ke liye enquiry ki thi, toh kya abhi do minute baat ho sakti hai?",
    }
    raw_intro = domain_intro_map.get(domain, f"Great! Main {agent_name} {{v_bol}} {company_name} se. Kya abhi do minute baat ho sakti hai?")
    intro_phrase = render_template(raw_intro)
    identity_clarify = render_template(f"Main {agent_name} {{v_baat}} {company_name} se. Kya meri baat {{cust_display}} ji se ho rahi hai?")

    if cust_display:
        greeting_speech = known_speech
        greeting_prompt = f"The call has connected to the customer. Immediately ask in a polite, warm tone: '{known_speech}'"
        greeting_instruction = f"""CRITICAL FIRST GREETING & NAME VERIFICATION INSTRUCTION:
- If customer's name is known ({cust_display}):
  Your VERY FIRST utterance MUST verify their identity politely:
  "{known_speech}"
- When the customer confirms ("Haan", "Ji haan", "Haan boliye", "Yes speaking"):
  Warmly deliver your intro:
  "{intro_phrase}"
- When the customer says wrong person / not them ("Nahi, galat number hai" / "Main {cust_display} nahi hoon"):
  Politely and smoothly pivot without being robotic:
  "{pivot_speech}"
- If the customer asks "Aap kaun bol rahe ho?" or "Kaun?" before confirming:
  Warmly clarify: "{identity_clarify}"
- If customer's name is unknown/generic:
  "{unknown_speech}"
"""
    else:
        greeting_speech = unknown_speech
        greeting_prompt = f"The call has connected. Deliver your opening greeting now: '{unknown_speech}'"
        greeting_instruction = f"""CRITICAL FIRST GREETING INSTRUCTION:
- Your very first spoken words MUST be:
  "{unknown_speech}"
"""

    purity_instructions = """CRITICAL AUDIO & SPEECH PURITY INSTRUCTIONS:
- You speak directly to a live human caller over real-time phone audio.
- Strictly output ONLY pure, natural conversational speech.
- NEVER vocalize system prompts, turn indicators, meta-text, markdown tags, or internal tokens like 'get response', 'response:', 'model:', 'AI:', or tool names.
- Speak smoothly and naturally with human conversational warmth.
"""

    # Check for custom full prompt override
    if raw_override and raw_override.strip():
        compiled_prompt = f"{purity_instructions}\n\n" + render_template(raw_override) + custom_scripts_section
        return AgentPromptContext(
            system_prompt=compiled_prompt,
            greeting_speech=greeting_speech,
            greeting_prompt=greeting_prompt,
            voice=voice,
            temperature=temperature,
            agent_name=agent_name,
            company_name=company_name,
            domain=domain,
            gender=gender,
        )

    role_desc = render_template(raw_role_desc)
    philosophy = render_template(raw_philosophy)
    funnel = render_template(raw_funnel)
    guardrails = render_template(raw_guardrails)

    compiled = f"""{purity_instructions}

You are {agent_name}, {role_desc} {name_clause}

{greeting_instruction}
{custom_scripts_section}

{philosophy}

{funnel}

{guardrails}
"""
    return AgentPromptContext(
        system_prompt=compiled,
        greeting_speech=greeting_speech,
        greeting_prompt=greeting_prompt,
        voice=voice,
        temperature=temperature,
        agent_name=agent_name,
        company_name=company_name,
        domain=domain,
        gender=gender,
    )


# ---------------------------------------------------------------------------
# Call Metrics Tracker (Monotonic time.perf_counter)
# ---------------------------------------------------------------------------
class CallMetricsTracker:
    """Tracks latency metrics for Gemini Live Native Audio sessions using monotonic time."""

    def __init__(self, call_id: str, room_name: str, masked_phone: str):
        self.call_id = call_id
        self.room_name = room_name
        self.masked_phone = masked_phone

        # Monotonic timestamps
        self.pc_job_received = time.perf_counter()
        self.pc_room_connected: Optional[float] = None
        self.pc_customer_connected: Optional[float] = None
        self.pc_gemini_session_started: Optional[float] = None
        self.pc_greeting_first_audio: Optional[float] = None
        self.pc_call_ended: Optional[float] = None

        self.wall_started = time.time()
        self.wall_ended: Optional[float] = None

        self.turn_count = 0
        self.interruption_count = 0
        self.turn_latencies: List[float] = []

        self.current_user_speech_end: Optional[float] = None
        self._greeting_audio_recorded = False
        self._greeting_finished = False
        self._finalized = False

    def mark_room_connected(self):
        self.pc_room_connected = time.perf_counter()
        elapsed = (self.pc_room_connected - self.pc_job_received) * 1000
        logger.info(f"ROOM_CONNECTED | call_id={self.call_id} | JOB_TO_ROOM={elapsed:.0f}ms")

    def mark_gemini_session_started(self):
        self.pc_gemini_session_started = time.perf_counter()
        elapsed = (self.pc_gemini_session_started - self.pc_job_received) * 1000
        logger.info(f"GEMINI_SESSION_STARTED | call_id={self.call_id} | t={elapsed:.0f}ms")

    def mark_customer_connected(self):
        self.pc_customer_connected = time.perf_counter()
        if self.pc_room_connected:
            elapsed = (self.pc_customer_connected - self.pc_room_connected) * 1000
            logger.info(f"CUSTOMER_CONNECTED | call_id={self.call_id} | ROOM_TO_CUSTOMER={elapsed:.0f}ms")
        else:
            logger.info(f"CUSTOMER_CONNECTED | call_id={self.call_id}")

    def mark_greeting_requested(self):
        now = time.perf_counter()
        if self.pc_customer_connected:
            latency = (now - self.pc_customer_connected) * 1000
            logger.info(f"GREETING_REQUESTED | call_id={self.call_id} | since_cust_conn={latency:.0f}ms")
        else:
            logger.info(f"GREETING_REQUESTED | call_id={self.call_id}")

    def mark_agent_speech_started(self):
        """Called when assistant audio begins playout."""
        now = time.perf_counter()

        if not self._greeting_audio_recorded and not self._greeting_finished:
            self._greeting_audio_recorded = True
            self.pc_greeting_first_audio = now
            if self.pc_customer_connected:
                latency = (now - self.pc_customer_connected) * 1000
                job_to_greeting = (now - self.pc_job_received) * 1000
                logger.info(
                    f"\n========================================\n"
                    f"GREETING FIRST AUDIO DELIVERED\n"
                    f"Customer → First Audio:  {latency:.0f}ms\n"
                    f"Total Job → First Audio: {job_to_greeting:.0f}ms\n"
                    f"========================================"
                )
            return

        if self._greeting_finished and self.current_user_speech_end:
            latency = (now - self.current_user_speech_end) * 1000
            self.turn_latencies.append(latency)
            self.turn_count += 1
            self.current_user_speech_end = None
            logger.info(f"ASSISTANT_FIRST_AUDIO | call_id={self.call_id} | turn={self.turn_count} | latency_ms={latency:.0f}")

    def mark_greeting_finished(self):
        self._greeting_finished = True

    def mark_user_speech_started(self):
        logger.info(f"USER_SPEECH_STARTED | call_id={self.call_id}")

    def mark_user_speech_ended(self):
        self.current_user_speech_end = time.perf_counter()
        logger.info(f"USER_SPEECH_ENDED | call_id={self.call_id}")

    def mark_interruption(self):
        self.interruption_count += 1
        logger.info(f"INTERRUPTION | call_id={self.call_id} | total={self.interruption_count}")

    def generate_final_report(
        self,
        lead: LeadState,
        call_status: str = "completed",
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate and persist final call report. Guaranteed to run exactly once."""
        if self._finalized:
            return {}
        self._finalized = True

        self.pc_call_ended = time.perf_counter()
        self.wall_ended = time.time()
        duration_sec = int(self.pc_call_ended - self.pc_job_received)
        mm, ss = divmod(duration_sec, 60)

        greeting_ms: Optional[float] = None
        if self.pc_greeting_first_audio and self.pc_customer_connected:
            greeting_ms = round((self.pc_greeting_first_audio - self.pc_customer_connected) * 1000)

        avg_lat = round(sum(self.turn_latencies) / len(self.turn_latencies)) if self.turn_latencies else None
        p50 = round(calculate_percentile(self.turn_latencies, 50)) if self.turn_latencies else None
        p90 = round(calculate_percentile(self.turn_latencies, 90)) if self.turn_latencies else None
        p95 = round(calculate_percentile(self.turn_latencies, 95)) if self.turn_latencies else None
        p99 = round(calculate_percentile(self.turn_latencies, 99)) if self.turn_latencies else None

        active_domain = domain or getattr(lead, "domain", "real_estate") or "real_estate"

        # Build Domain-Adaptive AI Call Summary
        if call_status == "ended_in_middle":
            outcome_val = "ended_in_middle"
            summary_text = (
                f"Customer {lead.customer_name} call ended after {self.turn_count} turns ({duration_sec}s). "
                f"Call was disconnected or customer hung up before confirmation."
            )
        elif call_status == "no_answer":
            outcome_val = "no_answer"
            summary_text = f"Call to {lead.customer_name} was not answered or was rejected."
        elif lead.callback_required or lead.next_action == "callback_scheduled":
            outcome_val = "callback_scheduled"
            time_str = lead.callback_datetime or "scheduled time"
            summary_text = (
                f"Customer {lead.customer_name} requested a callback for {time_str}. "
                f"Lead temperature: {lead.lead_temperature}. Next action: callback_scheduled. Outcome: callback_scheduled."
            )
        elif lead.dnd_requested or lead.next_action in ("dnd", "not_interested"):
            outcome_val = "not_interested"
            summary_text = f"Customer {lead.customer_name} requested DND / not interested. Next action: dnd. Outcome: not_interested."
        else:
            outcome_val = lead.next_action or "completed"
            if active_domain == "clinic_hospital":
                spec = lead.specialty or "doctor consultation"
                slot = lead.appointment_datetime or "OPD hours"
                summary_text = (
                    f"Patient {lead.customer_name} inquired about {spec} (Slot: {slot}). "
                    f"Lead temperature: {lead.lead_temperature}. Next action: {lead.next_action}. Outcome: {outcome_val}."
                )
            elif active_domain == "ecommerce":
                ord_id = f"Order #{lead.order_id}" if lead.order_id else "Order inquiry"
                issue = lead.order_issue or "delivery and return support"
                summary_text = (
                    f"Customer {lead.customer_name} discussed {ord_id} ({issue}). "
                    f"Lead temperature: {lead.lead_temperature}. Next action: {lead.next_action}. Outcome: {outcome_val}."
                )
            elif active_domain == "education":
                course = lead.course_name or "academic and career training"
                summary_text = (
                    f"Student/Parent {lead.customer_name} inquired about {course}. "
                    f"Lead temperature: {lead.lead_temperature}. Next action: {lead.next_action}. Outcome: {outcome_val}."
                )
            elif active_domain == "general_business":
                svc = lead.service_inquiry or "business solutions and advisory"
                summary_text = (
                    f"Client {lead.customer_name} inquired regarding {svc}. "
                    f"Lead temperature: {lead.lead_temperature}. Next action: {lead.next_action}. Outcome: {outcome_val}."
                )
            else:
                # Real Estate
                loc = lead.preferred_location or "Nagpur"
                bhk_val = lead.bhk or "Property"
                try:
                    b_max = float(lead.budget_max) if lead.budget_max is not None else None
                    budget_val = f"within ₹{b_max/100000:.0f} Lakhs" if b_max else "Budget discussed"
                except (ValueError, TypeError):
                    budget_val = "Budget discussed"

                if lead.site_visit_interested or lead.next_action == "site_visit_booked":
                    summary_text = (
                        f"Customer {lead.customer_name} scheduled a site visit for {bhk_val} in {loc} ({lead.site_visit_datetime or 'weekend'}). "
                        f"Lead temperature: hot. Next action: site_visit_booked. Outcome: site_visit_booked."
                    )
                elif lead.preferred_location or lead.bhk:
                    summary_text = (
                        f"Customer {lead.customer_name} inquired about {bhk_val} in {loc} ({budget_val}). "
                        f"Lead temperature: {lead.lead_temperature}. Next action: {lead.next_action}. Outcome: {outcome_val}."
                    )
                else:
                    summary_text = (
                        f"Customer {lead.customer_name} was contacted for property advisory. "
                        f"Lead temperature: {lead.lead_temperature}. Next action: {lead.next_action}. Outcome: {outcome_val}."
                    )

        report = {
            "call_id": self.call_id,
            "room_name": self.room_name,
            "customer_name": lead.customer_name,
            "phone_number_masked": self.masked_phone,
            "status": call_status,
            "started_at": self.wall_started,
            "ended_at": self.wall_ended or time.time(),
            "duration_seconds": duration_sec,
            "greeting_latency_ms": greeting_ms,
            "avg_response_latency_ms": avg_lat,
            "p50_latency_ms": p50,
            "p90_latency_ms": p90,
            "p95_latency_ms": p95,
            "p99_latency_ms": p99,
            "turns_count": self.turn_count,
            "interruptions_count": self.interruption_count,
            "lead_temperature": lead.lead_temperature,
            "next_action": lead.next_action,
            "outcome": outcome_val,
            "summary": summary_text,
        }

        # Persist report to Call Service & DB
        update_live_call_state(self.call_id, report)

        # Update Lead record in CRM
        if lead.phone_number:
            try:
                create_or_update_lead(
                    phone_number=lead.phone_number,
                    name=lead.customer_name,
                    preferred_location=lead.preferred_location,
                    property_type=lead.property_type,
                    bhk=lead.bhk,
                    budget_max=lead.budget_max,
                    purchase_purpose=lead.purchase_purpose,
                    purchase_timeline=lead.purchase_timeline,
                    lead_temperature=lead.lead_temperature,
                    stage="site_visit" if lead.site_visit_interested else ("qualified" if lead.preferred_location else "contacted"),
                )
            except Exception as lead_err:
                logger.warning(f"LEAD_UPDATE_ERROR | call_id={self.call_id} | {lead_err}")

        if BENCHMARK_MODE:
            logger.info(
                f"\n====================================================\n"
                f"VOICE CALL BENCHMARK [{active_domain.upper()}]\n"
                f"Call ID:                       {self.call_id}\n"
                f"Duration:                      {mm:02d}:{ss:02d}\n"
                f"Greeting first audio:          {greeting_ms or 'N/A'} ms\n"
                f"Avg Turn Latency:              {avg_lat or 'N/A'} ms\n"
                f"P50 / P90:                     {p50 or 'N/A'} ms / {p90 or 'N/A'} ms\n"
                f"Lead Outcome:                  {lead.next_action}\n"
                f"===================================================="
            )

        return report


# ---------------------------------------------------------------------------
# Function Tools for Gemini 3.1 Live (Multi-Domain)
# ---------------------------------------------------------------------------
def create_tools(lead_state: LeadState, call_id: str, trigger_hangup_cb: Any, domain: str = "real_estate") -> list:
    """Create asynchronous function tools tailored to the active business domain."""

    # 1. Universal Tools (All Domains)
    @llm.function_tool(description="Schedule a callback when the customer is busy or requests to speak later.")
    async def create_callback(
        preferred_time: str,
        reason: str = "Customer requested later call",
    ) -> str:
        """Schedule a callback in CRM."""
        lead_state.callback_required = True
        lead_state.callback_datetime = preferred_time
        lead_state.next_action = "callback_scheduled"
        lead_state.lead_temperature = "warm"

        logger.info(f"TOOL_EXECUTED | create_callback | call_id={call_id} | time={preferred_time}")

        if lead_state.lead_id:
            schedule_crm_callback(
                lead_id=lead_state.lead_id,
                scheduled_at=preferred_time,
                reason=reason,
                call_id=call_id,
                customer_name=lead_state.customer_name,
                phone_number=lead_state.phone_number,
            )

        update_live_call_state(call_id, {
            "stage": "callback_scheduled",
            "next_action": "callback_scheduled",
        })

        return f"Callback successfully scheduled for {preferred_time}."

    @llm.function_tool(description="Update lead or customer qualification state (preferences, notes, temperature).")
    async def update_lead(
        preferred_location: Optional[str] = None,
        property_type: Optional[str] = None,
        bhk: Optional[str] = None,
        budget_max: Optional[float] = None,
        purchase_purpose: Optional[str] = None,
        purchase_timeline: Optional[str] = None,
        lead_temperature: Optional[str] = None,
    ) -> str:
        """Update qualification criteria."""
        if preferred_location:
            lead_state.preferred_location = preferred_location
        if property_type:
            lead_state.property_type = property_type
        if bhk:
            lead_state.bhk = bhk
        if budget_max:
            lead_state.budget_max = budget_max
        if purchase_purpose:
            lead_state.purchase_purpose = purchase_purpose
        if purchase_timeline:
            lead_state.purchase_timeline = purchase_timeline
        if lead_temperature:
            lead_state.lead_temperature = lead_temperature.lower()

        logger.info(f"TOOL_EXECUTED | update_lead | call_id={call_id} | temp={lead_temperature}")
        return "Lead details updated."

    @llm.function_tool(description="Mark contact as Do Not Disturb (DND) or Not Interested when requested.")
    async def mark_dnd(
        reason: str = "Customer requested DND / Not interested",
    ) -> str:
        """Mark contact as DND."""
        lead_state.dnd_requested = True
        lead_state.lead_temperature = "not_interested"
        lead_state.next_action = "dnd"

        logger.info(f"TOOL_EXECUTED | mark_dnd | call_id={call_id} | reason={reason}")
        update_live_call_state(call_id, {
            "lead_temperature": "not_interested",
            "next_action": "dnd",
            "stage": "dnd",
        })
        return "Customer marked as DND."

    @llm.function_tool(
        description="Politely end the call ONLY after you have delivered your final goodbye words to the customer and the conversation is completely finished. Never call this while asking a question or awaiting customer response."
    )
    async def end_call(
        reason: str = "conversation_complete",
    ) -> str:
        """Gracefully request call termination after speaking final words."""
        logger.info(f"TOOL_EXECUTED | end_call | call_id={call_id} | reason={reason}")
        trigger_hangup_cb(reason)
        return "Call ending initiated."

    base_tools = [create_callback, update_lead, mark_dnd, end_call]

    # 2. Healthcare / Hospital & Clinic Tools
    if domain == "clinic_hospital":
        @llm.function_tool(description="Check available doctor consultation OPD timings and slots by medical specialty.")
        async def check_doctor_availability(
            specialty: str,
            preferred_date: Optional[str] = None,
        ) -> str:
            """Check clinic OPD availability."""
            lead_state.specialty = specialty
            lead_state.lead_temperature = "warm"
            logger.info(f"TOOL_EXECUTED | check_doctor_availability | call_id={call_id} | spec={specialty}")
            return (
                f"Available OPD slots for {specialty}: Morning 10:00 AM to 1:00 PM, "
                f"and Evening 5:00 PM to 8:30 PM. Priority tokens available."
            )

        @llm.function_tool(description="Book a doctor consultation appointment for a patient.")
        async def book_appointment(
            patient_name: str,
            specialty: str,
            preferred_datetime: str,
            doctor_name: Optional[str] = None,
        ) -> str:
            """Confirm patient appointment booking."""
            lead_state.customer_name = patient_name
            lead_state.specialty = specialty
            lead_state.appointment_datetime = preferred_datetime
            lead_state.doctor_name = doctor_name or f"Senior {specialty} Consultant"
            lead_state.lead_temperature = "hot"
            lead_state.next_action = "appointment_confirmed"
            logger.info(f"TOOL_EXECUTED | book_appointment | call_id={call_id} | patient={patient_name} | slot={preferred_datetime}")
            update_live_call_state(call_id, {"stage": "appointment_confirmed", "lead_temperature": "hot", "next_action": "appointment_confirmed"})
            return (
                f"Appointment confirmed for {patient_name} with {lead_state.doctor_name} "
                f"on {preferred_datetime}. Details and location map sent via WhatsApp."
            )

        @llm.function_tool(description="Get clinic facilities, departments, and consultation fee structure.")
        async def get_clinic_services(
            query: Optional[str] = None,
        ) -> str:
            """Retrieve clinic facilities overview."""
            return (
                "Our clinic features 24/7 Pharmacy, Digital X-Ray, Computerized Pathology Lab, "
                "and OPD consultations across General Medicine, Orthopedics, Pediatrics, Cardiology, and Dental."
            )

        return base_tools + [check_doctor_availability, book_appointment, get_clinic_services]

    # 3. E-Commerce & Customer Support Tools
    elif domain == "ecommerce":
        @llm.function_tool(description="Check real-time order tracking status and delivery updates.")
        async def track_order_status(
            order_id: Optional[str] = None,
        ) -> str:
            """Fetch tracking status for customer's order."""
            lead_state.order_id = order_id or "ORD-9842"
            lead_state.next_action = "order_status_shared"
            logger.info(f"TOOL_EXECUTED | track_order_status | call_id={call_id} | order={lead_state.order_id}")
            return f"Order #{lead_state.order_id} is in transit with priority courier. Expected delivery tomorrow by 4:00 PM."

        @llm.function_tool(description="Initiate a free doorstep product return or replacement request.")
        async def request_order_return(
            order_id: str,
            reason: str,
        ) -> str:
            """Initiate return and reverse courier pickup."""
            lead_state.order_id = order_id
            lead_state.order_issue = reason
            lead_state.next_action = "return_initiated"
            logger.info(f"TOOL_EXECUTED | request_order_return | call_id={call_id} | order={order_id} | reason={reason}")
            return (
                f"Doorstep return pickup initiated for Order #{order_id}. Courier will visit within 24 hours. "
                f"Full refund will be credited immediately upon pickup."
            )

        return base_tools + [track_order_status, request_order_return]

    # 4. Education & Admissions Counseling Tools
    elif domain == "education":
        @llm.function_tool(description="Get curriculum, duration, and placement records for career courses.")
        async def get_course_details(
            course_name: str,
        ) -> str:
            """Retrieve academic course details."""
            lead_state.course_name = course_name
            lead_state.lead_temperature = "warm"
            logger.info(f"TOOL_EXECUTED | get_course_details | call_id={call_id} | course={course_name}")
            return (
                f"The {course_name} program is 4 months intensive with 80% practical capstone projects, "
                f"industry mentorship, and 100% placement assistance with top tech firms."
            )

        @llm.function_tool(description="Schedule a free 1-on-1 counseling session or campus demo class.")
        async def schedule_campus_counseling(
            student_name: str,
            course_name: str,
            preferred_datetime: str,
        ) -> str:
            """Book counseling session on campus."""
            lead_state.customer_name = student_name
            lead_state.course_name = course_name
            lead_state.counseling_datetime = preferred_datetime
            lead_state.lead_temperature = "hot"
            lead_state.next_action = "counseling_booked"
            logger.info(f"TOOL_EXECUTED | schedule_campus_counseling | call_id={call_id} | student={student_name} | slot={preferred_datetime}")
            return f"Free counseling session confirmed for {student_name} on {preferred_datetime}. Campus pass sent via WhatsApp."

        return base_tools + [get_course_details, schedule_campus_counseling]

    # 5. General Business & B2B Tools
    elif domain == "general_business":
        @llm.function_tool(description="Record prospective client business needs and scope for consulting proposals.")
        async def record_business_inquiry(
            service_needed: str,
            budget_or_scale: Optional[str] = None,
        ) -> str:
            """Record B2B requirements."""
            lead_state.service_inquiry = service_needed
            lead_state.lead_temperature = "warm"
            lead_state.next_action = "proposal_followup"
            logger.info(f"TOOL_EXECUTED | record_business_inquiry | call_id={call_id} | svc={service_needed}")
            return f"Business requirement for {service_needed} recorded. Senior consultant follow-up scheduled."

        return base_tools + [record_business_inquiry]

    # 6. Real Estate Inventory & Site Visit Tools (Default)
    else:
        @llm.function_tool(description="Search available residential inventory using location, BHK, property type, and budget.")
        async def search_properties(
            location: str,
            property_type: str = "Flat",
            bhk: Optional[str] = None,
            budget_max: Optional[float] = None,
            query: Optional[str] = None,
        ) -> str:
            """Execute hybrid SQL + semantic RAG search across properties."""
            lead_state.preferred_location = location
            lead_state.property_type = property_type
            if bhk:
                lead_state.bhk = bhk
            if budget_max:
                lead_state.budget_max = budget_max
            lead_state.lead_temperature = "warm"
            lead_state.next_action = "property_recommendation"

            logger.info(f"TOOL_EXECUTED | search_properties | call_id={call_id} | loc={location} | bhk={bhk} | budget={budget_max}")

            rag_res = search_properties_hybrid(
                location=location,
                property_type=property_type,
                bhk=bhk,
                budget_max=budget_max,
                query_text=query or f"{bhk} in {location}",
                call_id=call_id,
                top_k=2,
            )

            matches = rag_res.get("matches", [])
            if not matches:
                return f"Currently checking inventory in {location}. Specialist will share customized layout options."

            lead_state.matched_properties = matches
            update_live_call_state(call_id, {"matched_properties": matches, "stage": "property_matched"})

            top = matches[0]
            amenity_summary = top["amenities"].split(",")[0] if top["amenities"] else "Prime amenities"
            return (
                f"Found {top['project_name']} in {top['location']}: {top['bhk']} {top['property_type']} "
                f"priced at {top['price_display']}, {top['possession_status']}, with {amenity_summary}."
            )

        @llm.function_tool(description="Get complete trusted details for a specific property project.")
        async def get_property_details(property_id: str) -> str:
            """Retrieve verified property details from database."""
            with get_db_session() as db:
                prop = db.query(Property).filter(Property.id == property_id).first()
                if not prop:
                    return "Property details currently unavailable."
                return (
                    f"{prop.project_name} by {prop.builder_name} in {prop.location}. "
                    f"Configuration: {prop.bhk} ({prop.carpet_area}). Price: {prop.price_display}. "
                    f"RERA ID: {prop.rera_id or 'Verified'}. Amenities: {prop.amenities}."
                )

        @llm.function_tool(description="Schedule a free property site visit for interested buyers.")
        async def schedule_site_visit(
            location: str,
            preferred_datetime: str,
            property_id: Optional[str] = None,
        ) -> str:
            """Book a site visit in CRM."""
            lead_state.site_visit_interested = True
            lead_state.site_visit_datetime = preferred_datetime
            lead_state.preferred_location = location
            lead_state.lead_temperature = "hot"
            lead_state.next_action = "site_visit_booked"

            logger.info(f"TOOL_EXECUTED | schedule_site_visit | call_id={call_id} | loc={location} | dt={preferred_datetime}")

            if lead_state.lead_id:
                book_site_visit(
                    lead_id=lead_state.lead_id,
                    location=location,
                    visit_datetime=preferred_datetime,
                    property_id=property_id,
                    customer_name=lead_state.customer_name,
                    phone_number=lead_state.phone_number,
                    salesperson=AGENT_DISPLAY_NAME,
                )

            update_live_call_state(call_id, {
                "site_visit_status": "confirmed",
                "stage": "site_visit_booked",
                "lead_temperature": "hot",
                "next_action": "site_visit_booked",
            })

            return f"Site visit successfully confirmed for {location} on {preferred_datetime}."

        return base_tools + [search_properties, get_property_details, schedule_site_visit]


# ---------------------------------------------------------------------------
# Worker Config Validation
# ---------------------------------------------------------------------------
def validate_worker_config():
    """Ensure required LiveKit and Google Gemini API keys are configured."""
    required = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "GOOGLE_API_KEY"]
    missing = [v for v in required if not os.getenv(v, "").strip() or "your_" in os.getenv(v, "").lower()]
    if missing:
        logger.error(f"CONFIG_VALIDATION_FAILED | Missing: {', '.join(missing)}")
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    model = os.getenv("GEMINI_LIVE_MODEL", "").strip()
    if model != "gemini-3.1-flash-live-preview":
        raise RuntimeError(f"Invalid GEMINI_LIVE_MODEL='{model}'. Must be 'gemini-3.1-flash-live-preview'.")

    logger.info(f"CONFIG_VALIDATED | model={model}")


# ---------------------------------------------------------------------------
# Worker Entrypoint
# ---------------------------------------------------------------------------
async def entrypoint(ctx: JobContext):
    """LiveKit Agents Worker Entrypoint running Gemini 3.1 Live Native Audio."""
    validate_worker_config()

    call_id = ctx.job.id if ctx.job else f"call-{int(time.time())}"
    room_name = ctx.room.name if ctx.room else "unknown"

    customer_name = "Customer"
    raw_phone = "+910000000000"
    lead_id = None
    campaign_id = None
    agent_config_id = None

    if ctx.job and ctx.job.metadata:
        try:
            meta = json.loads(ctx.job.metadata)
            customer_name = meta.get("customer_name", "Customer")
            raw_phone = meta.get("phone_number", "+910000000000")
            call_id = meta.get("call_id", call_id)
            lead_id = meta.get("lead_id")
            campaign_id = meta.get("campaign_id")
            agent_config_id = meta.get("agent_config_id")
        except Exception as e:
            logger.warning(f"METADATA_PARSE_ERROR | call_id={call_id} | error={e}")

    masked_phone = mask_phone_number(raw_phone)
    logger.info(f"CALL_STARTED | call_id={call_id} | room={room_name} | customer={customer_name} | phone={masked_phone}")

    lead_state = LeadState(lead_id=lead_id, customer_name=customer_name, phone_number=raw_phone)
    metrics = CallMetricsTracker(call_id=call_id, room_name=room_name, masked_phone=masked_phone)
    call_state = CallState.INITIALIZING
    call_status = "initiated"

    def set_state(new_state: CallState):
        nonlocal call_state
        logger.info(f"STATE_CHANGE | call_id={call_id} | {call_state.value} -> {new_state.value}")
        call_state = new_state
        if new_state != CallState.CALL_ENDED:
            update_live_call_state(call_id, {"status": new_state.value})
        else:
            update_live_call_state(call_id, {"status": call_status or "call_ended"})

    # 1. Connect Room Signaling
    logger.info(f"ROOM_CONNECT_START | room={room_name}")
    await ctx.connect()
    metrics.mark_room_connected()
    set_state(CallState.ROOM_CONNECTED)

    session_closed = asyncio.Event()

    # 2. Configure Dynamic Gemini Live Native Audio Model
    prompt_ctx = build_system_prompt(customer_name, agent_config_id=agent_config_id, campaign_id=campaign_id)
    lead_state.domain = prompt_ctx.domain
    system_prompt = prompt_ctx.system_prompt
    gemini_live_model = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview").strip()
    gemini_voice = prompt_ctx.voice or os.getenv("GEMINI_VOICE", "Aoede").strip()
    gemini_temp = prompt_ctx.temperature
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()

    logger.info(f"GEMINI_LIVE_INITIALIZING | model={gemini_live_model} | voice={gemini_voice} | temp={gemini_temp} | agent={prompt_ctx.agent_name} | domain={prompt_ctx.domain} | gender={prompt_ctx.gender}")

    # Hangup trigger callback for end_call tool
    hangup_requested = asyncio.Event()

    def request_hangup(reason: str):
        logger.info(f"HANGUP_REQUESTED | call_id={call_id} | reason={reason}")
        hangup_requested.set()

    tools = create_tools(lead_state, call_id, request_hangup, domain=prompt_ctx.domain)

    from livekit.agents import APIConnectOptions

    realtime_model = google.realtime.RealtimeModel(
        instructions=system_prompt,
        model=gemini_live_model,
        voice=gemini_voice,
        api_key=google_api_key,
        temperature=gemini_temp,
        conn_options=APIConnectOptions(
            max_retry=4,
            retry_interval=2.0,
            timeout=35.0,
        ),
    )
    metrics.mark_gemini_session_started()

    # 3. Customer Connection Detection
    customer_connected = asyncio.Event()

    def is_customer_participant(participant: rtc.RemoteParticipant) -> bool:
        ident = (participant.identity or "").lower()
        if ident.startswith("agent") or ident.startswith("ai-"):
            return False
        return True

    @ctx.room.on("participant_connected")
    def on_participant_connected(participant: rtc.RemoteParticipant):
        identity = participant.identity or ""
        logger.info(f"PARTICIPANT_CONNECTED | call_id={call_id} | identity={identity}")
        if is_customer_participant(participant):
            metrics.mark_customer_connected()
            set_state(CallState.CUSTOMER_CONNECTED)
            customer_connected.set()

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant: rtc.RemoteParticipant):
        identity = participant.identity or ""
        logger.info(f"PARTICIPANT_DISCONNECTED | call_id={call_id} | identity={identity}")
        if is_customer_participant(participant):
            logger.info(f"CUSTOMER_HUNG_UP | call_id={call_id} | Terminating session")
            session_closed.set()

    for p in ctx.room.remote_participants.values():
        if is_customer_participant(p):
            logger.info(f"PARTICIPANT_ALREADY_PRESENT | call_id={call_id} | identity={p.identity}")
            metrics.mark_customer_connected()
            set_state(CallState.CUSTOMER_CONNECTED)
            customer_connected.set()
            break

    set_state(CallState.WAITING_FOR_CUSTOMER)

    # 4. Create Agent subclass with on_enter greeting trigger
    greeting_triggered = False

    class NagpurEstatesAgent(voice.Agent):
        async def on_enter(self) -> None:
            """Trigger Gemini 3.1 Live greeting upon customer pickup."""
            nonlocal greeting_triggered
            if greeting_triggered:
                return
            greeting_triggered = True

            logger.info(f"ON_ENTER | call_id={call_id} | Waiting for customer connection...")
            try:
                await asyncio.wait_for(customer_connected.wait(), timeout=25.0)
            except asyncio.TimeoutError:
                logger.warning(f"CUSTOMER_CONNECT_TIMEOUT | call_id={call_id} | Proceeding with greeting anyway")

            # Allow 0.5s for audio stream and Gemini Live WebSocket session to fully stabilize
            await asyncio.sleep(0.5)

            metrics.mark_greeting_requested()
            logger.info(f"INJECTING_GREETING_TRIGGER | call_id={call_id}")

            greeting_prompt = prompt_ctx.greeting_prompt
            fallback_speech = prompt_ctx.greeting_speech

            try:
                rt_session = getattr(self, "realtime_llm_session", None)
                if rt_session:
                    if hasattr(rt_session, "_start_new_generation"):
                        rt_session._start_new_generation()
                    if hasattr(rt_session, "_send_client_event"):
                        rt_session._send_client_event(
                            genai_types.LiveClientContent(
                                turns=[
                                    genai_types.Content(
                                        parts=[genai_types.Part(text=greeting_prompt)],
                                        role="user",
                                    )
                                ],
                                turn_complete=True,
                            )
                        )
                        logger.info(f"GREETING_TRIGGER_SENT_VIA_CLIENT_EVENT | call_id={call_id}")
                elif hasattr(self, "session") and self.session:
                    self.session.say(
                        fallback_speech,
                        allow_interruptions=True,
                    )
                    logger.info(f"GREETING_TRIGGER_SENT_VIA_SAY | call_id={call_id}")
            except Exception as e:
                logger.error(f"GREETING_TRIGGER_ERROR | call_id={call_id} | {e}", exc_info=True)

    agent = NagpurEstatesAgent(
        instructions=system_prompt,
        llm=realtime_model,
        tools=tools,
        min_endpointing_delay=0.15,
        max_endpointing_delay=0.65,
    )

    session = voice.AgentSession()

    # 5. Wire up Lifecycle & Transcript Events
    turn_counter = 0

    @session.on("close")
    def on_session_close(*args):
        logger.info(f"SESSION_CLOSED | call_id={call_id}")
        session_closed.set()

    @ctx.room.on("disconnected")
    def on_room_disconnected(*args):
        logger.info(f"ROOM_DISCONNECTED | call_id={call_id}")
        session_closed.set()

    @session.on("user_state_changed")
    def on_user_state_changed(ev):
        new_state = str(ev.new_state).lower()
        old_state = str(ev.old_state).lower()
        if "speaking" in new_state:
            metrics.mark_user_speech_started()
            if not metrics._greeting_finished:
                metrics.mark_greeting_finished()
                set_state(CallState.CONVERSATION_ACTIVE)
        elif "speaking" in old_state and "speaking" not in new_state:
            metrics.mark_user_speech_ended()

    @session.on("agent_state_changed")
    def on_agent_state_changed(ev):
        new_state = str(ev.new_state).lower()
        if "speaking" in new_state:
            metrics.mark_agent_speech_started()
            if call_state == CallState.CUSTOMER_CONNECTED:
                set_state(CallState.GREETING_STARTED)

    # Transcript recording handler
    @session.on("conversation_item_added")
    def on_conversation_item_added(ev):
        nonlocal turn_counter
        try:
            item = getattr(ev, "item", ev)
            role = str(getattr(item, "role", "unknown")).lower()
            text = (
                getattr(item, "text_content", None)
                or getattr(item, "raw_text_content", None)
                or getattr(item, "text", None)
                or ""
            )
            if not text and hasattr(item, "content"):
                text = str(item.content)

            if text and text.strip():
                turn_counter += 1
                speaker = "assistant" if ("assistant" in role or "model" in role) else "customer"
                add_call_turn_record(
                    call_id=call_id,
                    turn_number=turn_counter,
                    speaker=speaker,
                    text=text.strip(),
                    latency_ms=metrics.turn_latencies[-1] if metrics.turn_latencies and speaker == "assistant" else None,
                )
                logger.info(f"TRANSCRIPT_RECORDED | turn={turn_counter} | {speaker}: {text.strip()[:60]}")
        except Exception as err:
            logger.warning(f"TRANSCRIPT_CAPTURE_ERROR | call_id={call_id} | {err}", exc_info=True)

    # 6. Start the session and monitor call duration & hangup
    async def duration_and_hangup_watcher():
        start_time = time.time()
        while not session_closed.is_set():
            await asyncio.sleep(1.0)
            elapsed = time.time() - start_time
            update_live_call_state(call_id, {"duration_seconds": int(elapsed)})

            # Check if customer hung up (remote customer participant left room)
            if customer_connected.is_set():
                customer_present = any(is_customer_participant(p) for p in ctx.room.remote_participants.values())
                if not customer_present:
                    logger.info(f"CUSTOMER_LEFT_ROOM | call_id={call_id} | Terminating session")
                    session_closed.set()
                    break

            # Auto-hangup after MAX_CALL_DURATION
            if elapsed > MAX_CALL_DURATION_SECONDS:
                logger.info(f"MAX_CALL_DURATION_REACHED | call_id={call_id} | duration={elapsed:.0f}s")
                try:
                    await ctx.room.disconnect()
                except Exception:
                    pass
                break

            # Hangup requested by end_call tool
            if hangup_requested.is_set():
                logger.info(f"HANGUP_REQUESTED | call_id={call_id} | Draining speech gracefully before disconnect...")

                # 1. Wait if the agent is still thinking or about to speak (up to 4 seconds)
                for _ in range(40):
                    curr_state = str(getattr(session, "agent_state", "")).lower()
                    if "speaking" in curr_state:
                        break
                    await asyncio.sleep(0.1)

                # 2. If agent is speaking, wait until speech finishes (up to 20 seconds)
                curr_state = str(getattr(session, "agent_state", "")).lower()
                if "speaking" in curr_state:
                    logger.info(f"AGENT_SPEAKING_FINAL_REPLY | call_id={call_id} | waiting for speech to finish...")
                    speech_wait = 0.0
                    while "speaking" in str(getattr(session, "agent_state", "")).lower() and speech_wait < 20.0:
                        await asyncio.sleep(0.2)
                        speech_wait += 0.2
                    logger.info(f"AGENT_FINISHED_SPEAKING | call_id={call_id} | spoken_for={speech_wait:.1f}s")
                else:
                    logger.info(f"AGENT_NOT_SPEAKING | call_id={call_id} | proceeding with standard drain")

                # 3. Allow 2.5s network buffer so WebRTC/SIP RTP packets reach the phone earpiece
                logger.info(f"ALLOWING_FINAL_AUDIO_DRAIN | call_id={call_id} | waiting 2.5s network buffer")
                await asyncio.sleep(2.5)

                try:
                    await ctx.room.disconnect()
                    logger.info(f"ROOM_DISCONNECTED_AFTER_DRAIN | call_id={call_id}")
                except Exception as e:
                    logger.warning(f"Room disconnect error: {e}")

                # 4. Schedule room deletion in background after 5 seconds to avoid breaking active FFI handles
                async def _delayed_room_cleanup(r_name: str):
                    await asyncio.sleep(5.0)
                    try:
                        livekit_url = os.getenv("LIVEKIT_URL")
                        api_key = os.getenv("LIVEKIT_API_KEY")
                        api_secret = os.getenv("LIVEKIT_API_SECRET")
                        async with lapi.LiveKitAPI(url=livekit_url, api_key=api_key, api_secret=api_secret) as lk_api:
                            await lk_api.room.delete_room(lapi.DeleteRoomRequest(room=r_name))
                        logger.info(f"LIVEKIT_ROOM_DELETED_ON_HANGUP | room={r_name}")
                    except Exception as err:
                        logger.debug(f"Delayed room cleanup note: {err}")

                asyncio.create_task(_delayed_room_cleanup(room_name))
                break

        session_closed.set()

    watcher_task = asyncio.create_task(duration_and_hangup_watcher())

    try:
        call_status = "in_progress"
        set_state(CallState.CONVERSATION_ACTIVE)
        await session.start(agent, room=ctx.room)
        logger.info(f"SESSION_RUNNING | call_id={call_id}")
        await session_closed.wait()

        # Distinguish completed vs ended in the middle
        total_turns = max(metrics.turn_count, turn_counter)
        if hangup_requested.is_set():
            call_status = "completed"
        elif lead_state.site_visit_interested or lead_state.callback_required or lead_state.dnd_requested:
            call_status = "completed"
        elif total_turns == 0 or not metrics.pc_customer_connected:
            call_status = "no_answer"
            lead_state.next_action = "no_answer"
        else:
            call_status = "ended_in_middle"
            lead_state.next_action = "ended_in_middle"

    except Exception as exc:
        logger.error(f"SESSION_ERROR | call_id={call_id} | error={exc}", exc_info=True)
        call_status = "failed"
        lead_state.next_action = "call_failed"
    finally:
        watcher_task.cancel()
        set_state(CallState.CALL_ENDING)
        try:
            metrics.generate_final_report(lead_state, call_status=call_status, domain=prompt_ctx.domain)
        except Exception as report_err:
            logger.error(f"FINAL_REPORT_ERROR | call_id={call_id} | {report_err}", exc_info=True)
            # Fallback direct state update so status is never left as 'call_ending'
            update_live_call_state(call_id, {
                "status": call_status,
                "ended_at": time.time(),
                "outcome": lead_state.next_action or call_status,
            })
        set_state(CallState.CALL_ENDED)
        logger.info(f"CALL_ENDED | call_id={call_id} | room={room_name} | status={call_status}")
        try:
            await ctx.room.disconnect()
        except Exception:
            pass
        # Ensure registry is cleared so the number is available for future calls
        asyncio.create_task(hangup_call(call_id))


# ---------------------------------------------------------------------------
# Worker Launcher
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    agent_name = os.getenv("AGENT_NAME", "ai-calling-agent")
    logger.info(f"STARTING_LIVEKIT_AGENT_WORKER | agent_name={agent_name} | engine=Gemini-3.1-Live-Native-Audio")
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=agent_name,
            load_threshold=1.0,
            load_fnc=lambda worker: len(getattr(worker, "active_jobs", [])) / 3.0,
            num_idle_processes=0,
            port=0,
            host="127.0.0.1",
        )
    )
