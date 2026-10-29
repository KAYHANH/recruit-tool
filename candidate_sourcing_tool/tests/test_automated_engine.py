"""
Tests for the Automated Sourcing Engine:
- Zero-budget source connectors (GitHub, GitLab, Stack Overflow, Hugging Face, Local DB)
- Entity Resolver (Normalization, Deduplication, Non-destructive Merging)
- Search Orchestrator (Multi-stage workflow, Cooperative cancellation, Error isolation)
- FastAPI endpoints (Search runs, Feedback calibration, Safe CSV export)
"""
import gzip
import json
import os
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from source_connectors import (
    GitHubConnector,
    GitLabConnector,
    StackExchangeConnector,
    HuggingFaceConnector,
    LocalDatabaseConnector,
    RawCandidateProfile,
    ConnectorSearchResult,
    classify_github_evidence,
)
from entity_resolver import (
    EntityResolver,
    normalize_profile_url,
    normalize_email,
    normalize_name,
)
from search_orchestrator import SearchOrchestrator, SourcingRunProgress
from cost_guard import cost_guard, CostPolicyViolationError
from talent_pool_mapper import talent_pool_mapper
from api import app, DB_PATH
import db


@pytest.fixture
def test_client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Source Connectors Tests
# ---------------------------------------------------------------------------

def test_github_connector_parsing():
    connector = GitHubConnector()
    mock_search_payload = {
        "total_count": 1,
        "items": [
            {"login": "ml_engineer_1", "html_url": "https://github.com/ml_engineer_1", "score": 9.5}
        ]
    }
    mock_user_payload = {
        "login": "ml_engineer_1",
        "name": "Alex Mercer",
        "bio": "Senior ML Engineer working with PyTorch and Transformers",
        "company": "AI Labs",
        "location": "Bengaluru, India",
        "email": "alex.mercer@example.com",
        "blog": "https://alexmercer.ai",
        "html_url": "https://github.com/ml_engineer_1",
        "public_repos": 42,
        "followers": 128,
    }

    with patch("source_connectors.urlopen") as mock_urlopen:
        # 1st call: search users, 2nd call: user profile
        mock_resp1 = MagicMock()
        mock_resp1.read.return_value = json.dumps(mock_search_payload).encode("utf-8")
        mock_resp1.__enter__.return_value = mock_resp1

        mock_resp2 = MagicMock()
        mock_resp2.read.return_value = json.dumps(mock_user_payload).encode("utf-8")
        mock_resp2.__enter__.return_value = mock_resp2

        mock_urlopen.side_effect = [mock_resp1, mock_resp2]

        result = connector.search(keywords="PyTorch Python", location="Bengaluru", limit=1)

        assert isinstance(result, ConnectorSearchResult)
        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert cand.name == "Alex Mercer"
        assert cand.source == "GitHub Public API"
        assert cand.email == "alex.mercer@example.com"
        assert cand.location == "Bengaluru, India"
        assert "PyTorch" in cand.evidence_text or "Transformers" in cand.evidence_text


def test_gitlab_connector_parsing():
    connector = GitLabConnector()
    mock_projects = [
        {
            "id": 101,
            "name": "nlp-pipeline",
            "description": "Production NLP model pipeline using spaCy and BERT",
            "web_url": "https://gitlab.com/devuser/nlp-pipeline",
            "star_count": 12,
            "forks_count": 3,
            "namespace": {
                "name": "Dev User",
                "path": "devuser",
                "kind": "user",
                "web_url": "https://gitlab.com/devuser",
            },
        }
    ]

    with patch("source_connectors.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_projects).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = connector.search(keywords="nlp pipeline", limit=1)

        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert cand.name == "Dev User"
        assert cand.source == "GitLab Public API"
        assert cand.profile_url == "https://gitlab.com/devuser"
        assert "nlp-pipeline" in cand.evidence_text


def test_stackexchange_connector_gzip_handling():
    connector = StackExchangeConnector()
    mock_data = {
        "items": [
            {
                "user_id": 554433,
                "display_name": "DataWizard",
                "link": "https://stackoverflow.com/users/554433/datawizard",
                "location": "Berlin, Germany",
                "reputation": 8450,
                "website_url": "https://datawizard.io",
                "badge_counts": {"gold": 3, "silver": 15, "bronze": 40},
            }
        ]
    }
    # Stack Exchange API serves gzip-compressed payloads
    compressed = gzip.compress(json.dumps(mock_data).encode("utf-8"))

    with patch("source_connectors.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = compressed
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = connector.search(keywords="python data", limit=1)

        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert cand.name == "DataWizard"
        assert cand.source == "Stack Overflow"
        assert cand.profile_url == "https://stackoverflow.com/users/554433/datawizard"
        assert "8,450" in cand.evidence_text


def test_huggingface_connector_parsing():
    connector = HuggingFaceConnector()
    mock_models = [
        {
            "id": "deeplearning-expert/vit-finetuned",
            "author": "deeplearning-expert",
            "downloads": 12500,
            "likes": 88,
            "pipeline_tag": "image-classification",
            "tags": ["pytorch", "vision"],
        }
    ]

    with patch("source_connectors.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_models).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        # Must include AI/ML keywords to trigger HF search
        result = connector.search(keywords="vision model pytorch", limit=1)

        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert cand.name == "deeplearning-expert"
        assert cand.source == "Hugging Face"
        assert cand.profile_url == "https://huggingface.co/deeplearning-expert"
        assert "vit-finetuned" in cand.evidence_text


def test_local_database_connector():
    conn = db.init_db(DB_PATH)
    try:
        connector = LocalDatabaseConnector(db_conn=conn)
        result = connector.search(keywords="Data Scientist Python", limit=5)
        assert isinstance(result, ConnectorSearchResult)
        assert len(result.candidates) > 0
        cand = result.candidates[0]
        assert cand.source == "Local DB Rediscovery"
        assert cand.name != ""
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Entity Resolver Tests
# ---------------------------------------------------------------------------

def test_entity_resolver_url_normalization():
    url1 = "https://github.com/torvalds/"
    url2 = "http://www.github.com/torvalds"
    url3 = "github.com/torvalds?tab=repositories"

    assert normalize_profile_url(url1) == "https://github.com/torvalds"
    assert normalize_profile_url(url2) == "https://github.com/torvalds"
    assert normalize_profile_url(url3).startswith("https://github.com/torvalds")


def test_entity_resolver_deduplication_and_merge():
    resolver = EntityResolver()
    p1 = RawCandidateProfile(
        name="John Doe",
        headline="Senior Python Engineer",
        source="GitHub Public API",
        profile_url="https://github.com/johndoe",
        email="john.doe@example.com",
        location="Remote",
        evidence_text="GitHub profile: Python contributor",
    )
    p2 = RawCandidateProfile(
        name="John Doe",
        headline="Backend Specialist",
        source="GitLab Public API",
        profile_url="https://gitlab.com/johndoe",
        email="JOHN.DOE@EXAMPLE.COM",  # Case insensitivity test
        location="Remote",
        evidence_text="GitLab repo: backend services",
    )
    p3 = RawCandidateProfile(
        name="Sarah Smith",
        headline="Data Analyst",
        source="Stack Overflow",
        profile_url="https://stackoverflow.com/users/999/sarah",
        email="",
        location="London",
        evidence_text="Top answerer in Python",
    )

    c1, is_dup1 = resolver.resolve(p1)
    assert is_dup1 is False
    assert c1.name == "John Doe"

    c2, is_dup2 = resolver.resolve(p2)
    assert is_dup2 is True
    # Merged into c1
    assert "GitHub profile" in c2.evidence_text
    assert "GitLab repo" in c2.evidence_text
    assert "GitHub Public API" in c2.raw_sources
    assert "GitLab Public API" in c2.raw_sources

    c3, is_dup3 = resolver.resolve(p3)
    assert is_dup3 is False
    assert c3.name == "Sarah Smith"


# ---------------------------------------------------------------------------
# 3. Search Orchestrator Stage Progression & Cooperative Cancellation
# ---------------------------------------------------------------------------

def test_search_orchestrator_execution():
    orchestrator = SearchOrchestrator(db_path=DB_PATH)
    # Run a test run targeting local_db only to avoid live network latency in unit test
    progress = orchestrator.start_run(
        job_id=1,
        enabled_sources=["local_db"],
        limit_per_source=2,
    )

    assert progress.job_id == 1
    assert progress.run_id != ""

    status = orchestrator.get_run_status(progress.run_id)
    assert status is not None
    assert status.job_id == 1
    assert status.status in ("CREATED", "PLANNING", "SEARCHING", "MATCHING", "COMPLETED")


def test_search_orchestrator_cooperative_cancellation():
    orchestrator = SearchOrchestrator(db_path=DB_PATH)
    progress = orchestrator.start_run(
        job_id=1,
        enabled_sources=["local_db"],
        limit_per_source=1,
    )

    cancelled = orchestrator.cancel_run(progress.run_id)
    assert cancelled is True
    import time
    time.sleep(0.05)
    status = orchestrator.get_run_status(progress.run_id)
    assert status.status in ("CANCELLED", "COMPLETED")


# ---------------------------------------------------------------------------
# 4. FastAPI Endpoints & Feedback Calibration
# ---------------------------------------------------------------------------

def test_api_search_runs_lifecycle(test_client):
    # 1. Start a run (returns 201 Created)
    resp = test_client.post(
        "/api/search-runs",
        json={
            "job_id": 1,
            "role_title": "Lead ML Engineer",
            "skills": ["Python", "TensorFlow"],
            "location": "Bengaluru",
            "enabled_sources": ["local_db"],
            "limit_per_source": 2,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "run_id" in data
    run_id = data["run_id"]

    # 2. Check run status
    resp_status = test_client.get(f"/api/search-runs/{run_id}")
    assert resp_status.status_code == 200
    assert resp_status.json()["run_id"] == run_id

    # 3. List runs
    resp_list = test_client.get("/api/search-runs?job_id=1")
    assert resp_list.status_code == 200
    runs = resp_list.json()
    assert any(r["run_id"] == run_id for r in runs)


def test_api_recruiter_feedback_lifecycle(test_client):
    # Feedback on candidate 1 (returns 200 OK)
    feedback_payload = {
        "rating": "Relevant",
        "feedback_text": "Excellent background in distributed systems and modeling.",
        "job_id": 1,
    }
    post_resp = test_client.post("/api/candidates/1/feedback", json=feedback_payload)
    assert post_resp.status_code == 200

    get_resp = test_client.get("/api/candidates/1/feedback")
    assert get_resp.status_code == 200
    feedbacks = get_resp.json()
    assert len(feedbacks) >= 1
    assert feedbacks[0]["rating"] == "Relevant"
    assert "distributed systems" in feedbacks[0]["feedback_text"]


def test_api_overview_stats(test_client):
    resp = test_client.get("/api/overview-stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert "total_jobs" in stats
    assert "total_candidates" in stats
    assert "source_breakdown" in stats
    assert "recent_runs" in stats
    assert stats["total_jobs"] >= 2


def test_safe_csv_export_escaping():
    conn = db.init_db(DB_PATH)
    try:
        raw_csv = db.export_shortlist_csv_safe(conn)
        # Verify no dangerous unescaped formula characters at beginning of cells
        lines = raw_csv.strip().split("\n")
        assert len(lines) >= 1
        for line in lines[1:]:
            cells = line.split(",")
            for cell in cells:
                clean = cell.strip('"')
                if clean and clean[0] in ("=", "+", "-", "@"):
                    # Must be escaped with a single quote prefix
                    assert clean.startswith("'=") or clean.startswith("'+") or clean.startswith("'-") or clean.startswith("'@")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. Cost Guard & Budget Enforcement Tests
# ---------------------------------------------------------------------------

def test_cost_guard_enforcement():
    # Verified free providers must pass
    for provider in ("github", "gitlab", "stackoverflow", "huggingface", "local_db", "local_extractor"):
        contract = cost_guard.verify_provider(provider)
        assert contract.is_free is True

    # Commercial/billable providers must be strictly blocked
    for blocked_provider in ("exa", "serpapi", "hunter_io", "brave_paid", "rocketreach", "clearbit", "any_random_paid"):
        with pytest.raises(CostPolicyViolationError):
            cost_guard.verify_provider(blocked_provider)

    # Total spend must remain zero
    assert cost_guard.verify_spend_is_zero() is True
    summary = cost_guard.get_audit_summary()
    assert summary["total_spend"] == "₹0.00"
    assert summary["max_permitted_spend"] == "₹0.00"
    assert "github" in summary["verified_free_providers"]


# ---------------------------------------------------------------------------
# 6. Talent Pool Mapper & Sourcing Strategy Tests
# ---------------------------------------------------------------------------

def test_talent_pool_mapper_detection_and_strategies():
    # Domain detection
    assert talent_pool_mapper.detect_domain("Lead Machine Learning Engineer", []).domain_name == "AI & Machine Learning"
    assert talent_pool_mapper.detect_domain("Principal NLP Scientist", []).domain_name == "AI & Machine Learning"
    assert talent_pool_mapper.detect_domain("Senior React & Frontend Architect", []).domain_name == "Frontend & Cross-Platform Mobile"
    assert talent_pool_mapper.detect_domain("Backend Cloud DevOps Engineer", []).domain_name == "Backend & Cloud Infrastructure"
    assert talent_pool_mapper.detect_domain("Data Analytics Specialist", []).domain_name == "Data Science & Analytics"

    # 4 distinct query strategies
    strategies = talent_pool_mapper.generate_expanded_search_queries("Machine Learning Engineer", ["Python", "PyTorch"], "Bengaluru")
    assert len(strategies) == 4
    strategy_types = {s["strategy"] for s in strategies}
    assert "Precision Core Skills" in strategy_types
    assert "Adjacent Role & Technical Ecosystem" in strategy_types
    assert "Target-Company Peer Mapping" in strategy_types
    assert "Open Source Ecosystem Stewardship" in strategy_types


# ---------------------------------------------------------------------------
# 7. GitHub Literacy Evidence Ladder Tests
# ---------------------------------------------------------------------------

def test_github_evidence_ladder_classification():
    # Tier 1: Substantive engineering work (repos >= 4, bio matching keywords)
    res1 = classify_github_evidence(
        user_details={"public_repos": 15, "followers": 200},
        bio="Distributed systems engineer working on consensus algorithms and Python",
        keywords="Python algorithms",
    )
    assert res1["tier"] == "Tier 1: Strong Technical Evidence"

    # Tier 2: Moderate engineering work (repos present without bio keyword match)
    res2 = classify_github_evidence(
        user_details={"public_repos": 3, "followers": 5},
        bio="General software developer",
        keywords="PyTorch Kubernetes",
    )
    assert res2["tier"] == "Tier 2: Moderate Technical Evidence"

    # Tier 3: Contextual / minimal signal (0 repos, no match)
    res3 = classify_github_evidence(
        user_details={"public_repos": 0, "followers": 10},
        bio="",
        keywords="Python PyTorch",
    )
    assert res3["tier"] == "Tier 3: Weak / Contextual Signal"


# ---------------------------------------------------------------------------
# 8. API Endpoints for Cost Guard & Talent Pool
# ---------------------------------------------------------------------------

def test_api_cost_guard_and_talent_pool(test_client):
    # GET /api/cost-guard
    resp = test_client.get("/api/cost-guard")
    assert resp.status_code == 200
    cg = resp.json()
    assert cg["total_spend"] == "₹0.00"
    assert cg["max_permitted_spend"] == "₹0.00"
    assert "github" in cg["verified_free_providers"]

    # GET /api/talent-pool/{role_title}
    resp_pool = test_client.get("/api/talent-pool/Senior%20ML%20Engineer")
    assert resp_pool.status_code == 200
    tp = resp_pool.json()
    assert tp["domain"] == "AI & Machine Learning"
    assert len(tp["target_companies"]) > 0
    assert len(tp["adjacent_titles"]) > 0
    assert len(tp["suggested_strategies"]) == 4

