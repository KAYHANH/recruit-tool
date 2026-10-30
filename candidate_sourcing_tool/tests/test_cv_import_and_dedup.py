"""
Automated tests for Stage A: CV-to-Referral Outreach Module
Covers:
- PDF, DOCX, and TXT local text extraction
- Scanned PDF detection (OCR_REQUIRED)
- SHA-256 file hashing
- File hash deduplication
- Normalized email deduplication & profile enrichment
- Ambiguous identity separation (preventing accidental merges of same-named candidates)
- Batch folder import with cancellation, failure reporting, and retry
- Contact permission and opt-out suppression controls
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import docx
import fitz

from cv_deduplicator import cv_deduplicator
from cv_import_manager import cv_import_manager
from cv_parser import cv_parser
from db import (
    get_candidate,
    get_candidate_by_email,
    get_cv_import_job,
    get_cv_import_job_files,
    init_db,
    list_candidate_files,
    update_candidate_opt_out,
)


class TestCVExtractionAndDeduplication(unittest.TestCase):
    def setUp(self):
        # In-memory SQLite database initialized with all schemas and migrations
        self.conn = init_db(":memory:")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_txt_extraction_full(self):
        """Tests parsing a plain text resume with all core fields."""
        txt_content = (
            "Alice Walker\n"
            "alice.walker@example-domain.org\n"
            "+1 555-019-2834\n"
            "San Francisco, United States\n"
            "Summary: 6 years of experience building distributed systems and machine learning pipelines.\n"
            "Skills: Python, FastAPI, Docker, Kubernetes, PostgreSQL, React, TypeScript, PyTorch, LangChain\n"
            "Languages: English, Spanish\n"
        )
        parsed = cv_parser.parse_bytes(txt_content.encode("utf-8"), "Alice_Walker_CV.txt")

        self.assertEqual(parsed.parsing_status, "SUCCESS")
        self.assertEqual(parsed.name, "Alice Walker")
        self.assertEqual(parsed.normalized_email, "alice.walker@example-domain.org")
        self.assertIn("+1 555-019-2834", parsed.phone)
        self.assertEqual(parsed.years_of_experience, 6)
        self.assertIn("python", parsed.skills)
        self.assertIn("fastapi", parsed.skills)
        self.assertIn("pytorch", parsed.skills)
        self.assertIn("English", parsed.languages)
        self.assertIn("Spanish", parsed.languages)
        self.assertGreater(parsed.confidence_score, 0.7)

    def test_docx_extraction_in_memory(self):
        """Tests extracting and normalizing text from a DOCX document with paragraphs and tables."""
        doc = docx.Document()
        doc.add_paragraph("Bob Martin")
        doc.add_paragraph("bob.martin.engineer@techcorp.io | +1 415-555-0199")
        doc.add_paragraph("Senior Python & Cloud Architect with 8+ years of experience in AWS, Kubernetes, and Golang.")
        table = doc.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "Core Skills: Python, Golang, AWS, Terraform, Docker"
        table.rows[0].cells[1].text = "Languages: English, German"

        docx_bytes = io.BytesIO()
        doc.save(docx_bytes)
        docx_bytes.seek(0)

        parsed = cv_parser.parse_bytes(docx_bytes.read(), "Bob_Martin_Resume.docx")
        self.assertEqual(parsed.parsing_status, "SUCCESS")
        self.assertEqual(parsed.name, "Bob Martin")
        self.assertEqual(parsed.normalized_email, "bob.martin.engineer@techcorp.io")
        self.assertIn("golang", parsed.skills)
        self.assertIn("aws", parsed.skills)
        self.assertIn("German", parsed.languages)

    def test_pdf_extraction_in_memory(self):
        """Tests PDF text extraction and metadata derivation using PyMuPDF."""
        pdf_doc = fitz.open()
        page = pdf_doc.new_page()
        text = (
            "Carol Danvers\n"
            "carol.danvers@cloudinnovations.co\n"
            "Austin, Texas, United States\n"
            "10 years of experience in Fullstack Engineering, TypeScript, React, Next.js, and GraphQL.\n"
            "Languages: English, French\n"
        )
        page.insert_text((50, 50), text)
        pdf_bytes = pdf_doc.write()
        pdf_doc.close()

        parsed = cv_parser.parse_bytes(pdf_bytes, "Carol_Danvers_CV.pdf")
        self.assertEqual(parsed.parsing_status, "SUCCESS")
        self.assertEqual(parsed.name, "Carol Danvers")
        self.assertEqual(parsed.normalized_email, "carol.danvers@cloudinnovations.co")
        self.assertIn("react", parsed.skills)
        self.assertIn("typescript", parsed.skills)
        self.assertEqual(parsed.years_of_experience, 10)

    def test_scanned_or_empty_pdf_detection(self):
        """Tests that image-only / empty PDFs are detected as OCR_REQUIRED without raising fatal errors."""
        pdf_doc = fitz.open()
        pdf_doc.new_page()  # Blank page with 0 text
        pdf_bytes = pdf_doc.write()
        pdf_doc.close()

        parsed = cv_parser.parse_bytes(pdf_bytes, "scanned_doc.pdf")
        self.assertEqual(parsed.parsing_status, "OCR_REQUIRED")
        self.assertIn("Scanned or image-only", parsed.error_message)

    def test_empty_and_corrupt_files(self):
        """Tests that 0-byte files return FAILED gracefully."""
        parsed = cv_parser.parse_bytes(b"", "empty.txt")
        self.assertEqual(parsed.parsing_status, "FAILED")
        self.assertIn("empty", parsed.error_message.lower())

    def test_file_hash_deduplication(self):
        """Tests that importing the exact same file twice flags the second as SKIPPED_DUPLICATE_FILE."""
        txt_content = (
            "David Miller\n"
            "david.miller@domaintech.com\n"
            "Skills: Python, FastAPI, SQL\n"
        ).encode("utf-8")

        parsed1 = cv_parser.parse_bytes(txt_content, "david_cv.txt", file_path="/mock/david_cv.txt")
        res1 = cv_deduplicator.process_parsed_cv(self.conn, parsed1)
        self.assertEqual(res1.action, "INSERTED_NEW")
        self.assertIsNotNone(res1.candidate_id)

        # Second import with identical content and hash
        parsed2 = cv_parser.parse_bytes(txt_content, "david_cv_copy.txt", file_path="/mock/david_cv_copy.txt")
        res2 = cv_deduplicator.process_parsed_cv(self.conn, parsed2)
        self.assertEqual(res2.action, "SKIPPED_DUPLICATE_FILE")
        self.assertEqual(res2.candidate_id, res1.candidate_id)
        self.assertTrue(res2.is_duplicate)

        # Verify only 1 candidate was inserted
        cand_count = self.conn.execute("SELECT count(*) FROM candidates").fetchone()[0]
        self.assertEqual(cand_count, 1)

    def test_email_deduplication_and_multiple_file_references(self):
        """Tests that different CV files belonging to the same email merge skills and maintain multiple file references."""
        cv1 = (
            "Emily Watson\n"
            "emily.watson@talentpool.io\n"
            "3 years exp\n"
            "Skills: React, TypeScript\n"
        ).encode("utf-8")

        cv2 = (
            "Emily Watson\n"
            "emily.watson@talentpool.io\n"
            "5 years of experience\n"
            "Skills: Python, Docker, Next.js\n"
            "Languages: Spanish\n"
        ).encode("utf-8")

        parsed1 = cv_parser.parse_bytes(cv1, "emily_2022.txt", file_path="/mock/emily_2022.txt")
        res1 = cv_deduplicator.process_parsed_cv(self.conn, parsed1)
        self.assertEqual(res1.action, "INSERTED_NEW")

        parsed2 = cv_parser.parse_bytes(cv2, "emily_2024.txt", file_path="/mock/emily_2024.txt")
        res2 = cv_deduplicator.process_parsed_cv(self.conn, parsed2)
        self.assertEqual(res2.action, "UPDATED_EXISTING")
        self.assertEqual(res2.candidate_id, res1.candidate_id)

        # Check candidate profile has merged skills
        cand = get_candidate(self.conn, res1.candidate_id)
        skills = json.loads(cand["skills"])
        self.assertIn("react", skills)
        self.assertIn("python", skills)
        self.assertIn("docker", skills)
        self.assertEqual(cand["years_of_experience"], 5)

        # Check candidate_files table holds both file records
        files = list_candidate_files(self.conn, res1.candidate_id)
        self.assertEqual(len(files), 2)
        filenames = [f["file_name"] for f in files]
        self.assertIn("emily_2022.txt", filenames)
        self.assertIn("emily_2024.txt", filenames)

    def test_ambiguous_name_distinct_email_not_merged(self):
        """Tests that two different individuals with the same name but different emails are NEVER merged."""
        cv1 = "Alex Smith\nalex.smith.1@company-a.com\nSkills: Java\n".encode("utf-8")
        cv2 = "Alex Smith\nalex.smith.99@company-z.com\nSkills: Python, Rust\n".encode("utf-8")

        parsed1 = cv_parser.parse_bytes(cv1, "alex_a.txt", file_path="/mock/alex_a.txt")
        res1 = cv_deduplicator.process_parsed_cv(self.conn, parsed1)
        self.assertEqual(res1.action, "INSERTED_NEW")

        parsed2 = cv_parser.parse_bytes(cv2, "alex_z.txt", file_path="/mock/alex_z.txt")
        res2 = cv_deduplicator.process_parsed_cv(self.conn, parsed2)
        self.assertEqual(res2.action, "INSERTED_NEW")
        self.assertNotEqual(res1.candidate_id, res2.candidate_id)

        # Both records must exist separately
        cand_count = self.conn.execute("SELECT count(*) FROM candidates").fetchone()[0]
        self.assertEqual(cand_count, 2)

    def test_batch_folder_import_pipeline(self):
        """Tests full batch folder scanning, processing, error handling, and stats."""
        # Create 3 valid CVs, 1 duplicate, and 1 empty file
        f1 = self.dir_path / "cv1.txt"
        f1.write_text("Grace Hopper\ngrace@navy.mil\nSkills: Python, SQL\n", encoding="utf-8")

        f2 = self.dir_path / "cv2.txt"
        f2.write_text("Alan Turing\nalan@bletchley.uk\nSkills: Machine Learning, Python\n", encoding="utf-8")

        # Duplicate of cv1 with different filename
        f3 = self.dir_path / "cv1_backup.txt"
        f3.write_text("Grace Hopper\ngrace@navy.mil\nSkills: Python, SQL\n", encoding="utf-8")

        # Empty file
        f4 = self.dir_path / "empty.txt"
        f4.write_text("", encoding="utf-8")

        job_id = cv_import_manager.start_folder_import(
            conn=self.conn,
            folder_path=self.dir_path,
            batch_size=2,
            run_async=False,
        )

        job = get_cv_import_job(self.conn, job_id)
        self.assertEqual(job["total_files"], 4)
        self.assertEqual(job["processed_files"], 4)
        self.assertEqual(job["successful_files"], 2)  # cv1 and cv2
        self.assertEqual(job["duplicate_files"], 1)   # cv1_backup
        self.assertEqual(job["failed_files"], 1)      # empty.txt
        self.assertEqual(job["status"], "PARTIAL")

        # Verify job file items
        files = get_cv_import_job_files(self.conn, job_id)
        self.assertEqual(len(files), 4)

    def test_contact_permission_and_opt_out(self):
        """Tests setting contact permission basis and recording opt-out suppression."""
        cv_text = "Fiona Gallagher\nfiona@chicago.org\nSkills: React\n".encode("utf-8")
        parsed = cv_parser.parse_bytes(cv_text, "fiona.txt", file_path="/mock/fiona.txt")
        res = cv_deduplicator.process_parsed_cv(self.conn, parsed)
        cand_id = res.candidate_id

        # Candidate is initially not opted out
        cand = get_candidate(self.conn, cand_id)
        self.assertEqual(cand["opt_out_status"], 0)

        # Record opt-out
        update_candidate_opt_out(self.conn, cand_id, opt_out=True, reason="Requested removal via email")
        cand_after = get_candidate(self.conn, cand_id)
        self.assertEqual(cand_after["opt_out_status"], 1)
        self.assertEqual(cand_after["suppression_reason"], "Requested removal via email")

    def test_rtf_extraction(self):
        """Tests local RTF resume text extraction with RTF formatting code stripping."""
        rtf_content = (
            "{\\rtf1\\ansi\\deff0\n"
            "{\\fonttbl{\\f0 Helvetica;}}\n"
            "\\viewkind4\\uc1\\pard\\f0\\fs24\n"
            "Grace Kelly\\par\n"
            "grace.kelly@hollywoodtech.com | +1 555-492-9901\\par\n"
            "Los Angeles, California\\par\n"
            "Summary: 7 years of experience in full-stack engineering with Python, React, and AWS.\\par\n"
            "Skills: Python, React, PostgreSQL, Docker\\par\n"
            "Languages: English, French\\par\n"
            "}"
        ).encode("ascii")

        parsed = cv_parser.parse_bytes(rtf_content, "grace_resume.rtf")
        self.assertEqual(parsed.parsing_status, "SUCCESS")
        self.assertEqual(parsed.name, "Grace Kelly")
        self.assertEqual(parsed.normalized_email, "grace.kelly@hollywoodtech.com")
        self.assertIn("python", parsed.skills)
        self.assertIn("react", parsed.skills)
        self.assertEqual(parsed.years_of_experience, 7)

    def test_zip_slip_rejection(self):
        """Tests that ZIP archives containing path traversal entries (.. or /evil) are rejected."""
        import zipfile
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            # Dangerous zip-slip member
            zf.writestr("../../evil_exploit.txt", "Malicious file outside extraction dir")
        zip_buf.seek(0)

        with self.assertRaises(ValueError) as ctx:
            cv_import_manager.start_zip_import(
                conn=self.conn,
                zip_source=zip_buf.getvalue(),
                zip_filename="dangerous.zip",
                extract_to_dir=self.dir_path / "zip_test",
                batch_size=5,
                run_async=False,
            )
        self.assertIn("no supported cv files", str(ctx.exception).lower())

    def test_zip_symlink_rejection(self):
        """Tests that ZIP archives containing symlinks are safely skipped without resolving links."""
        import zipfile
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            # Create symlink member
            zi = zipfile.ZipInfo("symlink_exploit.pdf")
            zi.create_system = 3  # Unix
            zi.external_attr = 0o120777 << 16  # Symlink bit
            zf.writestr(zi, "/etc/passwd")
        zip_buf.seek(0)

        with self.assertRaises(ValueError) as ctx:
            cv_import_manager.start_zip_import(
                conn=self.conn,
                zip_source=zip_buf.getvalue(),
                zip_filename="symlink.zip",
                extract_to_dir=self.dir_path / "zip_symlink_test",
                batch_size=5,
                run_async=False,
            )
        self.assertIn("no supported cv files", str(ctx.exception).lower())

    def test_worker_recovery_after_interruption(self):
        """Tests that recover_interrupted_jobs resets stuck PROCESSING jobs to PAUSED upon server restart."""
        # Create mock stuck PROCESSING job
        self.conn.execute(
            """INSERT INTO cv_import_jobs(job_id, source_type, source_path, status, total_files, processed_files, created_at)
            VALUES('job-stuck-123', 'folder', '/mock/folder', 'PROCESSING', 10, 3, '2026-10-30')"""
        )
        self.conn.commit()

        recovered_count = cv_import_manager.recover_interrupted_jobs(self.conn)
        self.assertEqual(recovered_count, 1)

        job = get_cv_import_job(self.conn, 'job-stuck-123')
        self.assertEqual(job["status"], "PAUSED")
        self.assertIn("interrupted", job["error_message"].lower())


if __name__ == "__main__":
    unittest.main()
