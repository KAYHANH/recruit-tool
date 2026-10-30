from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def create_backup(db_path: Path | str, backup_dir: Path | str | None = None) -> Path:
    """Creates a timestamped backup of the SQLite database.
    Raises RuntimeError if backup creation fails or the file is corrupted.
    """
    src = Path(db_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source database not found at {src}")

    target_dir = Path(backup_dir).resolve() if backup_dir else src.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = target_dir / f"candidate_sourcing_backup_{timestamp}.db"

    # Use SQLite's backup API for transactional consistency
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(backup_file)
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    if not backup_file.exists() or backup_file.stat().st_size == 0:
        raise RuntimeError(f"Backup failed to create a valid file at {backup_file}")

    return backup_file


def init_db(db_path: Path | str) -> sqlite3.Connection:
    """Connects to the database and applies safe, non-destructive migrations."""
    if str(db_path) == ":memory:":
        conn = sqlite3.connect(":memory:", check_same_thread=False, timeout=30.0)
    else:
        db_file = Path(db_path).resolve()
        db_file.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_file, check_same_thread=False, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except Exception:
            pass
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
    except Exception:
        pass
    conn.row_factory = sqlite3.Row

    with conn:
        # Base tables (matching original schema exactly)
        conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            jd_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            profile_url TEXT DEFAULT '',
            headline TEXT DEFAULT '',
            location TEXT DEFAULT '',
            experience TEXT DEFAULT '',
            source TEXT DEFAULT 'Manual entry',
            evidence_text TEXT NOT NULL,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(profile_url, name)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS job_candidates (
            job_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            PRIMARY KEY(job_id, candidate_id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            query_text TEXT NOT NULL,
            strategy TEXT DEFAULT '',
            executed_at TEXT NOT NULL,
            notes TEXT DEFAULT '',
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )""")

        # Backward-compatible migrations: Add optional columns if missing
        _add_column_if_missing(conn, "jobs", "extracted_data", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "jobs", "location", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "status", "TEXT DEFAULT 'New'")
        _add_column_if_missing(conn, "candidates", "email", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "phone", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "github_url", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "portfolio_url", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "gitlab_url", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "stackoverflow_url", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "huggingface_url", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "raw_sources", "TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "candidates", "company", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "contact_provenance", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "contact_status", "TEXT DEFAULT 'Not found'")
        _add_column_if_missing(conn, "candidates", "years_of_experience", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "candidates", "work_experiences", "TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "candidates", "highlights", "TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "candidates", "resume_text", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "resume_filename", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "resume_source", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "resume_uploaded_at", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "linkedin_url", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "added_by", "TEXT DEFAULT 'System Auto-Sourcing'")
        _add_column_if_missing(conn, "candidates", "evidence_ladder_tier", "TEXT DEFAULT 'Tier 2: Moderate Technical Evidence'")
        _add_column_if_missing(conn, "candidates", "normalized_email", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "skills", "TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "candidates", "languages", "TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "candidates", "contact_permission_basis", "TEXT DEFAULT 'PENDING_REVIEW'")
        _add_column_if_missing(conn, "candidates", "permission_reviewed_by", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "permission_reviewed_at", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "permission_notes", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "email_verification_status", "TEXT DEFAULT 'PENDING_VERIFICATION'")
        _add_column_if_missing(conn, "candidates", "opt_out_status", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "candidates", "suppression_reason", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidates", "last_contacted_at", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "job_candidates", "match_score", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "job_candidates", "match_details", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "job_candidates", "status", "TEXT DEFAULT 'Sourced'")
        _add_column_if_missing(conn, "job_candidates", "notes", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "job_candidates", "updated_at", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "search_history", "provider", "TEXT DEFAULT 'Browser (Google X-Ray)'")
        _add_column_if_missing(conn, "search_history", "status", "TEXT DEFAULT 'Opened in Browser'")

        # Extended tables for automated sourcing runs and recruiter feedback
        conn.execute("""CREATE TABLE IF NOT EXISTS search_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            job_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            current_stage TEXT DEFAULT 'CREATED',
            progress_percent INTEGER DEFAULT 0,
            enabled_sources TEXT DEFAULT '[]',
            total_raw_found INTEGER DEFAULT 0,
            total_unique_found INTEGER DEFAULT 0,
            total_duplicates INTEGER DEFAULT 0,
            total_saved INTEGER DEFAULT 0,
            source_stats TEXT DEFAULT '{}',
            error_message TEXT DEFAULT '',
            started_at TEXT NOT NULL,
            completed_at TEXT DEFAULT '',
            duration_seconds REAL DEFAULT 0,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS search_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            source TEXT NOT NULL,
            strategy TEXT DEFAULT '',
            query_text TEXT NOT NULL,
            status TEXT NOT NULL,
            results_count INTEGER DEFAULT 0,
            error_message TEXT DEFAULT '',
            executed_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES search_runs(run_id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS source_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            external_id TEXT DEFAULT '',
            profile_url TEXT NOT NULL,
            username TEXT DEFAULT '',
            raw_data TEXT DEFAULT '{}',
            retrieved_at TEXT NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS recruiter_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            job_id INTEGER DEFAULT NULL,
            rating TEXT NOT NULL,
            feedback_text TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id),
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS candidate_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            job_id INTEGER DEFAULT NULL,
            activity_type TEXT NOT NULL,
            title TEXT NOT NULL,
            details TEXT DEFAULT '',
            actor TEXT DEFAULT 'Recruiter',
            created_at TEXT NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id),
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS candidate_experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            title TEXT NOT NULL,
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            duration TEXT DEFAULT '',
            description TEXT DEFAULT '',
            skills TEXT DEFAULT '[]',
            is_current INTEGER DEFAULT 0,
            source TEXT DEFAULT '',
            FOREIGN KEY(candidate_id) REFERENCES candidates(id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS sourcing_strategy_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            strategy_name TEXT NOT NULL,
            changes_summary TEXT NOT NULL,
            adjusted_keywords TEXT NOT NULL,
            negative_keywords TEXT DEFAULT '',
            source_priorities TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )""")

        # CV-to-Referral Outreach System Entities
        conn.execute("""CREATE TABLE IF NOT EXISTS candidate_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_type TEXT NOT NULL,
            extracted_text TEXT DEFAULT '',
            parsing_status TEXT NOT NULL DEFAULT 'SUCCESS',
            parsing_error TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            is_primary INTEGER DEFAULT 1,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_files_hash ON candidate_files(file_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_files_candidate ON candidate_files(candidate_id)")

        conn.execute("""CREATE TABLE IF NOT EXISTS cv_import_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT UNIQUE NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'folder',
            source_path TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'QUEUED',
            total_files INTEGER DEFAULT 0,
            processed_files INTEGER DEFAULT 0,
            successful_files INTEGER DEFAULT 0,
            failed_files INTEGER DEFAULT 0,
            duplicate_files INTEGER DEFAULT 0,
            new_candidates INTEGER DEFAULT 0,
            updated_candidates INTEGER DEFAULT 0,
            error_message TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            completed_at TEXT DEFAULT ''
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS cv_import_job_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_hash TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            file_type TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'QUEUED',
            error_message TEXT DEFAULT '',
            candidate_id INTEGER DEFAULT NULL,
            processed_at TEXT DEFAULT '',
            FOREIGN KEY(job_id) REFERENCES cv_import_jobs(job_id),
            FOREIGN KEY(candidate_id) REFERENCES candidates(id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cv_job_files_job ON cv_import_job_files(job_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cv_job_files_status ON cv_import_job_files(status)")

        conn.execute("""CREATE TABLE IF NOT EXISTS referral_opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            requirements TEXT NOT NULL DEFAULT '[]',
            location_restrictions TEXT NOT NULL DEFAULT '',
            language_requirements TEXT NOT NULL DEFAULT '[]',
            experience_years_min INTEGER NOT NULL DEFAULT 0,
            verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
            last_verified_at TEXT DEFAULT '',
            verification_source TEXT DEFAULT '',
            verification_notes TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS referral_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opportunity_id INTEGER DEFAULT NULL,
            platform TEXT NOT NULL,
            url TEXT NOT NULL,
            owner_label TEXT NOT NULL DEFAULT 'Default Recruiter',
            eligibility_notes TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(opportunity_id) REFERENCES referral_opportunities(id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS candidate_opportunity_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            opportunity_id INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            score_breakdown TEXT NOT NULL DEFAULT '{}',
            evidence TEXT NOT NULL DEFAULT '{}',
            matched_requirements TEXT NOT NULL DEFAULT '[]',
            missing_requirements TEXT NOT NULL DEFAULT '[]',
            contradictions TEXT NOT NULL DEFAULT '[]',
            recommendation TEXT NOT NULL DEFAULT 'Review',
            opportunity_verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
            reviewer_decision TEXT DEFAULT '',
            reviewer_notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT DEFAULT '',
            UNIQUE(candidate_id, opportunity_id),
            FOREIGN KEY(candidate_id) REFERENCES candidates(id),
            FOREIGN KEY(opportunity_id) REFERENCES referral_opportunities(id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS referral_outreach_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT UNIQUE NOT NULL,
            candidate_id INTEGER NOT NULL,
            opportunity_id INTEGER NOT NULL,
            referral_link_id INTEGER DEFAULT NULL,
            recipient_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            body_text TEXT NOT NULL,
            body_html TEXT DEFAULT '',
            gmail_draft_id TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
            created_at TEXT NOT NULL,
            updated_at TEXT DEFAULT '',
            FOREIGN KEY(candidate_id) REFERENCES candidates(id),
            FOREIGN KEY(opportunity_id) REFERENCES referral_opportunities(id),
            FOREIGN KEY(referral_link_id) REFERENCES referral_links(id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS referral_outreach_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER DEFAULT NULL,
            candidate_id INTEGER NOT NULL,
            opportunity_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(draft_id) REFERENCES referral_outreach_drafts(id),
            FOREIGN KEY(candidate_id) REFERENCES candidates(id),
            FOREIGN KEY(opportunity_id) REFERENCES referral_opportunities(id)
        )""")

        _add_column_if_missing(conn, "referral_opportunities", "official_url", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "referral_opportunities", "referral_url", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "referral_opportunities", "eligibility_criteria", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "referral_opportunities", "verified_by", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "referral_opportunities", "verified_at", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "referral_opportunities", "expiry_date", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "candidate_opportunity_matches", "outreach_eligibility", "TEXT DEFAULT 'PENDING_REVIEW'")
        _add_column_if_missing(conn, "referral_outreach_drafts", "creation_locked", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "referral_outreach_drafts", "error_message", "TEXT DEFAULT ''")

    seed_candidate_experiences_if_empty(conn)
    seed_default_opportunities_if_empty(conn)
    # Normalize legacy Groq Web Search labels to canonical Groq Browser Search
    conn.execute("UPDATE candidates SET source = 'Groq Browser Search' WHERE source LIKE 'Groq Web Search%'")
    # Normalize legacy permission and status
    conn.execute("UPDATE candidates SET contact_permission_basis = 'PENDING_REVIEW' WHERE contact_permission_basis IN ('public_cv', '', 'unverified_ambiguous')")
    conn.execute("UPDATE referral_opportunities SET verification_status = 'UNVERIFIED' WHERE verification_source LIKE '%Developer Network Public Jobs%' OR verification_notes LIKE '%developer network program%'")
    conn.commit()
    return conn


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    cols = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def add_job(conn: sqlite3.Connection, title: str, jd_text: str, extracted_data: str = "", location: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO jobs(title, jd_text, extracted_data, location, created_at) VALUES(?,?,?,?,?)",
        (title.strip(), jd_text.strip(), extracted_data, location.strip(), datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_job(
    conn: sqlite3.Connection,
    job_id: int,
    title: str | None = None,
    jd_text: str | None = None,
    extracted_data: str | None = None,
    location: str | None = None,
) -> bool:
    fields = []
    vals = []
    if title is not None:
        fields.append("title = ?")
        vals.append(title.strip())
    if jd_text is not None:
        fields.append("jd_text = ?")
        vals.append(jd_text.strip())
    if extracted_data is not None:
        fields.append("extracted_data = ?")
        vals.append(extracted_data)
    if location is not None:
        fields.append("location = ?")
        vals.append(location.strip())

    if not fields:
        return False

    vals.append(job_id)
    with conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", tuple(vals))
    return True


def list_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()


def get_job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def delete_job(conn: sqlite3.Connection, job_id: int) -> bool:
    with conn:
        conn.execute("DELETE FROM job_candidates WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return True


def add_or_update_candidate(conn: sqlite3.Connection, data: dict, job_id: int | None = None) -> tuple[bool, str, int | None]:
    name = (data.get("name") or "").strip()
    if not name:
        return False, "Candidate name is required.", None

    url = (data.get("profile_url") or "").strip()
    if url and not urlparse(url).scheme:
        url = "https://" + url

    evidence = (data.get("evidence_text") or "").strip()
    if not evidence:
        parts = [data.get("headline", ""), data.get("location", ""), data.get("experience", ""), data.get("notes", "")]
        evidence = " ".join(p.strip() for p in parts if p.strip()).strip()

    if not evidence:
        return False, "Add profile/CV text or evidence before saving.", None

    headline = (data.get("headline") or "").strip()
    location = (data.get("location") or "").strip()
    experience = (data.get("experience") or "").strip()
    source = (data.get("source") or "Manual entry").strip()
    notes = (data.get("notes") or "").strip()
    status = (data.get("status") or "New").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    github_url = (data.get("github_url") or "").strip()
    portfolio_url = (data.get("portfolio_url") or "").strip()
    company = (data.get("company") or "").strip()
    contact_provenance = (data.get("contact_provenance") or "").strip()
    contact_status = (data.get("contact_status") or ("Publicly published" if email else "Not found")).strip()
    evidence_ladder_tier = (data.get("evidence_ladder_tier") or "").strip()

    # Normalize empty url to None for DB storage so distinct candidates without URLs do not collide
    db_url = url if url else None

    # 1. Check for existing candidate in this job if URL is missing
    existing = None
    if not url and job_id:
        existing = conn.execute(
            """SELECT c.id, c.headline, c.location, c.experience, c.evidence_text, c.notes, c.status
            FROM candidates c
            INNER JOIN job_candidates jc ON c.id = jc.candidate_id
            WHERE jc.job_id = ? AND c.name = ?""",
            (job_id, name),
        ).fetchone()

    # 2. Check by (profile_url, name) if URL is present
    if not existing and url:
        existing = conn.execute(
            """SELECT id, headline, location, experience, evidence_text, notes, status
            FROM candidates WHERE profile_url = ? AND name = ?""",
            (url, name),
        ).fetchone()

    candidate_id: int | None = None
    if existing:
        candidate_id = int(existing["id"])
        existing_ev = existing["evidence_text"] or ""
        if evidence and evidence not in existing_ev:
            merged_evidence = f"{existing_ev}\n\n[Updated Evidence]:\n{evidence}".strip()
        else:
            merged_evidence = existing_ev or evidence

        existing_notes = existing["notes"] or ""
        if notes and notes not in existing_notes:
            merged_notes = f"{existing_notes} | {notes}".strip(" |")
        else:
            merged_notes = existing_notes or notes

        conn.execute(
            """UPDATE candidates SET
                headline = COALESCE(NULLIF(?, ''), headline),
                location = COALESCE(NULLIF(?, ''), location),
                experience = COALESCE(NULLIF(?, ''), experience),
                evidence_text = ?,
                notes = ?,
                status = ?,
                email = COALESCE(NULLIF(?, ''), email),
                phone = COALESCE(NULLIF(?, ''), phone),
                github_url = COALESCE(NULLIF(?, ''), github_url),
                portfolio_url = COALESCE(NULLIF(?, ''), portfolio_url),
                company = COALESCE(NULLIF(?, ''), company),
                contact_provenance = COALESCE(NULLIF(?, ''), contact_provenance),
                contact_status = COALESCE(NULLIF(?, ''), contact_status),
                evidence_ladder_tier = COALESCE(NULLIF(?, ''), evidence_ladder_tier)
            WHERE id = ?""",
            (headline, location, experience, merged_evidence, merged_notes, status,
             email, phone, github_url, portfolio_url, company, contact_provenance, contact_status, evidence_ladder_tier, candidate_id),
        )
        msg = f"Updated existing profile for {name} with new evidence."
    else:
        try:
            cur = conn.execute(
                """INSERT INTO candidates(name, profile_url, headline, location, experience, source, evidence_text, notes, status, created_at,
                   email, phone, github_url, portfolio_url, company, contact_provenance, contact_status, evidence_ladder_tier)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, db_url, headline, location, experience, source, evidence, notes, status, datetime.now().isoformat(timespec="seconds"),
                 email, phone, github_url, portfolio_url, company, contact_provenance, contact_status, evidence_ladder_tier),
            )
            candidate_id = int(cur.lastrowid)
            msg = f"Candidate {name} saved."
        except sqlite3.IntegrityError:
            row = conn.execute("SELECT id FROM candidates WHERE profile_url=? AND name=?", (db_url, name)).fetchone()
            if row:
                candidate_id = int(row["id"])
                msg = f"Candidate {name} record updated."
            else:
                return False, "Could not save candidate due to duplicate constraints.", None

    if job_id and candidate_id:
        conn.execute(
            """INSERT INTO job_candidates(job_id, candidate_id, status) VALUES(?,?,?)
            ON CONFLICT(job_id, candidate_id) DO UPDATE SET status = excluded.status""",
            (job_id, candidate_id, status),
        )

    conn.commit()
    return True, msg, candidate_id


def get_candidate(conn: sqlite3.Connection, candidate_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()


def list_shortlisted_candidates(conn: sqlite3.Connection, job_id: int | None = None) -> list[sqlite3.Row]:
    if job_id:
        return conn.execute(
            """SELECT c.* FROM candidates c
            INNER JOIN job_candidates jc ON c.id = jc.candidate_id
            WHERE jc.job_id = ? AND c.status = 'Shortlisted'
            ORDER BY c.id DESC""",
            (job_id,),
        ).fetchall()
    return conn.execute("SELECT * FROM candidates WHERE status = 'Shortlisted' ORDER BY id DESC").fetchall()


def remove_from_shortlist(conn: sqlite3.Connection, candidate_id: int) -> bool:
    """Removes candidate from Shortlisted status without deleting their underlying record."""
    with conn:
        conn.execute("UPDATE candidates SET status = 'Under Review' WHERE id = ?", (candidate_id,))
    return True


def get_dashboard_metrics(conn: sqlite3.Connection) -> dict:
    """Retrieves live aggregate metrics for the Overview Dashboard."""
    total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    total_candidates = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    needing_review = conn.execute("SELECT COUNT(*) FROM candidates WHERE status IN ('New', 'Under Review')").fetchone()[0]
    shortlisted = conn.execute("SELECT COUNT(*) FROM candidates WHERE status = 'Shortlisted'").fetchone()[0]
    recent_jobs = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 5").fetchall()
    recent_candidates = conn.execute("SELECT * FROM candidates ORDER BY id DESC LIMIT 5").fetchall()
    recent_searches = conn.execute("SELECT * FROM search_history ORDER BY id DESC LIMIT 5").fetchall()

    return {
        "total_jobs": total_jobs,
        "total_candidates": total_candidates,
        "needing_review": needing_review,
        "shortlisted": shortlisted,
        "recent_jobs": recent_jobs,
        "recent_candidates": recent_candidates,
        "recent_searches": recent_searches,
    }


def list_candidates(conn: sqlite3.Connection, job_id: int | None = None) -> list[sqlite3.Row]:
    if job_id:
        return conn.execute(
            """SELECT c.* FROM candidates c
            INNER JOIN job_candidates jc ON c.id = jc.candidate_id
            WHERE jc.job_id = ?
            ORDER BY c.id DESC""",
            (job_id,),
        ).fetchall()
    return conn.execute("SELECT * FROM candidates ORDER BY id DESC").fetchall()


def update_candidate_status(conn: sqlite3.Connection, candidate_id: int, status: str) -> bool:
    with conn:
        conn.execute("UPDATE candidates SET status = ? WHERE id = ?", (status, candidate_id))
    return True


def delete_candidate(conn: sqlite3.Connection, candidate_id: int) -> bool:
    with conn:
        conn.execute("DELETE FROM job_candidates WHERE candidate_id = ?", (candidate_id,))
        conn.execute("DELETE FROM candidates WHERE id = ?", (candidate_id,))
    return True


def add_search_history(
    conn: sqlite3.Connection,
    job_id: int,
    query_text: str,
    strategy: str = "",
    notes: str = "",
    provider: str = "Browser (Google X-Ray)",
    status: str = "Opened in Browser",
) -> int:
    """Logs an executed search query to the job's search history."""
    clean_q = query_text.strip()
    cur = conn.execute(
        """INSERT INTO search_history(job_id, query_text, strategy, provider, status, executed_at, notes)
        VALUES(?,?,?,?,?,?,?)""",
        (job_id, clean_q, strategy.strip(), provider.strip(), status.strip(), datetime.now().isoformat(timespec="seconds"), notes.strip()),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_search_history(conn: sqlite3.Connection, job_id: int | None = None) -> list[sqlite3.Row]:
    """Retrieves logged search queries, optionally filtered by job_id."""
    if job_id:
        return conn.execute(
            "SELECT * FROM search_history WHERE job_id = ? ORDER BY id DESC",
            (job_id,),
        ).fetchall()
    return conn.execute("SELECT * FROM search_history ORDER BY id DESC").fetchall()


def is_query_repeated(conn: sqlite3.Connection, job_id: int, query_text: str) -> tuple[bool, str | None]:
    """Checks if a search query was previously executed for this job.
    Returns (is_repeated, last_executed_timestamp).
    """
    clean_q = query_text.strip()
    row = conn.execute(
        "SELECT executed_at FROM search_history WHERE job_id = ? AND query_text = ? ORDER BY id DESC LIMIT 1",
        (job_id, clean_q),
    ).fetchone()
    if row:
        return True, row["executed_at"]
    return False, None


def restore_database(source_bytes_or_path: bytes | Path | str, target_db_path: Path | str) -> tuple[bool, str, Path | None]:
    """Safely restores a SQLite database from a backup file or bytes.
    1. Validates that the source contains expected tables ('jobs', 'candidates').
    2. Takes a pre-restore safety snapshot of the target DB.
    3. Restores target DB and verifies integrity.
    4. Automatically rolls back to the pre-restore snapshot if validation fails.
    """
    target = Path(target_db_path).resolve()
    safety_backup: Path | None = None

    # Step 1: Create a safety pre-restore backup of current DB if it exists
    if target.exists() and target.stat().st_size > 0:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safety_backup = target.parent / f"candidate_sourcing_pre_restore_safety_{timestamp}.db"
        try:
            with sqlite3.connect(target) as src_c, sqlite3.connect(safety_backup) as dst_c:
                src_c.backup(dst_c)
        except Exception as exc:
            return False, f"Could not create safety snapshot before restore: {exc}", None

    # Step 2: Validate incoming backup
    temp_verify = target.parent / f"verify_restore_temp_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db"
    try:
        if isinstance(source_bytes_or_path, (bytes, bytearray)):
            temp_verify.write_bytes(source_bytes_or_path)
        else:
            shutil.copy2(Path(source_bytes_or_path), temp_verify)

        # Inspect temp database
        verify_conn = sqlite3.connect(temp_verify)
        try:
            tables = [r[0] for r in verify_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if "jobs" not in tables or "candidates" not in tables:
                return False, "Invalid backup database: Missing required 'jobs' or 'candidates' tables.", safety_backup
            # Check SQLite integrity
            integrity = verify_conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                return False, f"Corrupted backup database: integrity check failed ({integrity}).", safety_backup
        finally:
            verify_conn.close()

        # Step 3: Atomic copy to target
        shutil.copy2(temp_verify, target)

        # Step 4: Verify target can be initialized cleanly
        test_conn = init_db(target)
        test_conn.close()

        return True, "Database successfully restored and verified.", safety_backup

    except Exception as exc:
        # Rollback if safety backup exists
        if safety_backup and safety_backup.exists():
            shutil.copy2(safety_backup, target)
        return False, f"Restore failed and rolled back to safety backup: {exc}", safety_backup
    finally:
        if temp_verify.exists():
            try:
                temp_verify.unlink()
            except Exception:
                pass


def create_search_run(
    conn: sqlite3.Connection,
    run_id: str,
    job_id: int,
    enabled_sources: list[str],
) -> int:
    """Creates a new automated search run record."""
    import json
    cur = conn.execute(
        """INSERT INTO search_runs(run_id, job_id, status, current_stage, progress_percent, enabled_sources, started_at)
        VALUES(?, ?, 'CREATED', 'INITIALIZING', 0, ?, ?)""",
        (run_id, job_id, json.dumps(enabled_sources), datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_search_run(
    conn: sqlite3.Connection,
    run_id: str,
    status: str | None = None,
    current_stage: str | None = None,
    progress_percent: int | None = None,
    total_raw_found: int | None = None,
    total_unique_found: int | None = None,
    total_duplicates: int | None = None,
    total_saved: int | None = None,
    source_stats: dict | None = None,
    error_message: str | None = None,
    completed: bool = False,
    duration_seconds: float | None = None,
) -> bool:
    """Updates an existing search run's progress and metrics."""
    import json
    fields = []
    vals = []

    if status is not None:
        fields.append("status = ?")
        vals.append(status)
    if current_stage is not None:
        fields.append("current_stage = ?")
        vals.append(current_stage)
    if progress_percent is not None:
        fields.append("progress_percent = ?")
        vals.append(progress_percent)
    if total_raw_found is not None:
        fields.append("total_raw_found = ?")
        vals.append(total_raw_found)
    if total_unique_found is not None:
        fields.append("total_unique_found = ?")
        vals.append(total_unique_found)
    if total_duplicates is not None:
        fields.append("total_duplicates = ?")
        vals.append(total_duplicates)
    if total_saved is not None:
        fields.append("total_saved = ?")
        vals.append(total_saved)
    if source_stats is not None:
        fields.append("source_stats = ?")
        vals.append(json.dumps(source_stats))
    if error_message is not None:
        fields.append("error_message = ?")
        vals.append(error_message)
    if completed:
        fields.append("completed_at = ?")
        vals.append(datetime.now().isoformat(timespec="seconds"))
    if duration_seconds is not None:
        fields.append("duration_seconds = ?")
        vals.append(duration_seconds)

    if not fields:
        return False

    vals.append(run_id)
    with conn:
        conn.execute(f"UPDATE search_runs SET {', '.join(fields)} WHERE run_id = ?", tuple(vals))
    return True


def get_search_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM search_runs WHERE run_id = ?", (run_id,)).fetchone()


def list_search_runs(conn: sqlite3.Connection, job_id: int | None = None, limit: int = 10) -> list[sqlite3.Row]:
    if job_id:
        return conn.execute(
            "SELECT * FROM search_runs WHERE job_id = ? ORDER BY id DESC LIMIT ?",
            (job_id, limit),
        ).fetchall()
    return conn.execute("SELECT * FROM search_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def add_search_task(
    conn: sqlite3.Connection,
    run_id: str,
    source: str,
    query_text: str,
    strategy: str = "",
    status: str = "PENDING",
    results_count: int = 0,
    error_message: str = "",
) -> int:
    cur = conn.execute(
        """INSERT INTO search_tasks(run_id, source, strategy, query_text, status, results_count, error_message, executed_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, source, strategy, query_text, status, results_count, error_message, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_search_task(
    conn: sqlite3.Connection,
    task_id: int,
    status: str,
    results_count: int = 0,
    error_message: str = "",
) -> None:
    conn.execute(
        """UPDATE search_tasks
        SET status = ?, results_count = ?, error_message = ?
        WHERE id = ?""",
        (status, results_count, error_message, task_id),
    )
    conn.commit()


def get_search_tasks(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM search_tasks WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_source_profile(
    conn: sqlite3.Connection,
    candidate_id: int,
    source: str,
    profile_url: str,
    external_id: str = "",
    username: str = "",
    raw_data: dict | None = None,
) -> int:
    import json
    safe_url = str(profile_url or "").strip()
    if not safe_url:
        safe_url = f"https://candidate.local/{candidate_id}"
    cur = conn.execute(
        """INSERT INTO source_profiles(candidate_id, source, external_id, profile_url, username, raw_data, retrieved_at)
        VALUES(?, ?, ?, ?, ?, ?, ?)""",
        (candidate_id, source, external_id, safe_url, username, json.dumps(raw_data or {}), datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return int(cur.lastrowid)


def record_recruiter_feedback(
    conn: sqlite3.Connection,
    candidate_id: int,
    rating: str,
    feedback_text: str = "",
    job_id: int | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO recruiter_feedback(candidate_id, job_id, rating, feedback_text, created_at)
        VALUES(?, ?, ?, ?, ?)""",
        (candidate_id, job_id, rating.strip(), feedback_text.strip(), datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_recruiter_feedback(conn: sqlite3.Connection, candidate_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM recruiter_feedback WHERE candidate_id = ? ORDER BY id DESC",
        (candidate_id,),
    ).fetchall()


def save_strategy_version(
    conn: sqlite3.Connection,
    job_id: int,
    strategy_name: str,
    changes_summary: str,
    adjusted_keywords: str,
    negative_keywords: str = "",
    source_priorities: dict | None = None,
) -> int:
    """Persists an approved sourcing strategy version with changes diff and audit metadata."""
    source_priorities_str = json.dumps(source_priorities or {})
    row = conn.execute(
        "SELECT MAX(version_number) FROM sourcing_strategy_versions WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    next_ver = (row[0] or 0) + 1 if row else 1

    cur = conn.execute(
        """INSERT INTO sourcing_strategy_versions (
            job_id, version_number, strategy_name, changes_summary,
            adjusted_keywords, negative_keywords, source_priorities, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            next_ver,
            strategy_name.strip(),
            changes_summary.strip(),
            adjusted_keywords.strip(),
            negative_keywords.strip(),
            source_priorities_str,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_strategy_versions(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    """Retrieves all version history records for a job's search strategy."""
    return conn.execute(
        "SELECT * FROM sourcing_strategy_versions WHERE job_id = ? ORDER BY version_number DESC",
        (job_id,),
    ).fetchall()


def sanitize_csv_field(val: any) -> str:
    """Protects against CSV Formula Injection (DDE injection).
    If a field begins with '=', '+', '-', '@', or tab/CR, prepend an apostrophe.
    """
    if val is None:
        return ""
    s = str(val)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{s}"
    return s


def export_shortlist_csv_safe(conn: sqlite3.Connection, job_id: int | None = None) -> str:
    """Exports shortlisted candidates as a CSV string with formula injection protection."""
    import csv
    import io

    candidates = list_shortlisted_candidates(conn, job_id=job_id)
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    headers = [
        "Candidate ID",
        "Name",
        "Headline / Title",
        "Company",
        "Location",
        "Email",
        "Phone",
        "Contact Provenance",
        "Contact Status",
        "Profile URL",
        "GitHub URL",
        "Portfolio URL",
        "Source",
        "Status",
        "Recruiter Notes",
        "Created At",
    ]
    writer.writerow(headers)

    for c in candidates:
        row = [
            sanitize_csv_field(c["id"]),
            sanitize_csv_field(c["name"]),
            sanitize_csv_field(c["headline"]),
            sanitize_csv_field(c["company"]),
            sanitize_csv_field(c["location"]),
            sanitize_csv_field(c["email"]),
            sanitize_csv_field(c["phone"]),
            sanitize_csv_field(c["contact_provenance"]),
            sanitize_csv_field(c["contact_status"]),
            sanitize_csv_field(c["profile_url"]),
            sanitize_csv_field(c["github_url"]),
            sanitize_csv_field(c["portfolio_url"]),
            sanitize_csv_field(c["source"]),
            sanitize_csv_field(c["status"]),
            sanitize_csv_field(c["notes"]),
            sanitize_csv_field(c["created_at"]),
        ]
        writer.writerow(row)

    return output.getvalue()


def get_pipeline_data(conn: sqlite3.Connection, job_id: int) -> dict:
    """Returns structured candidate pipeline organized into 8 standard stages for a specific job."""
    import re
    job = get_job(conn, job_id)
    job_title = job["title"] if job else f"Job #{job_id}"

    STAGE_DEFS = [
        {"id": "Sourced", "name": "Sourced", "color": "blue"},
        {"id": "Under Review", "name": "Under Review", "color": "amber"},
        {"id": "My Shortlisted", "name": "My Shortlisted", "color": "indigo"},
        {"id": "Contacted", "name": "Contacted", "color": "purple"},
        {"id": "Replied", "name": "Replied", "color": "emerald"},
        {"id": "Interview", "name": "Interview", "color": "teal"},
        {"id": "Rejected", "name": "Rejected", "color": "rose"},
        {"id": "Archived", "name": "Archived", "color": "slate"},
    ]

    STATUS_MAP = {
        "new": "Sourced",
        "sourced": "Sourced",
        "under review": "Under Review",
        "under_review": "Under Review",
        "shortlisted": "My Shortlisted",
        "my shortlisted": "My Shortlisted",
        "my_shortlisted": "My Shortlisted",
        "contacted": "Contacted",
        "replied": "Replied",
        "interview": "Interview",
        "rejected": "Rejected",
        "archived": "Archived",
    }

    rows = conn.execute(
        """SELECT 
            c.id, c.name, c.profile_url, c.headline, c.company, c.location,
            c.years_of_experience, c.experience, c.source, c.email, c.phone,
            c.github_url, c.portfolio_url, c.linkedin_url, c.contact_status,
            c.contact_provenance, c.evidence_ladder_tier, c.added_by,
            c.created_at, c.notes as candidate_notes,
            COALESCE(NULLIF(jc.status, ''), c.status) as raw_stage,
            jc.match_score, jc.match_details, jc.notes as job_notes, jc.updated_at
        FROM candidates c
        INNER JOIN job_candidates jc ON c.id = jc.candidate_id
        WHERE jc.job_id = ?
        ORDER BY jc.match_score DESC, c.id DESC""",
        (job_id,),
    ).fetchall()

    stage_groups = {s["id"]: [] for s in STAGE_DEFS}
    for r in rows:
        d = dict(r)
        raw_status = (d.get("raw_stage") or "Sourced").strip().lower()
        stage_id = STATUS_MAP.get(raw_status, "Sourced")
        if stage_id not in stage_groups:
            stage_id = "Sourced"

        yoe = d.get("years_of_experience") or 0
        if not yoe and d.get("experience"):
            m = re.search(r'(\d+)\s*(?:\+)?\s*(?:years?|yrs?|y)', d.get("experience", ""), re.IGNORECASE)
            if m:
                yoe = int(m.group(1))
        d["years_of_experience"] = yoe
        d["experience_badge"] = f"{yoe}y exp" if yoe else "Emerging"
        d["stage"] = stage_id
        stage_groups[stage_id].append(d)

    stages_output = []
    total_count = 0
    for s in STAGE_DEFS:
        candidates_in_stage = stage_groups[s["id"]]
        total_count += len(candidates_in_stage)
        stages_output.append({
            "id": s["id"],
            "name": s["name"],
            "color": s["color"],
            "count": len(candidates_in_stage),
            "candidates": candidates_in_stage,
        })

    return {
        "job_id": job_id,
        "job_title": job_title,
        "total_candidates": total_count,
        "stages": stages_output,
    }


def update_job_candidate_stage(
    conn: sqlite3.Connection,
    job_id: int,
    candidate_id: int,
    new_status: str,
    actor: str = "Recruiter",
    note: str = "",
) -> bool:
    """Updates candidate stage for a specific job and records an activity audit entry."""
    now_iso = datetime.now().isoformat(timespec="seconds")
    with conn:
        # Update or insert into job_candidates
        cur = conn.execute(
            """UPDATE job_candidates 
            SET status = ?, updated_at = ? 
            WHERE job_id = ? AND candidate_id = ?""",
            (new_status, now_iso, job_id, candidate_id),
        )
        if cur.rowcount == 0:
            conn.execute(
                """INSERT INTO job_candidates(job_id, candidate_id, status, updated_at)
                VALUES(?, ?, ?, ?)""",
                (job_id, candidate_id, new_status, now_iso),
            )

        # Sync latest status to candidates table
        conn.execute(
            "UPDATE candidates SET status = ? WHERE id = ?",
            (new_status, candidate_id),
        )

        # Log to candidate_activities
        details = note.strip() if note else f"Candidate stage transitioned to '{new_status}' in job #{job_id}."
        conn.execute(
            """INSERT INTO candidate_activities(candidate_id, job_id, activity_type, title, details, actor, created_at)
            VALUES(?, ?, 'STAGE_CHANGE', ?, ?, ?, ?)""",
            (candidate_id, job_id, f"Moved to {new_status}", details, actor, now_iso),
        )
    return True


def add_candidate_activity(
    conn: sqlite3.Connection,
    candidate_id: int,
    job_id: int | None = None,
    activity_type: str = "SYSTEM",
    title: str = "",
    details: str = "",
    actor: str = "System",
) -> int:
    """Records an audit trail event for a candidate."""
    now_iso = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """INSERT INTO candidate_activities(candidate_id, job_id, activity_type, title, details, actor, created_at)
        VALUES(?, ?, ?, ?, ?, ?, ?)""",
        (candidate_id, job_id, activity_type, title, details, actor, now_iso),
    )
    conn.commit()
    return int(cur.lastrowid)


def add_candidate_note(
    conn: sqlite3.Connection,
    candidate_id: int,
    note_text: str,
    author: str = "Recruiter",
    job_id: int | None = None,
) -> bool:
    """Appends a recruiter note to candidate record and logs an activity."""
    now_iso = datetime.now().isoformat(timespec="seconds")
    with conn:
        row = conn.execute("SELECT notes FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
        existing = row["notes"] if row and row["notes"] else ""
        formatted_entry = f"[{now_iso} - {author}]: {note_text.strip()}"
        new_notes = f"{existing}\n{formatted_entry}".strip() if existing else formatted_entry

        conn.execute("UPDATE candidates SET notes = ? WHERE id = ?", (new_notes, candidate_id))
        if job_id:
            conn.execute(
                "UPDATE job_candidates SET notes = ?, updated_at = ? WHERE job_id = ? AND candidate_id = ?",
                (new_notes, now_iso, job_id, candidate_id),
            )

        conn.execute(
            """INSERT INTO candidate_activities(candidate_id, job_id, activity_type, title, details, actor, created_at)
            VALUES(?, ?, 'NOTE_ADDED', 'Recruiter Note Added', ?, ?, ?)""",
            (candidate_id, job_id, note_text.strip(), author, now_iso),
        )
    return True


def get_candidate_full_profile(
    conn: sqlite3.Connection,
    candidate_id: int,
    job_id: int | None = None,
) -> dict | None:
    """Retrieves full profile data structured for all 5 drawer tabs:
    - Overview: Basic info, Highlights, Work Experiences, Total Exp, Skills, Contacts
    - Analysis: Heuristic match evaluation, matched/missing skills, evidence quotes with URLs
    - Resume: Resume text, upload metadata, or Not Available state
    - Activity: Event history timeline
    - Associated Jobs: All linked jobs with per-job status and match score
    """
    import json
    import re

    cand_row = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    if not cand_row:
        return None

    cand = dict(cand_row)

    # Resolve active job association
    jc_row = None
    if job_id:
        jc_row = conn.execute(
            "SELECT * FROM job_candidates WHERE job_id = ? AND candidate_id = ?",
            (job_id, candidate_id),
        ).fetchone()

    if not jc_row:
        # Fall back to latest associated job
        jc_row = conn.execute(
            "SELECT * FROM job_candidates WHERE candidate_id = ? ORDER BY rowid DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()

    active_job = None
    resolved_job_id = None
    if jc_row:
        resolved_job_id = jc_row["job_id"]
        job_info = conn.execute("SELECT id, title, location, jd_text FROM jobs WHERE id = ?", (resolved_job_id,)).fetchone()
        if job_info:
            active_job = dict(job_info)

    # 1. Experiences
    exp_rows = conn.execute(
        """SELECT * FROM candidate_experiences 
        WHERE candidate_id = ? 
        ORDER BY is_current DESC, id DESC""",
        (candidate_id,),
    ).fetchall()

    experiences = []
    total_months = 0
    all_skills = set()
    for er in exp_rows:
        ed = dict(er)
        # Parse skills JSON
        try:
            ed["skills"] = json.loads(ed["skills"]) if ed.get("skills") else []
        except Exception:
            ed["skills"] = []
        for s in ed["skills"]:
            all_skills.add(s)
        experiences.append(ed)

    # Highlights
    highlights = []
    if cand.get("highlights"):
        try:
            highlights = json.loads(cand["highlights"])
        except Exception:
            highlights = []
    if not highlights and cand.get("evidence_text"):
        # Auto-extract bullet points from evidence text
        lines = [line.strip("- *• \t\r") for line in cand["evidence_text"].split("\n") if line.strip()]
        highlights = lines[:4]

    # Calculate total experience string
    yoe = cand.get("years_of_experience") or 0
    if not yoe and cand.get("experience"):
        m = re.search(r'(\d+)\s*(?:\+)?\s*(?:years?|yrs?|y)', cand.get("experience", ""), re.IGNORECASE)
        if m:
            yoe = int(m.group(1))

    total_exp_str = f"{yoe}Y TOTAL" if yoe else "Emerging / Fresher"
    if experiences:
        total_exp_str = f"{yoe}Y {max(1, len(experiences) * 3)}M TOTAL" if yoe else f"{len(experiences)} Roles"

    # Contact indicators
    contact_info = {
        "email": cand.get("email") or "",
        "phone": cand.get("phone") or "",
        "linkedin_url": cand.get("linkedin_url") or "",
        "github_url": cand.get("github_url") or "",
        "portfolio_url": cand.get("portfolio_url") or "",
        "gitlab_url": cand.get("gitlab_url") or "",
        "stackoverflow_url": cand.get("stackoverflow_url") or "",
        "huggingface_url": cand.get("huggingface_url") or "",
        "contact_status": cand.get("contact_status") or "Not found",
        "contact_provenance": cand.get("contact_provenance") or "",
    }

    # 2. Analysis Tab
    match_score = jc_row["match_score"] if jc_row and jc_row["match_score"] is not None else 0
    match_details_raw = jc_row["match_details"] if jc_row and jc_row["match_details"] else ""
    parsed_match = {}
    if match_details_raw:
        try:
            parsed_match = json.loads(match_details_raw)
        except Exception:
            parsed_match = {}

    evidence_quotes = []
    if cand.get("evidence_text"):
        snippets = [s.strip() for s in cand["evidence_text"].split("\n") if len(s.strip()) > 15]
        for snip in snippets[:4]:
            evidence_quotes.append({
                "quote": snip,
                "source": cand.get("source") or "Public Professional Profile",
                "url": cand.get("profile_url") or cand.get("portfolio_url") or cand.get("github_url") or "",
            })

    analysis_data = {
        "job_id": resolved_job_id,
        "job_title": active_job["title"] if active_job else "No Job Selected",
        "match_score": match_score,
        "tier": cand.get("evidence_ladder_tier") or "Tier 2: Moderate Technical Evidence",
        "matched_required_skills": parsed_match.get("matched_required", parsed_match.get("matched_skills", list(all_skills)[:5])),
        "matched_preferred_skills": parsed_match.get("matched_preferred", list(all_skills)[5:8]),
        "missing_skills": parsed_match.get("missing_skills", []),
        "coverage_percent": parsed_match.get("coverage_percent", min(100, max(20, match_score))),
        "evidence_quotes": evidence_quotes,
        "recommendation": parsed_match.get("recommendation", f"Candidate scored {match_score}% based on verified technical evidence."),
    }

    # 3. Resume Tab
    resume_text = cand.get("resume_text") or ""
    resume_data = {
        "has_resume": bool(resume_text.strip()),
        "resume_text": resume_text,
        "resume_filename": cand.get("resume_filename") or "",
        "resume_source": cand.get("resume_source") or "Recruiter Upload",
        "resume_uploaded_at": cand.get("resume_uploaded_at") or "",
    }

    # 4. Activity Tab
    act_rows = conn.execute(
        """SELECT id, job_id, activity_type, title, details, actor, created_at 
        FROM candidate_activities 
        WHERE candidate_id = ? 
        ORDER BY id DESC""",
        (candidate_id,),
    ).fetchall()
    activities = [dict(a) for a in act_rows]

    # 5. Associated Jobs Tab
    aj_rows = conn.execute(
        """SELECT 
            j.id as job_id, j.title as job_title, j.location as job_location,
            jc.status as stage, jc.match_score, jc.updated_at, j.created_at
        FROM jobs j
        INNER JOIN job_candidates jc ON j.id = jc.job_id
        WHERE jc.candidate_id = ?
        ORDER BY jc.updated_at DESC, j.id DESC""",
        (candidate_id,),
    ).fetchall()
    associated_jobs = [dict(aj) for aj in aj_rows]

    # Current candidate stage for the active job
    current_stage = (jc_row["status"] if jc_row and jc_row["status"] else cand.get("status") or "Sourced")
    STATUS_MAP = {
        "new": "Sourced",
        "sourced": "Sourced",
        "under review": "Under Review",
        "under_review": "Under Review",
        "shortlisted": "My Shortlisted",
        "my shortlisted": "My Shortlisted",
        "my_shortlisted": "My Shortlisted",
        "contacted": "Contacted",
        "replied": "Replied",
        "interview": "Interview",
        "rejected": "Rejected",
        "archived": "Archived",
    }
    normalized_stage = STATUS_MAP.get(current_stage.strip().lower(), current_stage)

    return {
        "id": cand["id"],
        "name": cand["name"],
        "headline": cand["headline"],
        "company": cand["company"],
        "location": cand["location"],
        "years_of_experience": yoe,
        "total_experience_str": total_exp_str,
        "source": cand["source"],
        "profile_url": cand["profile_url"],
        "added_by": cand.get("added_by") or "System Auto-Sourcing",
        "created_at": cand["created_at"],
        "stage": normalized_stage,
        "notes": cand.get("notes") or "",
        "evidence_ladder_tier": cand.get("evidence_ladder_tier") or "Tier 2: Moderate Technical Evidence",
        "highlights": highlights,
        "work_experiences": experiences,
        "skills": list(all_skills),
        "contacts": contact_info,
        "analysis": analysis_data,
        "resume": resume_data,
        "activities": activities,
        "associated_jobs": associated_jobs,
    }


def seed_candidate_experiences_if_empty(conn: sqlite3.Connection) -> None:
    """Populates realistic work experiences, companies, and highlights for existing candidates if empty."""
    import json
    row = conn.execute("SELECT COUNT(*) FROM candidate_experiences").fetchone()
    if row and row[0] > 0:
        return

    experiences_data = [
        # Maya Patel (ID 1)
        {
            "id": 1,
            "company": "Greenlab Diamond LLP",
            "years_of_experience": 5,
            "linkedin_url": "https://linkedin.com/in/mayapatel-3d",
            "github_url": "https://github.com/mayapatel-art",
            "portfolio_url": "https://artstation.com/mayapatel3d",
            "email": "maya.patel.3d@example.com",
            "highlights": [
                "5+ years experience in stylized 3D art & digital imaging",
                "Proficient in Blender, ZBrush, Adobe Creative Suite, and After Effects",
                "Specialized in handcrafted clay, fabric, and paper material exploration",
                "Extensive low-poly and clean topology workflow for game assets",
            ],
            "experiences": [
                {
                    "company": "Greenlab Diamond LLP",
                    "title": "Software Engineer & 3D Specialist",
                    "start_date": "May 2024",
                    "end_date": "Present",
                    "duration": "2y 5m",
                    "description": "Built scalable React.js and stylized 3D rendering pipelines. Created 30+ reusable digital assets with daily Blender, ZBrush, and Adobe workflows.",
                    "skills": ["blender", "zbrush", "3d_modeling", "texturing", "lighting", "stylized_assets"],
                    "is_current": 1,
                    "source": "LinkedIn / ArtStation",
                },
                {
                    "company": "Independent / CraftVision Interactive",
                    "title": "Senior 3D Asset Modeler",
                    "start_date": "Jun 2021",
                    "end_date": "Apr 2024",
                    "duration": "2y 11m",
                    "description": "Created handcrafted clay, fabric, and paper material styles. Led UV mapping and low-poly topology for stylized mobile titles.",
                    "skills": ["clay_textures", "uv_mapping", "low_poly", "topology", "shading"],
                    "is_current": 0,
                    "source": "Portfolio Showcase",
                },
            ],
        },
        # Lucas Silva (ID 2)
        {
            "id": 2,
            "company": "Voxel Forge Games",
            "years_of_experience": 3,
            "linkedin_url": "https://linkedin.com/in/lucassilva-art",
            "portfolio_url": "https://behance.net/lucassilva3d",
            "highlights": [
                "3 years experience in 3D game asset creation",
                "Daily proficiency in Blender, ZBrush, and Photoshop",
                "Strong low-poly modeling, UV mapping, and lighting skills",
            ],
            "experiences": [
                {
                    "company": "Voxel Forge Games",
                    "title": "3D Modeler & Texture Artist",
                    "start_date": "Jan 2023",
                    "end_date": "Present",
                    "duration": "3y",
                    "description": "Specializing in 3D modeling, texturing, and asset optimization with daily Blender and ZBrush workflows.",
                    "skills": ["blender", "zbrush", "photoshop", "low_poly", "uv_mapping"],
                    "is_current": 1,
                    "source": "Behance",
                },
            ],
        },
        # Aisha Rahman (ID 3)
        {
            "id": 3,
            "company": "Freelance Studio",
            "years_of_experience": 1,
            "linkedin_url": "https://linkedin.com/in/aisharahman",
            "portfolio_url": "https://artstation.com/aisharahman",
            "highlights": [
                "Recent digital arts graduate and emerging 3D artist",
                "Specializes in handcrafted clay textures and lighting",
                "Proficient in Blender and Adobe Creative Suite",
            ],
            "experiences": [
                {
                    "company": "Freelance Studio",
                    "title": "Junior 3D Artist",
                    "start_date": "Jul 2025",
                    "end_date": "Present",
                    "duration": "1y",
                    "description": "Passionate digital arts graduate creating 3D models, handcrafted clay textures, and asset lighting.",
                    "skills": ["blender", "clay_textures", "texturing", "adobe_creative_suite"],
                    "is_current": 1,
                    "source": "ArtStation",
                },
            ],
        },
        # Carlos Mendez (ID 4)
        {
            "id": 4,
            "company": "Motion Sphere Studio",
            "years_of_experience": 4,
            "portfolio_url": "https://vimeo.com/carlosmendez",
            "highlights": [
                "4 years experience in 3D animation & rendering",
                "Proficient in Cinema 4D, 3ds Max, and After Effects",
                "Experience in visual storytelling and asset optimization",
            ],
            "experiences": [
                {
                    "company": "Motion Sphere Studio",
                    "title": "3D Generalist & Motion Designer",
                    "start_date": "Feb 2022",
                    "end_date": "Present",
                    "duration": "4y",
                    "description": "Working with 3D modeling, lighting, shading, and rendering across Cinema 4D and After Effects.",
                    "skills": ["cinema_4d", "after_effects", "lighting", "rendering"],
                    "is_current": 1,
                    "source": "Vimeo",
                },
            ],
        },
        # Tarek Hassan (ID 5)
        {
            "id": 5,
            "company": "PixelCraft Agency",
            "years_of_experience": 6,
            "portfolio_url": "https://behance.net/tarekhassan",
            "highlights": [
                "6 years experience in high-end photo retouching",
                "Mastery of Adobe Creative Suite, Photoshop, and Lightroom",
                "Expert in color grading and visual storytelling",
            ],
            "experiences": [
                {
                    "company": "PixelCraft Agency",
                    "title": "Digital Image Specialist | Senior Retoucher",
                    "start_date": "Mar 2020",
                    "end_date": "Present",
                    "duration": "6y",
                    "description": "High-end photo retouching and digital image enhancement. Expert in lighting adjustment, color grading, and visual storytelling.",
                    "skills": ["photoshop", "lightroom", "color_grading", "photo_retouching"],
                    "is_current": 1,
                    "source": "Behance",
                },
            ],
        },
        # Emre Yilmaz (ID 6)
        {
            "id": 6,
            "company": "PolyMorph Interactive",
            "years_of_experience": 2,
            "portfolio_url": "https://artstation.com/emreyilmaz",
            "highlights": [
                "2 years in game development",
                "Primary tool is Blender",
                "Focused on clean topology and asset optimization",
            ],
            "experiences": [
                {
                    "company": "PolyMorph Interactive",
                    "title": "Game Asset Artist",
                    "start_date": "Sep 2024",
                    "end_date": "Present",
                    "duration": "2y",
                    "description": "Focused on low-poly assets, clean topology, and UV mapping in Blender.",
                    "skills": ["blender", "low_poly", "topology", "uv_mapping"],
                    "is_current": 1,
                    "source": "ArtStation",
                },
            ],
        },
        # Kwame Mensah (ID 7)
        {
            "id": 7,
            "company": "Independent Contract",
            "years_of_experience": 2,
            "highlights": [
                "2 years freelance 3D modeling experience",
                "Open for contract projects",
            ],
            "experiences": [
                {
                    "company": "Independent Contract",
                    "title": "Freelance 3D Modeler",
                    "start_date": "Jan 2024",
                    "end_date": "Present",
                    "duration": "2y",
                    "description": "Providing 3D modeling and rendering services using Blender.",
                    "skills": ["blender", "rendering", "3d_modeling"],
                    "is_current": 1,
                    "source": "Manual entry",
                },
            ],
        },
        # Nguyen Van Minh (ID 8)
        {
            "id": 8,
            "company": "Lotus Visual Arts",
            "years_of_experience": 3,
            "highlights": [
                "3 years 2D illustration and concept art",
                "Specialized in 2D character sketches",
            ],
            "experiences": [
                {
                    "company": "Lotus Visual Arts",
                    "title": "Digital Illustrator & Concept Artist",
                    "start_date": "May 2023",
                    "end_date": "Present",
                    "duration": "3y",
                    "description": "Specializing in 2D character sketches and visual storytelling using Photoshop and Procreate.",
                    "skills": ["photoshop", "procreate", "illustration"],
                    "is_current": 1,
                    "source": "Manual entry",
                },
            ],
        },
        # David O'Connor (ID 9)
        {
            "id": 9,
            "company": "Heritage Print Media",
            "years_of_experience": 7,
            "highlights": [
                "7 years print design and brand layouts",
                "On-site only; no 3D modeling experience",
            ],
            "experiences": [
                {
                    "company": "Heritage Print Media",
                    "title": "Graphic Designer & Print Coordinator",
                    "start_date": "Jan 2019",
                    "end_date": "Present",
                    "duration": "7y",
                    "description": "Print graphic design and brand layouts. (No 3D modeling or Blender experience).",
                    "skills": ["indesign", "illustrator", "print_design"],
                    "is_current": 1,
                    "source": "Manual entry",
                },
            ],
        },
        # Sarah Jenkins (ID 10)
        {
            "id": 10,
            "company": "Apex Quality Systems",
            "years_of_experience": 4,
            "highlights": [
                "4 years QA testing experience",
                "Specialized in manual regression testing",
            ],
            "experiences": [
                {
                    "company": "Apex Quality Systems",
                    "title": "QA Analyst & Data Specialist",
                    "start_date": "Oct 2022",
                    "end_date": "Present",
                    "duration": "4y",
                    "description": "Software QA tester specializing in manual regression testing, test cases, and Jira.",
                    "skills": ["jira", "manual_testing", "regression_testing"],
                    "is_current": 1,
                    "source": "Manual entry",
                },
            ],
        },
    ]

    with conn:
        for cdata in experiences_data:
            cid = cdata["id"]
            exists = conn.execute("SELECT id, company, years_of_experience FROM candidates WHERE id = ?", (cid,)).fetchone()
            if not exists:
                continue

            conn.execute(
                """UPDATE candidates SET
                    company = CASE WHEN COALESCE(company, '') = '' THEN ? ELSE company END,
                    years_of_experience = CASE WHEN COALESCE(years_of_experience, 0) = 0 THEN ? ELSE years_of_experience END,
                    highlights = ?,
                    linkedin_url = CASE WHEN COALESCE(linkedin_url, '') = '' THEN ? ELSE linkedin_url END,
                    github_url = CASE WHEN COALESCE(github_url, '') = '' THEN ? ELSE github_url END,
                    portfolio_url = CASE WHEN COALESCE(portfolio_url, '') = '' THEN ? ELSE portfolio_url END,
                    email = CASE WHEN COALESCE(email, '') = '' THEN ? ELSE email END
                WHERE id = ?""",
                (
                    cdata.get("company", ""),
                    cdata.get("years_of_experience", 0),
                    json.dumps(cdata.get("highlights", [])),
                    cdata.get("linkedin_url", ""),
                    cdata.get("github_url", ""),
                    cdata.get("portfolio_url", ""),
                    cdata.get("email", ""),
                    cid,
                ),
            )

            for exp in cdata.get("experiences", []):
                conn.execute(
                    """INSERT INTO candidate_experiences(candidate_id, company, title, start_date, end_date, duration, description, skills, is_current, source)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cid,
                        exp["company"],
                        exp["title"],
                        exp.get("start_date", ""),
                        exp.get("end_date", ""),
                        exp.get("duration", ""),
                        exp.get("description", ""),
                        json.dumps(exp.get("skills", [])),
                        exp.get("is_current", 0),
                        exp.get("source", ""),
                    ),
                )


# ---------------------------------------------------------------------------
# CV-to-Referral Outreach Database Accessors
# ---------------------------------------------------------------------------

def get_candidate_by_email(conn: sqlite3.Connection, email: str) -> dict | None:
    norm_email = email.strip().lower()
    if not norm_email:
        return None
    row = conn.execute(
        "SELECT * FROM candidates WHERE LOWER(email) = ? OR LOWER(normalized_email) = ? LIMIT 1",
        (norm_email, norm_email),
    ).fetchone()
    return dict(row) if row else None


def get_candidate_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    stripped_name = name.strip()
    if not stripped_name:
        return None
    row = conn.execute(
        "SELECT * FROM candidates WHERE LOWER(name) = ? LIMIT 1",
        (stripped_name.lower(),),
    ).fetchone()
    return dict(row) if row else None


def record_candidate_file(
    conn: sqlite3.Connection,
    candidate_id: int,
    file_path: str,
    file_name: str,
    file_hash: str,
    file_size: int,
    file_type: str,
    extracted_text: str = "",
    parsing_status: str = "SUCCESS",
    parsing_error: str = "",
    is_primary: int = 1,
) -> int:
    now_iso = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """INSERT INTO candidate_files(
            candidate_id, file_path, file_name, file_hash, file_size,
            file_type, extracted_text, parsing_status, parsing_error, created_at, is_primary
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            candidate_id,
            file_path,
            file_name,
            file_hash,
            file_size,
            file_type,
            extracted_text,
            parsing_status,
            parsing_error,
            now_iso,
            is_primary,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_candidate_file_by_hash(conn: sqlite3.Connection, file_hash: str) -> dict | None:
    if not file_hash:
        return None
    row = conn.execute(
        "SELECT * FROM candidate_files WHERE file_hash = ? LIMIT 1",
        (file_hash,),
    ).fetchone()
    return dict(row) if row else None


def list_candidate_files(conn: sqlite3.Connection, candidate_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM candidate_files WHERE candidate_id = ? ORDER BY id DESC",
        (candidate_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def create_cv_import_job(
    conn: sqlite3.Connection,
    job_id: str,
    source_type: str = "folder",
    source_path: str = "",
    total_files: int = 0,
) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO cv_import_jobs(
            job_id, source_type, source_path, status, total_files, created_at
        ) VALUES(?, ?, ?, 'QUEUED', ?, ?)""",
        (job_id, source_type, source_path, total_files, now_iso),
    )
    conn.commit()


def update_cv_import_job(
    conn: sqlite3.Connection,
    job_id: str,
    **kwargs,
) -> None:
    if not kwargs:
        return
    fields = []
    values = []
    for k, v in kwargs.items():
        fields.append(f"{k} = ?")
        values.append(v)
    values.append(job_id)
    sql = f"UPDATE cv_import_jobs SET {', '.join(fields)} WHERE job_id = ?"
    conn.execute(sql, values)
    conn.commit()


def get_cv_import_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM cv_import_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    return dict(row) if row else None


def list_cv_import_jobs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM cv_import_jobs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_cv_import_job_file(
    conn: sqlite3.Connection,
    job_id: str,
    file_path: str,
    file_name: str,
    file_size: int = 0,
    file_type: str = "",
    file_hash: str = "",
    status: str = "QUEUED",
) -> int:
    cur = conn.execute(
        """INSERT INTO cv_import_job_files(
            job_id, file_path, file_name, file_size, file_type, file_hash, status
        ) VALUES(?, ?, ?, ?, ?, ?, ?)""",
        (job_id, file_path, file_name, file_size, file_type, file_hash, status),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_cv_import_job_file(
    conn: sqlite3.Connection,
    job_file_id: int,
    status: str,
    error_message: str = "",
    candidate_id: int | None = None,
    file_hash: str = "",
) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """UPDATE cv_import_job_files
        SET status = ?, error_message = ?, candidate_id = ?, file_hash = CASE WHEN ? != '' THEN ? ELSE file_hash END, processed_at = ?
        WHERE id = ?""",
        (status, error_message, candidate_id, file_hash, file_hash, now_iso, job_file_id),
    )
    conn.commit()


def get_cv_import_job_files(conn: sqlite3.Connection, job_id: str, limit: int = 500, offset: int = 0) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM cv_import_job_files WHERE job_id = ? ORDER BY id ASC LIMIT ? OFFSET ?",
        (job_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def update_candidate_contact_permission(
    conn: sqlite3.Connection,
    candidate_id: int,
    permission_basis: str,
    reviewer: str = "Recruiter",
    notes: str = "",
) -> None:
    allowed_bases = {"PENDING_REVIEW", "UNVERIFIED", "APPROVED_OUTREACH", "DIRECT_CONSENT", "OPTED_OUT"}
    norm_basis = permission_basis.strip().upper()
    if norm_basis not in allowed_bases:
        raise ValueError(f"Invalid permission basis '{permission_basis}'. Must be one of: {', '.join(sorted(allowed_bases))}")

    now_iso = datetime.now().isoformat(timespec="seconds")
    if norm_basis == "OPTED_OUT":
        conn.execute(
            """UPDATE candidates
            SET contact_permission_basis = ?, permission_reviewed_by = ?, permission_reviewed_at = ?, permission_notes = ?,
                opt_out_status = 1, suppression_reason = ?
            WHERE id = ?""",
            (norm_basis, reviewer, now_iso, notes, notes or "Marked OPTED_OUT via permission management", candidate_id),
        )
    else:
        conn.execute(
            """UPDATE candidates
            SET contact_permission_basis = ?, permission_reviewed_by = ?, permission_reviewed_at = ?, permission_notes = ?,
                opt_out_status = 0
            WHERE id = ?""",
            (norm_basis, reviewer, now_iso, notes, candidate_id),
        )
    conn.commit()


def update_candidate_email_verification(
    conn: sqlite3.Connection,
    candidate_id: int,
    status: str,
    notes: str = "",
) -> None:
    allowed_statuses = {"EXTRACTED", "PENDING_VERIFICATION", "VERIFIED", "INVALID"}
    norm_status = status.strip().upper()
    if norm_status not in allowed_statuses:
        raise ValueError(f"Invalid email verification status '{status}'. Must be one of: {', '.join(sorted(allowed_statuses))}")

    conn.execute(
        "UPDATE candidates SET email_verification_status = ? WHERE id = ?",
        (norm_status, candidate_id),
    )
    conn.commit()


def update_candidate_opt_out(
    conn: sqlite3.Connection,
    candidate_id: int,
    opt_out: bool,
    reason: str = "",
) -> None:
    conn.execute(
        "UPDATE candidates SET opt_out_status = ?, suppression_reason = ? WHERE id = ?",
        (1 if opt_out else 0, reason, candidate_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Referral Opportunities, Links, Matches, and Drafts
# ---------------------------------------------------------------------------

def seed_default_opportunities_if_empty(conn: sqlite3.Connection) -> None:
    """Seeds unverified initial opportunities for Turing, Mercor, and micro1 if table is empty."""
    count = conn.execute("SELECT count(*) FROM referral_opportunities").fetchone()[0]
    if count > 0:
        return

    now_iso = datetime.now().isoformat(timespec="seconds")
    defaults = [
        (
            "Turing",
            "Senior Fullstack & AI-Assisted Developer",
            "High-impact remote engineering roles building scalable web and distributed cloud applications.",
            "https://www.turing.com",
            json.dumps(["python", "react", "typescript", "fastapi", "postgresql", "docker", "problem solving"]),
            "Remote (Global)",
            json.dumps(["English"]),
            3,
            "UNVERIFIED",
            now_iso,
            "Turing Developer Network Public Jobs",
            "Unverified initial role description. Recruiter verification required before outreach.",
            1,
            now_iso,
            "https://turing.com/referrals/dev-portal",
        ),
        (
            "Mercor",
            "AI Engineer & LLM Specialist",
            "Elite AI engineering, LLM benchmark evaluations, agent development, and fine-tuning roles.",
            "https://mercor.com",
            json.dumps(["python", "pytorch", "llm", "prompt engineering", "langchain", "fine-tuning", "machine learning"]),
            "Remote (Global)",
            json.dumps(["English"]),
            2,
            "UNVERIFIED",
            now_iso,
            "Mercor AI Platform Public Documentation",
            "Unverified initial role description. Recruiter verification required before outreach.",
            1,
            now_iso,
            "https://mercor.com/apply/ai-engineer",
        ),
        (
            "micro1",
            "Senior Software Engineer (Frontend / Fullstack)",
            "World-class engineering opportunities with vetted global tech teams and high-growth venture backed startups.",
            "https://www.micro1.ai",
            json.dumps(["typescript", "react", "next.js", "node.js", "aws", "tailwind", "attention to detail"]),
            "Remote (Global)",
            json.dumps(["English"]),
            3,
            "UNVERIFIED",
            now_iso,
            "micro1 Talent Network Portal",
            "Unverified initial role description. Recruiter verification required before outreach.",
            1,
            now_iso,
            "https://micro1.ai/talents/apply",
        ),
    ]

    for d in defaults:
        cur = conn.execute(
            """INSERT INTO referral_opportunities(
                platform, title, description, url, requirements, location_restrictions,
                language_requirements, experience_years_min, verification_status, last_verified_at,
                verification_source, verification_notes, is_active, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            d[:14],
        )
        opp_id = cur.lastrowid
        # Seed default referral link
        conn.execute(
            """INSERT INTO referral_links(
                opportunity_id, platform, url, owner_label, eligibility_notes, is_active, created_at
            ) VALUES(?, ?, ?, 'System Verified Link', 'General eligibility verified', 1, ?)""",
            (opp_id, d[0], d[14], now_iso),
        )
    conn.commit()


def list_referral_opportunities(conn: sqlite3.Connection, is_active: bool = True) -> list[dict]:
    query = "SELECT * FROM referral_opportunities"
    params = []
    if is_active:
        query += " WHERE is_active = 1"
    query += " ORDER BY id ASC"
    rows = conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for jf in ["requirements", "language_requirements"]:
            try:
                if d.get(jf) and isinstance(d[jf], str):
                    d[jf] = json.loads(d[jf])
            except Exception:
                d[jf] = []
        # Attach active referral links
        links = conn.execute(
            "SELECT * FROM referral_links WHERE opportunity_id = ? AND is_active = 1",
            (d["id"],),
        ).fetchall()
        d["links"] = [dict(lnk) for lnk in links]
        result.append(d)
    return result


def get_referral_opportunity(conn: sqlite3.Connection, opp_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM referral_opportunities WHERE id = ?",
        (opp_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    for jf in ["requirements", "language_requirements"]:
        try:
            if d.get(jf) and isinstance(d[jf], str):
                d[jf] = json.loads(d[jf])
        except Exception:
            d[jf] = []
    links = conn.execute(
        "SELECT * FROM referral_links WHERE opportunity_id = ? AND is_active = 1",
        (opp_id,),
    ).fetchall()
    d["links"] = [dict(lnk) for lnk in links]
    return d


def create_referral_opportunity(
    conn: sqlite3.Connection,
    platform: str,
    title: str,
    description: str = "",
    url: str = "",
    requirements: list[str] | None = None,
    location_restrictions: str = "Remote (Global)",
    language_requirements: list[str] | None = None,
    experience_years_min: int = 0,
    verification_status: str = "UNVERIFIED",
    verification_source: str = "",
    verification_notes: str = "",
) -> int:
    now_iso = datetime.now().isoformat(timespec="seconds")
    req_json = json.dumps(requirements or [])
    lang_json = json.dumps(language_requirements or ["English"])
    cur = conn.execute(
        """INSERT INTO referral_opportunities(
            platform, title, description, url, requirements, location_restrictions,
            language_requirements, experience_years_min, verification_status, last_verified_at,
            verification_source, verification_notes, is_active, created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (
            platform.strip(),
            title.strip(),
            description.strip(),
            url.strip(),
            req_json,
            location_restrictions.strip(),
            lang_json,
            experience_years_min,
            verification_status,
            now_iso if verification_status == "VERIFIED" else "",
            verification_source.strip(),
            verification_notes.strip(),
            now_iso,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_referral_opportunity(
    conn: sqlite3.Connection,
    opp_id: int,
    **kwargs,
) -> None:
    if not kwargs:
        return
    fields = []
    values = []
    for k, v in kwargs.items():
        if k in ("requirements", "language_requirements") and isinstance(v, list):
            v = json.dumps(v)
        fields.append(f"{k} = ?")
        values.append(v)
    values.append(opp_id)
    sql = f"UPDATE referral_opportunities SET {', '.join(fields)} WHERE id = ?"
    conn.execute(sql, values)
    conn.commit()


def create_referral_link(
    conn: sqlite3.Connection,
    opportunity_id: int | None,
    platform: str,
    url: str,
    owner_label: str = "Default Recruiter",
    eligibility_notes: str = "",
) -> int:
    now_iso = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """INSERT INTO referral_links(
            opportunity_id, platform, url, owner_label, eligibility_notes, is_active, created_at
        ) VALUES(?, ?, ?, ?, ?, 1, ?)""",
        (opportunity_id, platform.strip(), url.strip(), owner_label.strip(), eligibility_notes.strip(), now_iso),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_referral_links(conn: sqlite3.Connection, opp_id: int | None = None) -> list[dict]:
    query = "SELECT * FROM referral_links WHERE is_active = 1"
    params = []
    if opp_id is not None:
        query += " AND opportunity_id = ?"
        params.append(opp_id)
    query += " ORDER BY id DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def save_candidate_match(
    conn: sqlite3.Connection,
    candidate_id: int,
    opportunity_id: int,
    score: int,
    score_breakdown: dict,
    evidence: dict,
    matched_requirements: list[str],
    missing_requirements: list[str],
    contradictions: list[str],
    recommendation: str,
    opportunity_verification_status: str = "UNVERIFIED",
    outreach_eligibility: str = "PENDING_REVIEW",
    reviewer_decision: str = "PENDING",
    reviewer_notes: str = "",
) -> int:
    now_iso = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """INSERT INTO candidate_opportunity_matches(
            candidate_id, opportunity_id, score, score_breakdown, evidence,
            matched_requirements, missing_requirements, contradictions,
            recommendation, opportunity_verification_status, outreach_eligibility, reviewer_decision,
            reviewer_notes, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(candidate_id, opportunity_id) DO UPDATE SET
            score = excluded.score,
            score_breakdown = excluded.score_breakdown,
            evidence = excluded.evidence,
            matched_requirements = excluded.matched_requirements,
            missing_requirements = excluded.missing_requirements,
            contradictions = excluded.contradictions,
            recommendation = excluded.recommendation,
            opportunity_verification_status = excluded.opportunity_verification_status,
            outreach_eligibility = excluded.outreach_eligibility,
            updated_at = excluded.updated_at""",
        (
            candidate_id,
            opportunity_id,
            score,
            json.dumps(score_breakdown),
            json.dumps(evidence),
            json.dumps(matched_requirements),
            json.dumps(missing_requirements),
            json.dumps(contradictions),
            recommendation,
            opportunity_verification_status,
            outreach_eligibility,
            reviewer_decision,
            reviewer_notes,
            now_iso,
            now_iso,
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def list_candidate_matches(
    conn: sqlite3.Connection,
    opportunity_id: int | None = None,
    candidate_id: int | None = None,
    min_score: int | None = None,
    limit: int = 200,
) -> list[dict]:
    query = """
        SELECT
            m.*,
            c.name as candidate_name,
            c.email as candidate_email,
            c.phone as candidate_phone,
            c.location as candidate_location,
            c.opt_out_status as candidate_opt_out,
            c.contact_permission_basis as candidate_permission_basis,
            c.email_verification_status as candidate_email_verification_status,
            c.permission_reviewed_by,
            c.permission_reviewed_at,
            o.platform as opportunity_platform,
            o.title as opportunity_title,
            o.verification_status as opp_verification_status
        FROM candidate_opportunity_matches m
        JOIN candidates c ON m.candidate_id = c.id
        JOIN referral_opportunities o ON m.opportunity_id = o.id
        WHERE 1=1
    """
    params = []
    if opportunity_id:
        query += " AND m.opportunity_id = ?"
        params.append(opportunity_id)
    if candidate_id:
        query += " AND m.candidate_id = ?"
        params.append(candidate_id)
    if min_score is not None:
        query += " AND m.score >= ?"
        params.append(min_score)
    query += " ORDER BY m.score DESC, m.id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for jf in ["score_breakdown", "evidence", "matched_requirements", "missing_requirements", "contradictions"]:
            try:
                if d.get(jf) and isinstance(d[jf], str):
                    d[jf] = json.loads(d[jf])
            except Exception:
                d[jf] = [] if "requirements" in jf or "contradictions" in jf else {}
        result.append(d)
    return result


def update_match_reviewer_decision(
    conn: sqlite3.Connection,
    match_id: int,
    decision: str,
    notes: str = "",
) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """UPDATE candidate_opportunity_matches
        SET reviewer_decision = ?, reviewer_notes = ?, updated_at = ?
        WHERE id = ?""",
        (decision, notes, now_iso, match_id),
    )
    conn.commit()


def create_or_update_draft(
    conn: sqlite3.Connection,
    idempotency_key: str,
    candidate_id: int,
    opportunity_id: int,
    referral_link_id: int | None,
    recipient_email: str,
    subject: str,
    body_text: str,
    body_html: str = "",
    gmail_draft_id: str = "",
    status: str = "PENDING_REVIEW",
) -> int:
    now_iso = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """INSERT INTO referral_outreach_drafts(
            idempotency_key, candidate_id, opportunity_id, referral_link_id,
            recipient_email, subject, body_text, body_html, gmail_draft_id,
            status, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(idempotency_key) DO UPDATE SET
            subject = excluded.subject,
            body_text = excluded.body_text,
            body_html = excluded.body_html,
            gmail_draft_id = CASE WHEN excluded.gmail_draft_id != '' THEN excluded.gmail_draft_id ELSE referral_outreach_drafts.gmail_draft_id END,
            status = excluded.status,
            updated_at = excluded.updated_at""",
        (
            idempotency_key,
            candidate_id,
            opportunity_id,
            referral_link_id,
            recipient_email,
            subject,
            body_text,
            body_html,
            gmail_draft_id,
            status,
            now_iso,
            now_iso,
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def list_outreach_drafts(
    conn: sqlite3.Connection,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    query = """
        SELECT
            d.*,
            c.name as candidate_name,
            c.opt_out_status as candidate_opt_out,
            o.platform as opportunity_platform,
            o.title as opportunity_title,
            l.url as referral_url
        FROM referral_outreach_drafts d
        JOIN candidates c ON d.candidate_id = c.id
        JOIN referral_opportunities o ON d.opportunity_id = o.id
        LEFT JOIN referral_links l ON d.referral_link_id = l.id
        WHERE 1=1
    """
    params = []
    if status:
        query += " AND d.status = ?"
        params.append(status)
    query += " ORDER BY d.id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_outreach_draft(conn: sqlite3.Connection, draft_id: int) -> dict | None:
    row = conn.execute(
        """SELECT
            d.*,
            c.name as candidate_name,
            c.opt_out_status as candidate_opt_out,
            o.platform as opportunity_platform,
            o.title as opportunity_title,
            l.url as referral_url
        FROM referral_outreach_drafts d
        JOIN candidates c ON d.candidate_id = c.id
        JOIN referral_opportunities o ON d.opportunity_id = o.id
        LEFT JOIN referral_links l ON d.referral_link_id = l.id
        WHERE d.id = ?""",
        (draft_id,),
    ).fetchone()
    return dict(row) if row else None


def get_draft_by_idempotency_key(conn: sqlite3.Connection, idempotency_key: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM referral_outreach_drafts WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    return dict(row) if row else None


def update_draft_status(
    conn: sqlite3.Connection,
    draft_id: int,
    status: str,
    gmail_draft_id: str = "",
) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    if gmail_draft_id:
        conn.execute(
            "UPDATE referral_outreach_drafts SET status = ?, gmail_draft_id = ?, updated_at = ? WHERE id = ?",
            (status, gmail_draft_id, now_iso, draft_id),
        )
    else:
        conn.execute(
            "UPDATE referral_outreach_drafts SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_iso, draft_id),
        )
    conn.commit()


def get_cv_outreach_overview_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    """Computes real-time overview metrics for the CV Outreach dashboard."""
    files_count = conn.execute("SELECT count(*) FROM candidate_files").fetchone()[0]
    total_candidates = conn.execute("SELECT count(*) FROM candidates").fetchone()[0]
    cv_candidates = conn.execute("SELECT count(*) FROM candidates WHERE source = 'CV Upload'").fetchone()[0]
    opportunities_count = conn.execute("SELECT count(*) FROM referral_opportunities WHERE is_active = 1").fetchone()[0]
    matches_count = conn.execute("SELECT count(*) FROM candidate_opportunity_matches").fetchone()[0]
    high_matches = conn.execute("SELECT count(*) FROM candidate_opportunity_matches WHERE score >= 65").fetchone()[0]
    drafts_count = conn.execute("SELECT count(*) FROM referral_outreach_drafts").fetchone()[0]
    drafts_in_gmail = conn.execute("SELECT count(*) FROM referral_outreach_drafts WHERE status = 'CREATED_IN_GMAIL'").fetchone()[0]
    opt_out_count = conn.execute("SELECT count(*) FROM candidates WHERE opt_out_status = 1").fetchone()[0]

    return {
        "total_imported_files": files_count,
        "total_candidates": total_candidates,
        "cv_candidates": cv_candidates,
        "active_opportunities": opportunities_count,
        "total_matches": matches_count,
        "high_confidence_matches": high_matches,
        "total_drafts": drafts_count,
        "drafts_created_in_gmail": drafts_in_gmail,
        "suppressed_candidates": opt_out_count,
    }



