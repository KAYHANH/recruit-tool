from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import pandas as pd
import streamlit as st

from db import (
    add_job,
    add_or_update_candidate,
    add_search_history,
    create_backup,
    delete_candidate,
    delete_job,
    get_candidate,
    get_dashboard_metrics,
    get_job,
    get_search_history,
    init_db,
    is_query_repeated,
    list_candidates,
    list_jobs,
    list_shortlisted_candidates,
    remove_from_shortlist,
    restore_database,
    update_candidate_status,
    update_job,
)
from jd_parser import (
    DocumentParsingError,
    ScannedOrEmptyPdfError,
    clean_text,
    parse_document,
)
from keyword_extractor import JobRequirements, extract_requirements
from matcher import (
    CandidateEvaluation,
    CriterionMatch,
    ScoringWeights,
    evaluate_candidate,
    sanitize_csv_cell,
    sanitize_dataframe_for_csv,
)
from groq_extractor import (
    DEFAULT_GROQ_MODEL,
    extract_requirements_with_groq,
    get_groq_api_key,
    get_groq_model,
    resolve_groq_api_key,
    run_groq_live_smoke_test,
)
from query_generator import SearchQuery, generate_search_queries
from search_provider import (
    GitHubCandidateResult,
    GitHubSearchProvider,
    LocalFallbackProvider,
    get_search_provider,
)
from title_extractor import TitleExtractionResult, extract_job_title

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "candidate_sourcing.db"

st.set_page_config(
    page_title="Candidate Finder — Recruiter Workspace",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject refined, professional recruiter CSS
st.markdown(
    """
    <style>
    /* Clean layout & typography */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2.5rem;
        max-width: 1280px;
    }
    /* Metric card styling */
    div[data-testid="stMetric"] {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 12px 18px;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
    }
    div[data-testid="stMetric"] label {
        color: #475569 !important;
        font-weight: 500;
        font-size: 0.88rem;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #0F172A !important;
        font-weight: 700;
        font-size: 1.6rem;
    }
    /* Section headers */
    .section-header {
        font-size: 1.4rem;
        font-weight: 700;
        color: #0F172A;
        margin-bottom: 0.25rem;
    }
    .section-caption {
        color: #64748B;
        font-size: 0.92rem;
        margin-bottom: 1.25rem;
    }
    /* Primary buttons */
    button[kind="primary"] {
        background-color: #1E3A8A !important;
        border-color: #1E3A8A !important;
        color: #FFFFFF !important;
        font-weight: 600;
    }
    /* Status badges */
    .badge-new { background-color: #EFF6FF; color: #1D4ED8; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.8rem; }
    .badge-review { background-color: #FEF9C3; color: #854D0E; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.8rem; }
    .badge-shortlist { background-color: #DCFCE7; color: #15803D; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.8rem; }
    .badge-archived { background-color: #F1F5F9; color: #475569; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Connect to database and run safe migrations
conn = init_db(DB_PATH)

# Initialize navigation session state
NAV_PAGES = [
    "Overview",
    "JD Analyzer",
    "Find Candidates",
    "Candidates",
    "Shortlist",
    "Saved Jobs & Data",
    "Settings",
]

if "nav_page" not in st.session_state:
    st.session_state["nav_page"] = "Overview"

# --- Sidebar Navigation ---
with st.sidebar:
    st.markdown("### 🔎 **Candidate Finder**")
    st.caption("Personal Recruitment Workspace · Strict ₹0 Budget")
    st.divider()

    selected_nav = st.radio(
        "Navigation",
        NAV_PAGES,
        index=NAV_PAGES.index(st.session_state["nav_page"]) if st.session_state["nav_page"] in NAV_PAGES else 0,
        key="sidebar_nav_radio",
    )
    if selected_nav != st.session_state["nav_page"]:
        st.session_state["nav_page"] = selected_nav
        st.rerun()

    st.divider()

    # Active Job quick-context selector
    all_jobs = list_jobs(conn)
    job_options = {f"#{j['id']} · {j['title']}": j["id"] for j in all_jobs}
    current_active_id = st.session_state.get("active_job_id")

    if job_options:
        default_idx = 0
        if current_active_id:
            for idx, (label, jid) in enumerate(job_options.items()):
                if jid == current_active_id:
                    default_idx = idx
                    break
        chosen_job_label = st.selectbox(
            "Active Target Job:",
            options=list(job_options.keys()),
            index=default_idx,
            key="sidebar_active_job_select",
        )
        st.session_state["active_job_id"] = job_options[chosen_job_label]
    else:
        st.caption("No jobs saved yet. Create your first job in **JD Analyzer**.")

    st.divider()
    metrics = get_dashboard_metrics(conn)
    st.markdown(
        f"**Database Status**\n"
        f"- 💼 Jobs: **{metrics['total_jobs']}**\n"
        f"- 👥 Candidates: **{metrics['total_candidates']}**\n"
        f"- ⭐ Shortlisted: **{metrics['shortlisted']}**"
    )
    st.caption("🔒 **Local-first guarantee:** All candidate records, notes, and searches stay 100% on this computer in SQLite.")


# ==============================================================================
# SECTION 1: OVERVIEW DASHBOARD
# ==============================================================================
if st.session_state["nav_page"] == "Overview":
    st.markdown('<div class="section-header">Recruitment Overview</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-caption">Pipeline summary, recent activity, and quick actions</div>', unsafe_allow_html=True)

    metrics = get_dashboard_metrics(conn)

    # 4 Key Dashboard Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Saved Jobs", metrics["total_jobs"], help="Total job specifications saved locally.")
    m2.metric("Total Candidates", metrics["total_candidates"], help="Unique candidates in your local database.")
    m3.metric("Needing Review", metrics["needing_review"], help="Candidates with status 'New' or 'Under Review'.")
    m4.metric("Shortlisted", metrics["shortlisted"], help="Candidates approved for interview or client presentation.")

    st.write("")
    # Quick Primary Actions
    col_act1, col_act2, col_act3 = st.columns([1.5, 2, 2.5])
    with col_act1:
        if st.button("➕ Analyze New JD", type="primary", use_container_width=True):
            st.session_state["nav_page"] = "JD Analyzer"
            st.session_state["loaded_job_id"] = None
            st.rerun()
    with col_act2:
        if metrics["total_jobs"] > 0:
            if st.button("🔎 Find Candidates for Active Job", use_container_width=True):
                st.session_state["nav_page"] = "Find Candidates"
                st.rerun()
    with col_act3:
        if metrics["shortlisted"] > 0:
            if st.button("⭐ View Shortlisted Candidates", use_container_width=True):
                st.session_state["nav_page"] = "Shortlist"
                st.rerun()

    st.divider()

    # Empty State Guide
    if metrics["total_jobs"] == 0:
        st.info(
            "👋 **Welcome to Candidate Finder!**\n\n"
            "You haven't added any job descriptions yet. Start by analyzing a job description (PDF, DOCX, TXT, or pasted text) "
            "to extract requirements and generate tailored Google and Bing X-Ray search links."
        )
        if st.button("🚀 Get Started: Analyze First Job", type="primary"):
            st.session_state["nav_page"] = "JD Analyzer"
            st.rerun()
    else:
        # Recent activity split view
        c_left, c_right = st.columns([3, 2])
        with c_left:
            st.markdown("#### Recent Jobs")
            recent_jobs = metrics["recent_jobs"]
            job_rows = []
            for j in recent_jobs:
                cands_count = len(list_candidates(conn, job_id=j["id"]))
                job_rows.append({
                    "Job ID": f"#{j['id']}",
                    "Title": j["title"],
                    "Location": j["location"] or "Unspecified",
                    "Created": j["created_at"][:10],
                    "Candidates": cands_count,
                })
            df_jobs = pd.DataFrame(job_rows)
            st.dataframe(df_jobs, use_container_width=True, hide_index=True)

        with c_right:
            st.markdown("#### Recent Sourcing Activity")
            recent_cands = metrics["recent_candidates"]
            if recent_cands:
                cand_rows = []
                for c in recent_cands:
                    cand_rows.append({
                        "Name": c["name"],
                        "Headline": c["headline"][:40] if c["headline"] else "-",
                        "Source": c["source"] or "Manual",
                        "Status": c["status"] or "New",
                    })
                st.dataframe(pd.DataFrame(cand_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("No candidates sourced yet. Use **Find Candidates** to discover talent.")


# ==============================================================================
# SECTION 2: JD ANALYZER — A GUIDED WORKFLOW
# ==============================================================================
elif st.session_state["nav_page"] == "JD Analyzer":
    st.markdown('<div class="section-header">Job Description Analyzer</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-caption">Guided 4-step workflow to extract requirements and configure sourcing queries</div>', unsafe_allow_html=True)

    if "job_save_flash" in st.session_state:
        st.success(st.session_state.pop("job_save_flash"))

    # STEP 1: Select or Create Job
    st.markdown("### Step 1 — Select or Create a Job")
    jobs = list_jobs(conn)
    existing_options = {f"#{j['id']} · {j['title']} ({j['created_at'][:10]})": j["id"] for j in jobs}
    load_choice = st.selectbox(
        "Choose an existing job to review or start fresh:",
        ["— Create New Job —", *existing_options.keys()],
        index=0 if not st.session_state.get("active_job_id") else (
            list(existing_options.values()).index(st.session_state["active_job_id"]) + 1
            if st.session_state["active_job_id"] in existing_options.values() else 0
        ),
        key="jd_analyzer_job_choice",
    )

    loaded_job = None
    if load_choice != "— Create New Job —":
        loaded_id = existing_options[load_choice]
        loaded_job = get_job(conn, loaded_id)
        st.session_state["active_job_id"] = loaded_id

    # File uploader and text area
    col_u1, col_u2 = st.columns([1, 1])
    with col_u1:
        uploaded_jd = st.file_uploader(
            "Upload Job Description (PDF, DOCX, TXT, MD):",
            type=["pdf", "docx", "txt", "md"],
            key="jd_analyzer_file",
            help="Extracts clean text from uploaded document. For scanned/image PDFs, paste text directly.",
        )
    with col_u2:
        default_paste = loaded_job["jd_text"] if loaded_job else ""
        pasted_jd = st.text_area(
            "Or Paste JD Text Directly:",
            value=default_paste,
            height=140,
            key="jd_analyzer_paste",
            placeholder="Paste complete role overview, responsibilities, and requirements here...",
        )

    # Document parsing logic
    raw_jd_text = ""
    if uploaded_jd:
        try:
            raw_jd_text = parse_document(uploaded_jd.getvalue(), uploaded_jd.name)
            st.caption(f"📄 Loaded `{uploaded_jd.name}` ({len(raw_jd_text)} characters parsed successfully)")
        except (ScannedOrEmptyPdfError, DocumentParsingError) as err:
            st.error(f"Document parsing error: {err}")
            raw_jd_text = ""
    elif pasted_jd.strip():
        raw_jd_text = clean_text(pasted_jd)
    elif loaded_job:
        raw_jd_text = loaded_job["jd_text"]

    st.divider()

    # STEP 2: Choose Extraction Engine
    st.markdown("### Step 2 — Choose Extraction Engine")
    active_groq_model = get_groq_model()
    detected_key = resolve_groq_api_key()

    engine_mode = st.radio(
        "Select Extraction Method:",
        [
            "Local Offline Extractor (Rule-based, 100% Free & Private — Default)",
            f"Groq AI-Assisted Extraction (Free Tier Only · {active_groq_model})",
        ],
        index=0,
        key="jd_engine_choice",
        help="Local extractor runs on CPU with zero telemetry. Groq AI provides high-speed cloud parsing for complex JDs.",
    )

    groq_override_key = None
    if "Groq" not in engine_mode:
        st.info("🔒 **Local Mode Active**: Requirements are extracted locally on your machine with zero external network requests.")
    else:
        st.info(
            f"🌐 **External AI Notice**: Only the sanitized Job Description text is sent to the Groq API (`{active_groq_model}`) "
            "for structured inference. Candidate records, CVs, recruiter notes, and database contents are NEVER transmitted. "
            "If Groq connectivity fails, the app falls back to local offline extraction."
        )
        col_g1, col_g2 = st.columns([3, 2])
        with col_g1:
            if detected_key:
                st.caption("✅ Groq API key detected from project `.env` or system environment.")
                session_key = st.text_input(
                    "Session API Key Override (optional):",
                    value="",
                    type="password",
                    key="groq_session_key_override",
                    help="Leave blank to use GROQ_API_KEY from project .env. Never pre-fills or exposes your key.",
                )
                groq_override_key = session_key.strip() if session_key.strip() else None
            else:
                session_key = st.text_input(
                    "Session Groq API Key (optional):",
                    value="",
                    type="password",
                    key="groq_session_key_override",
                    help="Enter a key for this session or add GROQ_API_KEY to project .env.",
                )
                groq_override_key = session_key.strip() if session_key.strip() else None
                st.caption("ℹ️ No Groq API key configured in project .env. Local offline extraction remains ready and 100% free.")

        with col_g2:
            st.write("")
            st.write("")
            if st.button("⚡ Test Groq Connection", key="btn_jd_test_groq"):
                with st.spinner("Testing Groq connectivity..."):
                    test_res = run_groq_live_smoke_test(api_key=groq_override_key, model=active_groq_model)
                    if test_res["success"]:
                        st.success(f"✅ {test_res['message']}")
                    else:
                        st.warning(f"⚠️ {test_res['message']} (Category: {test_res['status_category']})")

    analyze_clicked = st.button("🔍 Parse & Analyze Job Description", type="primary")

    # Perform analysis or load existing extracted data
    extracted_reqs: JobRequirements | None = None
    title_res: TitleExtractionResult | None = None

    if analyze_clicked and raw_jd_text:
        st.session_state["active_jd_text"] = raw_jd_text
        if "Groq" in engine_mode:
            with st.spinner(f"Extracting requirements via Groq AI ({active_groq_model})..."):
                ok, g_reqs, g_msg = extract_requirements_with_groq(raw_jd_text, api_key=groq_override_key, model=active_groq_model)
                if ok and g_reqs:
                    st.success(f"✅ {g_msg}")
                    extracted_reqs = g_reqs
                    title_res = TitleExtractionResult(
                        title=g_reqs.job_title,
                        alternative_titles=g_reqs.alternative_titles,
                        confidence_score=0.98,
                        confidence_level="High",
                        detected_candidates=[g_reqs.job_title] + g_reqs.alternative_titles,
                    )
                else:
                    st.warning(f"⚠️ {g_msg}\nUsing local offline extractor instead.")
                    extracted_reqs = extract_requirements(raw_jd_text)
                    title_res = extract_job_title(raw_jd_text)
        else:
            with st.spinner("Extracting requirements locally..."):
                extracted_reqs = extract_requirements(raw_jd_text)
                title_res = extract_job_title(raw_jd_text)

        st.session_state["current_extracted_reqs"] = extracted_reqs
        st.session_state["current_title_res"] = title_res

    elif loaded_job and not analyze_clicked:
        if loaded_job["extracted_data"]:
            try:
                extracted_reqs = JobRequirements.from_dict(json.loads(loaded_job["extracted_data"]))
                title_res = TitleExtractionResult(
                    title=extracted_reqs.job_title,
                    alternative_titles=extracted_reqs.alternative_titles,
                    confidence_score=0.95,
                    confidence_level="High",
                    detected_candidates=[extracted_reqs.job_title] + extracted_reqs.alternative_titles,
                )
            except Exception:
                extracted_reqs = extract_requirements(loaded_job["jd_text"])
                title_res = extract_job_title(loaded_job["jd_text"])
        else:
            extracted_reqs = extract_requirements(loaded_job["jd_text"])
            title_res = extract_job_title(loaded_job["jd_text"])
        st.session_state["current_extracted_reqs"] = extracted_reqs
        st.session_state["current_title_res"] = title_res
    else:
        extracted_reqs = st.session_state.get("current_extracted_reqs")
        title_res = st.session_state.get("current_title_res")

    st.divider()

    # STEP 3: Review Extracted Requirements
    st.markdown("### Step 3 — Review & Edit Extracted Requirements")
    if not extracted_reqs:
        st.caption("Extracted role requirements will appear here once analysis runs. Select a saved job or click 'Parse & Analyze Job Description'.")
    else:
        # Grouped into 3 clean subsections
        with st.expander("💼 Role Details", expanded=True):
            r_col1, r_col2 = st.columns(2)
            with r_col1:
                edit_title = st.text_input("Primary Job Title:", value=extracted_reqs.job_title)
                edit_alts = st.text_input("Alternative Job Titles (comma-separated):", value=", ".join(extracted_reqs.alternative_titles))
                edit_emp_type = st.text_input("Employment Type:", value=extracted_reqs.employment_type or "Full-time")
            with r_col2:
                edit_exp = st.text_input("Experience Level:", value=extracted_reqs.experience_level or "Not specified")
                edit_loc = st.text_input("Target Location / Work Arrangement:", value=extracted_reqs.location or "Remote")
                edit_portfolio = st.checkbox("Portfolio / Work Samples Explicitly Required", value=extracted_reqs.portfolio_required)

        with st.expander("🛠️ Skills and Qualifications", expanded=True):
            s_col1, s_col2 = st.columns(2)
            with s_col1:
                edit_req_skills = st.text_area("Required Core Skills (comma-separated):", value=", ".join(extracted_reqs.required_skills), height=90)
                edit_tools = st.text_area("Tools & Technology Platforms (comma-separated):", value=", ".join(extracted_reqs.tools_and_tech), height=90)
            with s_col2:
                edit_pref_skills = st.text_area("Preferred / Bonus Skills (comma-separated):", value=", ".join(extracted_reqs.preferred_skills), height=90)
                edit_edu = st.text_input("Education & Certifications:", value=", ".join(extracted_reqs.education_or_certifications))
                edit_constraints = st.text_input("Mandatory Constraints:", value=", ".join(extracted_reqs.qualifications[:3]))

        with st.expander("🔍 Evidence & Confidence", expanded=False):
            if title_res:
                st.write(f"**Title Extraction Confidence:** {title_res.confidence_level} ({round(title_res.confidence_score * 100)}%)")
            st.caption("ℹ️ Confidence indicators are heuristic estimates based on JD formatting. Manual recruiter review is always recommended.")

        # Recruiter actions: Save, Reset, Continue
        act_col1, act_col2, act_col3 = st.columns([1.5, 1.5, 2])
        with act_col1:
            if st.button("💾 Save Job Requirements", type="primary", use_container_width=True):
                reviewed_reqs = JobRequirements(
                    job_title=edit_title.strip(),
                    alternative_titles=[t.strip() for t in edit_alts.split(",") if t.strip()],
                    required_skills=[s.strip() for s in edit_req_skills.split(",") if s.strip()],
                    preferred_skills=[s.strip() for s in edit_pref_skills.split(",") if s.strip()],
                    tools_and_tech=[t.strip() for t in edit_tools.split(",") if t.strip()],
                    qualifications=[q.strip() for q in edit_constraints.split(",") if q.strip()],
                    education_or_certifications=[e.strip() for e in edit_edu.split(",") if e.strip()],
                    experience_level=edit_exp.strip(),
                    location=edit_loc.strip(),
                    employment_type=edit_emp_type.strip(),
                    portfolio_required=edit_portfolio,
                )
                reqs_json = json.dumps(reviewed_reqs.to_dict())
                if loaded_job:
                    update_job(conn, loaded_job["id"], title=edit_title, extracted_data=reqs_json, location=edit_loc)
                    st.session_state["job_save_flash"] = f"Job #{loaded_job['id']} '{edit_title}' updated successfully!"
                else:
                    new_id = add_job(conn, title=edit_title, jd_text=raw_jd_text or edit_title, extracted_data=reqs_json, location=edit_loc)
                    st.session_state["active_job_id"] = new_id
                    st.session_state["job_save_flash"] = f"Job #{new_id} '{edit_title}' saved successfully!"
                st.rerun()

        with act_col2:
            if st.button("🔄 Reset Edits", use_container_width=True):
                st.session_state["current_extracted_reqs"] = None
                st.rerun()

        with act_col3:
            if st.button("➡️ Continue to Candidate Search", use_container_width=True):
                st.session_state["nav_page"] = "Find Candidates"
                st.rerun()

        st.divider()

        # STEP 4: Search Preview
        st.markdown("### Step 4 — Search Preview")
        st.markdown(
            f"**Target Role:** `{edit_title}` | **Location:** `{edit_loc}`\n\n"
            f"**Core Must-Haves:** {', '.join([s.strip() for s in edit_req_skills.split(',') if s.strip()][:5]) or 'None'}\n\n"
            f"**Selected Provider:** `GitHub Public API (Zero Cost)` + `Manual Google/Bing X-Ray Links`"
        )
        if st.button("🔎 Open Sourcing Workspace in 'Find Candidates'", type="primary"):
            st.session_state["nav_page"] = "Find Candidates"
            st.rerun()


# ==============================================================================
# SECTION 3: FIND CANDIDATES — SOURCING WORKSPACE
# ==============================================================================
elif st.session_state["nav_page"] == "Find Candidates":
    st.markdown('<div class="section-header">Find Candidates</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-caption">Discover candidates using official free endpoints and role-specific X-Ray links</div>', unsafe_allow_html=True)

    jobs = list_jobs(conn)
    if not jobs:
        st.info("ℹ️ No saved jobs found. Analyze and save a job first in **JD Analyzer**.")
    else:
        job_map = {f"#{j['id']} · {j['title']}": j for j in jobs}
        active_id = st.session_state.get("active_job_id")
        def_idx = 0
        if active_id:
            for idx, (label, j) in enumerate(job_map.items()):
                if j["id"] == active_id:
                    def_idx = idx
                    break

        selected_job_label = st.selectbox("Select Target Job:", list(job_map.keys()), index=def_idx)
        selected_job = job_map[selected_job_label]
        st.session_state["active_job_id"] = selected_job["id"]

        # Parse requirements
        if selected_job["extracted_data"]:
            try:
                target_reqs = JobRequirements.from_dict(json.loads(selected_job["extracted_data"]))
            except Exception:
                target_reqs = extract_requirements(selected_job["jd_text"])
        else:
            target_reqs = extract_requirements(selected_job["jd_text"])

        # Compact requirements summary banner
        st.info(
            f"🎯 **Target Job:** **{target_reqs.job_title}** | **Location:** {target_reqs.location or 'Remote'}\n\n"
            f"**Required Skills:** {', '.join(target_reqs.required_skills) if target_reqs.required_skills else 'None extracted'}\n\n"
            f"**Tools & Tech:** {', '.join(target_reqs.tools_and_tech) if target_reqs.tools_and_tech else 'None'}"
        )

        # Tabbed Sourcing Modes
        tab_gh, tab_xray, tab_intake = st.tabs([
            "⚡ Automated Free Search (GitHub Public API)",
            "🌐 Manual Google & Bing X-Ray Search",
            "📥 Quick Profile & CV Intake",
        ])

        # ----------------------------------------------------------------------
        # Tab 1: GitHub Public API
        # ----------------------------------------------------------------------
        with tab_gh:
            st.markdown("#### Official Public GitHub Candidate Search")
            st.caption(
                "Searches public developer profiles via the official GitHub REST API. "
                "Strictly ₹0 spend — no paid APIs, no subscriptions, stops gracefully at public rate limits."
            )

            gh_provider = GitHubSearchProvider()
            gh_limits = gh_provider.check_rate_limit()

            col_rl1, col_rl2 = st.columns([3, 2])
            with col_rl1:
                if gh_limits.get("success"):
                    st.caption(
                        f"📊 **GitHub Rate Limit:** Core: **{gh_limits['core_remaining']}/{gh_limits['core_limit']}** remaining "
                        f"(resets {gh_limits['core_reset']}) | Search: **{gh_limits['search_remaining']}/{gh_limits['search_limit']}** "
                        f"(resets {gh_limits['search_reset']})"
                    )
                else:
                    st.caption(f"⚠️ Rate limit status unavailable: {gh_limits.get('error', 'Network error')}")
            with col_rl2:
                if gh_limits.get("authenticated"):
                    st.caption("🔒 Authenticated via personal `GITHUB_TOKEN` from `.env`.")
                else:
                    st.caption("ℹ️ Unauthenticated public mode (60 requests/hr, 10 searches/min).")

            default_gh_kw = " ".join(target_reqs.required_skills[:3]) if target_reqs.required_skills else target_reqs.job_title
            col_gq1, col_gq2, col_gq3 = st.columns([3, 2, 1])
            with col_gq1:
                gh_keywords = st.text_input("Keywords to search in GitHub public profiles:", value=default_gh_kw)
            with col_gq2:
                gh_loc = st.text_input("Location filter (optional):", value=target_reqs.location)
            with col_gq3:
                gh_limit = st.selectbox("Max profiles:", [3, 5, 10], index=1)

            search_gh_btn = st.button("🚀 Search Public GitHub Profiles", type="primary")

            if search_gh_btn:
                with st.spinner("Querying official GitHub public user search API..."):
                    gh_result = gh_provider.search_candidates(
                        keywords=gh_keywords,
                        location=gh_loc,
                        num_results=gh_limit,
                    )
                    st.session_state["last_gh_result"] = gh_result

            saved_gh = st.session_state.get("last_gh_result")
            if saved_gh:
                if saved_gh.rate_limited:
                    st.warning(f"⚠️ {saved_gh.message}")
                else:
                    st.success(f"✅ {saved_gh.message}")

                if saved_gh.candidates:
                    st.markdown("##### Retrieved Candidate Profiles (Review & Save)")
                    st.caption(
                        "⚠️ **Notice:** These are genuine candidate profiles returned by the GitHub API. "
                        "Missing email/phone are labeled 'Not found'. No paid enrichment or fabricated emails are used."
                    )

                    for idx, c in enumerate(saved_gh.candidates):
                        with st.expander(f"👤 {c['name']} — {c['headline'][:60]}", expanded=(idx < 2)):
                            ev_col1, ev_col2 = st.columns([2, 1])
                            with ev_col1:
                                st.write(f"**Profile URL:** [{c['profile_url']}]({c['profile_url']})")
                                if c['portfolio_url']:
                                    st.write(f"**Website / Portfolio:** [{c['portfolio_url']}]({c['portfolio_url']})")
                                st.write(f"**Location:** {c['location'] or 'Not specified'}")
                                st.write(f"**Company:** {c['company'] or 'Not specified'}")
                                
                                # Contact Provenance Display
                                if c['email']:
                                    st.write(f"📧 **Public Email:** `{c['email']}`")
                                    st.caption(f"Provenance: {c['contact_provenance']}")
                                else:
                                    st.write("📧 **Public Email:** *Not found*")
                                    st.caption("ℹ️ Email is not publicly published on candidate's GitHub profile.")
                                st.write("📞 **Phone:** *Not found* (GitHub does not support phone numbers)")

                            with ev_col2:
                                # Real-time match score against job
                                c_eval = evaluate_candidate(c, target_reqs, target_location=target_reqs.location)
                                st.metric("Match Score", f"{c_eval.total_score} / 100")
                                st.write(f"**Coverage:** {c_eval.evidence_coverage_pct}%")
                                st.write(f"**Confidence:** {c_eval.confidence}")

                                if st.button(f"💾 Save {c['name']} to Job", key=f"btn_save_gh_{idx}"):
                                    ok, msg, cid = add_or_update_candidate(conn, c, job_id=selected_job["id"])
                                    if ok:
                                        st.success(f"Saved {c['name']} to Job #{selected_job['id']}!")
                                    else:
                                        st.error(f"Error: {msg}")

        # ----------------------------------------------------------------------
        # Tab 2: Manual Google & Bing X-Ray Search Links
        # ----------------------------------------------------------------------
        with tab_xray:
            st.markdown("#### Role-Specific Google & Bing X-Ray Search Links")
            st.caption(
                "Generates high-precision Boolean search links. Open them directly in your browser. "
                "No automated scraping of Google/Bing search results is performed. Respects all provider terms."
            )

            generated_queries = generate_search_queries(target_reqs, user_location=target_reqs.location)
            st.write(f"Generated **{len(generated_queries)}** varied search strategies for **{target_reqs.job_title}**.")

            # Organize queries into purpose-driven expanders
            for q in generated_queries:
                with st.expander(f"📌 {q.label} ({q.strategy})", expanded=False):
                    st.write(f"**Description:** {q.description}")
                    
                    # Editable query text
                    edited_q = st.text_input(
                        "Search Query:",
                        value=q.query_text,
                        key=f"edit_q_{selected_job['id']}_{q.id}",
                    )
                    
                    encoded_q = quote_plus(edited_q)
                    google_link = f"https://www.google.com/search?q={encoded_q}"
                    bing_link = f"https://www.bing.com/search?q={encoded_q}"

                    # Check repeated query execution
                    is_rep, rep_time = is_query_repeated(conn, selected_job["id"], edited_q)
                    if is_rep:
                        st.caption(f"ℹ️ Previously opened on {rep_time[:16]}")

                    b_c1, b_c2, b_c3 = st.columns([1.5, 1.5, 3])
                    with b_c1:
                        st.link_button("🌐 Open Google Search", google_link, use_container_width=True)
                    with b_c2:
                        st.link_button("🌐 Open Bing Search", bing_link, use_container_width=True)
                    with b_c3:
                        if st.button("📝 Log Query Execution", key=f"btn_log_{selected_job['id']}_{q.id}"):
                            add_search_history(
                                conn,
                                job_id=selected_job["id"],
                                query_text=edited_q,
                                strategy=q.strategy,
                                provider="Browser (Google/Bing)",
                                status="Opened in Browser",
                            )
                            st.success("Search logged to job history.")

        # ----------------------------------------------------------------------
        # Tab 3: Quick Profile & CV Intake
        # ----------------------------------------------------------------------
        with tab_intake:
            st.markdown("#### Quick Candidate Profile Intake")
            st.caption("Paste public profile URLs (LinkedIn, GitHub, portfolio, personal sites) and text/CV to evaluate and save.")

            with st.form("quick_intake_form"):
                ic1, ic2 = st.columns(2)
                with ic1:
                    i_name = st.text_input("Candidate Full Name *", placeholder="e.g. Jane Doe")
                    i_url = st.text_input("Public Profile / Portfolio URL", placeholder="https://linkedin.com/in/... or github.com/...")
                    i_headline = st.text_input("Headline / Current Role", placeholder="e.g. Senior Data Scientist | Python, ML")
                    i_company = st.text_input("Current Company", placeholder="e.g. Acme Analytics")
                    i_location = st.text_input("Location", placeholder="e.g. London, UK")
                with ic2:
                    i_email = st.text_input("Public Professional Email (optional)", placeholder="name@company.com")
                    i_phone = st.text_input("Public Professional Phone (optional)", placeholder="+44 20 ...")
                    i_status = st.selectbox("Candidate Status", ["New", "Under Review", "Shortlisted", "Archived"])
                    i_source = st.selectbox(
                        "Information Source",
                        ["Manually reviewed public profile", "Candidate-provided CV", "Direct Referral", "Public portfolio site"],
                    )

                i_evidence = st.text_area(
                    "Profile / CV Text Evidence *",
                    height=140,
                    placeholder="Paste candidate work history, skills, projects, and summary here...",
                    help="Used for transparent evidence-based heuristic matching against the active job.",
                )
                i_notes = st.text_area("Recruiter Notes (optional)", height=80, placeholder="Interview impressions, availability...")

                submit_intake = st.form_submit_button("Save Candidate to Job", type="primary")

            if submit_intake:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                prov = f"Manual intake from {i_source} ({i_url or 'CV/Text'}) [Added {now_str}]"
                contact_st = "Publicly provided" if (i_email or i_phone) else "Not found"

                candidate_payload = {
                    "name": i_name,
                    "profile_url": i_url,
                    "github_url": i_url if "github.com" in i_url.lower() else "",
                    "portfolio_url": i_url if "github.com" not in i_url.lower() and "linkedin.com" not in i_url.lower() else "",
                    "headline": i_headline,
                    "company": i_company,
                    "location": i_location,
                    "email": i_email,
                    "phone": i_phone,
                    "contact_provenance": prov,
                    "contact_status": contact_st,
                    "evidence_text": i_evidence,
                    "notes": i_notes,
                    "source": i_source,
                    "status": i_status,
                }
                ok, msg, cid = add_or_update_candidate(conn, candidate_payload, job_id=selected_job["id"])
                if ok:
                    st.success(f"✅ {msg} (ID: #{cid})")
                else:
                    st.error(f"❌ {msg}")


# ==============================================================================
# SECTION 4: CANDIDATES — DIRECTORY & DEEP REVIEW
# ==============================================================================
elif st.session_state["nav_page"] == "Candidates":
    st.markdown('<div class="section-header">Candidate Directory & Evaluation</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-caption">Inspect candidate profiles, matched evidence, missing criteria, and contact provenance</div>', unsafe_allow_html=True)

    all_jobs = list_jobs(conn)
    job_filter_map = {"All Saved Jobs": None}
    for j in all_jobs:
        job_filter_map[f"#{j['id']} · {j['title']}"] = j["id"]

    f_col1, f_col2, f_col3 = st.columns([2, 1.5, 1.5])
    with f_col1:
        chosen_job_filter = st.selectbox("Filter by Associated Job:", list(job_filter_map.keys()))
    with f_col2:
        chosen_status_filter = st.selectbox("Filter by Status:", ["All Statuses", "New", "Under Review", "Shortlisted", "Archived"])
    with f_col3:
        score_threshold = st.slider("Minimum Match Score:", 0, 100, 0)

    selected_filter_job_id = job_filter_map[chosen_job_filter]
    cands_list = list_candidates(conn, job_id=selected_filter_job_id)

    # Determine reference job requirements for scoring
    reference_job = get_job(conn, selected_filter_job_id) if selected_filter_job_id else (all_jobs[0] if all_jobs else None)
    if reference_job and reference_job["extracted_data"]:
        try:
            ref_reqs = JobRequirements.from_dict(json.loads(reference_job["extracted_data"]))
        except Exception:
            ref_reqs = extract_requirements(reference_job["jd_text"])
    elif reference_job:
        ref_reqs = extract_requirements(reference_job["jd_text"])
    else:
        ref_reqs = JobRequirements(job_title="General Role")

    if not cands_list:
        st.info("No candidates found matching the selected filter.")
    else:
        # Evaluate all candidates against reference job
        evaluated_cands = []
        for c in cands_list:
            c_dict = dict(c)
            if chosen_status_filter != "All Statuses" and c_dict.get("status") != chosen_status_filter:
                continue
            ev = evaluate_candidate(c_dict, ref_reqs, target_location=ref_reqs.location)
            if ev.total_score >= score_threshold:
                evaluated_cands.append((c_dict, ev))

        # Sort descending by match score
        evaluated_cands.sort(key=lambda x: x[1].total_score, reverse=True)

        st.write(f"Showing **{len(evaluated_cands)}** candidates matching criteria:")

        # Summary table
        cand_table_data = []
        for c_dict, ev in evaluated_cands:
            cand_table_data.append({
                "ID": c_dict["id"],
                "Name": c_dict["name"],
                "Role / Headline": c_dict.get("headline") or "-",
                "Company": c_dict.get("company") or "-",
                "Location": c_dict.get("location") or "-",
                "Match Score": f"{ev.total_score}/100",
                "Confidence": ev.confidence,
                "Status": c_dict.get("status") or "New",
                "Email": c_dict.get("email") or "Not found",
                "Phone": c_dict.get("phone") or "Not found",
                "Profile URL": c_dict.get("profile_url") or "",
            })

        df_cands = pd.DataFrame(cand_table_data)
        st.dataframe(
            df_cands,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Profile URL": st.column_config.LinkColumn("Profile URL"),
            },
        )

        st.divider()

        # Detailed Candidate Inspector
        st.markdown("### 🔎 Detailed Evidence & Contact Inspector")
        inspect_options = {f"#{c['id']} · {c['name']} ({ev.total_score}/100)": c["id"] for c, ev in evaluated_cands}
        chosen_inspect_label = st.selectbox("Select candidate to inspect full itemized criteria:", list(inspect_options.keys()))
        inspected_cid = inspect_options[chosen_inspect_label]

        sel_cand, sel_eval = next((c, ev) for c, ev in evaluated_cands if c["id"] == inspected_cid)

        col_det1, col_det2 = st.columns([1, 2])
        with col_det1:
            st.metric("Match Score", f"{sel_eval.total_score} / 100")
            st.metric("Credible Score", f"{sel_eval.confidence_adjusted_score} / 100")
            st.write(f"**Evidence Confidence:** {sel_eval.confidence} ({sel_eval.word_count} words)")
            st.write(f"**Criteria Coverage:** {sel_eval.evidence_coverage_pct}%")
            
            # Contact Details & Provenance
            st.markdown("#### Contact Information")
            st.write(f"📧 **Email:** {sel_cand.get('email') or '*Not found*'}")
            st.write(f"📞 **Phone:** {sel_cand.get('phone') or '*Not found*'}")
            st.caption(f"**Provenance:** {sel_cand.get('contact_provenance') or 'No provenance recorded'}")
            st.caption("ℹ️ Missing contacts remain blank. Never guessed or fabricated.")

            # Status and Shortlist Controls
            st.markdown("#### Recruiter Status")
            current_status = sel_cand.get("status", "New")
            new_st = st.selectbox(
                "Update Status:",
                ["New", "Under Review", "Shortlisted", "Archived"],
                index=["New", "Under Review", "Shortlisted", "Archived"].index(current_status) if current_status in ["New", "Under Review", "Shortlisted", "Archived"] else 0,
                key=f"cand_status_sel_{inspected_cid}",
            )
            if st.button("Apply Status", key=f"btn_apply_st_{inspected_cid}"):
                update_candidate_status(conn, inspected_cid, new_st)
                st.success(f"Updated status for #{inspected_cid} to {new_st}!")
                st.rerun()

        with col_det2:
            st.markdown("#### Itemized Requirements Breakdown")
            crit_rows = []
            for cm in sel_eval.criteria_matches:
                badge = (
                    "🟢 Matched" if cm.status == "Matched"
                    else "🟡 Needs review" if cm.status == "Needs review"
                    else "🔴 Contradictory" if cm.status == "Contradictory"
                    else "⚪ Not found"
                )
                crit_rows.append({
                    "Requirement": cm.requirement,
                    "Category": cm.category,
                    "Status": badge,
                    "Evidence Snippet": cm.evidence_snippet or "(None observed)",
                })
            st.dataframe(pd.DataFrame(crit_rows), use_container_width=True, hide_index=True)

            with st.expander("📄 Raw Profile Evidence Text", expanded=False):
                st.text_area("Evidence Text", value=sel_cand.get("evidence_text", ""), height=150, disabled=True)
                if sel_cand.get("notes"):
                    st.info(f"**Recruiter Notes:** {sel_cand['notes']}")


# ==============================================================================
# SECTION 5: SHORTLIST — TALENT PIPELINE & EXPORT
# ==============================================================================
elif st.session_state["nav_page"] == "Shortlist":
    st.markdown('<div class="section-header">Candidate Shortlist</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-caption">Manage vetted candidates, update recruiter notes, and export pipeline with contact provenance</div>', unsafe_allow_html=True)

    all_jobs = list_jobs(conn)
    job_filter_map = {"All Saved Jobs": None}
    for j in all_jobs:
        job_filter_map[f"#{j['id']} · {j['title']}"] = j["id"]

    chosen_sl_job = st.selectbox("Filter Shortlist by Target Job:", list(job_filter_map.keys()))
    sl_job_id = job_filter_map[chosen_sl_job]

    shortlisted = list_shortlisted_candidates(conn, job_id=sl_job_id)

    if not shortlisted:
        st.info("ℹ️ No candidates currently marked as 'Shortlisted'. Review candidates in **Candidates** or **Find Candidates** to shortlist talent.")
    else:
        st.write(f"Total Shortlisted: **{len(shortlisted)}** candidates")

        sl_table = []
        for c in shortlisted:
            c_dict = dict(c)
            sl_table.append({
                "ID": c_dict["id"],
                "Name": c_dict["name"],
                "Headline": c_dict.get("headline") or "-",
                "Company": c_dict.get("company") or "-",
                "Location": c_dict.get("location") or "-",
                "Profile URL": c_dict.get("profile_url") or "",
                "Public Email": c_dict.get("email") or "Not found",
                "Public Phone": c_dict.get("phone") or "Not found",
                "Contact Provenance": c_dict.get("contact_provenance") or "-",
                "Notes": c_dict.get("notes") or "",
            })

        df_sl = pd.DataFrame(sl_table)
        st.dataframe(
            df_sl,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Profile URL": st.column_config.LinkColumn("Profile URL"),
            },
        )

        # Download Shortlist CSV with Formula-Injection Protection
        clean_csv = sanitize_dataframe_for_csv(df_sl).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📥 Export Shortlist to CSV (Sanitized)",
            data=clean_csv,
            file_name=f"shortlist_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            type="primary",
        )

        st.divider()
        st.markdown("#### Manage Shortlist Candidates")
        m_col1, m_col2 = st.columns([2, 1])
        with m_col1:
            cand_to_manage = st.selectbox(
                "Select Candidate to update notes or remove from shortlist:",
                options=[c["id"] for c in shortlisted],
                format_func=lambda cid: next(f"#{c['id']} · {c['name']} ({c['headline'] or 'Candidate'})" for c in shortlisted if c["id"] == cid),
            )
            managed_c = next(c for c in shortlisted if c["id"] == cand_to_manage)
            updated_notes = st.text_area("Edit Recruiter Notes:", value=managed_c.get("notes") or "", height=80)
            if st.button("Save Notes Update"):
                add_or_update_candidate(conn, {"name": managed_c["name"], "profile_url": managed_c["profile_url"], "notes": updated_notes})
                st.success("Notes updated successfully!")
                st.rerun()

        with m_col2:
            st.write("")
            st.write("")
            st.caption("Remove from shortlist without deleting the underlying candidate profile:")
            if st.button("❌ Remove from Shortlist", type="secondary"):
                remove_from_shortlist(conn, cand_to_manage)
                st.success(f"Candidate #{cand_to_manage} status changed to 'Under Review'. Record preserved.")
                st.rerun()


# ==============================================================================
# SECTION 6: SAVED JOBS & DATA ADMINISTRATION
# ==============================================================================
elif st.session_state["nav_page"] == "Saved Jobs & Data":
    st.markdown('<div class="section-header">Saved Jobs & Data Administration</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-caption">Manage job definitions, candidate directory, bulk imports, and SQLite database backups</div>', unsafe_allow_html=True)

    tab_jobs, tab_dir, tab_backup = st.tabs([
        "💼 Saved Jobs",
        "👥 Candidate Directory & Bulk Import",
        "💾 Database Backups & Restore",
    ])

    # Tab 1: Saved Jobs
    with tab_jobs:
        st.subheader("Manage Saved Jobs")
        jobs = list_jobs(conn)
        if not jobs:
            st.info("No jobs saved in database.")
        else:
            for j in jobs:
                cands_count = len(list_candidates(conn, job_id=j["id"]))
                with st.expander(f"💼 #{j['id']} · {j['title']} (Created: {j['created_at'][:10]}) — {cands_count} candidates"):
                    col_j1, col_j2 = st.columns([2, 1])
                    with col_j1:
                        new_t = st.text_input("Job Title:", value=j["title"], key=f"edit_job_title_{j['id']}")
                        new_l = st.text_input("Location:", value=j["location"] or "", key=f"edit_job_loc_{j['id']}")
                        if st.button("Save Job Details", key=f"btn_save_j_{j['id']}"):
                            update_job(conn, j["id"], title=new_t, location=new_l)
                            st.success("Job updated!")
                            st.rerun()
                    with col_j2:
                        st.caption("Destructive Action:")
                        confirm_del = st.checkbox("Confirm Delete Job", key=f"conf_del_{j['id']}")
                        if confirm_del and st.button("🗑️ Delete Job", key=f"btn_del_j_{j['id']}"):
                            delete_job(conn, j["id"])
                            st.success(f"Job #{j['id']} deleted.")
                            st.rerun()

                    with st.expander("View Full Job Description Text"):
                        st.text_area("JD Text", value=j["jd_text"], height=160, disabled=True, key=f"jd_text_view_{j['id']}")

    # Tab 2: Candidate Directory & Bulk Import
    with tab_dir:
        st.subheader("Candidate Directory")
        all_cands = list_candidates(conn)
        st.write(f"Total Candidates: **{len(all_cands)}**")

        if all_cands:
            c_table = []
            for c in all_cands:
                c_table.append({
                    "ID": c["id"],
                    "Name": c["name"],
                    "Headline": c["headline"] or "-",
                    "Location": c["location"] or "-",
                    "Status": c["status"] or "New",
                    "Email": c["email"] or "Not found",
                    "Source": c["source"] or "Manual",
                    "Created": c["created_at"][:10],
                })
            st.dataframe(pd.DataFrame(c_table), use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Bulk Import from CSV")
        st.caption("Import candidate profiles from a local CSV file. Deduplication is handled automatically.")
        st.markdown(
            """**Expected CSV columns:** `name` *(required)*, `profile_url`, `headline`, `location`, `experience`, `evidence_text`, `email`, `phone`, `notes`"""
        )
        bulk_file = st.file_uploader("Select CSV file to import", type=["csv"], key="admin_bulk_csv")
        if bulk_file and st.button("🚀 Process Bulk Import"):
            try:
                df_b = pd.read_csv(bulk_file).fillna("")
                if "name" not in df_b.columns:
                    st.error("CSV must contain a 'name' column.")
                else:
                    success_cnt = 0
                    for _, row in df_b.iterrows():
                        payload = {
                            "name": str(row.get("name", "")).strip(),
                            "profile_url": str(row.get("profile_url", "")).strip(),
                            "headline": str(row.get("headline", "")).strip(),
                            "location": str(row.get("location", "")).strip(),
                            "experience": str(row.get("experience", "")).strip(),
                            "evidence_text": str(row.get("evidence_text", "")).strip(),
                            "email": str(row.get("email", "")).strip(),
                            "phone": str(row.get("phone", "")).strip(),
                            "notes": str(row.get("notes", "")).strip(),
                            "source": "CSV Import",
                            "status": "New",
                        }
                        ok, _, _ = add_or_update_candidate(conn, payload)
                        if ok:
                            success_cnt += 1
                    st.success(f"Successfully processed {success_cnt} candidates from CSV!")
                    st.rerun()
            except Exception as exc:
                st.error(f"Error parsing CSV: {exc}")

    # Tab 3: Database Backups & Restore
    with tab_backup:
        st.subheader("Database Backups & Safety Snapshots")
        st.caption("Create verified backups of SQLite database before major changes. Uses SQLite transactional backup API.")

        col_b1, col_b2 = st.columns([1.5, 2])
        with col_b1:
            if st.button("💾 Create Verified Backup Now", type="primary"):
                try:
                    b_path = create_backup(DB_PATH)
                    st.success(f"✅ Backup created: `{b_path.name}`")
                except Exception as exc:
                    st.error(f"Backup failed: {exc}")

        # List existing backups
        backup_files = sorted(APP_DIR.glob("candidate_sourcing_backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
        st.markdown("#### Existing Database Backups")
        if backup_files:
            b_data = []
            for bf in backup_files:
                b_data.append({
                    "Filename": bf.name,
                    "Size (KB)": round(bf.stat().st_size / 1024, 1),
                    "Created": datetime.fromtimestamp(bf.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })
            st.dataframe(pd.DataFrame(b_data), use_container_width=True, hide_index=True)
        else:
            st.caption("No backups found in project directory.")

        st.divider()
        st.subheader("Restore Database from Backup")
        st.warning("⚠️ Restoring a database replaces the current database with the backup file. A pre-restore safety snapshot is taken automatically.")
        restore_file = st.file_uploader("Upload Backup Database (.db)", type=["db"], key="restore_db_upload")
        if restore_file and st.button("⚠️ Confirm Database Restore"):
            ok, r_msg, s_backup = restore_database(restore_file.getvalue(), DB_PATH)
            if ok:
                st.success(f"✅ {r_msg}")
                st.rerun()
            else:
                st.error(f"❌ {r_msg}")


# ==============================================================================
# SECTION 7: SETTINGS & ZERO-BUDGET GOVERNANCE
# ==============================================================================
elif st.session_state["nav_page"] == "Settings":
    st.markdown('<div class="section-header">System Settings & Provider Configuration</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-caption">Strict zero-budget policies, provider configuration, and privacy guarantees</div>', unsafe_allow_html=True)

    st.success(
        "🔒 **Strict ₹0 Budget Guarantee**: Total permitted expenditure is ₹0. "
        "Paid search endpoints (Exa, Brave paid, SerpAPI billable, etc.) and paid contact enrichment services "
        "are strictly prohibited and disabled. No subscriptions or billable APIs will ever be called."
    )

    # 1. Local Extraction Configuration
    with st.expander("⚙️ Local Extraction Engine (Default)", expanded=True):
        st.markdown(
            "**Status:** `Active & Ready`\n\n"
            "- Runs 100% locally on your computer CPU.\n"
            "- Requires zero API keys, network calls, or telemetry.\n"
            "- Extracts core requirements, job titles, tools, and experience levels using deterministic pattern matching."
        )

    # 2. Groq AI Configuration
    with st.expander("⚡ Groq AI-Assisted Extraction (Optional Free Plan)", expanded=True):
        st.caption("Provides optional cloud-assisted extraction for complex job descriptions under Groq's Free tier.")
        cfg_model = get_groq_model()
        st.write(f"**Configured Model ID:** `{cfg_model}`")

        detected_key = resolve_groq_api_key()
        if detected_key:
            st.write("🔑 **API Key Status:** `Configured via project .env or system environment`")
        else:
            st.write("🔑 **API Key Status:** `Not configured (Local extraction active)`")

        col_st1, col_st2 = st.columns([3, 2])
        with col_st1:
            session_override = st.text_input(
                "Session API Key Override (optional):",
                value="",
                type="password",
                key="settings_groq_session_override",
                help="Leave blank to use GROQ_API_KEY from project .env. Never pre-fills or exposes your key.",
            )
        with col_st2:
            st.write("")
            st.write("")
            if st.button("⚡ Test Groq Connection", key="btn_settings_test_groq"):
                override_val = session_override.strip() if session_override.strip() else None
                with st.spinner("Testing Groq connectivity..."):
                    res = run_groq_live_smoke_test(api_key=override_val, model=cfg_model)
                    if res["success"]:
                        st.success(f"✅ {res['message']}")
                    else:
                        st.warning(f"⚠️ {res['message']} (Category: {res['status_category']})")

    # 3. GitHub Public API Configuration
    with st.expander("🐙 GitHub Public Candidate Search", expanded=True):
        st.caption("Official public developer discovery endpoint: https://api.github.com/search/users")
        gh_p = GitHubSearchProvider()
        gh_status = gh_p.check_rate_limit()

        if gh_status.get("success"):
            st.write(f"**Core Limit:** `{gh_status['core_remaining']} / {gh_status['core_limit']}` remaining (Resets at {gh_status['core_reset']})")
            st.write(f"**Search Limit:** `{gh_status['search_remaining']} / {gh_status['search_limit']}` remaining (Resets at {gh_status['search_reset']})")
            st.write(f"**Authentication:** {'Authenticated with GITHUB_TOKEN' if gh_status['authenticated'] else 'Unauthenticated (Free public mode)'}")
        else:
            st.write(f"**Rate Limit Check:** {gh_status.get('error')}")

        st.caption("To increase rate limits from 60/hr to 5,000/hr for free, generate a free personal access token on GitHub and add `GITHUB_TOKEN=ghp_...` to `.env`.")

    # 4. Privacy & Data Handling
    with st.expander("🛡️ Privacy & Local-First Architecture", expanded=True):
        st.markdown(
            """
            - **Local SQLite Database (`candidate_sourcing.db`)**: All candidate CVs, evidence excerpts, notes, match scores, and search logs reside purely on your local machine.
            - **No External Candidate Leakage**: Candidate profiles, CVs, and recruiter notes are NEVER sent to external AI or search engines.
            - **Manual X-Ray Links**: Google and Bing links are generated for manual viewing in your own browser; no automated scraping of search engines is performed.
            - **Contact Transparency**: Emails and phone numbers are sourced ONLY from public profile fields. Missing contacts remain blank and labeled 'Not found'.
            """
        )
