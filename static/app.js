/**
 * Nagpur Estates AI Voice CRM — Enterprise Frontend Architecture
 * Single Page Application Controller with Real-Time Gemini 3.1 Live Audio Tracking
 */

const AppState = {
  authToken: localStorage.getItem('nagpur_crm_token') || null,
  currentUser: null,
  currentView: 'dashboard',
  leads: [],
  selectedLeads: new Set(),
  campaigns: [],
  activeCampaignId: null,
  activeCampaignData: null,
  newCampaignSelectedLeads: new Set(),
  addLeadsSelectedLeads: new Set(),
  activeCallId: null,
  liveCallPollInterval: null,
  liveCallSeconds: 0,
  currentLeadInDrawer: null,
  debounceTimer: null,
  theme: localStorage.getItem('crm-theme') || 'light',
  isSidebarCollapsed: localStorage.getItem('sidebar-collapsed') === 'true',
  properties: [],
  calls: [],
  siteVisits: [],
  callbacks: [],
  knowledgeDocs: [],
  agentScripts: [],
  agentConfig: null,
  agentVoices: [],
  selectedVoice: 'Aoede',
  activeStudioTab: 'persona',
  kbActiveTab: 'scripts'
};

const DOMAIN_CLIENT_PRESETS = {
  real_estate: {
    domain: 'real_estate',
    name: 'Real Estate Sales & Advisory',
    agent_name: 'Priya',
    female_name: 'Priya',
    male_name: 'Parth',
    company_name: 'Nagpur Estates',
    gender: 'female',
    voice: 'Aoede',
    role_description: "an exceptionally warm, friendly, natural, and articulate real-estate sales advisor calling from {company_name}, Nagpur's most trusted property firm.",
    greeting_known: "Namaste, kya meri baat {customer_name} ji se ho rahi hai?",
    greeting_unknown: "Namaste ji, main {agent_name} {v_bol} {company_name} se. Aapne property enquiry ki thi. Kya abhi do minute baat ho sakti hai?",
    wrong_number: "Achha, koi baat nahi ji! Darasal hume is number par {customer_name} ji ke naam se Nagpur mein property ki enquiry aayi thi. Waise kya aap khud Nagpur mein kisi flat ya residential plot mein interested hain?",
    funnel: `1. DISCOVER: Ask location & configuration preference (e.g., Besa or Manish Nagar? 2 BHK flat or plot?).
2. MATCH & RECOMMEND: Call search_properties and highlight 1 attractive match with key amenities & verified RERA status.
3. ADDRESS CONCERNS: Budget alternatives (Wardha Road/Beltarodi), possession timeline, bank loan assistance.
4. SITE VISIT PUSH: Proactively offer free weekend cab pick-and-drop facility. Ask Saturday or Sunday 11 AM.
5. BOOK & CLOSE: Confirm appointment with schedule_site_visit, send details on WhatsApp, warm farewell with end_call.`,
    philosophy: `- Sound 100% like a real, enthusiastic human sales advisor on a phone call, NEVER like an AI or IVR bot.
- Naturally use conversational fillers and backchannels: 'Haan ji', 'Achha', 'Hmm', 'Bilkul', 'Sahi baat hai', 'Waise...', 'Dekhiye'.
- Give empathetic verbal nods before answering questions: 'Achha, Besa side dekh rahe hain? Bahut badhiya!', or 'Hmm, budget ka concern {v_sakti}'.
- Keep your answers short, crisp, and conversational (10–25 words). Never give long monologues.
- Speak with natural Indian conversational energy, vocal warmth, and breathing pauses.
- Ask strictly ONE clear question at a time.
- Mirror customer language (Hindi, Marathi, English, Hinglish) seamlessly.
- Format Indian currency phonetically (e.g. '55 Lakhs', '1.2 Crore').`,
    guardrails: `- If customer asks if you are AI: 'Ji, main {company_name} ki AI property advisor hoon, aur main aapko best properties discover karne mein help {v_kar_sakti}.'
- If customer wants WhatsApp details: Agree warmly, confirm sending brochure, ask if okay to follow up tomorrow, then close politely.
- If busy: Ask 'Kya shaam ko 5 baje call karoon ya kal subah?', schedule callback, and politely disconnect.
- If not interested/DND: Mark DND, say polite farewell, and end call.
- CRITICAL: Never call end_call while asking a question. Only call it when delivering final polite farewell.`
  },
  clinic_hospital: {
    domain: 'clinic_hospital',
    name: 'Hospital & Clinic Receptionist',
    agent_name: 'Ananya',
    female_name: 'Ananya',
    male_name: 'Parth',
    company_name: 'CarePlus Super-Specialty Clinic',
    gender: 'female',
    voice: 'Kore',
    role_description: 'a deeply caring, professional, calm, and articulate clinic coordinator calling from {company_name}, providing medical appointment scheduling and healthcare assistance.',
    greeting_known: 'Namaste, kya meri baat {customer_name} ji se ho rahi hai?',
    greeting_unknown: 'Namaste ji, main {agent_name} {v_bol} {company_name} se. Aapne doctor consultation ya clinic visit ke liye enquiry ki thi. Kya main aapki help {v_kar_sakti}?',
    wrong_number: 'Achha, koi baat nahi ji! Hume is number par {customer_name} ji ke naam se healthcare enquiry mili thi. Maaf kijiyega disturb karne ke liye. Have a healthy day!',
    funnel: `1. INQUIRE & TRIAGE: Ask what specialty or doctor consultation is required (e.g. General Medicine, Orthopedic, Pediatric, Dental, Cardiology).
2. CHECK DOCTOR AVAILABILITY: Call check_doctor_availability(specialty=..., date=...) and inform available OPD time slots (Morning 10 AM - 1 PM or Evening 5 PM - 8 PM).
3. APPOINTMENT CONFIRMATION: Ask preferred date and slot. Once customer agrees, call book_appointment(patient_name=..., specialty=..., slot_datetime=...).
4. CLINIC LOGISTICS: Mention clinic location, parking facility, and tell them to arrive 10 minutes before the scheduled time.
5. WRAP & WHATSAPP: Send appointment token and clinic Google Maps location to their WhatsApp. Warm goodbye and call end_call.`,
    philosophy: `- Speak with extreme empathy, reassurance, warmth, and composure. Patients or relatives may be anxious.
- Use caring backchannels: 'Ji bilkul', 'Haan ji', 'Aap chinta mat kijiye', 'Theek hai ji', 'Bilkul samajh rahi/raha hoon'.
- Maintain professional clarity without diagnosing illnesses or prescribing medication.
- Keep answers clear, patient, and direct (under 25 words).
- Strictly ask one question at a time (e.g. preferred department or doctor, date, morning or evening slot).`,
    guardrails: `- EMERGENCY PROTOCOL: If patient reports severe chest pain, breathlessness, accident, or acute emergency, immediately state: 'Yeh emergency situation lag rahi hai. Kripya bina der kiye turant nazdeeki emergency room pahuchein ya 108 ambulance call karein.' Do not attempt to book routine OPD.
- NO PRESCRIPTION: Never advise medicines or dosages over phone. Only state: 'Doctor sahab checkup ke baad hi sahi advice de paayenge.'
- Consultation Fee query: Inform standard OPD consultation fee (e.g. ₹500 to ₹800 including 7 days validity).
- If busy: Ask 'Kya shaam ko 5 baje call karoon ya kal subah?', schedule callback, and politely end call.`
  },
  ecommerce: {
    domain: 'ecommerce',
    name: 'E-Commerce & D2C Customer Support',
    agent_name: 'Priya',
    female_name: 'Priya',
    male_name: 'Rohan',
    company_name: 'NexStore Direct',
    gender: 'female',
    voice: 'Aoede',
    role_description: 'a highly energetic, helpful, solution-oriented customer care specialist calling from {company_name} regarding recent orders, deliveries, and customer assistance.',
    greeting_known: 'Namaste, kya meri baat {customer_name} ji se ho rahi hai?',
    greeting_unknown: 'Namaste ji, main {agent_name} {v_bol} {company_name} se. Aapke recent order enquiry ke regarding call kiya hai. Kya abhi do minute baat ho sakti hai?',
    wrong_number: 'Achha, koi baat nahi ji! Hume is number par {customer_name} ji ke order ka update share karna tha. Lagta hai number update nahi hua. Have a wonderful day!',
    funnel: `1. IDENTIFY QUERY: Check if the call is regarding order tracking, delivery delay, return/exchange, or payment issue.
2. FETCH STATUS: Call track_order_status(order_id=...) or check customer account with phone number.
3. PROVIDE REAL-TIME UPDATE: Share accurate courier tracking, expected delivery time, or pickup date.
4. RESOLVE CONCERN: If delivery delayed, escalate to priority dispatch. If return requested, trigger free doorstep pickup with request_order_return.
5. CONFIRM ON WHATSAPP: Send tracking link and support ticket ID to their WhatsApp. Deliver cheerful closing and call end_call.`,
    philosophy: `- Sound prompt, energetic, reassuring, and completely customer-first.
- Always apologize sincerely for any delivery delay or damaged item before offering an instant resolution.
- Use active verbal nods: 'Ji bilkul', 'Haan ji', 'Main abhi check {v_kar_sakti}', 'Aap fikar mat kijiye'.
- Never keep caller waiting without giving an immediate status update.
- Explain refund or replacement timelines clearly (e.g. 24–48 hours for UPI/bank, free reverse pickup).`,
    guardrails: `- Frustrated/Angry Customer: Listen patiently without interrupting. Say: 'Main aapki pareshani bilkul {v_sakti}. Main personally aapke order ko escalate kar {v_rahi}.'
- Refund Status: Refunds are credited within 24 to 48 hours after quality check of return.
- Cash on Delivery (COD) to Prepaid: Inform that paying online gives instant ₹50 discount or cashback.
- Never give false delivery guarantees. Always provide verified courier estimates.`
  },
  education: {
    domain: 'education',
    name: 'Education & Admissions Counseling',
    agent_name: 'Ananya',
    female_name: 'Ananya',
    male_name: 'Parth',
    company_name: 'Apex Academy & Institutes',
    gender: 'female',
    voice: 'Kore',
    role_description: 'an inspiring, articulate, knowledgeable educational counselor calling from {company_name}, guiding students and parents on career-oriented degree and certificate programs.',
    greeting_known: 'Namaste, kya meri baat {customer_name} ji se ho rahi hai?',
    greeting_unknown: 'Namaste ji, main {agent_name} {v_bol} {company_name} se. Aapne professional training course ke liye enquiry ki thi. Kya abhi do minute baat ho sakti hai?',
    wrong_number: 'Achha, koi baat nahi ji! Hume is number par course guidance ke liye enquiry mili thi. Kya aapke parivar mein koi student career courses dekh raha hai?',
    funnel: `1. UNDERSTAND ASPIRATION: Inquire about student's current qualification (12th passed, Graduate, Working Professional) and dream field (AI/Data, Full Stack, MBA, Design).
2. RECOMMEND COURSE: Call get_course_details and recommend the optimal batch, duration (3 to 6 months), and industry mentors.
3. SCHOLARSHIP & FEES: Explain flexible EMI options, scholarship test benefits, and placement support.
4. FREE COUNSELING / CAMPUS VISIT: Invite student/parent for a free 1-on-1 counseling session with schedule_campus_counseling.
5. CONFIRM & WHATSAPP: Send syllabus PDF and counseling pass on WhatsApp. Warm closing and call end_call.`,
    philosophy: `- Sound motivational, encouraging, knowledgeable, and genuinely invested in the student's career growth.
- Validate student or parent aspirations warmly: 'Bahut achha decision hai', 'Is field mein future bahut bright hai'.
- Simplify complex syllabus or eligibility details into crisp, actionable points.
- Highlight 100% placement assistance, live industry projects, and recognized certification.
- Ask one question at a time: educational background, preferred batch timing (weekday vs weekend).`,
    guardrails: `- Placement Guarantee Objection: 'Hum 100% dedicated placement support provide karte hain with top MNC partners and resume workshops.'
- Fee Objection: 'Hamare paas zero-interest EMI options aur up to 30% merit scholarship available hai.'
- If busy: Offer evening or weekend callback and schedule with create_callback.`
  },
  general_business: {
    domain: 'general_business',
    name: 'General Business & B2B Lead Qualification',
    agent_name: 'Parth',
    female_name: 'Priya',
    male_name: 'Parth',
    company_name: 'Prime Solutions',
    gender: 'male',
    voice: 'Charon',
    role_description: 'a polished, knowledgeable corporate consultant calling from {company_name}, discussing tailored business services, software solutions, and strategic advisory.',
    greeting_known: 'Namaste, kya meri baat {customer_name} ji se ho rahi hai?',
    greeting_unknown: 'Namaste ji, main {agent_name} {v_bol} {company_name} se. Aapne hamari business services ke regarding enquiry ki thi. Kya abhi do minute baat ho sakti hai?',
    wrong_number: 'Achha, koi baat nahi ji! Hume is number par business inquiry mili thi. Maaf kijiyega disturbance ke liye. Have a great day!',
    funnel: `1. QUALIFY NEED: Identify current business requirement and pain points.
2. CAPABILITY HIGHLIGHT: Share relevant case study or capability snapshot.
3. PROPOSE CONSULTATION: Offer a 15-minute Google Meet / Phone consultation with senior solution architect.
4. SCHEDULE & CONFIRM: Call create_callback or schedule consultation for mutual calendar slot.
5. CLOSE & WHATSAPP: Send company deck and meeting invite via WhatsApp/Email. Call end_call.`,
    philosophy: `- Maintain an articulate, executive tone with professional warmth.
- Focus on business value, efficiency, and ROI rather than superficial pitches.
- Ask clear qualification questions: company scale, primary challenge, expected timeline.
- Keep answers concise (15–25 words) and respect the executive's busy schedule.`,
    guardrails: `- Send email/deck first: 'Ji bilkul, main executive summary deck WhatsApp aur email par share kar {v_rahi}. Kya review ke baad kal subah 11 baje follow-up connect theek rahega?'
- Not decision maker: Politely ask for the right point of contact's name or direct extension.
- If busy: Instantly offer to schedule a brief callback at their convenience.`
  }
};

window.DOMAIN_CLIENT_PRESETS = DOMAIN_CLIENT_PRESETS;

window.App = {
  // ---------------------------------------------------------------------------
  // Lifecycle & Initialization
  // ---------------------------------------------------------------------------
  init() {
    this.applyTheme(AppState.theme);
    this.applySidebarCollapse(AppState.isSidebarCollapsed);
    this.setupKeyboardShortcuts();
    this.checkAuth();
    this.checkHealthStatus();
    setInterval(() => this.checkHealthStatus(), 30000);

    // Bind instantaneous domain selector listeners
    const topSelect = document.getElementById('topbar-domain-select');
    if (topSelect) {
      topSelect.addEventListener('change', (e) => this.handleDomainChange(e.target.value));
    }
    const studioSelect = document.getElementById('studio-domain-select');
    if (studioSelect) {
      studioSelect.addEventListener('change', (e) => this.handleDomainChange(e.target.value));
    }
  },

  refreshIcons() {
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
  },

  // ---------------------------------------------------------------------------
  // Centralized API Client
  // ---------------------------------------------------------------------------
  async authFetch(url, options = {}) {
    options.headers = options.headers || {};
    if (AppState.authToken) {
      if (options.headers instanceof Headers) {
        options.headers.set('Authorization', `Bearer ${AppState.authToken}`);
      } else {
        options.headers['Authorization'] = `Bearer ${AppState.authToken}`;
      }
    }

    try {
      const res = await fetch(url, options);
      if (res.status === 401) {
        console.warn('Session expired or unauthorized. Returning to login screen.');
        this.handleLogout(false);
        throw new Error('Unauthorized');
      }
      return res;
    } catch (err) {
      throw err;
    }
  },

  // ---------------------------------------------------------------------------
  // Authentication Flow
  // ---------------------------------------------------------------------------
  async checkAuth() {
    if (!AppState.authToken) {
      this.showAuthScreen();
      return;
    }

    try {
      const res = await fetch('/api/auth/me', {
        headers: { 'Authorization': `Bearer ${AppState.authToken}` }
      });

      if (res.ok) {
        const user = await res.json();
        AppState.currentUser = user;
        this.showAppScreen(user);
        this.initWorkspaceData();
      } else {
        this.showAuthScreen();
      }
    } catch (err) {
      this.showAuthScreen();
    }
  },

  showAuthScreen() {
    const authScreen = document.getElementById('auth-screen');
    const appContainer = document.getElementById('app-main-container');
    if (authScreen) authScreen.style.display = 'flex';
    if (appContainer) appContainer.style.display = 'none';
    this.refreshIcons();
  },

  showAppScreen(user) {
    const authScreen = document.getElementById('auth-screen');
    const appContainer = document.getElementById('app-main-container');
    if (authScreen) authScreen.style.display = 'none';
    if (appContainer) appContainer.style.display = 'flex';

    if (user) {
      const nameEl = document.getElementById('sidebar-user-name');
      const roleEl = document.getElementById('sidebar-user-role');
      const avatarEl = document.getElementById('sidebar-user-avatar');
      const greetingEl = document.getElementById('dash-greeting-name');

      if (nameEl) nameEl.innerText = user.name || 'Admin Manager';
      if (roleEl) roleEl.innerText = (user.role || 'Administrator').toUpperCase();
      if (avatarEl) avatarEl.innerText = (user.name || 'A')[0].toUpperCase();
      if (greetingEl) greetingEl.innerText = (user.name || 'Admin').split(' ')[0];
    }
    this.refreshIcons();
  },

  async handleLogin(event) {
    if (event) event.preventDefault();
    const email = document.getElementById('login-email')?.value.trim() || '';
    const password = document.getElementById('login-password')?.value.trim() || '';
    const errorBox = document.getElementById('login-error-box');
    const errorMsg = document.getElementById('login-error-msg');
    const btnText = document.getElementById('login-btn-text');

    if (errorBox) errorBox.classList.add('hidden');
    if (btnText) btnText.innerText = 'Signing In...';

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Invalid email or password.');
      }

      AppState.authToken = data.token;
      AppState.currentUser = data.user;
      localStorage.setItem('nagpur_crm_token', data.token);

      this.showAppScreen(data.user);
      this.initWorkspaceData();
      this.showToast('success', `Welcome back, ${data.user.name}!`);
    } catch (err) {
      if (errorMsg) errorMsg.innerText = err.message || 'Login failed';
      if (errorBox) errorBox.classList.remove('hidden');
    } finally {
      if (btnText) btnText.innerText = 'Sign In to CRM';
    }
  },

  async handleLogout(notifyServer = true) {
    if (notifyServer && AppState.authToken) {
      try {
        await fetch('/api/auth/logout', { method: 'POST' });
      } catch {}
    }
    AppState.authToken = null;
    AppState.currentUser = null;
    localStorage.removeItem('nagpur_crm_token');
    this.showAuthScreen();
    this.showToast('info', 'Logged out successfully.');
  },

  togglePasswordVisibility(inputId) {
    const input = document.getElementById(inputId);
    if (input) {
      input.type = input.type === 'password' ? 'text' : 'password';
    }
  },

  // ---------------------------------------------------------------------------
  // Health & AI Engine Probe
  // ---------------------------------------------------------------------------
  async checkHealthStatus() {
    try {
      const res = await fetch('/health');
      if (res.ok) {
        const data = await res.json();
        const headerBadge = document.getElementById('header-live-badge');
        const headerText = document.getElementById('header-live-text');
        const sidebarLabel = document.getElementById('sidebar-agent-status-label');
        const pulseDot = document.getElementById('sidebar-pulse-dot');

        if (headerBadge) {
          headerBadge.className = 'hidden sm:flex items-center gap-2 px-2.5 py-1 rounded-full bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300 text-xs font-semibold';
        }
        if (headerText) headerText.innerText = 'Gemini 3.1 Operational';
        if (sidebarLabel) {
          sidebarLabel.innerText = 'Operational';
          sidebarLabel.className = 'text-[10px] text-emerald-400 font-medium';
        }
        if (pulseDot) pulseDot.className = 'pulse-dot-green flex-shrink-0';
      }
    } catch (e) {
      const sidebarLabel = document.getElementById('sidebar-agent-status-label');
      if (sidebarLabel) {
        sidebarLabel.innerText = 'Offline';
        sidebarLabel.className = 'text-[10px] text-red-400 font-medium';
      }
    }
  },

  // ---------------------------------------------------------------------------
  // Workspace Navigation & Router
  // ---------------------------------------------------------------------------
  navigate(viewName) {
    AppState.currentView = viewName;

    document.querySelectorAll('.nav-item').forEach(item => {
      const target = item.getAttribute('data-view');
      item.classList.toggle('active', target === viewName);
    });

    document.querySelectorAll('.view-pane').forEach(pane => {
      pane.classList.toggle('hidden', pane.id !== `view-${viewName}`);
    });

    const titles = {
      'dashboard': { title: 'CRM Dashboard', subtitle: 'Real estate sales command & outbound voice operations' },
      'leads': { title: 'Leads Pipeline', subtitle: 'Manage buyers, budget qualification & outbound dialing' },
      'campaigns': { title: 'AI Calling Campaigns', subtitle: 'Automated batch dialing workflows, concurrency & campaign leads' },
      'calls': { title: 'Call History & Transcripts', subtitle: 'Gemini 3.1 Live turns, latency metrics & recordings' },
      'properties': { title: 'Property Inventory', subtitle: 'Nagpur residential & commercial listings for AI matching' },
      'knowledge-base': { title: 'AI Prompting & Training Studio', subtitle: 'Tune agent identity, Gemini voices, opening greetings, and conversational playbooks' },
      'rag-playground': { title: 'RAG Retrieval Sandbox', subtitle: 'Test real-time similarity search & chunk extraction' },
      'site-visits': { title: 'Site Visits Schedule', subtitle: 'On-site property tours and customer confirmations' },
      'follow-ups': { title: 'Follow-ups & Callbacks', subtitle: 'Scheduled customer callbacks and reminders' },
      'analytics': { title: 'Voice AI & Sales Analytics', subtitle: 'Latency P50/P90, duration & locality demand metrics' }
    };

    const info = titles[viewName] || { title: 'Nagpur Estates CRM', subtitle: 'AI Voice Operating System' };
    const titleEl = document.getElementById('header-page-title');
    const subtitleEl = document.getElementById('header-page-subtitle');
    if (titleEl) titleEl.innerText = info.title;
    if (subtitleEl) subtitleEl.innerText = info.subtitle;

    this.closeMobileSidebar();
    this.loadViewData(viewName);
    this.refreshIcons();
  },

  loadViewData(viewName) {
    if (!AppState.authToken) return;
    if (viewName === 'dashboard') this.loadDashboardData();
    else if (viewName === 'leads') this.fetchLeads();
    else if (viewName === 'campaigns') this.fetchCampaigns();
    else if (viewName === 'properties') this.fetchProperties();
    else if (viewName === 'knowledge-base') {
      this.fetchAgentConfig();
      this.fetchAgentVoices();
      this.fetchAgentScripts();
      this.fetchKnowledgeDocs();
    }
    else if (viewName === 'calls') this.fetchCalls();
    else if (viewName === 'site-visits') this.fetchSiteVisits();
    else if (viewName === 'follow-ups') this.fetchCallbacks();
    else if (viewName === 'analytics') this.fetchAnalytics();
  },

  initWorkspaceData() {
    this.loadDashboardData();
    this.fetchLeads();
    this.fetchCampaigns();
    this.fetchProperties();
    this.fetchKnowledgeDocs();
    this.fetchCalls();
    this.fetchSiteVisits();
    this.fetchCallbacks();
    this.fetchAnalytics();
  },

  openMobileSidebar() {
    const sidebar = document.getElementById('app-sidebar');
    const overlay = document.getElementById('mobile-sidebar-overlay');
    if (sidebar) sidebar.classList.add('mobile-open');
    if (overlay) overlay.classList.add('active');
    this.refreshIcons();
  },

  closeMobileSidebar() {
    const sidebar = document.getElementById('app-sidebar');
    const overlay = document.getElementById('mobile-sidebar-overlay');
    if (sidebar) sidebar.classList.remove('mobile-open');
    if (overlay) overlay.classList.remove('active');
  },

  toggleSidebarCollapse() {
    AppState.isSidebarCollapsed = !AppState.isSidebarCollapsed;
    localStorage.setItem('sidebar-collapsed', AppState.isSidebarCollapsed);
    this.applySidebarCollapse(AppState.isSidebarCollapsed);
  },

  applySidebarCollapse(isCollapsed) {
    const sidebar = document.getElementById('app-sidebar');
    const icon = document.getElementById('sidebar-collapse-icon');
    if (sidebar) {
      sidebar.classList.toggle('collapsed', isCollapsed);
    }
    if (icon) {
      icon.setAttribute('data-lucide', isCollapsed ? 'chevrons-right' : 'chevrons-left');
    }
    this.refreshIcons();
  },

  // ---------------------------------------------------------------------------
  // Theme Management
  // ---------------------------------------------------------------------------
  toggleTheme() {
    const nextTheme = AppState.theme === 'dark' ? 'light' : 'dark';
    AppState.theme = nextTheme;
    localStorage.setItem('crm-theme', nextTheme);
    this.applyTheme(nextTheme);
  },

  applyTheme(theme) {
    const isDark = theme === 'dark';
    document.body.classList.toggle('dark', isDark);
    const themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
      themeBtn.innerHTML = isDark
        ? '<i data-lucide="sun" class="w-4 h-4 text-amber-400"></i>'
        : '<i data-lucide="moon" class="w-4 h-4"></i>';
    }
    this.refreshIcons();
  },

  // ---------------------------------------------------------------------------
  // Toast Notification System
  // ---------------------------------------------------------------------------
  showToast(type, message, duration = 3500) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `crm-toast toast-${type}`;

    const icons = {
      success: '<i data-lucide="check-circle" class="w-4 h-4 text-emerald-500 flex-shrink-0"></i>',
      error: '<i data-lucide="alert-circle" class="w-4 h-4 text-red-500 flex-shrink-0"></i>',
      warning: '<i data-lucide="alert-triangle" class="w-4 h-4 text-amber-500 flex-shrink-0"></i>',
      info: '<i data-lucide="info" class="w-4 h-4 text-blue-500 flex-shrink-0"></i>'
    };

    toast.innerHTML = `
      ${icons[type] || icons.info}
      <div class="flex-1 text-xs font-medium">${message}</div>
      <button class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200" onclick="this.parentElement.remove()">
        <i data-lucide="x" class="w-3.5 h-3.5"></i>
      </button>
    `;

    container.appendChild(toast);
    this.refreshIcons();

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      setTimeout(() => toast.remove(), 200);
    }, duration);
  },

  // ---------------------------------------------------------------------------
  // 1. Dashboard View Logic
  // ---------------------------------------------------------------------------
  async loadDashboardData() {
    try {
      const res = await this.authFetch('/api/dashboard');
      const data = await res.json();

      const kpis = data.kpis;
      document.getElementById('kpi-total-leads').innerText = kpis.total_leads;
      document.getElementById('kpi-hot-leads').innerText = kpis.hot_leads;
      document.getElementById('kpi-total-calls').innerText = kpis.total_calls;
      document.getElementById('kpi-completed-calls').innerText = kpis.completed_calls;
      document.getElementById('kpi-site-visits').innerText = kpis.site_visits;
      document.getElementById('kpi-conversion-rate').innerText = `${kpis.conversion_rate}%`;

      const badgeLeads = document.getElementById('badge-leads-count');
      const badgeCallbacks = document.getElementById('badge-callbacks-due');
      if (badgeLeads) badgeLeads.innerText = kpis.total_leads;
      if (badgeCallbacks) badgeCallbacks.innerText = kpis.callbacks_due;

      // Pipeline Stepper
      const stepper = document.getElementById('dash-pipeline-stepper');
      if (stepper) {
        stepper.innerHTML = Object.entries(data.pipeline).map(([stage, count]) => `
          <div class="flex-1 p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center min-w-[90px]">
            <div class="text-[10px] font-bold uppercase tracking-wider text-slate-500 truncate">${stage.replace('_', ' ')}</div>
            <div class="text-lg font-black text-indigo-600 dark:text-indigo-400 mt-1">${count}</div>
          </div>
        `).join('');
      }

      // Recent CRM Activities
      const actTbody = document.getElementById('dash-activity-rows');
      if (actTbody) {
        if (!data.recent_activities || !data.recent_activities.length) {
          actTbody.innerHTML = `<tr><td colspan="4" class="text-center text-slate-400 py-6">No recent activity recorded.</td></tr>`;
        } else {
          actTbody.innerHTML = data.recent_activities.map(a => `
            <tr>
              <td class="text-slate-400 text-xs whitespace-nowrap">${this.formatDate(a.created_at)}</td>
              <td><span class="crm-badge crm-badge-stage">${a.type.replace('_', ' ')}</span></td>
              <td class="text-xs text-slate-700 dark:text-slate-300">${a.description}</td>
              <td class="text-xs font-mono text-slate-400">${a.lead_id || 'N/A'}</td>
            </tr>
          `).join('');
        }
      }
      this.refreshIcons();
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
    }
  },

  // ---------------------------------------------------------------------------
  // 2. Leads Pipeline Logic
  // ---------------------------------------------------------------------------
  debounceFetchLeads() {
    clearTimeout(AppState.debounceTimer);
    AppState.debounceTimer = setTimeout(() => this.fetchLeads(), 250);
  },

  async fetchLeads() {
    const search = document.getElementById('lead-search-input')?.value || '';
    const stage = document.getElementById('lead-stage-filter')?.value || 'all';
    const temp = document.getElementById('lead-temp-filter')?.value || 'all';
    const loc = document.getElementById('lead-loc-filter')?.value || 'all';

    const tbody = document.getElementById('leads-table-rows');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center text-slate-400 py-8">Loading leads...</td></tr>`;
    }

    try {
      const res = await this.authFetch(`/api/leads?search=${encodeURIComponent(search)}&stage=${stage}&temperature=${temp}&location=${loc}`);
      const data = await res.json();
      AppState.leads = data.leads || [];

      const allCountChip = document.getElementById('count-chip-all');
      if (allCountChip) allCountChip.innerText = data.total || 0;

      if (!data.leads || !data.leads.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-slate-400 py-10">No leads match your filter criteria.</td></tr>`;
        return;
      }

      tbody.innerHTML = data.leads.map(l => {
        const isChecked = AppState.selectedLeads.has(l.id);
        const tempBadge = l.lead_temperature === 'hot'
          ? `<span class="crm-badge crm-badge-hot">🔥 Hot</span>`
          : l.lead_temperature === 'warm'
          ? `<span class="crm-badge crm-badge-warm">⚡ Warm</span>`
          : `<span class="crm-badge crm-badge-cold">❄️ Cold</span>`;

        return `
          <tr class="${isChecked ? 'bg-indigo-50/50 dark:bg-indigo-950/20' : ''}">
            <td data-label="Select">
              <input type="checkbox" onchange="App.toggleLeadSelection('${l.id}')" ${isChecked ? 'checked' : ''} class="rounded text-indigo-600">
            </td>
            <td data-label="Customer">
              <div class="flex items-center gap-2.5">
                <div class="w-8 h-8 rounded-full bg-indigo-50 dark:bg-slate-800 text-indigo-700 dark:text-indigo-300 font-bold text-xs flex items-center justify-center flex-shrink-0">
                  ${(l.name || 'C')[0].toUpperCase()}
                </div>
                <div class="leading-tight">
                  <a href="javascript:void(0)" onclick="App.openLeadDrawer('${l.id}')" class="font-bold text-xs sm:text-sm text-slate-900 dark:text-white hover:text-indigo-600 transition-colors">
                    ${l.name}
                  </a>
                  <div class="text-[11px] text-slate-400">${l.purchase_timeline || 'Immediate'}</div>
                </div>
              </div>
            </td>
            <td data-label="Phone">
              <span class="font-mono text-xs text-slate-600 dark:text-slate-300">${l.masked_phone}</span>
            </td>
            <td data-label="Requirement">
              <div class="text-xs font-medium text-slate-800 dark:text-slate-200">${l.preferred_location || 'Nagpur'}</div>
              <div class="text-[11px] text-slate-400">${l.bhk || ''} ${l.property_type || 'Residential'}</div>
            </td>
            <td data-label="Budget">
              <span class="text-xs font-bold text-emerald-600 dark:text-emerald-400">${l.budget_display}</span>
            </td>
            <td data-label="Temperature">${tempBadge}</td>
            <td data-label="Stage">
              <span class="crm-badge crm-badge-stage">${l.stage.replace('_', ' ')}</span>
            </td>
            <td data-label="Actions" class="text-right whitespace-nowrap">
              <div class="flex items-center justify-end gap-1.5">
                <button onclick="App.initiateCall('${l.phone_number}', '${l.name}', '${l.id}')" class="crm-btn crm-btn-success crm-btn-sm text-xs py-1 px-2.5 shadow-sm" title="Initiate AI Voice Call">
                  <i data-lucide="phone" class="w-3.5 h-3.5"></i>
                  Call
                </button>
                <button onclick="App.openLeadDrawer('${l.id}')" class="crm-btn crm-btn-secondary crm-btn-sm text-xs py-1 px-2.5" title="View Lead Details">
                  Details
                </button>
              </div>
            </td>
          </tr>
        `;
      }).join('');

      this.refreshIcons();
    } catch (err) {
      console.error('Fetch leads error:', err);
      if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="text-center text-red-500 py-6">Failed to load leads.</td></tr>`;
    }
  },

  setLeadQuickFilter(type) {
    const stageFilter = document.getElementById('lead-stage-filter');
    const tempFilter = document.getElementById('lead-temp-filter');

    ['all', 'hot', 'warm', 'site_visit', 'qualified'].forEach(key => {
      const chip = document.getElementById(`chip-filter-${key}`);
      if (chip) {
        if (key === type) {
          chip.className = 'chip-btn px-3 py-1 rounded-full font-medium border border-indigo-500 bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300';
        } else {
          chip.className = 'chip-btn px-3 py-1 rounded-full font-medium border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800';
        }
      }
    });

    if (type === 'all') {
      if (stageFilter) stageFilter.value = 'all';
      if (tempFilter) tempFilter.value = 'all';
    } else if (type === 'hot' || type === 'warm') {
      if (tempFilter) tempFilter.value = type;
      if (stageFilter) stageFilter.value = 'all';
    } else {
      if (stageFilter) stageFilter.value = type;
      if (tempFilter) tempFilter.value = 'all';
    }

    this.fetchLeads();
  },

  toggleSelectAllLeads(masterCheckbox) {
    if (masterCheckbox.checked) {
      AppState.selectedLeads.clear();
      AppState.leads.slice(0, 3).forEach(l => AppState.selectedLeads.add(l.id));
      if (AppState.leads.length > 3) {
        this.showToast('info', 'Limited to 3 leads for concurrent batch testing. First 3 selected.');
      }
    } else {
      AppState.selectedLeads.clear();
    }
    this.updateBulkActionBar();
    this.fetchLeads();
  },

  toggleLeadSelection(leadId) {
    if (AppState.selectedLeads.has(leadId)) {
      AppState.selectedLeads.delete(leadId);
    } else {
      if (AppState.selectedLeads.size >= 3) {
        this.showToast('warning', 'Maximum 3 leads can be tested concurrently right now.');
        return;
      }
      AppState.selectedLeads.add(leadId);
    }
    this.updateBulkActionBar();
  },

  clearLeadSelection() {
    AppState.selectedLeads.clear();
    const master = document.getElementById('leads-select-all');
    if (master) master.checked = false;
    this.updateBulkActionBar();
    this.fetchLeads();
  },

  updateBulkActionBar() {
    const bar = document.getElementById('leads-bulk-bar');
    const countEl = document.getElementById('bulk-selected-count');
    const count = AppState.selectedLeads.size;

    if (count > 0) {
      if (bar) bar.classList.remove('hidden');
      if (countEl) countEl.innerText = count;
    } else {
      if (bar) bar.classList.add('hidden');
    }
  },

  async callSelectedLeads() {
    const count = AppState.selectedLeads.size;
    if (count === 0) {
      this.showToast('warning', 'Please select up to 3 leads first.');
      return;
    }
    if (count > 3) {
      this.showToast('warning', 'Maximum 3 leads can be tested concurrently right now.');
      return;
    }

    const leadIds = Array.from(AppState.selectedLeads);
    try {
      this.showToast('info', `Creating 3-lead batch calling campaign...`);

      // 1. Create campaign
      const createRes = await this.authFetch('/api/campaigns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: '3 Lead Concurrency Test',
          lead_ids: leadIds,
          concurrency: Math.min(count, 3),
        }),
      });

      if (!createRes.ok) {
        const err = await createRes.json();
        throw new Error(err.detail || 'Failed to create campaign');
      }

      const cmpData = await createRes.json();
      const campaignId = cmpData.campaign_id;

      // 2. Start campaign asynchronously
      const startRes = await this.authFetch(`/api/campaigns/${campaignId}/start`, {
        method: 'POST',
      });
      if (!startRes.ok) {
        const err = await startRes.json();
        throw new Error(err.detail || 'Failed to start campaign');
      }

      this.showToast('success', `Campaign started! Launching ${count} concurrent AI calls...`);
      this.clearLeadSelection();

      // 3. Open Live Campaign Monitor Panel
      this.openLiveCampaignMonitor(campaignId);

    } catch (err) {
      this.showToast('error', 'Batch Calling error: ' + err.message);
    }
  },

  // ---------------------------------------------------------------------------
  // 4B. Live Campaign Monitor Panel (3-Concurrent Real Calling Smoke Test)
  // ---------------------------------------------------------------------------
  openLiveCampaignMonitor(campaignId) {
    AppState.activeMonitorCampaignId = campaignId;
    const panel = document.getElementById('live-campaign-panel');
    if (panel) panel.classList.remove('hidden');

    this.pollLiveCampaignMonitor();
    clearInterval(AppState.liveCampaignMonitorInterval);
    AppState.liveCampaignMonitorInterval = setInterval(() => {
      this.pollLiveCampaignMonitor();
    }, 1500);
  },

  async pollLiveCampaignMonitor() {
    const campaignId = AppState.activeMonitorCampaignId;
    if (!campaignId) return;

    try {
      const res = await this.authFetch(`/api/campaigns/${campaignId}`);
      if (!res.ok) return;
      const data = await res.json();

      const nameEl = document.getElementById('live-cmp-name');
      const statusEl = document.getElementById('live-cmp-status');
      const linesEl = document.getElementById('live-cmp-lines');
      const activeMeterEl = document.getElementById('live-cmp-active-meter');
      const peakEl = document.getElementById('live-cmp-peak');
      const summaryEl = document.getElementById('live-cmp-summary-text');
      const listEl = document.getElementById('live-cmp-leads-list');
      const pingDot = document.getElementById('live-cmp-ping-dot');

      if (nameEl) nameEl.innerText = data.name || '3 Lead Concurrency Test';
      if (statusEl) {
        statusEl.innerText = (data.status || 'running').toUpperCase();
        statusEl.className = data.status === 'running'
          ? 'uppercase font-bold text-emerald-400'
          : data.status === 'completed'
          ? 'uppercase font-bold text-indigo-300'
          : 'uppercase font-bold text-amber-400';
      }

      if (pingDot) {
        pingDot.className = data.status === 'running'
          ? 'w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse'
          : 'w-2.5 h-2.5 rounded-full bg-slate-400';
      }

      const active = data.active_calls || 0;
      const conc = data.concurrency || 3;
      const peak = data.max_observed_active_calls || 0;
      if (linesEl) linesEl.innerText = `${active} / ${conc}`;
      if (activeMeterEl) activeMeterEl.innerText = `${active} / ${conc}`;
      if (peakEl) peakEl.innerText = peak;

      const completed = data.completed_leads || 0;
      const failed = data.failed_leads || 0;
      const dropped = data.ended_in_middle_leads || 0;
      const total = data.total_leads || (data.leads ? data.leads.length : 0);
      if (summaryEl) summaryEl.innerText = `${total} total • ${completed} completed • ${dropped ? `${dropped} dropped • ` : ''}${failed} failed`;

      if (listEl && data.leads) {
        listEl.innerHTML = data.leads.map(l => {
          let statusBadge = '';
          const s = (l.campaign_status || 'queued').toLowerCase();
          const dur = l.call_duration_seconds ? `${l.call_duration_seconds}s` : '';
          
          if (s === 'active' || s === 'dialing' || s === 'in_progress') {
            statusBadge = `<span class="crm-badge crm-badge-hot animate-pulse text-[10px] font-bold">● IN CALL ${dur ? `(${dur})` : ''}</span>`;
          } else if (s === 'completed') {
            statusBadge = `<span class="crm-badge crm-badge-success text-[10px] font-bold">✓ COMPLETED ${dur ? `(${dur})` : ''}</span>`;
          } else if (s === 'ended_in_middle') {
            statusBadge = `<span class="crm-badge crm-badge-warm text-[10px] font-bold">⚠️ DROPPED ${dur ? `(${dur})` : ''}</span>`;
          } else if (s === 'failed' || s === 'no_answer') {
            statusBadge = `<span class="crm-badge crm-badge-cold text-[10px] font-bold">✕ UNREACHABLE</span>`;
          } else if (s === 'cancelled') {
            statusBadge = `<span class="crm-badge crm-badge-cold text-[10px] font-bold">CANCELLED</span>`;
          } else {
            statusBadge = `<span class="crm-badge crm-badge-stage text-[10px]">READY</span>`;
          }

          const transcriptBtn = l.last_call_id
            ? `<button onclick="App.openCallDetail('${l.last_call_id}')" class="text-[10px] font-bold text-indigo-500 hover:text-indigo-700 underline flex items-center gap-0.5">
                 <i data-lucide="file-text" class="w-3 h-3"></i> Transcript
               </button>`
            : '';

          return `
            <div class="p-2.5 rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 flex items-center justify-between shadow-sm">
              <div class="leading-tight">
                <div class="font-bold text-xs text-slate-900 dark:text-white">${l.name}</div>
                <div class="font-mono text-[10px] text-slate-500">${l.masked_phone} ${l.last_call_outcome ? `• ${l.last_call_outcome.replace(/_/g, ' ')}` : ''}</div>
              </div>
              <div class="flex items-center gap-1.5">
                ${statusBadge}
                ${transcriptBtn}
              </div>
            </div>
          `;
        }).join('');
      }

      const stopBtn = document.getElementById('live-cmp-stop-btn');
      if (['completed', 'stopped', 'failed'].includes(data.status)) {
        clearInterval(AppState.liveCampaignMonitorInterval);
        if (stopBtn) {
          stopBtn.className = 'crm-btn crm-btn-primary crm-btn-sm text-xs py-1 px-2.5';
          stopBtn.innerHTML = '<i data-lucide="rotate-ccw" class="w-3 h-3"></i> Restart';
          stopBtn.onclick = () => this.restartCampaignFromMonitor(campaignId);
        }
        this.fetchCampaigns();
        this.fetchCalls();
      } else {
        if (stopBtn) {
          stopBtn.className = 'crm-btn crm-btn-danger crm-btn-sm text-xs py-1 px-2.5';
          stopBtn.innerHTML = '<i data-lucide="square" class="w-3 h-3"></i> Stop';
          stopBtn.onclick = () => this.stopActiveCampaignFromMonitor();
        }
      }

      this.refreshIcons();
    } catch (err) {
      console.warn('Live campaign poll error:', err);
    }
  },

  async stopActiveCampaignFromMonitor() {
    const campaignId = AppState.activeMonitorCampaignId;
    if (!campaignId) return;
    try {
      await this.authFetch(`/api/campaigns/${campaignId}/stop`, { method: 'POST' });
      this.showToast('info', 'Campaign stopped. Queued leads cancelled.');
      this.pollLiveCampaignMonitor();
    } catch (err) {
      this.showToast('error', 'Stop campaign error: ' + err.message);
    }
  },

  async restartCampaignFromMonitor(campaignId) {
    if (!campaignId) return;
    try {
      this.showToast('info', 'Restarting campaign...');
      const res = await this.authFetch(`/api/campaigns/${campaignId}/restart`, { method: 'POST' });
      if (!res.ok) throw new Error('Restart failed');
      this.showToast('success', 'Campaign restarted! Dialing all leads...');
      this.openLiveCampaignMonitor(campaignId);
      this.fetchCampaigns();
    } catch (err) {
      this.showToast('error', 'Restart error: ' + err.message);
    }
  },

  closeLiveCampaignMonitor() {
    clearInterval(AppState.liveCampaignMonitorInterval);
    AppState.activeMonitorCampaignId = null;
    const panel = document.getElementById('live-campaign-panel');
    if (panel) panel.classList.add('hidden');
  },

  // ---------------------------------------------------------------------------
  // Lead Detail Drawer
  // ---------------------------------------------------------------------------
  async openLeadDrawer(leadId) {
    try {
      const res = await this.authFetch(`/api/leads/${leadId}`);
      const lead = await res.json();
      AppState.currentLeadInDrawer = lead;

      document.getElementById('drawer-lead-name').innerText = lead.name;
      document.getElementById('drawer-lead-phone').innerText = lead.phone_number;
      document.getElementById('drawer-lead-loc').innerText = lead.preferred_location || 'Nagpur';
      document.getElementById('drawer-lead-bhk').innerText = `${lead.bhk || ''} ${lead.property_type || ''}`;
      document.getElementById('drawer-lead-budget').innerText = lead.budget_display;
      document.getElementById('drawer-lead-stage').innerText = lead.stage;

      const notesContainer = document.getElementById('drawer-notes-list');
      if (notesContainer) {
        if (!lead.lead_notes || !lead.lead_notes.length) {
          notesContainer.innerHTML = `<div class="text-slate-400 text-xs py-2">No notes added yet.</div>`;
        } else {
          notesContainer.innerHTML = lead.lead_notes.map(n => `
            <div class="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-xs">
              <div class="flex items-center justify-between text-[10px] text-slate-400 mb-1">
                <span class="font-semibold text-slate-600 dark:text-slate-300">${n.author}</span>
                <span>${this.formatDate(n.created_at)}</span>
              </div>
              <div class="text-slate-800 dark:text-slate-200">${n.note}</div>
            </div>
          `).join('');
        }
      }

      document.getElementById('drawer-lead-backdrop')?.classList.add('active');
      document.getElementById('drawer-lead')?.classList.add('active');
      this.refreshIcons();
    } catch (err) {
      this.showToast('error', 'Failed to load lead profile: ' + err.message);
    }
  },

  closeLeadDrawer() {
    document.getElementById('drawer-lead-backdrop')?.classList.remove('active');
    document.getElementById('drawer-lead')?.classList.remove('active');
  },

  callLeadFromDrawer() {
    if (!AppState.currentLeadInDrawer) return;
    const lead = AppState.currentLeadInDrawer;
    this.closeLeadDrawer();
    this.initiateCall(lead.phone_number, lead.name, lead.id);
  },

  async saveLeadNote() {
    if (!AppState.currentLeadInDrawer) return;
    const input = document.getElementById('drawer-new-note');
    const note = input?.value.trim();
    if (!note) return;

    try {
      await this.authFetch(`/api/leads/${AppState.currentLeadInDrawer.id}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note, author_name: AppState.currentUser?.name || 'Priya' })
      });
      input.value = '';
      this.showToast('success', 'Note saved to lead profile.');
      this.openLeadDrawer(AppState.currentLeadInDrawer.id);
    } catch (err) {
      this.showToast('error', 'Failed to save note: ' + err.message);
    }
  },

  openNewLeadModal() {
    this.openModal('modal-new-lead');
  },

  async handleCreateLeadSubmit(event) {
    if (event) event.preventDefault();
    const payload = {
      name: document.getElementById('form-lead-name')?.value.trim(),
      phone_number: document.getElementById('form-lead-phone')?.value.trim(),
      preferred_location: document.getElementById('form-lead-loc')?.value,
      property_type: 'Flat',
      bhk: document.getElementById('form-lead-bhk')?.value,
      budget_max: parseFloat(document.getElementById('form-lead-budget')?.value) || 6000000,
      lead_temperature: document.getElementById('form-lead-temp')?.value,
      stage: 'new'
    };

    try {
      const res = await this.authFetch('/api/leads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(await res.text());

      this.closeModal('modal-new-lead');
      this.showToast('success', `Lead ${payload.name} created successfully!`);
      this.fetchLeads();
      this.loadDashboardData();
    } catch (err) {
      this.showToast('error', 'Failed to create lead: ' + err.message);
    }
  },

  triggerCsvImportModal() {
    this.openModal('modal-csv-import');
  },

  async handleCsvFile(event) {
    const file = event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      this.showToast('info', 'Parsing and validating CSV leads...');
      const res = await this.authFetch('/api/leads/import', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      this.closeModal('modal-csv-import');
      this.showToast('success', `Import Complete: ${data.imported} leads added, ${data.skipped} skipped.`);
      this.fetchLeads();
      this.loadDashboardData();
    } catch (err) {
      this.showToast('error', 'CSV Import failed: ' + err.message);
    }
  },

  // ---------------------------------------------------------------------------
  // 3. Campaigns & Batch Dialing Controller
  // ---------------------------------------------------------------------------
  async fetchCampaigns() {
    const container = document.getElementById('campaigns-grid-container');
    if (container) {
      container.innerHTML = `<div class="col-span-3 text-center text-slate-400 py-10">Loading campaigns...</div>`;
    }

    try {
      const res = await this.authFetch('/api/campaigns');
      const campaigns = await res.json();
      AppState.campaigns = campaigns || [];

      if (!campaigns || !campaigns.length) {
        if (container) {
          container.innerHTML = `
            <div class="col-span-3 text-center p-12 bg-white dark:bg-slate-900 rounded-2xl border border-dashed border-slate-300 dark:border-slate-800">
              <div class="w-12 h-12 rounded-full bg-indigo-50 dark:bg-slate-800 text-indigo-600 flex items-center justify-center mx-auto mb-3">
                <i data-lucide="megaphone" class="w-6 h-6"></i>
              </div>
              <h3 class="font-bold text-sm text-slate-900 dark:text-white">No Calling Campaigns Yet</h3>
              <p class="text-xs text-slate-500 mt-1 max-w-sm mx-auto">Create a targeted batch campaign, configure leads from your pipeline or CSV, and launch AI dialing.</p>
              <button onclick="App.openNewCampaignModal()" class="crm-btn crm-btn-primary crm-btn-sm mt-4">
                + Create First Campaign
              </button>
            </div>
          `;
        }
        this.refreshIcons();
        return;
      }

      if (container) {
        container.innerHTML = campaigns.map(c => {
          const total = c.total_leads || 0;
          const completed = c.completed_leads || 0;
          const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
          
          const statusBadge = c.status === 'running'
            ? `<span class="crm-badge crm-badge-hot animate-pulse">● Running</span>`
            : c.status === 'paused'
            ? `<span class="crm-badge crm-badge-warm">⏸ Paused</span>`
            : c.status === 'completed'
            ? `<span class="crm-badge crm-badge-success">✓ Completed</span>`
            : `<span class="crm-badge crm-badge-stage">● Ready</span>`;

          const goalLabel = {
            site_visit_booking: 'Site Visit Booking',
            qualification: 'Lead Qualification',
            follow_up: 'Follow-up Reminder',
            property_intro: 'New Launch Promo'
          }[c.goal] || c.goal;

          return `
            <div class="crm-card p-5 flex flex-col justify-between hover:border-indigo-300 dark:hover:border-indigo-700 transition-all">
              <div>
                <div class="flex items-center justify-between gap-2 mb-2.5">
                  ${statusBadge}
                  <span class="text-[11px] font-mono text-slate-400">⚡ ${c.concurrency} lines</span>
                </div>

                <div class="flex items-center gap-1.5 mb-1.5">
                  <span class="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950/80 text-indigo-700 dark:text-indigo-300">${goalLabel}</span>
                  ${c.target_locality ? `<span class="text-[10px] font-medium px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">${c.target_locality}</span>` : ''}
                </div>

                <h3 class="font-bold text-base text-slate-900 dark:text-white leading-snug">${c.name}</h3>
                <p class="text-xs text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">${c.description || 'Targeted AI outbound dialing campaign'}</p>

                <!-- Progress Bar -->
                <div class="mt-4 space-y-1">
                  <div class="flex justify-between text-[11px] text-slate-500 font-medium">
                    <span>Progress (${completed}/${total})</span>
                    <span>${pct}%</span>
                  </div>
                  <div class="h-2 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                    <div class="h-full bg-indigo-600 rounded-full transition-all duration-300" style="width: ${pct}%"></div>
                  </div>
                </div>

                <!-- Counts Pills -->
                <div class="grid grid-cols-3 gap-1.5 mt-3 pt-3 border-t border-slate-100 dark:border-slate-800 text-center text-[10px]">
                  <div class="p-1 rounded bg-slate-50 dark:bg-slate-900 text-slate-600 dark:text-slate-400">
                    <div class="font-bold text-slate-900 dark:text-white">${c.ready_leads || 0}</div>
                    <div>Ready</div>
                  </div>
                  <div class="p-1 rounded bg-slate-50 dark:bg-slate-900 text-slate-600 dark:text-slate-400">
                    <div class="font-bold text-indigo-600 dark:text-indigo-400">${c.calling_leads || 0}</div>
                    <div>Dialing</div>
                  </div>
                  <div class="p-1 rounded bg-slate-50 dark:bg-slate-900 text-slate-600 dark:text-slate-400">
                    <div class="font-bold text-emerald-600 dark:text-emerald-400">${c.completed_leads || 0}</div>
                    <div>Done</div>
                  </div>
                </div>
              </div>

              <!-- Card Actions -->
              <div class="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between gap-2">
                <button onclick="App.openCampaignDetail('${c.id}')" class="crm-btn crm-btn-secondary crm-btn-sm text-xs py-1.5 px-3 flex-1">
                  <i data-lucide="users" class="w-3.5 h-3.5"></i>
                  <span>Manage Leads (${total})</span>
                </button>
                <button onclick="App.quickToggleCampaign('${c.id}', '${c.status}')" class="crm-btn ${c.status === 'running' ? 'crm-btn-secondary' : 'crm-btn-primary'} crm-btn-sm text-xs py-1.5 px-3">
                  <i data-lucide="${c.status === 'running' ? 'pause' : (c.status === 'completed' || c.status === 'stopped' ? 'rotate-ccw' : 'play')}" class="w-3.5 h-3.5"></i>
                  <span>${c.status === 'running' ? 'Pause' : (c.status === 'completed' || c.status === 'stopped' ? 'Restart' : 'Start')}</span>
                </button>
                <button onclick="App.deleteCampaign('${c.id}', '${(c.name || 'Campaign').replace(/'/g, "\\'")}')" class="crm-btn crm-btn-ghost crm-btn-sm text-xs text-slate-400 hover:text-red-500 p-1.5" title="Delete Campaign">
                  <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                </button>
              </div>
            </div>
          `;
        }).join('');
      }
      this.refreshIcons();
    } catch (err) {
      console.error('Fetch campaigns error:', err);
    }
  },

  openNewCampaignModal() {
    AppState.newCampaignSelectedLeads.clear();
    AppState.customNewCampaignLeads = [];

    const nameInput = document.getElementById('cmp-form-name');
    if (nameInput) nameInput.value = '';
    const descInput = document.getElementById('cmp-form-desc');
    if (descInput) descInput.value = '';
    const customName = document.getElementById('cmp-custom-name');
    if (customName) customName.value = '';
    const customPhone = document.getElementById('cmp-custom-phone');
    if (customPhone) customPhone.value = '';
    const customLoc = document.getElementById('cmp-custom-loc');
    if (customLoc) customLoc.value = '';

    const concSelect = document.getElementById('cmp-form-concurrency');
    if (concSelect) concSelect.value = '3';

    const startCheck = document.getElementById('cmp-form-start-immediate');
    if (startCheck) startCheck.checked = true;

    this.switchNewCampaignLeadTab('custom');
    this.renderNewCampaignStagedLeads();
    this.filterNewCampaignLeadsPicker();
    this.openModal('modal-new-campaign');
    this.refreshIcons();
  },

  switchNewCampaignLeadTab(tab) {
    const tabCustom = document.getElementById('tab-new-campaign-custom');
    const tabPipeline = document.getElementById('tab-new-campaign-pipeline');
    const btnCustom = document.getElementById('btn-tab-custom-lead');
    const btnPipeline = document.getElementById('btn-tab-pipeline-lead');

    if (tab === 'custom') {
      tabCustom?.classList.remove('hidden');
      tabPipeline?.classList.add('hidden');
      btnCustom?.classList.add('bg-indigo-600', 'text-white');
      btnCustom?.classList.remove('bg-slate-200', 'dark:bg-slate-800', 'text-slate-700', 'dark:text-slate-300');
      btnPipeline?.classList.remove('bg-indigo-600', 'text-white');
      btnPipeline?.classList.add('bg-slate-200', 'dark:bg-slate-800', 'text-slate-700', 'dark:text-slate-300');
    } else {
      tabCustom?.classList.add('hidden');
      tabPipeline?.classList.remove('hidden');
      btnPipeline?.classList.add('bg-indigo-600', 'text-white');
      btnPipeline?.classList.remove('bg-slate-200', 'dark:bg-slate-800', 'text-slate-700', 'dark:text-slate-300');
      btnCustom?.classList.remove('bg-indigo-600', 'text-white');
      btnCustom?.classList.add('bg-slate-200', 'dark:bg-slate-800', 'text-slate-700', 'dark:text-slate-300');
      this.filterNewCampaignLeadsPicker();
    }
    this.refreshIcons();
  },

  addCustomLeadToNewCampaign() {
    const nameEl = document.getElementById('cmp-custom-name');
    const phoneEl = document.getElementById('cmp-custom-phone');
    const locEl = document.getElementById('cmp-custom-loc');

    const name = nameEl?.value.trim();
    const phone = phoneEl?.value.trim();
    const loc = locEl?.value.trim() || 'Nagpur';

    if (!name) {
      this.showToast('warning', 'Please enter a customer name.');
      nameEl?.focus();
      return;
    }
    if (!phone || phone.length < 7) {
      this.showToast('warning', 'Please enter a valid phone number (e.g. +919823012345).');
      phoneEl?.focus();
      return;
    }

    const currentTotal = AppState.newCampaignSelectedLeads.size + (AppState.customNewCampaignLeads?.length || 0);
    if (currentTotal >= 3) {
      this.showToast('warning', 'Maximum 3 leads can be tested concurrently right now.');
      return;
    }

    AppState.customNewCampaignLeads = AppState.customNewCampaignLeads || [];
    AppState.customNewCampaignLeads.push({
      name,
      phone_number: phone,
      preferred_location: loc
    });

    if (nameEl) nameEl.value = '';
    if (phoneEl) phoneEl.value = '';
    if (locEl) locEl.value = '';

    this.showToast('success', `Added "${name}" (${phone}) to calling list.`);
    this.renderNewCampaignStagedLeads();
  },

  removeCustomLeadFromNewCampaign(index) {
    if (AppState.customNewCampaignLeads && AppState.customNewCampaignLeads[index]) {
      AppState.customNewCampaignLeads.splice(index, 1);
      this.renderNewCampaignStagedLeads();
    }
  },

  toggleNewCampaignLead(leadId) {
    const isSelected = AppState.newCampaignSelectedLeads.has(leadId);
    if (!isSelected) {
      const currentTotal = AppState.newCampaignSelectedLeads.size + (AppState.customNewCampaignLeads?.length || 0);
      if (currentTotal >= 3) {
        this.showToast('warning', 'Maximum 3 leads can be tested concurrently right now.');
        this.filterNewCampaignLeadsPicker();
        return;
      }
      AppState.newCampaignSelectedLeads.add(leadId);
    } else {
      AppState.newCampaignSelectedLeads.delete(leadId);
    }
    this.renderNewCampaignStagedLeads();
    this.filterNewCampaignLeadsPicker();
  },

  renderNewCampaignStagedLeads() {
    const totalCount = AppState.newCampaignSelectedLeads.size + (AppState.customNewCampaignLeads?.length || 0);
    const countEl = document.getElementById('cmp-form-selected-count');
    if (countEl) countEl.innerText = totalCount;

    const container = document.getElementById('cmp-staged-leads-container');
    if (!container) return;

    if (totalCount === 0) {
      container.innerHTML = `
        <div class="text-xs text-slate-400 text-center py-2 italic bg-white dark:bg-slate-950 rounded-lg border border-dashed border-slate-200 dark:border-slate-800">
          No leads added yet. Type a phone number below or pick from your pipeline.
        </div>
      `;
      return;
    }

    let html = '';

    // Render custom leads
    (AppState.customNewCampaignLeads || []).forEach((cl, idx) => {
      html += `
        <div class="p-2 rounded-lg bg-white dark:bg-slate-950 border border-indigo-200 dark:border-indigo-900 flex items-center justify-between shadow-xs">
          <div class="flex items-center gap-2 min-w-0">
            <span class="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0"></span>
            <div class="leading-tight truncate">
              <span class="font-bold text-xs text-slate-900 dark:text-white">${cl.name}</span>
              <span class="text-[11px] font-mono text-indigo-600 dark:text-indigo-400 ml-1.5">${cl.phone_number}</span>
              <span class="text-[10px] text-slate-400 ml-1">(${cl.preferred_location || 'Nagpur'})</span>
            </div>
          </div>
          <button type="button" onclick="App.removeCustomLeadFromNewCampaign(${idx})" class="text-slate-400 hover:text-red-500 p-1" title="Remove">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      `;
    });

    // Render pipeline leads
    Array.from(AppState.newCampaignSelectedLeads).forEach(lid => {
      const lead = (AppState.leads || []).find(l => l.id === lid);
      if (lead) {
        html += `
          <div class="p-2 rounded-lg bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 flex items-center justify-between shadow-xs">
            <div class="flex items-center gap-2 min-w-0">
              <span class="w-2 h-2 rounded-full bg-indigo-500 flex-shrink-0"></span>
              <div class="leading-tight truncate">
                <span class="font-bold text-xs text-slate-900 dark:text-white">${lead.name}</span>
                <span class="text-[11px] font-mono text-slate-500 ml-1.5">${lead.phone_number}</span>
                <span class="text-[10px] text-slate-400 ml-1">(${lead.preferred_location || 'Nagpur'})</span>
              </div>
            </div>
            <button type="button" onclick="App.toggleNewCampaignLead('${lead.id}')" class="text-slate-400 hover:text-red-500 p-1" title="Remove">
              <i data-lucide="x" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        `;
      }
    });

    container.innerHTML = html;
    this.refreshIcons();
  },

  filterNewCampaignLeadsPicker() {
    const q = document.getElementById('cmp-form-lead-search')?.value.toLowerCase().trim() || '';
    const container = document.getElementById('cmp-form-leads-picker-container');
    if (!container) return;

    const filtered = AppState.leads.filter(l => 
      !q || l.name.toLowerCase().includes(q) || l.phone_number.includes(q) || (l.preferred_location || '').toLowerCase().includes(q)
    );

    if (!filtered.length) {
      container.innerHTML = `<div class="text-slate-400 text-center py-4">No matching leads.</div>`;
      return;
    }

    container.innerHTML = filtered.map(l => {
      const isChecked = AppState.newCampaignSelectedLeads.has(l.id);
      return `
        <label class="flex items-center justify-between p-2 rounded-lg bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 cursor-pointer hover:bg-indigo-50/40 dark:hover:bg-indigo-950/20">
          <div class="flex items-center gap-2.5">
            <input type="checkbox" onchange="App.toggleNewCampaignLead('${l.id}')" ${isChecked ? 'checked' : ''} class="rounded text-indigo-600">
            <div>
              <div class="font-bold text-xs text-slate-900 dark:text-white">${l.name} (${l.phone_number})</div>
              <div class="text-[10px] text-slate-400">${l.preferred_location || 'Nagpur'} • ${l.bhk || ''} • ${l.budget_display}</div>
            </div>
          </div>
          <span class="crm-badge crm-badge-${l.lead_temperature || 'warm'} text-[10px]">${l.lead_temperature || 'warm'}</span>
        </label>
      `;
    }).join('');
    this.refreshIcons();
  },

  async handleCreateCampaignSubmit(event, startImmediately = null) {
    if (event) event.preventDefault();

    const name = document.getElementById('cmp-form-name')?.value.trim() || 'Custom Outbound Campaign';
    const locality = document.getElementById('cmp-form-loc')?.value || 'All Localities';
    const goal = document.getElementById('cmp-form-goal')?.value || 'site_visit_booking';
    const concurrency = Math.min(parseInt(document.getElementById('cmp-form-concurrency')?.value) || 3, 3);
    const desc = document.getElementById('cmp-form-desc')?.value.trim();

    if (startImmediately === null) {
      startImmediately = document.getElementById('cmp-form-start-immediate')?.checked ?? true;
    }

    const leadIds = Array.from(AppState.newCampaignSelectedLeads);
    const newLeads = [...(AppState.customNewCampaignLeads || [])];

    // Auto-commit any lead currently typed in the custom lead input fields
    const customPhoneInput = document.getElementById('cmp-form-custom-phone');
    const customNameInput = document.getElementById('cmp-form-custom-name');
    const customLocInput = document.getElementById('cmp-form-custom-loc');
    const pendingPhone = customPhoneInput?.value.trim();
    if (pendingPhone) {
      const pendingName = customNameInput?.value.trim() || 'Customer';
      const pendingLoc = customLocInput?.value.trim() || locality;
      if (!newLeads.some(nl => nl.phone_number === pendingPhone)) {
        newLeads.push({
          name: pendingName,
          phone_number: pendingPhone,
          preferred_location: pendingLoc
        });
      }
      if (customPhoneInput) customPhoneInput.value = '';
      if (customNameInput) customNameInput.value = '';
      if (customLocInput) customLocInput.value = '';
    }

    const totalLeads = leadIds.length + newLeads.length;

    if (totalLeads === 0) {
      this.showToast('warning', 'Please add at least 1 lead to call in this campaign.');
      return;
    }
    if (totalLeads > 3) {
      this.showToast('warning', 'Maximum 3 leads can be tested concurrently right now.');
      return;
    }

    const payload = {
      name,
      target_locality: locality,
      goal,
      concurrency: Math.min(concurrency, totalLeads),
      description: desc,
      lead_ids: leadIds,
      new_leads: newLeads,
      start_immediately: startImmediately
    };

    try {
      this.showToast('info', 'Creating campaign...');
      const res = await this.authFetch('/api/campaigns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to create campaign');

      this.closeModal('modal-new-campaign');
      await this.fetchCampaigns();

      if (startImmediately) {
        this.showToast('success', `Campaign "${name}" started! Launching ${totalLeads} concurrent calls...`);
        this.openLiveCampaignMonitor(data.campaign_id);
      } else {
        this.showToast('success', `Campaign "${name}" saved as draft.`);
        this.openCampaignDetail(data.campaign_id);
      }
    } catch (err) {
      this.showToast('error', 'Create Campaign error: ' + err.message);
    }
  },

  async openCampaignDetail(campaignId) {
    AppState.activeCampaignId = campaignId;
    try {
      const res = await this.authFetch(`/api/campaigns/${campaignId}`);
      if (!res.ok) throw new Error('Campaign details not found');
      const data = await res.json();
      AppState.activeCampaignData = data;

      // Switch views
      document.getElementById('campaigns-list-container')?.classList.add('hidden');
      document.getElementById('campaign-detail-container')?.classList.remove('hidden');

      // Populate hero
      document.getElementById('cmp-detail-title').innerText = data.name;
      document.getElementById('cmp-detail-desc').innerText = data.description || 'Targeted AI outbound dialing campaign';
      document.getElementById('cmp-detail-loc-tag').innerText = data.target_locality || 'All Localities';
      document.getElementById('cmp-detail-goal-tag').innerText = (data.goal || 'site_visit_booking').replace('_', ' ');
      document.getElementById('cmp-detail-concurrency-pill').innerText = `⚡ ${data.concurrency} Concurrent Lines`;

      const statusPill = document.getElementById('cmp-detail-status-pill');
      if (statusPill) {
        statusPill.className = data.status === 'running'
          ? 'crm-badge crm-badge-hot animate-pulse'
          : data.status === 'paused'
          ? 'crm-badge crm-badge-warm'
          : 'crm-badge crm-badge-success';
        statusPill.innerText = `● ${data.status.toUpperCase()}`;
      }

      // Buttons
      const startBtn = document.getElementById('cmp-detail-start-btn');
      const restartBtn = document.getElementById('cmp-detail-restart-btn');
      const pauseBtn = document.getElementById('cmp-detail-pause-btn');
      const redialBtn = document.getElementById('cmp-detail-redial-btn');

      const stats = data.stats || {};
      const hasFailedOrDropped = ((stats.failed || 0) + (stats.ended_in_middle || 0)) > 0;

      if (data.status === 'running') {
        startBtn?.classList.add('hidden');
        restartBtn?.classList.add('hidden');
        pauseBtn?.classList.remove('hidden');
        redialBtn?.classList.add('hidden');
      } else if (data.status === 'completed' || data.status === 'stopped') {
        startBtn?.classList.add('hidden');
        restartBtn?.classList.remove('hidden');
        pauseBtn?.classList.add('hidden');
        if (hasFailedOrDropped) {
          redialBtn?.classList.remove('hidden');
        } else {
          redialBtn?.classList.add('hidden');
        }
      } else {
        startBtn?.classList.remove('hidden');
        restartBtn?.classList.add('hidden');
        pauseBtn?.classList.add('hidden');
        redialBtn?.classList.add('hidden');
      }

      // Stats
      document.getElementById('cmp-stat-total').innerText = stats.total || 0;
      document.getElementById('cmp-stat-ready').innerText = stats.ready || 0;
      document.getElementById('cmp-stat-calling').innerText = stats.calling || 0;
      document.getElementById('cmp-stat-completed').innerText = stats.completed || 0;
      const droppedEl = document.getElementById('cmp-stat-dropped');
      if (droppedEl) droppedEl.innerText = stats.ended_in_middle || 0;
      document.getElementById('cmp-stat-failed').innerText = stats.failed || 0;

      // Render leads table
      this.renderCampaignLeadsTable(data.leads || []);
      this.refreshIcons();

      // Start live fast polling if campaign is running or has active calls
      clearInterval(AppState.campaignPollInterval);
      if (data.status === 'running' || (stats.calling || 0) > 0) {
        AppState.campaignPollInterval = setInterval(async () => {
          if (AppState.activeCampaignId && AppState.currentView === 'campaigns') {
            try {
              const r = await this.authFetch(`/api/campaigns/${AppState.activeCampaignId}`);
              if (r.ok) {
                const refreshed = await r.json();
                AppState.activeCampaignData = refreshed;
                const rStats = refreshed.stats || {};
                document.getElementById('cmp-stat-total').innerText = rStats.total || 0;
                document.getElementById('cmp-stat-ready').innerText = rStats.ready || 0;
                document.getElementById('cmp-stat-calling').innerText = rStats.calling || 0;
                document.getElementById('cmp-stat-completed').innerText = rStats.completed || 0;
                const rDrop = document.getElementById('cmp-stat-dropped');
                if (rDrop) rDrop.innerText = rStats.ended_in_middle || 0;
                document.getElementById('cmp-stat-failed').innerText = rStats.failed || 0;

                // Update status pill if changed
                const sPill = document.getElementById('cmp-detail-status-pill');
                if (sPill) {
                  sPill.className = refreshed.status === 'running'
                    ? 'crm-badge crm-badge-hot animate-pulse'
                    : refreshed.status === 'paused'
                    ? 'crm-badge crm-badge-warm'
                    : 'crm-badge crm-badge-success';
                  sPill.innerText = `● ${refreshed.status.toUpperCase()}`;
                }

                if (refreshed.status !== 'running' && (rStats.calling || 0) === 0) {
                  clearInterval(AppState.campaignPollInterval);
                  if (startBtn) startBtn.classList.add('hidden');
                  if (restartBtn) restartBtn.classList.remove('hidden');
                  if (pauseBtn) pauseBtn.classList.add('hidden');
                  if (redialBtn) {
                    if (((rStats.failed || 0) + (rStats.ended_in_middle || 0)) > 0) {
                      redialBtn.classList.remove('hidden');
                    } else {
                      redialBtn.classList.add('hidden');
                    }
                  }
                }

                this.renderCampaignLeadsTable(refreshed.leads || []);
              }
            } catch {}
          }
        }, 1500);
      }
    } catch (err) {
      this.showToast('error', 'Failed to load campaign: ' + err.message);
    }
  },

  backToCampaignsList() {
    clearInterval(AppState.campaignPollInterval);
    AppState.activeCampaignId = null;
    AppState.activeCampaignData = null;
    document.getElementById('campaign-detail-container')?.classList.add('hidden');
    document.getElementById('campaigns-list-container')?.classList.remove('hidden');
    this.fetchCampaigns();
  },

  renderCampaignLeadsTable(leads) {
    const tbody = document.getElementById('campaign-leads-rows');
    const countEl = document.getElementById('cmp-leads-filtered-count');
    if (countEl) countEl.innerText = leads.length;

    if (!tbody) return;

    if (!leads.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center text-slate-400 py-10">No leads attached to this campaign. Click "+ Add Existing Leads" or "Import CSV" above.</td></tr>`;
      return;
    }

    tbody.innerHTML = leads.map(l => {
      const s = (l.campaign_status || 'queued').toLowerCase();
      let dialBadge = '';
      if (s === 'active' || s === 'dialing' || s === 'in_progress') {
        dialBadge = `<span class="crm-badge crm-badge-hot animate-pulse font-bold text-[11px]">● In Call</span>`;
      } else if (s === 'completed') {
        dialBadge = `<span class="crm-badge crm-badge-success font-semibold text-[11px]">✓ Completed</span>`;
      } else if (s === 'ended_in_middle') {
        dialBadge = `<span class="crm-badge crm-badge-warm font-semibold text-[11px]">⚠️ Ended in Middle</span>`;
      } else if (s === 'failed' || s === 'no_answer') {
        dialBadge = `<span class="crm-badge crm-badge-cold text-[11px]">✕ Unreachable</span>`;
      } else if (s === 'cancelled') {
        dialBadge = `<span class="crm-badge crm-badge-cold text-[11px]">Cancelled</span>`;
      } else {
        dialBadge = `<span class="crm-badge crm-badge-stage text-[11px]">Ready to Call</span>`;
      }

      // Format timing and duration
      let timeTiming = '<span class="text-slate-400 text-xs">Pending</span>';
      if (l.started_at) {
        const d = new Date(l.started_at);
        const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const durSec = l.call_duration_seconds || 0;
        const durStr = durSec > 0 ? `${Math.floor(durSec / 60)}m ${durSec % 60}s` : (s === 'active' ? 'Talking...' : '0s');
        timeTiming = `<div><strong class="text-xs text-slate-800 dark:text-slate-200">${timeStr}</strong></div><div class="text-[11px] font-mono text-indigo-600 dark:text-indigo-400 font-semibold">${durStr}</div>`;
      }

      // Format outcome
      let outcomeDisplay = l.last_call_outcome ? l.last_call_outcome.replace(/_/g, ' ') : 'Pending call';
      if (outcomeDisplay.toLowerCase().includes('site_visit_booked') || outcomeDisplay.toLowerCase().includes('site visit')) {
        outcomeDisplay = '<strong class="text-emerald-600 dark:text-emerald-400 text-xs">📅 Site Visit Booked</strong>';
      } else if (outcomeDisplay.toLowerCase().includes('ended in middle') || s === 'ended_in_middle') {
        outcomeDisplay = '<span class="text-amber-600 dark:text-amber-400 font-semibold text-xs">⚠️ Customer Hung Up Early</span>';
      } else if (outcomeDisplay.toLowerCase().includes('no answer')) {
        outcomeDisplay = '<span class="text-red-500 text-xs">No Answer / Busy</span>';
      } else if (outcomeDisplay.toLowerCase().includes('in call')) {
        outcomeDisplay = `<span class="text-indigo-600 dark:text-indigo-400 font-medium text-xs animate-pulse">${outcomeDisplay}</span>`;
      }

      const transcriptBtn = l.last_call_id
        ? `<button onclick="App.openCallDetail('${l.last_call_id}')" class="crm-btn crm-btn-secondary crm-btn-sm text-xs py-1 px-2" title="View full call transcript and latency details">
             <i data-lucide="file-text" class="w-3.5 h-3.5 text-indigo-500"></i>
             Transcript
           </button>`
        : '';

      return `
        <tr>
          <td data-label="Customer">
            <div class="flex items-center gap-2">
              <div class="w-7 h-7 rounded-full bg-indigo-50 dark:bg-slate-800 text-indigo-700 dark:text-indigo-300 font-bold text-xs flex items-center justify-center flex-shrink-0">
                ${(l.name || 'C')[0].toUpperCase()}
              </div>
              <div class="leading-tight">
                <a href="javascript:void(0)" onclick="App.openLeadDrawer('${l.lead_id}')" class="font-bold text-xs sm:text-sm text-slate-900 dark:text-white hover:text-indigo-600 transition-colors">
                  ${l.name}
                </a>
              </div>
            </div>
          </td>
          <td data-label="Phone" class="font-mono text-xs text-slate-600 dark:text-slate-300">${l.masked_phone}</td>
          <td data-label="Requirement">
            <div class="text-xs font-medium text-slate-800 dark:text-slate-200">${l.preferred_location || 'Nagpur'}</div>
            <div class="text-[11px] text-slate-400">${l.bhk || ''} ${l.property_type || ''}</div>
          </td>
          <td data-label="Dial Status">${dialBadge}</td>
          <td data-label="Call Timing">${timeTiming}</td>
          <td data-label="Outcome">${outcomeDisplay}</td>
          <td data-label="Attempts" class="text-xs font-mono text-slate-500">${l.attempts || 0}</td>
          <td data-label="Actions" class="text-right whitespace-nowrap">
            <div class="flex items-center justify-end gap-1.5">
              ${transcriptBtn}
              <button onclick="App.initiateCall('${l.phone_number}', '${l.name}', '${l.lead_id}')" class="crm-btn crm-btn-success crm-btn-sm text-xs py-1 px-2.5" title="Call this lead immediately">
                <i data-lucide="phone" class="w-3.5 h-3.5"></i>
                Call
              </button>
              <button onclick="App.removeLeadFromCampaign('${l.lead_id}')" class="crm-btn crm-btn-ghost crm-btn-sm text-xs text-red-500 hover:text-red-700 py-1 px-1.5" title="Remove from this campaign">
                <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
    this.refreshIcons();
  },

  filterCampaignLeadsTable() {
    if (!AppState.activeCampaignData || !AppState.activeCampaignData.leads) return;
    const q = document.getElementById('cmp-lead-search')?.value.toLowerCase().trim() || '';
    const status = document.getElementById('cmp-lead-status-filter')?.value || 'all';

    const filtered = AppState.activeCampaignData.leads.filter(l => {
      const matchSearch = !q || l.name.toLowerCase().includes(q) || l.phone_number.includes(q) || (l.preferred_location || '').toLowerCase().includes(q);
      const matchStatus = status === 'all' || l.campaign_status === status;
      return matchSearch && matchStatus;
    });

    this.renderCampaignLeadsTable(filtered);
  },

  async quickToggleCampaign(campaignId, currentStatus) {
    if (currentStatus === 'running') {
      await this.authFetch(`/api/campaigns/${campaignId}/pause`, { method: 'POST' });
      this.showToast('info', 'Campaign paused.');
    } else if (currentStatus === 'completed' || currentStatus === 'stopped') {
      await this.authFetch(`/api/campaigns/${campaignId}/restart`, { method: 'POST' });
      this.showToast('success', 'Campaign restarted! Calling all leads concurrently...');
      this.openLiveCampaignMonitor(campaignId);
    } else {
      await this.authFetch(`/api/campaigns/${campaignId}/start`, { method: 'POST' });
      this.showToast('success', 'Campaign started! Launching concurrent AI calls...');
      this.openLiveCampaignMonitor(campaignId);
    }
    this.fetchCampaigns();
  },

  async startActiveCampaign() {
    if (!AppState.activeCampaignId) return;
    try {
      await this.authFetch(`/api/campaigns/${AppState.activeCampaignId}/start`, { method: 'POST' });
      this.showToast('success', 'Campaign batch dialer started! Calling leads concurrently...');
      this.openCampaignDetail(AppState.activeCampaignId);
      this.openLiveCampaignMonitor(AppState.activeCampaignId);
    } catch (err) {
      this.showToast('error', 'Failed to start campaign: ' + err.message);
    }
  },

  async restartActiveCampaign() {
    if (!AppState.activeCampaignId) return;
    try {
      this.showToast('info', 'Restarting campaign...');
      const res = await this.authFetch(`/api/campaigns/${AppState.activeCampaignId}/restart`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed to restart campaign');
      this.showToast('success', 'Campaign restarted! All leads reset & dialing initiated concurrently...');
      this.openCampaignDetail(AppState.activeCampaignId);
      this.openLiveCampaignMonitor(AppState.activeCampaignId);
    } catch (err) {
      this.showToast('error', 'Restart campaign error: ' + err.message);
    }
  },

  async redialFailedLeads() {
    if (!AppState.activeCampaignId) return;
    try {
      this.showToast('info', 'Re-queueing failed & dropped leads...');
      const res = await this.authFetch(`/api/campaigns/${AppState.activeCampaignId}/redial-failed`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed to redial leads');
      this.showToast('success', 'Redialing initiated for uncompleted leads!');
      this.openCampaignDetail(AppState.activeCampaignId);
      this.openLiveCampaignMonitor(AppState.activeCampaignId);
    } catch (err) {
      this.showToast('error', 'Redial error: ' + err.message);
    }
  },

  async pauseActiveCampaign() {
    if (!AppState.activeCampaignId) return;
    try {
      await this.authFetch(`/api/campaigns/${AppState.activeCampaignId}/pause`, { method: 'POST' });
      this.showToast('info', 'Campaign batch dialer paused.');
      this.openCampaignDetail(AppState.activeCampaignId);
    } catch (err) {
      this.showToast('error', 'Failed to pause campaign: ' + err.message);
    }
  },

  async deleteCampaign(campaignId, campaignName) {
    if (!confirm(`Are you sure you want to delete campaign "${campaignName || 'this campaign'}"? This cannot be undone.`)) {
      return;
    }
    try {
      const res = await this.authFetch(`/api/campaigns/${campaignId}`, { method: 'DELETE' });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to delete campaign');
      }
      this.showToast('info', `Campaign "${campaignName || ''}" deleted.`);
      if (AppState.activeCampaignId === campaignId) {
        this.backToCampaignsList();
      } else {
        this.fetchCampaigns();
      }
    } catch (err) {
      this.showToast('error', 'Delete campaign error: ' + err.message);
    }
  },

  async deleteActiveCampaign() {
    if (!AppState.activeCampaignId) return;
    const name = AppState.activeCampaignData?.name || 'this campaign';
    await this.deleteCampaign(AppState.activeCampaignId, name);
  },

  openCampaignAddLeadsModal() {
    if (!AppState.activeCampaignData) return;
    AppState.addLeadsSelectedLeads.clear();
    const existingIds = new Set((AppState.activeCampaignData.leads || []).map(l => l.lead_id));

    // Get available leads not in campaign
    const available = AppState.leads.filter(l => !existingIds.has(l.id));
    this._availableCampaignLeads = available;

    const countEl = document.getElementById('cmp-add-selected-count');
    if (countEl) countEl.innerText = '0';
    const master = document.getElementById('cmp-add-select-all');
    if (master) master.checked = false;

    // Reset custom inputs
    const cName = document.getElementById('cmp-add-custom-name');
    if (cName) cName.value = '';
    const cPhone = document.getElementById('cmp-add-custom-phone');
    if (cPhone) cPhone.value = '';
    const cLoc = document.getElementById('cmp-add-custom-loc');
    if (cLoc) cLoc.value = '';

    this.filterCampaignAddLeadsPicker();
    this.openModal('modal-campaign-add-leads');
  },

  async addCustomLeadToActiveCampaign() {
    if (!AppState.activeCampaignId) return;
    const nameEl = document.getElementById('cmp-add-custom-name');
    const phoneEl = document.getElementById('cmp-add-custom-phone');
    const locEl = document.getElementById('cmp-add-custom-loc');

    const name = nameEl?.value.trim();
    const phone = phoneEl?.value.trim();
    const loc = locEl?.value.trim() || 'Nagpur';

    if (!name || !phone) {
      this.showToast('warning', 'Please enter both customer name and phone number.');
      return;
    }

    const startImmediately = document.getElementById('cmp-add-start-immediate')?.checked ?? true;

    try {
      const res = await this.authFetch(`/api/campaigns/${AppState.activeCampaignId}/leads`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          new_leads: [{ name, phone_number: phone, preferred_location: loc }],
          start_immediately: startImmediately
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to add lead');

      if (nameEl) nameEl.value = '';
      if (phoneEl) phoneEl.value = '';
      if (locEl) locEl.value = '';

      this.closeModal('modal-campaign-add-leads');
      this.showToast('success', `Lead "${name}" added to campaign!`);
      this.openCampaignDetail(AppState.activeCampaignId);

      if (startImmediately) {
        this.openLiveCampaignMonitor(AppState.activeCampaignId);
      }
    } catch (err) {
      this.showToast('error', 'Add custom lead error: ' + err.message);
    }
  },

  filterCampaignAddLeadsPicker() {
    const q = document.getElementById('cmp-add-leads-search')?.value.toLowerCase().trim() || '';
    const container = document.getElementById('cmp-add-leads-list-container');
    if (!container) return;

    const available = this._availableCampaignLeads || [];
    const filtered = available.filter(l => !q || l.name.toLowerCase().includes(q) || l.phone_number.includes(q) || (l.preferred_location || '').toLowerCase().includes(q));

    if (!filtered.length) {
      container.innerHTML = `<div class="text-slate-400 text-center py-6">All matching leads are already in this campaign or no matches found.</div>`;
      return;
    }

    container.innerHTML = filtered.map(l => {
      const isChecked = AppState.addLeadsSelectedLeads.has(l.id);
      return `
        <label class="flex items-center justify-between p-2 rounded-lg bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 cursor-pointer hover:bg-indigo-50/40 dark:hover:bg-indigo-950/20">
          <div class="flex items-center gap-2.5">
            <input type="checkbox" onchange="App.toggleCampaignAddLead('${l.id}')" ${isChecked ? 'checked' : ''} class="rounded text-indigo-600">
            <div>
              <div class="font-bold text-xs text-slate-900 dark:text-white">${l.name} (${l.phone_number})</div>
              <div class="text-[10px] text-slate-400">${l.preferred_location || 'Nagpur'} • ${l.bhk || ''} • ${l.budget_display}</div>
            </div>
          </div>
          <span class="crm-badge crm-badge-${l.lead_temperature || 'warm'} text-[10px]">${l.lead_temperature || 'warm'}</span>
        </label>
      `;
    }).join('');
    this.refreshIcons();
  },

  toggleCampaignAddLead(leadId) {
    if (AppState.addLeadsSelectedLeads.has(leadId)) {
      AppState.addLeadsSelectedLeads.delete(leadId);
    } else {
      AppState.addLeadsSelectedLeads.add(leadId);
    }
    const countEl = document.getElementById('cmp-add-selected-count');
    if (countEl) countEl.innerText = AppState.addLeadsSelectedLeads.size;
  },

  toggleCampaignAddAllLeads(master) {
    const available = this._availableCampaignLeads || [];
    if (master.checked) {
      available.forEach(l => AppState.addLeadsSelectedLeads.add(l.id));
    } else {
      AppState.addLeadsSelectedLeads.clear();
    }
    const countEl = document.getElementById('cmp-add-selected-count');
    if (countEl) countEl.innerText = AppState.addLeadsSelectedLeads.size;
    this.filterCampaignAddLeadsPicker();
  },

  async confirmAddLeadsToCampaign() {
    if (!AppState.activeCampaignId) return;
    const leadIds = Array.from(AppState.addLeadsSelectedLeads);
    if (!leadIds.length) {
      this.showToast('warning', 'Please select at least one lead to add.');
      return;
    }

    const startImmediately = document.getElementById('cmp-add-start-immediate')?.checked ?? true;

    try {
      const res = await this.authFetch(`/api/campaigns/${AppState.activeCampaignId}/leads`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lead_ids: leadIds,
          start_immediately: startImmediately
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to add leads');

      this.closeModal('modal-campaign-add-leads');
      this.showToast('success', `Added ${data.added_count || leadIds.length} leads to campaign!`);
      this.openCampaignDetail(AppState.activeCampaignId);

      if (startImmediately) {
        this.openLiveCampaignMonitor(AppState.activeCampaignId);
      }
    } catch (err) {
      this.showToast('error', 'Add leads error: ' + err.message);
    }
  },

  openCampaignCsvImportModal() {
    this.openModal('modal-campaign-csv-import');
  },

  async handleCampaignCsvFile(event) {
    const file = event.target.files[0];
    if (!file || !AppState.activeCampaignId) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      this.showToast('info', 'Importing and attaching CSV leads to this campaign...');
      const res = await this.authFetch(`/api/campaigns/${AppState.activeCampaignId}/import`, {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      this.closeModal('modal-campaign-csv-import');
      this.showToast('success', `Campaign Import: ${data.leads_created} created, ${data.leads_added_to_campaign} attached.`);
      this.fetchLeads();
      this.openCampaignDetail(AppState.activeCampaignId);
    } catch (err) {
      this.showToast('error', 'Campaign CSV import failed: ' + err.message);
    }
  },

  async removeLeadFromCampaign(leadId) {
    if (!AppState.activeCampaignId) return;
    try {
      await this.authFetch(`/api/campaigns/${AppState.activeCampaignId}/leads/${leadId}`, {
        method: 'DELETE'
      });
      this.showToast('info', 'Lead removed from campaign.');
      this.openCampaignDetail(AppState.activeCampaignId);
    } catch (err) {
      this.showToast('error', 'Failed to remove lead: ' + err.message);
    }
  },

  // ---------------------------------------------------------------------------
  // 4. Live AI Calling Controller
  // ---------------------------------------------------------------------------
  async initiateCall(phoneNumber, customerName = 'Customer', leadId = null) {
    if (AppState.activeCallId) {
      this.showToast('warning', 'Another AI call is currently active. Hang up first.');
      return;
    }

    const widget = document.getElementById('live-calling-widget');
    const custEl = document.getElementById('live-call-customer-name');
    const statusEl = document.getElementById('live-call-status-label');
    const feed = document.getElementById('live-transcript-feed');

    const agentName = (AppState.agentConfig && AppState.agentConfig.agent_display_name) || 'Priya';
    const companyName = (AppState.agentConfig && AppState.agentConfig.company_name) || 'Nagpur Estates';

    if (custEl) custEl.innerText = `${customerName} (${phoneNumber})`;
    if (statusEl) statusEl.innerText = 'Dialing SIP Trunk...';
    if (feed) feed.innerHTML = `<div class="text-center text-slate-400 py-4">Connecting to SIP Trunk & ${agentName} (${companyName})...</div>`;
    if (widget) widget.classList.add('active');

    try {
      const res = await this.authFetch('/api/calls', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phone_number: phoneNumber,
          customer_name: customerName,
          lead_id: leadId,
          agent_config_id: (AppState.agentConfig && AppState.agentConfig.id) || null
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Call dispatch failed');
      }

      const callInfo = await res.json();
      AppState.activeCallId = callInfo.call_id;
      this.startLiveCallPolling(callInfo.call_id);
      this.showToast('success', `Call initiated with ${customerName} (${agentName} from ${companyName})`);
    } catch (err) {
      this.showToast('error', 'Call error: ' + err.message);
      if (widget) widget.classList.remove('active');
    }
  },

  startLiveCallPolling(callId) {
    clearInterval(AppState.liveCallPollInterval);
    AppState.liveCallSeconds = 0;

    AppState.liveCallPollInterval = setInterval(async () => {
      AppState.liveCallSeconds++;
      const mm = String(Math.floor(AppState.liveCallSeconds / 60)).padStart(2, '0');
      const ss = String(AppState.liveCallSeconds % 60).padStart(2, '0');
      const timerEl = document.getElementById('live-call-timer');
      if (timerEl) timerEl.innerText = `${mm}:${ss}`;

      try {
        const res = await this.authFetch(`/api/calls/${callId}/live`);
        if (!res.ok) {
          this.stopLiveCallPolling();
          return;
        }
        const data = await res.json();

        const statusEl = document.getElementById('live-call-status-label');
        if (statusEl) {
          if (data.status === 'call_ending') {
            statusEl.innerText = 'Ending call...';
          } else {
            statusEl.innerText = `${data.status || 'in_progress'} • ${data.stage || 'Greeting'}`;
          }
        }

        if (data.turns && data.turns.length) {
          const feed = document.getElementById('live-transcript-feed');
          const currentAgentName = (AppState.agentConfig && AppState.agentConfig.agent_display_name) || 'AI Voice';
          if (feed) {
            feed.innerHTML = data.turns.map(t => `
              <div class="turn-bubble ${t.speaker}">
                <div class="text-[10px] font-bold mb-0.5 opacity-70">${t.speaker === 'assistant' ? `${currentAgentName} (AI Voice)` : 'Customer'}</div>
                <div>${t.text}</div>
              </div>
            `).join('');
            feed.scrollTop = feed.scrollHeight;
          }
        }

        const TERMINAL_STATUSES = ['completed', 'failed', 'cancelled', 'terminated', 'ended_in_middle', 'no_answer', 'busy', 'call_ended'];
        if (TERMINAL_STATUSES.includes(data.status)) {
          this.stopLiveCallPolling();
          const statusLabel = {
            'completed': 'Call completed successfully.',
            'ended_in_middle': 'Call ended mid-conversation.',
            'no_answer': 'Customer did not answer.',
            'busy': 'Line was busy.',
            'failed': 'Call failed.',
            'cancelled': 'Call was cancelled.',
            'call_ended': 'Call ended.',
          }[data.status] || `Call finished (${data.status}).`;
          this.showToast('info', statusLabel);
          return;
        }

        if (data.status === 'call_ending') {
          AppState.endingPollCounter = (AppState.endingPollCounter || 0) + 1;
          if (AppState.endingPollCounter >= 3) {
            this.stopLiveCallPolling();
            this.showToast('info', 'Call ended.');
            return;
          }
        } else {
          AppState.endingPollCounter = 0;
        }
      } catch (err) {
        console.warn('Live call polling note:', err);
      }
    }, 1000);
  },

  stopLiveCallPolling() {
    clearInterval(AppState.liveCallPollInterval);
    AppState.activeCallId = null;
    setTimeout(() => {
      const widget = document.getElementById('live-calling-widget');
      if (widget) widget.classList.remove('active');
      this.fetchCalls();
      this.loadDashboardData();
      this.fetchLeads();
      this.fetchSiteVisits();
      this.fetchCallbacks();
      if (AppState.activeCampaignId) {
        this.openCampaignDetail(AppState.activeCampaignId);
      }
    }, 1200);
  },

  async hangupActiveCall() {
    if (!AppState.activeCallId) {
      document.getElementById('live-calling-widget')?.classList.remove('active');
      return;
    }
    try {
      await this.authFetch(`/api/calls/${AppState.activeCallId}/hangup`, { method: 'POST' });
      this.showToast('info', 'Terminating active call...');
      this.stopLiveCallPolling();
    } catch (err) {
      console.error('Hangup error:', err);
    }
  },

  // ---------------------------------------------------------------------------
  // 5. Call History Logic
  // ---------------------------------------------------------------------------
  async fetchCalls() {
    const status = document.getElementById('call-status-filter')?.value || 'all';
    const tbody = document.getElementById('calls-table-rows');
    if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="text-center text-slate-400 py-8">Loading calls...</td></tr>`;

    try {
      const res = await this.authFetch(`/api/calls?status=${status}`);
      const data = await res.json();
      AppState.calls = data.calls || [];

      if (!data.calls || !data.calls.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-slate-400 py-8">No call history recorded.</td></tr>`;
        return;
      }

      tbody.innerHTML = data.calls.map(c => `
        <tr>
          <td class="font-mono text-xs text-slate-500">${c.call_id}</td>
          <td class="font-bold text-xs sm:text-sm text-slate-900 dark:text-white">${c.customer_name}</td>
          <td class="font-mono text-xs text-slate-500">${c.phone_number_masked}</td>
          <td class="text-xs font-semibold text-slate-700 dark:text-slate-300">${c.duration_seconds}s</td>
          <td class="text-xs font-mono text-indigo-600 dark:text-indigo-400">${c.greeting_latency_ms ? `${c.greeting_latency_ms}ms` : 'N/A'}</td>
          <td class="text-xs font-mono text-slate-500">${c.avg_response_latency_ms ? `${c.avg_response_latency_ms}ms` : 'N/A'}</td>
          <td><span class="crm-badge crm-badge-stage">${c.outcome || 'Completed'}</span></td>
          <td class="text-right">
            <button onclick="App.openCallDetail('${c.call_id}')" class="crm-btn crm-btn-secondary crm-btn-sm text-xs py-1 px-2.5">
              Transcript
            </button>
          </td>
        </tr>
      `).join('');

      this.refreshIcons();
    } catch (err) {
      console.error('Fetch calls error:', err);
    }
  },

  async openCallDetail(callId) {
    try {
      const res = await this.authFetch(`/api/calls/${callId}`);
      const call = await res.json();

      document.getElementById('call-modal-title').innerText = `Call with ${call.customer_name}`;
      document.getElementById('call-modal-meta').innerText = `${call.phone_number_masked} • Duration: ${call.duration_seconds}s • P50 Latency: ${call.p50_latency_ms || 420}ms`;
      document.getElementById('call-modal-summary').innerText = call.summary || 'Summary automatically generated via Gemini.';

      const container = document.getElementById('call-modal-transcript');
      if (container) {
        if (!call.turns || !call.turns.length) {
          container.innerHTML = `<div class="text-center text-slate-400 py-6">No transcript recorded for this call.</div>`;
        } else {
          container.innerHTML = call.turns.map(t => `
            <div class="turn-bubble ${t.speaker}">
              <div class="text-[10px] font-bold mb-0.5 opacity-70">
                ${t.speaker === 'assistant' ? 'Priya (AI Voice)' : call.customer_name} ${t.latency_ms ? `• ${t.latency_ms.toFixed(0)}ms` : ''}
              </div>
              <div>${t.text}</div>
            </div>
          `).join('');
        }
      }

      this.openModal('modal-call-detail');
      this.refreshIcons();
    } catch (err) {
      this.showToast('error', 'Failed to load call detail: ' + err.message);
    }
  },

  // ---------------------------------------------------------------------------
  // 6. Properties Inventory Logic
  // ---------------------------------------------------------------------------
  async fetchProperties() {
    const loc = document.getElementById('prop-location-filter')?.value || 'all';
    const type = document.getElementById('prop-type-filter')?.value || 'all';
    const container = document.getElementById('properties-grid-container');

    try {
      const res = await this.authFetch(`/api/properties?location=${loc}&property_type=${type}`);
      const props = await res.json();
      AppState.properties = props || [];

      if (!props || !props.length) {
        container.innerHTML = `<div class="col-span-3 text-center text-slate-400 py-10">No properties match your filter.</div>`;
        return;
      }

      container.innerHTML = props.map(p => `
        <div class="crm-card p-5 flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between gap-2 mb-2">
              <span class="text-xs font-semibold px-2 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300">${p.location}</span>
              <span class="text-xs font-bold text-emerald-600 dark:text-emerald-400">${p.price_display}</span>
            </div>
            <h3 class="font-bold text-base text-slate-900 dark:text-white">${p.project_name}</h3>
            <div class="text-xs text-slate-500 mt-1">${p.bhk} • ${p.property_type} (${p.carpet_area || 'Standard'})</div>
            <p class="text-xs text-slate-600 dark:text-slate-400 mt-2 line-clamp-2">${p.description}</p>
          </div>

          <div class="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
            <span class="text-[11px] text-slate-400">${p.available_units || 0} units left</span>
            <button onclick="App.openNewLeadModal()" class="crm-btn crm-btn-secondary crm-btn-sm text-xs py-1 px-3">
              Match Lead
            </button>
          </div>
        </div>
      `).join('');

      this.refreshIcons();
    } catch (err) {
      console.error('Fetch properties error:', err);
    }
  },

  openNewPropertyModal() {
    this.openModal('modal-new-property');
  },

  async handleCreatePropertySubmit(event) {
    if (event) event.preventDefault();
    const payload = {
      project_name: document.getElementById('prop-form-name')?.value.trim(),
      location: document.getElementById('prop-form-loc')?.value.trim(),
      bhk: document.getElementById('prop-form-bhk')?.value.trim(),
      price_display: document.getElementById('prop-form-pricedisp')?.value.trim(),
      price_min: parseFloat(document.getElementById('prop-form-pricemin')?.value) || 5000000,
      price_max: 7500000,
      description: document.getElementById('prop-form-desc')?.value.trim() || 'Nagpur property listing'
    };

    try {
      await this.authFetch('/api/properties', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      this.closeModal('modal-new-property');
      this.showToast('success', 'Property listing created.');
      this.fetchProperties();
    } catch (err) {
      this.showToast('error', 'Failed to add property: ' + err.message);
    }
  },

  // ---------------------------------------------------------------------------
  // 7. AI Prompting & Agent Training Studio Logic
  // ---------------------------------------------------------------------------
  navigateToPlaybooks() {
    this.navigate('knowledge-base');
    this.switchStudioTab('scripts');
  },

  switchStudioTab(tabName) {
    const tabs = ['persona', 'greetings', 'funnel', 'scripts', 'docs', 'preview'];
    AppState.activeStudioTab = tabName;

    tabs.forEach(t => {
      const pane = document.getElementById(`studio-pane-${t}`);
      const btn = document.getElementById(`studio-tab-${t}`);
      if (pane) {
        if (t === tabName) {
          pane.classList.remove('hidden');
        } else {
          pane.classList.add('hidden');
        }
      }
      if (btn) {
        if (t === tabName) {
          btn.classList.add('active', 'bg-indigo-50', 'dark:bg-indigo-950', 'text-indigo-600', 'dark:text-indigo-400', 'border', 'border-indigo-200', 'dark:border-indigo-800', 'font-bold');
          btn.classList.remove('text-slate-600', 'dark:text-slate-400');
        } else {
          btn.classList.remove('active', 'bg-indigo-50', 'dark:bg-indigo-950', 'text-indigo-600', 'dark:text-indigo-400', 'border', 'border-indigo-200', 'dark:border-indigo-800', 'font-bold');
          btn.classList.add('text-slate-600', 'dark:text-slate-400');
        }
      }
    });

    if (tabName === 'scripts') {
      this.fetchAgentScripts();
    } else if (tabName === 'docs') {
      this.fetchKnowledgeDocs();
    } else if (tabName === 'preview') {
      this.fetchPromptPreview();
    }
  },

  switchKbTab(tabName) {
    if (tabName === 'scripts') this.switchStudioTab('scripts');
    else if (tabName === 'docs') this.switchStudioTab('docs');
    else this.switchStudioTab(tabName);
  },

  async fetchAgentVoices() {
    try {
      const res = await this.authFetch('/api/agent-voices');
      const voices = await res.json();
      AppState.agentVoices = voices || [];
      this.renderVoiceCards();
    } catch (err) {
      console.error('Failed to fetch agent voices:', err);
    }
  },

  renderVoiceCards() {
    const container = document.getElementById('studio-voices-grid');
    if (!container) return;

    const currentVoice = (AppState.agentConfig && AppState.agentConfig.voice) || AppState.selectedVoice || 'Aoede';
    AppState.selectedVoice = currentVoice;

    const tagEl = document.getElementById('studio-selected-voice-tag');
    if (tagEl) tagEl.innerText = currentVoice;

    container.innerHTML = (AppState.agentVoices || []).map(v => {
      const isSelected = v.id.toLowerCase() === currentVoice.toLowerCase();
      const activeClasses = isSelected
        ? 'border-indigo-600 dark:border-indigo-500 bg-indigo-50/70 dark:bg-indigo-950/60 ring-2 ring-indigo-500/30'
        : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 hover:border-slate-300 dark:hover:border-slate-700';

      return `
        <div onclick="App.selectVoice('${v.id}')" class="p-3.5 rounded-xl border cursor-pointer transition-all duration-200 flex flex-col justify-between ${activeClasses}">
          <div>
            <div class="flex items-center justify-between mb-1">
              <span class="font-bold text-xs text-slate-900 dark:text-white flex items-center gap-1.5">
                <i data-lucide="volume-2" class="w-3.5 h-3.5 ${isSelected ? 'text-indigo-600 dark:text-indigo-400' : 'text-slate-400'}"></i>
                ${v.name}
              </span>
              <span class="px-2 py-0.5 rounded text-[10px] font-bold ${isSelected ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'}">
                ${v.gender}
              </span>
            </div>
            <div class="text-[10px] font-semibold text-indigo-600 dark:text-indigo-400 mb-1">${v.tag}</div>
            <p class="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">${v.description}</p>
          </div>
          ${isSelected ? '<div class="mt-2 text-[10px] font-bold text-emerald-600 dark:text-emerald-400 flex items-center gap-1"><i data-lucide="check" class="w-3 h-3"></i> Active Voice</div>' : ''}
        </div>
      `;
    }).join('');

    this.refreshIcons();
  },

  selectVoice(voiceId) {
    AppState.selectedVoice = voiceId;
    if (AppState.agentConfig) {
      AppState.agentConfig.voice = voiceId;
    }
    const tagEl = document.getElementById('studio-selected-voice-tag');
    if (tagEl) tagEl.innerText = voiceId;

    // Auto-detect gender of selected voice and sync grammar & default name
    const vMeta = (AppState.agentVoices || []).find(v => v.id.toLowerCase() === voiceId.toLowerCase());
    if (vMeta && vMeta.gender) {
      const gSelect = document.getElementById('studio-gender-select');
      if (gSelect) gSelect.value = vMeta.gender.toLowerCase();
      if (AppState.agentConfig) {
        AppState.agentConfig.gender = vMeta.gender.toLowerCase();
      }
      
      const nameInput = document.getElementById('studio-agent-name');
      if (nameInput) {
        const curName = nameInput.value.trim().toLowerCase();
        if (vMeta.gender.toLowerCase() === 'male' && (curName === 'priya' || curName === '')) {
          nameInput.value = 'Parth';
          if (AppState.agentConfig) AppState.agentConfig.agent_display_name = 'Parth';
        } else if (vMeta.gender.toLowerCase() === 'female' && (curName === 'parth' || curName === '')) {
          nameInput.value = 'Priya';
          if (AppState.agentConfig) AppState.agentConfig.agent_display_name = 'Priya';
        }
      }
    }

    this.renderVoiceCards();
    this.showToast('info', `Selected Voice: ${voiceId} (${vMeta?.gender || 'Dynamic'})`);
    if (AppState.activeStudioTab === 'preview') {
      this.fetchPromptPreview();
    }
  },

  handleGenderChange(gender) {
    if (AppState.agentConfig) {
      AppState.agentConfig.gender = gender;
    }
    const domain = document.getElementById('studio-domain-select')?.value || AppState.agentConfig?.domain || 'real_estate';
    const preset = DOMAIN_CLIENT_PRESETS[domain] || DOMAIN_CLIENT_PRESETS['real_estate'];
    const nameInput = document.getElementById('studio-agent-name');
    if (nameInput) {
      nameInput.value = gender === 'male' ? preset.male_name : preset.female_name;
      if (AppState.agentConfig) {
        AppState.agentConfig.agent_display_name = nameInput.value;
      }
    }

    // Auto-switch voice to match gender if current voice has opposite gender
    const curVoiceMeta = (AppState.agentVoices || []).find(v => v.id.toLowerCase() === (AppState.selectedVoice || '').toLowerCase());
    if (curVoiceMeta && curVoiceMeta.gender && curVoiceMeta.gender.toLowerCase() !== gender) {
      const matchingVoice = (AppState.agentVoices || []).find(v => v.gender && v.gender.toLowerCase() === gender);
      if (matchingVoice) {
        AppState.selectedVoice = matchingVoice.id;
        if (AppState.agentConfig) AppState.agentConfig.voice = matchingVoice.id;
        const tagEl = document.getElementById('studio-selected-voice-tag');
        if (tagEl) tagEl.innerText = matchingVoice.id;
        this.renderVoiceCards();
      }
    }

    const headerPersonaText = document.getElementById('studio-active-persona-text');
    if (headerPersonaText) {
      const aName = nameInput?.value || preset.agent_name;
      const cName = document.getElementById('studio-company-name')?.value || preset.company_name;
      headerPersonaText.innerText = `${aName} • ${cName} • ${AppState.selectedVoice || 'Aoede'} • ${gender.toUpperCase()} • Temp 0.6`;
    }

    this.showToast('info', `Switched grammar to ${gender === 'male' ? '♂ Male' : '♀ Female'}`);
    if (AppState.activeStudioTab === 'preview') {
      this.fetchPromptPreview();
    }
  },

  applyDomainPresetToDOM(domainId, dataOverride = null) {
    const preset = DOMAIN_CLIENT_PRESETS[domainId] || DOMAIN_CLIENT_PRESETS['real_estate'];
    const data = dataOverride || {};

    const setVal = (id, val) => {
      const el = document.getElementById(id);
      if (el && val !== undefined && val !== null) el.value = val;
    };

    const agentName = data.agent_display_name || preset.agent_name;
    const companyName = data.company_name || preset.company_name;
    const gender = data.gender || preset.gender || 'female';
    const voice = data.voice || preset.voice || (gender === 'male' ? 'Charon' : 'Aoede');
    const roleDesc = (data.role_description !== undefined && data.role_description !== null && data.role_description !== '') ? data.role_description : preset.role_description;
    const greetingKnown = (data.greeting_known_lead !== undefined && data.greeting_known_lead !== null && data.greeting_known_lead !== '') ? data.greeting_known_lead : preset.greeting_known;
    const greetingUnknown = (data.greeting_unknown_lead !== undefined && data.greeting_unknown_lead !== null && data.greeting_unknown_lead !== '') ? data.greeting_unknown_lead : preset.greeting_unknown;
    const wrongNumber = (data.wrong_number_pivot !== undefined && data.wrong_number_pivot !== null && data.wrong_number_pivot !== '') ? data.wrong_number_pivot : preset.wrong_number;
    const funnel = (data.sales_funnel_stages !== undefined && data.sales_funnel_stages !== null && data.sales_funnel_stages !== '') ? data.sales_funnel_stages : preset.funnel;
    const philosophy = (data.conversation_philosophy !== undefined && data.conversation_philosophy !== null && data.conversation_philosophy !== '') ? data.conversation_philosophy : preset.philosophy;
    const guardrails = (data.objection_guardrails !== undefined && data.objection_guardrails !== null && data.objection_guardrails !== '') ? data.objection_guardrails : preset.guardrails;
    const temp = data.temperature !== undefined && data.temperature !== null ? data.temperature : 0.6;
    const lang = data.language_mode || 'hinglish';

    setVal('topbar-domain-select', domainId);
    setVal('studio-domain-select', domainId);
    setVal('studio-gender-select', gender);
    setVal('studio-agent-name', agentName);
    setVal('studio-company-name', companyName);
    setVal('studio-role-desc', roleDesc);
    setVal('studio-greeting-known', greetingKnown);
    setVal('studio-greeting-unknown', greetingUnknown);
    setVal('studio-wrong-number', wrongNumber);
    setVal('studio-funnel-stages', funnel);
    setVal('studio-philosophy', philosophy);
    setVal('studio-guardrails', guardrails);
    setVal('studio-language-mode', lang);

    const tempEl = document.getElementById('studio-temperature');
    const tempDisplay = document.getElementById('studio-temp-display');
    if (tempEl) tempEl.value = temp;
    if (tempDisplay) tempDisplay.innerText = parseFloat(temp).toFixed(2);

    AppState.selectedVoice = voice;
    const headerPersonaText = document.getElementById('studio-active-persona-text');
    if (headerPersonaText) {
      headerPersonaText.innerText = `${agentName} • ${companyName} • ${voice} • ${gender.toUpperCase()} • Temp ${parseFloat(temp).toFixed(1)}`;
    }
    const voiceTag = document.getElementById('studio-selected-voice-tag');
    if (voiceTag) voiceTag.innerText = voice;

    this.renderVoiceCards();
  },

  async handleDomainChange(domainId) {
    try {
      // 1. INSTANT ZERO-LATENCY LOCAL UI UPDATE:
      this.applyDomainPresetToDOM(domainId);
      this.showToast('info', `Switching active AI persona to ${DOMAIN_CLIENT_PRESETS[domainId]?.name || domainId}...`);

      // 2. PERSIST TO BACKEND & ISOLATE SCRIPTS:
      const res = await this.authFetch('/api/agent-config/switch-domain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: domainId })
      });
      const data = await res.json();
      AppState.agentConfig = data;
      AppState.selectedVoice = data.voice || 'Aoede';

      // 3. SYNC WITH COMMITTED SERVER RECORD:
      this.applyDomainPresetToDOM(data.domain || domainId, data);
      await this.fetchAgentScripts(data.domain || domainId);

      this.showToast('success', `Activated ${data.company_name} (${data.agent_display_name})! All live calls now speak in this persona.`);
      if (AppState.activeStudioTab === 'preview') {
        this.fetchPromptPreview();
      }
    } catch (err) {
      console.error('Failed to switch domain:', err);
      this.showToast('error', 'Failed to persist domain switch: ' + err.message);
    }
  },

  async fetchAgentConfig() {
    try {
      const res = await this.authFetch('/api/agent-config');
      const cfg = await res.json();
      AppState.agentConfig = cfg;
      AppState.selectedVoice = cfg.voice || 'Aoede';

      const dom = cfg.domain || 'real_estate';
      this.applyDomainPresetToDOM(dom, cfg);
      await this.fetchAgentScripts(dom);
    } catch (err) {
      console.error('Failed to fetch agent config:', err);
    }
  },

  async saveAgentConfig() {
    const domain = document.getElementById('studio-domain-select')?.value || 'real_estate';
    const gender = document.getElementById('studio-gender-select')?.value || 'female';
    const agent_display_name = document.getElementById('studio-agent-name')?.value.trim();
    const company_name = document.getElementById('studio-company-name')?.value.trim();
    const role_description = document.getElementById('studio-role-desc')?.value.trim();
    const voice = AppState.selectedVoice || 'Aoede';
    const temperature = parseFloat(document.getElementById('studio-temperature')?.value || 0.6);
    const language_mode = document.getElementById('studio-language-mode')?.value;
    const greeting_known_lead = document.getElementById('studio-greeting-known')?.value.trim();
    const greeting_unknown_lead = document.getElementById('studio-greeting-unknown')?.value.trim();
    const wrong_number_pivot = document.getElementById('studio-wrong-number')?.value.trim();
    const sales_funnel_stages = document.getElementById('studio-funnel-stages')?.value.trim();
    const conversation_philosophy = document.getElementById('studio-philosophy')?.value.trim();
    const objection_guardrails = document.getElementById('studio-guardrails')?.value.trim();

    const payload = {
      name: `${company_name} - ${agent_display_name} Sales Persona`,
      domain,
      gender,
      agent_display_name,
      company_name,
      role_description,
      voice,
      temperature,
      language_mode,
      greeting_known_lead,
      greeting_unknown_lead,
      wrong_number_pivot,
      sales_funnel_stages,
      conversation_philosophy,
      objection_guardrails,
      is_active: true
    };

    try {
      this.showToast('info', 'Saving AI Studio configurations...');
      const res = await this.authFetch('/api/agent-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const updated = await res.json();
      AppState.agentConfig = updated;

      const headerPersonaText = document.getElementById('studio-active-persona-text');
      if (headerPersonaText) {
        headerPersonaText.innerText = `${updated.agent_display_name} • ${updated.voice} • ${(updated.gender || 'female').toUpperCase()} • Temp ${(updated.temperature || 0.6).toFixed(1)}`;
      }

      this.showToast('success', `Studio Saved! ${updated.agent_display_name} is active for all upcoming calls.`);
    } catch (err) {
      this.showToast('error', 'Save failed: ' + err.message);
    }
  },

  async resetAgentConfig() {
    if (!confirm('Are you sure you want to reset the agent persona, greetings, and sales funnel back to active domain default factory settings?')) return;

    try {
      this.showToast('info', 'Resetting to factory defaults...');
      const res = await this.authFetch('/api/agent-config/reset', { method: 'POST' });
      const def = await res.json();
      AppState.agentConfig = def;
      await this.fetchAgentConfig();
      await this.fetchAgentScripts();
      this.showToast('success', `Agent persona successfully restored to ${def.agent_display_name} - ${def.company_name} defaults!`);
    } catch (err) {
      this.showToast('error', 'Reset failed: ' + err.message);
    }
  },

  async fetchPromptPreview() {
    const domain = document.getElementById('studio-domain-select')?.value || 'real_estate';
    const gender = document.getElementById('studio-gender-select')?.value || 'female';
    const testCustName = document.getElementById('studio-preview-test-customer')?.value.trim() || 'Rahul Sharma';
    const agentName = document.getElementById('studio-agent-name')?.value.trim() || 'Priya';
    const companyName = document.getElementById('studio-company-name')?.value.trim() || 'Nagpur Estates';
    const roleDesc = document.getElementById('studio-role-desc')?.value.trim();
    const voice = AppState.selectedVoice || 'Aoede';
    const temp = parseFloat(document.getElementById('studio-temperature')?.value || 0.6);

    const preEl = document.getElementById('preview-prompt-text');
    if (preEl) preEl.innerText = 'Compiling real-time prompt from database and active playbooks...';

    try {
      const res = await this.authFetch('/api/agent-config/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          domain: domain,
          gender: gender,
          test_customer_name: testCustName,
          agent_display_name: agentName,
          company_name: companyName,
          role_description: roleDesc,
          voice: voice,
          temperature: temp
        })
      });
      const data = await res.json();

      const setTxt = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.innerText = val;
      };

      setTxt('preview-stat-chars', (data.char_count || 0).toLocaleString());
      setTxt('preview-stat-words', (data.word_count || 0).toLocaleString());
      setTxt('preview-stat-tokens', `~${(data.approx_tokens || 0).toLocaleString()}`);
      setTxt('preview-stat-voice', `${data.voice} (${(data.temperature || 0.6).toFixed(2)})`);
      setTxt('preview-opening-speech', `"${data.greeting_speech}"`);

      if (preEl) preEl.innerText = data.system_prompt || '';
    } catch (err) {
      if (preEl) preEl.innerText = 'Error loading prompt preview: ' + err.message;
    }
  },

  // ---------------------------------------------------------------------------
  // 7.5 AI Scripts & Agent Training Playbooks Logic
  // ---------------------------------------------------------------------------
  scriptTemplates: {
    fillers_empathy: {
      title: "Natural Hindi/Hinglish Verbal Nods & Empathy",
      category: "fillers",
      content: `- While customer is speaking, insert warm verbal nods naturally every 4-7 seconds: "Haan ji", "Bilkul", "Sahi baat hai", "Samajh rahi hoon".
- If customer expresses hesitation or confusion: "Aap bilkul befikr rahiye, main poori clarity doongi."
- Never sound mechanical or scripted. Keep intonation lively and supportive.`
    },
    objection_pricing: {
      title: "Budget & Price Objection Handling",
      category: "objections",
      content: `- When customer says "Budget bahut high hai" or "Price zyaada hai":
  1. Acknowledge with respect: "Main aapki baat samajh rahi hoon {cust_ji}. Budget sabse important consideration hota hai."
  2. Highlight value & flexible terms: "Hamare paas flexible payment plans aur attractive EMI options bhi available hain."
  3. Offer to check lower-range options: "Kya main aapke comfortable budget ke hisaab se alternative options shortlist karoon?"`
    },
    clinic_triage: {
      title: "Doctor Consultation OPD Guidance & Triage",
      category: "conversation_script",
      content: `- When patient asks about medical symptoms or doctor advice:
  1. State clearly: "Main AI assistant hoon, medical diagnosis nahi de sakti, lekin hamare specialist doctor se aapki consultation zaroor book kar sakti hoon."
  2. Inquire politely: "Aap kis department mein dikhana chahte hain? Jaise General Medicine, Orthopedic, Dermatologist ya Pediatric?"
  3. Confirm slot and ask patient details politely.`
    },
    sales_closing: {
      title: "Site Visit / Appointment Closing Script",
      category: "conversation_script",
      content: `- When customer shows interest:
  "Toh {cust_ji}, property ko directly dekhna sabse best rehta hai. Kya is weekend ko ek site visit schedule kar lein? Hamari cab facility bhi available hai."
- When confirmed: Immediately invoke schedule_site_visit tool with customer's date and time.`
    },
    wrong_number: {
      title: "Polite Wrong Number Pivot & Clarification",
      category: "identity_verification",
      content: `- If recipient says "Main {cust_display} nahi hoon" or "Galat number hai":
  "Arey, maafi chahti hoon ji! Shayad number dial karne mein galti ho gayi. Kya aap bhi {company_name} ke offerings mein interested hain, ya main call disconnect kar doon?"
- If they decline, politely apologize and close warmly.`
    }
  },

  insertScriptTemplate(templateKey, target = 'new') {
    const tmpl = this.scriptTemplates[templateKey];
    if (!tmpl) return;

    const prefix = target === 'edit' ? 'edit-script-' : 'script-modal-';
    const titleEl = document.getElementById(`${prefix}title`);
    const catEl = document.getElementById(`${prefix}category`);
    const contentEl = document.getElementById(`${prefix}content`);

    if (titleEl && (!titleEl.value.trim() || target === 'new')) {
      titleEl.value = tmpl.title;
    }
    if (catEl) {
      catEl.value = tmpl.category;
    }
    if (contentEl) {
      if (target === 'edit' && contentEl.value.trim()) {
        contentEl.value += '\n\n' + tmpl.content;
      } else {
        contentEl.value = tmpl.content;
      }
    }
    this.showToast('info', `Template loaded: ${tmpl.title}`);
  },

  filterScriptsByCategory(category) {
    AppState.scriptCategoryFilter = category;
    document.querySelectorAll('.script-cat-pill').forEach(btn => {
      btn.classList.remove('active', 'bg-indigo-50', 'dark:bg-indigo-950', 'text-indigo-600', 'dark:text-indigo-400', 'border-indigo-200', 'dark:border-indigo-800', 'font-bold');
      btn.classList.add('text-slate-600', 'dark:text-slate-400', 'border-transparent');
    });

    const activeBtn = document.getElementById(`script-cat-btn-${category}`);
    if (activeBtn) {
      activeBtn.classList.add('active', 'bg-indigo-50', 'dark:bg-indigo-950', 'text-indigo-600', 'dark:text-indigo-400', 'border-indigo-200', 'dark:border-indigo-800', 'font-bold');
      activeBtn.classList.remove('text-slate-600', 'dark:text-slate-400', 'border-transparent');
    }

    this.renderAgentScripts(AppState.agentScripts || []);
  },

  handleScriptSearch(val) {
    AppState.scriptSearchKeyword = (val || '').toLowerCase().trim();
    this.renderAgentScripts(AppState.agentScripts || []);
  },

  async fetchAgentScripts(domain = null) {
    try {
      const activeDom = domain || document.getElementById('studio-domain-select')?.value || AppState.agentConfig?.domain || 'real_estate';
      const url = activeDom && activeDom !== 'all' ? `/api/agent-scripts?domain=${encodeURIComponent(activeDom)}` : '/api/agent-scripts';
      const res = await this.authFetch(url);
      const scripts = await res.json();
      AppState.agentScripts = scripts || [];

      // Update counters
      const activeCount = (scripts || []).filter(s => s.is_active).length;
      const totalCount = (scripts || []).length;
      const primaryScript = (scripts || []).find(s => s.is_primary);

      const badge = document.getElementById('kb-scripts-count');
      if (badge) badge.innerText = totalCount;

      const sbBadge = document.getElementById('sidebar-playbooks-count');
      if (sbBadge) sbBadge.innerText = `${activeCount} Active`;

      const activePill = document.getElementById('scripts-active-count-badge');
      if (activePill) {
        if (primaryScript) {
          activePill.innerHTML = `● ${activeCount} Active <span class="ml-1 px-1.5 py-0.2 rounded bg-amber-500 text-white text-[9px] font-black">★ Primary: ${this.escapeHtml(primaryScript.title.slice(0, 20))}</span>`;
        } else {
          activePill.innerText = `● ${activeCount} Active on Calls`;
        }
      }

      this.renderAgentScripts(AppState.agentScripts);
    } catch (err) {
      console.error('Fetch agent scripts error:', err);
    }
  },

  renderAgentScripts(scripts) {
    const container = document.getElementById('kb-scripts-container');
    if (!container) return;

    // Always sort primary script to the top
    let sorted = [...(scripts || [])].sort((a, b) => {
      if (a.is_primary && !b.is_primary) return -1;
      if (!a.is_primary && b.is_primary) return 1;
      return 0;
    });

    let filtered = sorted;

    // Category filter
    const catFilter = AppState.scriptCategoryFilter || 'all';
    if (catFilter === 'primary') {
      filtered = filtered.filter(s => s.is_primary);
    } else if (catFilter !== 'all') {
      filtered = filtered.filter(s => s.category === catFilter);
    }

    // Search keyword filter
    const q = AppState.scriptSearchKeyword || '';
    if (q) {
      filtered = filtered.filter(s => 
        (s.title && s.title.toLowerCase().includes(q)) ||
        (s.content && s.content.toLowerCase().includes(q)) ||
        (s.category && s.category.toLowerCase().includes(q))
      );
    }

    if (!filtered || !filtered.length) {
      const isFiltered = (catFilter !== 'all') || Boolean(q);
      container.innerHTML = `
        <div class="col-span-full text-center py-12 bg-white dark:bg-slate-900 border border-dashed border-slate-300 dark:border-slate-800 rounded-2xl p-6">
          <i data-lucide="layers" class="w-8 h-8 text-indigo-400 mx-auto mb-2 opacity-80"></i>
          <h3 class="text-sm font-bold text-slate-800 dark:text-slate-200">${isFiltered ? 'No Scripts Match Filter' : 'No Scripts Found'}</h3>
          <p class="text-xs text-slate-500 mt-1 max-w-md mx-auto">
            ${isFiltered 
              ? `No playbooks match category '${catFilter}' or search '${q}'. Click below to view all scripts or create a new one.` 
              : 'No spoken scripts have been configured yet for this domain. Add a script or upload a file to train the AI agent.'}
          </p>
          <div class="flex items-center justify-center gap-2 mt-4">
            ${isFiltered ? `
              <button onclick="App.filterScriptsByCategory('all'); const si = document.getElementById('script-search-input'); if (si) { si.value = ''; App.handleScriptSearch(''); }" class="crm-btn crm-btn-secondary crm-btn-sm">
                <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i>
                Show All Scripts
              </button>
            ` : ''}
            <button onclick="App.openNewScriptModal()" class="crm-btn crm-btn-primary crm-btn-sm">
              <i data-lucide="plus" class="w-3.5 h-3.5"></i>
              + Add AI Script
            </button>
          </div>
        </div>
      `;
      this.refreshIcons();
      return;
    }

    const domainBadges = {
      real_estate: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800/50">🏢 Real Estate</span>',
      clinic_hospital: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-teal-50 text-teal-800 dark:bg-teal-950/60 dark:text-teal-300 border border-teal-200 dark:border-teal-800/50">🏥 Hospital</span>',
      ecommerce: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-purple-50 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300 border border-purple-200 dark:border-purple-800/50">🛍️ E-Comm</span>',
      education: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-blue-50 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300 border border-blue-200 dark:border-blue-800/50">🎓 Education</span>',
      general_business: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-300 border border-slate-300 dark:border-slate-700">💼 Business</span>',
      all: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-indigo-50 text-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800/50">🌐 Universal</span>'
    };

    const categoryBadges = {
      fillers: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300">Fillers & Tone</span>',
      identity_verification: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">Name Verification</span>',
      conversation_script: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300">Sales Script</span>',
      objections: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300">Objection Handling</span>',
      persona: '<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-pink-100 text-pink-800 dark:bg-pink-950/60 dark:text-pink-300">Persona & Tone</span>'
    };

    container.innerHTML = filtered.map(s => {
      const domBadge = domainBadges[s.domain || 'real_estate'] || domainBadges['real_estate'];
      const catBadge = categoryBadges[s.category] || `<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">${s.category}</span>`;
      const activeClass = s.is_active
        ? 'bg-emerald-500 hover:bg-emerald-600 text-white shadow-sm shadow-emerald-500/20'
        : 'bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400';
      const activeLabel = s.is_active ? '● Active on Call' : 'Disabled';

      const cardBorderClass = s.is_primary
        ? 'border-2 border-amber-500 shadow-lg shadow-amber-500/10 bg-gradient-to-b from-amber-50/40 via-white to-white dark:from-amber-950/30 dark:via-slate-900 dark:to-slate-900'
        : (s.is_active ? 'border-t-2 border-t-emerald-500 shadow-sm' : 'border-t-2 border-t-slate-300 dark:border-t-slate-700 opacity-80');

      const primaryBadge = s.is_primary ? `
        <span class="px-2 py-0.5 rounded-full text-[10px] font-black bg-amber-500 text-white flex items-center gap-1 shadow-sm shadow-amber-500/30 animate-pulse">
          <i data-lucide="star" class="w-3 h-3 fill-white"></i>
          ★ PRIMARY SCRIPT (Next Calls/Batch)
        </span>
      ` : '';

      const primaryBtn = s.is_primary ? `
        <button onclick="App.unselectPrimaryScript('${s.id}')" class="px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-500 hover:bg-amber-600 text-white shadow-sm shadow-amber-500/30 flex items-center gap-1 transition" title="Currently active primary script for next calls. Click to unselect.">
          <i data-lucide="check-circle" class="w-3 h-3 fill-white"></i>
          ★ Primary Active
        </button>
      ` : `
        <button onclick="App.selectPrimaryScript('${s.id}')" class="px-2 py-1 rounded-full text-[10px] font-semibold bg-slate-100 hover:bg-amber-50 dark:bg-slate-800 dark:hover:bg-amber-950/60 text-slate-600 dark:text-slate-300 hover:text-amber-700 dark:hover:text-amber-300 border border-slate-200 dark:border-slate-700 hover:border-amber-300 flex items-center gap-1 transition" title="Choose as primary script for next calls or batch dialer">
          <i data-lucide="star" class="w-3 h-3 text-slate-400"></i>
          Select for Next Calls
        </button>
      `;

      return `
        <div class="crm-card p-4 flex flex-col justify-between space-y-3 relative group ${cardBorderClass}">
          <div>
            <div class="flex items-start justify-between gap-2 mb-2">
              <div>
                ${primaryBadge}
                <h4 class="font-bold text-xs sm:text-sm text-slate-900 dark:text-white leading-snug mt-1">${this.escapeHtml(s.title)}</h4>
              </div>
              <div class="shrink-0 flex items-center gap-1.5">
                <button onclick="App.openEditScriptModal('${s.id}')" class="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950 dark:hover:bg-indigo-900 text-indigo-600 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800 transition" title="Edit Playbook">
                  <i data-lucide="edit-3" class="w-3 h-3"></i>
                  <span>Edit</span>
                </button>
                <button onclick="App.deleteScript('${s.id}')" class="p-1 rounded hover:bg-red-50 dark:hover:bg-red-950 text-slate-400 hover:text-red-500 transition" title="Delete Script">
                  <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                </button>
              </div>
            </div>
            <div class="flex items-center gap-2 mb-2.5 flex-wrap">
              ${domBadge}
              ${catBadge}
              ${s.filename ? `<span class="text-[10px] text-slate-400 font-mono flex items-center gap-0.5"><i data-lucide="file-text" class="w-3 h-3"></i> ${this.escapeHtml(s.filename)}</span>` : ''}
            </div>
            <div class="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-950/70 border border-slate-100 dark:border-slate-800 text-[11px] font-mono text-slate-600 dark:text-slate-300 max-h-36 overflow-y-auto whitespace-pre-wrap leading-relaxed">
${this.escapeHtml(s.content)}
            </div>
          </div>

          <div class="flex items-center justify-between pt-2 border-t border-slate-100 dark:border-slate-800 text-[11px] flex-wrap gap-2">
            <div class="flex items-center gap-2">
              <span class="text-slate-400">${s.created_at ? this.formatDate(s.created_at) : 'Active'}</span>
              ${primaryBtn}
            </div>
            <button onclick="App.toggleScriptActive('${s.id}')" class="px-2.5 py-1 rounded-full text-[10px] font-bold transition flex items-center gap-1 ${activeClass}">
              ${activeLabel}
            </button>
          </div>
        </div>
      `;
    }).join('');

    this.refreshIcons();
  },

  async selectPrimaryScript(scriptId) {
    try {
      const res = await this.authFetch(`/api/agent-scripts/${scriptId}/select-primary`, { method: 'PATCH' });
      const data = await res.json();
      this.showToast('success', `★ Script '${data.title}' selected as PRIMARY for upcoming calls & batches!`);
      await this.fetchAgentScripts();
      this.fetchPromptPreview();
    } catch (err) {
      this.showToast('error', 'Selection failed: ' + err.message);
    }
  },

  async unselectPrimaryScript(scriptId) {
    try {
      await this.authFetch(`/api/agent-scripts/${scriptId}/unselect-primary`, { method: 'PATCH' });
      this.showToast('info', 'Primary script designation cleared.');
      await this.fetchAgentScripts();
      this.fetchPromptPreview();
    } catch (err) {
      this.showToast('error', 'Unselect failed: ' + err.message);
    }
  },

  async toggleScriptActive(scriptId) {
    try {
      const res = await this.authFetch(`/api/agent-scripts/${scriptId}/toggle`, { method: 'PATCH' });
      const data = await res.json();
      this.showToast('info', `AI Script '${data.title}' is now ${data.is_active ? 'ACTIVE' : 'DISABLED'} for upcoming calls.`);
      await this.fetchAgentScripts();
      this.fetchPromptPreview();
    } catch (err) {
      this.showToast('error', 'Toggle failed: ' + err.message);
    }
  },

  async deleteScript(scriptId) {
    if (!confirm('Are you sure you want to remove this training script?')) return;
    try {
      await this.authFetch(`/api/agent-scripts/${scriptId}`, { method: 'DELETE' });
      this.showToast('success', 'Training script removed.');
      await this.fetchAgentScripts();
      this.fetchPromptPreview();
    } catch (err) {
      this.showToast('error', 'Delete failed: ' + err.message);
    }
  },

  openNewScriptModal() {
    const modal = document.getElementById('new-script-modal');
    if (modal) {
      const curDomain = document.getElementById('studio-domain-select')?.value || 'real_estate';
      const domEl = document.getElementById('script-modal-domain');
      if (domEl) domEl.value = curDomain;
      document.getElementById('script-modal-title').value = '';
      document.getElementById('script-modal-content').value = '';
      document.getElementById('script-modal-category').value = 'conversation_script';
      document.getElementById('script-modal-active').checked = true;
      const primEl = document.getElementById('script-modal-primary');
      if (primEl) primEl.checked = false;
      modal.classList.remove('hidden');
    }
  },

  closeNewScriptModal() {
    document.getElementById('new-script-modal')?.classList.add('hidden');
  },

  openEditScriptModal(scriptId) {
    const script = (AppState.agentScripts || []).find(s => s.id === scriptId);
    if (!script) return;

    const modal = document.getElementById('edit-script-modal');
    if (modal) {
      document.getElementById('edit-script-id').value = script.id;
      const domEl = document.getElementById('edit-script-domain');
      if (domEl) domEl.value = script.domain || 'real_estate';
      document.getElementById('edit-script-title').value = script.title || '';
      document.getElementById('edit-script-category').value = script.category || 'conversation_script';
      document.getElementById('edit-script-active').checked = !!script.is_active;
      const primEl = document.getElementById('edit-script-primary');
      if (primEl) primEl.checked = !!script.is_primary;
      document.getElementById('edit-script-content').value = script.content || '';
      modal.classList.remove('hidden');
    }
  },

  closeEditScriptModal() {
    document.getElementById('edit-script-modal')?.classList.add('hidden');
  },

  async saveEditedScript() {
    const scriptId = document.getElementById('edit-script-id')?.value;
    const title = document.getElementById('edit-script-title')?.value.trim();
    const domain = document.getElementById('edit-script-domain')?.value || 'real_estate';
    const category = document.getElementById('edit-script-category')?.value;
    const content = document.getElementById('edit-script-content')?.value.trim();
    const isActive = document.getElementById('edit-script-active')?.checked ?? true;
    const isPrimary = document.getElementById('edit-script-primary')?.checked ?? false;

    if (!scriptId) return;
    if (!title) return this.showToast('warning', 'Please provide a playbook title.');
    if (!content) return this.showToast('warning', 'Please enter script instructions.');

    try {
      const res = await this.authFetch(`/api/agent-scripts/${scriptId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          domain,
          category,
          content,
          is_active: isActive,
          is_primary: isPrimary
        })
      });
      const data = await res.json();
      this.showToast('success', `AI Script '${data.title}' updated! Agent training refreshed.`);
      this.closeEditScriptModal();
      await this.fetchAgentScripts();
      this.fetchPromptPreview();
    } catch (err) {
      this.showToast('error', 'Update failed: ' + err.message);
    }
  },

  async saveNewScript() {
    const title = document.getElementById('script-modal-title')?.value.trim();
    const domain = document.getElementById('script-modal-domain')?.value || 'real_estate';
    const category = document.getElementById('script-modal-category')?.value;
    const content = document.getElementById('script-modal-content')?.value.trim();
    const isActive = document.getElementById('script-modal-active')?.checked ?? true;
    const isPrimary = document.getElementById('script-modal-primary')?.checked ?? false;

    if (!title) return this.showToast('warning', 'Please provide a playbook title.');
    if (!content) return this.showToast('warning', 'Please enter script instructions or dialogue.');

    try {
      const res = await this.authFetch('/api/agent-scripts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          domain,
          category,
          content,
          is_active: isActive,
          is_primary: isPrimary
        })
      });
      const data = await res.json();
      this.showToast('success', `AI Script created! Agent is now trained with '${data.title}'.`);
      this.closeNewScriptModal();
      await this.fetchAgentScripts();
      this.fetchPromptPreview();
    } catch (err) {
      this.showToast('error', 'Failed to save script: ' + err.message);
    }
  },

  triggerScriptUpload() {
    document.getElementById('script-file-input')?.click();
  },

  async uploadScriptFile(event) {
    const file = event.target.files[0];
    if (!file) return;

    const curDomain = document.getElementById('studio-domain-select')?.value || 'real_estate';
    const formData = new FormData();
    formData.append('file', file);
    formData.append('category', 'conversation_script');
    formData.append('domain', curDomain);

    try {
      this.showToast('info', `Ingesting script file ${file.name}...`);
      const res = await this.authFetch('/api/agent-scripts/upload', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      this.showToast('success', `Script Ingested! Agent trained with '${data.title}' (${data.char_count} chars).`);
      await this.fetchAgentScripts();
      this.fetchPromptPreview();
    } catch (err) {
      this.showToast('error', 'Script upload failed: ' + err.message);
    } finally {
      event.target.value = '';
    }
  },

  // ---------------------------------------------------------------------------
  // 8. Knowledge Base Documents Logic
  // ---------------------------------------------------------------------------
  async fetchKnowledgeDocs() {
    const tbody = document.getElementById('kb-documents-rows');
    const badge = document.getElementById('kb-docs-count');
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" class="text-center text-slate-400 py-6">Loading documents...</td></tr>`;

    try {
      const res = await this.authFetch('/api/knowledge-base');
      const docs = await res.json();
      AppState.knowledgeDocs = docs || [];

      if (badge) badge.innerText = docs.length;

      if (!docs || !docs.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-slate-400 py-6">No documents uploaded yet.</td></tr>`;
        return;
      }

      tbody.innerHTML = docs.map(d => `
        <tr>
          <td class="font-semibold text-xs text-slate-900 dark:text-white">${d.filename}</td>
          <td><span class="crm-badge crm-badge-stage">${d.document_type}</span></td>
          <td><span class="crm-badge crm-badge-success">● ${d.status}</span></td>
          <td class="text-xs text-slate-500">${d.chunk_count} chunks</td>
          <td class="text-xs text-slate-500">${d.vector_count} vectors</td>
          <td class="text-xs text-slate-400">${this.formatDate(d.created_at)}</td>
        </tr>
      `).join('');

      this.refreshIcons();
    } catch (err) {
      console.error('Fetch knowledge docs error:', err);
    }
  },

  triggerDocUpload() {
    document.getElementById('doc-file-input')?.click();
  },

  async uploadDocFile(event) {
    const file = event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      this.showToast('info', `Vectorizing ${file.name} with Gemini Embedding...`);
      const res = await this.authFetch('/api/knowledge-base/upload', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      this.showToast('success', `Document Vectorized: ${data.filename} (${data.chunks} chunks).`);
      this.fetchKnowledgeDocs();
    } catch (err) {
      this.showToast('error', 'Upload failed: ' + err.message);
    }
  },

  setRagQuery(text) {
    const input = document.getElementById('rag-test-query');
    if (input) {
      input.value = text;
      this.testRagSearch();
    }
  },

  async testRagSearch() {
    const input = document.getElementById('rag-test-query');
    const query = input?.value.trim();
    if (!query) return;

    const resultsBox = document.getElementById('rag-test-results');
    if (resultsBox) resultsBox.innerHTML = 'Searching vector embeddings with top_k=3...';

    try {
      const res = await this.authFetch(`/api/knowledge-base/search-test?query=${encodeURIComponent(query)}`, {
        method: 'POST'
      });
      const data = await res.json();

      if (!data.results || !data.results.length) {
        resultsBox.innerHTML = '<div class="text-slate-400">No matching vector chunks found.</div>';
        return;
      }

      resultsBox.innerHTML = data.results.map((r, i) => `
        <div class="p-3 bg-white dark:bg-slate-950 rounded-lg border border-slate-200 dark:border-slate-800">
          <div class="flex items-center justify-between text-[11px] font-semibold text-slate-500 mb-1">
            <span>Result #${i+1} • Source: <strong>${r.metadata?.filename || 'Document'}</strong></span>
            <span class="text-emerald-600 dark:text-emerald-400">Score: ${(r.score * 100).toFixed(1)}%</span>
          </div>
          <div class="text-xs text-slate-800 dark:text-slate-200">${r.content}</div>
        </div>
      `).join('');
    } catch (err) {
      if (resultsBox) resultsBox.innerHTML = `<div class="text-red-500">Vector search failed: ${err.message}</div>`;
    }
  },

  // ---------------------------------------------------------------------------
  // 8. Site Visits & Callbacks Logic
  // ---------------------------------------------------------------------------
  async fetchSiteVisits() {
    const tbody = document.getElementById('site-visits-rows');
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center text-slate-400 py-6">Loading site visits...</td></tr>`;

    try {
      const res = await this.authFetch('/api/site-visits');
      const visits = await res.json();
      AppState.siteVisits = visits || [];

      if (!visits || !visits.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-slate-400 py-6">No site visits scheduled.</td></tr>`;
        return;
      }

      tbody.innerHTML = visits.map(v => `
        <tr>
          <td class="font-bold text-xs sm:text-sm text-slate-900 dark:text-white">${v.customer_name}</td>
          <td class="font-mono text-xs text-slate-500">${v.phone_number}</td>
          <td class="text-xs text-slate-700 dark:text-slate-300">${v.location}</td>
          <td class="text-xs font-semibold text-indigo-600 dark:text-indigo-400">${v.visit_datetime}</td>
          <td><span class="crm-badge crm-badge-success">● ${v.status}</span></td>
          <td class="text-xs text-slate-500">${v.salesperson}</td>
          <td class="text-right">
            <button onclick="App.updateVisitStatus('${v.id}', 'completed')" class="crm-btn crm-btn-secondary crm-btn-sm text-xs py-1 px-2.5">
              Mark Done
            </button>
          </td>
        </tr>
      `).join('');

      this.refreshIcons();
    } catch (err) {
      console.error('Fetch site visits error:', err);
    }
  },

  openBookVisitModalDirect() {
    this.openModal('modal-book-visit');
  },

  openBookVisitModalFromDrawer() {
    if (!AppState.currentLeadInDrawer) return;
    this.closeLeadDrawer();
    this.openModal('modal-book-visit');
  },

  async handleBookVisitSubmit(event) {
    if (event) event.preventDefault();
    const leadId = AppState.currentLeadInDrawer?.id || (AppState.leads[0]?.id || 'lead_demo');
    const payload = {
      lead_id: leadId,
      location: document.getElementById('visit-form-loc')?.value.trim(),
      visit_datetime: document.getElementById('visit-form-dt')?.value,
      salesperson: document.getElementById('visit-form-salesperson')?.value.trim() || 'Priya'
    };

    try {
      await this.authFetch('/api/site-visits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      this.closeModal('modal-book-visit');
      this.showToast('success', 'Site visit confirmed & booked!');
      this.fetchSiteVisits();
      this.loadDashboardData();
    } catch (err) {
      this.showToast('error', 'Booking failed: ' + err.message);
    }
  },

  async updateVisitStatus(visitId, status) {
    try {
      await this.authFetch(`/api/site-visits/${visitId}/status?new_status=${status}`, { method: 'PATCH' });
      this.showToast('success', `Site visit marked as ${status}.`);
      this.fetchSiteVisits();
      this.loadDashboardData();
    } catch (err) {
      this.showToast('error', 'Update error: ' + err.message);
    }
  },

  async fetchCallbacks() {
    const tbody = document.getElementById('callbacks-rows');
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" class="text-center text-slate-400 py-6">Loading callbacks...</td></tr>`;

    try {
      const res = await this.authFetch('/api/callbacks');
      const cbs = await res.json();
      AppState.callbacks = cbs || [];

      if (!cbs || !cbs.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-slate-400 py-6">No scheduled callbacks due.</td></tr>`;
        return;
      }

      tbody.innerHTML = cbs.map(cb => `
        <tr>
          <td class="font-bold text-xs sm:text-sm text-slate-900 dark:text-white">${cb.customer_name}</td>
          <td class="font-mono text-xs text-slate-500">${cb.phone_number}</td>
          <td class="text-xs font-bold text-amber-600 dark:text-amber-400">${cb.scheduled_at}</td>
          <td class="text-xs text-slate-600 dark:text-slate-400">${cb.reason}</td>
          <td><span class="crm-badge crm-badge-warm">${cb.status}</span></td>
          <td class="text-right">
            <button onclick="App.initiateCall('${cb.phone_number}', '${cb.customer_name}', '${cb.lead_id}')" class="crm-btn crm-btn-success crm-btn-sm text-xs py-1 px-2.5">
              <i data-lucide="phone" class="w-3.5 h-3.5"></i>
              Call
            </button>
          </td>
        </tr>
      `).join('');

      this.refreshIcons();
    } catch (err) {
      console.error('Fetch callbacks error:', err);
    }
  },

  // ---------------------------------------------------------------------------
  // 9. Analytics View Logic
  // ---------------------------------------------------------------------------
  async fetchAnalytics() {
    try {
      const res = await this.authFetch('/api/analytics');
      const data = await res.json();

      document.getElementById('analytics-avg-lat').innerText = `${data.call_analytics?.avg_latency_ms || 420} ms`;
      document.getElementById('analytics-avg-dur').innerText = `${data.call_analytics?.avg_duration_sec || 0} s`;

      const funnelContainer = document.getElementById('analytics-funnel-container');
      if (funnelContainer && data.funnel) {
        const max = Math.max(...data.funnel.map(f => f.count), 1);
        funnelContainer.innerHTML = data.funnel.map(f => {
          const pct = Math.max(Math.round((f.count / max) * 100), 8);
          return `
            <div>
              <div class="flex justify-between text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                <span>${f.stage}</span>
                <span>${f.count}</span>
              </div>
              <div class="h-2.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                <div class="h-full bg-indigo-600 rounded-full" style="width: ${pct}%"></div>
              </div>
            </div>
          `;
        }).join('');
      }

      const locContainer = document.getElementById('analytics-locality-container');
      if (locContainer && data.location_demand) {
        const total = Object.values(data.location_demand).reduce((a, b) => a + b, 0) || 1;
        locContainer.innerHTML = Object.entries(data.location_demand).map(([loc, count]) => {
          const pct = Math.round((count / total) * 100);
          return `
            <div>
              <div class="flex justify-between text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                <span>${loc}</span>
                <span>${count} (${pct}%)</span>
              </div>
              <div class="h-2.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                <div class="h-full bg-emerald-500 rounded-full" style="width: ${pct}%"></div>
              </div>
            </div>
          `;
        }).join('');
      }
    } catch (err) {
      console.error('Fetch analytics error:', err);
    }
  },

  // ---------------------------------------------------------------------------
  // 10. Command Palette (Ctrl + K / ⌘K)
  // ---------------------------------------------------------------------------
  setupKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        this.openCommandPalette();
      }
      if (e.key === 'Escape') {
        this.closeCommandPalette();
        this.closeLeadDrawer();
        document.querySelectorAll('.crm-modal-backdrop.active').forEach(m => m.classList.remove('active'));
      }
    });
  },

  openCommandPalette() {
    const modal = document.getElementById('command-palette-modal');
    const input = document.getElementById('command-palette-input');
    if (modal) modal.classList.add('active');
    if (input) {
      input.value = '';
      input.focus();
    }
    this.handleCommandPaletteSearch('');
  },

  closeCommandPalette(event) {
    if (!event || event.target.id === 'command-palette-modal') {
      document.getElementById('command-palette-modal')?.classList.remove('active');
    }
  },

  handleCommandPaletteSearch(query) {
    const resultsContainer = document.getElementById('command-palette-results');
    if (!resultsContainer) return;

    const q = query.toLowerCase().trim();
    const results = [];

    AppState.leads.forEach(l => {
      if (!q || l.name.toLowerCase().includes(q) || l.phone_number.includes(q) || (l.preferred_location || '').toLowerCase().includes(q)) {
        results.push({
          type: 'Lead',
          title: l.name,
          subtitle: `${l.preferred_location || 'Nagpur'} • ${l.bhk || ''} • ${l.budget_display}`,
          action: () => { this.closeCommandPalette(); this.openLeadDrawer(l.id); }
        });
      }
    });

    AppState.campaigns.forEach(c => {
      if (!q || c.name.toLowerCase().includes(q) || (c.target_locality || '').toLowerCase().includes(q)) {
        results.push({
          type: 'Campaign',
          title: c.name,
          subtitle: `${c.target_locality || 'Nagpur'} • ${c.total_leads || 0} leads • Concurrency: ${c.concurrency}`,
          action: () => { this.closeCommandPalette(); this.navigate('campaigns'); this.openCampaignDetail(c.id); }
        });
      }
    });

    AppState.properties.forEach(p => {
      if (!q || p.project_name.toLowerCase().includes(q) || p.location.toLowerCase().includes(q)) {
        results.push({
          type: 'Property',
          title: p.project_name,
          subtitle: `${p.location} • ${p.bhk} • ${p.price_display}`,
          action: () => { this.closeCommandPalette(); this.navigate('properties'); }
        });
      }
    });

    if (!results.length) {
      resultsContainer.innerHTML = `<div class="p-6 text-center text-xs text-slate-400">No matching records found.</div>`;
      return;
    }

    resultsContainer.innerHTML = results.slice(0, 8).map((r, idx) => `
      <div class="command-result-item" onclick="App.executeCommandResult(${idx})">
        <div>
          <div class="text-xs font-bold text-slate-900 dark:text-white">${r.title}</div>
          <div class="text-[11px] text-slate-500">${r.subtitle}</div>
        </div>
        <span class="text-[10px] font-semibold uppercase px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">${r.type}</span>
      </div>
    `).join('');

    this._paletteResults = results.slice(0, 8);
    this.refreshIcons();
  },

  executeCommandResult(index) {
    if (this._paletteResults && this._paletteResults[index]) {
      this._paletteResults[index].action();
    }
  },

  // ---------------------------------------------------------------------------
  // Modal Helpers & Formatters
  // ---------------------------------------------------------------------------
  openModal(id) {
    document.getElementById(id)?.classList.add('active');
    this.refreshIcons();
  },

  closeModal(id) {
    document.getElementById(id)?.classList.remove('active');
  },

  formatDate(isoStr) {
    if (!isoStr) return '--';
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoStr;
    }
  },

  escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
};

document.addEventListener('DOMContentLoaded', () => {
  window.handleDomainChange = (domId) => App.handleDomainChange(domId);
  App.init();
});
