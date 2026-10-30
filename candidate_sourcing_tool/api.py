from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

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
    create_search_run,
    update_search_run,
    get_search_run,
    list_search_runs,
    record_recruiter_feedback,
    get_recruiter_feedback,
    export_shortlist_csv_safe,
    get_pipeline_data,
    update_job_candidate_stage,
    add_candidate_activity,
    add_candidate_note,
    get_candidate_full_profile,
    list_strategy_versions,
    save_strategy_version,
    get_search_tasks,
)
from groq_extractor import (
    DEFAULT_GROQ_MODEL,
    extract_requirements_with_groq,
    get_groq_api_key,
    get_groq_model,
    resolve_groq_api_key,
    run_groq_live_smoke_test,
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
    ScoringWeights,
    evaluate_candidate,
    sanitize_csv_cell,
    sanitize_dataframe_for_csv,
)
from query_generator import SearchQuery, generate_search_queries
from search_provider import GitHubCandidateResult, GitHubSearchProvider
from title_extractor import TitleExtractionResult, extract_job_title, resolve_safe_title
from search_orchestrator import SearchOrchestrator
from source_connectors import (
    GitHubConnector,
    GitLabConnector,
    HuggingFaceConnector,
    LocalDatabaseConnector,
    StackExchangeConnector,
)
from groq_browser_connector import GROQ_SEARCH_MODEL, GroqBrowserSearchConnector
from cost_guard import cost_guard
from talent_pool_mapper import talent_pool_mapper
from search_engine_planner import search_engine_planner
from groq_reasoning import (
    analyze_profile_intelligence,
    assist_deduplication_with_groq,
    calibrate_sourcing_from_feedback,
    explain_candidate_match_with_groq,
    plan_search_reasoning,
)

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("CANDIDATE_SOURCING_DB_PATH", APP_DIR / "candidate_sourcing.db"))

def set_db_path(new_path: Path | str):
    """Sets a new database path and reinitializes the global connection (used for isolated tests)."""
    global DB_PATH, conn
    DB_PATH = Path(new_path)
    conn = init_db(DB_PATH)
    return conn

app = FastAPI(
    title="Candidate Finder API",
    description="Local-first recruitment sourcing API with strict ₹0 budget guarantee",
    version="0.5.0",
)

# Configure CORS for local frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect to database and ensure migrations
conn = init_db(DB_PATH)


# --- Pydantic Models ---

class JobCreate(BaseModel):
    title: str = Field(..., min_length=1)
    jd_text: str = Field(..., min_length=1)
    location: Optional[str] = ""
    extracted_data: Optional[str] = ""


class JobUpdate(BaseModel):
    title: Optional[str] = None
    jd_text: Optional[str] = None
    location: Optional[str] = None
    extracted_data: Optional[str] = None


class AnalyzeRequest(BaseModel):
    jd_text: str = Field(..., min_length=1)
    engine: str = Field(default="local")  # "local" or "groq"
    groq_model: Optional[str] = None
    session_key: Optional[str] = None


class CandidateCreate(BaseModel):
    name: str = Field(..., min_length=1)
    profile_url: Optional[str] = ""
    github_url: Optional[str] = ""
    portfolio_url: Optional[str] = ""
    headline: Optional[str] = ""
    company: Optional[str] = ""
    location: Optional[str] = ""
    experience: Optional[str] = ""
    source: Optional[str] = "Manual entry"
    evidence_text: str = Field(..., min_length=1)
    notes: Optional[str] = ""
    status: Optional[str] = "New"
    email: Optional[str] = ""
    phone: Optional[str] = ""
    contact_provenance: Optional[str] = ""
    contact_status: Optional[str] = ""
    job_id: Optional[int] = None


class CandidateUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    headline: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class StageUpdate(BaseModel):
    stage: str = Field(..., min_length=1)
    note: Optional[str] = ""
    actor: Optional[str] = "Recruiter"


class CandidateNoteCreate(BaseModel):
    note: str = Field(..., min_length=1)
    author: Optional[str] = "Recruiter"
    job_id: Optional[int] = None


class CandidateActivityCreate(BaseModel):
    activity_type: str = Field(default="NOTE_ADDED")
    title: str = Field(..., min_length=1)
    details: Optional[str] = ""
    actor: Optional[str] = "Recruiter"
    job_id: Optional[int] = None


class GitHubSearchRequest(BaseModel):
    keywords: str = Field(..., min_length=1)
    location: Optional[str] = ""
    limit: Optional[int] = Field(default=5, ge=1, le=10)


class LogSearchRequest(BaseModel):
    query_text: str = Field(..., min_length=1)
    strategy: Optional[str] = ""
    provider: Optional[str] = "Browser (Google/Bing)"


class ScoringWeightsInput(BaseModel):
    core_skills: int = 40
    tools: int = 25
    role_alignment: int = 15
    location: int = 10
    portfolio: int = 10


class RankRequest(BaseModel):
    target_location: Optional[str] = ""
    weights: Optional[ScoringWeightsInput] = None
    include_all_candidates: bool = False
    status_filter: Optional[str] = None


class StartRunRequest(BaseModel):
    job_id: int
    enabled_sources: Optional[list[str]] = ["github", "gitlab", "stackoverflow", "huggingface", "local_db", "groq_browser"]
    limit_per_source: Optional[int] = Field(default=5, ge=1, le=10)
    strategy_keys: Optional[list[str]] = None


class ExecuteXRayRequest(BaseModel):
    strategy_keys: Optional[list[str]] = None
    max_strategies: Optional[int] = 7
    limit_per_strategy: Optional[int] = 3
    enabled_sources: Optional[list[str]] = None


class RecruiterFeedbackCreate(BaseModel):
    rating: str = Field(..., min_length=1)
    feedback_text: Optional[str] = ""
    job_id: Optional[int] = None


class DedupCheckRequest(BaseModel):
    candidate_a: dict[str, Any]
    candidate_b: dict[str, Any]


class CalibrateFeedbackRequest(BaseModel):
    feedback_items: Optional[list[dict[str, Any]]] = None


class ExplainMatchRequest(BaseModel):
    job_id: int


class ProfileIntelligenceRequest(BaseModel):
    job_id: Optional[int] = None



# --- Health & Overview Endpoints ---

@app.get("/api/health")
def get_health() -> dict[str, Any]:
    """Health check endpoint confirming database status."""
    return {
        "status": "healthy",
        "service": "Candidate Finder API",
        "version": "0.5.0",
        "database": DB_PATH.name,
        "zero_budget_spend": "₹0.00",
    }


@app.get("/api/overview")
def get_overview_dashboard() -> dict[str, Any]:
    """Retrieves live aggregate metrics for the Overview Dashboard."""
    m = get_dashboard_metrics(conn)
    return {
        "total_jobs": m["total_jobs"],
        "total_candidates": m["total_candidates"],
        "needing_review": m["needing_review"],
        "shortlisted": m["shortlisted"],
        "recent_jobs": [dict(j) for j in m["recent_jobs"]],
        "recent_candidates": [dict(c) for c in m["recent_candidates"]],
        "recent_searches": [dict(s) for s in m["recent_searches"]],
    }


# --- Jobs Endpoints ---

@app.get("/api/jobs")
def get_jobs() -> list[dict[str, Any]]:
    """Lists all saved jobs ordered by creation date."""
    jobs = list_jobs(conn)
    result = []
    for j in jobs:
        row = dict(j)
        cands_count = len(list_candidates(conn, job_id=row["id"]))
        row["candidate_count"] = cands_count
        result.append(row)
    return result


@app.post("/api/jobs", status_code=status.HTTP_201_CREATED)
def create_new_job(payload: JobCreate) -> dict[str, Any]:
    """Saves a new job description to SQLite."""
    jid = add_job(
        conn,
        title=payload.title,
        jd_text=payload.jd_text,
        extracted_data=payload.extracted_data or "",
        location=payload.location or "",
    )
    job = get_job(conn, jid)
    if not job:
        raise HTTPException(status_code=500, detail="Failed to retrieve created job.")
    return dict(job)


@app.get("/api/jobs/{job_id}")
def get_single_job(job_id: int) -> dict[str, Any]:
    """Retrieves a single job by ID."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")
    res = dict(job)
    res["candidate_count"] = len(list_candidates(conn, job_id=job_id))
    return res


@app.patch("/api/jobs/{job_id}")
def update_job_details(job_id: int, payload: JobUpdate) -> dict[str, Any]:
    """Updates an existing job's title, location, text, or extracted requirements."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

    extracted_data_str = payload.extracted_data
    # Reconcile job.title with extracted_data.job_title so search queries stay in sync
    if payload.title:
        try:
            curr_data = json.loads(payload.extracted_data or job["extracted_data"] or "{}")
            if curr_data and isinstance(curr_data, dict):
                curr_data["job_title"] = payload.title
                extracted_data_str = json.dumps(curr_data)
        except Exception:
            pass

    update_job(
        conn,
        job_id=job_id,
        title=payload.title,
        jd_text=payload.jd_text,
        location=payload.location,
        extracted_data=extracted_data_str,
    )
    updated = get_job(conn, job_id)
    return dict(updated)


@app.delete("/api/jobs/{job_id}")
def delete_single_job(job_id: int) -> dict[str, Any]:
    """Deletes a job and its candidate associations."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")
    delete_job(conn, job_id)
    return {"message": f"Job #{job_id} deleted successfully."}


# --- JD Document Parsing & Requirement Analysis ---

@app.post("/api/parse-document")
async def parse_jd_file(file: UploadFile = File(...)) -> dict[str, Any]:
    """Parses text from an uploaded PDF, DOCX, TXT, or Markdown document."""
    # Size check: 10MB limit
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File exceeds maximum size limit of 10MB.")

    filename = file.filename or "uploaded_document"
    ext = Path(filename).suffix.lower()
    if ext not in {".pdf", ".docx", ".txt", ".md"}:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload PDF, DOCX, TXT, or MD.")

    try:
        parsed_text = parse_document(content, filename)
        return {
            "filename": filename,
            "text": parsed_text,
            "character_count": len(parsed_text),
        }
    except ScannedOrEmptyPdfError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except DocumentParsingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected parsing error: {exc}")


def _format_requirements_dict(reqs: JobRequirements) -> dict[str, Any]:
    """Ensures requirements dictionary supports both backend and frontend field naming conventions."""
    d = reqs.to_dict()
    # Provide frontend-expected aliases
    d["core_skills"] = d.get("required_skills", [])
    d["required_skills"] = d.get("required_skills", [])
    d["tools_and_technologies"] = d.get("tools_and_tech", [])
    d["tools_and_tech"] = d.get("tools_and_tech", [])
    d["domain_keywords"] = d.get("inferred_keywords", [])
    d["inferred_keywords"] = d.get("inferred_keywords", [])
    d["education"] = d.get("education_or_certifications", [])
    d["education_or_certifications"] = d.get("education_or_certifications", [])
    return d


@app.post("/api/analyze-jd")
def analyze_job_description(req: AnalyzeRequest) -> dict[str, Any]:
    """Extracts structured requirements from JD text using Local Extractor or Groq AI."""
    raw_text = clean_text(req.jd_text)
    if not raw_text:
        raise HTTPException(status_code=400, detail="Job description text is empty.")

    engine = req.engine.lower().strip()
    active_model = get_groq_model(override_model=req.groq_model)

    if engine == "groq":
        ok, groq_reqs, msg = extract_requirements_with_groq(
            jd_text=raw_text,
            api_key=req.session_key,
            model=active_model,
        )
        if ok and groq_reqs:
            title_res = TitleExtractionResult(
                title=groq_reqs.job_title,
                alternative_titles=groq_reqs.alternative_titles,
                confidence_score=0.98,
                confidence_level="High",
                detected_candidates=[groq_reqs.job_title] + groq_reqs.alternative_titles,
            )
            return {
                "engine": "groq",
                "model": active_model,
                "message": msg,
                "requirements": _format_requirements_dict(groq_reqs),
                "title_extraction": {
                    "title": title_res.title,
                    "alternative_titles": title_res.alternative_titles,
                    "confidence_score": title_res.confidence_score,
                    "confidence_level": title_res.confidence_level,
                },
            }
        else:
            # Fall back safely to local extractor
            local_reqs = extract_requirements(raw_text)
            title_res = extract_job_title(raw_text)
            return {
                "engine": "local_fallback",
                "model": "rule_based_local",
                "message": f"{msg} (Fell back to local offline extractor)",
                "requirements": _format_requirements_dict(local_reqs),
                "title_extraction": {
                    "title": title_res.title,
                    "alternative_titles": title_res.alternative_titles,
                    "confidence_score": title_res.confidence_score,
                    "confidence_level": title_res.confidence_level,
                },
            }
    else:
        # Default Local Offline Extractor
        local_reqs = extract_requirements(raw_text)
        title_res = extract_job_title(raw_text)
        return {
            "engine": "local",
            "model": "rule_based_local",
            "message": "Extracted requirements 100% locally with zero external network calls.",
            "requirements": _format_requirements_dict(local_reqs),
            "title_extraction": {
                "title": title_res.title,
                "alternative_titles": title_res.alternative_titles,
                "confidence_score": title_res.confidence_score,
                "confidence_level": title_res.confidence_level,
            },
        }


# --- Sourcing & Search Queries Endpoints ---

@app.get("/api/jobs/{job_id}/queries")
def get_job_search_queries(job_id: int) -> dict[str, Any]:
    """Generates varied Boolean and Google/Bing X-Ray queries for a saved job."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

    if job["extracted_data"]:
        try:
            reqs = JobRequirements.from_dict(json.loads(job["extracted_data"]))
        except Exception:
            reqs = extract_requirements(job["jd_text"])
    else:
        reqs = extract_requirements(job["jd_text"])

    reqs.job_title = resolve_safe_title(reqs.job_title, jd_text=job["jd_text"])
    queries = generate_search_queries(reqs, user_location=job["location"] or reqs.location)
    history = get_search_history(conn, job_id=job_id)

    queries_data = []
    for q in queries:
        is_rep, rep_time = is_query_repeated(conn, job_id, q.query_text)
        queries_data.append({
            "id": q.id,
            "label": q.label,
            "strategy": q.strategy,
            "query_text": q.query_text,
            "description": q.description,
            "google_url": q.google_url,
            "bing_url": q.bing_url,
            "is_repeated": is_rep,
            "last_executed_at": rep_time,
        })

    return {
        "job_id": job_id,
        "job_title": reqs.job_title,
        "target_location": job["location"] or reqs.location,
        "queries": queries_data,
        "history_count": len(history),
    }


@app.post("/api/jobs/{job_id}/log-search")
def log_job_search(job_id: int, payload: LogSearchRequest) -> dict[str, Any]:
    """Logs an executed search query to the job's search history."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

    hid = add_search_history(
        conn,
        job_id=job_id,
        query_text=payload.query_text,
        strategy=payload.strategy or "",
        provider=payload.provider or "Browser (Google/Bing)",
        status="Opened in Browser",
    )
    return {"message": "Search logged to history.", "history_id": hid}


@app.get("/api/jobs/{job_id}/search-history")
def get_job_search_history(job_id: int) -> list[dict[str, Any]]:
    """Returns past search queries executed for a job."""
    rows = get_search_history(conn, job_id=job_id)
    return [dict(r) for r in rows]


class LaunchBatchRequest(BaseModel):
    max_queries: Optional[int] = 4
    strategy_keys: Optional[list[str]] = None


@app.get("/api/jobs/{job_id}/xray-plan")
def get_job_xray_plan(job_id: int) -> dict[str, Any]:
    """Generates the integrated 7-strategy Google X-Ray & Boolean search plan (Strategies A through G)."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

    if job["extracted_data"]:
        try:
            reqs = JobRequirements.from_dict(json.loads(job["extracted_data"]))
        except Exception:
            reqs = extract_requirements(job["jd_text"])
    else:
        reqs = extract_requirements(job["jd_text"])

    reqs.job_title = resolve_safe_title(reqs.job_title, jd_text=job["jd_text"])
    plan = search_engine_planner.plan_job_search(
        requirements=reqs,
        job_id=job_id,
        target_location=job["location"] or reqs.location,
    )
    return plan.to_dict()


@app.post("/api/jobs/{job_id}/xray-plan/launch-batch")
def launch_job_xray_batch(job_id: int, payload: LaunchBatchRequest) -> dict[str, Any]:
    """Logs batch browser execution of X-Ray strategies and returns direct search URLs."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

    if job["extracted_data"]:
        try:
            reqs = JobRequirements.from_dict(json.loads(job["extracted_data"]))
        except Exception:
            reqs = extract_requirements(job["jd_text"])
    else:
        reqs = extract_requirements(job["jd_text"])

    reqs.job_title = resolve_safe_title(reqs.job_title, jd_text=job["jd_text"])
    plan = search_engine_planner.plan_job_search(
        requirements=reqs,
        job_id=job_id,
        target_location=job["location"] or reqs.location,
    )

    strategies_to_launch = plan.strategies
    if payload.strategy_keys:
        strategies_to_launch = [s for s in plan.strategies if s.key in payload.strategy_keys]
    elif payload.max_queries:
        strategies_to_launch = plan.strategies[: payload.max_queries]

    launched_urls = []
    for s in strategies_to_launch:
        launched_urls.append({
            "key": s.key,
            "name": s.name,
            "google_url": s.google_url,
            "bing_url": s.bing_url,
        })
        add_search_history(
            conn=conn,
            job_id=job_id,
            query_text=s.query_text,
            strategy=f"{s.key}: {s.name}",
            provider="Browser X-Ray (Google)",
            status="Batch Launched in Browser",
        )

    return {
        "job_id": job_id,
        "job_title": plan.job_title,
        "batch_size": len(launched_urls),
        "launched_strategies": launched_urls,
        "direct_urls": [u["google_url"] for u in launched_urls],
        "message": f"Successfully prepared batch of {len(launched_urls)} X-Ray queries for browser launch.",
    }


@app.post("/api/jobs/{job_id}/xray-plan/execute")
def execute_job_xray_plan(job_id: int, payload: ExecuteXRayRequest) -> dict[str, Any]:
    """Executes X-Ray search strategies automatically via the automated discovery engine.
    Dispatches each strategy through Groq Browser Search, imports real candidates into SQLite,
    scores them against the JD, and links them to the job's Sourced stage."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

    if job["extracted_data"]:
        try:
            reqs = JobRequirements.from_dict(json.loads(job["extracted_data"]))
        except Exception:
            reqs = extract_requirements(job["jd_text"])
    else:
        reqs = extract_requirements(job["jd_text"])

    reqs.job_title = resolve_safe_title(reqs.job_title, jd_text=job["jd_text"])
    role_fam = talent_pool_mapper.detect_role_family(reqs.job_title, reqs.required_skills, job["jd_text"])
    plan = search_engine_planner.plan_job_search(
        requirements=reqs,
        job_id=job_id,
        target_location=job["location"] or reqs.location,
        role_family=role_fam,
    )

    strategies_to_run = plan.strategies
    if payload.strategy_keys:
        valid_keys = set(payload.strategy_keys)
        for k in list(valid_keys):
            if len(k) == 1:
                valid_keys.add(f"Strategy {k}")
            elif k.startswith("Strategy "):
                valid_keys.add(k.replace("Strategy ", ""))
        strategies_to_run = [s for s in plan.strategies if s.key in valid_keys or s.key.replace("Strategy ", "") in valid_keys]
    elif payload.max_strategies:
        strategies_to_run = plan.strategies[: payload.max_strategies]

    selected_keys = [s.key for s in strategies_to_run]
    enabled_srcs = payload.enabled_sources or ["groq_browser"]
    if "groq_browser" not in enabled_srcs:
        enabled_srcs.append("groq_browser")

    # Start automated search run with the specific strategies
    prog = _orchestrator.start_run(
        job_id=job_id,
        enabled_sources=enabled_srcs,
        limit_per_source=payload.limit_per_strategy or 3,
        strategy_keys=selected_keys,
    )

    return {
        "run_id": prog.run_id,
        "job_id": job_id,
        "status": prog.status,
        "current_stage": prog.current_stage,
        "progress_percent": prog.progress_percent,
        "strategies_queued": [f"{s.key}: {s.name}" for s in strategies_to_run],
        "message": f"Successfully initiated automated execution of {len(strategies_to_run)} X-Ray search strategies.",
    }


@app.post("/api/search/github")
def search_github_candidates(payload: GitHubSearchRequest) -> dict[str, Any]:
    """Performs candidate discovery using the official public GitHub API (zero cost)."""
    provider = GitHubSearchProvider()
    result = provider.search_candidates(
        keywords=payload.keywords,
        location=payload.location or "",
        num_results=payload.limit or 5,
    )
    return {
        "total_found": result.total_found,
        "rate_limited": result.rate_limited,
        "message": result.message,
        "candidates": result.candidates,
    }


# --- Candidates & Ranking Endpoints ---

@app.get("/api/candidates")
def get_candidates(
    job_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Lists candidates, optionally filtered by job association, review status, or search query."""
    cands = list_candidates(conn, job_id=job_id)
    result = []
    for c in cands:
        d = dict(c)
        if status and d.get("status") != status:
            continue
        if search:
            q = search.lower()
            name_match = q in d.get("name", "").lower()
            head_match = q in d.get("headline", "").lower()
            comp_match = q in d.get("company", "").lower()
            if not (name_match or head_match or comp_match):
                continue
        result.append(d)
    return result


@app.post("/api/candidates", status_code=status.HTTP_201_CREATED)
def create_candidate(payload: CandidateCreate) -> dict[str, Any]:
    """Saves or updates a candidate record with evidence and contact details."""
    data = payload.model_dump()
    jid = data.pop("job_id", None)
    ok, msg, cid = add_or_update_candidate(conn, data, job_id=jid)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    cand = get_candidate(conn, cid)
    return dict(cand)


@app.get("/api/candidates/{candidate_id}")
def get_single_candidate(candidate_id: int) -> dict[str, Any]:
    """Retrieves a single candidate by ID."""
    cand = get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")
    return dict(cand)


@app.patch("/api/candidates/{candidate_id}")
def update_candidate(candidate_id: int, payload: CandidateUpdate) -> dict[str, Any]:
    """Updates candidate status, notes, or contact info."""
    cand = get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")

    if payload.status:
        update_candidate_status(conn, candidate_id, payload.status)

    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    data["name"] = cand["name"]
    data["profile_url"] = cand["profile_url"]
    add_or_update_candidate(conn, data)

    updated = get_candidate(conn, candidate_id)
    return dict(updated)


@app.delete("/api/candidates/{candidate_id}")
def delete_single_candidate(candidate_id: int) -> dict[str, Any]:
    """Deletes a candidate record."""
    cand = get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")
    delete_candidate(conn, candidate_id)
    return {"message": f"Candidate #{candidate_id} deleted."}


@app.get("/api/jobs/{job_id}/pipeline")
def get_job_pipeline(job_id: int) -> dict[str, Any]:
    """Retrieves candidates grouped by the 8 Kanban pipeline stages for a specific job."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")
    return get_pipeline_data(conn, job_id)


@app.patch("/api/jobs/{job_id}/candidates/{candidate_id}/stage")
def update_candidate_stage_for_job(job_id: int, candidate_id: int, payload: StageUpdate) -> dict[str, Any]:
    """Updates a candidate's pipeline stage for a job and writes an activity audit entry."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")
    cand = get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")

    ok = update_job_candidate_stage(
        conn,
        job_id=job_id,
        candidate_id=candidate_id,
        new_status=payload.stage,
        actor=payload.actor or "Recruiter",
        note=payload.note or "",
    )
    return {
        "success": ok,
        "job_id": job_id,
        "candidate_id": candidate_id,
        "stage": payload.stage,
    }


@app.get("/api/candidates/{candidate_id}/full-profile")
def get_candidate_profile_endpoint(candidate_id: int, job_id: Optional[int] = None) -> dict[str, Any]:
    """Retrieves full candidate profile for slide-over drawer across all 5 tabs."""
    profile = get_candidate_full_profile(conn, candidate_id, job_id=job_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")
    return profile


@app.post("/api/candidates/{candidate_id}/notes")
def add_note_endpoint(candidate_id: int, payload: CandidateNoteCreate) -> dict[str, Any]:
    """Adds a recruiter note to a candidate and logs an activity entry."""
    cand = get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")
    ok = add_candidate_note(
        conn,
        candidate_id=candidate_id,
        note_text=payload.note,
        author=payload.author or "Recruiter",
        job_id=payload.job_id,
    )
    return {"success": ok, "candidate_id": candidate_id}


@app.post("/api/candidates/{candidate_id}/activities")
def add_activity_endpoint(candidate_id: int, payload: CandidateActivityCreate) -> dict[str, Any]:
    """Adds an activity event to a candidate timeline."""
    cand = get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")
    aid = add_candidate_activity(
        conn,
        candidate_id=candidate_id,
        job_id=payload.job_id,
        activity_type=payload.activity_type,
        title=payload.title,
        details=payload.details or "",
        actor=payload.actor or "Recruiter",
    )
    return {"success": True, "activity_id": aid}


@app.post("/api/jobs/{job_id}/rank")
def rank_candidates_for_job(job_id: int, payload: RankRequest) -> dict[str, Any]:
    """Ranks candidates linked to a job using deterministic heuristic evidence matching."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

    if job["extracted_data"]:
        try:
            reqs = JobRequirements.from_dict(json.loads(job["extracted_data"]))
        except Exception:
            reqs = extract_requirements(job["jd_text"])
    else:
        reqs = extract_requirements(job["jd_text"])

    weights = ScoringWeights()
    if payload.weights:
        weights = ScoringWeights(
            core_skills=payload.weights.core_skills,
            tools=payload.weights.tools,
            role_alignment=payload.weights.role_alignment,
            location=payload.weights.location,
            portfolio=payload.weights.portfolio,
        )

    target_loc = payload.target_location or job["location"] or reqs.location
    cands = list_candidates(conn) if payload.include_all_candidates else list_candidates(conn, job_id=job_id)

    evaluations = []
    for c in cands:
        c_dict = dict(c)
        if payload.status_filter and c_dict.get("status") != payload.status_filter:
            continue
        ev = evaluate_candidate(c_dict, reqs, target_location=target_loc, weights=weights)
        evaluations.append({
            "candidate": c_dict,
            "evaluation": ev.to_dict(),
        })

    # Sort descending by match score
    evaluations.sort(key=lambda x: x["evaluation"]["total_score"], reverse=True)

    return {
        "job_id": job_id,
        "job_title": reqs.job_title,
        "target_location": target_loc,
        "total_evaluated": len(evaluations),
        "results": evaluations,
    }


# --- Shortlist & CSV Export Endpoints ---

@app.get("/api/shortlist")
def get_shortlist(job_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Lists all shortlisted candidates, optionally filtered by job_id."""
    shortlisted = list_shortlisted_candidates(conn, job_id=job_id)
    return [dict(c) for c in shortlisted]


@app.post("/api/candidates/{candidate_id}/remove-shortlist")
def remove_candidate_from_shortlist(candidate_id: int) -> dict[str, Any]:
    """Removes a candidate from the shortlist (sets status to 'Under Review') without deleting record."""
    cand = get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")
    remove_from_shortlist(conn, candidate_id)
    return {"message": f"Candidate #{candidate_id} moved to 'Under Review'. Record preserved."}


@app.get("/api/export/shortlist")
def export_shortlist_csv(job_id: Optional[int] = None) -> Response:
    """Exports shortlisted candidates to a formula-injection sanitized CSV."""
    shortlisted = list_shortlisted_candidates(conn, job_id=job_id)
    if not shortlisted:
        raise HTTPException(status_code=404, detail="No shortlisted candidates found to export.")

    rows = []
    for c in shortlisted:
        d = dict(c)
        rows.append({
            "ID": d.get("id"),
            "Name": d.get("name"),
            "Headline": d.get("headline") or "",
            "Company": d.get("company") or "",
            "Location": d.get("location") or "",
            "Status": d.get("status") or "Shortlisted",
            "Public Email": d.get("email") or "Not found",
            "Public Phone": d.get("phone") or "Not found",
            "Profile URL": d.get("profile_url") or "",
            "GitHub URL": d.get("github_url") or "",
            "Contact Provenance": d.get("contact_provenance") or "",
            "Recruiter Notes": d.get("notes") or "",
            "Source": d.get("source") or "",
            "Exported At": datetime.now().isoformat(timespec="seconds"),
        })

    df = pd.DataFrame(rows)
    sanitized_df = sanitize_dataframe_for_csv(df)
    csv_bytes = sanitized_df.to_csv(index=False).encode("utf-8-sig")

    filename = f"shortlist_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# --- Automated Sourcing Engine & Run Management Endpoints ---

_orchestrator = SearchOrchestrator(DB_PATH)


@app.post("/api/search-runs", status_code=status.HTTP_201_CREATED)
def start_sourcing_run(payload: StartRunRequest) -> dict[str, Any]:
    """Initiates an asynchronous multi-source candidate sourcing run."""
    job = get_job(conn, payload.job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{payload.job_id} not found.")

    sources = payload.enabled_sources or ["github", "gitlab", "stackoverflow", "huggingface", "local_db", "groq_browser"]
    limit = payload.limit_per_source or 5

    progress = _orchestrator.start_run(
        job_id=payload.job_id,
        enabled_sources=sources,
        limit_per_source=limit,
        strategy_keys=payload.strategy_keys,
    )

    return {
        "run_id": progress.run_id,
        "job_id": progress.job_id,
        "status": progress.status,
        "current_stage": progress.current_stage,
        "progress_percent": progress.progress_percent,
        "enabled_sources": progress.enabled_sources,
        "started_at": progress.started_at,
        "message": "Automated sourcing run initiated successfully across verified zero-budget sources.",
    }


@app.get("/api/search-runs/{run_id}")
def get_sourcing_run_status(run_id: str) -> dict[str, Any]:
    """Polls real-time progress of an automated sourcing run."""
    prog = _orchestrator.get_run_status(run_id)
    if not prog:
        raise HTTPException(status_code=404, detail=f"Search run '{run_id}' not found.")

    tasks = get_search_tasks(conn, run_id)
    strategy_tasks = getattr(prog, "strategy_tasks", {}) or (prog.source_stats or {}).get("_strategy_tasks", {})
    reconciled = getattr(prog, "reconciled_counters", {}) or (prog.source_stats or {}).get("_reconciled_counters", {})

    return {
        "run_id": prog.run_id,
        "job_id": prog.job_id,
        "status": prog.status,
        "current_stage": prog.current_stage,
        "progress_percent": prog.progress_percent,
        "enabled_sources": prog.enabled_sources,
        "total_raw_found": prog.total_raw_found,
        "total_unique_found": prog.total_unique_found,
        "total_duplicates": prog.total_duplicates,
        "total_saved": prog.total_saved,
        "source_stats": prog.source_stats,
        "strategy_tasks": strategy_tasks,
        "reconciled_counters": reconciled,
        "tasks": tasks,
        "error_message": prog.error_message,
        "started_at": prog.started_at,
        "completed_at": prog.completed_at,
        "duration_seconds": prog.duration_seconds,
        "xray_plan": prog.xray_plan or {},
    }


@app.get("/api/search-runs/{run_id}/results")
def get_sourcing_run_results(run_id: str) -> dict[str, Any]:
    """Returns incremental or final discovered candidates for a search run."""
    prog = _orchestrator.get_run_status(run_id)
    if not prog:
        raise HTTPException(status_code=404, detail=f"Search run '{run_id}' not found.")

    candidates = prog.discovered_candidates
    # If in-memory candidates list is empty (e.g. server restarted), fetch from DB
    if not candidates:
        rows = conn.execute(
            """SELECT c.*, jc.match_score, jc.match_details
            FROM candidates c
            INNER JOIN job_candidates jc ON c.id = jc.candidate_id
            WHERE jc.job_id = ?
            ORDER BY jc.match_score DESC""",
            (prog.job_id,),
        ).fetchall()
        for r in rows:
            details = {}
            if r["match_details"]:
                try:
                    details = json.loads(r["match_details"])
                except Exception:
                    pass
            candidates.append({
                "id": r["id"],
                "name": r["name"],
                "headline": r["headline"],
                "location": r["location"],
                "company": r["company"],
                "profile_url": r["profile_url"],
                "github_url": r["github_url"],
                "gitlab_url": r["gitlab_url"],
                "portfolio_url": r["portfolio_url"],
                "source": r["source"],
                "email": r["email"],
                "phone": r["phone"],
                "contact_status": r["contact_status"],
                "contact_provenance": r["contact_provenance"],
                "match_score": r["match_score"],
                "status": r["status"],
                "evidence_text": r["evidence_text"],
                "evidence_ladder_tier": r["evidence_ladder_tier"] if "evidence_ladder_tier" in r.keys() else None,
                "match_details": details,
            })

    return {
        "run_id": prog.run_id,
        "job_id": prog.job_id,
        "status": prog.status,
        "candidates": candidates,
        "total_results": len(candidates),
    }


@app.post("/api/search-runs/{run_id}/cancel")
def cancel_sourcing_run(run_id: str) -> dict[str, Any]:
    """Requests immediate cancellation of a running search."""
    ok = _orchestrator.cancel_run(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Search run '{run_id}' not active or not found.")
@app.get("/api/jobs/{job_id}/recommended-sources")
def get_job_recommended_sources(job_id: int) -> dict[str, Any]:
    """Returns JD-aware recommended sourcing sources and policy for a specific job."""
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

    if job["extracted_data"]:
        try:
            reqs = JobRequirements.from_dict(json.loads(job["extracted_data"]))
        except Exception:
            reqs = extract_requirements(job["jd_text"])
    else:
        reqs = extract_requirements(job["jd_text"])

    role_family = talent_pool_mapper.detect_role_family(reqs.job_title, reqs.required_skills, job["jd_text"])
    recommended_sources = talent_pool_mapper.get_recommended_sources(role_family)
    policy = talent_pool_mapper.get_role_source_policy(role_family)

    return {
        "job_id": job_id,
        "job_title": reqs.job_title,
        "role_family": role_family,
        "recommended_sources": recommended_sources,
        "policy": policy,
    }


@app.get("/api/search-runs")
def list_recent_sourcing_runs(job_id: Optional[int] = None, limit: int = 15) -> list[dict[str, Any]]:
    """Lists recorded automated search runs from SQLite."""
    runs = list_search_runs(conn, job_id=job_id, limit=limit)
    out = []
    for r in runs:
        sources = []
        stats = {}
        try:
            sources = json.loads(r["enabled_sources"] or "[]")
            stats = json.loads(r["source_stats"] or "{}")
        except Exception:
            pass
        out.append({
            "run_id": r["run_id"],
            "job_id": r["job_id"],
            "status": r["status"],
            "current_stage": r["current_stage"],
            "progress_percent": r["progress_percent"],
            "enabled_sources": sources,
            "total_raw_found": r["total_raw_found"],
            "total_unique_found": r["total_unique_found"],
            "total_duplicates": r["total_duplicates"],
            "total_saved": r["total_saved"],
            "source_stats": stats,
            "error_message": r["error_message"] or "",
            "started_at": r["started_at"],
            "completed_at": r["completed_at"] or "",
            "duration_seconds": r["duration_seconds"] or 0.0,
        })
    return out


# --- Recruiter Feedback Endpoints ---

@app.post("/api/candidates/{candidate_id}/feedback")
def submit_recruiter_feedback(candidate_id: int, payload: RecruiterFeedbackCreate) -> dict[str, Any]:
    """Records recruiter evaluation feedback (relevant, irrelevant, duplicate, etc.)."""
    cand = get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")

    fid = record_recruiter_feedback(
        conn=conn,
        candidate_id=candidate_id,
        rating=payload.rating,
        feedback_text=payload.feedback_text or "",
        job_id=payload.job_id,
    )
    return {
        "success": True,
        "feedback_id": fid,
        "candidate_id": candidate_id,
        "rating": payload.rating,
        "message": f"Feedback '{payload.rating}' saved for {cand['name']}.",
    }


@app.get("/api/candidates/{candidate_id}/feedback")
def get_candidate_feedback_history(candidate_id: int) -> list[dict[str, Any]]:
    """Retrieves all feedback records for a candidate."""
    rows = get_recruiter_feedback(conn, candidate_id)
    return [dict(r) for r in rows]


# --- Groq AI Reasoning & Orchestration Endpoints ---

@app.post("/api/jobs/{job_id}/ai-search-plan")
def get_job_ai_search_plan(job_id: int) -> dict[str, Any]:
    """Generates an AI-reasoned Boolean search strategy tailored to the job requirements
    and informed by past recruiter calibration feedback.
    """
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

    if job["extracted_data"]:
        try:
            reqs = JobRequirements.from_dict(json.loads(job["extracted_data"]))
        except Exception:
            reqs = extract_requirements(job["jd_text"])
    else:
        reqs = extract_requirements(job["jd_text"])

    feedback_rows = conn.execute(
        "SELECT rating, feedback_text FROM recruiter_feedback WHERE job_id = ? ORDER BY id DESC LIMIT 15",
        (job_id,),
    ).fetchall()
    previous_feedback = [dict(r) for r in feedback_rows]

    plan = plan_search_reasoning(
        requirements=reqs,
        previous_feedback=previous_feedback,
    )
    return {
        "job_id": job_id,
        "job_title": reqs.job_title,
        "plan": plan,
    }


@app.post("/api/candidates/{candidate_id}/explain-match")
def get_candidate_ai_match_explanation(candidate_id: int, payload: ExplainMatchRequest) -> dict[str, Any]:
    """Generates an evidence-backed qualitative AI explanation for a candidate's match with a job."""
    cand = get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")

    job = get_job(conn, payload.job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{payload.job_id} not found.")

    if job["extracted_data"]:
        try:
            reqs = JobRequirements.from_dict(json.loads(job["extracted_data"]))
        except Exception:
            reqs = extract_requirements(job["jd_text"])
    else:
        reqs = extract_requirements(job["jd_text"])

    explanation = explain_candidate_match_with_groq(
        candidate=dict(cand),
        requirements=reqs,
    )
    return {
        "candidate_id": candidate_id,
        "job_id": payload.job_id,
        "explanation": explanation,
    }


@app.post("/api/candidates/{candidate_id}/profile-intelligence")
def get_candidate_profile_intelligence(
    candidate_id: int,
    payload: Optional[ProfileIntelligenceRequest] = None,
) -> dict[str, Any]:
    """Extracts deep profile intelligence (supported skills, project evidence, tenure, contacts)
    and distinguishes direct technical corroboration from superficial vanity metrics.
    """
    cand = get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate #{candidate_id} not found.")

    reqs: Optional[JobRequirements] = None
    if payload and payload.job_id:
        job = get_job(conn, payload.job_id)
        if job:
            if job["extracted_data"]:
                try:
                    reqs = JobRequirements.from_dict(json.loads(job["extracted_data"]))
                except Exception:
                    reqs = extract_requirements(job["jd_text"])
            else:
                reqs = extract_requirements(job["jd_text"])

    cand_dict = dict(cand)
    evidence_text = f"{cand_dict.get('name', '')}\n{cand_dict.get('skills', '')}\n{cand_dict.get('evidence_text', '')}"
    intelligence = analyze_profile_intelligence(
        evidence_text=evidence_text,
        requirements=reqs,
    )
    return {
        "candidate_id": candidate_id,
        "job_id": payload.job_id if payload else None,
        "intelligence": intelligence,
    }


@app.post("/api/candidates/dedup-check")
def check_duplicate_candidates(payload: DedupCheckRequest) -> dict[str, Any]:
    """Uses Groq AI reasoning to evaluate whether two candidate records belong to the same person."""
    result = assist_deduplication_with_groq(payload.candidate_a, payload.candidate_b)
    return result


@app.post("/api/jobs/{job_id}/calibrate-feedback")
def calibrate_job_feedback(job_id: int, payload: Optional[CalibrateFeedbackRequest] = None) -> dict[str, Any]:
    """Analyzes recruiter feedback for a job, formulates search adjustments,
    and records an approved strategy version in SQLite with version history.
    """
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

    if job["extracted_data"]:
        try:
            reqs = JobRequirements.from_dict(json.loads(job["extracted_data"]))
        except Exception:
            reqs = extract_requirements(job["jd_text"])
    else:
        reqs = extract_requirements(job["jd_text"])

    if payload and payload.feedback_items is not None:
        feedback_items = payload.feedback_items
    else:
        rows = conn.execute(
            """SELECT rf.rating, rf.feedback_text, c.name as candidate_name
            FROM recruiter_feedback rf
            LEFT JOIN candidates c ON rf.candidate_id = c.id
            WHERE rf.job_id = ?
            ORDER BY rf.id DESC LIMIT 20""",
            (job_id,),
        ).fetchall()
        feedback_items = [dict(r) for r in rows]

    calibration_result = calibrate_sourcing_from_feedback(
        db_conn=conn,
        job_id=job_id,
        feedback_items=feedback_items,
        current_requirements=reqs,
    )
    return {
        "job_id": job_id,
        "calibration": calibration_result,
    }


@app.get("/api/jobs/{job_id}/strategy-versions")
def get_job_strategy_versions(job_id: int) -> list[dict[str, Any]]:
    """Retrieves all version history records for a job's calibrated sourcing strategy."""
    rows = list_strategy_versions(conn, job_id)
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["source_priorities"] = json.loads(d.get("source_priorities") or "{}")
        except Exception:
            pass
        out.append(d)
    return out


# --- Rich Overview Analytics Endpoint ---

@app.get("/api/overview-stats")
def get_overview_statistics() -> dict[str, Any]:
    """Returns real SQLite database analytics and source yield breakdown for the dashboard."""
    total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    total_candidates = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    needing_review = conn.execute("SELECT COUNT(*) FROM candidates WHERE status IN ('New', 'Under Review')").fetchone()[0]
    shortlisted = conn.execute("SELECT COUNT(*) FROM candidates WHERE status = 'Shortlisted'").fetchone()[0]
    archived = conn.execute("SELECT COUNT(*) FROM candidates WHERE status = 'Archived'").fetchone()[0]

    # Source breakdown
    source_counts = {}
    rows = conn.execute("SELECT source, COUNT(*) as cnt FROM candidates GROUP BY source").fetchall()
    for r in rows:
        src = r["source"] or "Manual entry"
        source_counts[src] = r["cnt"]

    # Contact status breakdown
    contacts_found = conn.execute("SELECT COUNT(*) FROM candidates WHERE email != '' OR phone != ''").fetchone()[0]

    recent_jobs = [dict(j) for j in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 5").fetchall()]
    recent_candidates = [dict(c) for c in conn.execute("SELECT * FROM candidates ORDER BY id DESC LIMIT 5").fetchall()]
    recent_runs = list_recent_sourcing_runs(limit=5)

    return {
        "total_jobs": total_jobs,
        "total_candidates": total_candidates,
        "needing_review": needing_review,
        "shortlisted": shortlisted,
        "archived": archived,
        "contacts_found": contacts_found,
        "source_breakdown": source_counts,
        "recent_jobs": recent_jobs,
        "recent_candidates": recent_candidates,
        "recent_runs": recent_runs,
        "zero_budget_enforced": True,
        "spend_amount": "₹0.00",
    }


# --- Settings & Backups Endpoints ---

@app.get("/api/settings")
def get_system_settings() -> dict[str, Any]:
    """Returns system configuration, provider rate limits, and zero-budget verification status."""
    gh_p = GitHubSearchProvider()
    gh_status = gh_p.check_rate_limit()
    detected_key = resolve_groq_api_key()

    return {
        "zero_budget_policy": {
            "spend_permitted": "₹0.00",
            "paid_apis_enabled": False,
            "status": "Strict Zero-Budget Enforced",
            "prohibited_services": ["Exa", "SerpAPI", "Brave Paid", "Commercial Search APIs", "Paid Scraping"],
        },
        "verified_free_connectors": {
            "github": {
                "name": "GitHub Public API",
                "cost": "₹0.00",
                "rate_limit": f"{gh_status.get('search_remaining', 10)} searches remaining (resets {gh_status.get('search_reset', 'soon')})",
                "status": "Active & Ready" if gh_status.get("success") else "Rate-limited cooldown",
                "authenticated": gh_status.get("authenticated", False),
            },
            "gitlab": {
                "name": "GitLab Public API",
                "cost": "₹0.00",
                "rate_limit": "Free public endpoints (project & user namespaces)",
                "status": "Active & Ready",
                "authenticated": bool(os.getenv("GITLAB_TOKEN")),
            },
            "stackoverflow": {
                "name": "Stack Overflow Public API",
                "cost": "₹0.00",
                "rate_limit": "300 requests/day unauthenticated (10,000 with free app key)",
                "status": "Active & Ready",
                "authenticated": False,
            },
            "huggingface": {
                "name": "Hugging Face Hub API",
                "cost": "₹0.00",
                "rate_limit": "Free public Hub endpoints (AI/ML models & creators)",
                "status": "Active & Ready",
                "authenticated": False,
            },
            "local_db": {
                "name": "Local Talent Rediscovery (SQLite)",
                "cost": "₹0.00",
                "rate_limit": "Unlimited (Offline Local Disk)",
                "status": "Active & Ready",
                "authenticated": True,
            },
            "groq_browser": {
                "name": "Groq Browser Search",
                "cost": "₹0.00",
                "rate_limit": "1,000 req/day, 8,000 tokens/min Free Tier",
                "status": GroqBrowserSearchConnector().check_status().get("status", "Active & Ready"),
                "authenticated": bool(detected_key),
            },
        },
        "local_extractor": {
            "status": "Active & Ready",
            "offline_cpu": True,
            "telemetry": "None",
        },
        "groq_extractor": {
            "active_model": get_groq_model(),
            "api_key_configured": bool(detected_key),
            "free_tier_only": True,
        },
        "cost_guard": cost_guard.get_audit_summary(),
        "github_search": gh_status,
        "database": {
            "file": DB_PATH.name,
            "size_kb": round(DB_PATH.stat().st_size / 1024, 1) if DB_PATH.exists() else 0,
        },
    }


@app.get("/api/cost-guard")
def get_cost_guard_status() -> dict[str, Any]:
    """Returns the central cost-guard audit status and strict ₹0 spend verification."""
    return cost_guard.get_audit_summary()


@app.get("/api/talent-pool/{role_title}")
def get_talent_pool_mapping(role_title: str, skills: Optional[str] = "") -> dict[str, Any]:
    """Returns target companies, adjacent roles, and open source projects for a role."""
    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
    cluster = talent_pool_mapper.detect_domain(role_title, skill_list)
    strategies = talent_pool_mapper.generate_expanded_search_queries(role_title, skill_list)
    return {
        "role_title": role_title,
        "domain": cluster.domain_name,
        "target_companies": cluster.target_companies,
        "adjacent_titles": cluster.adjacent_titles,
        "tech_ecosystems": cluster.tech_ecosystems,
        "sample_open_source_projects": cluster.sample_open_source_projects,
        "suggested_strategies": strategies,
    }


@app.post("/api/settings/test-groq")
def test_groq_connection(payload: dict[str, Any]) -> dict[str, Any]:
    """Executes minimal live smoke test against Groq without logging secrets."""
    override_key = payload.get("session_key")
    override_model = payload.get("model")
    return run_groq_live_smoke_test(api_key=override_key, model=override_model)


@app.get("/api/test/groq-browser-smoke")
def test_groq_browser_smoke() -> dict[str, Any]:
    """Explicitly invoked live smoke test for Groq Browser Search.
    Executes a minimal test query using openai/gpt-oss-120b and browser_search
    to verify actual live network connectivity and distinguishes real citations from mock data."""
    import time
    connector = GroqBrowserSearchConnector()
    status_info = connector.check_status()
    if not status_info.get("api_key_configured"):
        return {
            "status": "SKIPPED",
            "is_mock": False,
            "message": "GROQ_API_KEY is not configured. Candidate Finder operates offline safely.",
            "status_info": status_info,
        }

    t0 = time.time()
    try:
        res = connector.search(
            keywords="AI prompt engineer",
            location="United States",
            limit=2,
        )
        elapsed = round(time.time() - t0, 2)
        return {
            "status": "COMPLETED" if res.candidates else ("RATE_LIMITED" if res.rate_limited else "EMPTY"),
            "is_mock": False,
            "model": GROQ_SEARCH_MODEL,
            "tool": "browser_search",
            "elapsed_seconds": elapsed,
            "candidates_found": len(res.candidates),
            "candidates": [
                {
                    "name": c.name,
                    "profile_url": c.profile_url,
                    "headline": c.headline,
                    "location": c.location,
                    "source": c.source,
                }
                for c in res.candidates
            ],
            "rate_limited": res.rate_limited,
            "error_message": res.error_message,
        }
    except Exception as exc:
        return {
            "status": "FAILED",
            "is_mock": False,
            "elapsed_seconds": round(time.time() - t0, 2),
            "error": str(exc),
        }


@app.post("/api/settings/test-github")
def test_github_connection() -> dict[str, Any]:
    """Tests official GitHub API rate limit status."""
    gh_p = GitHubSearchProvider()
    return gh_p.check_rate_limit()


@app.get("/api/backups")
def list_database_backups() -> list[dict[str, Any]]:
    """Lists existing database backups."""
    backup_files = sorted(APP_DIR.glob("candidate_sourcing_backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
    backups = []
    for bf in backup_files:
        backups.append({
            "filename": bf.name,
            "size_kb": round(bf.stat().st_size / 1024, 1),
            "created_at": datetime.fromtimestamp(bf.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return backups


@app.post("/api/backups/create")
def create_database_backup() -> dict[str, Any]:
    """Creates a verified timestamped backup using SQLite's transactional backup API."""
    try:
        bpath = create_backup(DB_PATH)
        return {
            "success": True,
            "filename": bpath.name,
            "size_kb": round(bpath.stat().st_size / 1024, 1),
            "message": f"Backup created successfully: {bpath.name}",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Backup creation failed: {exc}")


@app.post("/api/backups/restore")
async def restore_database_backup(file: UploadFile = File(...)) -> dict[str, Any]:
    """Restores database from an uploaded .db file with pre-restore safety snapshot and rollback."""
    content = await file.read()
    ok, msg, safety = restore_database(content, DB_PATH)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {
        "success": True,
        "message": msg,
        "safety_snapshot": safety.name if safety else None,
    }


# Bulk CV referral outreach (local parsing; Gmail drafts only).
from bulk_outreach import router as bulk_outreach_router
app.include_router(bulk_outreach_router)
