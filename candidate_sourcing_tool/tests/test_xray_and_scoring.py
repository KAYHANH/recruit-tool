import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from api import app, init_db
from keyword_extractor import JobRequirements
from matcher import evaluate_candidate
from search_engine_planner import search_engine_planner, SearchEnginePlanner
from search_orchestrator import SearchOrchestrator
from source_connectors import (
    GitHubConnector,
    GitLabConnector,
    HuggingFaceConnector,
    LocalDatabaseConnector,
    StackExchangeConnector,
    classify_github_evidence,
)


@pytest.fixture
def test_reqs():
    return JobRequirements(
        job_title="Senior Backend Engineer",
        alternative_titles=["Backend Developer", "Python Engineer"],
        required_skills=["Python", "FastAPI", "PostgreSQL"],
        preferred_skills=["Docker", "Redis"],
        tools_and_tech=["Docker", "Git", "Kubernetes"],
        location="Remote",
        portfolio_required=False,
    )


def test_search_engine_planner_strategies_a_through_g(test_reqs):
    planner = SearchEnginePlanner()
    plan = planner.plan_job_search(test_reqs, job_id=1, target_location="Remote")

    assert plan.job_title == "Senior Backend Engineer"
    assert plan.total_strategies == 7
    strategy_keys = [s.key for s in plan.strategies]
    expected_keys = [
        "Strategy A",
        "Strategy B",
        "Strategy C",
        "Strategy D",
        "Strategy E",
        "Strategy F",
        "Strategy G",
    ]
    assert strategy_keys == expected_keys

    # Check Strategy A (LinkedIn profile X-Ray)
    strat_a = next(s for s in plan.strategies if s.key == "Strategy A")
    assert "site:linkedin.com/in/" in strat_a.query_text
    assert "Senior Backend Engineer" in strat_a.query_text
    assert "https://www.google.com/search?q=" in strat_a.google_url
    assert "https://www.bing.com/search?q=" in strat_a.bing_url
    assert strat_a.target_platform == "LinkedIn Profiles"

    # Check Strategy E (Public CVs & resumes outside LinkedIn)
    strat_e = next(s for s in plan.strategies if s.key == "Strategy E")
    assert "filetype:pdf" in strat_e.query_text or "inurl:resume" in strat_e.query_text
    assert strat_e.target_platform == "Public Web & CVs"

    # Check Strategy F (Developer evidence / GitHub pages)
    strat_f = next(s for s in plan.strategies if s.key == "Strategy F")
    assert "site:github.io" in strat_f.query_text
    assert strat_f.target_platform == "Code & Repositories"

    # Check batch launch URLs
    assert len(plan.batch_urls) >= 4
    for u in plan.batch_urls:
        assert u.startswith("https://www.google.com/search?q=")


def test_candidate_scoring_not_flatlining(test_reqs):
    """Verifies that candidates with distinct profiles receive genuinely varied, non-flatlined scores."""
    # Candidate 1: Strong match with exact title, Python, FastAPI, and Docker repo
    c1 = {
        "id": 101,
        "name": "Alice Backend",
        "headline": "Senior Backend Engineer at TechCorp",
        "location": "Remote",
        "source": "GitHub Public API",
        "evidence_ladder_tier": "Tier 1: Strong Technical Evidence",
        "evidence_text": (
            "Candidate: Alice Backend (@alice)\n"
            "Profile: https://github.com/alice\n"
            "Bio: Senior Backend Engineer building APIs with Python and FastAPI.\n"
            "Recent Public Repositories:\n"
            "- fastapi-microservice (Python) [42★]: Production FastAPI backend\n"
            "- postgres-toolkit (Python) [15★]: PostgreSQL migration helper\n"
            "- docker-runner: Docker setup"
        ),
    }

    # Candidate 2: Partial match (Python only, general developer title, no FastAPI)
    c2 = {
        "id": 102,
        "name": "Bob Scripter",
        "headline": "Software Developer",
        "location": "Remote",
        "source": "GitLab Public API",
        "evidence_ladder_tier": "Tier 2: Moderate Technical Evidence",
        "evidence_text": (
            "Candidate: Bob Scripter (@bob on GitLab)\n"
            "Profile: https://gitlab.com/bob\n"
            "Project: data-cleaner\n"
            "Description: Python scripts for CSV parsing\n"
            "GitLab Project Stars: 1, Forks: 0"
        ),
    }

    # Candidate 3: Unrelated candidate (JavaScript/Frontend, no backend skills)
    c3 = {
        "id": 103,
        "name": "Carol Frontend",
        "headline": "UI Designer & CSS Specialist",
        "location": "New York, NY",
        "source": "Stack Overflow",
        "evidence_ladder_tier": "Tier 3: Weak Technical Evidence",
        "evidence_text": (
            "Candidate: Carol Frontend\n"
            "Profile: https://stackoverflow.com/users/999\n"
            "Reputation: 120\n"
            "Badges: 0 Gold, 1 Silver, 4 Bronze\n"
            "Location: New York, NY\n"
            "Website: https://carol.design"
        ),
    }

    eval1 = evaluate_candidate(c1, test_reqs)
    eval2 = evaluate_candidate(c2, test_reqs)
    eval3 = evaluate_candidate(c3, test_reqs)

    score1 = eval1.confidence_adjusted_score or eval1.total_score
    score2 = eval2.confidence_adjusted_score or eval2.total_score
    score3 = eval3.confidence_adjusted_score or eval3.total_score

    # Assert scores are strictly ordered and distinct (not flatlining to 58%, 17%, or 9%)
    assert score1 > score2 > score3
    assert score1 >= 70
    assert score2 < score1
    assert score3 <= 25

    # Verify 4-tier evidence model integration
    assert eval1.evidence_tier == "Tier 1: Strong Technical Evidence"
    assert eval2.evidence_tier == "Tier 2: Moderate Technical Evidence"
    assert eval3.evidence_tier in ("Tier 3: Weak Technical Evidence", "Tier 4: Insufficient Evidence")

    # Verify contact availability and source reliability
    assert eval1.source_reliability == "High (Verified Code / API)"
    assert eval1.contact_availability == "Profile Link Only"


def test_4_tier_evidence_model_github_classification():
    # Tier 1
    t1 = classify_github_evidence(
        user_details={"public_repos": 10, "followers": 50},
        bio="Senior Python Developer",
        keywords="Python FastAPI",
        repos=[{"name": "fastapi-demo", "language": "Python", "stargazers_count": 5}],
    )
    assert t1["tier"] == "Tier 1: Strong Technical Evidence"

    # Tier 2
    t2 = classify_github_evidence(
        user_details={"public_repos": 2, "followers": 5},
        bio="Junior Coder",
        keywords="Go Kubernetes",
        repos=[{"name": "hello-world", "language": "Go"}],
    )
    assert t2["tier"] == "Tier 2: Moderate Technical Evidence"

    # Tier 3
    t3 = classify_github_evidence(
        user_details={"public_repos": 0, "followers": 2},
        bio="",
        keywords="Python",
        repos=[],
    )
    assert t3["tier"] == "Tier 3: Weak / Contextual Signal"

    # Tier 4
    t4 = classify_github_evidence(
        user_details={"public_repos": 0, "followers": 0},
        bio="",
        keywords="Python",
        repos=[],
    )
    assert t4["tier"] == "Tier 4: Insufficient Evidence"


def test_unique_candidates_rediscovery_and_persistence(tmp_path):
    """Verifies that Rediscovered local candidates are not discarded as duplicates
    and are properly persisted into SQLite with status 'Sourced' and total_saved > 0.
    """
    db_file = tmp_path / "test_sourcing.db"
    conn = init_db(db_file)

    # 1. Insert a test job
    cur = conn.execute(
        "INSERT INTO jobs (title, jd_text, extracted_data, location, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            "Python Engineer",
            "Looking for Python FastAPI developer",
            json.dumps({"job_title": "Python Engineer", "required_skills": ["Python", "FastAPI"], "location": "Remote"}),
            "Remote",
            "2026-10-28 12:00:00",
        ),
    )
    job_id = cur.lastrowid

    # 2. Insert existing candidates into SQLite
    conn.execute(
        """INSERT INTO candidates (name, profile_url, headline, location, source, evidence_text, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "Dave Database",
            "https://github.com/davedb",
            "Python Engineer",
            "Remote",
            "Local DB",
            "Experienced with Python and FastAPI web frameworks.",
            "New",
            "2026-10-28 10:00:00",
        ),
    )
    conn.commit()
    conn.close()

    orchestrator = SearchOrchestrator(db_file)
    prog = orchestrator.start_run(
        job_id=job_id,
        enabled_sources=["local_db"],
        limit_per_source=5,
    )

    # Wait for background thread to complete
    import time
    for _ in range(30):
        time.sleep(0.1)
        st = orchestrator.get_run_status(prog.run_id)
        if st and st.status in ("COMPLETED", "FAILED"):
            break

    final_st = orchestrator.get_run_status(prog.run_id)
    assert final_st.status == "COMPLETED"
    assert final_st.total_saved >= 1
    assert final_st.total_unique_found >= 1
    assert "xray_plan" in final_st.__dict__ or final_st.xray_plan is not None

    # Check that candidate is in job_candidates with stage 'Sourced'
    check_conn = sqlite3.connect(db_file)
    check_conn.row_factory = sqlite3.Row
    jc_rows = check_conn.execute("SELECT * FROM job_candidates WHERE job_id = ?", (job_id,)).fetchall()
    assert len(jc_rows) >= 1
    assert jc_rows[0]["status"] == "Sourced"
    assert jc_rows[0]["match_score"] > 0
    check_conn.close()


def test_api_xray_plan_endpoints():
    client = TestClient(app)

    # 1. Test GET /api/jobs/1/xray-plan
    resp = client.get("/api/jobs/1/xray-plan")
    assert resp.status_code == 200
    data = resp.json()
    assert "strategies" in data
    assert len(data["strategies"]) == 7
    assert data["strategies"][0]["key"] == "Strategy A"
    assert len(data["batch_urls"]) >= 4

    # 2. Test POST /api/jobs/1/xray-plan/launch-batch
    batch_resp = client.post("/api/jobs/1/xray-plan/launch-batch", json={"max_queries": 3})
    assert batch_resp.status_code == 200
    batch_data = batch_resp.json()
    assert batch_data["batch_size"] == 3
    assert len(batch_data["direct_urls"]) == 3
    assert "google.com" in batch_data["direct_urls"][0]
