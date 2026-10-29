from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from db import (
    add_or_update_candidate,
    add_search_task,
    add_source_profile,
    create_search_run,
    get_job,
    get_search_tasks,
    init_db,
    update_search_run,
    update_search_task,
)
from entity_resolver import CanonicalCandidate, EntityResolver
from keyword_extractor import JobRequirements, extract_requirements
from matcher import evaluate_candidate
from source_connectors import (
    BaseSourceConnector,
    GitHubConnector,
    GitLabConnector,
    HuggingFaceConnector,
    LocalDatabaseConnector,
    RawCandidateProfile,
    StackExchangeConnector,
)
from groq_browser_connector import GroqBrowserSearchConnector
from groq_reasoning import (
    GroqToolCallingOrchestrator,
    explain_candidate_match_with_groq,
    plan_search_reasoning,
)
from talent_pool_mapper import talent_pool_mapper
from search_engine_planner import search_engine_planner
from groq_browser_connector import is_valid_candidate_url


def is_valid_candidate_lead(url: str, name: str = "Lead Profile", evidence_text: str | None = None) -> bool:
    """Validates that a lead URL points to a legitimate individual profile rather than a search page or company page,
    with genuine candidate identity and supporting evidence.
    """
    if not url:
        return False
    if name is not None and name.strip().lower() in ["", "n/a", "unknown", "none", "null", "candidate", "[full name]"]:
        return False
    if url.startswith("local://") or url.startswith("https://candidate.local/"):
        return True
    if evidence_text is not None:
        if len(evidence_text.strip()) < 15 or evidence_text.strip().lower() in ["n/a", "none", "unknown", "evidence"]:
            return False
    return is_valid_candidate_url(url)



@dataclass
class SourcingRunProgress:
    run_id: str
    job_id: int
    status: str  # CREATED, PLANNING, SEARCHING, NORMALIZING, DEDUPLICATING, MATCHING, COMPLETED, CANCELLED, FAILED, PARTIAL
    current_stage: str
    progress_percent: int
    enabled_sources: list[str]
    total_raw_found: int = 0
    total_unique_found: int = 0
    total_duplicates: int = 0
    total_saved: int = 0
    source_stats: dict[str, dict] = field(default_factory=dict)
    strategy_tasks: dict[str, dict] = field(default_factory=dict)
    reconciled_counters: dict[str, int] = field(default_factory=dict)
    error_message: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    discovered_candidates: list[dict] = field(default_factory=list)
    cancelled: bool = False
    xray_plan: dict = field(default_factory=dict)


# Global in-memory cache for fast UI polling of active and recent runs
_active_runs: dict[str, SourcingRunProgress] = {}
_run_locks: dict[str, threading.Lock] = {}


class SearchOrchestrator:
    """Asynchronous multi-source candidate sourcing engine.
    Orchestrates the entire discovery pipeline with strict ₹0 budget enforcement:
    Planning -> Multi-Source Search -> Normalization -> Cross-Source Deduplication -> Scoring -> Local DB Persistence.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()

    def _get_db(self) -> sqlite3.Connection:
        return init_db(self.db_path)

    def start_run(
        self,
        job_id: int,
        enabled_sources: list[str] | None = None,
        limit_per_source: int = 5,
        strategy_keys: list[str] | None = None,
    ) -> SourcingRunProgress:
        """Initiates an asynchronous automated sourcing run for a job."""
        if enabled_sources is None:
            enabled_sources = ["github", "gitlab", "stackoverflow", "huggingface", "local_db", "groq_browser"]

        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        progress = SourcingRunProgress(
            run_id=run_id,
            job_id=job_id,
            status="CREATED",
            current_stage="INITIALIZING",
            progress_percent=0,
            enabled_sources=enabled_sources,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )

        _active_runs[run_id] = progress
        _run_locks[run_id] = threading.Lock()

        # Record in SQLite
        conn = self._get_db()
        try:
            create_search_run(conn, run_id, job_id, enabled_sources)
        finally:
            conn.close()

        # Launch asynchronous execution in background thread
        thread = threading.Thread(
            target=self._execute_run_pipeline,
            args=(run_id, job_id, enabled_sources, limit_per_source, strategy_keys),
            daemon=True,
        )
        thread.start()

        return progress

    def cancel_run(self, run_id: str) -> bool:
        """Requests cooperative cancellation of a running search."""
        if run_id in _active_runs:
            _active_runs[run_id].cancelled = True
            _active_runs[run_id].status = "CANCELLED"
            _active_runs[run_id].current_stage = "Cancelled by recruiter"
            conn = self._get_db()
            try:
                update_search_run(conn, run_id, status="CANCELLED", current_stage="Cancelled by recruiter")
            finally:
                conn.close()
            return True
        return False

    def get_run_status(self, run_id: str) -> SourcingRunProgress | None:
        """Returns in-memory progress or loads from SQLite if completed previously."""
        if run_id in _active_runs:
            return _active_runs[run_id]

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM search_runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            sources = json.loads(row["enabled_sources"] or "[]")
            stats = json.loads(row["source_stats"] or "{}")
            return SourcingRunProgress(
                run_id=row["run_id"],
                job_id=row["job_id"],
                status=row["status"],
                current_stage=row["current_stage"],
                progress_percent=row["progress_percent"],
                enabled_sources=sources,
                total_raw_found=row["total_raw_found"],
                total_unique_found=row["total_unique_found"],
                total_duplicates=row["total_duplicates"],
                total_saved=row["total_saved"],
                source_stats=stats,
                strategy_tasks=stats.get("_strategy_tasks", {}),
                reconciled_counters=stats.get("_reconciled_counters", {}),
                error_message=row["error_message"] or "",
                started_at=row["started_at"],
                completed_at=row["completed_at"] or "",
                duration_seconds=row["duration_seconds"] or 0.0,
                xray_plan=self._get_job_xray_plan(conn, row["job_id"]),
            )
        finally:
            conn.close()

    def _get_job_xray_plan(self, conn: sqlite3.Connection, job_id: int) -> dict:
        try:
            job_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job_row:
                return {}
            if job_row["extracted_data"]:
                reqs = JobRequirements.from_dict(json.loads(job_row["extracted_data"]))
            else:
                reqs = extract_requirements(job_row["jd_text"])
            role_fam = talent_pool_mapper.detect_role_family(reqs.job_title, reqs.required_skills, job_row["jd_text"])
            return search_engine_planner.plan_job_search(
                reqs, job_id=job_id, target_location=job_row["location"] or reqs.location, role_family=role_fam
            ).to_dict()
        except Exception:
            return {}

    def _execute_run_pipeline(
        self,
        run_id: str,
        job_id: int,
        enabled_sources: list[str],
        limit_per_source: int,
        strategy_keys: list[str] | None = None,
    ) -> None:
        """The complete automated sourcing workflow."""
        start_time = time.time()
        prog = _active_runs[run_id]

        conn = self._get_db()
        try:
            if prog.cancelled:
                return

            # 1. Fetch Job
            job = get_job(conn, job_id)
            if not job:
                prog.status = "FAILED"
                prog.error_message = f"Job ID {job_id} not found."
                update_search_run(conn, run_id, status="FAILED", error_message=prog.error_message)
                return

            if prog.cancelled:
                return

            # 2. Requirements Planning
            prog.status = "PLANNING"
            prog.current_stage = "Analyzing Job Requirements & Planning Search Strategies"
            prog.progress_percent = 10
            update_search_run(conn, run_id, status="PLANNING", current_stage=prog.current_stage, progress_percent=10)

            # Parse extracted requirements
            # IMPORTANT: Never use job["title"] (user-defined save name) as the professional
            # job title for query generation. Always extract from JD text or extracted_data.
            _BAD_TITLE_PLACEHOLDERS = {
                "", "new job", "candidate search", "search candidates",
                "job title", "untitled", "test job", "test", "job",
            }

            reqs: JobRequirements
            if job["extracted_data"]:
                try:
                    data = json.loads(job["extracted_data"])
                    extracted_title = (data.get("job_title") or "").strip()
                    # If extracted_data has a bad/empty title, re-extract from JD text
                    if extracted_title.lower() in _BAD_TITLE_PLACEHOLDERS:
                        reqs = extract_requirements(job["jd_text"])
                    else:
                        reqs = JobRequirements(
                            job_title=extracted_title,
                            alternative_titles=data.get("alternative_titles") or [],
                            required_skills=data.get("required_skills") or data.get("core_skills") or [],
                            preferred_skills=data.get("preferred_skills") or [],
                            tools_and_tech=data.get("tools_and_tech") or data.get("tools_and_technologies") or [],
                            location=data.get("location") or job["location"] or "",
                            portfolio_required=data.get("portfolio_required", False),
                        )
                except Exception:
                    reqs = extract_requirements(job["jd_text"])
            else:
                reqs = extract_requirements(job["jd_text"])

            # Final safety guard: if the extracted professional title is still a
            # placeholder or empty, re-extract from the raw JD text one more time.
            if reqs.job_title.strip().lower() in _BAD_TITLE_PLACEHOLDERS:
                try:
                    reqs = extract_requirements(job["jd_text"])
                except Exception:
                    pass

            # Recruiter Calibration Feedback Loop (recruiting-copilot & recruiting-sourcing-agent-oss)
            try:
                calibration_rows = conn.execute(
                    "SELECT rating, feedback_text FROM recruiter_feedback WHERE job_id = ? ORDER BY id DESC LIMIT 20",
                    (job_id,)
                ).fetchall()
            except Exception:
                calibration_rows = []

            # Build primary keyword string for connectors.
            # Use the extracted professional job title as primary signal;
            # fall back to required skills only if title is also empty.
            # NEVER use job["title"] (user save name) as it may be arbitrary.
            _pro_title = reqs.job_title.strip()
            if _pro_title and _pro_title.lower() not in _BAD_TITLE_PLACEHOLDERS:
                keywords = _pro_title
            elif reqs.required_skills:
                keywords = " ".join(reqs.required_skills[:3])
            else:
                keywords = "Generalist"  # last-resort safe default
            target_loc = reqs.location or job["location"] or ""

            # Target-Company & Talent-Pool Mapping (Recruiting-Skills-for-AI-Agents)
            role_family = talent_pool_mapper.detect_role_family(reqs.job_title, reqs.required_skills, job["jd_text"])
            expanded_strategies = talent_pool_mapper.generate_expanded_search_queries(
                role_title=reqs.job_title,
                skills=reqs.required_skills,
                location=target_loc,
            )

            # Integrated Google X-Ray & Boolean Strategy Plan (Strategies A through G)
            try:
                xplan = search_engine_planner.plan_job_search(
                    requirements=reqs,
                    job_id=job_id,
                    target_location=target_loc,
                    role_family=role_family,
                )
                prog.xray_plan = xplan.to_dict()
                if "groq_browser" in enabled_sources:
                    try:
                        ai_plan = plan_search_reasoning(
                            requirements=reqs,
                            previous_feedback=[dict(r) for r in calibration_rows],
                        )
                        if ai_plan and ai_plan.get("primary_query"):
                            prog.xray_plan["ai_reasoned_plan"] = ai_plan
                    except Exception:
                        pass
            except Exception:
                prog.xray_plan = {}

            # Initialize 7 strategy tasks tracking
            if "xplan" in locals() and hasattr(xplan, "strategies") and xplan.strategies:
                for strat in xplan.strategies:
                    prog.strategy_tasks[strat.key] = {
                        "key": strat.key,
                        "name": strat.name,
                        "target_platform": strat.target_platform,
                        "query_text": strat.query_text,
                        "status": "PENDING",
                        "results_count": 0,
                        "error_message": "",
                        "duration_seconds": 0.0,
                    }

            # Check cancellation
            if prog.cancelled:
                return

            # 3. Instantiate Connectors
            connectors: dict[str, BaseSourceConnector] = {
                "github": GitHubConnector(),
                "gitlab": GitLabConnector(),
                "stackoverflow": StackExchangeConnector(),
                "huggingface": HuggingFaceConnector(),
                "local_db": LocalDatabaseConnector(db_conn=conn),
                "groq_browser": GroqBrowserSearchConnector(),
            }

            raw_profiles: list[RawCandidateProfile] = []
            source_stats: dict[str, dict] = {}

            # 4. Multi-Source Search Execution with Role-Aware Source Filtering
            if prog.cancelled:
                return
            prog.status = "SEARCHING"
            # Apply role-aware source filtering to ensure non-technical roles do not flood with code repos
            active_sources = talent_pool_mapper.filter_sources_for_role(enabled_sources, role_family)
            if not active_sources:
                active_sources = [s for s in enabled_sources if s in connectors]

            # Mark all strategy tasks SKIPPED if groq_browser is not active
            if "groq_browser" not in active_sources:
                for strat_key, strat_val in prog.strategy_tasks.items():
                    strat_val["status"] = "SKIPPED"
                    strat_val["error_message"] = "Automated web search not enabled for this run; manual fallback links available."
                    add_search_task(
                        conn=conn,
                        run_id=run_id,
                        source="Groq Web Search",
                        query_text=strat_val.get("query_text", ""),
                        strategy=strat_val.get("name", ""),
                        status="SKIPPED",
                        results_count=0,
                        error_message="Automated web search disabled",
                    )

            step_increment = 50 / max(1, len(active_sources))
            current_progress = 15.0

            for src_id in active_sources:
                if prog.cancelled:
                    return

                connector = connectors[src_id]
                prog.current_stage = f"Searching {connector.name}"
                prog.progress_percent = int(current_progress)
                update_search_run(
                    conn,
                    run_id,
                    status="SEARCHING",
                    current_stage=prog.current_stage,
                    progress_percent=prog.progress_percent,
                )

                if src_id == "groq_browser":
                    groq_conn: GroqBrowserSearchConnector = connector
                    status_info = groq_conn.check_status()

                    available_strats = getattr(xplan, "strategies", []) if "xplan" in locals() else []
                    if strategy_keys:
                        normalized_keys = set(strategy_keys)
                        for k in list(normalized_keys):
                            if len(k) == 1:
                                normalized_keys.add(f"Strategy {k}")
                            elif k.startswith("Strategy "):
                                normalized_keys.add(k.replace("Strategy ", ""))
                        strats_to_run = [s for s in available_strats if s.key in normalized_keys or s.key.replace("Strategy ", "") in normalized_keys]
                    else:
                        strats_to_run = available_strats

                    # Mark non-selected strategies as SKIPPED
                    for s in available_strats:
                        if s not in strats_to_run:
                            prog.strategy_tasks[s.key]["status"] = "SKIPPED"
                            prog.strategy_tasks[s.key]["error_message"] = "Strategy not selected for execution."

                    if not status_info.get("api_key_configured"):
                        for s in available_strats:
                            prog.strategy_tasks[s.key]["status"] = "SKIPPED"
                            prog.strategy_tasks[s.key]["error_message"] = "GROQ_API_KEY is not configured. Web search unavailable (manual Google/Bing links available)."
                            add_search_task(
                                conn=conn,
                                run_id=run_id,
                                source=f"Groq Web Search ({s.key})",
                                query_text=s.query_text,
                                strategy=s.name,
                                status="SKIPPED",
                                results_count=0,
                                error_message="GROQ_API_KEY not configured",
                            )
                        source_stats[src_id] = {
                            "name": connector.name,
                            "found": 0,
                            "status": "Skipped",
                            "rate_limited": False,
                            "strategy_tasks": prog.strategy_tasks,
                            "error": "GROQ_API_KEY is not configured.",
                        }
                    else:
                        groq_candidates: list[RawCandidateProfile] = []

                        # Check cooldown before making any request
                        now_t = time.time()
                        if groq_conn._cooldown_until > now_t:
                            wait_left = int(groq_conn._cooldown_until - now_t)
                            reason_msg = getattr(groq_conn, "_rate_limit_reason", "") or "Groq Free tier cooldown active"
                            for s in strats_to_run:
                                prog.strategy_tasks[s.key]["status"] = "RATE_LIMITED"
                                prog.strategy_tasks[s.key]["error_message"] = f"{reason_msg} ({wait_left}s remaining)."
                                add_search_task(
                                    conn=conn,
                                    run_id=run_id,
                                    source=f"Groq Web Search ({s.key})",
                                    query_text=s.query_text,
                                    strategy=s.name,
                                    status="RATE_LIMITED",
                                    results_count=0,
                                    error_message=f"{reason_msg} ({wait_left}s)",
                                )
                            source_stats[src_id] = {
                                "name": connector.name,
                                "found": 0,
                                "status": "Rate Limited",
                                "rate_limited": True,
                                "strategy_tasks": prog.strategy_tasks,
                                "error": f"{reason_msg} ({wait_left}s remaining).",
                            }
                        else:
                            prog.current_stage = f"Executing Consolidated Groq Web Search across {len(strats_to_run)} strategies"
                            prog.progress_percent = int(current_progress)
                            update_search_run(
                                conn,
                                run_id,
                                status="SEARCHING",
                                current_stage=prog.current_stage,
                                progress_percent=prog.progress_percent,
                            )

                            task_db_ids = {}
                            for s in strats_to_run:
                                prog.strategy_tasks[s.key]["status"] = "SEARCHING"
                                t_id = add_search_task(
                                    conn=conn,
                                    run_id=run_id,
                                    source=f"Groq Web Search ({s.key})",
                                    query_text=s.query_text,
                                    strategy=s.name,
                                    status="SEARCHING",
                                )
                                task_db_ids[s.key] = t_id

                            t_strat_start = time.time()
                            try:
                                if len(strats_to_run) == 1:
                                    s_res = groq_conn.search_strategy(
                                        strategy=strats_to_run[0],
                                        keywords=keywords,
                                        location=target_loc,
                                        limit=3,
                                        role_family=role_family,
                                        requirements=reqs,
                                    )
                                else:
                                    # Single consolidated bounded search across strategies to preserve free quota
                                    s_res = groq_conn.search_consolidated(
                                        strategies=strats_to_run,
                                        keywords=keywords,
                                        location=target_loc,
                                        limit=max(3, min(limit_per_source, 5)),
                                        role_family=role_family,
                                        requirements=reqs,
                                    )

                                dur = round(time.time() - t_strat_start, 2)

                                if s_res.rate_limited:
                                    for s in strats_to_run:
                                        prog.strategy_tasks[s.key]["status"] = "RATE_LIMITED"
                                        prog.strategy_tasks[s.key]["error_message"] = s_res.error_message or "Rate limited (HTTP 429)"
                                        prog.strategy_tasks[s.key]["duration_seconds"] = dur
                                        update_search_task(conn, task_db_ids[s.key], status="RATE_LIMITED", results_count=0, error_message=s_res.error_message or "Rate limited")
                                elif s_res.error_message:
                                    for s in strats_to_run:
                                        prog.strategy_tasks[s.key]["status"] = "FAILED"
                                        prog.strategy_tasks[s.key]["error_message"] = s_res.error_message
                                        prog.strategy_tasks[s.key]["duration_seconds"] = dur
                                        update_search_task(conn, task_db_ids[s.key], status="FAILED", results_count=0, error_message=s_res.error_message)
                                else:
                                    # Attribute returned candidates to their strategy
                                    cands_by_strat: dict[str, list] = {}
                                    for c in s_res.candidates:
                                        sk = c.raw_data.get("strategy_key") or "Strategy A"
                                        cands_by_strat.setdefault(sk, []).append(c)

                                    for s in strats_to_run:
                                        s_cands = cands_by_strat.get(s.key, [])
                                        if not s_cands and s.key.replace("Strategy ", "") in cands_by_strat:
                                            s_cands = cands_by_strat.get(s.key.replace("Strategy ", ""), [])

                                        prog.strategy_tasks[s.key]["duration_seconds"] = dur
                                        if s_cands:
                                            prog.strategy_tasks[s.key]["status"] = "RESULTS_RETURNED"
                                            prog.strategy_tasks[s.key]["results_count"] = len(s_cands)
                                            update_search_task(conn, task_db_ids[s.key], status="COMPLETED", results_count=len(s_cands))
                                        else:
                                            prog.strategy_tasks[s.key]["status"] = "NO_RESULTS"
                                            prog.strategy_tasks[s.key]["results_count"] = 0
                                            update_search_task(conn, task_db_ids[s.key], status="EMPTY", results_count=0)

                                    groq_candidates.extend(s_res.candidates)
                                    raw_profiles.extend(s_res.candidates)

                            except Exception as strat_exc:
                                dur = round(time.time() - t_strat_start, 2)
                                for s in strats_to_run:
                                    prog.strategy_tasks[s.key]["status"] = "FAILED"
                                    prog.strategy_tasks[s.key]["error_message"] = str(strat_exc)
                                    prog.strategy_tasks[s.key]["duration_seconds"] = dur
                                    update_search_task(conn, task_db_ids[s.key], status="FAILED", results_count=0, error_message=str(strat_exc))

                            current_progress += step_increment

                        source_stats[src_id] = {
                            "name": connector.name,
                            "found": len(groq_candidates),
                            "total_available": len(groq_candidates),
                            "rate_limited": any(t["status"] == "RATE_LIMITED" for t in prog.strategy_tasks.values()),
                            "strategy_tasks": prog.strategy_tasks,
                            "error": "",
                        }

                else:
                    # Execute search with safe error handling for standard connectors
                    try:
                        res = connector.search(
                            keywords=keywords,
                            location=target_loc,
                            limit=limit_per_source,
                            strategies=getattr(xplan, "strategies", None) if "xplan" in locals() else None,
                            requirements=reqs,
                        )
                        source_stats[src_id] = {
                            "name": connector.name,
                            "found": len(res.candidates),
                            "total_available": res.total_found,
                            "rate_limited": res.rate_limited,
                            "error": res.error_message or "",
                        }

                        add_search_task(
                            conn=conn,
                            run_id=run_id,
                            source=connector.name,
                            query_text=f"{keywords} {target_loc}".strip(),
                            strategy="Skills & Role Discovery",
                            status="RATE_LIMITED" if res.rate_limited else ("COMPLETED" if res.candidates else "EMPTY"),
                            results_count=len(res.candidates),
                            error_message=res.error_message or "",
                        )

                        raw_profiles.extend(res.candidates)

                    except Exception as exc:
                        source_stats[src_id] = {
                            "name": connector.name,
                            "found": 0,
                            "error": str(exc),
                            "rate_limited": False,
                        }
                        add_search_task(
                            conn=conn,
                            run_id=run_id,
                            source=connector.name,
                            query_text=keywords,
                            strategy="Error Recovery",
                            status="FAILED",
                            results_count=0,
                            error_message=str(exc),
                        )

                    current_progress += step_increment

            prog.total_raw_found = len(raw_profiles)
            prog.source_stats = source_stats

            if prog.cancelled:
                return

            # 5. Normalization & Cross-Source Deduplication
            prog.status = "DEDUPLICATING"
            prog.current_stage = "Normalizing Profiles & Resolving Cross-Source Entities"
            prog.progress_percent = 70
            update_search_run(
                conn,
                run_id,
                status="DEDUPLICATING",
                current_stage=prog.current_stage,
                progress_percent=70,
                total_raw_found=len(raw_profiles),
                source_stats=source_stats,
            )

            # Filter out obvious non-candidate leads before entity resolution
            valid_raw_profiles = [
                p for p in raw_profiles
                if is_valid_candidate_lead(p.profile_url or "", p.name, p.evidence_text or "")
            ]


            # Load existing DB candidates into resolver so we enrich rather than re-duplicate
            existing_cands = [dict(r) for r in conn.execute("SELECT * FROM candidates").fetchall()]
            resolver = EntityResolver(existing_db_candidates=existing_cands)

            unique_candidates: list[CanonicalCandidate] = []
            duplicate_count = 0

            for raw in valid_raw_profiles:
                canonical, is_dup = resolver.resolve(raw)
                if canonical not in unique_candidates:
                    unique_candidates.append(canonical)
                    if is_dup:
                        duplicate_count += 1
                else:
                    duplicate_count += 1

            prog.total_unique_found = len(unique_candidates)
            prog.total_duplicates = duplicate_count

            if prog.cancelled:
                return

            # 6. Matching, Quality Gating & Deterministic Scoring
            prog.status = "MATCHING"
            prog.current_stage = "Evaluating Candidates Against Job Requirements"
            prog.progress_percent = 85
            update_search_run(
                conn,
                run_id,
                status="MATCHING",
                current_stage=prog.current_stage,
                progress_percent=85,
                total_unique_found=len(unique_candidates),
                total_duplicates=duplicate_count,
            )

            newly_inserted_count = 0
            updated_count = 0
            associated_job_count = 0
            sourced_stage_count = 0
            rejected_count = 0
            discovered_list: list[dict] = []

            for cand in unique_candidates:
                try:
                    cand_dict = {
                        "id": cand.id,
                        "name": cand.name,
                        "headline": cand.headline,
                        "location": cand.location,
                        "company": cand.company,
                        "evidence_text": cand.evidence_text,
                        "notes": cand.notes,
                        "source": cand.source,
                        "evidence_ladder_tier": cand.evidence_ladder_tier,
                    }
                    # Run evaluation with role family context
                    eval_res = evaluate_candidate(cand_dict, reqs, target_location=target_loc, role_family=role_family)
                    cand.match_score = eval_res.confidence_adjusted_score or eval_res.total_score
                    cand.evidence_ladder_tier = eval_res.evidence_tier
                    eval_dict = eval_res.to_dict()

                    # Generate qualitative AI match explanation when Groq is enabled and available
                    if "groq_browser" in enabled_sources:
                        groq_c = connectors.get("groq_browser")
                        if not groq_c or getattr(groq_c, "_cooldown_until", 0.0) <= time.time():
                            try:
                                ai_expl = explain_candidate_match_with_groq(
                                    candidate=cand_dict,
                                    requirements=reqs,
                                )
                                if ai_expl:
                                    eval_dict["ai_explanation"] = ai_expl
                            except Exception:
                                pass


                    cand.match_details = json.dumps(eval_dict)

                    # Quality / Relevance Gate:
                    # SOURCED_STAGE_MIN_SCORE = 30 (evidence-backed minimum relevance)
                    # A candidate requires:
                    #   - confidence-adjusted score >= 30
                    #   - zero contradictory criteria (e.g. wrong country for a US-only role)
                    # Candidates below the threshold go to "Low Relevance" — they are kept in the
                    # database but excluded from the Sourced stage pipeline to prevent false positives
                    # like a 3D artist in Brazil appearing for a US remote AI Generalist role.
                    SOURCED_STAGE_MIN_SCORE = 30
                    has_fatal_contradiction = eval_res.contradictory_count > 0
                    is_qualified = (cand.match_score >= SOURCED_STAGE_MIN_SCORE and not has_fatal_contradiction)
                    if is_qualified:
                        job_stage = "Sourced"
                    elif cand.match_score > 0:
                        job_stage = "Low Relevance"
                    else:
                        job_stage = "Needs Review"


                    # Safeguard profile_url against NULL/empty to guarantee SQLite NOT NULL integrity
                    safe_url = str(cand.profile_url or cand.github_url or cand.gitlab_url or cand.portfolio_url or "").strip()
                    if not safe_url:
                        safe_url = f"https://candidate.local/{cand.id or uuid.uuid4().hex[:8]}"
                    cand.profile_url = safe_url

                    save_data = {
                        "name": cand.name,
                        "profile_url": safe_url,
                        "headline": cand.headline,
                        "location": cand.location,
                        "company": cand.company,
                        "experience": "",
                        "source": cand.source,
                        "evidence_text": cand.evidence_text,
                        "notes": cand.notes,
                        "status": job_stage,
                        "email": cand.email,
                        "phone": cand.phone,
                        "github_url": cand.github_url,
                        "gitlab_url": cand.gitlab_url,
                        "stackoverflow_url": cand.stackoverflow_url,
                        "huggingface_url": cand.huggingface_url,
                        "portfolio_url": cand.portfolio_url,
                        "contact_provenance": cand.contact_provenance,
                        "contact_status": cand.contact_status,
                        "evidence_ladder_tier": cand.evidence_ladder_tier,
                    }

                    # Check if candidate existed prior to this write
                    existing_row = None
                    if safe_url:
                        existing_row = conn.execute(
                            "SELECT id FROM candidates WHERE profile_url = ? AND name = ?",
                            (safe_url, cand.name),
                        ).fetchone()

                    ok, msg, c_id = add_or_update_candidate(conn, save_data, job_id=job_id)
                    if not ok or not c_id:
                        rejected_count += 1
                        continue

                    if existing_row:
                        updated_count += 1
                    else:
                        newly_inserted_count += 1

                    cand.id = c_id
                    associated_job_count += 1
                    if is_qualified:
                        sourced_stage_count += 1

                    # Link score and stage to job_candidates
                    conn.execute(
                        """INSERT INTO job_candidates(job_id, candidate_id, match_score, match_details, status)
                        VALUES(?, ?, ?, ?, ?)
                        ON CONFLICT(job_id, candidate_id) DO UPDATE SET
                            match_score = excluded.match_score,
                            match_details = excluded.match_details,
                            status = excluded.status""",
                        (job_id, c_id, cand.match_score, cand.match_details, job_stage),
                    )

                    # Record activity in candidate_activities
                    conn.execute(
                        """INSERT INTO candidate_activities(candidate_id, job_id, activity_type, title, details, actor, created_at)
                        VALUES(?, ?, 'DISCOVERY', ?, ?, 'System Auto-Sourcing', ?)""",
                        (
                            c_id,
                            job_id,
                            f"Discovered via {cand.source}",
                            f"Discovered via {cand.source} and placed into '{job_stage}' stage for Job #{job_id}.",
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )

                    # Record source profile evidence with guaranteed non-null profile_url
                    add_source_profile(
                        conn=conn,
                        candidate_id=c_id,
                        source=cand.source,
                        profile_url=safe_url,
                        username=cand.name,
                        raw_data={"sources": cand.raw_sources, "score": cand.match_score},
                    )

                    discovered_list.append({
                        "id": c_id,
                        "name": cand.name,
                        "headline": cand.headline,
                        "location": cand.location,
                        "company": cand.company,
                        "profile_url": safe_url,
                        "github_url": cand.github_url,
                        "gitlab_url": cand.gitlab_url,
                        "portfolio_url": cand.portfolio_url,
                        "source": cand.source,
                        "email": cand.email,
                        "phone": cand.phone,
                        "contact_status": cand.contact_status,
                        "contact_provenance": cand.contact_provenance,
                        "match_score": cand.match_score,
                        "status": job_stage,
                        "evidence_ladder_tier": cand.evidence_ladder_tier,
                        "evidence_text": cand.evidence_text,
                        "match_details": eval_res.to_dict(),
                    })

                except Exception as cand_exc:
                    rejected_count += 1
                    continue

            conn.commit()

            # Reconcile actual counts for this run only.
            # "total_saved" = candidates newly inserted or updated during this run.
            # Do NOT count pre-existing job_candidate rows — that would inflate the counter.
            total_saved = newly_inserted_count + updated_count
            prog.total_saved = total_saved

            # Recompute sourced_stage_count from the DB for accuracy
            sourced_row = conn.execute(
                "SELECT count(*) FROM job_candidates WHERE job_id = ? AND status = 'Sourced'",
                (job_id,),
            ).fetchone()
            sourced_stage_count = sourced_row[0] if sourced_row else sourced_stage_count

            # Low relevance count: candidates processed but excluded from Sourced
            low_relevance_excluded = sum(
                1 for c in discovered_list if c.get("status") == "Low Relevance"
            )

            task_count_row = conn.execute("SELECT count(*) FROM search_tasks WHERE run_id = ?", (run_id,)).fetchone()
            search_tasks_attempted = task_count_row[0] if task_count_row else len(prog.strategy_tasks)

            source_backed_contacts = sum(
                1 for c in unique_candidates if (c.email or c.phone or c.github_url or c.portfolio_url)
            )

            # Store reconciled counters in source_stats and progress object
            reconciled = {
                "search_tasks_attempted": search_tasks_attempted,
                "raw_results_retrieved": len(raw_profiles),
                "valid_profile_leads": len(valid_raw_profiles),
                "duplicates_filtered": duplicate_count,
                "unique_candidates": len(unique_candidates),
                "candidates_newly_saved": newly_inserted_count,
                "candidates_updated": updated_count,
                "candidates_associated_job": associated_job_count,
                "sourced_stage_count": sourced_stage_count,
                "low_relevance_excluded": low_relevance_excluded,
                "rejected_count": rejected_count,
                "source_backed_contacts": source_backed_contacts,
                "total_candidates_saved": total_saved,
                # Legacy keys for frontend compatibility
                "raw_source_results": len(raw_profiles),
                "total_duplicates": duplicate_count,
                "total_unique_found": len(unique_candidates),
                "newly_inserted_count": newly_inserted_count,
                "updated_count": updated_count,
                "associated_job_count": associated_job_count,
            }
            prog.reconciled_counters = reconciled
            source_stats["_reconciled_counters"] = reconciled
            source_stats["_strategy_tasks"] = prog.strategy_tasks

            # Sort discovered list by match score descending
            discovered_list.sort(key=lambda x: x["match_score"], reverse=True)

            # 7. Finalize Run with accurate PARTIAL vs COMPLETED vs FAILED state
            # FAILED:    ZERO candidates saved AND at least one connector errored
            # PARTIAL:   At least one candidate saved, but some connectors had errors/rate-limits
            # COMPLETED: All connectors ran without critical errors (may have found 0 candidates)
            if prog.cancelled:
                return
            duration = round(time.time() - start_time, 2)

            strategy_issues = [
                s_key for s_key, s_data in prog.strategy_tasks.items()
                if s_data.get("status") in ["FAILED", "RATE_LIMITED"]
            ]
            sources_with_error = [
                src for src, stats in source_stats.items()
                if isinstance(stats, dict) and (stats.get("error") or stats.get("rate_limited")) and not src.startswith("_")
            ]


            # Count how many connectors succeeded (returned candidates or ran without error)
            connectors_succeeded = len([
                src for src, stats in source_stats.items()
                if isinstance(stats, dict) and not src.startswith("_") and not stats.get("error") and not stats.get("rate_limited")
            ])
            all_connectors_errored = (
                len(active_sources) > 0
                and connectors_succeeded == 0
                and len(sources_with_error) >= len(active_sources)
            )

            if total_saved > 0 and (strategy_issues or sources_with_error):
                final_status = "PARTIAL"
                low_rel_note = f"; {low_relevance_excluded} low-relevance excluded" if low_relevance_excluded else ""
                stage_msg = (
                    f"Discovery Partially Completed in {duration}s "
                    f"({total_saved} saved, {sourced_stage_count} in Sourced stage{low_rel_note}; some sources had issues)"
                )
            elif total_saved == 0 and all_connectors_errored:
                final_status = "FAILED"
                stage_msg = "Discovery Failed: No candidates could be retrieved or saved — all connectors errored."
            elif total_saved == 0 and not all_connectors_errored:
                # Connectors ran fine but found nothing — not a failure
                final_status = "COMPLETED"
                stage_msg = f"Discovery Completed in {duration}s — 0 new candidates matched the search criteria."
            else:
                final_status = "COMPLETED"
                low_rel_note = f"; {low_relevance_excluded} low-relevance excluded" if low_relevance_excluded else ""
                stage_msg = (
                    f"Discovery Completed in {duration}s "
                    f"({total_saved} saved, {sourced_stage_count} in Sourced stage{low_rel_note})"
                )


            prog.status = final_status
            prog.current_stage = stage_msg
            prog.progress_percent = 100
            prog.duration_seconds = duration
            prog.completed_at = datetime.now().isoformat(timespec="seconds")
            prog.discovered_candidates = discovered_list

            update_search_run(
                conn=conn,
                run_id=run_id,
                status=final_status,
                current_stage=stage_msg,
                progress_percent=100,
                total_raw_found=len(raw_profiles),
                total_unique_found=len(unique_candidates),
                total_duplicates=duplicate_count,
                total_saved=total_saved,
                source_stats=source_stats,
                completed=True,
                duration_seconds=duration,
            )

        except Exception as exc:
            prog.status = "FAILED"
            prog.error_message = f"Pipeline error: {exc}"
            prog.current_stage = "Pipeline failed"
            update_search_run(
                conn,
                run_id,
                status="FAILED",
                current_stage="Pipeline failed",
                error_message=str(exc),
                completed=True,
                duration_seconds=round(time.time() - start_time, 2),
            )
        finally:
            conn.close()
