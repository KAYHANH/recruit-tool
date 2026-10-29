from __future__ import annotations

import sqlite3
import pytest
from fastapi.testclient import TestClient

from api import app
from db import (
    init_db,
    add_job,
    add_or_update_candidate,
    get_pipeline_data,
    update_job_candidate_stage,
    get_candidate_full_profile,
    add_candidate_note,
    add_candidate_activity,
    seed_candidate_experiences_if_empty,
)


@pytest.fixture
def test_db(tmp_path):
    """Provides a fresh isolated test database with initialized schema."""
    db_file = tmp_path / "test_pipeline.db"
    conn = init_db(db_file)
    yield conn
    conn.close()


@pytest.fixture
def client():
    """FastAPI TestClient instance."""
    return TestClient(app)


def test_seed_candidate_experiences_and_pipeline(test_db):
    """Tests that seeding populates realistic experiences and get_pipeline_data groups correctly."""
    # Add a sample job
    jid = add_job(test_db, "Senior 3D Artist", "Seeking Blender, ZBrush, and stylized asset modeling.", location="Remote")

    # Add candidates
    _, _, c1 = add_or_update_candidate(
        test_db,
        {
            "name": "Candidate Alpha",
            "headline": "Senior 3D Artist",
            "experience": "5 years in stylized 3D",
            "company": "Studio Alpha",
            "evidence_text": "Proficient in Blender and ZBrush.\nExtensive low-poly and UV mapping workflow.\nPortfolio: artstation.com/alpha",
            "status": "Sourced",
        },
        job_id=jid,
    )

    _, _, c2 = add_or_update_candidate(
        test_db,
        {
            "name": "Candidate Beta",
            "headline": "Junior 3D Artist",
            "experience": "1 year in 3D modeling",
            "company": "Studio Beta",
            "evidence_text": "Emerging 3D artist proficient in Blender.\nPortfolio: behance.net/beta",
            "status": "Under Review",
        },
        job_id=jid,
    )

    pipe = get_pipeline_data(test_db, jid)
    assert pipe["job_id"] == jid
    assert pipe["total_candidates"] == 2
    assert len(pipe["stages"]) == 8

    stage_names = [s["name"] for s in pipe["stages"]]
    assert "Sourced" in stage_names
    assert "Under Review" in stage_names
    assert "My Shortlisted" in stage_names
    assert "Contacted" in stage_names
    assert "Interview" in stage_names

    sourced_stage = next(s for s in pipe["stages"] if s["name"] == "Sourced")
    assert sourced_stage["count"] == 1
    assert sourced_stage["candidates"][0]["name"] == "Candidate Alpha"
    assert sourced_stage["candidates"][0]["experience_badge"] == "5y exp"


def test_stage_transition_and_activity_audit(test_db):
    """Verifies candidate stage movement persists and records an audit log entry."""
    jid = add_job(test_db, "Fullstack Developer", "Python, React, TypeScript", location="Surat")
    _, _, cid = add_or_update_candidate(
        test_db,
        {
            "name": "Kishan Modi",
            "headline": "Software Engineer",
            "experience": "5 years in web dev",
            "evidence_text": "React, TypeScript, Node.js development.",
            "status": "Sourced",
        },
        job_id=jid,
    )

    # Initial stage check
    profile_before = get_candidate_full_profile(test_db, cid, job_id=jid)
    assert profile_before["stage"] == "Sourced"

    # Transition to Interview
    ok = update_job_candidate_stage(
        test_db,
        job_id=jid,
        candidate_id=cid,
        new_status="Interview",
        actor="Lead Recruiter",
        note="Passed technical screening, scheduled panel interview.",
    )
    assert ok is True

    # Profile check after stage transition
    profile_after = get_candidate_full_profile(test_db, cid, job_id=jid)
    assert profile_after["stage"] == "Interview"

    # Activity log check
    acts = profile_after["activities"]
    assert len(acts) >= 1
    stage_act = next(a for a in acts if a["activity_type"] == "STAGE_CHANGE")
    assert "Interview" in stage_act["title"]
    assert "Passed technical screening" in stage_act["details"]
    assert stage_act["actor"] == "Lead Recruiter"


def test_add_candidate_notes_and_activity(test_db):
    """Verifies adding notes updates both candidate notes and candidate_activities table."""
    jid = add_job(test_db, "Product Designer", "Figma, UI/UX", location="Bengaluru")
    _, _, cid = add_or_update_candidate(
        test_db,
        {
            "name": "Anita Roy",
            "headline": "Lead UI/UX Designer",
            "evidence_text": "Expert in design systems and accessibility.",
            "status": "Under Review",
        },
        job_id=jid,
    )

    ok = add_candidate_note(
        test_db,
        candidate_id=cid,
        note_text="Candidate is open to contract-to-hire with 30 day notice period.",
        author="Senior Recruiter",
        job_id=jid,
    )
    assert ok is True

    profile = get_candidate_full_profile(test_db, cid, job_id=jid)
    assert "Candidate is open to contract-to-hire" in profile["notes"]
    note_act = next(a for a in profile["activities"] if a["activity_type"] == "NOTE_ADDED")
    assert "Senior Recruiter" in note_act["actor"]
    assert "30 day notice period" in note_act["details"]


def test_full_profile_five_tabs_integrity(test_db):
    """Verifies that get_candidate_full_profile supplies complete, structured data for all 5 drawer tabs."""
    jid = add_job(test_db, "Graphics Programmer", "C++, Vulkan, Shaders", location="Remote")
    _, _, cid = add_or_update_candidate(
        test_db,
        {
            "name": "Elena Rostova",
            "headline": "Senior Graphics Engineer",
            "company": "Voxel Works",
            "location": "Berlin, Germany",
            "experience": "6 years graphics programming",
            "evidence_text": "Deep expertise in Vulkan and HLSL shaders.\nBuilt cross-platform rendering pipelines.\nPortfolio: github.com/erostova",
            "status": "Sourced",
            "email": "elena@example.com",
            "portfolio_url": "https://github.com/erostova",
        },
        job_id=jid,
    )

    profile = get_candidate_full_profile(test_db, cid, job_id=jid)
    assert profile is not None

    # Tab 1: Overview
    assert profile["name"] == "Elena Rostova"
    assert profile["company"] == "Voxel Works"
    assert profile["location"] == "Berlin, Germany"
    assert "6Y" in profile["total_experience_str"]
    assert profile["contacts"]["email"] == "elena@example.com"
    assert len(profile["highlights"]) > 0

    # Tab 2: Analysis
    assert profile["analysis"]["job_id"] == jid
    assert "Graphics Programmer" in profile["analysis"]["job_title"]
    assert len(profile["analysis"]["evidence_quotes"]) > 0

    # Tab 3: Resume
    assert profile["resume"]["has_resume"] is False  # No uploaded document yet
    assert profile["resume"]["resume_text"] == ""

    # Tab 4: Activity
    assert isinstance(profile["activities"], list)

    # Tab 5: Associated Jobs
    assert len(profile["associated_jobs"]) == 1
    assert profile["associated_jobs"][0]["job_id"] == jid
    assert profile["associated_jobs"][0]["stage"] == "Sourced"


def test_api_pipeline_endpoints(client):
    """Tests live FastAPI endpoints for pipeline retrieval and stage updates."""
    # 1. Fetch pipeline for job #1
    res = client.get("/api/jobs/1/pipeline")
    assert res.status_code == 200
    data = res.json()
    assert "stages" in data
    assert len(data["stages"]) == 8
    assert data["total_candidates"] >= 1

    # 2. Fetch full profile for candidate #1
    p_res = client.get("/api/candidates/1/full-profile?job_id=1")
    assert p_res.status_code == 200
    p_data = p_res.json()
    assert p_data["name"] == "Maya Patel"
    assert len(p_data["work_experiences"]) >= 1
    assert len(p_data["highlights"]) >= 1

    # 3. Patch stage transition
    patch_res = client.patch(
        "/api/jobs/1/candidates/1/stage",
        json={"stage": "Replied", "note": "Candidate replied via email expressing interest."},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["stage"] == "Replied"

    # Verify stage updated in profile
    p_res2 = client.get("/api/candidates/1/full-profile?job_id=1")
    assert p_res2.json()["stage"] == "Replied"

    # 4. Add recruiter note
    note_res = client.post(
        "/api/candidates/1/notes",
        json={"note": "Portfolio review passed with top remarks.", "author": "Hiring Manager", "job_id": 1},
    )
    assert note_res.status_code == 200

    # Restore stage back to Contacted
    client.patch("/api/jobs/1/candidates/1/stage", json={"stage": "Contacted", "note": "Reset to original test stage."})
