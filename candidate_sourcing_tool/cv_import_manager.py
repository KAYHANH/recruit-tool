"""
CV Batch Import Manager — Orchestrates bulk CV import with bounded memory,
cancellation, resumption, per-file status tracking, and SQLite audit persistence.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
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

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".rtf"}

# ZIP Bomb & Payload Safeguards
MAX_ZIP_ARCHIVE_SIZE = 500 * 1024 * 1024  # 500 MB max compressed archive
MAX_TOTAL_EXPANDED_SIZE = 1024 * 1024 * 1024  # 1 GB max uncompressed total
MAX_PER_FILE_SIZE = 50 * 1024 * 1024  # 50 MB max per single CV file
MAX_FILE_COUNT = 2500  # 2500 files max per archive


class CVImportManager:
    """Manages bulk CV import tasks with persistent queue state in SQLite."""

    def __init__(self):
        self._cancel_flags: dict[str, bool] = {}
        self._pause_flags: dict[str, bool] = {}
        self._active_workers: dict[str, threading.Thread] = {}
        self._worker_lock = threading.Lock()

    def _start_worker_thread(self, db_path: str, job_id: str, batch_size: int) -> None:
        """Starts a background worker thread for a job if not already active."""
        with self._worker_lock:
            existing = self._active_workers.get(job_id)
            if existing and existing.is_alive():
                logger.info("Worker thread for job %s already running.", job_id)
                return
            t = threading.Thread(
                target=self._run_job_worker,
                args=(db_path, job_id, batch_size),
                daemon=True,
                name=f"CVImportWorker-{job_id[:8]}",
            )
            self._active_workers[job_id] = t
            t.start()

    def recover_interrupted_jobs(self, conn: sqlite3.Connection) -> int:
        """Recovers jobs that were left in PROCESSING state when server stopped/crashed."""
        rows = conn.execute(
            """SELECT job_id FROM cv_import_jobs WHERE status = 'PROCESSING'"""
        ).fetchall()
        count = 0
        for r in rows:
            update_cv_import_job(
                conn,
                r["job_id"],
                status="PAUSED",
                error_message="Interrupted by server restart. Click Resume or Retry to continue.",
            )
            count += 1
        if count > 0:
            logger.info("Recovered %d interrupted import job(s) into PAUSED state.", count)
        return count

    def cancel_job(self, conn: sqlite3.Connection, job_id: str) -> bool:
        """Signals an in-progress import job to cancel gracefully."""
        self._cancel_flags[job_id] = True
        job = get_cv_import_job(conn, job_id)
        if job and job["status"] in ("QUEUED", "PROCESSING", "PAUSED"):
            update_cv_import_job(
                conn,
                job_id,
                status="CANCELLED",
                completed_at=datetime.now().isoformat(timespec="seconds"),
                error_message="Import was cancelled by user.",
            )
            return True
        return False

    def pause_job(self, conn: sqlite3.Connection, job_id: str) -> bool:
        """Signals an in-progress import job to pause after current batch completes."""
        self._pause_flags[job_id] = True
        job = get_cv_import_job(conn, job_id)
        if job and job["status"] == "PROCESSING":
            update_cv_import_job(conn, job_id, status="PAUSED")
            return True
        return False

    def resume_job(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        batch_size: int = 15,
        run_async: bool = True,
    ) -> bool:
        """Resumes processing a paused import job."""
        job = get_cv_import_job(conn, job_id)
        if not job or job["status"] not in ("PAUSED", "QUEUED"):
            return False

        self._pause_flags[job_id] = False
        self._cancel_flags[job_id] = False
        update_cv_import_job(conn, job_id, status="PROCESSING")

        if run_async:
            db_path = conn.execute("PRAGMA database_list").fetchone()[2]
            self._start_worker_thread(db_path, job_id, batch_size)
        else:
            self._process_job_loop(conn, job_id, batch_size=batch_size)
        return True

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
            self._start_worker_thread(db_path, job_id, batch_size)
        else:
            self._process_job_loop(conn, job_id, batch_size=batch_size)

        return job_id

    def start_zip_import(
        self,
        conn: sqlite3.Connection,
        zip_source: bytes | Path | str,
        zip_filename: str,
        extract_to_dir: Path | str,
        batch_size: int = 15,
        run_async: bool = True,
    ) -> str:
        """Extracts a ZIP archive into a managed local folder with ZIP-bomb protection and starts import."""
        dest = Path(extract_to_dir).resolve() / f"zip_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        dest.mkdir(parents=True, exist_ok=True)

        try:
            total_expanded_bytes = 0
            extracted_file_count = 0

            if isinstance(zip_source, (Path, str)):
                source_path = Path(zip_source)
                if not source_path.exists():
                    raise ValueError(f"ZIP archive not found: {source_path}")
                archive_size = source_path.stat().st_size
                zf_ctx = zipfile.ZipFile(source_path)
            else:
                archive_size = len(zip_source)
                zf_ctx = zipfile.ZipFile(io.BytesIO(zip_source))

            if archive_size > MAX_ZIP_ARCHIVE_SIZE:
                raise ValueError(
                    f"Uploaded archive ({archive_size // (1024 * 1024)} MB) exceeds maximum allowed ZIP size ({MAX_ZIP_ARCHIVE_SIZE // (1024 * 1024)} MB)."
                )

            with zf_ctx as zf:
                members = zf.infolist()
                if len(members) > MAX_FILE_COUNT:
                    raise ValueError(
                        f"Archive contains {len(members)} files, which exceeds maximum safety limit of {MAX_FILE_COUNT} files."
                    )

                for member in members:
                    # Ignore directories
                    if member.is_dir() or member.filename.endswith("/"):
                        continue

                    # Reject symlinks (0o120000 in upper 16 bits of external_attr)
                    if (member.external_attr >> 16) & 0o170000 == 0o120000:
                        logger.warning("Rejecting symlink entry in zip: %s", member.filename)
                        continue

                    # Prevent zip-slip directory traversal
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        logger.warning("Rejecting suspicious path in zip: %s", member.filename)
                        continue

                    if member.file_size > MAX_PER_FILE_SIZE:
                        raise ValueError(
                            f"Archive file '{member.filename}' ({member.file_size // (1024 * 1024)} MB) exceeds single file limit of {MAX_PER_FILE_SIZE // (1024 * 1024)} MB."
                        )

                    total_expanded_bytes += member.file_size
                    if total_expanded_bytes > MAX_TOTAL_EXPANDED_SIZE:
                        raise ValueError(
                            f"Total uncompressed ZIP size exceeds safety limit of {MAX_TOTAL_EXPANDED_SIZE // (1024 * 1024)} MB (Potential ZIP bomb detected)."
                        )

                    ext = member_path.suffix.lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        target = (dest / member_path).resolve()
                        if not str(target).startswith(str(dest)):
                            logger.warning("Zip slip attempt detected and blocked: %s", member.filename)
                            continue

                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        extracted_file_count += 1

            if extracted_file_count == 0:
                shutil.rmtree(dest, ignore_errors=True)
                raise ValueError(f"No supported CV files ({', '.join(sorted(SUPPORTED_EXTENSIONS))}) found in uploaded ZIP archive.")

            return self.start_folder_import(conn, dest, batch_size=batch_size, run_async=run_async)

        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise

    def retry_failed_files(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        batch_size: int = 15,
        run_async: bool = True,
    ) -> bool:
        """Resets failed files in a job to QUEUED and reprocesses them.
        Note: Excludes OCR_REQUIRED files to prevent infinite loops without an active OCR engine."""
        job = get_cv_import_job(conn, job_id)
        if not job:
            return False

        conn.execute(
            """UPDATE cv_import_job_files
            SET status = 'QUEUED', error_message = ''
            WHERE job_id = ? AND status = 'FAILED'""",
            (job_id,),
        )
        conn.commit()

        update_cv_import_job(conn, job_id, status="PROCESSING", error_message="")
        if run_async:
            db_path = conn.execute("PRAGMA database_list").fetchall()[0][2]
            self._start_worker_thread(db_path, job_id, batch_size)
        else:
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

            # Check pause request
            if self._pause_flags.get(job_id, False):
                update_cv_import_job(conn, job_id, status="PAUSED")
                logger.info("Import job %s paused cleanly.", job_id)
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
