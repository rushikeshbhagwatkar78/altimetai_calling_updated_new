from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import livekit.api as lapi
from livekit.protocol import sip as sip_proto
from sqlalchemy.orm import Session

from db.models import CallEvent, CallRecord, CallTurn, Lead, LeadActivity
from db.session import get_db_session
from services.lead_service import mask_phone_number, normalize_phone_e164

logger = logging.getLogger("crm_calls")

# In-memory real-time state for live calls: call_id -> dict
LIVE_CALL_REGISTRY: Dict[str, Dict[str, Any]] = {}
IDEMPOTENCY_CACHE: Dict[str, Dict[str, Any]] = {}


async def _simulate_mock_call(
    call_id: str,
    norm_phone: str,
    customer_name: str,
    lead_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    campaign_lead_id: Optional[str] = None,
):
    """Simulates call lifecycle for testing concurrency safely without placing real outbound calls."""
    try:
        # 1. Ringing
        await asyncio.sleep(0.2)
        update_live_call_state(call_id, {"status": "ringing"})

        # 2. Connected / Conversation Active
        await asyncio.sleep(0.2)
        update_live_call_state(call_id, {"status": "in_progress", "stage": "conversation_active", "greeting_latency_ms": 420.0})
        add_call_turn_record(call_id, 1, "assistant", f"Namaste {customer_name} ji, main Priya bol rahi hoon Nagpur Estates se. Aapne property enquiry ki thi.", latency_ms=420.0)

        # 3. Customer response
        await asyncio.sleep(0.3)
        add_call_turn_record(call_id, 2, "customer", "Haan boliye, Besa mein ready possession 2 BHK dekh rahe the.", latency_ms=350.0)

        # 4. Agent response
        await asyncio.sleep(0.3)
        add_call_turn_record(call_id, 3, "assistant", "Besa mein Greenwood Meadows mein ready 2 BHK available hai 55 Lakhs mein clubhouse ke sath. Ek baar site visit convenient rahega?", latency_ms=410.0)

        # 5. Customer confirmation
        await asyncio.sleep(0.2)
        add_call_turn_record(call_id, 4, "customer", "Haan Saturday 11 baje confirm kar dijiye.", latency_ms=310.0)

        # 6. Call Completed
        await asyncio.sleep(0.2)
        duration = 6
        update_live_call_state(call_id, {
            "status": "completed",
            "duration_seconds": duration,
            "outcome": "site_visit_booked",
            "lead_temperature": "hot",
            "next_action": "site_visit_followup",
            "summary": f"Mock call with {customer_name}. Lead confirmed site visit for Saturday 11 AM in Besa.",
            "p50_latency_ms": 380.0,
            "avg_response_latency_ms": 370.0,
            "turns_count": 4,
        })
        with get_db_session() as db:
            cr = db.query(CallRecord).filter(CallRecord.call_id == call_id).first()
            if cr:
                cr.ended_at = time.time()
                db.commit()
        # Clean up registry so the number is no longer blocked
        await hangup_call(call_id)
    except Exception as e:
        logger.error(f"MOCK_CALL_ERROR | call_id={call_id} | error={e}")
        update_live_call_state(call_id, {"status": "failed", "outcome": f"Mock error: {e}"})
        await hangup_call(call_id)


async def initiate_outbound_call(
    phone_number: str,
    customer_name: str = "Customer",
    lead_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    campaign_id: Optional[str] = None,
    campaign_lead_id: Optional[str] = None,
    attempt_number: int = 1,
    agent_config_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Initiate Outbound Call via LiveKit Cloud SIP Trunk or Safe Mock Simulator:
    1. Validates and normalizes phone number to E.164 format.
    2. Prevents simultaneous duplicate active calls to same phone.
    3. Persists initial CallRecord in database with campaign linkages.
    4. In real mode: Creates LiveKit room, dispatches Agent Worker, triggers SIP outbound participant.
       In mock mode: Simulates lifecycles and transcripts asynchronously.
    """
    norm_phone = normalize_phone_e164(phone_number)
    masked_phone = mask_phone_number(norm_phone)

    # Check idempotency
    if idempotency_key and idempotency_key in IDEMPOTENCY_CACHE:
        logger.info(f"IDEMPOTENT_CALL_SERVED | key={idempotency_key}")
        return IDEMPOTENCY_CACHE[idempotency_key]

    # Prevent simultaneous active calls to same number.
    # Cross-check against DB so stale registry entries (e.g. from a restart or
    # missed cleanup) don't permanently block new calls.
    _ACTIVE_STATUSES = {"initiating", "ringing", "in_progress"}
    _TERMINAL_DB_STATUSES = {"completed", "failed", "cancelled", "busy", "no_answer", "ended_in_middle", "call_ended"}
    stale_cids: List[str] = []
    for cid, cinfo in list(LIVE_CALL_REGISTRY.items()):
        if cinfo.get("phone_number") != norm_phone:
            continue
        if cinfo.get("status") not in _ACTIVE_STATUSES:
            continue
        # Verify the call is truly still live in the DB
        with get_db_session() as _db:
            _cr = _db.query(CallRecord).filter(CallRecord.call_id == cid).first()
            if _cr and _cr.status in _TERMINAL_DB_STATUSES:
                # DB says it's done — registry is stale, evict it
                logger.warning(
                    f"STALE_REGISTRY_EVICTED | call_id={cid} | "
                    f"registry_status={cinfo.get('status')} | db_status={_cr.status}"
                )
                stale_cids.append(cid)
                continue
        raise RuntimeError(f"An active call to {masked_phone} is already in progress (Call ID: {cid}).")
    for cid in stale_cids:
        LIVE_CALL_REGISTRY.pop(cid, None)

    room_name = f"call-{uuid.uuid4().hex[:8]}"
    call_id = room_name

    mock_mode = os.getenv("BATCH_CALL_MOCK_MODE", "false").lower() in ("true", "1")

    trunk_id = os.getenv("LIVEKIT_SIP_OUTBOUND_TRUNK_ID") or os.getenv("LIVEKIT_SIP_TRUNK_ID")
    agent_name = os.getenv("AGENT_NAME", "ai-calling-agent")
    livekit_url = os.getenv("LIVEKIT_URL")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")

    if not mock_mode and (not trunk_id or not livekit_url or not api_key):
        raise RuntimeError("LiveKit credentials or SIP trunk ID is not configured.")

    # 1. Look up or auto-link Lead ID
    with get_db_session() as db:
        lead = None
        if lead_id:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            lead = db.query(Lead).filter(Lead.phone_number == norm_phone).first()
        if not lead:
            lead = Lead(
                name=customer_name or "Customer",
                phone_number=norm_phone,
                masked_phone=masked_phone,
                assigned_agent="Priya",
                stage="contacted",
            )
            db.add(lead)
            db.flush()

        actual_lead_id = lead.id

        # 2. Persist CallRecord in database
        call_rec = CallRecord(
            call_id=call_id,
            room_name=room_name,
            lead_id=actual_lead_id,
            customer_name=customer_name or lead.name,
            phone_number_masked=masked_phone,
            campaign_id=campaign_id,
            campaign_lead_id=campaign_lead_id,
            attempt_number=attempt_number,
            status="initiating",
            started_at=time.time(),
        )
        db.add(call_rec)

        # Log lead activity
        act = LeadActivity(
            lead_id=actual_lead_id,
            activity_type="call_started",
            description=f"Outbound AI call initiated to {masked_phone} (Call ID: {call_id}).",
            metadata_json=json.dumps({"call_id": call_id, "room": room_name, "campaign_id": campaign_id}),
        )
        db.add(act)
        db.commit()

    # MOCK MODE BRANCH
    if mock_mode:
        logger.info(f"MOCK_CALL_DISPATCHED | room={room_name} | call_id={call_id} | customer={customer_name}")
        dispatch_id = f"mock_disp_{uuid.uuid4().hex[:6]}"
        sip_call_id = f"mock_sip_{uuid.uuid4().hex[:6]}"
        live_record = {
            "call_id": call_id,
            "room_name": room_name,
            "lead_id": actual_lead_id,
            "phone_number": norm_phone,
            "phone_number_masked": masked_phone,
            "customer_name": customer_name,
            "dispatch_id": dispatch_id,
            "sip_call_id": sip_call_id,
            "campaign_id": campaign_id,
            "campaign_lead_id": campaign_lead_id,
            "attempt_number": attempt_number,
            "status": "initiating",
            "stage": "connecting",
            "duration_seconds": 0,
            "turns": [],
            "started_at": time.time(),
            "lead_temperature": "warm",
            "matched_properties": [],
            "site_visit_status": None,
        }
        LIVE_CALL_REGISTRY[call_id] = live_record

        with get_db_session() as db:
            c = db.query(CallRecord).filter(CallRecord.call_id == call_id).first()
            if c:
                c.dispatch_id = dispatch_id
                c.sip_call_id = sip_call_id
                db.commit()

        if idempotency_key:
            IDEMPOTENCY_CACHE[idempotency_key] = live_record

        asyncio.create_task(_simulate_mock_call(call_id, norm_phone, customer_name, actual_lead_id, campaign_id, campaign_lead_id))
        return live_record

    # 3. Create LiveKit API Client for Real Call Mode
    lk_api = lapi.LiveKitAPI(url=livekit_url, api_key=api_key, api_secret=api_secret)

    try:
        # Step A: Dispatch Agent worker
        metadata_payload = json.dumps({
            "call_id": call_id,
            "customer_name": customer_name,
            "phone_number": norm_phone,
            "room_name": room_name,
            "lead_id": actual_lead_id,
            "campaign_id": campaign_id,
            "campaign_lead_id": campaign_lead_id,
            "attempt_number": attempt_number,
            "agent_config_id": agent_config_id,
        })

        dispatch_req = lapi.CreateAgentDispatchRequest(
            agent_name=agent_name,
            room=room_name,
            metadata=metadata_payload,
        )
        dispatch_info = await lk_api.agent_dispatch.create_dispatch(dispatch_req)
        dispatch_id = getattr(dispatch_info, "id", None)
        logger.info(f"AGENT_DISPATCHED | room={room_name} | dispatch_id={dispatch_id}")

        # Step B: Create Outbound SIP Participant
        sip_req = sip_proto.CreateSIPParticipantRequest(
            sip_trunk_id=trunk_id,
            sip_call_to=norm_phone,
            room_name=room_name,
            participant_identity=f"sip-{norm_phone}",
            participant_name=customer_name,
            participant_attributes={
                "customer_name": customer_name,
                "phone_number": norm_phone,
                "call_id": call_id,
                "lead_id": actual_lead_id,
                "campaign_id": campaign_id or "",
                "campaign_lead_id": campaign_lead_id or "",
            },
        )
        sip_info = await lk_api.sip.create_sip_participant(sip_req)
        sip_call_id = getattr(sip_info, "sip_call_id", None) or getattr(sip_info, "participant_id", None)
        logger.info(f"SIP_PARTICIPANT_CREATED | room={room_name} | trunk={trunk_id} | sip_id={sip_call_id}")

        # Record in live registry
        live_record = {
            "call_id": call_id,
            "room_name": room_name,
            "lead_id": actual_lead_id,
            "phone_number": norm_phone,
            "phone_number_masked": masked_phone,
            "customer_name": customer_name,
            "dispatch_id": dispatch_id,
            "sip_call_id": sip_call_id,
            "campaign_id": campaign_id,
            "campaign_lead_id": campaign_lead_id,
            "attempt_number": attempt_number,
            "status": "initiating",
            "stage": "connecting",
            "duration_seconds": 0,
            "turns": [],
            "started_at": time.time(),
            "lead_temperature": "warm",
            "matched_properties": [],
            "site_visit_status": None,
        }
        LIVE_CALL_REGISTRY[call_id] = live_record

        # Update DB record with dispatch and SIP IDs
        with get_db_session() as db:
            c = db.query(CallRecord).filter(CallRecord.call_id == call_id).first()
            if c:
                c.dispatch_id = dispatch_id
                c.sip_call_id = sip_call_id
                db.commit()

        if idempotency_key:
            IDEMPOTENCY_CACHE[idempotency_key] = live_record

        return live_record

    except Exception as e:
        logger.error(f"CALL_INITIATION_ERROR | room={room_name} | error={e}", exc_info=True)
        with get_db_session() as db:
            c = db.query(CallRecord).filter(CallRecord.call_id == call_id).first()
            if c:
                c.status = "failed"
                c.outcome = f"Error: {str(e)}"
                db.commit()
        raise
    finally:
        await lk_api.aclose()


# Terminal statuses that mean the call is fully over
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "busy", "no_answer", "ended_in_middle", "call_ended"})


def update_live_call_state(call_id: str, updates: Dict[str, Any]):
    """Update live in-memory and database state for an active call."""
    if call_id in LIVE_CALL_REGISTRY:
        LIVE_CALL_REGISTRY[call_id].update(updates)

    # Sync critical state to DB
    with get_db_session() as db:
        c = db.query(CallRecord).filter(CallRecord.call_id == call_id).first()
        if c:
            if "status" in updates:
                c.status = updates["status"]
            if "duration_seconds" in updates:
                c.duration_seconds = updates["duration_seconds"]
            if "outcome" in updates:
                c.outcome = updates["outcome"]
            if "summary" in updates:
                c.summary = updates["summary"]
            if "greeting_latency_ms" in updates:
                c.greeting_latency_ms = updates["greeting_latency_ms"]
            if "avg_response_latency_ms" in updates:
                c.avg_response_latency_ms = updates["avg_response_latency_ms"]
            if "p50_latency_ms" in updates:
                c.p50_latency_ms = updates["p50_latency_ms"]
            if "p90_latency_ms" in updates:
                c.p90_latency_ms = updates["p90_latency_ms"]
            if "turns_count" in updates:
                c.turns_count = updates["turns_count"]
            if "lead_temperature" in updates:
                c.lead_temperature = updates["lead_temperature"]
            if "next_action" in updates:
                c.next_action = updates["next_action"]
            if "ended_at" in updates and updates["ended_at"]:
                c.ended_at = updates["ended_at"]
            db.commit()


async def hangup_call(call_id: str):
    """
    Tear down a call cleanly:
    - In real mode: deletes the LiveKit room so the SIP leg is dropped.
    - In both modes: removes the call from LIVE_CALL_REGISTRY so the
      phone number is no longer blocked for future calls.
    """
    mock_mode = os.getenv("BATCH_CALL_MOCK_MODE", "false").lower() in ("true", "1")
    room_name = call_id
    if call_id in LIVE_CALL_REGISTRY:
        room_name = LIVE_CALL_REGISTRY[call_id].get("room_name", call_id)

    if not mock_mode:
        livekit_url = os.getenv("LIVEKIT_URL")
        api_key = os.getenv("LIVEKIT_API_KEY")
        api_secret = os.getenv("LIVEKIT_API_SECRET")
        if livekit_url and api_key and api_secret:
            lk_api = lapi.LiveKitAPI(url=livekit_url, api_key=api_key, api_secret=api_secret)
            try:
                await lk_api.room.delete_room(lapi.DeleteRoomRequest(room=room_name))
                logger.info(f"CALL_ROOM_DELETED | call_id={call_id} | room={room_name}")
            except Exception as e:
                logger.debug(f"CALL_ROOM_DELETE_NOTE | call_id={call_id} | {e}")
            finally:
                await lk_api.aclose()

    # Always remove from registry so the number becomes available again
    LIVE_CALL_REGISTRY.pop(call_id, None)
    logger.info(f"CALL_REGISTRY_CLEARED | call_id={call_id}")


def add_call_turn_record(
    call_id: str,
    turn_number: int,
    speaker: str,
    text: str,
    latency_ms: Optional[float] = None,
    interrupted: bool = False,
):
    """Add a speaker turn to live registry and database."""
    turn_data = {
        "turn_number": turn_number,
        "speaker": speaker,
        "text": text,
        "latency_ms": latency_ms,
        "interrupted": interrupted,
        "timestamp": time.time(),
    }

    if call_id in LIVE_CALL_REGISTRY:
        LIVE_CALL_REGISTRY[call_id]["turns"].append(turn_data)

    with get_db_session() as db:
        t = CallTurn(
            call_id=call_id,
            turn_number=turn_number,
            speaker=speaker,
            text=text,
            latency_ms=latency_ms,
            interrupted=interrupted,
            timestamp=time.time(),
        )
        db.add(t)
        db.commit()


def get_live_call_status(call_id: str) -> Dict[str, Any]:
    """Retrieve real-time call status and turns from database across processes."""
    with get_db_session() as db:
        c = db.query(CallRecord).filter(CallRecord.call_id == call_id).first()
        if not c:
            if call_id in LIVE_CALL_REGISTRY:
                return LIVE_CALL_REGISTRY[call_id]
            raise KeyError(f"Call ID {call_id} not found.")

        turns = [
            {
                "turn_number": t.turn_number,
                "speaker": t.speaker,
                "text": t.text,
                "latency_ms": t.latency_ms,
                "interrupted": t.interrupted,
                "timestamp": t.timestamp,
            }
            for t in c.turns
        ]

        _LIVE_STATUSES = {"initiating", "in_progress", "conversation_active", "customer_connected"}
        _TERMINAL_STATUSES = {"completed", "failed", "cancelled", "busy", "no_answer", "ended_in_middle", "call_ended"}

        # Auto-heal any calls stuck in 'call_ending' state
        if c.status == "call_ending":
            ref_time = c.ended_at or c.started_at or time.time()
            if time.time() - ref_time > 4.0:
                has_turns = bool(c.turns and len(c.turns) > 0)
                c.status = "completed" if has_turns else "ended_in_middle"
                if not c.ended_at:
                    c.ended_at = time.time()
                if not c.outcome:
                    c.outcome = c.status
                db.commit()
                logger.info(f"AUTO_HEALED_CALL_ENDING | call_id={call_id} | new_status={c.status}")

        duration = c.duration_seconds
        if c.status in _LIVE_STATUSES and c.started_at:
            # Call is actively ongoing — compute live elapsed time
            duration = int(time.time() - c.started_at)
        elif c.status in _TERMINAL_STATUSES and not duration and c.started_at:
            # Call ended but duration_seconds wasn't committed — derive from ended_at or now
            end_ts = c.ended_at or time.time()
            duration = int(end_ts - c.started_at)

        if c.outcome:
            stage = c.outcome
        elif c.status == "call_ending":
            stage = "Ending"
        elif c.status in _TERMINAL_STATUSES:
            stage = "Ended"
        elif c.status == "customer_connected":
            stage = "Greeting"
        else:
            stage = "Active"

        return {
            "call_id": c.call_id,
            "room_name": c.room_name,
            "lead_id": c.lead_id,
            "phone_number_masked": c.phone_number_masked,
            "customer_name": c.customer_name,
            "status": c.status,
            "stage": stage,
            "duration_seconds": duration,
            "greeting_latency_ms": c.greeting_latency_ms,
            "avg_response_latency_ms": c.avg_response_latency_ms,
            "turns": turns,
            "lead_temperature": c.lead_temperature or "warm",
            "next_action": c.next_action,
            "outcome": c.outcome,
            "summary": c.summary,
        }


async def terminate_call(call_id: str) -> Dict[str, Any]:
    """Terminate an active call room in LiveKit and clean up registry."""
    livekit_url = os.getenv("LIVEKIT_URL")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")

    room_name = call_id
    if call_id in LIVE_CALL_REGISTRY:
        room_name = LIVE_CALL_REGISTRY[call_id].get("room_name", call_id)

    result: Dict[str, Any] = {"status": "terminated", "call_id": call_id}

    mock_mode = os.getenv("BATCH_CALL_MOCK_MODE", "false").lower() in ("true", "1")
    if not mock_mode and livekit_url and api_key and api_secret:
        lk_api = lapi.LiveKitAPI(url=livekit_url, api_key=api_key, api_secret=api_secret)
        try:
            await lk_api.room.delete_room(lapi.DeleteRoomRequest(room=room_name))
            logger.info(f"CALL_TERMINATED | call_id={call_id} | room={room_name}")
        except Exception as e:
            logger.warning(f"Error terminating call {call_id}: {e}")
            result["status"] = "already_closed"
        finally:
            await lk_api.aclose()

    with get_db_session() as db:
        c = db.query(CallRecord).filter(CallRecord.call_id == call_id).first()
        if c:
            c.status = "cancelled"
            c.ended_at = time.time()
            db.commit()

    # Remove from registry so the number is free for future calls
    LIVE_CALL_REGISTRY.pop(call_id, None)
    logger.info(f"CALL_REGISTRY_CLEARED | call_id={call_id}")
    return result
