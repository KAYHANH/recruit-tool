from __future__ import annotations

import io
import json
import sqlite3
import time
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from db import add_job, init_db, list_candidates
from groq_browser_connector import (
    GroqBrowserSearchConnector,
    clean_text,
    is_valid_candidate_url,
    parse_browser_search_response,
)
from search_orchestrator import SearchOrchestrator


def test_is_valid_candidate_url():
    """Verifies URL filtering rules: accepts authentic personal profiles, rejects job boards/templates."""
    assert is_valid_candidate_url("https://www.linkedin.com/in/john-doe-123") is True
    assert is_valid_candidate_url("https://github.com/janedoe") is True
    assert is_valid_candidate_url("https://johndoe.github.io/portfolio") is True
    assert is_valid_candidate_url("https://janedoe.dev/resume.pdf") is True

    # Rejections
    assert is_valid_candidate_url("https://www.indeed.com/jobs?q=python") is False
    assert is_valid_candidate_url("https://www.linkedin.com/jobs/view/12345") is False
    assert is_valid_candidate_url("https://www.linkedin.com/company/google") is False
    assert is_valid_candidate_url("https://www.glassdoor.com/Job/san-francisco-jobs.htm") is False
    assert is_valid_candidate_url("https://example.com/templates/resume-sample.docx") is False
    assert is_valid_candidate_url("not_a_url") is False
    assert is_valid_candidate_url("") is False


def test_clean_text():
    """Verifies Unicode character normalization (e.g. non-breaking hyphens and spaces)."""
    raw = "Senior\u202fSoftware\u2011Engineer \u2014 London"
    cleaned = clean_text(raw)
    assert cleaned == "Senior Software-Engineer - London"


def test_parse_browser_search_response_plain_text():
    """Verifies parsing of structured plain text output from Groq Browser Search."""
    sample_response = """
Candidate 1:
Name: Chubiyojo Adejoh
Profile URL: https://github.com/chubi-x
Headline: Distributed Systems & Backend Engineer
Location: London, UK
Company: FinTech Labs
Skills: Python, Go, Docker, PostgreSQL
Evidence: Active contributor to open source distributed systems 【1†L1-L8】
---
Candidate 2:
Name: Sarah Connor
Profile URL: https://www.linkedin.com/in/sarah-connor-cyber
Headline: Machine Learning Engineer
Location: San Francisco, CA
Company: Cyberdyne AI
Skills: PyTorch, Python, Transformers, FastAPI
Evidence: Published research on generative model evaluation 【2†L10-L15】
"""
    profiles = parse_browser_search_response(sample_response)
    assert len(profiles) == 2

    p1 = profiles[0]
    assert p1.name == "Chubiyojo Adejoh"
    assert p1.profile_url == "https://github.com/chubi-x"
    assert p1.github_url == "https://github.com/chubi-x"
    assert p1.headline == "Distributed Systems & Backend Engineer"
    assert p1.location == "London, UK"
    assert p1.company == "FinTech Labs"
    assert "Tier 1" in p1.evidence_ladder_tier
    assert p1.source == "Groq Browser Search"

    p2 = profiles[1]
    assert p2.name == "Sarah Connor"
    assert p2.profile_url == "https://www.linkedin.com/in/sarah-connor-cyber"
    assert p2.location == "San Francisco, CA"
    assert "Tier 2" in p2.evidence_ladder_tier


def test_parse_browser_search_response_markdown_bold():
    """Verifies parsing when the LLM outputs markdown lists with bold keys."""
    sample_response = """
**Candidate 1:**
- **Name:** Alex Mercer
- **Profile URL:** https://github.com/alex-mercer
- **Headline:** Staff Site Reliability Engineer
- **Location:** New York, NY
- **Company:** Cloud Scale
- **Skills:** Kubernetes, Go, Terraform, Prometheus
- **Evidence:** Maintainer of popular Kubernetes operator with 500+ stars 【3†L5-L12】
---
**Candidate 2:**
- **Name:** Elena Rostova
- **Profile URL:** https://www.linkedin.com/in/elena-rostova
- **Headline:** Senior Data Scientist
- **Location:** Berlin, Germany
- **Company:** Quantum Metrics
- **Skills:** Python, Scikit-learn, SQL
- **Evidence:** Lead data scientist specializing in churn prediction 【4†L1-L6】
"""
    profiles = parse_browser_search_response(sample_response)
    assert len(profiles) == 2

    assert profiles[0].name == "Alex Mercer"
    assert profiles[0].profile_url == "https://github.com/alex-mercer"
    assert profiles[0].company == "Cloud Scale"

    assert profiles[1].name == "Elena Rostova"
    assert profiles[1].profile_url == "https://www.linkedin.com/in/elena-rostova"


def test_parse_browser_search_response_drops_job_boards():
    """Verifies that job boards and aggregator links are dropped from candidate extraction."""
    sample_response = """
Candidate 1:
Name: Real Developer
Profile URL: https://github.com/realdev
Headline: Senior Python Engineer
Location: Remote
Company: Tech Innovations
Skills: Python, Django
Evidence: Active repositories with code samples.
---
Candidate 2:
Name: Software Engineer Jobs in London
Profile URL: https://www.indeed.com/jobs/view?id=99999
Headline: 25+ Software Engineer Jobs
Location: London
Company: Multiple
Skills: Python
Evidence: Job posting board listing.
"""
    profiles = parse_browser_search_response(sample_response)
    assert len(profiles) == 1
    assert profiles[0].name == "Real Developer"
    assert profiles[0].profile_url == "https://github.com/realdev"


def test_groq_browser_connector_check_status():
    """Verifies check_status reporting when API key is set or missing."""
    with patch("groq_browser_connector.resolve_groq_api_key", return_value=None):
        connector = GroqBrowserSearchConnector()
        status = connector.check_status()
        assert status["status"] == "Not configured"
        assert status["api_key_configured"] is False
        assert status["is_free"] is True

    with patch("groq_browser_connector.resolve_groq_api_key", return_value="gsk_testkey123456789"):
        connector = GroqBrowserSearchConnector()
        connector._cooldown_until = 0.0
        status = connector.check_status()
        assert status["status"] == "Ready on Free plan"
        assert status["api_key_configured"] is True


def test_groq_browser_connector_search_mocked_success():
    """Verifies successful candidate discovery through mocked Groq response."""
    mock_payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        "Candidate 1:\n"
                        "Name: Marcus Vance\n"
                        "Profile URL: https://github.com/mvance\n"
                        "Headline: Principal Infrastructure Engineer\n"
                        "Location: Austin, TX\n"
                        "Company: Cloud Works\n"
                        "Skills: Go, Terraform, Kubernetes\n"
                        "Evidence: Author of notable cloud automation tools 【1†L1-L10】\n"
                    )
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("groq_browser_connector.resolve_groq_api_key", return_value="gsk_validkey"):
        with patch("groq_browser_connector.urlopen", return_value=mock_resp):
            connector = GroqBrowserSearchConnector()
            connector._cooldown_until = 0.0
            result = connector.search(keywords="Kubernetes Terraform", location="Austin", limit=5)

            assert result.rate_limited is False
            assert result.error_message is None
            assert len(result.candidates) == 1
            cand = result.candidates[0]
            assert cand.name == "Marcus Vance"
            assert cand.profile_url == "https://github.com/mvance"
            assert cand.source == "Groq Browser Search"


def test_groq_browser_connector_search_mocked_http_429():
    """Verifies that HTTP 429 quota exhaustion initiates safe cooldown and returns rate_limited=True."""
    err_fp = io.BytesIO(b'{"error": {"message": "Rate limit reached for model openai/gpt-oss-120b"}}')
    http_err = HTTPError(
        url="https://api.groq.com/openai/v1/chat/completions",
        code=429,
        msg="Too Many Requests",
        hdrs={"x-ratelimit-reset-tokens": "45"},
        fp=err_fp,
    )

    with patch("groq_browser_connector.resolve_groq_api_key", return_value="gsk_validkey"):
        with patch("groq_browser_connector.urlopen", side_effect=http_err):
            connector = GroqBrowserSearchConnector()
            connector._cooldown_until = 0.0
            result = connector.search(keywords="Python Backend", limit=5)

            assert result.rate_limited is True
            assert "rate limit reached" in (result.error_message or "").lower()
            assert connector._cooldown_until > time.time()

            # Second call should immediately respect cooldown without making network call
            with patch("groq_browser_connector.urlopen") as mock_url:
                res2 = connector.search(keywords="Python Backend", limit=5)
                assert res2.rate_limited is True
                mock_url.assert_not_called()


def test_search_orchestrator_integration_with_groq_browser(tmp_path):
    """Verifies that SearchOrchestrator runs Groq Browser Search, parses candidates,
    deduplicates them, and places them into the Sourced stage in SQLite.
    """
    db_file = tmp_path / "test_sourcing.db"
    conn = init_db(db_file)

    # Insert a test job
    job_id = add_job(
        conn,
        title="Backend Engineer",
        jd_text="Seeking a Senior Python Backend Engineer with experience in FastAPI and PostgreSQL.",
        location="Remote",
        extracted_data=json.dumps({
            "job_title": "Backend Engineer",
            "required_skills": ["Python", "FastAPI", "PostgreSQL"],
            "tools_and_tech": ["Docker", "Git"],
            "preferred_skills": ["Redis"],
            "location": "Remote",
        }),
    )
    conn.close()

    orchestrator = SearchOrchestrator(db_path=db_file)

    # Mock Groq response for the search run
    mock_payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        "Candidate 1:\n"
                        "Name: Priya Sharma\n"
                        "Profile URL: https://github.com/psharma-dev\n"
                        "Headline: Senior Python & FastAPI Engineer\n"
                        "Location: Remote\n"
                        "Company: DataScale\n"
                        "Skills: Python, FastAPI, PostgreSQL, Docker\n"
                        "Evidence: Maintains popular async API templates 【1†L1-L10】\n"
                    )
                }
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("groq_browser_connector.resolve_groq_api_key", return_value="gsk_mockedkey"), \
         patch("groq_browser_connector.urlopen", return_value=mock_resp), \
         patch("search_orchestrator.plan_search_reasoning", return_value={"primary_query": "mocked"}), \
         patch("search_orchestrator.explain_candidate_match_with_groq", return_value={"summary": "Mocked explanation", "evidence_verdict": "High Match"}):

        run = orchestrator.start_run(
            job_id=job_id,
            enabled_sources=["groq_browser"],
            limit_per_source=3,
        )

        # Wait for background thread to complete
        for _ in range(50):
            status = orchestrator.get_run_status(run.run_id)
            if status and status.status in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.1)

        final_status = orchestrator.get_run_status(run.run_id)
        assert final_status is not None
        assert final_status.status == "COMPLETED"
        assert final_status.total_saved >= 1

        # Check database persistence and job_candidates link
        test_conn = init_db(db_file)
        saved_candidates = list_candidates(test_conn, job_id=job_id)
        assert len(saved_candidates) >= 1
        cand = saved_candidates[0]
        assert cand["name"] == "Priya Sharma"
        assert cand["profile_url"] == "https://github.com/psharma-dev"
        assert cand["status"] == "Sourced"
        assert cand["source"].startswith("Groq")
        jc_row = test_conn.execute("SELECT match_score FROM job_candidates WHERE job_id = ? AND candidate_id = ?", (job_id, cand["id"])).fetchone()
        assert jc_row is not None
        assert jc_row["match_score"] > 0
        test_conn.close()
