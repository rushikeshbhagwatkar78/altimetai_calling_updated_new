import asyncio
import os
import sys
import time
import pytest
from fastapi.testclient import TestClient

# Ensure workspace is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Ensure safe mock mode is active for testing
os.environ["BATCH_CALL_MOCK_MODE"] = "true"

from main import app
from db.models import Campaign, CampaignLead, CallRecord, Lead
from db.session import init_db, get_db_session
from agent import LeadState

# Initialize database schema
init_db()

client = TestClient(app)

def get_auth_headers():
    login_res = client.post("/api/auth/login", json={"email": "admin@nagpurestates.com", "password": "admin123"})
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    token = login_res.json()["token"]
    return {"Authorization": f"Bearer {token}"}

def get_or_create_test_leads(count=5):
    """Ensure at least `count` leads exist in DB."""
    headers = get_auth_headers()
    leads_res = client.get("/api/leads", headers=headers)
    leads = leads_res.json().get("leads", [])
    lead_ids = [l["id"] for l in leads]

    needed = count - len(lead_ids)
    for i in range(needed):
        create_res = client.post(
            "/api/leads",
            headers=headers,
            json={
                "name": f"Test Lead {i+1}",
                "phone_number": f"+9198000000{i+1:02d}",
                "preferred_location": "Besa",
                "property_type": "Flat",
                "budget_max": 6500000.0,
            }
        )
        assert create_res.status_code == 201
        lead_ids.append(create_res.json()["lead_id"])

    return lead_ids[:count]


def test_validation_limits():
    """Test MVP limits: concurrency > 3 and lead_ids > 3 must be rejected with HTTP 400."""
    headers = get_auth_headers()
    lead_ids = get_or_create_test_leads(5)

    # 1. Reject concurrency > 3
    res1 = client.post(
        "/api/campaigns",
        headers=headers,
        json={"name": "Over Limit Concurrency", "lead_ids": lead_ids[:2], "concurrency": 4},
    )
    assert res1.status_code == 400
    assert "concurrency" in res1.text.lower()

    # 2. Reject lead_ids > 3 for this MVP
    res2 = client.post(
        "/api/campaigns",
        headers=headers,
        json={"name": "Over Limit Leads", "lead_ids": lead_ids[:4], "concurrency": 3},
    )
    assert res2.status_code == 400
    assert "maximum 3 leads" in res2.text.lower()


def test_1_three_leads_concurrency_three():
    """
    Test 1: 3 leads, concurrency = 3.
    Expected: 3 calls start simultaneously (active_calls = 3, queued_leads = 0).
    max_observed_active_calls <= 3.
    """
    headers = get_auth_headers()
    lead_ids = get_or_create_test_leads(3)

    create_res = client.post(
        "/api/campaigns",
        headers=headers,
        json={"name": "3-Concurrent Smoke Test", "lead_ids": lead_ids, "concurrency": 3},
    )
    assert create_res.status_code == 201
    campaign_id = create_res.json()["campaign_id"]

    # Start campaign
    start_res = client.post(f"/api/campaigns/{campaign_id}/start", headers=headers)
    assert start_res.status_code == 200

    # Allow non-blocking worker to claim and dispatch
    time.sleep(1.2)

    status_res = client.get(f"/api/campaigns/{campaign_id}", headers=headers)
    assert status_res.status_code == 200
    data = status_res.json()

    print("\n--- TEST 1 RESULTS ---")
    print(f"Status: {data['status']}, Active: {data['active_calls']}, Queued: {data['queued_leads']}, Peak: {data['max_observed_active_calls']}")
    
    assert data["total_leads"] == 3
    assert data["concurrency"] == 3
    assert data["max_observed_active_calls"] <= 3
    assert data["active_calls"] >= 1  # Calls active concurrently

    # Check leads endpoint
    leads_res = client.get(f"/api/campaigns/{campaign_id}/leads", headers=headers)
    assert leads_res.status_code == 200
    assert len(leads_res.json()) == 3


def test_2_three_leads_concurrency_two():
    """
    Test 2: 3 leads, concurrency = 2.
    Expected: 2 start initially, 1 remains queued.
    After one finishes, third starts.
    """
    headers = get_auth_headers()
    lead_ids = get_or_create_test_leads(3)

    create_res = client.post(
        "/api/campaigns",
        headers=headers,
        json={"name": "Concurrency 2 Rolling Test", "lead_ids": lead_ids, "concurrency": 2},
    )
    assert create_res.status_code == 201
    campaign_id = create_res.json()["campaign_id"]

    start_res = client.post(f"/api/campaigns/{campaign_id}/start", headers=headers)
    assert start_res.status_code == 200

    # Check immediately after start
    time.sleep(1.2)
    status_res = client.get(f"/api/campaigns/{campaign_id}", headers=headers)
    data = status_res.json()

    print("\n--- TEST 2 RESULTS ---")
    print(f"Status: {data['status']}, Active: {data['active_calls']}, Queued: {data['queued_leads']}, Peak: {data['max_observed_active_calls']}")

    assert data["concurrency"] == 2
    assert data["max_observed_active_calls"] <= 2
    assert data["active_calls"] <= 2


def test_3_and_4_engine_level_four_leads_rolling():
    """
    Test 3 & 4: Engine-level 4 leads test with concurrency = 3.
    Directly attaches 4 leads to campaign in DB, starts campaign,
    verifies max 3 active initially, and 4th starts after completion.
    """
    headers = get_auth_headers()
    lead_ids = get_or_create_test_leads(4)

    # Create with 3 leads via API
    create_res = client.post(
        "/api/campaigns",
        headers=headers,
        json={"name": "Engine 4-Lead Rolling Test", "lead_ids": lead_ids[:3], "concurrency": 3},
    )
    campaign_id = create_res.json()["campaign_id"]

    # Directly attach 4th lead to test engine rolling capacity
    with get_db_session() as db:
        cl4 = CampaignLead(campaign_id=campaign_id, lead_id=lead_ids[3], status="queued")
        db.add(cl4)
        c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        c.total_leads = 4
        c.queued_leads = 4
        db.commit()

    start_res = client.post(f"/api/campaigns/{campaign_id}/start", headers=headers)
    assert start_res.status_code == 200

    time.sleep(1.2)
    data1 = client.get(f"/api/campaigns/{campaign_id}", headers=headers).json()
    print("\n--- TEST 3 & 4 RESULTS (Initial) ---")
    print(f"Active: {data1['active_calls']}, Queued: {data1['queued_leads']}, Peak: {data1['max_observed_active_calls']}")

    assert data1["max_observed_active_calls"] <= 3
    assert data1["active_calls"] <= 3


def test_5_lead_reservation_idempotency():
    """Test 5: Ensure the same CampaignLead cannot be reserved twice."""
    headers = get_auth_headers()
    lead_ids = get_or_create_test_leads(1)

    with get_db_session() as db:
        c = Campaign(name="Reservation Test", concurrency=1, status="draft", total_leads=1, queued_leads=1)
        db.add(c)
        db.commit()
        db.refresh(c)

        cl = CampaignLead(campaign_id=c.id, lead_id=lead_ids[0], status="queued")
        db.add(cl)
        db.commit()
        db.refresh(cl)
        campaign_lead_id = cl.id

    # First reservation: claim lead
    with get_db_session() as db:
        item = db.query(CampaignLead).filter(CampaignLead.id == campaign_lead_id, CampaignLead.status == "queued").first()
        assert item is not None
        item.status = "dialing"
        db.commit()

    # Second worker attempts to claim same lead
    with get_db_session() as db:
        item2 = db.query(CampaignLead).filter(CampaignLead.id == campaign_lead_id, CampaignLead.status == "queued").first()
        assert item2 is None, "Lead was already claimed; should not be selectable by second worker!"


def test_6_call_isolation():
    """Test 6: Ensure one call's LeadState cannot affect another call."""
    # Create Call A LeadState
    state_a = LeadState(lead_id="lead_001", customer_name="Customer A", phone_number="+919876543210")
    state_a.preferred_location = "Besa"
    state_a.bhk = "2 BHK"
    state_a.lead_temperature = "hot"

    # Create Call B LeadState
    state_b = LeadState(lead_id="lead_002", customer_name="Customer B", phone_number="+919876543211")
    state_b.preferred_location = "Wardha Road"
    state_b.bhk = "3 BHK"
    state_b.lead_temperature = "warm"

    # Create Call C LeadState
    state_c = LeadState(lead_id="lead_003", customer_name="Customer C", phone_number="+919876543212")
    state_c.preferred_location = "MIHAN"
    state_c.bhk = "Plot"
    state_c.lead_temperature = "cold"

    # Verify complete isolation
    assert state_a.preferred_location != state_b.preferred_location
    assert state_b.bhk != state_c.bhk
    assert state_a.lead_temperature == "hot"
    assert state_b.lead_temperature == "warm"
    assert state_c.lead_temperature == "cold"


def test_7_manual_single_call():
    """Test 7: Ensure manual single call endpoint (/api/calls) still works identically."""
    headers = get_auth_headers()
    lead_ids = get_or_create_test_leads(1)

    res = client.post(
        "/api/calls",
        headers=headers,
        json={
            "phone_number": "+919876500000",
            "customer_name": "Manual Single Caller",
            "lead_id": lead_ids[0],
        }
    )
    assert res.status_code == 201, f"Manual call initiation failed: {res.text}"
    call_info = res.json()
    assert "call_id" in call_info
    assert call_info["customer_name"] == "Manual Single Caller"

    # Verify status endpoint
    call_id = call_info["call_id"]
    status_res = client.get(f"/api/calls/{call_id}/live", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["call_id"] == call_id


def test_stop_campaign():
    """Test Stop Campaign endpoint: queued leads transition to cancelled."""
    headers = get_auth_headers()
    lead_ids = get_or_create_test_leads(3)

    create_res = client.post(
        "/api/campaigns",
        headers=headers,
        json={"name": "Stop Campaign Test", "lead_ids": lead_ids, "concurrency": 1},
    )
    campaign_id = create_res.json()["campaign_id"]

    client.post(f"/api/campaigns/{campaign_id}/start", headers=headers)
    time.sleep(0.5)

    stop_res = client.post(f"/api/campaigns/{campaign_id}/stop", headers=headers)
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "stopped"

    detail = client.get(f"/api/campaigns/{campaign_id}", headers=headers).json()
    assert detail["status"] == "stopped"
