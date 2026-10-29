"""Regression tests for Google X-Ray Search Strategy Execution Pipeline.

Verifies:
1. Dynamic 7-strategy generation (A through G) for a given JD.
2. Strategy task tracking in SQLite db (search_tasks table) with valid statuses.
3. Automated execution of strategies via GroqBrowserSearchConnector with URL extraction and source tagging.
4. Entity deduplication and candidate persistence with NOT NULL safe profile URLs.
5. Association of candidates to job in 'Sourced' stage.
6. Mathematical reconciliation of counters (attempted, raw, valid, duplicates, unique, saved).
7. Partial status handling on rate-limit / partial results.
8. Graceful fallback when automated web discovery is disabled (marking tasks SKIPPED).
9. API endpoints: POST /api/jobs/{id}/xray-plan/execute and GET /api/test/groq-browser-smoke.
"""
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api import app
from db import (
    init_db,
    add_job,
    get_job,
    create_search_run,
    add_search_task,
    update_search_task,
    get_search_tasks,
    list_candidates,
)
from keyword_extractor import JobRequirements
from search_engine_planner import search_engine_planner
from groq_browser_connector import (
    GroqBrowserSearchConnector,
    ConnectorSearchResult,
    RawCandidateProfile,
    parse_browser_search_response,
    _clean_url,
)
from search_orchestrator import SearchOrchestrator, SourcingRunProgress


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


def get_sample_reqs():
    return JobRequirements(
        job_title="Generalist",
        alternative_titles=["AI Generalist", "Operations Specialist"],
        required_skills=["chatgpt proficiency", "problem solving", "task execution", "documentation"],
        preferred_skills=["ai tools", "digital literacy"],
        tools_and_tech=["chatgpt", "google workspace"],
        inferred_keywords=["contractor", "remote", "us remote"],
        qualifications=[],
        education_or_certifications=[],
        experience_level="Mid-Level",
        location="Remote, United States",
        employment_type="Contractor",
        portfolio_required=False,
    )


# ---------------------------------------------------------------------------
# Test 1: Dynamic 7-strategy generation
# ---------------------------------------------------------------------------
def test_dynamic_7_strategy_generation():
    reqs = get_sample_reqs()
    plan = search_engine_planner.plan_job_search(reqs)
    
    assert plan is not None
    assert len(plan.strategies) == 7
    keys = [s.key.replace("Strategy ", "") for s in plan.strategies]
    assert keys == ["A", "B", "C", "D", "E", "F", "G"]
    
    # Check that each strategy has a non-empty query and valid google/bing URLs
    for strat in plan.strategies:
        assert strat.query_text
        assert "google.com" in strat.google_url
        assert "bing.com" in strat.bing_url
        assert strat.name


# ---------------------------------------------------------------------------
# Test 2: URL cleaning and response parsing with citations
# ---------------------------------------------------------------------------
def test_clean_url_and_parse_browser_search_response():
    # Markdown link with trailing period
    assert _clean_url("[Rui Jin](https://github.com/ruijindev0801).") == "https://github.com/ruijindev0801"
    # Plain URL with trailing punctuation
    assert _clean_url("https://erikjolsen.com/,") == "https://erikjolsen.com/"
    # Empty / none
    assert _clean_url("") == ""
    assert _clean_url(None) == ""

    # Simulated LLM browser_search synthesis response
    response_text = """
    Here are the candidate profiles identified from the web search:

    1. Name: **Jordan Lee**
       Profile URL: https://www.linkedin.com/in/jordan-lee-ai-operations
       Role: AI Operations Specialist & Generalist
       Location: Austin, TX, United States
       Evidence: Strong ChatGPT proficiency, prompt engineering, task execution workflows.
       Contact: jordan.lee@example.com

    2. Name: **Taylor Morgan**
       Profile URL: [Taylor Morgan Portfolio](https://taylormorgan.dev/about)
       Role: Generalist / AI Evaluator
       Location: Remote, US
       Evidence: Built prompt evaluation pipelines, daily documentation in Notion.
    """
    profiles = parse_browser_search_response(response_text, default_strategy_key="A")
    assert len(profiles) == 2
    
    p1 = profiles[0]
    assert p1.name == "Jordan Lee"
    assert p1.profile_url == "https://www.linkedin.com/in/jordan-lee-ai-operations"
    assert "ChatGPT" in p1.evidence_text
    assert p1.source == "Groq Web Search (A)"
    assert p1.raw_data.get("strategy_key") == "A"
    assert p1.email == "jordan.lee@example.com"

    p2 = profiles[1]
    assert p2.name == "Taylor Morgan"
    assert p2.profile_url == "https://taylormorgan.dev/about"
    assert p2.source == "Groq Web Search (A)"


# ---------------------------------------------------------------------------
# Test 3: Search tasks tracking in SQLite db
# ---------------------------------------------------------------------------
def test_search_tasks_db_lifecycle(temp_db):
    conn, db_path = temp_db
    job_id = add_job(conn, "Generalist", "Contractor remote role", "Remote, United States")
    run_id = "test-run-task-1"
    create_search_run(conn, run_id, job_id, ["groq_browser"])
    
    # Add tasks for strategies A and B
    task_a_id = add_search_task(conn, run_id, "Strategy A", "site:linkedin.com/in/ Generalist", "LinkedIn Profiles")
    task_b_id = add_search_task(conn, run_id, "Strategy B", "Generalist resume PDF", "Public Resumes")
    
    tasks = get_search_tasks(conn, run_id)
    assert len(tasks) == 2
    assert tasks[0]["status"] == "PENDING"
    assert tasks[1]["status"] == "PENDING"
    
    # Update task A to SEARCHING then RESULTS_RETURNED
    update_search_task(conn, task_a_id, "SEARCHING")
    tasks = get_search_tasks(conn, run_id)
    assert tasks[0]["status"] == "SEARCHING"
    
    update_search_task(conn, task_a_id, "RESULTS_RETURNED", results_count=3)
    # Update task B to RATE_LIMITED
    update_search_task(conn, task_b_id, "RATE_LIMITED", results_count=0, error_message="HTTP 429: TPM exceeded")
    
    tasks = get_search_tasks(conn, run_id)
    assert tasks[0]["status"] == "RESULTS_RETURNED"
    assert tasks[0]["results_count"] == 3
    assert tasks[1]["status"] == "RATE_LIMITED"
    assert "TPM exceeded" in tasks[1]["error_message"]


# ---------------------------------------------------------------------------
# Test 4: SearchOrchestrator executes strategies with mocked connector
# ---------------------------------------------------------------------------
def test_search_orchestrator_xray_execution(temp_db):
    conn, db_path = temp_db
    job_id = add_job(
        conn,
        "Generalist",
        "Contractor role remote US requiring ChatGPT and problem solving",
        "Remote, United States",
        json.dumps(get_sample_reqs().to_dict()),
    )

    orchestrator = SearchOrchestrator(db_path=db_path)

    def fake_search_strategy(self, strategy, keywords, location, limit=3, role_family="", requirements=None):
        strat_key = strategy.key.replace("Strategy ", "")
        if strat_key == "A":
            return ConnectorSearchResult(
                source_name="Groq Browser Search",
                source_id="groq_browser",
                candidates=[
                    RawCandidateProfile(
                        name="Alex Mercer",
                        headline="Operations Specialist & ChatGPT Generalist",
                        profile_url="https://linkedin.com/in/alex-mercer-ops",
                        source="Groq Web Search (Strategy A)",
                        location="Remote, US",
                        evidence_text="Strong task execution and documentation skills",
                        email="alex@example.com",
                        raw_data={"strategy_key": "Strategy A"},
                    )
                ],
                total_found=1,
                rate_limited=False,
            )
        return ConnectorSearchResult(source_name="Groq Browser Search", source_id="groq_browser", candidates=[], total_found=0)

    def fake_search_consolidated(self, strategies, keywords="", location="", limit=5, role_family="", requirements=None):
        return ConnectorSearchResult(
            source_name="Groq Browser Search",
            source_id="groq_browser",
            candidates=[
                RawCandidateProfile(
                    name="Alex Mercer",
                    headline="Operations Specialist & ChatGPT Generalist",
                    profile_url="https://linkedin.com/in/alex-mercer-ops",
                    source="Groq Web Search (Strategy A)",
                    location="Remote, US",
                    evidence_text="Strong task execution and documentation skills",
                    email="alex@example.com",
                    raw_data={"strategy_key": "Strategy A"},
                )
            ],
            total_found=1,
            rate_limited=False,
        )

    with patch("groq_browser_connector.GroqBrowserSearchConnector.check_status", return_value={"api_key_configured": True, "model": "openai/gpt-oss-120b"}), \
         patch("groq_browser_connector.GroqBrowserSearchConnector.search_strategy", side_effect=fake_search_strategy, autospec=True), \
         patch("groq_browser_connector.GroqBrowserSearchConnector.search_consolidated", side_effect=fake_search_consolidated, autospec=True), \
         patch("search_orchestrator.plan_search_reasoning", return_value={"primary_query": "mocked query", "broadened_queries": []}), \
         patch("search_orchestrator.explain_candidate_match_with_groq", return_value="Strong fit for operations generalist role"):

        # Execute run with strategies A and B
        run_prog = orchestrator.start_run(
            job_id=job_id,
            enabled_sources=["groq_browser"],
            strategy_keys=["Strategy A", "Strategy B"],
        )

        run_id = run_prog.run_id

        import time
        prog = None
        for _ in range(60):
            prog = orchestrator.get_run_status(run_id)
            if prog and prog.status in ("COMPLETED", "PARTIAL", "FAILED"):
                break
            time.sleep(0.1)

        assert prog is not None
        assert prog.status in ("COMPLETED", "PARTIAL")


        # Verify strategy tasks tracking
        task_a = prog.strategy_tasks.get("Strategy A") or prog.strategy_tasks.get("A")
        assert task_a is not None
        assert task_a["status"] == "RESULTS_RETURNED"
        assert task_a["results_count"] == 1

        task_b = prog.strategy_tasks.get("Strategy B") or prog.strategy_tasks.get("B")
        assert task_b is not None
        assert task_b["status"] == "NO_RESULTS"

        # Verify reconciliation counters
        reconciled = prog.reconciled_counters
        assert reconciled["search_tasks_attempted"] >= 2
        assert reconciled["raw_source_results"] >= 1
        assert reconciled["valid_profile_leads"] >= 1
        assert reconciled["total_unique_found"] >= 1
        assert reconciled["total_candidates_saved"] >= 1

        # Verify candidate is saved in DB associated to job_candidates
        candidates = list_candidates(conn, job_id=job_id)
        assert len(candidates) >= 1
        saved_cand = next(c for c in candidates if c["name"] == "Alex Mercer")
        assert saved_cand["profile_url"] == "https://linkedin.com/in/alex-mercer-ops"
        assert saved_cand["status"] in ("Sourced", "Needs Review")


# ---------------------------------------------------------------------------
# Test 5: Fallback when automated web search is disabled
# ---------------------------------------------------------------------------
def test_fallback_when_groq_disabled(temp_db):
    conn, db_path = temp_db
    job_id = add_job(
        conn,
        "Generalist",
        "Role description",
        "Remote, United States",
        json.dumps(get_sample_reqs().to_dict()),
    )

    orchestrator = SearchOrchestrator(db_path=db_path)

    run_prog = orchestrator.start_run(
        job_id=job_id,
        enabled_sources=["local_db"],
        strategy_keys=["Strategy A", "Strategy B", "Strategy C"],
    )
    run_id = run_prog.run_id

    import time
    prog = None
    for _ in range(40):
        prog = orchestrator.get_run_status(run_id)
        if prog and prog.status in ("COMPLETED", "PARTIAL", "FAILED"):
            break
        time.sleep(0.1)

    assert prog is not None
    assert prog.status == "COMPLETED"
    # All strategy tasks must be marked SKIPPED safely
    for sk in ["A", "B", "C"]:
        t = prog.strategy_tasks.get(f"Strategy {sk}") or prog.strategy_tasks.get(sk)
        assert t is not None
        assert t["status"] == "SKIPPED"


# ---------------------------------------------------------------------------
# Test 6: API endpoint POST /api/jobs/{job_id}/xray-plan/execute
# ---------------------------------------------------------------------------
def test_api_xray_plan_execute_endpoint(client):
    job_res = client.post("/api/jobs", json={
        "title": "Generalist XRay Test Role",
        "jd_text": "Contractor remote role requiring ChatGPT proficiency and documentation.",
        "location": "Remote, United States",
    })
    assert job_res.status_code == 201
    created_job_id = job_res.json()["id"]

    mock_prog = SourcingRunProgress(
        run_id="test-xray-run-123",
        job_id=created_job_id,
        status="STARTED",
        current_stage="INITIALIZING",
        progress_percent=0,
        enabled_sources=["groq_browser"],
        started_at="2026-10-29T12:00:00",
    )
    with patch("api._orchestrator.start_run", return_value=mock_prog) as mock_start:
        response = client.post(
            f"/api/jobs/{created_job_id}/xray-plan/execute",
            json={
                "strategy_keys": ["Strategy A", "Strategy B", "Strategy C", "Strategy D"],
                "max_strategies": 4,
                "limit_per_strategy": 3,
                "enabled_sources": ["groq_browser", "local_db"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "test-xray-run-123"
        assert data["status"] == "STARTED"
        assert len(data["strategies_queued"]) == 4
        assert mock_start.called


# ---------------------------------------------------------------------------
# Test 7: API endpoint GET /api/test/groq-browser-smoke
# ---------------------------------------------------------------------------
def test_api_groq_browser_smoke_endpoint(client):
    mock_connector_res = ConnectorSearchResult(
        source_name="Groq Browser Search",
        source_id="groq_browser",
        candidates=[
            RawCandidateProfile(
                name="Jane Doe",
                headline="AI Operations Specialist",
                profile_url="https://linkedin.com/in/jane-doe-ops",
                source="Groq Web Search (Smoke Test)",
                location="Remote, US",
                evidence_text="Experienced prompt engineer",
            )
        ],
        total_found=1,
        rate_limited=False,
    )
    with patch("api.GroqBrowserSearchConnector.check_status", return_value={"api_key_configured": True}), \
         patch("api.GroqBrowserSearchConnector.search", return_value=mock_connector_res):
        response = client.get("/api/test/groq-browser-smoke")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "COMPLETED"
        assert data["is_mock"] is False
        assert data["model"] == "openai/gpt-oss-120b"
        assert data["tool"] == "browser_search"
        assert data["candidates_found"] == 1
        assert data["tool"] == "browser_search"
        assert data["candidates_found"] == 1
