from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
import time
from typing import Any, Dict, List, Optional

from db.models import CallEvent, CallRecord, Campaign, CampaignLead, Lead
from db.session import get_db_session
from services.call_service import hangup_call, initiate_outbound_call

logger = logging.getLogger("crm_campaign_dialer")

# Track active background tasks: campaign_id -> asyncio.Task
RUNNING_CAMPAIGN_TASKS: Dict[str, asyncio.Task] = {}
STOP_FLAGS: Dict[str, bool] = {}
PAUSE_FLAGS: Dict[str, bool] = {}

MAX_CAMPAIGN_CONCURRENCY = 3


def _record_call_event(call_id: Optional[str], event_name: str, payload: Dict[str, Any]):
    """Safely log CallEvent if call_id exists in calls table."""
    if not call_id:
        return
    try:
        with get_db_session() as db:
            cr = db.query(CallRecord).filter(CallRecord.call_id == call_id).first()
            if cr:
                ev = CallEvent(
                    call_id=call_id,
                    event_name=event_name,
                    payload_json=json.dumps(payload),
                    timestamp=time.time(),
                )
                db.add(ev)
                db.commit()
    except Exception as e:
        logger.debug(f"CallEvent recording note for {call_id}: {e}")


async def _execute_single_campaign_call(
    campaign_id: str,
    campaign_lead_id: str,
    lead_id: str,
    phone_number: str,
    customer_name: str,
    attempt_number: int,
    wake_event: asyncio.Event,
):
    """
    Executes a single campaign lead call through the existing call service,
    tracks duration and outcomes, and decrements active_calls upon completion.
    """
    dial_started_at = time.time()
    call_id = None

    try:
        # 1. Initiate outbound call via existing call service
        logger.info(
            f"CAMPAIGN_CALL_INITIATE | campaign={campaign_id} | lead_id={lead_id} | "
            f"customer={customer_name} | attempt={attempt_number} | t={dial_started_at:.3f}"
        )

        # Fetch campaign's agent_config_id if assigned
        agent_config_id = None
        try:
            with get_db_session() as db:
                c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if c and c.agent_config_id:
                    agent_config_id = c.agent_config_id
        except Exception:
            pass

        call_res = await initiate_outbound_call(
            phone_number=phone_number,
            customer_name=customer_name,
            lead_id=lead_id,
            campaign_id=campaign_id,
            campaign_lead_id=campaign_lead_id,
            attempt_number=attempt_number,
            agent_config_id=agent_config_id,
        )
        call_id = call_res.get("call_id")

        # 2. Update CampaignLead to 'active'
        with get_db_session() as db:
            cl = db.query(CampaignLead).filter(CampaignLead.id == campaign_lead_id).first()
            if cl:
                cl.status = "active"
                cl.last_call_id = call_id
                cl.last_call_status = "active"
                db.commit()

        _record_call_event(
            call_id,
            "campaign_call_started",
            {
                "campaign_id": campaign_id,
                "campaign_lead_id": campaign_lead_id,
                "lead_id": lead_id,
                "dial_started_at": dial_started_at,
            },
        )

        # 3. Monitor live call until terminal state
        max_duration = 600  # 10 minutes max per call
        start_monitor = time.time()
        final_status = "completed"
        final_outcome = "completed"

        while time.time() - start_monitor < max_duration:
            if STOP_FLAGS.get(campaign_id, False):
                logger.info(f"CAMPAIGN_STOP_DETECTED_IN_CALL | call_id={call_id}")
                final_status = "cancelled"
                final_outcome = "Campaign stopped by user"
                break

            with get_db_session() as db:
                cr = db.query(CallRecord).filter(CallRecord.call_id == call_id).first()
                if cr:
                    # Sync real-time call duration to campaign lead if active
                    if cr.duration_seconds and cr.duration_seconds > 0:
                        cl_live = db.query(CampaignLead).filter(CampaignLead.id == campaign_lead_id).first()
                        if cl_live and cl_live.status in ("active", "dialing"):
                            cl_live.last_call_outcome = f"In call ({cr.duration_seconds}s)"
                            db.commit()

                    if cr.status in ("completed", "failed", "cancelled", "busy", "no_answer", "ended_in_middle", "call_ended"):
                        final_status = cr.status
                        if cr.status == "call_ended":
                            if cr.outcome in ("site_visit_booked", "callback_scheduled"):
                                final_status = "completed"
                            elif cr.outcome == "ended_in_middle":
                                final_status = "ended_in_middle"
                            else:
                                final_status = "completed" if cr.duration_seconds and cr.duration_seconds > 45 else "failed"
                        final_outcome = cr.outcome or cr.status
                        break

            await asyncio.sleep(0.5)

        # Hang up and clean up registry once the call is done
        if call_id:
            await hangup_call(call_id)
            logger.info(f"CAMPAIGN_CALL_HUNG_UP | call_id={call_id} | status={final_status}")

        # 4. Finalize CampaignLead and Campaign counters
        with get_db_session() as db:
            cl = db.query(CampaignLead).filter(CampaignLead.id == campaign_lead_id).first()
            if cl:
                cl.status = final_status
                cl.last_call_status = final_status
                cl.last_call_outcome = final_outcome
                cl.completed_at = datetime.utcnow()

            c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
            if c:
                c.active_calls = max(0, (c.active_calls or 1) - 1)
                if final_status in ("completed", "site_visit_booked"):
                    c.completed_leads = (c.completed_leads or 0) + 1
                else:
                    c.failed_leads = (c.failed_leads or 0) + 1
            db.commit()

        _record_call_event(
            call_id,
            f"campaign_call_{final_status}",
            {
                "campaign_id": campaign_id,
                "campaign_lead_id": campaign_lead_id,
                "lead_id": lead_id,
                "final_status": final_status,
                "final_outcome": final_outcome,
                "ended_at": time.time(),
            },
        )

        logger.info(
            f"CAMPAIGN_CALL_FINISHED | campaign={campaign_id} | customer={customer_name} | "
            f"call_id={call_id} | status={final_status} | outcome={final_outcome}"
        )

    except Exception as e:
        logger.error(f"CAMPAIGN_CALL_ERROR | campaign={campaign_id} | lead={customer_name} | error={e}", exc_info=True)
        with get_db_session() as db:
            cl = db.query(CampaignLead).filter(CampaignLead.id == campaign_lead_id).first()
            if cl:
                cl.status = "failed"
                cl.last_call_status = "failed"
                cl.last_call_outcome = f"Error: {str(e)[:500]}"
                cl.completed_at = datetime.utcnow()

            c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
            if c:
                c.active_calls = max(0, (c.active_calls or 1) - 1)
                c.failed_leads = (c.failed_leads or 0) + 1
            db.commit()

        _record_call_event(
            call_id,
            "campaign_call_failed",
            {
                "campaign_id": campaign_id,
                "campaign_lead_id": campaign_lead_id,
                "error": str(e),
            },
        )
    finally:
        # Notify dialer loop that an active call slot has freed up
        wake_event.set()


async def run_campaign_batch_dialer(campaign_id: str):
    """
    Asynchronous queue worker that continuously dials queued leads in a campaign,
    strictly governed by campaign concurrency (max 3 lines).
    
    1. Locks queued leads using PostgreSQL row-level locks (FOR UPDATE SKIP LOCKED).
    2. Atomically claims leads (queued -> dialing) and increments active_calls.
    3. Initiates calls concurrently without waiting for previous calls to finish.
    4. Records dial_started_at and maintains max_observed_active_calls <= 3.
    """
    STOP_FLAGS[campaign_id] = False
    PAUSE_FLAGS[campaign_id] = False
    logger.info(f"CAMPAIGN_DIALER_STARTING | campaign_id={campaign_id}")

    wake_event = asyncio.Event()

    try:
        # 1. Initialize campaign state
        concurrency = 3
        with get_db_session() as db:
            c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
            if not c:
                logger.error(f"CAMPAIGN_NOT_FOUND | campaign_id={campaign_id}")
                return

            c.status = "running"
            c.started_at = c.started_at or datetime.utcnow()
            concurrency = min(max(c.concurrency or 3, 1), MAX_CAMPAIGN_CONCURRENCY)
            c.concurrency = concurrency
            c.active_calls = 0

            # Update queued_leads count
            queued_count = db.query(CampaignLead).filter(
                CampaignLead.campaign_id == campaign_id,
                CampaignLead.status.in_(["queued", "ready"]),
            ).count()

            # Auto-requeue leads if starting a campaign where all leads are completed/failed/stopped
            if queued_count == 0:
                all_cls = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id).all()
                if all_cls:
                    for cl in all_cls:
                        cl.status = "queued"
                        cl.last_call_status = None
                        cl.last_call_outcome = None
                        cl.started_at = None
                        cl.completed_at = None
                    queued_count = len(all_cls)
                    c.completed_leads = 0
                    c.failed_leads = 0
                    c.completed_at = None
                    logger.info(f"CAMPAIGN_AUTO_REQUEUED_LEADS | campaign_id={campaign_id} | count={queued_count}")

            c.queued_leads = queued_count
            c.total_leads = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id).count()
            db.commit()

        # 2. Main Dialing Loop
        while not STOP_FLAGS.get(campaign_id, False) and not PAUSE_FLAGS.get(campaign_id, False):
            leads_to_dial = []

            with get_db_session() as db:
                c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if not c or c.status != "running":
                    logger.info(f"CAMPAIGN_STATUS_NOT_RUNNING | status={getattr(c, 'status', None)}")
                    break

                # Calculate available capacity
                current_active = c.active_calls or 0
                max_concurrency = min(c.concurrency or 3, MAX_CAMPAIGN_CONCURRENCY)
                capacity = max_concurrency - current_active

                if capacity <= 0:
                    # Capacity full (3/3 active), wait for a slot to free up
                    pass
                else:
                    # Row-locking lead reservation
                    is_postgres = not str(db.bind.url).startswith("sqlite")
                    q = db.query(CampaignLead).filter(
                        CampaignLead.campaign_id == campaign_id,
                        CampaignLead.status.in_(["queued", "ready"]),
                    )
                    if is_postgres:
                        q = q.with_for_update(skip_locked=True)

                    available_leads = q.order_by(CampaignLead.created_at.asc()).limit(capacity).all()

                    for cl in available_leads:
                        lead = cl.lead
                        if not lead:
                            continue

                        # Atomically claim lead
                        cl.status = "dialing"
                        cl.started_at = datetime.utcnow()
                        cl.attempts = (cl.attempts or 0) + 1

                        c.active_calls = (c.active_calls or 0) + 1
                        c.queued_leads = max(0, (c.queued_leads or 1) - 1)
                        c.max_observed_active_calls = max(
                            c.max_observed_active_calls or 0,
                            c.active_calls,
                        )

                        leads_to_dial.append({
                            "campaign_lead_id": cl.id,
                            "lead_id": lead.id,
                            "phone_number": lead.phone_number,
                            "customer_name": lead.name,
                            "attempt_number": cl.attempts,
                        })

                    if leads_to_dial:
                        db.commit()
                        logger.info(
                            f"CAMPAIGN_RESERVED_LEADS | campaign={campaign_id} | count={len(leads_to_dial)} | "
                            f"active_now={c.active_calls} | max_observed={c.max_observed_active_calls}"
                        )

            # 3. Launch reserved calls concurrently with 1.5s micro-stagger to avoid WebRTC FFI handshake collisions
            for i, item in enumerate(leads_to_dial):
                if i > 0:
                    await asyncio.sleep(1.5)
                asyncio.create_task(
                    _execute_single_campaign_call(
                        campaign_id=campaign_id,
                        campaign_lead_id=item["campaign_lead_id"],
                        lead_id=item["lead_id"],
                        phone_number=item["phone_number"],
                        customer_name=item["customer_name"],
                        attempt_number=item["attempt_number"],
                        wake_event=wake_event,
                    )
                )

            # 4. Check if finished or need to wait
            with get_db_session() as db:
                c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if c:
                    remaining_queued = db.query(CampaignLead).filter(
                        CampaignLead.campaign_id == campaign_id,
                        CampaignLead.status.in_(["queued", "ready"]),
                    ).count()
                    c.queued_leads = remaining_queued

                    if remaining_queued == 0 and (c.active_calls or 0) == 0:
                        c.status = "completed"
                        c.completed_at = datetime.utcnow()
                        db.commit()
                        logger.info(
                            f"CAMPAIGN_COMPLETED_SUCCESSFULLY | campaign_id={campaign_id} | "
                            f"total={c.total_leads} | completed={c.completed_leads} | failed={c.failed_leads} | "
                            f"max_observed_active_calls={c.max_observed_active_calls}"
                        )
                        break
                    db.commit()

            # Wait for a call to finish or poll interval (max 1.5s)
            try:
                await asyncio.wait_for(wake_event.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
            wake_event.clear()

    except asyncio.CancelledError:
        logger.info(f"CAMPAIGN_DIALER_CANCELLED | campaign_id={campaign_id}")
    except Exception as e:
        logger.error(f"CAMPAIGN_DIALER_FATAL | campaign_id={campaign_id} | error={e}", exc_info=True)
        with get_db_session() as db:
            c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
            if c:
                c.status = "failed"
                db.commit()
    finally:
        RUNNING_CAMPAIGN_TASKS.pop(campaign_id, None)


def start_campaign_dialer_task(campaign_id: str):
    """Start background parallel dialer task for campaign."""
    STOP_FLAGS[campaign_id] = False
    PAUSE_FLAGS[campaign_id] = False

    if campaign_id in RUNNING_CAMPAIGN_TASKS:
        old_task = RUNNING_CAMPAIGN_TASKS[campaign_id]
        if not old_task.done():
            with get_db_session() as db:
                c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if c and c.status == "running":
                    logger.info(f"CAMPAIGN_ALREADY_RUNNING | campaign_id={campaign_id}")
                    return
            old_task.cancel()
        RUNNING_CAMPAIGN_TASKS.pop(campaign_id, None)

    task = asyncio.create_task(run_campaign_batch_dialer(campaign_id))
    RUNNING_CAMPAIGN_TASKS[campaign_id] = task


def pause_campaign_dialer_task(campaign_id: str):
    """Pause background dialer task for campaign."""
    PAUSE_FLAGS[campaign_id] = True
    task = RUNNING_CAMPAIGN_TASKS.pop(campaign_id, None)
    if task and not task.done():
        task.cancel()

    with get_db_session() as db:
        c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if c:
            c.status = "paused"
            db.commit()
    logger.info(f"CAMPAIGN_PAUSED | campaign_id={campaign_id}")


def stop_campaign_dialer_task(campaign_id: str):
    """Stop campaign, cancel queued leads, and allow active calls to finish cleanly."""
    STOP_FLAGS[campaign_id] = True
    task = RUNNING_CAMPAIGN_TASKS.pop(campaign_id, None)
    if task and not task.done():
        task.cancel()

    with get_db_session() as db:
        c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if c:
            c.status = "stopped"
            # Cancel all unstarted queued leads
            queued_leads = db.query(CampaignLead).filter(
                CampaignLead.campaign_id == campaign_id,
                CampaignLead.status == "queued",
            ).all()
            for ql in queued_leads:
                ql.status = "cancelled"
            c.queued_leads = 0
            db.commit()
    logger.info(f"CAMPAIGN_STOPPED | campaign_id={campaign_id}")
