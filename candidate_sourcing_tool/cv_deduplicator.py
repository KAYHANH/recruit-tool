"""
CV Deduplication and Identity Resolution Engine.

Ensures:
- SHA-256 hash checks prevent duplicate file parsing.
- Normalized email matching reuses existing canonical records in `candidates`.
- Multiple original CV file references are linked to the single canonical candidate via `candidate_files`.
- Ambiguous identity matches (e.g. same name, different or missing email) are never silently merged.
- Re-importing files is 100% idempotent.
- Existing database candidates and sourcing associations are completely preserved.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from cv_parser import ParsedCV
from db import (
    get_candidate_by_email,
    get_candidate_file_by_hash,
    record_candidate_file,
)

logger = logging.getLogger("cv_deduplicator")


@dataclass
class DeduplicationResult:
    action: str  # "SKIPPED_DUPLICATE_FILE", "UPDATED_EXISTING", "INSERTED_NEW", "AMBIGUOUS_SEPARATED"
    candidate_id: int | None
    file_record_id: int | None
    message: str
    is_duplicate: bool = False
    is_new: bool = False
    is_updated: bool = False


class CVDeduplicator:
    """Manages identity resolution and deduplication against the SQLite database."""

    def process_parsed_cv(
        self,
        conn: sqlite3.Connection,
        parsed: ParsedCV,
        allow_name_fallback_for_empty_email: bool = False,
    ) -> DeduplicationResult:
        """Processes a parsed CV, resolves candidate identity, and persists records."""

        # 1. Level 1: File Hash Deduplication
        existing_file = get_candidate_file_by_hash(conn, parsed.file_hash)
        if existing_file:
            cand_id = existing_file["candidate_id"]
            return DeduplicationResult(
                action="SKIPPED_DUPLICATE_FILE",
                candidate_id=cand_id,
                file_record_id=existing_file["id"],
                message=f"Identical file already indexed (Candidate #{cand_id}).",
                is_duplicate=True,
            )

        # 2. Level 2: Normalized Email Match (Authoritative Identity)
        if parsed.normalized_email:
            existing_candidate = get_candidate_by_email(conn, parsed.normalized_email)
            if existing_candidate:
                cand_id = existing_candidate["id"]
                self._enrich_existing_candidate(conn, cand_id, existing_candidate, parsed)
                file_rec_id = record_candidate_file(
                    conn=conn,
                    candidate_id=cand_id,
                    file_path=parsed.file_path,
                    file_name=parsed.file_name,
                    file_hash=parsed.file_hash,
                    file_size=parsed.file_size,
                    file_type=parsed.file_type,
                    extracted_text=parsed.cleaned_text,
                    parsing_status=parsed.parsing_status,
                    parsing_error=parsed.error_message,
                    is_primary=0,
                )
                return DeduplicationResult(
                    action="UPDATED_EXISTING",
                    candidate_id=cand_id,
                    file_record_id=file_rec_id,
                    message=f"Matched existing candidate #{cand_id} by email ({parsed.normalized_email}). Profile updated.",
                    is_updated=True,
                )

        # 3. Level 3: Ambiguous Identity Check (Same Name, Different / Missing Email)
        if parsed.name and parsed.name.lower() not in ("candidate", "curriculum vitae", "resume"):
            row_same_name = conn.execute(
                "SELECT id, name, email, normalized_email FROM candidates WHERE LOWER(name) = ? LIMIT 1",
                (parsed.name.strip().lower(),),
            ).fetchone()

            if row_same_name:
                existing_same_name = dict(row_same_name)
                # If existing candidate has an email, and parsed CV has a DIFFERENT email:
                if parsed.normalized_email and existing_same_name.get("email"):
                    existing_norm = (existing_same_name.get("normalized_email") or existing_same_name.get("email", "")).lower().strip()
                    if parsed.normalized_email != existing_norm:
                        # DO NOT MERGE! Treat as distinct candidate to avoid conflating different individuals
                        logger.info(
                            "Ambiguous identity: Same name '%s' but different emails ('%s' vs '%s'). Keeping separate.",
                            parsed.name, parsed.normalized_email, existing_norm
                        )
                        return self._create_new_candidate(
                            conn,
                            parsed,
                            notes=f"Ambiguous name match with Candidate #{existing_same_name['id']} ('{existing_same_name.get('name')}') - separated due to distinct email.",
                            status="AMBIGUOUS_REVIEW",
                            permission_basis="UNVERIFIED",
                        )
                elif not parsed.normalized_email or not existing_same_name.get("email"):
                    # One or both lack verified email - flag for ambiguity review
                    logger.info(
                        "Ambiguous identity: Same name '%s' with unverified email on one or both profiles. Flagging for review.",
                        parsed.name
                    )
                    return self._create_new_candidate(
                        conn,
                        parsed,
                        notes=f"Ambiguous identity: Same name as existing Candidate #{existing_same_name['id']} ('{existing_same_name.get('name')}'), but email is unverified on one or both records. Recruiter manual review required.",
                        status="AMBIGUOUS_REVIEW",
                        permission_basis="UNVERIFIED",
                    )

        # 4. Level 4: Create Brand New Candidate Record
        return self._create_new_candidate(conn, parsed)

    def _enrich_existing_candidate(
        self,
        conn: sqlite3.Connection,
        candidate_id: int,
        existing: dict,
        parsed: ParsedCV,
    ) -> None:
        """Merges new CV intelligence into existing candidate record safely."""
        # Merge skills
        existing_skills: list[str] = []
        try:
            if existing.get("skills"):
                existing_skills = json.loads(existing["skills"])
        except Exception:
            existing_skills = []

        combined_skills = sorted(list(set(existing_skills + parsed.skills)))

        # Merge languages
        existing_langs: list[str] = []
        try:
            if existing.get("languages"):
                existing_langs = json.loads(existing["languages"])
        except Exception:
            existing_langs = []
        combined_langs = sorted(list(set(existing_langs + parsed.languages)))

        # Highest years of experience
        years_exp = max(existing.get("years_of_experience", 0) or 0, parsed.years_of_experience)

        # Phone if missing
        phone = existing.get("phone") or parsed.phone or ""

        # Update evidence text if new text contains more data
        evidence = existing.get("evidence_text") or ""
        if len(parsed.cleaned_text) > len(evidence):
            evidence = parsed.cleaned_text[:3500]

        now_iso = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """UPDATE candidates
            SET skills = ?, languages = ?, years_of_experience = ?, phone = ?, evidence_text = ?,
                resume_text = CASE WHEN resume_text = '' THEN ? ELSE resume_text END,
                resume_filename = ?,
                resume_uploaded_at = ?
            WHERE id = ?""",
            (
                json.dumps(combined_skills),
                json.dumps(combined_langs),
                years_exp,
                phone,
                evidence,
                parsed.cleaned_text[:4000],
                parsed.file_name,
                now_iso,
                candidate_id,
            ),
        )
        conn.commit()

    def _create_new_candidate(
        self,
        conn: sqlite3.Connection,
        parsed: ParsedCV,
        notes: str = "",
        status: str = "New",
        permission_basis: str = "PENDING_REVIEW",
    ) -> DeduplicationResult:
        """Inserts a brand new canonical candidate and associated candidate_file."""
        now_iso = datetime.now().isoformat(timespec="seconds")
        name = parsed.name.strip() if parsed.name else "Candidate"
        email = parsed.email.strip()
        norm_email = parsed.normalized_email.strip()
        phone = parsed.phone.strip()
        location = parsed.location.strip()
        headline = parsed.headline.strip()
        evidence = parsed.cleaned_text[:3500] if parsed.cleaned_text else "CV Uploaded"
        skills_json = json.dumps(parsed.skills)
        langs_json = json.dumps(parsed.languages)

        email_status = "PENDING_VERIFICATION" if norm_email and "@" in norm_email else "INVALID"

        cur = conn.execute(
            """INSERT INTO candidates(
                name, profile_url, headline, location, experience, source,
                evidence_text, notes, created_at, status, email, phone,
                normalized_email, skills, languages, years_of_experience,
                contact_permission_basis, email_verification_status, opt_out_status, suppression_reason,
                resume_text, resume_filename, resume_source, resume_uploaded_at,
                added_by, evidence_ladder_tier
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?, 'CV Upload', ?, 'Bulk CV Importer', 'Tier 1: Document CV')""",
            (
                name,
                f"file://local-cv/{parsed.file_hash[:12]}",
                headline,
                location,
                f"{parsed.years_of_experience} years documented",
                "CV Upload",
                evidence,
                notes,
                now_iso,
                status,
                email,
                phone,
                norm_email,
                skills_json,
                langs_json,
                parsed.years_of_experience,
                permission_basis,
                email_status,
                parsed.cleaned_text[:4000],
                parsed.file_name,
                now_iso,
            ),
        )
        cand_id = int(cur.lastrowid)

        file_rec_id = record_candidate_file(
            conn=conn,
            candidate_id=cand_id,
            file_path=parsed.file_path,
            file_name=parsed.file_name,
            file_hash=parsed.file_hash,
            file_size=parsed.file_size,
            file_type=parsed.file_type,
            extracted_text=parsed.cleaned_text,
            parsing_status=parsed.parsing_status,
            parsing_error=parsed.error_message,
            is_primary=1,
        )

        return DeduplicationResult(
            action="INSERTED_NEW",
            candidate_id=cand_id,
            file_record_id=file_rec_id,
            message=f"Created new candidate #{cand_id} ({name}).",
            is_new=True,
        )


cv_deduplicator = CVDeduplicator()
