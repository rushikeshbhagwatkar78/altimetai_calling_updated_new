from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    Enum,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True, default=lambda: f"usr_{uuid.uuid4().hex[:10]}")
    email = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    role = Column(String(32), default="sales_agent", nullable=False)  # admin, sales_manager, sales_agent
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Lead(Base):
    __tablename__ = "leads"

    id = Column(String(64), primary_key=True, default=lambda: f"lead_{uuid.uuid4().hex[:10]}")
    name = Column(String(128), default="Customer", nullable=False, index=True)
    phone_number = Column(String(32), nullable=False, index=True)
    masked_phone = Column(String(32), nullable=False)
    
    # Requirements
    preferred_location = Column(String(128), nullable=True, index=True)  # Besa, Manish Nagar, Wardha Road, etc.
    property_type = Column(String(64), nullable=True, index=True)  # Flat, Plot, Bungalow, Commercial
    bhk = Column(String(16), nullable=True)  # 1, 2, 3, 4
    budget_min = Column(Float, nullable=True)
    budget_max = Column(Float, nullable=True, index=True)
    purchase_purpose = Column(String(64), nullable=True)  # Self-use, Investment
    purchase_timeline = Column(String(64), nullable=True)  # Immediate, 1-3 months, Diwali, Next year
    loan_required = Column(Boolean, nullable=True)
    
    # Qualification & Pipeline State
    lead_temperature = Column(String(32), default="warm", index=True)  # hot, warm, cold, not_interested
    stage = Column(String(64), default="new", index=True)  # new, contacted, qualified, property_matched, site_visit, won, lost, dnd
    assigned_agent = Column(String(128), default="Priya", nullable=False)
    
    # Operational flags
    site_visit_interested = Column(Boolean, default=False)
    callback_required = Column(Boolean, default=False)
    dnd_requested = Column(Boolean, default=False, index=True)
    whatsapp_followup = Column(Boolean, default=False)
    
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    lead_notes = relationship("LeadNote", back_populates="lead", cascade="all, delete-orphan", order_by="desc(LeadNote.created_at)")
    activities = relationship("LeadActivity", back_populates="lead", cascade="all, delete-orphan", order_by="desc(LeadActivity.created_at)")
    calls = relationship("CallRecord", back_populates="lead", cascade="all, delete-orphan", order_by="desc(CallRecord.created_at)")
    site_visits = relationship("SiteVisit", back_populates="lead", cascade="all, delete-orphan", order_by="desc(SiteVisit.created_at)")
    callbacks = relationship("Callback", back_populates="lead", cascade="all, delete-orphan", order_by="desc(Callback.created_at)")


class LeadNote(Base):
    __tablename__ = "lead_notes"

    id = Column(String(64), primary_key=True, default=lambda: f"note_{uuid.uuid4().hex[:10]}")
    lead_id = Column(String(64), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(64), nullable=True)
    author_name = Column(String(128), default="Agent", nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="lead_notes")


class LeadActivity(Base):
    __tablename__ = "lead_activities"

    id = Column(String(64), primary_key=True, default=lambda: f"act_{uuid.uuid4().hex[:10]}")
    lead_id = Column(String(64), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    activity_type = Column(String(64), nullable=False)  # lead_created, call_completed, site_visit_booked, note_added, stage_changed, etc.
    description = Column(String(256), nullable=False)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="activities")


class Property(Base):
    __tablename__ = "properties"

    id = Column(String(64), primary_key=True, default=lambda: f"prop_{uuid.uuid4().hex[:10]}")
    project_name = Column(String(128), nullable=False, index=True)
    location = Column(String(128), nullable=False, index=True)  # Besa, Manish Nagar, Wardha Road, Sonegaon, MIHAN, Civil Lines, etc.
    property_type = Column(String(64), nullable=False, index=True)  # Flat, Plot, Luxury Apartment, Bungalow, Commercial
    bhk = Column(String(16), nullable=True, index=True)  # 1 BHK, 2 BHK, 3 BHK, 4 BHK, Plot
    price_min = Column(Float, nullable=False, index=True)
    price_max = Column(Float, nullable=False, index=True)
    price_display = Column(String(64), nullable=False)  # e.g. "₹55 L - ₹65 L"
    carpet_area = Column(String(64), nullable=True)  # e.g. "1050 - 1350 sq.ft."
    possession_status = Column(String(64), default="Ready to Move", nullable=False)  # Ready to Move, Under Construction (Diwali 2026)
    rera_id = Column(String(64), nullable=True)
    builder_name = Column(String(128), default="Nagpur Estates Partner", nullable=False)
    description = Column(Text, nullable=False)
    amenities = Column(Text, nullable=True)  # Comma-separated or JSON string
    available_units = Column(Integer, default=5, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(String(64), primary_key=True, default=lambda: f"doc_{uuid.uuid4().hex[:10]}")
    filename = Column(String(256), nullable=False)
    document_type = Column(String(32), nullable=False)  # pdf, docx, txt, md, csv
    status = Column(String(32), default="uploaded", nullable=False)  # uploaded, indexing, indexed, failed
    chunk_count = Column(Integer, default=0, nullable=False)
    vector_count = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(String(64), primary_key=True, default=lambda: f"chk_{uuid.uuid4().hex[:10]}")
    document_id = Column(String(64), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    # Stored as JSON string or text for vector values (compatible across SQLite and PostgreSQL)
    embedding_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("KnowledgeDocument", back_populates="chunks")


class AgentScript(Base):
    __tablename__ = "agent_scripts"

    id = Column(String(64), primary_key=True, default=lambda: f"scr_{uuid.uuid4().hex[:10]}")
    title = Column(String(256), nullable=False)
    domain = Column(String(64), default="real_estate", nullable=False, index=True)
    category = Column(String(64), default="conversation_script", nullable=False)  # conversation_script, fillers, objections, persona, identity_verification
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    filename = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class CallRecord(Base):
    __tablename__ = "calls"

    id = Column(String(64), primary_key=True, default=lambda: f"call_{uuid.uuid4().hex[:10]}")
    call_id = Column(String(64), unique=True, nullable=False, index=True)
    room_name = Column(String(64), nullable=False, index=True)
    lead_id = Column(String(64), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_name = Column(String(128), default="Customer", nullable=False)
    phone_number_masked = Column(String(32), nullable=False)
    dispatch_id = Column(String(64), nullable=True)
    sip_call_id = Column(String(64), nullable=True)
    status = Column(String(32), default="initiated", nullable=False)  # initiating, ringing, in_progress, completed, failed, cancelled, busy, no_answer
    
    campaign_id = Column(String(64), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    campaign_lead_id = Column(String(64), ForeignKey("campaign_leads.id", ondelete="SET NULL"), nullable=True, index=True)
    attempt_number = Column(Integer, default=1, nullable=False)

    duration_seconds = Column(Integer, default=0, nullable=False)
    greeting_latency_ms = Column(Float, nullable=True)
    avg_response_latency_ms = Column(Float, nullable=True)
    p50_latency_ms = Column(Float, nullable=True)
    p90_latency_ms = Column(Float, nullable=True)
    p95_latency_ms = Column(Float, nullable=True)
    p99_latency_ms = Column(Float, nullable=True)
    
    turns_count = Column(Integer, default=0, nullable=False)
    interruptions_count = Column(Integer, default=0, nullable=False)
    lead_temperature = Column(String(32), nullable=True)
    next_action = Column(String(64), nullable=True)
    outcome = Column(String(64), nullable=True)  # site_visit_booked, callback_required, property_shared, not_interested, dnd, wrong_number, completed
    summary = Column(Text, nullable=True)
    
    started_at = Column(Float, nullable=True)
    ended_at = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="calls")
    turns = relationship("CallTurn", back_populates="call", cascade="all, delete-orphan", order_by="CallTurn.turn_number")
    events = relationship("CallEvent", back_populates="call", cascade="all, delete-orphan", order_by="CallEvent.timestamp")
    campaign = relationship("Campaign", foreign_keys=[campaign_id])
    campaign_lead = relationship("CampaignLead", foreign_keys=[campaign_lead_id])


class CallTurn(Base):
    __tablename__ = "call_turns"

    id = Column(String(64), primary_key=True, default=lambda: f"turn_{uuid.uuid4().hex[:10]}")
    call_id = Column(String(64), ForeignKey("calls.call_id", ondelete="CASCADE"), nullable=False, index=True)
    turn_number = Column(Integer, nullable=False)
    speaker = Column(String(16), nullable=False)  # assistant, customer
    text = Column(Text, nullable=False)
    latency_ms = Column(Float, nullable=True)
    interrupted = Column(Boolean, default=False, nullable=False)
    timestamp = Column(Float, default=time.time, nullable=False)

    call = relationship("CallRecord", back_populates="turns")


class CallEvent(Base):
    __tablename__ = "call_events"

    id = Column(String(64), primary_key=True, default=lambda: f"ev_{uuid.uuid4().hex[:10]}")
    call_id = Column(String(64), ForeignKey("calls.call_id", ondelete="CASCADE"), nullable=False, index=True)
    event_name = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=True)
    timestamp = Column(Float, default=time.time, nullable=False)

    call = relationship("CallRecord", back_populates="events")


class SiteVisit(Base):
    __tablename__ = "site_visits"

    id = Column(String(64), primary_key=True, default=lambda: f"sv_{uuid.uuid4().hex[:10]}")
    lead_id = Column(String(64), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(String(64), ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_name = Column(String(128), nullable=False)
    phone_number = Column(String(32), nullable=False)
    location = Column(String(128), nullable=False)
    visit_datetime = Column(String(128), nullable=False)  # e.g. "Saturday 11:00 AM" or ISO
    status = Column(String(32), default="requested", nullable=False)  # requested, confirmed, completed, cancelled, rescheduled, no_show
    assigned_salesperson = Column(String(128), default="Priya", nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="site_visits")
    property = relationship("Property")


class Callback(Base):
    __tablename__ = "callbacks"

    id = Column(String(64), primary_key=True, default=lambda: f"cb_{uuid.uuid4().hex[:10]}")
    lead_id = Column(String(64), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    call_id = Column(String(64), nullable=True)
    customer_name = Column(String(128), nullable=False)
    phone_number = Column(String(32), nullable=False)
    scheduled_at = Column(String(128), nullable=False)  # e.g. "Tomorrow 10:00 AM" or ISO
    reason = Column(String(256), default="Customer requested later call", nullable=False)
    status = Column(String(32), default="pending", nullable=False)  # pending, completed, missed, cancelled
    assigned_to = Column(String(128), default="Priya", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="callbacks")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String(64), primary_key=True, default=lambda: f"cmp_{uuid.uuid4().hex[:10]}")
    name = Column(String(128), nullable=False, index=True)
    description = Column(Text, nullable=True)
    target_locality = Column(String(128), nullable=True)
    target_property_type = Column(String(64), nullable=True)
    goal = Column(String(64), default="site_visit_booking", nullable=False)  # site_visit_booking, qualification, follow_up
    concurrency = Column(Integer, default=3, nullable=False)
    status = Column(String(32), default="draft", nullable=False)  # draft, running, paused, completed, stopped, failed
    agent_config_id = Column(String(64), ForeignKey("agent_configs.id", ondelete="SET NULL"), nullable=True)
    selected_script_id = Column(String(64), ForeignKey("agent_scripts.id", ondelete="SET NULL"), nullable=True)
    
    total_leads = Column(Integer, default=0, nullable=False)
    queued_leads = Column(Integer, default=0, nullable=False)
    active_calls = Column(Integer, default=0, nullable=False)
    completed_leads = Column(Integer, default=0, nullable=False)
    failed_leads = Column(Integer, default=0, nullable=False)
    max_observed_active_calls = Column(Integer, default=0, nullable=False)
    
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    campaign_leads = relationship("CampaignLead", back_populates="campaign", cascade="all, delete-orphan", order_by="desc(CampaignLead.created_at)")
    agent_config = relationship("AgentConfig", foreign_keys=[agent_config_id])
    selected_script = relationship("AgentScript", foreign_keys=[selected_script_id])


class CampaignLead(Base):
    __tablename__ = "campaign_leads"

    id = Column(String(64), primary_key=True, default=lambda: f"cmpl_{uuid.uuid4().hex[:10]}")
    campaign_id = Column(String(64), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(String(64), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), default="queued", nullable=False)  # queued, dialing, active, completed, failed, cancelled
    attempts = Column(Integer, default=0, nullable=False)
    last_call_id = Column(String(64), nullable=True)
    last_call_status = Column(String(64), nullable=True)
    last_call_outcome = Column(String(512), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    campaign = relationship("Campaign", back_populates="campaign_leads")
    lead = relationship("Lead")
    calls = relationship("CallRecord", foreign_keys="[CallRecord.campaign_lead_id]", order_by="desc(CallRecord.created_at)", overlaps="campaign_lead")


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id = Column(String(64), primary_key=True, default=lambda: f"cfg_{uuid.uuid4().hex[:10]}")
    name = Column(String(128), default="Default Sales Persona", nullable=False)
    domain = Column(String(64), default="real_estate", nullable=False, index=True)
    gender = Column(String(16), default="female", nullable=False)
    agent_display_name = Column(String(64), default="Priya", nullable=False)
    company_name = Column(String(128), default="Nagpur Estates", nullable=False)
    role_description = Column(Text, default="an exceptionally warm, friendly, natural, and articulate real-estate sales advisor calling from {company_name}, Nagpur's most trusted property firm.", nullable=False)
    voice = Column(String(64), default="Aoede", nullable=False)  # Aoede, Kore, Puck, Charon, Fenrir
    temperature = Column(Float, default=0.6, nullable=False)
    language_mode = Column(String(64), default="hinglish", nullable=False)  # hinglish, hindi, english, marathi_hinglish
    
    greeting_known_lead = Column(Text, default="Namaste, kya meri baat {customer_name} ji se ho rahi hai?", nullable=False)
    greeting_unknown_lead = Column(Text, default="Namaste ji, main {agent_name} bol rahi hoon {company_name} se. Aapne property enquiry ki thi. Kya abhi do minute baat ho sakti hai?", nullable=False)
    wrong_number_pivot = Column(Text, default="Achha, koi baat nahi ji! Darasal hume is number par {customer_name} ji ke naam se Nagpur mein property ki enquiry aayi thi. Waise kya aap khud Nagpur mein kisi flat ya residential plot mein interested hain?", nullable=False)
    
    conversation_philosophy = Column(Text, nullable=True)
    sales_funnel_stages = Column(Text, nullable=True)
    objection_guardrails = Column(Text, nullable=True)
    custom_system_prompt_override = Column(Text, nullable=True)
    
    selected_script_id = Column(String(64), ForeignKey("agent_scripts.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    selected_script = relationship("AgentScript", foreign_keys=[selected_script_id])

