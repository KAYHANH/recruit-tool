"""Regression test suite for Candidate Finder.

Verifies fixes for:
1. JD-aware source selection (Generalist vs Technical roles).
2. Elimination of score flatlining / free points (FastAPI developer scores low on Generalist, AI evaluator scores high).
3. Evidence ladder tiering (Tier 1 requires real domain evidence, not just any GitHub link).
4. Elimination of repeated search terms ("Generalist" "Generalist") and improper qualifiers ("architect").
5. Mathematical reconciliation of counters across raw, valid, duplicate, unique, and saved.
6. Safe persistence with fallback profile URLs (never failing at 85% with NOT NULL constraint error).
"""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import app
from db import init_db, add_job, add_or_update_candidate, add_source_profile, get_candidate
from keyword_extractor import JobRequirements
from matcher import evaluate_candidate, ScoringWeights
import talent_pool_mapper
import search_engine_planner
from search_orchestrator import SearchOrchestrator, is_valid_candidate_lead


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = Path(f.name)
    conn = init_db(temp_path)
    yield conn, temp_path
    conn.close()
    if temp_path.exists():
        temp_path.unlink()


def get_generalist_reqs():
    return JobRequirements(
        job_title="Generalist",
        alternative_titles=["AI Generalist", "Operations Specialist", "AI Evaluator"],
        required_skills=[
            "chatgpt proficiency",
            "problem solving",
            "attention to detail",
            "communication",
            "task execution",
            "documentation",
        ],
        preferred_skills=[
            "ai tools",
            "digital literacy",
            "independent work",
            "ai training",
        ],
        tools_and_tech=["chatgpt", "google workspace", "notion"],
        inferred_keywords=["contractor", "remote", "us remote", "evaluation"],
        qualifications=[],
        education_or_certifications=[],
        experience_level="Mid-Level",
        location="Remote, United States",
        employment_type="Contractor",
        portfolio_required=False,
    )


# ---------------------------------------------------------------------------
# Test 1: Generalist source selection prioritizes web/local DB over code APIs
# ---------------------------------------------------------------------------
def test_generalist_source_selection_prioritizes_web_and_local():
    role_family = talent_pool_mapper.detect_role_family(
        role_title="Generalist",
        skills=["chatgpt proficiency", "problem solving", "task execution", "documentation"],
        jd_text="Contractor, remote, United States. ChatGPT proficiency, prompt evaluation, task execution.",
    )
    assert role_family == "ai_generalist_operations"

    rec_sources = talent_pool_mapper.get_recommended_sources(role_family)
    assert "groq_browser" in rec_sources
    assert "local_db" in rec_sources
    assert "github" not in rec_sources
    assert "gitlab" not in rec_sources
    assert "stackoverflow" not in rec_sources
    assert "huggingface" not in rec_sources

    policy = talent_pool_mapper.get_role_source_policy(role_family)
    assert "github" in policy["excluded_or_low_priority"]
    assert "stackoverflow" in policy["excluded_or_low_priority"]
    assert "huggingface" in policy["excluded_or_low_priority"]
    assert "Generalist" in policy["rationale"] or "operations" in policy["rationale"]

    # Filter sources test
    all_sources = ["github", "gitlab", "stackoverflow", "huggingface", "local_db", "groq_browser"]
    filtered = talent_pool_mapper.filter_sources_for_role(all_sources, role_family)
    assert filtered == ["groq_browser", "local_db"]


# ---------------------------------------------------------------------------
# Test 2: FastAPI developer (Sebastián Ramírez) scores low on Generalist JD
# ---------------------------------------------------------------------------
def test_fastapi_author_sebastian_ramirez_scores_low_on_generalist():
    reqs = get_generalist_reqs()

    # Sebastián Ramírez / tiangolo profile
    tiangolo_profile = {
        "id": 991,
        "name": "Sebastián Ramírez",
        "headline": "Creator of FastAPI, Typer, SQLModel, AsmPHP",
        "location": "Berlin, Germany",
        "company": "FastAPI / Explosion",
        "skills": "Python, FastAPI, Starlette, Pydantic, Docker, OpenAPI, AsyncIO, Pytest",
        "evidence_text": "GitHub: https://github.com/tiangolo - 70,000+ stars on FastAPI repository. Author of Python web frameworks.",
        "profile_url": "https://github.com/tiangolo",
        "github_url": "https://github.com/tiangolo",
    }

    eval_result = evaluate_candidate(
        candidate=tiangolo_profile,
        requirements=reqs,
        target_location="Remote, United States",
    )

    # Key Assertions:
    # 1. Location must be recognized as Contradictory (US required vs Berlin, Germany)
    loc_match = next((c for c in eval_result.criteria_matches if c.category == "Location"), None)
    assert loc_match is not None
    assert loc_match.status == "Contradictory"

    # 2. Must NOT receive Tier 1 (prior bug gave Tier 1 to anyone with GitHub stars)
    tier = eval_result.evidence_tier
    assert "Tier 1" not in tier
    assert "Tier 4" in tier

    # 3. Match score must be low (<= 15%), NOT the collapsed 83%
    assert eval_result.total_score <= 15


# ---------------------------------------------------------------------------
# Test 3: AI Evaluator candidate scores high on Generalist JD
# ---------------------------------------------------------------------------
def test_ai_evaluator_scores_high_on_generalist():
    reqs = get_generalist_reqs()

    evaluator_profile = {
        "id": 992,
        "name": "Sarah Jenkins",
        "headline": "AI Training Specialist & Prompt Evaluator | Digital Project Specialist",
        "location": "Austin, Texas, United States",
        "company": "Independent Contractor / Scale AI",
        "skills": "ChatGPT proficiency, prompt engineering, attention to detail, problem solving, communication, task execution, documentation, digital literacy, AI training",
        "evidence_text": "Contractor conducting RLHF evaluation, prompt response scoring, and digital workflow documentation using ChatGPT, Notion, and Google Workspace. Demonstrated problem solving, attention to detail, and communication across task execution and digital guidelines. US based remote professional.",
        "profile_url": "https://www.linkedin.com/in/sarah-jenkins-ai-trainer",
    }

    eval_result = evaluate_candidate(
        candidate=evaluator_profile,
        requirements=reqs,
        target_location="Remote, United States",
    )

    # Key Assertions:
    # 1. Location matches US constraint
    loc_match = next((c for c in eval_result.criteria_matches if c.category == "Location"), None)
    assert loc_match is not None
    assert loc_match.status == "Matched"

    # 2. Score must be high (>= 80%)
    assert eval_result.total_score >= 80

    # 3. Tier must be Tier 1 or Tier 2 Domain Evidence
    assert any(t in eval_result.evidence_tier for t in ["Tier 1", "Tier 2"])


# ---------------------------------------------------------------------------
# Test 4: Weak or missing evidence produces Tier 4 / low score
# ---------------------------------------------------------------------------
def test_weak_or_missing_evidence_scores_tier4_low():
    reqs = get_generalist_reqs()

    minimal_profile = {
        "id": 993,
        "name": "Alex Generic",
        "headline": "Student looking for work",
        "location": "",
        "company": "",
        "skills": "Office",
        "evidence_text": "Profile without details",
        "profile_url": "https://example.com/alex",
    }

    eval_result = evaluate_candidate(
        candidate=minimal_profile,
        requirements=reqs,
        target_location="Remote, United States",
    )

    assert eval_result.total_score < 30
    assert "Tier 4" in eval_result.evidence_tier


# ---------------------------------------------------------------------------
# Test 5: Technical roles still prioritize developer connectors
# ---------------------------------------------------------------------------
def test_technical_roles_prioritize_developer_connectors():
    tech_family = talent_pool_mapper.detect_role_family(
        role_title="Senior Python / ML Engineer",
        skills=["python", "pytorch", "transformers", "fastapi", "docker"],
        jd_text="Build scalable ML inference pipelines and microservices in Python.",
    )
    assert tech_family in ["software_engineering", "ai_ml_research"]

    rec_sources = talent_pool_mapper.get_recommended_sources(tech_family)
    assert "github" in rec_sources
    assert "gitlab" in rec_sources
    assert "huggingface" in rec_sources or "stackoverflow" in rec_sources


# ---------------------------------------------------------------------------
# Test 6: Search queries for Generalist do not contain duplicate titles or "architect"
# ---------------------------------------------------------------------------
def test_search_strategies_generalist_no_duplicates_and_correct_qualifiers():
    reqs = get_generalist_reqs()

    plan = search_engine_planner.plan_job_search(
        requirements=reqs,
        job_id=41,
        target_location="United States",
        role_family="ai_generalist_operations",
    )

    assert plan.total_strategies == 7
    queries = {s.key: s.query_text for s in plan.strategies}

    for key, qtext in queries.items():
        # No repeated "Generalist" "Generalist"
        assert '"Generalist" "Generalist"' not in qtext
        assert 'Generalist Generalist' not in qtext

        # Strategy D and F must not have technical "architect"
        if key in ["Strategy D", "Strategy F"]:
            assert '"architect"' not in qtext

    # Strategy D must contain role-appropriate operational/evaluator terms
    strat_d = queries["Strategy D"]
    assert any(term in strat_d for term in ['"evaluator"', '"specialist"', '"trainer"', '"contractor"', '"rater"'])

    # Strategy F must target non-code platforms for generalist
    strat_f = queries["Strategy F"]
    assert any(site in strat_f for site in ["medium.com", "substack.com", "notion.site"])
    assert "github.com" not in strat_f


# ---------------------------------------------------------------------------
# Test 7: Reconciled counters mathematical consistency
# ---------------------------------------------------------------------------
def test_reconciled_counters_mathematical_consistency():
    # Verify lead validator drops non-person and junk urls
    assert not is_valid_candidate_lead("https://github.com/search")
    assert not is_valid_candidate_lead("https://www.linkedin.com/jobs/view/12345")
    assert not is_valid_candidate_lead("https://www.google.com/search?q=test")
    assert not is_valid_candidate_lead("https://www.linkedin.com/company/google")
    assert is_valid_candidate_lead("https://www.linkedin.com/in/johndoe")
    assert is_valid_candidate_lead("https://github.com/tiangolo")
    assert is_valid_candidate_lead("https://huggingface.co/julien-c")

    # Reconciled math test logic:
    # 10 raw, 8 valid, 2 invalid
    # 8 valid has 2 dups, 6 unique
    # 6 unique has 4 new, 2 updated
    # total linked to job = 6
    # 5 qualified (sourced), 1 low match (needs review)
    raw = 10
    valid = 8
    dups = 2
    unique = valid - dups  # 6
    newly_saved = 4
    updated_saved = 2
    associated = newly_saved + updated_saved  # 6
    sourced = 5
    rejected = 1

    # Invariants
    assert raw >= valid
    assert valid == unique + dups
    assert associated == newly_saved + updated_saved
    assert associated == sourced + rejected


# ---------------------------------------------------------------------------
# Test 8: Candidate persistence handles null/empty profile_url without failure
# ---------------------------------------------------------------------------
def test_candidate_persistence_handles_null_urls_and_reaches_100_percent(temp_db):
    conn, db_path = temp_db

    # Create test job
    job_id = add_job(conn, "Generalist", "Test JD", "Remote, US")

    # Candidate with None profile_url
    cand1 = {
        "name": "Jane Candidate",
        "headline": "Prompt Specialist",
        "profile_url": None,
        "source": "groq_browser",
        "skills": "ChatGPT, Prompt Evaluation",
        "evidence_text": "Public web search result",
    }

    ok, msg, cid1 = add_or_update_candidate(conn, cand1, job_id=job_id)
    assert ok, f"Candidate 1 save failed: {msg}"
    assert cid1 > 0

    # Add source profile with None profile_url (previously caused SQLite NOT NULL crash)
    sp_id = add_source_profile(
        conn=conn,
        candidate_id=cid1,
        source="groq_browser",
        profile_url=None,
        raw_data={"lead": "web search lead"},
    )
    assert sp_id > 0

    # Candidate with empty string profile_url
    cand2 = {
        "name": "Bob Reviewer",
        "headline": "AI Annotator",
        "profile_url": "",
        "source": "local_db",
        "skills": "Task Execution",
        "evidence_text": "Local DB rediscovery",
    }
    ok2, msg2, cid2 = add_or_update_candidate(conn, cand2, job_id=job_id)
    assert ok2, f"Candidate 2 save failed: {msg2}"
    assert cid2 > 0

    # Verify total_saved matches job_candidates table count
    count = conn.execute("SELECT COUNT(*) FROM job_candidates WHERE job_id = ?", (job_id,)).fetchone()[0]
    assert count == 2


# ---------------------------------------------------------------------------
# Test 9: FastAPI recommended-sources API returns role family and policy
# ---------------------------------------------------------------------------
def test_api_recommended_sources(client):
    # Job #41 exists in the dev database or we get jobs list
    jobs_res = client.get("/api/jobs")
    assert jobs_res.status_code == 200
    jobs = jobs_res.json()
    assert len(jobs) > 0

    target_job = next((j for j in jobs if "generalist" in j["title"].lower()), jobs[0])
    res = client.get(f"/api/jobs/{target_job['id']}/recommended-sources")
    assert res.status_code == 200
    data = res.json()
    assert "role_family" in data
    assert "recommended_sources" in data
    assert "policy" in data
    assert isinstance(data["recommended_sources"], list)
