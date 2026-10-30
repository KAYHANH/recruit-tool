"""
CV Batch Import Manager — Orchestrates bulk CV import with bounded memory,
cancellation, resumption, per-file status tracking, and SQLite audit persistence.
"""
from __future__ import annotations

import io
import logging
import sqlite3
import threading
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Generator

from cv_deduplicator import cv_deduplicator
from cv_parser import cv_parser
from db import (
    add_cv_import_job_file,
    create_cv_import_job,
    get_cv_import_job,
    get_cv_import_job_files,
    update_cv_import_job,
    update_cv_import_job_file,
)

logger = logging.getLogger("cv_import_manager")

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


class CVImportManager:
    """Manages bulk CV import tasks with persistent queue state in SQLite."""

    def __init__(self):
        self._cancel_flags: dict[str, bool] = {}

    def cancel_job(self, conn: sqlite3.Connection, job_id: str) -> bool:
        """Signals an in-progress import job to cancel gracefully."""
        self._cancel_flags[job_id] = True
        job = get_cv_import_job(conn, job_id)
        if job and job["status"] in ("QUEUED", "PROCESSING"):
            update_cv_import_job(
                conn,
                job_id,
                status="CANCELLED",
                completed_at=datetime.now().isoformat(timespec="seconds"),
                error_message="Import was cancelled by user.",
            )
            return True
        return False

    def scan_folder_for_cvs(self, folder_path: Path | str) -> list[Path]:
        """Recursively finds all supported CV files in a given directory."""
        root = Path(folder_path).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Directory not found: {folder_path}")

        files: list[Path] = []
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                # Skip hidden files or lock files
                if path.name.startswith((".", "~$")):
                    continue
                files.append(path)
        return sorted(files)

    def start_folder_import(
        self,
        conn: sqlite3.Connection,
        folder_path: Path | str,
        batch_size: int = 15,
        run_async: bool = False,
    ) -> str:
        """Initializes and runs an import job for a Windows folder of CVs."""
        job_id = str(uuid.uuid4())
        files = self.scan_folder_for_cvs(folder_path)

        create_cv_import_job(
            conn=conn,
            job_id=job_id,
            source_type="folder",
            source_path=str(folder_path),
            total_files=len(files),
        )

        for p in files:
            add_cv_import_job_file(
                conn=conn,
                job_id=job_id,
                file_path=str(p),
                file_name=p.name,
                file_size=p.stat().st_size,
                file_type=p.suffix.lower().lstrip("."),
                status="QUEUED",
            )

        if run_async:
            db_path = conn.execute("PRAGMA database_list").fetchall()[0][2]
            t = threading.Thread(
                target=self._run_job_worker,
                args=(db_path, job_id, batch_size),
                daemon=True,
            )
            t.start()
        else:
            self._process_job_loop(conn, job_id, batch_size=batch_size)

        return job_id

    def start_zip_import(
        self,
        conn: sqlite3.Connection,
        zip_bytes: bytes,
        zip_filename: str,
        extract_to_dir: Path | str,
        batch_size: int = 15,
        run_async: bool = False,
    ) -> str:
        """Extracts a ZIP archive into a managed local folder and starts import."""
        dest = Path(extract_to_dir).resolve() / f"zip_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        dest.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for member in zf.infolist():
                # Prevent zip-slip directory traversal
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    continue
                if member.filename.endswith("/"):
                    continue
                ext = member_path.suffix.lower()
                if ext in SUPPORTED_EXTENSIONS:
                    target = dest / member_path.name
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())

        return self.start_folder_import(conn, dest, batch_size=batch_size, run_async=run_async)

    def retry_failed_files(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        batch_size: int = 15,
    ) -> bool:
        """Resets failed files in a job to QUEUED and reprocesses them."""
        job = get_cv_import_job(conn, job_id)
        if not job:
            return False

        conn.execute(
            """UPDATE cv_import_job_files
            SET status = 'QUEUED', error_message = ''
            WHERE job_id = ? AND status IN ('FAILED', 'OCR_REQUIRED')""",
            (job_id,),
        )
        conn.commit()

        update_cv_import_job(conn, job_id, status="PROCESSING", error_message="")
        self._process_job_loop(conn, job_id, batch_size=batch_size)
        return True

    def _run_job_worker(self, db_path: str, job_id: str, batch_size: int):
        """Worker thread entrypoint for async job execution."""
        from db import init_db
        conn = init_db(db_path)
        try:
            self._process_job_loop(conn, job_id, batch_size=batch_size)
        finally:
            conn.close()

    def _process_job_loop(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        batch_size: int = 15,
    ) -> None:
        """Iterates through pending files in bounded chunks and processes them."""
        update_cv_import_job(conn, job_id, status="PROCESSING")
        self._cancel_flags[job_id] = False

        while True:
            # Check cancellation
            if self._cancel_flags.get(job_id, False):
                update_cv_import_job(
                    conn,
                    job_id,
                    status="CANCELLED",
                    completed_at=datetime.now().isoformat(timespec="seconds"),
                )
                break

            # Fetch a small batch of QUEUED files
            rows = conn.execute(
                """SELECT id, file_path, file_name, file_size, file_type
                FROM cv_import_job_files
                WHERE job_id = ? AND status = 'QUEUED'
                ORDER BY id ASC LIMIT ?""",
                (job_id, batch_size),
            ).fetchall()

            if not rows:
                # All files processed!
                self._finalize_job_status(conn, job_id)
                break

            for row in rows:
                if self._cancel_flags.get(job_id, False):
                    break

                file_id = row["id"]
                file_path = row["file_path"]
                file_name = row["file_name"]

                try:
                    update_cv_import_job_file(conn, file_id, status="PROCESSING")
                    parsed = cv_parser.parse_file(file_path)

                    if parsed.parsing_status == "OCR_REQUIRED":
                        update_cv_import_job_file(
                            conn,
                            file_id,
                            status="OCR_REQUIRED",
                            error_message="Scanned or image-only PDF. OCR required.",
                            file_hash=parsed.file_hash,
                        )
                        continue

                    if parsed.parsing_status == "FAILED":
                        update_cv_import_job_file(
                            conn,
                            file_id,
                            status="FAILED",
                            error_message=parsed.error_message or "Extraction failed.",
                            file_hash=parsed.file_hash,
                        )
                        continue

                    # Deduplication & Persistence
                    dedup_res = cv_deduplicator.process_parsed_cv(conn, parsed)

                    if dedup_res.action == "SKIPPED_DUPLICATE_FILE":
                        file_status = "SKIPPED_DUPLICATE"
                    else:
                        file_status = "SUCCESS"

                    update_cv_import_job_file(
                        conn,
                        file_id,
                        status=file_status,
                        error_message="",
                        candidate_id=dedup_res.candidate_id,
                        file_hash=parsed.file_hash,
                    )

                except Exception as exc:
                    logger.exception("Error processing file %s: %s", file_name, exc)
                    update_cv_import_job_file(
                        conn,
                        file_id,
                        status="FAILED",
                        error_message=str(exc),
                    )

            # Update aggregate counters in cv_import_jobs
            self._sync_job_counters(conn, job_id)

    def _sync_job_counters(self, conn: sqlite3.Connection, job_id: str) -> None:
        """Audits database counts for this job and persists updated progress."""
        stats = conn.execute(
            """SELECT
                count(*) as total,
                sum(case when status != 'QUEUED' and status != 'PROCESSING' then 1 else 0 end) as processed,
                sum(case when status = 'SUCCESS' then 1 else 0 end) as successful,
                sum(case when status in ('FAILED', 'OCR_REQUIRED') then 1 else 0 end) as failed,
                sum(case when status = 'SKIPPED_DUPLICATE' then 1 else 0 end) as duplicates
            FROM cv_import_job_files
            WHERE job_id = ?""",
            (job_id,),
        ).fetchone()

        if stats:
            update_cv_import_job(
                conn,
                job_id,
                processed_files=stats["processed"] or 0,
                successful_files=stats["successful"] or 0,
                failed_files=stats["failed"] or 0,
                duplicate_files=stats["duplicates"] or 0,
            )

    def _finalize_job_status(self, conn: sqlite3.Connection, job_id: str) -> None:
        """Calculates final job outcome status and sets completed_at timestamp."""
        self._sync_job_counters(conn, job_id)
        job = get_cv_import_job(conn, job_id)
        if not job:
            return

        total = job["total_files"]
        successful = job["successful_files"]
        failed = job["failed_files"]
        duplicates = job["duplicate_files"]

        now_iso = datetime.now().isoformat(timespec="seconds")

        if successful + duplicates == total:
            final_status = "COMPLETED"
        elif successful > 0 or duplicates > 0:
            final_status = "PARTIAL"
        else:
            final_status = "FAILED"

        update_cv_import_job(
            conn,
            job_id,
            status=final_status,
            completed_at=now_iso,
        )


cv_import_manager = CVImportManager()
