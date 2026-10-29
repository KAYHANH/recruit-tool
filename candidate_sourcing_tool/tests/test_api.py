from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api import app, DB_PATH
from db import init_db


@pytest.fixture(scope="module")
def client():
    # TestClient for FastAPI
    with TestClient(app) as test_client:
        yield test_client


def test_api_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "Candidate Finder" in data["service"]
    assert data["zero_budget_spend"] == "₹0.00"


def test_api_overview(client):
    response = client.get("/api/overview")
    assert response.status_code == 200
    data = response.json()
    assert "total_jobs" in data
    assert "total_candidates" in data
    assert "needing_review" in data
    assert "shortlisted" in data
    assert isinstance(data["recent_jobs"], list)
    assert isinstance(data["recent_candidates"], list)


def test_api_list_jobs(client):
    response = client.get("/api/jobs")
    assert response.status_code == 200
    jobs = response.json()
    assert isinstance(jobs, list)
    if jobs:
        first = jobs[0]
        assert "id" in first
        assert "title" in first
        assert "candidate_count" in first


def test_api_single_job_not_found(client):
    response = client.get("/api/jobs/999999")
    assert response.status_code == 404


def test_api_job_lifecycle(client):
    # 1. Create a test job
    create_payload = {
        "title": "Temporary Test Engineer",
        "jd_text": "We are looking for a Python and Docker Engineer in Remote.",
        "location": "Remote",
        "extracted_data": json.dumps({"core_skills": ["python", "docker"], "job_title": "Test Engineer"}),
    }
    create_res = client.post("/api/jobs", json=create_payload)
    assert create_res.status_code == 201
    job = create_res.json()
    job_id = job["id"]
    assert job["title"] == "Temporary Test Engineer"

    # 2. Get the test job
    get_res = client.get(f"/api/jobs/{job_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == job_id

    # 3. Update the job
    patch_res = client.patch(f"/api/jobs/{job_id}", json={"title": "Updated Test Engineer"})
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "Updated Test Engineer"

    # 4. Delete the job
    del_res = client.delete(f"/api/jobs/{job_id}")
    assert del_res.status_code == 200

    # 5. Confirm deletion
    get_deleted = client.get(f"/api/jobs/{job_id}")
    assert get_deleted.status_code == 404


def test_api_analyze_jd_local(client):
    jd_sample = """
    Job Title: Senior Data Engineer
    Location: Bengaluru, India
    Requirements:
    - 5+ years experience in Python, Apache Spark, and SQL
    - Hands-on experience with Kafka and AWS
    - Bachelor's degree in Computer Science
    """
    res = client.post("/api/analyze-jd", json={"jd_text": jd_sample, "engine": "local"})
    assert res.status_code == 200
    data = res.json()
    assert data["engine"] == "local"
    assert "requirements" in data
    assert "title_extraction" in data
    assert "data engineer" in data["title_extraction"]["title"].lower()


def test_api_candidate_lifecycle(client):
    # 1. Create candidate
    candidate_data = {
        "name": "Jane Test API Candidate",
        "profile_url": "https://github.com/janetestapi",
        "github_url": "https://github.com/janetestapi",
        "headline": "Senior Data Specialist",
        "company": "Test Tech Corp",
        "location": "Bengaluru",
        "evidence_text": "Expert in Python, Spark, SQL, Kafka with 6 years experience.",
        "notes": "FastAPI candidate lifecycle test",
        "status": "New",
        "email": "jane@example.com",
        "phone": "+91 9876543210",
        "contact_provenance": "Profile bio",
        "contact_status": "Verified",
    }
    create_res = client.post("/api/candidates", json=candidate_data)
    assert create_res.status_code == 201
    cand = create_res.json()
    cand_id = cand["id"]
    assert cand["name"] == "Jane Test API Candidate"

    # 2. Get candidate
    get_res = client.get(f"/api/candidates/{cand_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Jane Test API Candidate"

    # 3. Update candidate status and notes
    patch_res = client.patch(
        f"/api/candidates/{cand_id}",
        json={"status": "Shortlisted", "notes": "Promoted to shortlist via API"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "Shortlisted"

    # 4. Remove from shortlist (non-destructive status change)
    remove_res = client.post(f"/api/candidates/{cand_id}/remove-shortlist")
    assert remove_res.status_code == 200
    cand_after_remove = client.get(f"/api/candidates/{cand_id}").json()
    assert cand_after_remove["status"] == "Under Review"

    # 5. Delete candidate
    del_res = client.delete(f"/api/candidates/{cand_id}")
    assert del_res.status_code == 200


def test_api_settings(client):
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["zero_budget_policy"]["spend_permitted"] == "₹0.00"
    assert data["local_extractor"]["status"] == "Active & Ready"
    assert "active_model" in data["groq_extractor"]


def test_api_backups_list(client):
    res = client.get("/api/backups")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_candidate_intelligence_and_reasoning_endpoints(client):
    # 1. Create a job
    job_res = client.post(
        "/api/jobs",
        json={"title": "FastAPI Architect", "jd_text": "Need senior FastAPI and Python engineer in London."},
    )
    assert job_res.status_code == 201
    job_id = job_res.json()["id"]

    # 2. Create a candidate
    cand_res = client.post(
        "/api/candidates",
        json={
            "name": "Sarah Connor",
            "job_id": job_id,
            "skills": "Python, FastAPI, Docker",
            "experience": "6 years",
            "location": "London",
            "evidence_text": "Authored multiple microservices with FastAPI. https://github.com/sconnor. 300 followers.",
        },
    )
    assert cand_res.status_code == 201
    cand_id = cand_res.json()["id"]

    # 3. Test explain-match endpoint with fallback/mock
    with patch("groq_reasoning.resolve_groq_api_key", return_value=""):
        explain_res = client.post(
            f"/api/candidates/{cand_id}/explain-match",
            json={"job_id": job_id},
        )
        assert explain_res.status_code == 200
        explain_data = explain_res.json()
        assert "explanation" in explain_data
        assert "summary" in explain_data["explanation"]

        # 4. Test profile-intelligence endpoint
        intel_res = client.post(
            f"/api/candidates/{cand_id}/profile-intelligence",
            json={"job_id": job_id},
        )
        assert intel_res.status_code == 200
        intel_data = intel_res.json()
        assert "intelligence" in intel_data
        assert "supported_skills" in intel_data["intelligence"]
        assert "public_contact_or_links" in intel_data["intelligence"]

        # 5. Test dedup-check endpoint
        dedup_res = client.post(
            "/api/candidates/dedup-check",
            json={
                "candidate_a": {"name": "Sarah Connor", "profile_url": "https://github.com/sconnor"},
                "candidate_b": {"name": "S. Connor", "profile_url": "https://github.com/sconnor"},
            },
        )
        assert dedup_res.status_code == 200
        assert "is_likely_same_person" in dedup_res.json()

        # 6. Test calibrate-feedback & strategy-versions endpoints
        cal_res = client.post(
            f"/api/jobs/{job_id}/calibrate-feedback",
            json={"feedback_items": []},
        )
        assert cal_res.status_code == 200

        ver_res = client.get(f"/api/jobs/{job_id}/strategy-versions")
        assert ver_res.status_code == 200
        assert len(ver_res.json()) >= 1

