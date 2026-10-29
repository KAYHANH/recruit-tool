from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from db import add_job, init_db, list_strategy_versions
from groq_reasoning import (
    APPROVED_TOOL_NAMES,
    ArgumentValidationError,
    GroqToolCallingOrchestrator,
    JobRequirements,
    analyze_profile_intelligence,
    assist_deduplication_with_groq,
    calibrate_sourcing_from_feedback,
    explain_candidate_match_with_groq,
    plan_search_reasoning,
    validate_tool_call,
)


# ==============================================================================
# 1. TOOL CALL VALIDATION TESTS
# ==============================================================================

def test_validate_tool_call_valid():
    """Validates that legitimate tool names and arguments pass validation."""
    for tool_name in APPROVED_TOOL_NAMES:
        args = {"keywords": "fastapi python", "limit": 5, "location": "Remote"}
        valid = validate_tool_call(tool_name, args)
        assert valid["keywords"] == "fastapi python"
        assert valid["limit"] == 5
        assert valid["location"] == "Remote"


def test_validate_tool_call_unapproved_tool():
    """Verifies unapproved tool names raise ArgumentValidationError."""
    with pytest.raises(ArgumentValidationError, match="Unauthorized tool"):
        validate_tool_call("execute_shell_command", {"keywords": "test"})

    with pytest.raises(ArgumentValidationError, match="Unauthorized tool"):
        validate_tool_call("query_raw_sql", {"keywords": "test"})


def test_validate_tool_call_missing_keywords():
    """Verifies that missing or empty keywords argument is rejected."""
    with pytest.raises(ArgumentValidationError, match="Missing required 'keywords' parameter"):
        validate_tool_call("search_github", {})

    with pytest.raises(ArgumentValidationError, match="Missing required 'keywords' parameter"):
        validate_tool_call("search_github", {"keywords": "   "})


def test_validate_tool_call_overly_long_keywords():
    """Verifies that overly long keywords (>200 chars) are safely clamped to 200 chars."""
    long_kw = "python " * 35
    valid = validate_tool_call("search_github", {"keywords": long_kw})
    assert len(valid["keywords"]) <= 200


def test_validate_tool_call_control_characters():
    """Verifies that newlines and injection characters in keywords are sanitized."""
    valid = validate_tool_call("search_github", {"keywords": "python\n--rm -rf /; select *"})
    assert "\n" not in valid["keywords"]
    assert "--" not in valid["keywords"]
    assert ";" not in valid["keywords"]


def test_validate_tool_call_limit_bounds():
    """Verifies limit parameter is clamped within 1 to 10."""
    valid_low = validate_tool_call("search_github", {"keywords": "rust", "limit": -5})
    assert valid_low["limit"] == 1

    valid_high = validate_tool_call("search_github", {"keywords": "rust", "limit": 50})
    assert valid_high["limit"] == 10

    valid_invalid_type = validate_tool_call("search_github", {"keywords": "rust", "limit": "not_an_int"})
    assert valid_invalid_type["limit"] == 5


def test_validate_tool_call_location_sanitization():
    """Verifies location argument is stripped and length-bounded."""
    valid = validate_tool_call(
        "search_github",
        {"keywords": "golang", "location": "  San Francisco, CA  "}
    )
    assert valid["location"] == "San Francisco, CA"

    long_loc = "A" * 150
    valid_long = validate_tool_call(
        "search_github",
        {"keywords": "golang", "location": long_loc}
    )
    assert len(valid_long["location"]) <= 100


# ==============================================================================
# 2. TOOL CALLING ORCHESTRATOR & RECURSION LIMITS
# ==============================================================================

def test_groq_orchestrator_max_turns_limit():
    """Verifies the multi-turn agent halts at max_turns (3) even if model loops."""
    mock_connector = MagicMock()
    mock_connector.search.return_value = MagicMock(candidates=[], total_found=0)

    connectors = {"github": mock_connector}
    orchestrator = GroqToolCallingOrchestrator(connectors=connectors, max_turns=3)

    reqs = JobRequirements(
        job_title="React Engineer",
        required_skills=["React"],
        tools_and_tech=[],
        location="Remote",
    )

    # Mock Groq always requesting a tool call
    always_request_tool = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Searching...",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "search_github",
                                "arguments": json.dumps({"keywords": "react", "limit": 3}),
                            },
                        }
                    ],
                }
            }
        ]
    }

    with patch("groq_reasoning.resolve_groq_api_key", return_value="gsk_test"):
        with patch("groq_reasoning.call_groq_chat_completion", return_value=(True, always_request_tool, None)) as mock_call:
            profiles, audit, summary = orchestrator.run_sourcing_session(reqs)
            assert len(audit) == 3
            assert mock_call.call_count == 3


def test_groq_orchestrator_handles_connector_error():
    """Verifies orchestrator continues safely if a connector search raises an error."""
    mock_connector = MagicMock()
    mock_connector.search.side_effect = RuntimeError("Network timeout")

    connectors = {"github": mock_connector}
    orchestrator = GroqToolCallingOrchestrator(connectors=connectors, max_turns=3)

    reqs = JobRequirements(
        job_title="Django Engineer",
        required_skills=["Django"],
        tools_and_tech=[],
        location="Remote",
    )

    tool_call_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Searching...",
                    "tool_calls": [
                        {
                            "id": "call_err",
                            "type": "function",
                            "function": {
                                "name": "search_github",
                                "arguments": json.dumps({"keywords": "django", "limit": 3}),
                            },
                        }
                    ],
                }
            }
        ]
    }
    final_text_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Completed search after handling error.",
                    "tool_calls": None,
                }
            }
        ]
    }

    with patch("groq_reasoning.resolve_groq_api_key", return_value="gsk_test"):
        with patch("groq_reasoning.call_groq_chat_completion", side_effect=[
            (True, tool_call_response, None),
            (True, final_text_response, None),
        ]):
            profiles, audit, summary = orchestrator.run_sourcing_session(reqs)
            assert len(audit) == 1
            assert audit[0]["status"] == "FAILED"


# ==============================================================================
# 3. SEARCH PLANNING WITH GROQ REASONING & FALLBACK
# ==============================================================================

def test_plan_search_reasoning_success():
    """Verifies successful search planning with structured output from Groq."""
    reqs = JobRequirements(
        job_title="Senior Backend Engineer",
        required_skills=["Python", "PostgreSQL", "FastAPI"],
        tools_and_tech=["Docker", "Redis"],
        location="Remote",
    )

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "primary_query": '"Senior Backend Engineer" (Python AND FastAPI AND PostgreSQL) -jobs',
                        "alternative_queries": ['site:github.com "FastAPI" "PostgreSQL"'],
                        "negative_keywords": ["-jobs", "-careers", "-intern"],
                        "broadened_queries": ['"Backend Engineer" Python Remote'],
                        "target_platforms": ["GitHub", "LinkedIn Profiles"],
                        "strategy_rationale": "High-intent queries focusing on modern Python web stack.",
                    })
                }
            }
        ]
    }

    with patch("groq_reasoning.resolve_groq_api_key", return_value="gsk_test_123"):
        with patch("groq_reasoning.call_groq_chat_completion", return_value=(True, mock_response, None)):
            plan = plan_search_reasoning(reqs)
            assert plan["primary_query"].startswith('"Senior Backend Engineer"')
            assert len(plan["negative_keywords"]) >= 3
            assert "GitHub" in plan["target_platforms"]


def test_plan_search_reasoning_fallback_when_api_missing():
    """Verifies deterministic fallback strategy when Groq API key is not configured."""
    reqs = JobRequirements(
        job_title="DevOps Specialist",
        required_skills=["Kubernetes", "Terraform"],
        tools_and_tech=["AWS"],
        location="Bengaluru",
    )

    with patch("groq_reasoning.resolve_groq_api_key", return_value=""):
        plan = plan_search_reasoning(reqs)
        assert "DevOps Specialist" in plan["primary_query"]
        assert "-jobs" in plan["negative_keywords"]
        assert len(plan["alternative_queries"]) > 0


# ==============================================================================
# 4. CANDIDATE MATCH EXPLANATION (QUALITATIVE AI REASONING)
# ==============================================================================

def test_explain_candidate_match_with_groq_success():
    """Verifies evidence-backed qualitative explanation generation from Groq."""
    cand = {
        "name": "David Miller",
        "headline": "Lead Systems Architect",
        "location": "Berlin, Germany",
        "evidence_text": "Architected distributed event pipelines with Kafka and Go. Contributed to open source Go microservices.",
    }
    reqs = JobRequirements(
        job_title="Go Backend Architect",
        required_skills=["Go", "Kafka", "Distributed Systems"],
        tools_and_tech=["Docker"],
        location="Berlin",
    )

    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "summary": "David demonstrates direct architectural experience with Go and Kafka.",
                        "strong_signals": ["Distributed systems architecture", "Kafka pipeline design in Go"],
                        "missing_or_uncertain": ["Docker containerization not explicitly mentioned in excerpt"],
                        "contradictions": [],
                        "evidence_verdict": "High Match",
                        "uncertainty_flags": [],
                    })
                }
            }
        ]
    }

    with patch("groq_reasoning.resolve_groq_api_key", return_value="gsk_test_key"):
        with patch("groq_reasoning.call_groq_chat_completion", return_value=(True, mock_resp, None)):
            expl = explain_candidate_match_with_groq(cand, reqs)
            assert expl["evidence_verdict"] == "High Match"
            assert "Kafka" in expl["strong_signals"][1]
            assert "Docker" in expl["missing_or_uncertain"][0]


def test_explain_candidate_match_privacy_check():
    """Verifies that private recruiter notes and database identifiers are NOT transmitted to Groq."""
    cand = {
        "id": 9999,
        "name": "Jane Smith",
        "headline": "Fullstack Engineer",
        "private_recruiter_notes": "Internal note: Negotiating salary, current CTC $120k",
        "resume_full_pdf_binary": b"confidential_data_blob",
        "evidence_text": "GitHub profile with active React and Node repositories.",
        "location": "Toronto",
    }
    reqs = JobRequirements(
        job_title="Fullstack Developer",
        required_skills=["React", "Node.js"],
        tools_and_tech=[],
        location="Toronto",
    )

    captured_messages = []

    def fake_call(messages, **kwargs):
        captured_messages.extend(messages)
        return (False, None, "Simulated call end")

    with patch("groq_reasoning.resolve_groq_api_key", return_value="gsk_test"):
        with patch("groq_reasoning.call_groq_chat_completion", side_effect=fake_call):
            explain_candidate_match_with_groq(cand, reqs)

    # Check payload contents
    payload_str = json.dumps(captured_messages)
    assert "Negotiating salary" not in payload_str
    assert "confidential_data_blob" not in payload_str
    assert "React" in payload_str


def test_explain_candidate_match_fallback_on_429():
    """Verifies that HTTP 429 quota exhaustion triggers graceful local heuristic fallback."""
    cand = {
        "name": "Priya Sharma",
        "evidence_text": "Expert in Python, FastAPI, and PostgreSQL database optimization.",
    }
    reqs = JobRequirements(
        job_title="Python Developer",
        required_skills=["Python", "FastAPI", "PostgreSQL"],
        tools_and_tech=[],
        location="Remote",
    )

    with patch("groq_reasoning.resolve_groq_api_key", return_value="gsk_test"):
        with patch("groq_reasoning.call_groq_chat_completion", return_value=(False, None, "HTTP 429: Rate limit reached")):
            expl = explain_candidate_match_with_groq(cand, reqs)
            assert "Priya Sharma" in expl["summary"]
            assert expl["evidence_verdict"] == "Moderate Match"
            assert len(expl["strong_signals"]) == 3


# ==============================================================================
# 5. DEDUPLICATION ASSISTANCE (PROBABILISTIC REASONING)
# ==============================================================================

def test_assist_deduplication_identical_links():
    """Verifies identity match assistance when deterministic URLs match."""
    cand_a = {
        "name": "Alex Johnson",
        "github_url": "https://github.com/alexj",
        "profile_url": "https://linkedin.com/in/alex-johnson",
    }
    cand_b = {
        "name": "Alex J.",
        "github_url": "https://github.com/alexj",
        "profile_url": "",
    }

    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "is_likely_same_person": True,
                        "confidence": 0.98,
                        "shared_signals": ["Exact matching GitHub URL"],
                        "conflicting_signals": [],
                        "rationale": "High-confidence identity match via deterministic unique identifier.",
                    })
                }
            }
        ]
    }

    with patch("groq_reasoning.resolve_groq_api_key", return_value="gsk_test"):
        with patch("groq_reasoning.call_groq_chat_completion", return_value=(True, mock_resp, None)):
            res = assist_deduplication_with_groq(cand_a, cand_b)
            assert res["is_likely_same_person"] is True
            assert res["confidence"] >= 0.95


def test_assist_deduplication_never_merge_on_common_name_alone():
    """Verifies common names with conflicting profiles are NOT marked as same person."""
    cand_a = {
        "name": "David Smith",
        "profile_url": "https://github.com/dsmith-london",
        "location": "London, UK",
        "headline": "Junior Frontend Developer",
    }
    cand_b = {
        "name": "David Smith",
        "profile_url": "https://github.com/dsmith-sf",
        "location": "San Francisco, US",
        "headline": "Staff Data Engineer",
    }

    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "is_likely_same_person": False,
                        "confidence": 0.1,
                        "shared_signals": ["Common Name: David Smith"],
                        "conflicting_signals": ["Different locations (London vs San Francisco)", "Different tech domains (Frontend vs Data Engineer)"],
                        "rationale": "High likelihood of separate individuals sharing a common name.",
                    })
                }
            }
        ]
    }

    with patch("groq_reasoning.resolve_groq_api_key", return_value="gsk_test"):
        with patch("groq_reasoning.call_groq_chat_completion", return_value=(True, mock_resp, None)):
            res = assist_deduplication_with_groq(cand_a, cand_b)
            assert res["is_likely_same_person"] is False
            assert res["confidence"] <= 0.2


# ==============================================================================
# 6. RECRUITER FEEDBACK CALIBRATION & VERSION PERSISTENCE
# ==============================================================================

def test_calibrate_sourcing_from_feedback_preserves_mandatory_skills():
    """Verifies calibration never removes or overwrites mandatory requirements and saves version in SQLite."""
    conn = init_db(":memory:")

    job_id = add_job(
        conn=conn,
        title="Full Stack Engineer",
        jd_text="Seeking Senior Full Stack Engineer with React, Python, and PostgreSQL.",
        location="Remote",
    )

    reqs = JobRequirements(
        job_title="Full Stack Engineer",
        required_skills=["React", "Python", "PostgreSQL"],
        tools_and_tech=["Docker"],
        location="Remote",
    )

    feedback_items = [
        {"rating": "Irrelevant", "feedback_text": "Too junior, lacks PostgreSQL depth", "candidate_name": "Junior Dev"},
        {"rating": "Relevant", "feedback_text": "Strong Python and React", "candidate_name": "Alex Tech"},
    ]

    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "strategy_name": "Seniority Focus v2",
                        "changes_summary": "Added negative filters for junior and intern roles.",
                        "adjusted_keywords": "React Python PostgreSQL senior lead",
                        "negative_keywords": "-junior -intern -entry -graduate",
                        "source_priorities": {"github": "High", "groq_browser": "High"},
                        "preserved_mandatory_skills": ["React", "Python", "PostgreSQL"],
                    })
                }
            }
        ]
    }

    with patch("groq_reasoning.resolve_groq_api_key", return_value="gsk_test"):
        with patch("groq_reasoning.call_groq_chat_completion", return_value=(True, mock_resp, None)):
            cal = calibrate_sourcing_from_feedback(conn, job_id, feedback_items, reqs)

            # 1. Mandatory skills must remain strictly intact
            assert cal["preserved_mandatory_skills"] == ["React", "Python", "PostgreSQL"]
            assert "-junior" in cal["negative_keywords"]

            # 2. Must be persisted in SQLite sourcing_strategy_versions
            versions = list_strategy_versions(conn, job_id)
            assert len(versions) == 1
            assert versions[0]["strategy_name"] == "Seniority Focus v2"
            assert versions[0]["version_number"] == 1
            assert "-junior" in versions[0]["negative_keywords"]


def test_calibrate_sourcing_fallback_when_offline():
    """Verifies offline feedback calibration works and successfully stores version."""
    conn = init_db(":memory:")

    job_id = add_job(
        conn=conn,
        title="Rust Core Engineer",
        jd_text="Rust systems engineer",
        location="",
    )

    reqs = JobRequirements(
        job_title="Rust Core Engineer",
        required_skills=["Rust", "Tokio"],
        tools_and_tech=[],
        location="",
    )

    with patch("groq_reasoning.resolve_groq_api_key", return_value=""):
        cal = calibrate_sourcing_from_feedback(conn, job_id, [], reqs)
        assert cal["version_id"] > 0

        versions = list_strategy_versions(conn, job_id)
        assert len(versions) == 1
        assert "Rust" in versions[0]["adjusted_keywords"]


# ==============================================================================
# 6. PROFILE INTELLIGENCE TESTS
# ==============================================================================

def test_analyze_profile_intelligence_mocked_success():
    """Verifies that analyze_profile_intelligence parses structured skills and vanity metrics."""
    mock_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "supported_skills": [
                            {"skill": "FastAPI", "evidence": "Built async REST microservices handling 10k rps", "confidence": "high"},
                            {"skill": "React", "evidence": "Developed responsive dashboard using hooks", "confidence": "high"},
                        ],
                        "projects": [
                            {"name": "FleetOps", "description": "IoT fleet telematics platform", "technologies": ["Python", "Docker"]}
                        ],
                        "tenure_signals": ["5+ years professional experience"],
                        "public_contact_or_links": ["https://github.com/johndoe", "john@example.com"],
                        "vanity_signals": ["1200 followers on GitHub (non-technical vanity signal)"],
                        "uncertainty_flags": ["No public mentions of Kubernetes despite Docker use"],
                    })
                }
            }
        ]
    }

    reqs = JobRequirements(
        job_title="Full Stack Engineer",
        required_skills=["FastAPI", "React"],
        tools_and_tech=["Docker"],
        location="Remote",
    )

    evidence_text = "John Doe. Senior Engineer with 5+ years experience. Built FleetOps using Python and Docker. 1200 followers."

    with patch("groq_reasoning.resolve_groq_api_key", return_value="gsk_test"):
        with patch("groq_reasoning.call_groq_chat_completion", return_value=(True, mock_resp, None)):
            res = analyze_profile_intelligence(evidence_text, reqs)
            assert len(res["supported_skills"]) == 2
            assert res["supported_skills"][0]["skill"] == "FastAPI"
            assert "FleetOps" in res["projects"][0]["name"]
            assert len(res["vanity_signals"]) == 1
            assert "1200 followers" in res["vanity_signals"][0]
            assert "https://github.com/johndoe" in res["public_contact_or_links"]


def test_analyze_profile_intelligence_fallback_offline():
    """Verifies offline heuristic extraction of skills, contacts, tenure, and vanity metrics."""
    reqs = JobRequirements(
        job_title="Backend Engineer",
        required_skills=["Python", "PostgreSQL"],
        tools_and_tech=["Docker"],
        location="Remote",
    )

    sample_text = (
        "Alice Smith (alice@example.org, https://github.com/alicesmith). "
        "Over 4 years of experience working with Python and PostgreSQL in production. "
        "Has 500 followers and 10 starred repos."
    )

    with patch("groq_reasoning.resolve_groq_api_key", return_value=""):
        res = analyze_profile_intelligence(sample_text, reqs)
        # Verify offline extracted skills
        skills_found = [s["skill"] for s in res["supported_skills"]]
        assert "Python" in skills_found or "PostgreSQL" in skills_found

        # Verify extracted contact and links
        assert any("alice@example.org" in link for link in res["public_contact_or_links"])
        assert any("https://github.com/alicesmith" in link for link in res["public_contact_or_links"])

        # Verify tenure signal extracted
        assert any("4 years" in ts for ts in res["tenure_signals"])

        # Verify vanity signals detected
        assert any("followers" in vs for vs in res["vanity_signals"])

