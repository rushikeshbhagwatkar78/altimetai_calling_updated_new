from __future__ import annotations

import hashlib
import logging
import os
import secrets
from contextlib import contextmanager
from typing import Generator, Optional, Tuple

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base, Lead, Property, User, Campaign, CampaignLead, AgentScript, AgentConfig

load_dotenv()
logger = logging.getLogger("crm_db")

def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Hash password using PBKDF2 HMAC SHA-256 with salt."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"{salt}${key.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    """Verify plain password against stored salt$hash string."""
    try:
        if "$" not in stored_hash:
            return False
        salt, key_hex = stored_hash.split("$", 1)
        expected_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
        return secrets.compare_digest(key_hex, expected_key.hex())
    except Exception:
        return False

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///nagpur_estates.db").strip()
# Handle older 'postgres://' scheme provided by platforms like Railway/Heroku
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Configure engine
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 15}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for thread-safe database sessions."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error: {e}", exc_info=True)
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def seed_initial_data(db: Session):
    """Seed initial Nagpur properties and sample CRM leads if tables are empty."""
    # 1. Seed properties
    if db.query(Property).count() == 0:
        logger.info("Seeding initial Nagpur Estates property inventory...")
        seed_properties = [
            Property(
                id="prop_besa_01",
                project_name="Greenwood Meadows",
                location="Besa",
                property_type="Flat",
                bhk="2 BHK",
                price_min=5200000.0,
                price_max=6200000.0,
                price_display="₹52 L - ₹62 L",
                carpet_area="1050 sq.ft.",
                possession_status="Ready to Move",
                rera_id="P50500021489",
                builder_name="Meadows Infratech",
                description="Premium 2 BHK luxury apartment in Besa near Pipla road with clubhouse, swimming pool, and children play area.",
                amenities="Clubhouse, Swimming Pool, Gym, 24/7 Security, Power Backup, Covered Parking, Children Play Area",
                available_units=6,
            ),
            Property(
                id="prop_besa_02",
                project_name="Besa Imperial Towers",
                location="Besa",
                property_type="Flat",
                bhk="3 BHK",
                price_min=6800000.0,
                price_max=7800000.0,
                price_display="₹68 L - ₹78 L",
                carpet_area="1450 sq.ft.",
                possession_status="Ready to Move",
                rera_id="P50500028711",
                builder_name="Imperial Landmarks",
                description="Spacious 3 BHK apartment with modular kitchen, Italian marble flooring, and panoramic sunset views in Besa.",
                amenities="Gym, Rooftop Garden, Solar Water, EV Charging Station, 24/7 Security, Intercom",
                available_units=4,
            ),
            Property(
                id="prop_wardha_01",
                project_name="Royal Palms Enclave",
                location="Wardha Road",
                property_type="Plot",
                bhk="Plot",
                price_min=1800000.0,
                price_max=3500000.0,
                price_display="₹18 L - ₹35 L",
                carpet_area="1200 - 2400 sq.ft.",
                possession_status="Immediate Registration",
                rera_id="P50500019234",
                builder_name="Royal Developers Nagpur",
                description="NMRDA & RERA approved gated layout plots on Wardha Road near MIHAN flyover with cement roads, underground drainage, and streetlights.",
                amenities="Gated Community, Cement Roads, Underground Drainage, 24/7 Water Pipeline, Landscaped Garden, Street Lights",
                available_units=12,
            ),
            Property(
                id="prop_manish_01",
                project_name="Manish Heights",
                location="Manish Nagar",
                property_type="Flat",
                bhk="2 BHK",
                price_min=5800000.0,
                price_max=6600000.0,
                price_display="₹58 L - ₹66 L",
                carpet_area="1120 sq.ft.",
                possession_status="Under Construction (Diwali 2026)",
                rera_id="P50500034102",
                builder_name="Heights Infrastructure",
                description="Ultra-modern 2 BHK flats in the heart of Manish Nagar close to Metro Station, market, and top schools.",
                amenities="Metro Proximity, Automated Lift, Video Door Phone, Gymnasium, Rainwater Harvesting",
                available_units=5,
            ),
            Property(
                id="prop_sonegaon_01",
                project_name="Airport View Residency",
                location="Sonegaon",
                property_type="Flat",
                bhk="3 BHK",
                price_min=7500000.0,
                price_max=8500000.0,
                price_display="₹75 L - ₹85 L",
                carpet_area="1550 sq.ft.",
                possession_status="Ready to Move",
                rera_id="P50500015690",
                builder_name="Nagpur Skyline Developers",
                description="Luxury 3 BHK residence in prestigious Sonegaon near Airport Road with high-speed elevators and 2 car parkings.",
                amenities="Airport Proximity, 2 Covered Parkings, Terrace Lounge, Smart Home Automation, Fire Safety System",
                available_units=3,
            ),
            Property(
                id="prop_mihan_01",
                project_name="Tech City Oasis",
                location="MIHAN",
                property_type="Flat",
                bhk="2 BHK",
                price_min=4200000.0,
                price_max=5000000.0,
                price_display="₹42 L - ₹50 L",
                carpet_area="980 sq.ft.",
                possession_status="Ready to Move",
                rera_id="P50500041289",
                builder_name="Oasis Group",
                description="Ideal for IT professionals working in TCS, Infosys, and HCL in MIHAN SEZ with rental yield potential.",
                amenities="Clubhouse, Shuttle Service to SEZ, Badminton Court, Supermarket inside campus",
                available_units=8,
            ),
            Property(
                id="prop_civil_01",
                project_name="The Grand Heritage",
                location="Civil Lines",
                property_type="Luxury Apartment",
                bhk="4 BHK",
                price_min=18000000.0,
                price_max=24000000.0,
                price_display="₹1.80 Cr - ₹2.40 Cr",
                carpet_area="2800 sq.ft.",
                possession_status="Ready to Move",
                rera_id="P50500055123",
                builder_name="Heritage Luxury Spaces",
                description="Exclusive 4 BHK ultra-luxury apartment in lush green Civil Lines with private foyer and concierge service.",
                amenities="Infinity Pool, Concierge, Private Elevator, Banquet Hall, Spa & Jacuzzi, 3 Parkings",
                available_units=2,
            ),
        ]
        db.add_all(seed_properties)
        db.commit()
        logger.info(f"Seeded {len(seed_properties)} properties successfully.")

    # 2. Seed default users
    if db.query(User).count() == 0:
        logger.info("Seeding default CRM users...")
        admin_user = User(
            id="usr_admin_01",
            email="admin@nagpurestates.com",
            name="Rohit Patil",
            role="admin",
            password_hash="admin123",
        )
        agent_user = User(
            id="usr_agent_01",
            email="priya@nagpurestates.com",
            name="Priya Sharma",
            role="sales_agent",
            password_hash="agent123",
        )
        db.add_all([admin_user, agent_user])
        db.commit()

    # 3. Seed sample leads
    if db.query(Lead).count() == 0:
        logger.info("Seeding initial CRM leads...")
        sample_leads = [
            Lead(
                id="lead_001",
                name="Rahul",
                phone_number="+918600079496",
                masked_phone="+91860****96",
                preferred_location="Besa",
                property_type="Flat",
                bhk="2 BHK",
                budget_min=5000000.0,
                budget_max=6500000.0,
                purchase_purpose="Self-use",
                purchase_timeline="1-2 months",
                lead_temperature="hot",
                stage="qualified",
                assigned_agent="Priya",
                notes="Inquired about 2 BHK flats near Besa. Interested in ready to move properties.",
            ),
            Lead(
                id="lead_002",
                name="Amit Deshmukh",
                phone_number="+919823012345",
                masked_phone="+91982****45",
                preferred_location="Wardha Road",
                property_type="Plot",
                bhk="Plot",
                budget_min=2000000.0,
                budget_max=3000000.0,
                purchase_purpose="Investment",
                purchase_timeline="Immediate",
                lead_temperature="warm",
                stage="property_matched",
                assigned_agent="Priya",
                notes="Looking for NMRDA approved plots near MIHAN SEZ.",
            ),
            Lead(
                id="lead_003",
                name="Sneha Kulkarni",
                phone_number="+919765432100",
                masked_phone="+91976****00",
                preferred_location="Manish Nagar",
                property_type="Flat",
                bhk="2 BHK",
                budget_min=5500000.0,
                budget_max=6500000.0,
                purchase_purpose="Self-use",
                purchase_timeline="Diwali",
                lead_temperature="warm",
                stage="contacted",
                assigned_agent="Priya",
                notes="Wants metro-connected apartment in Manish Nagar.",
            ),
            Lead(
                id="lead_004",
                name="Vikram Joshi",
                phone_number="+919422155890",
                masked_phone="+91942****90",
                preferred_location="Sonegaon",
                property_type="Flat",
                bhk="3 BHK",
                budget_min=7000000.0,
                budget_max=8500000.0,
                purchase_purpose="Self-use",
                purchase_timeline="Immediate",
                lead_temperature="hot",
                stage="site_visit",
                assigned_agent="Priya",
                site_visit_interested=True,
                notes="Site visit scheduled for Airport View Residency.",
            ),
        ]
        db.add_all(sample_leads)
        db.commit()
        logger.info(f"Seeded {len(sample_leads)} CRM leads.")

    # 3. Seed default admin user
    if db.query(User).count() == 0:
        admin_email = os.getenv("ADMIN_EMAIL", "admin@nagpurestates.com").strip().lower()
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
        admin_user = User(
            id="usr_admin_01",
            email=admin_email,
            name="Admin Manager",
            role="admin",
            password_hash=hash_password(admin_password),
        )
        db.add(admin_user)
        db.commit()
        logger.info(f"Seeded default CRM admin user: {admin_email}")

    # 4. Seed initial campaigns if none exist
    if db.query(Campaign).count() == 0:
        cmp1 = Campaign(
            id="cmp_besa_01",
            name="Besa 2 BHK Warm Buyers",
            description="Outbound follow-up campaign for leads inquiring about Greenwood Meadows & Besa properties.",
            target_locality="Besa",
            target_property_type="Flat",
            goal="site_visit_booking",
            concurrency=2,
            status="ready",
        )
        cmp2 = Campaign(
            id="cmp_wardha_01",
            name="Wardha Road Plot Inquiries",
            description="Verification calls for commercial and residential plot investors near MIHAN Corridor.",
            target_locality="Wardha Road",
            target_property_type="Plot",
            goal="qualification",
            concurrency=1,
            status="ready",
        )
        db.add_all([cmp1, cmp2])
        db.commit()

        # Attach sample leads to campaign
        besa_leads = db.query(Lead).filter(Lead.preferred_location == "Besa").limit(10).all()
        for l in besa_leads:
            db.add(CampaignLead(campaign_id=cmp1.id, lead_id=l.id, status="ready"))

        wardha_leads = db.query(Lead).filter(Lead.preferred_location == "Wardha Road").limit(10).all()
        for l in wardha_leads:
            db.add(CampaignLead(campaign_id=cmp2.id, lead_id=l.id, status="ready"))

        db.commit()
        logger.info("Seeded default outbound voice campaigns.")

    # 5. Seed default training scripts & human-like conversational playbooks
    if db.query(AgentScript).count() == 0:
        script_fillers = AgentScript(
            id="scr_fillers_01",
            title="Human-Like Natural Fillers & Conversational Flow",
            category="fillers",
            domain="real_estate",
            content=(
                "Rules for Human-Like Conversational Speech:\n"
                "- Use natural Hindi/Hinglish fillers and backchannels frequently: 'Haan ji', 'Achha', 'Hmm', 'Bilkul', 'Sahi baat hai', 'Waise...', 'Um, actually...', 'Dekhiye'.\n"
                "- Never sound like a robotic IVR or stiff corporate agent. Sound like a polite, warm, energetic local Nagpur property advisor.\n"
                "- When the customer gives information, acknowledge first with a verbal nod before answering: e.g. 'Achha, Besa side dekh rahe hain? Bahut badhiya!', or 'Hmm, bilkul samajh sakti hoon'.\n"
                "- Keep answers crisp, 10–25 words per turn. Pause naturally and invite them to speak."
            ),
            is_active=True,
        )

        script_verification = AgentScript(
            id="scr_verify_01",
            title="Dedicated Lead Verification & Wrong Number Pivot",
            category="identity_verification",
            domain="real_estate",
            content=(
                "Rules for Opening Name Verification & Polite Sales Pivot:\n"
                "- Always open by checking the lead name: 'Namaste, kya meri baat {customer_name} ji se ho rahi hai?'\n"
                "- If confirmed ('Haan', 'Ji haan', 'Haan boliye', 'Yes'): Proceed warmly: 'Great! Main Priya bol rahi hoon Nagpur Estates se. Aapne property ke liye enquiry ki thi, toh kya abhi do minute baat ho sakti hai?'\n"
                "- If wrong person / not them ('Nahi, galat number hai' / 'Main {customer_name} nahi hoon'):\n"
                "  Do NOT hang up immediately. Pivot politely and warmly:\n"
                "  'Achha, koi baat nahi ji! Darasal hume is number par {customer_name} ji ke naam se Nagpur mein property ki enquiry aayi thi. Waise kya aap khud Nagpur mein kisi flat ya plot mein interested hain?'\n"
                "  - If they say 'Haan, main dekh raha hoon': Pivot into discovery: 'Wah, bahut badhiya! Aap Besa ya Manish Nagar side dekh rahe hain? Aur 2 BHK flat ya plot?'\n"
                "  - If they say 'Nahi, bilkul nahi' / 'Rakh dijiye phone': Say 'Theek hai ji, koi baat nahi. Have a great day!' and call end_call(reason='wrong_number').\n"
                "- If they ask 'Aap kaun bol rahe ho?' before confirming:\n"
                "  Reply: 'Main Priya baat kar rahi hoon Nagpur Estates se. Kya meri baat {customer_name} ji se ho rahi hai?'"
            ),
            is_active=True,
        )

        script_objections = AgentScript(
            id="scr_objections_01",
            title="Nagpur Real Estate Local Knowledge & Objection Handling",
            category="objections",
            domain="real_estate",
            content=(
                "Nagpur Property Highlights & Handling Objections:\n"
                "- Prime Areas: Besa (near Pipla road, booming residential hub), Manish Nagar (metro proximity, high rental demand), Wardha Road (MIHAN SEZ, IT parks, airport corridor).\n"
                "- Projects: Greenwood Meadows in Besa (2 BHK ready possession, ₹52L-₹62L, swimming pool, clubhouse, RERA approved).\n"
                "- If budget is low (under 40 Lakhs): Recommend Wardha Road / Beltarodi emerging layouts or NMRDA sanctioned plots.\n"
                "- If customer asks for WhatsApp: Agree warmly ('Ji bilkul, main abhi brochure aur verified pricing WhatsApp par share kar deti hoon'), check if they want to review and talk tomorrow, and only say goodbye once confirmed."
            ),
            is_active=True,
        )

        db.add_all([script_fillers, script_verification, script_objections])
        db.commit()
        logger.info("Seeded default AgentScript training playbooks.")

    # 6. Seed default AgentConfig persona if none exists
    if db.query(AgentConfig).count() == 0:
        default_config = AgentConfig(
            id="cfg_default_01",
            name="Nagpur Estates - Priya Consultative Persona",
            agent_display_name="Priya",
            company_name="Nagpur Estates",
            role_description="an exceptionally warm, friendly, natural, and articulate real-estate sales advisor calling from Nagpur Estates, Nagpur's most trusted property firm.",
            voice="Aoede",
            temperature=0.6,
            language_mode="hinglish",
            greeting_known_lead="Namaste, kya meri baat {customer_name} ji se ho rahi hai?",
            greeting_unknown_lead="Namaste ji, main {agent_name} bol rahi hoon {company_name} se. Aapne property enquiry ki thi. Kya abhi do minute baat ho sakti hai?",
            wrong_number_pivot="Achha, koi baat nahi ji! Darasal hume is number par {customer_name} ji ke naam se Nagpur mein property ki enquiry aayi thi. Waise kya aap khud Nagpur mein kisi flat ya residential plot mein interested hain?",
            conversation_philosophy=(
                "- Sound 100% like a real, enthusiastic human sales advisor on a phone call, NEVER like an AI or IVR bot.\n"
                "- Naturally use conversational fillers, backchannels, and verbal nods: 'Haan ji', 'Achha', 'Hmm', 'Bilkul', 'Sahi baat hai', 'Waise...', 'Um, actually...', 'Dekhiye', 'Ji samajh gayi'.\n"
                "- Give empathetic verbal nods before answering questions or objections (e.g. 'Achha, Besa side dekh rahe hain? Bahut badhiya!', or 'Hmm, budget ka concern samajh sakti hoon').\n"
                "- Keep your answers short, crisp, and conversational (usually 10–25 words, 1–2 short sentences). Never give long speech monologues.\n"
                "- Speak with natural Indian conversational energy, vocal warmth, and breathing pauses.\n"
                "- Ask strictly ONE clear question at a time. Never barrage the customer with multiple questions.\n"
                "- Support Hindi, English, Marathi, and Hinglish with natural code-switching.\n"
                "- Mirror the customer's language immediately (if Hindi, speak Hindi; if Marathi, speak warm Marathi/Hinglish; if English, speak English).\n"
                "- Format Indian currency phonetically (e.g. '55 Lakhs', '60 se 70 Lakh', '1.5 Crore'). Never output raw numeric symbols like ₹5500000."
            ),
            sales_funnel_stages=(
                "1. DISCOVER:\n"
                "   - When customer confirms ('Haan', 'Bolo', 'Aapki marzi'):\n"
                "     'Great! Aap Besa ya Manish Nagar side dekh rahe hain? Aur 2 BHK flat ya residential plot?'\n"
                "2. MATCH & RECOMMEND:\n"
                "   - As soon as customer mentions area or BHK, immediately call search_properties(location=..., bhk=...).\n"
                "   - Recommend 1 attractive match with a compelling highlight:\n"
                "     'Haan ji, Besa mein hamare paas Greenwood Meadows project hai — ready-to-move 2 BHK sirf 55 Lakhs mein with clubhouse and amenities.'\n"
                "3. ADDRESS CONCERNS:\n"
                "   - If budget is tight: 'Achha, Wardha Road aur Besa mein hamare paas 35 se 45 Lakhs ke budget mein bhi verified options hain.'\n"
                "   - If already purchased: 'Congratulations! Waise kya future investment ya rental income ke liye koi plot dekhna chahenge?'\n"
                "4. SITE VISIT PUSH:\n"
                "   - Directly invite customer for site visit:\n"
                "     'Is weekend hamari taraf se free cab pick-and-drop facility available hai. Kya Saturday ya Sunday 11 baje site visit dekhna convenient rahega?'\n"
                "5. BOOK, CONFIRM & CLOSE:\n"
                "   - When customer agrees ('Saturday theek hai' / 'Sunday subah'):\n"
                "     Call schedule_site_visit(location=..., preferred_datetime=...).\n"
                "     Say closing sentence: 'Perfect {cust_ji}! Aapka site visit confirm ho gaya hai. Main property brochure aur location aapke WhatsApp par share kar rahi hoon. Have a wonderful day!'\n"
                "     Immediately call end_call(reason='site_visit_booked')."
            ),
            objection_guardrails=(
                "- If customer asks if you are AI/bot: 'Ji, main {company_name} ki AI property advisor hoon, aur main aapko best properties discover karne mein help kar sakti hoon.'\n"
                "- If customer says 'WhatsApp kar dijiye': Agree warmly ('Ji bilkul {cust_ji}, main abhi project brochure aur verified price details WhatsApp par share kar deti hoon.'), check if they want a follow-up call tomorrow, and call end_call(reason='whatsapp_sent').\n"
                "- If customer is busy: Ask 'Bilkul samajh sakti hoon {cust_ji}. Kya shaam ko 5 baje call karoon ya kal subah?', call create_callback(), and call end_call(reason='callback_scheduled').\n"
                "- If customer is not interested / DND: Call mark_dnd(), say 'Koi baat nahi {cust_ji}, aapka din shubh ho! Thank you!', and call end_call(reason='not_interested').\n"
                "- CRITICAL RULE FOR CALL ENDING: NEVER call end_call while asking a question or expecting customer to reply."
            ),
            is_active=True,
        )
        db.add(default_config)
        db.commit()
        logger.info("Seeded default AgentConfig (Priya Consultative Persona).")


def _migrate_schema():
    """Ensure newly added columns exist in SQLite or PostgreSQL without dropping tables."""
    from sqlalchemy import text
    
    migrations = [
        # Table 'calls'
        ("calls", "campaign_id", "VARCHAR(64)"),
        ("calls", "campaign_lead_id", "VARCHAR(64)"),
        ("calls", "attempt_number", "INTEGER DEFAULT 1"),
        # Table 'campaigns'
        ("campaigns", "agent_config_id", "VARCHAR(64)"),
        ("campaigns", "total_leads", "INTEGER DEFAULT 0"),
        ("campaigns", "queued_leads", "INTEGER DEFAULT 0"),
        ("campaigns", "active_calls", "INTEGER DEFAULT 0"),
        ("campaigns", "completed_leads", "INTEGER DEFAULT 0"),
        ("campaigns", "failed_leads", "INTEGER DEFAULT 0"),
        ("campaigns", "max_observed_active_calls", "INTEGER DEFAULT 0"),
        ("campaigns", "started_at", "TIMESTAMP"),
        ("campaigns", "completed_at", "TIMESTAMP"),
        # Table 'campaign_leads'
        ("campaign_leads", "last_call_status", "VARCHAR(64)"),
        ("campaign_leads", "started_at", "TIMESTAMP"),
        ("campaign_leads", "completed_at", "TIMESTAMP"),
        # Table 'agent_configs'
        ("agent_configs", "domain", "VARCHAR(64) DEFAULT 'real_estate'"),
        ("agent_configs", "gender", "VARCHAR(16) DEFAULT 'female'"),
        # Table 'agent_scripts'
        ("agent_scripts", "domain", "VARCHAR(64) DEFAULT 'real_estate'"),
    ]
    
    is_sqlite = DATABASE_URL.startswith("sqlite")
    
    with engine.begin() as conn:
        for table, col, col_type in migrations:
            try:
                if is_sqlite:
                    # Check column existence via pragma
                    pragma_res = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                    existing_cols = [row[1] for row in pragma_res]
                    if col not in existing_cols:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                        logger.info(f"MIGRATION | Added column {col} to SQLite table {table}")
                else:
                    # PostgreSQL supports ADD COLUMN IF NOT EXISTS
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
            except Exception as e:
                logger.debug(f"Column migration check note for {table}.{col}: {e}")

        # Data backfill: ensure existing rows have domain populated
        try:
            conn.execute(text("UPDATE agent_scripts SET domain = 'real_estate' WHERE domain IS NULL OR domain = ''"))
            conn.execute(text("UPDATE agent_configs SET domain = 'real_estate' WHERE domain IS NULL OR domain = ''"))
            conn.execute(text("UPDATE agent_configs SET gender = 'female' WHERE gender IS NULL OR gender = ''"))
        except Exception as e:
            logger.debug(f"Domain backfill note: {e}")


def init_db():
    """Create all database tables, migrate schema, and seed initial catalog."""
    logger.info(f"Initializing database schema at: {DATABASE_URL}")
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    with get_db_session() as db:
        seed_initial_data(db)
    logger.info("Database schema initialized successfully.")
