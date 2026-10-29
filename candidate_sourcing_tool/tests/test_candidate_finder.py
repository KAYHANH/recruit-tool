from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import unquote_plus

import pytest

from db import (
    add_job,
    add_or_update_candidate,
    add_search_history,
    create_backup,
    get_job,
    get_search_history,
    init_db,
    is_query_repeated,
    list_candidates,
    list_jobs,
    restore_database,
)
from jd_parser import (
    DocumentParsingError,
    ScannedOrEmptyPdfError,
    clean_text,
    parse_document,
)
from keyword_extractor import JobRequirements, extract_location, extract_requirements
from matcher import (
    ScoringWeights,
    evaluate_candidate,
    sanitize_csv_cell,
    sanitize_dataframe_for_csv,
)
from query_generator import generate_search_queries
from search_provider import (
    GoogleCseProvider,
    LocalFallbackProvider,
    SerpApiProvider,
    get_search_provider,
)
from title_extractor import (
    clean_title_candidate,
    extract_alternative_titles_from_overview,
    extract_job_title,
)


# --- 1. Title Extraction & Noise Removal Tests ---

def test_extract_digital_image_specialist_without_page_noise():
    """Verifies that 'Digital Image Specialist | 1' and filename artifacts do NOT pollute the title."""
    sample_raw_text = """
FUTUREJOBS
FUTUREJOBS
Digital Image Specialist | 1
FUTUREJOBS
Digital Image Specialist
Short-term contract · Remote · Pay per task
ROLE ID: 102612
100 active openings

Role Overview
We are seeking creative digital imaging specialists, digital artists, and 3D artists.
Requirements:
- 3D modeling, texturing, Blender, ZBrush
- Strong portfolio
"""
    result = extract_job_title(sample_raw_text)
    assert result.title == "Digital Image Specialist"
    assert "| 1" not in result.title
    assert "FutureJobs" not in result.title
    assert result.confidence_level in {"High", "Medium"}


def test_clean_title_candidate_variations():
    """Tests various page marker and separator formats."""
    assert clean_title_candidate("Digital Image Specialist | 1") == "Digital Image Specialist"
    assert clean_title_candidate("Digital Image Specialist | Page 1 of 2") == "Digital Image Specialist"
    assert clean_title_candidate("Digital Image Specialist - 1") == "Digital Image Specialist"
    assert clean_title_candidate("1 | Digital Image Specialist") == "Digital Image Specialist"
    assert clean_title_candidate("Page 2 - 3D Artist") == "3D Artist"
    assert clean_title_candidate("Backend Software Engineer (1)") == "Backend Software Engineer"
    # Preserves valid names with digits
    assert clean_title_candidate("3D Artist") == "3D Artist"
    assert clean_title_candidate("2D Animator") == "2D Animator"


def test_alternative_job_titles_detection():
    """Verifies that alternative job titles are detected and presented."""
    sample_text = """
Digital Image Specialist
Role Overview
We are seeking creative and detail-oriented digital imaging specialists, digital artists, and 3D artists who can create stylized assets.
"""
    result = extract_job_title(sample_text)
    assert result.title == "Digital Image Specialist"
    assert any("3D Artist" in alt for alt in result.alternative_titles)
    assert any("Digital Artist" in alt for alt in result.alternative_titles)


# --- 2. Stopword, Boilerplate & Multiword Skill Tests ---

def test_stopword_and_boilerplate_removal():
    """Verifies that noise words (per, can, after, task, availability, FutureJobs) are completely excluded."""
    noisy_jd = """
Digital Image Specialist
FutureJobs portal. 100 active openings.
Rate: $3.50 per task.
Availability: Up to 40 hours per week.
Work begins after portfolio approval.
Candidates can apply immediately.
Requirements:
- 3D modeling
- Texture creation
- Blender proficiency
"""
    reqs = extract_requirements(noisy_jd)
    noise = ["per", "can", "after", "task", "availability", "futurejobs", "hours", "rate"]

    all_extracted = set(reqs.required_skills + reqs.tools_and_tech + reqs.inferred_keywords)
    for w in noise:
        assert w not in all_extracted, f"Boilerplate word '{w}' was incorrectly extracted as a skill!"


def test_preservation_of_meaningful_multiword_skills():
    """Verifies that multiword technical terms are properly parsed as full phrases."""
    jd = """
Backend Software Engineer
Requirements:
- 3+ years experience with rest apis and machine learning
- Proficiency in test-driven development and continuous integration
- Working knowledge of material creation and visual storytelling
"""
    reqs = extract_requirements(jd)
    assert "rest apis" in reqs.required_skills
    assert "machine learning" in reqs.required_skills
    assert "material creation" in reqs.required_skills
    assert "visual storytelling" in reqs.required_skills


# --- 3. Empty Documents & Scanned PDF Handling ---

def test_empty_document_handling():
    """Verifies that empty documents raise appropriate parsing errors."""
    with pytest.raises(DocumentParsingError):
        parse_document(b"", "empty.txt")

    with pytest.raises(DocumentParsingError):
        parse_document(b"   ", "empty.md")


def test_scanned_pdf_error_message():
    """Verifies that a PDF with no extractable text triggers ScannedOrEmptyPdfError with OCR warning."""
    # Create an empty minimal PDF stream using fitz if available
    try:
        import fitz
        doc = fitz.open()
        doc.new_page()  # blank page without text
        pdf_bytes = doc.tobytes()
        doc.close()

        with pytest.raises(ScannedOrEmptyPdfError) as exc_info:
            parse_document(pdf_bytes, "scanned_doc.pdf")
        assert "scanned or image-only" in str(exc_info.value).lower()
        assert "ocr" in str(exc_info.value).lower()
    except ImportError:
        pass


def test_clean_text_unicode_normalization():
    """Tests normalization of unicode characters, bullets, and dashes."""
    raw = "• Role\u2013Title with \u2018curly quotes\u2019 and broken hy-\nphenation."
    cleaned = clean_text(raw)
    assert "- Role-Title" in cleaned
    assert "'curly quotes'" in cleaned
    assert "hyphenation" in cleaned


# --- 4. Query Generation Diversity & URL Encoding ---

def test_query_diversity_and_url_encoding():
    """Verifies that 6-12 distinct queries are generated without duplicates and with proper URL encoding."""
    reqs = JobRequirements(
        job_title="Digital Image Specialist",
        alternative_titles=["Digital Artist", "3D Artist"],
        required_skills=["3d modeling", "texturing", "material creation"],
        tools_and_tech=["blender", "zbrush", "adobe creative suite"],
        location="Remote",
        portfolio_required=True,
    )
    queries = generate_search_queries(reqs)
    assert 6 <= len(queries) <= 12

    # Check query uniqueness
    query_texts = [q.query_text for q in queries]
    assert len(query_texts) == len(set(query_texts)), "Duplicate search queries were generated!"

    # Check Boolean formatting: balanced parentheses and quotes
    for q in queries:
        assert q.query_text.count("(") == q.query_text.count(")"), f"Unbalanced parentheses in: {q.query_text}"
        assert q.query_text.count('"') % 2 == 0, f"Unbalanced quotes in: {q.query_text}"
        # Check URL encoding
        assert "https://www.google.com/search?q=" in q.google_url
        decoded = unquote_plus(q.google_url.split("?q=")[1])
        assert "Digital Image Specialist" in decoded or "3D Artist" in decoded or "blender" in decoded


# --- 5. Candidate Matching & Missing Requirements ---

def test_candidate_scoring_missing_requirements():
    """Verifies that missing evidence does NOT fabricate disqualifications and displays 'Not found'."""
    reqs = JobRequirements(
        job_title="Digital Image Specialist",
        required_skills=["3d modeling", "uv mapping"],
        tools_and_tech=["blender"],
        location="Remote",
    )
    # Candidate with only 3D modeling and Blender, missing UV mapping
    candidate = {
        "id": 1,
        "name": "Jane Doe",
        "headline": "Digital Image Specialist",
        "evidence_text": "Experienced in 3D modeling using Blender.",
    }
    eval_res = evaluate_candidate(candidate, reqs)

    statuses = {c.requirement: c.status for c in eval_res.criteria_matches}
    assert statuses["3d modeling"] == "Matched"
    assert statuses["blender"] == "Matched"
    assert statuses["uv mapping"] == "Not found"
    assert eval_res.total_score > 0  # Still scored positively on observed skills


def test_candidate_scoring_contradictory_evidence():
    """Verifies that explicit negative evidence triggers 'Contradictory' status and score penalty."""
    reqs = JobRequirements(
        job_title="Digital Image Specialist",
        required_skills=["3d modeling"],
        tools_and_tech=["blender"],
    )
    candidate = {
        "id": 2,
        "name": "John Skeptical",
        "evidence_text": "I do 2D graphics only. No Blender experience and no 3D modeling experience.",
    }
    eval_res = evaluate_candidate(candidate, reqs)
    contradictory = [c for c in eval_res.criteria_matches if c.status == "Contradictory"]
    assert len(contradictory) >= 1
    assert eval_res.total_score <= 30


# --- 6. Database Safety & Migration Tests ---

def test_database_backup_and_preservation(tmp_path):
    """Verifies that database backups are transactional and preserve all existing rows."""
    db_file = tmp_path / "test_sourcing.db"
    conn = init_db(db_file)

    # Insert a sample job and candidate
    job_id = add_job(conn, "Initial Job", "Initial JD text")
    ok, msg, cand_id = add_or_update_candidate(
        conn,
        {"name": "Initial Candidate", "evidence_text": "Experienced Python engineer"},
        job_id,
    )
    assert ok and cand_id is not None
    conn.close()

    # Create backup
    backup_file = create_backup(db_file, tmp_path)
    assert backup_file.exists()
    assert backup_file.stat().st_size > 0

    # Verify backup contains exact records
    backup_conn = sqlite3.connect(backup_file)
    backup_conn.row_factory = sqlite3.Row
    jobs = list_jobs(backup_conn)
    candidates = list_candidates(backup_conn)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Initial Job"
    assert len(candidates) == 1
    assert candidates[0]["name"] == "Initial Candidate"
    backup_conn.close()


def test_candidate_deduplication(tmp_path):
    """Verifies that candidates with the same profile_url and name are updated rather than duplicated."""
    db_file = tmp_path / "dedup_test.db"
    conn = init_db(db_file)

    cand_data = {
        "name": "Sarah Connor",
        "profile_url": "https://linkedin.com/in/sarah-connor",
        "headline": "Junior Artist",
        "evidence_text": "Initial evidence text",
    }
    ok1, _, id1 = add_or_update_candidate(conn, cand_data)
    assert ok1

    # Update with new evidence
    cand_data_updated = {
        "name": "Sarah Connor",
        "profile_url": "https://linkedin.com/in/sarah-connor",
        "headline": "Lead 3D Artist",
        "evidence_text": "Updated evidence with Blender and Maya.",
    }
    ok2, msg2, id2 = add_or_update_candidate(conn, cand_data_updated)
    assert ok2
    assert id1 == id2  # Same record updated

    all_cands = list_candidates(conn)
    assert len(all_cands) == 1
    assert all_cands[0]["headline"] == "Lead 3D Artist"
    assert "Updated evidence" in all_cands[0]["evidence_text"]
    conn.close()


def test_existing_database_access():
    """Verifies that the actual project candidate_sourcing.db can be safely opened and read."""
    actual_db = Path("candidate_sourcing.db")
    if actual_db.exists():
        conn = init_db(actual_db)
        jobs = list_jobs(conn)
        assert len(jobs) >= 1
        job1 = get_job(conn, 1)
        assert job1 is not None
        assert "Digital Image Specialist" in job1["title"] or "1" in str(job1["id"])
        conn.close()


# --- 7. Search History & Repeated Query Detection ---

def test_search_history_and_repeated_query(tmp_path):
    """Verifies search query logging and repeated query detection."""
    db_file = tmp_path / "search_history_test.db"
    conn = init_db(db_file)
    job_id = add_job(conn, "3D Artist", "Job description text")

    q_text = 'site:linkedin.com/in ("3D Artist" OR "Blender")'

    # Check initially not repeated
    is_rep, ts = is_query_repeated(conn, job_id, q_text)
    assert not is_rep
    assert ts is None

    # Log query
    row_id = add_search_history(conn, job_id, q_text, strategy="Role & Tool", notes="First run")
    assert row_id > 0

    # Check now repeated
    is_rep, ts = is_query_repeated(conn, job_id, q_text)
    assert is_rep
    assert ts is not None

    # Retrieve history
    history = get_search_history(conn, job_id)
    assert len(history) == 1
    assert history[0]["query_text"] == q_text
    assert history[0]["strategy"] == "Role & Tool"
    conn.close()


# --- 8. Configurable Scoring Weights ---

def test_configurable_scoring_weights():
    """Verifies that customizing ScoringWeights alters candidate scores predictably."""
    reqs = JobRequirements(
        job_title="Digital Image Specialist",
        required_skills=["3d modeling", "uv mapping"],
        tools_and_tech=["photoshop"],
    )
    # Candidate with only tools (photoshop), no core skills
    candidate = {
        "id": 10,
        "name": "Alex Mercer",
        "headline": "Junior Artist",
        "evidence_text": "Experienced only in Photoshop graphic editing.",
    }

    # Default weights: tools = 25
    default_eval = evaluate_candidate(candidate, reqs)

    # Custom weights: tools = 10, core_skills = 60
    custom_weights = ScoringWeights(
        core_skills=60,
        tools=10,
        role_alignment=10,
        location=10,
        portfolio=10,
    )
    custom_eval = evaluate_candidate(candidate, reqs, weights=custom_weights)

    assert default_eval.score_breakdown["Tools & Software"] == 25
    assert custom_eval.score_breakdown["Tools & Software"] == 10
    assert default_eval.total_score != custom_eval.total_score
    assert custom_eval.total_score > 0


# --- 9. Safe Database Restore & Safety Rollback ---

def test_safe_database_restore_and_rollback(tmp_path):
    """Verifies atomic database restore and safety rollback on corrupted backup."""
    target_db = tmp_path / "live_candidate_sourcing.db"
    target_conn = init_db(target_db)
    add_job(target_conn, "Target Original Job", "Description")
    target_conn.close()

    # Create a valid backup DB with 2 jobs
    valid_backup_file = tmp_path / "valid_backup.db"
    valid_conn = init_db(valid_backup_file)
    add_job(valid_conn, "Backup Job 1", "Desc 1")
    add_job(valid_conn, "Backup Job 2", "Desc 2")
    valid_conn.close()

    # Perform safe restore
    ok, msg, safety_snap = restore_database(valid_backup_file, target_db)
    assert ok, f"Restore failed: {msg}"
    assert safety_snap is not None and safety_snap.exists()

    # Check restored data
    verify_conn = init_db(target_db)
    jobs = list_jobs(verify_conn)
    assert len(jobs) == 2
    verify_conn.close()

    # Test corrupted restore: passing invalid binary bytes
    ok_corrupt, msg_corrupt, snap2 = restore_database(b"NOT_A_VALID_SQLITE_DATABASE", target_db)
    assert not ok_corrupt
    assert "not a database" in msg_corrupt.lower() or "invalid backup" in msg_corrupt.lower() or "failed" in msg_corrupt.lower()

    # Verify target DB was NOT destroyed and remains valid with the 2 jobs
    post_corrupt_conn = init_db(target_db)
    jobs_after = list_jobs(post_corrupt_conn)
    assert len(jobs_after) == 2
    post_corrupt_conn.close()


# --- 10. Optional Search Provider & Quota / Error Handling ---

def test_optional_search_provider_local_and_fallback():
    """Verifies that LocalFallbackProvider and unconfigured providers never crash and return fallback results."""
    # 1. LocalFallbackProvider
    local_p = LocalFallbackProvider()
    res = local_p.search('site:linkedin.com/in "Digital Image Specialist"')
    assert res.is_fallback is True
    assert res.quota_exhausted is False
    assert len(res.items) == 1
    assert "https://www.google.com/search?q=" in res.items[0].url

    # 2. Unconfigured Google CSE Provider
    unconf_cse = GoogleCseProvider(api_key="", cx="")
    res_cse = unconf_cse.search("test query")
    assert res_cse.is_fallback is True
    assert "missing" in res_cse.error_message.lower()

    # 3. Factory defaults to local
    factory_p = get_search_provider("local")
    assert isinstance(factory_p, LocalFallbackProvider)

    factory_unknown = get_search_provider("non_existent_provider")
    assert isinstance(factory_unknown, LocalFallbackProvider)


def test_optional_search_provider_simulated_quota(monkeypatch):
    """Verifies that HTTP 429 quota exhaustion is handled cleanly without crashing."""
    from urllib.error import HTTPError

    def mock_urlopen(*args, **kwargs):
        raise HTTPError(url="https://serpapi.com", code=429, msg="Too Many Requests", hdrs={}, fp=None)

    monkeypatch.setattr("search_provider.urlopen", mock_urlopen)

    serp_p = SerpApiProvider(api_key="dummy_test_key")
    res = serp_p.search('site:linkedin.com/in "Digital Artist"')
    assert res.is_fallback is True
    assert res.quota_exhausted is True
    assert "quota exhausted" in res.error_message.lower()


# --- 11. Senior Illustrator Real-World JD Validation ---

def test_senior_illustrator_jd_extraction_and_query_diversity():
    """Validates extraction and queries for Senior Illustrator JD without bullet pollution."""
    jd_text = """Senior Illustrator

Location: Remote (US / Europe / Asia-Pacific)
Employment Type: Full-time
Experience: 5+ years of professional illustration experience

Role Overview:
We are seeking a talented Senior Illustrator to create visual assets and character designs.

Required Skills:
- Vector illustration and digital painting
- Character design and concept art
- Strong understanding of color theory, composition, and visual storytelling
- High proficiency in Adobe Illustrator and Photoshop

Preferred Skills & Nice to Have:
- Experience with 2D animation or Procreate / Figma
- Knowledge of 3D modeling fundamentals (Blender or Maya)
- Prior experience mentoring junior illustrators

Qualifications:
- 5+ years in a senior creative role
- Portfolio review is mandatory.
"""
    t_res = extract_job_title(jd_text)
    assert t_res.title == "Senior Illustrator"
    assert t_res.confidence_level == "High"
    # Ensure bullet requirements are NOT treated as alternative titles
    for alt in t_res.alternative_titles:
        assert "proficiency" not in alt.lower()
        assert "mentoring" not in alt.lower()
        assert "experience" not in alt.lower()

    reqs = extract_requirements(jd_text)
    assert reqs.job_title == "Senior Illustrator"
    assert "5+ years" in reqs.experience_level
    assert "Remote" in reqs.location
    assert "vector illustration" in reqs.required_skills
    assert "character design" in reqs.required_skills
    assert "photoshop" in reqs.tools_and_tech
    assert "illustrator" in reqs.tools_and_tech
    assert "procreate" in reqs.tools_and_tech
    assert reqs.portfolio_required is True

    # Check generated queries
    queries = generate_search_queries(reqs)
    assert 6 <= len(queries) <= 12
    for q in queries:
        assert "proficiency in adobe" not in q.query_text.lower()
        assert "mentoring junior" not in q.query_text.lower()


# --- 12. Synthetic Candidate Scoring Tiers & Evidence Consistency ---

def test_synthetic_candidate_scoring_tiers_and_unverified_criteria():
    """Verifies scoring across strong, moderate, weak, insufficient, and contradictory profiles."""
    reqs = JobRequirements(
        job_title="Senior Illustrator",
        required_skills=["vector illustration", "character design", "color theory"],
        tools_and_tech=["illustrator", "photoshop"],
        location="Remote",
        portfolio_required=True,
    )

    strong = {
        "name": "Alice Strong",
        "headline": "Senior Illustrator & Character Designer",
        "location": "Remote",
        "evidence_text": "Experienced Senior Illustrator with 8 years in vector illustration, character design, and color theory. Expert in Illustrator and Photoshop. Portfolio at behance.net/alicestrong",
    }
    moderate = {
        "name": "Bob Moderate",
        "headline": "Illustrator",
        "location": "Remote",
        "evidence_text": "Illustrator skilled in Photoshop and vector illustration.",
    }
    weak = {
        "name": "Charlie Weak",
        "headline": "Junior Graphic Designer",
        "location": "London, UK",
        "evidence_text": "Junior designer specializing in layout and typography.",
    }
    insufficient = {
        "name": "Dana Minimal",
        "headline": "Creative",
        "location": "Remote",
        "evidence_text": "Open to new creative roles.",
    }
    contradictory = {
        "name": "Evan Contradictory",
        "headline": "Traditional Oil Painter",
        "location": "Remote",
        "evidence_text": "I do not use Adobe Illustrator and have no experience in vector illustration. Pure traditional painting.",
    }

    eval_strong = evaluate_candidate(strong, reqs)
    eval_mod = evaluate_candidate(moderate, reqs)
    eval_weak = evaluate_candidate(weak, reqs)
    eval_insuff = evaluate_candidate(insufficient, reqs)
    eval_contra = evaluate_candidate(contradictory, reqs)

    # 1. Monotonic ordering: Strong > Moderate > Weak >= Insufficient > Contradictory
    assert eval_strong.total_score > eval_mod.total_score
    assert eval_mod.total_score > eval_weak.total_score
    assert eval_weak.total_score >= eval_insuff.total_score
    assert eval_insuff.total_score > eval_contra.total_score

    # 2. Unverified criteria in Bob Moderate: missing portfolio and missing character design are "Not found"
    statuses_mod = {c.requirement: c.status for c in eval_mod.criteria_matches}
    assert statuses_mod["character design"] == "Not found"
    assert statuses_mod["Portfolio / Work Samples"] == "Not found"
    # Not found has NO negative penalty
    assert eval_mod.contradictory_count == 0

    # 3. Explicit contradiction in Evan has penalty applied
    statuses_contra = {c.requirement: c.status for c in eval_contra.criteria_matches}
    assert statuses_contra["vector illustration"] == "Contradictory"
    assert statuses_contra["illustrator"] == "Contradictory"
    assert eval_contra.contradictory_count >= 1

    # 4. Proportional scaling when custom weights do not sum to 100
    custom_w_80 = ScoringWeights(core_skills=40, tools=40, role_alignment=0, location=0, portfolio=0)
    eval_scaled = evaluate_candidate(strong, reqs, weights=custom_w_80)
    # Alice matches 100% of core skills and tools, so scaled score should be 100
    assert eval_scaled.total_score == 100


# --- 12. Complete V0.1–V0.4 Security & Robustness Tests ---

def test_csv_formula_injection_sanitization():
    """Verifies that cells starting with '=', '+', '-', '@', '\t', '\r' are prefixed with single quote."""
    import pandas as pd

    # Individual cell sanitation
    assert sanitize_csv_cell("=CMD|' /C calc'!A0") == "'=CMD|' /C calc'!A0"
    assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert sanitize_csv_cell("-10+2") == "'-10+2"
    assert sanitize_csv_cell("+44 123456") == "'+44 123456"
    assert sanitize_csv_cell("\tTabPrefix") == "'\tTabPrefix"
    assert sanitize_csv_cell("\rReturnPrefix") == "'\rReturnPrefix"

    # Safe text and numeric cells
    assert sanitize_csv_cell("Jane Doe") == "Jane Doe"
    assert sanitize_csv_cell("3D Digital Artist") == "3D Digital Artist"
    assert sanitize_csv_cell(100) == 100
    assert sanitize_csv_cell(95.5) == 95.5
    assert sanitize_csv_cell(None) == ""

    # DataFrame sanitization
    df = pd.DataFrame([
        {"Name": "=MALICIOUS()", "Score": 90, "Headline": "Senior Artist"},
        {"Name": "@TEST", "Score": 85, "Headline": "-Dangerous"},
    ])
    clean_df = sanitize_dataframe_for_csv(df)
    assert clean_df.iloc[0]["Name"] == "'=MALICIOUS()"
    assert clean_df.iloc[0]["Score"] == 90
    assert clean_df.iloc[1]["Name"] == "'@TEST"
    assert clean_df.iloc[1]["Headline"] == "'-Dangerous"


def test_max_file_size_validation():
    """Verifies that documents larger than MAX_FILE_SIZE_BYTES (15MB) raise DocumentParsingError."""
    oversized_data = b"X" * (16 * 1024 * 1024)
    with pytest.raises(DocumentParsingError) as exc_info:
        parse_document(oversized_data, "oversized_document.txt")
    assert "exceeds maximum allowed size" in str(exc_info.value).lower()


def test_search_history_provider_and_status_tracking(tmp_path):
    """Verifies that search history logs provider, status, and query details reliably."""
    db_file = tmp_path / "test_sh.db"
    conn = init_db(db_file)
    job_id = add_job(conn, "3D Artist", "Job description")

    hid1 = add_search_history(
        conn,
        job_id,
        'site:linkedin.com/in "3D Artist"',
        strategy="Targeted Role",
        provider="Browser (Google X-Ray)",
        status="Opened in Browser",
    )
    assert hid1 > 0

    hid2 = add_search_history(
        conn,
        job_id,
        'site:artstation.com "3D Artist"',
        strategy="Portfolio",
        provider="SerpApi",
        status="Completed via API",
    )
    assert hid2 > 0

    history = get_search_history(conn, job_id)
    assert len(history) == 2
    # Verify latest search is returned first
    assert history[0]["provider"] == "SerpApi"
    assert history[0]["status"] == "Completed via API"
    assert history[1]["provider"] == "Browser (Google X-Ray)"
    assert history[1]["status"] == "Opened in Browser"
    conn.close()


def test_candidate_deduplication_null_url_and_evidence_merge(tmp_path):
    """Verifies deduplication without URL: merges evidence in same job, allows distinct records across jobs."""
    db_file = tmp_path / "test_dedup.db"
    conn = init_db(db_file)
    job1_id = add_job(conn, "Job 1", "JD 1")
    job2_id = add_job(conn, "Job 2", "JD 2")

    # 1. Add candidate Alex without URL to Job 1
    c1_data = {
        "name": "Alex Mercer",
        "profile_url": "",
        "headline": "3D Generalist",
        "evidence_text": "Experienced in Blender and ZBrush.",
        "notes": "Met at conference",
    }
    ok1, msg1, cid1 = add_or_update_candidate(conn, c1_data, job1_id)
    assert ok1 is True
    assert cid1 is not None

    # 2. Add same name without URL to Job 1 again -> should update existing record and merge evidence
    c1_update = {
        "name": "Alex Mercer",
        "profile_url": "",
        "evidence_text": "Also proficient in Substance Painter.",
        "notes": "Available from Nov 1",
    }
    ok2, msg2, cid2 = add_or_update_candidate(conn, c1_update, job1_id)
    assert ok2 is True
    assert cid2 == cid1
    assert "updated" in msg2.lower()

    # Verify merged evidence
    cand_row = conn.execute("SELECT * FROM candidates WHERE id = ?", (cid1,)).fetchone()
    assert "Blender" in cand_row["evidence_text"]
    assert "Substance Painter" in cand_row["evidence_text"]
    assert "Met at conference" in cand_row["notes"]
    assert "Available from Nov 1" in cand_row["notes"]

    # 3. Add a distinct candidate named Alex Mercer without URL to Job 2 -> creates distinct candidate
    c2_data = {
        "name": "Alex Mercer",
        "profile_url": "",
        "headline": "Senior Character Artist",
        "evidence_text": "Character sculpting expert.",
    }
    ok3, msg3, cid3 = add_or_update_candidate(conn, c2_data, job2_id)
    assert ok3 is True
    assert cid3 != cid1

    conn.close()


def test_education_and_mandatory_constraints_extraction_and_matching():
    """Verifies that explicit education and mandatory constraints are extracted and matched without hallucination."""
    jd_with_constraints = """Senior Python Developer
Locations: Bengaluru, India
Employment type: Full-time

Requirements:
- Bachelor's degree in Computer Science or equivalent
- Must have valid work authorization in India
- 5+ years of experience with Python and FastAPI
- Docker and PostgreSQL
"""
    reqs = extract_requirements(jd_with_constraints)
    assert any("bachelor" in e.lower() for e in reqs.education_or_certifications)
    assert any("work authorization" in c.lower() for c in reqs.mandatory_constraints)

    # Test candidate matching with satisfying evidence
    qualified_cand = {
        "name": "Priya Sharma",
        "headline": "Python Lead",
        "location": "Bengaluru, India",
        "evidence_text": "Bachelor's degree in Computer Science. Valid work authorization in India. 6 years Python and FastAPI experience.",
    }
    eval_qual = evaluate_candidate(qualified_cand, reqs)
    crit_dict = {c.requirement: c.status for c in eval_qual.criteria_matches}
    edu_match = next(c for c in eval_qual.criteria_matches if c.category == "Education / Certification")
    assert edu_match.status == "Matched"

    # Test candidate with missing education (should be 'Not found', not penalized)
    missing_edu_cand = {
        "name": "Rohan Verma",
        "headline": "Python Developer",
        "location": "Bengaluru, India",
        "evidence_text": "5 years Python and FastAPI experience. Valid work authorization in India.",
    }
    eval_missing = evaluate_candidate(missing_edu_cand, reqs)
    edu_match_missing = next(c for c in eval_missing.criteria_matches if c.category == "Education / Certification")
    assert edu_match_missing.status == "Not found"
    assert eval_missing.contradictory_count == 0


# --- 13. Business Analyst JD Extraction & Regression Tests ---

BUSINESS_ANALYST_JD_SAMPLE = """FUTUREJOBS
Business Analyst
Short-term contract · Remote · 16 weeks
ROLE
Business Analyst
POSITIONS
450
LOCATION
Global (India and USA preferred)
DURATION
16 weeks
START DATE
Immediate
RATE
$30/hour USD
AVAILABILITY
8 hours/day; 4 hours overlap with PST
EXPERIENCE
3 years and above
WORK SCHEDULE
5 days/week, weekends as required; 2 weekdays off

Country-Specific Guidelines
Preferred locations: India and the United States. The project is listed as global, but location eligibility and approval status must be checked before onboarding.
India: Listed as APPROVED in the provided country guidelines.
United States - state-level geo status (from the provided US Geo sheet):
Approved states: Alabama, Arizona, Colorado, Florida, Idaho, Iowa, Kentucky, Michigan, Minnesota, Mississippi, Missouri, Montana, New York, North Carolina, North Dakota, Oklahoma, Pennsylvania, South Carolina, South Dakota, Texas, Virginia, Wisconsin, Wyoming.
Approval needed: Alaska, Arkansas, Delaware, Georgia, Hawaii, Illinois, Indiana, Kansas, Louisiana, Maine, Maryland, Nebraska, Nevada, New Hampshire, New Mexico, Ohio, Oregon, Rhode Island, Tennessee, Utah, Washington, Washington DC, West Virginia, Puerto Rico*.
Exceptional approval needed: California, Connecticut, Massachusetts, New Jersey, Vermont.
Note: Puerto Rico is marked with an asterisk in the source sheet. Confirm the applicable interpretation before proceeding. Do not assume all US
locations are approved.

Role Overview
We are looking for a detail-oriented Business Analyst to support a project involving the evaluation of multiple chatbot responses. The role combines structured response evaluation with business analysis activities, including reviewing requirements, comparing chatbot outputs, documenting findings, and providing final assessments against defined criteria.

Project Snapshot
- Remote project lasting 16 weeks.
- Rate of $30/hour USD.
- 450 positions listed for this opportunity.

What You'll Do
- Gather, analyze, and document business requirements.
- Collaborate with stakeholders to understand business needs and objectives.
- Translate business requirements into clear functional specifications.
- Analyze workflows, processes, and data to identify gaps and improvement areas.
- Create reports, dashboards, process maps, and other documentation.
- Support project planning, testing, implementation, and user acceptance testing (UAT).
- Coordinate with technical and cross-functional teams to support successful delivery.
- Track project progress, risks, dependencies, and key performance indicators (KPIs).
- Compare multiple chatbot responses and provide structured assessments against defined criteria.

Requirements
- Bachelor's degree in Business Administration, Finance, Computer Science, or a related field.
- 3 years of experience as a Business Analyst or in a similar role.
- Strong analytical, problem-solving, and communication skills.
- Proficiency in Excel, SQL, Power BI, Tableau, or similar tools.
- Experience with requirements gathering and process-mapping techniques.
- Ability to work with cross-functional teams and manage multiple priorities.
- Strong attention to detail and documentation skills.
- Knowledge of Agile or Scrum methodologies is an advantage.
"""


def test_business_analyst_jd_actual_and_fixture_extraction():
    """Verifies that Business Analyst JD extracts correct title, legitimate skills, BI tools,
    clean locations, and zero false locations/alternative titles.
    """
    reqs = extract_requirements(BUSINESS_ANALYST_JD_SAMPLE)

    # 1. Job Title & Alternative Titles
    assert reqs.job_title == "Business Analyst"
    assert "Detail-oriented" not in " ".join(reqs.alternative_titles)
    assert reqs.alternative_titles == []

    # 2. Location (Never extracts 'are approved.')
    assert "Remote" in reqs.location
    assert "India" in reqs.location
    assert "United States" in reqs.location
    assert "are approved" not in reqs.location.lower()
    assert "approved" not in reqs.location.lower()

    # 3. Core Required Skills
    req_skills_lower = [s.lower() for s in reqs.required_skills]
    assert "requirements gathering" in req_skills_lower
    assert "process mapping" in req_skills_lower
    assert "functional specifications" in req_skills_lower
    assert "user acceptance testing" in req_skills_lower
    assert "stakeholder management" in req_skills_lower
    assert "gap analysis" in req_skills_lower

    # 4. Preferred Skills (distinguished via 'is an advantage')
    pref_skills_lower = [s.lower() for s in reqs.preferred_skills]
    assert "agile" in pref_skills_lower
    assert "scrum" in pref_skills_lower
    assert "agile" not in req_skills_lower

    # 5. Tools & Technologies
    tools_lower = [t.lower() for t in reqs.tools_and_tech]
    assert "excel" in tools_lower
    assert "sql" in tools_lower
    assert "power bi" in tools_lower
    assert "tableau" in tools_lower

    # 6. Inferred Domain Keywords (No administrative boilerplate)
    assert "approved" not in reqs.inferred_keywords
    assert "defined" not in reqs.inferred_keywords
    assert "responses" not in reqs.inferred_keywords
    assert "india" not in reqs.inferred_keywords
    assert "chatbot" in reqs.inferred_keywords


def test_false_location_prose_rejection():
    """Verifies that ordinary prose fragments such as 'are approved' or 'defined in the appendix'
    are never extracted as locations.
    """
    prose_snippet_1 = """Job Title: Operations Associate
Note: Confirm the applicable interpretation before proceeding. Do not assume all US locations are approved.
"""
    loc1 = extract_location(prose_snippet_1)
    assert "are approved" not in loc1.lower()
    assert "approved" not in loc1.lower()

    prose_snippet_2 = """Job Title: Data Entry Specialist
Locations were defined in the appendix and must be checked before proceeding.
"""
    loc2 = extract_location(prose_snippet_2)
    assert "defined" not in loc2.lower()
    assert "appendix" not in loc2.lower()

    # Valid geography block header
    geo_snippet = """Job Title: Business Analyst
Remote contract opportunity
GEOGRAPHY
India, Brazil, Colombia
"""
    loc3 = extract_location(geo_snippet)
    assert "Remote" in loc3
    assert "India" in loc3
    assert "Brazil" in loc3
    assert "Colombia" in loc3


def test_alternative_title_qualifier_stripping_and_deduplication():
    """Verifies that generic adjectives ('detail-oriented', 'creative') do not form alternative titles
    and titles identical to the primary title are discarded.
    """
    # 1. Generic adjective with same primary role title -> returns empty
    overview_text_1 = "We are looking for a detail-oriented Business Analyst to support a project."
    alts1 = extract_alternative_titles_from_overview(overview_text_1, primary_title="Business Analyst")
    assert alts1 == []
    assert "Detail-oriented Business Analyst" not in alts1

    # 2. Genuine alternative titles in creative JD -> returns unique distinct titles
    overview_text_2 = "We are seeking creative and detail-oriented digital imaging specialists, digital artists, and 3D artists who can create stylized assets."
    alts2 = extract_alternative_titles_from_overview(overview_text_2, primary_title="Digital Image Specialist")
    assert "Digital Artist" in alts2
    assert "3D Artist" in alts2
    assert "Digital Image Specialist" not in alts2
    assert "Detail-oriented" not in " ".join(alts2)

    # 3. Explicit alternative title section
    explicit_text = """Job Title: Business Systems Analyst
Alternative Titles: Systems Analyst, Functional Analyst
"""
    alts3 = extract_alternative_titles_from_overview(explicit_text, primary_title="Business Systems Analyst")
    assert "Systems Analyst" in alts3
    assert "Functional Analyst" in alts3


def test_business_analyst_search_queries_generation():
    """Verifies that 6+ diverse, high-relevance search queries are generated for Business Analyst
    without noise terms, false locations, or duplicate strategies.
    """
    reqs = extract_requirements(BUSINESS_ANALYST_JD_SAMPLE)
    queries = generate_search_queries(reqs)

    # Must generate 6-12 varied queries
    assert len(queries) >= 6

    # Verify query text content
    all_query_texts = [q.query_text for q in queries]
    strategies = [q.strategy for q in queries]

    title_strategies = {
        "High Precision",
        "Alternative Titles",
        "Location Focus",
        "Public Web",
        "Availability",
        "Broad Discovery",
        "Tool Synergy",
        "Preferred Skills",
    }
    for q in queries:
        if q.strategy in title_strategies:
            assert "Business Analyst" in q.query_text
        assert "are approved" not in q.query_text.lower()
        assert "detail-oriented" not in q.query_text.lower()
        assert "defined" not in q.query_text.lower()
        assert "responses" not in q.query_text.lower()

    # Check key diverse strategies (when alternative_titles is empty, Skill Synergy replaces Alternative Titles)
    assert "High Precision" in strategies
    assert "Skill Synergy" in strategies
    assert "Alternative Titles" not in strategies
    assert "Skill Centric" in strategies
    assert "Location Focus" in strategies
    assert "Public Web" in strategies
    assert "Availability" in strategies
    assert "Broad Discovery" in strategies

    # Verify that Alternative Titles strategy is generated when genuine alternative titles are provided
    queries_with_alts = generate_search_queries(reqs, user_extra_titles="Systems Analyst, Functional Analyst")
    assert "Alternative Titles" in [q.strategy for q in queries_with_alts]
    assert "Tool Synergy" in strategies
    assert "Preferred Skills" in strategies


# --- 14. Priority 1–5 Comprehensive Validation Tests ---

def test_security_audit_no_external_iframes_or_scripts():
    """Verifies that project Python codebase does not contain unexpected external scripts,
    dynamic iframe rendering, or references to easyshopsoffers/in_extension_register (outside audit advisory).
    """
    code_dir = Path(__file__).resolve().parent.parent
    py_files = [
        f for f in code_dir.glob("*.py")
        if f.name not in ("__init__.py",)
    ]
    assert len(py_files) >= 6

    for py_file in py_files:
        content = py_file.read_text(encoding="utf-8")
        # Ensure no dynamic st.components.v1.html iframe injections
        assert "components.html(" not in content, f"Disallowed iframe component found in {py_file.name}"
        assert "<iframe" not in content, f"Disallowed raw <iframe> tag found in {py_file.name}"

        # If easyshopsoffers appears, ensure it is only within an explicit security audit advisory warning string
        if "easyshopsoffers" in content.lower():
            assert py_file.name == "app.py", f"Unexpected reference to easyshopsoffers in {py_file.name}"
            assert "browser extension" in content or "injection artifact" in content


def test_competitive_data_scientist_jd_extraction_and_query_diversity():
    """Verifies complete, accurate extraction and search query generation for Competitive Data Scientist JD."""
    pdf_path = Path("C:/Users/Asus/Downloads/Competitive_Data_Scientist (2).pdf")
    if pdf_path.exists():
        raw_bytes = pdf_path.read_bytes()
        jd_text = parse_document(raw_bytes, "Competitive_Data_Scientist (2).pdf")
    else:
        # High-fidelity fixture matching actual PDF text
        jd_text = """FutureJobs.ai
COMPETITIVE DATA SCIENTIST
Role Type
Contractor
Location
Remote / Global
Pay
$60-$120/hour
Openings
50
Required Skills
- ML Engineering
- Data Science
- Mathematics
- Coding
About the Role
We're looking for data scientists, machine learning practitioners, and applied mathematics experts with competitive
Data Science experience, including platforms such as Kaggle, DrivenData, and similar competitions.
You'll draw on your competition experience, mathematical reasoning, and programming skills to create tasks that
require more than a plausible answer. Each task should have a reproducible environment, a verified reference
solution, and reliable checks for successful completion.
Scope of Work
1. Build reproducible environments, prepare relevant data and dependencies, and implement reference solutions.
2. Develop tests and evaluation criteria that reliably distinguish correct solutions from incomplete or flawed
approaches.
3. Run coding agents against tasks, investigate their failures, and refine the tasks based on observed behavior.
4. Identify implementation errors, flawed assumptions, data leakage, and other issues that affect correctness.
5. Document task requirements, solution reasoning, and verification steps clearly.
Required Qualifications
1. Demonstrated experience in data science, ML, quantitative modeling, or relevant research competitions. (Kaggle,
DrivenData, etc.)
2. Strong problem-solving ability and a clear understanding of the methods you use.
3. Practical programming ability sufficient to implement and verify your own solutions.
Relevant Competition Platforms
- Kaggle
- DrivenData
- Zindi
- AIcrowd
- Numerai
- DataSource.ai
- CodaLab/Codabench

FutureJobs.ai
Huge Pluses
1. Strong coding experience, particularly in Python, including testing, debugging, and working with unfamiliar code.
"""

    t_res = extract_job_title(jd_text)
    assert t_res.title == "Competitive Data Scientist"
    # Alternative titles must NOT infer "Data Scientists" from plural overview
    assert t_res.alternative_titles == []

    reqs = extract_requirements(jd_text)
    assert reqs.job_title == "Competitive Data Scientist"
    assert reqs.alternative_titles == []
    assert reqs.employment_type == "Contractor"
    assert "Remote" in reqs.location
    assert "Global" in reqs.location

    # Required core skills: exactly the 4 required competencies
    assert "ml engineering" in reqs.required_skills
    assert "data science" in reqs.required_skills
    assert "mathematics" in reqs.required_skills
    assert "coding" in reqs.required_skills
    assert "python" not in reqs.required_skills  # Python must NOT be promoted to required

    # Preferred skills (Huge Pluses)
    assert "python" in reqs.preferred_skills
    assert "testing" in reqs.preferred_skills
    assert "debugging" in reqs.preferred_skills
    assert "working with unfamiliar code" in reqs.preferred_skills

    # Tools: competition platforms
    assert "kaggle" in reqs.tools_and_tech
    assert "drivendata" in reqs.tools_and_tech
    assert "zindi" in reqs.tools_and_tech
    assert "aicrowd" in reqs.tools_and_tech
    assert "numerai" in reqs.tools_and_tech
    assert "datasource.ai" in reqs.tools_and_tech
    assert "codalab/codabench" in reqs.tools_and_tech

    # Inferred domain keywords must NOT include stopwords or skill/tool tokens
    assert "flawed" not in reqs.inferred_keywords
    assert "leakage" not in reqs.inferred_keywords
    assert "assumptions" not in reqs.inferred_keywords
    assert "competition" not in reqs.inferred_keywords
    assert "competitions" not in reqs.inferred_keywords
    assert "data" not in reqs.inferred_keywords
    assert "science" not in reqs.inferred_keywords
    assert "futurejobs" not in reqs.inferred_keywords
    assert "futurejobs.ai" not in reqs.inferred_keywords
    assert "platforms" not in reqs.inferred_keywords
    assert "implement" not in reqs.inferred_keywords
    assert "reproducible" not in reqs.inferred_keywords

    # Query generation check
    queries = generate_search_queries(reqs)
    assert 6 <= len(queries) <= 12
    strategies = [q.strategy for q in queries]
    assert "High Precision" in strategies
    # Truthful labeling: when alternative_titles is empty, Alternative Titles is NOT generated
    assert "Alternative Titles" not in strategies
    assert "Skill Synergy" in strategies
    assert "Competition Experience" in strategies
    assert "Work Arrangement" in strategies
    assert "Portfolio / Evidence" in strategies
    assert "Availability" in strategies

    # Verify High Precision includes all 4 core required skills
    hp_q = next(q for q in queries if q.strategy == "High Precision")
    assert "ml engineering" in hp_q.query_text.lower()
    assert "data science" in hp_q.query_text.lower()
    assert "mathematics" in hp_q.query_text.lower()
    assert "coding" in hp_q.query_text.lower()

    # Verify Competition Experience query targets the major competition platforms
    comp_q = next(q for q in queries if q.strategy == "Competition Experience")
    assert "kaggle" in comp_q.query_text.lower()
    assert "drivendata" in comp_q.query_text.lower()
    assert "zindi" in comp_q.query_text.lower()

    for q in queries:
        assert "flawed" not in q.query_text.lower()
        assert "futurejobs" not in q.query_text.lower()
        assert q.query_text.count("(") == q.query_text.count(")")
        assert q.query_text.count('"') % 2 == 0


def test_lucas_silva_evidence_coverage_and_sparse_confidence():
    """Verifies that Lucas Silva (53 words, Medium confidence) does not receive an unearned
    100/100 without evidence coverage accounting, and is flagged with coverage advisory.
    """
    reqs = JobRequirements(
        job_title="Digital Image Specialist",
        alternative_titles=["3D Artist"],
        required_skills=["3d modeling", "texturing", "material creation", "lighting", "shading"],
        tools_and_tech=["blender", "zbrush", "photoshop"],
        location="Remote",
        portfolio_required=False,
    )

    lucas_fixture = {
        "id": 2,
        "name": "Lucas Silva",
        "headline": "3D Modeler & Texture Artist | Blender & ZBrush",
        "location": "Sao Paulo, Brazil (Remote)",
        "evidence_text": (
            "3D Artist specializing in 3D modeling, texturing, and asset optimization.\n"
            "Daily proficiency in Blender, ZBrush, and Photoshop (Adobe Creative Suite).\n"
            "Skilled in low-poly modeling, UV mapping, lighting, shading, and rendering.\n"
            "Portfolio at behance.net/lucassilva3d"
        ),
    }

    eval_res = evaluate_candidate(lucas_fixture, reqs)

    # 1. Evidence coverage check: Lucas does not match 100% of all possible criteria (material creation missing)
    assert eval_res.confidence == "Medium"
    assert eval_res.word_count < 80
    assert 0 < eval_res.evidence_coverage_pct <= 100
    assert eval_res.verified_criteria_count > 0

    # 2. Confidence adjusted score: discounted because confidence is Medium (<80 words)
    assert eval_res.confidence_adjusted_score <= 85

    # 3. If total score is >= 80 and confidence is Medium, coverage advisory must be triggered
    if eval_res.total_score >= 80:
        assert eval_res.coverage_advisory != ""
        assert "Sparse evidence alert" in eval_res.coverage_advisory


def test_sparse_candidate_does_not_receive_unearned_full_points():
    """Verifies that an ultra-sparse candidate (e.g. 10 words) does not receive 100/100 points
    or unearned portfolio points when portfolio is not required.
    """
    reqs = JobRequirements(
        job_title="Digital Image Specialist",
        required_skills=["3d modeling", "texturing"],
        tools_and_tech=["blender", "photoshop"],
        location="Remote",
        portfolio_required=False,
    )

    sparse_cand = {
        "id": 99,
        "name": "Sparse Sam",
        "headline": "Artist",
        "location": "Remote",
        "evidence_text": "Experienced in Blender and 3D modeling.",
    }

    eval_res = evaluate_candidate(sparse_cand, reqs)
    assert eval_res.confidence == "Low"
    assert eval_res.total_score < 80
    assert eval_res.confidence_adjusted_score <= 50

    # Portfolio not required and not provided -> 0 points, Not found
    port_crit = next(c for c in eval_res.criteria_matches if c.category == "Portfolio")
    assert port_crit.status == "Not found"
    assert eval_res.score_breakdown["Portfolio"] == 0


def test_groq_extractor_missing_key_graceful_fallback(monkeypatch):
    """Verifies that extract_requirements_with_groq gracefully fails and advises fallback when key is absent."""
    from groq_extractor import extract_requirements_with_groq
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    ok, reqs, msg = extract_requirements_with_groq("Sample JD text", api_key="")
    assert ok is False
    assert reqs is None
    assert "GROQ_API_KEY" in msg or "local rule-based extractor" in msg


def test_groq_extractor_mocked_success(monkeypatch):
    """Verifies that extract_requirements_with_groq correctly parses valid JSON completion."""
    import json
    import urllib.request
    from groq_extractor import extract_requirements_with_groq

    mock_response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "job_title": "Competitive Data Scientist",
                        "alternative_titles": ["Kaggle Grandmaster", "ML Competitor"],
                        "required_skills": ["ml engineering", "data science", "mathematics", "coding"],
                        "preferred_skills": ["python", "testing", "debugging"],
                        "tools_and_tech": ["kaggle", "drivendata"],
                        "qualifications": ["Competitive ML experience"],
                        "education_or_certifications": [],
                        "experience_level": "3+ years",
                        "location": "Remote",
                        "employment_type": "Contractor",
                        "portfolio_required": False,
                        "mandatory_constraints": [],
                        "inferred_keywords": ["benchmarks", "solutions"],
                    })
                }
            }
        ]
    }

    class MockHTTPResponse:
        def read(self):
            return json.dumps(mock_response_payload).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: MockHTTPResponse())

    ok, reqs, msg = extract_requirements_with_groq("Sample JD", api_key="gsk_test_key_12345")
    assert ok is True
    assert reqs is not None
    assert reqs.job_title == "Competitive Data Scientist"
    assert reqs.employment_type == "Contractor"
    assert "ml engineering" in reqs.required_skills
    assert "kaggle" in reqs.tools_and_tech
    assert "Requirements successfully extracted using Groq AI" in msg
    assert "openai/gpt-oss-120b" in msg


def test_groq_extractor_mocked_rate_limit_and_timeout(monkeypatch):
    """Verifies that HTTP 429 and network timeouts return clear failure messages without crashing."""
    import urllib.error
    import urllib.request
    from groq_extractor import extract_requirements_with_groq

    # 1. Test HTTP 429 Rate Limit
    def raise_429(req, timeout):
        raise urllib.error.HTTPError("https://api.groq.com", 429, "Rate limit reached", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", raise_429)
    ok429, reqs429, msg429 = extract_requirements_with_groq("Sample JD", api_key="gsk_valid_key")
    assert ok429 is False
    assert reqs429 is None
    assert "429" in msg429 or "Rate Limit" in msg429

    # 2. Test URLError Timeout
    def raise_timeout(req, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", raise_timeout)
    ok_to, reqs_to, msg_to = extract_requirements_with_groq("Sample JD", api_key="gsk_valid_key")
    assert ok_to is False
    assert reqs_to is None
    assert "network error" in msg_to.lower() or "timed out" in msg_to.lower()


def test_groq_model_configuration_and_precedence(monkeypatch, tmp_path):
    """Verifies that get_groq_model prioritizes GROQ_MODEL env var over .env and defaults to openai/gpt-oss-120b."""
    from groq_extractor import DEFAULT_GROQ_MODEL, get_groq_model

    # 1. Default fallback
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    assert get_groq_model(search_dir=tmp_path) == DEFAULT_GROQ_MODEL
    assert DEFAULT_GROQ_MODEL == "openai/gpt-oss-120b"

    # 2. Configured in .env file
    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_MODEL=llama-3.1-8b-instant\n", encoding="utf-8")
    assert get_groq_model(search_dir=tmp_path) == "llama-3.1-8b-instant"

    # 3. Environment variable overrides .env file
    monkeypatch.setenv("GROQ_MODEL", "custom-groq-model-v1")
    assert get_groq_model(search_dir=tmp_path) == "custom-groq-model-v1"


def test_groq_extractor_http_404_model_not_found(monkeypatch):
    """Verifies that HTTP 404 (model not found / deprecated) produces a clear actionable error."""
    import io
    import json
    import urllib.error
    import urllib.request
    from groq_extractor import extract_requirements_with_groq

    err_payload = json.dumps({"error": {"message": "The model 'deprecated-model' does not exist."}}).encode("utf-8")

    def raise_404(req, timeout):
        fp = io.BytesIO(err_payload)
        raise urllib.error.HTTPError("https://api.groq.com", 404, "Not Found", {}, fp)

    monkeypatch.setattr(urllib.request, "urlopen", raise_404)
    ok, reqs, msg = extract_requirements_with_groq("Sample JD", api_key="gsk_test_key", model="deprecated-model")
    assert ok is False
    assert reqs is None
    assert "HTTP 404 Not Found" in msg
    assert "deprecated-model" in msg
    assert "local offline extractor" in msg


def test_groq_extractor_http_400_bad_request_unsupported_format(monkeypatch):
    """Verifies that HTTP 400 (unsupported JSON object format or invalid params) produces clear diagnostic message."""
    import io
    import json
    import urllib.error
    import urllib.request
    from groq_extractor import extract_requirements_with_groq

    err_payload = json.dumps({"error": {"message": "Model does not support response_format json_object"}}).encode("utf-8")

    def raise_400(req, timeout):
        fp = io.BytesIO(err_payload)
        raise urllib.error.HTTPError("https://api.groq.com", 400, "Bad Request", {}, fp)

    monkeypatch.setattr(urllib.request, "urlopen", raise_400)
    ok, reqs, msg = extract_requirements_with_groq("Sample JD", api_key="gsk_test_key", model="unsupported-model")
    assert ok is False
    assert reqs is None
    assert "HTTP 400 Bad Request" in msg
    assert "json_object" in msg or "structured JSON" in msg
    assert "local offline extractor" in msg


def test_groq_extractor_redacts_keys_on_unexpected_exception(monkeypatch):
    """Verifies that the API key is never included in error messages even if an exception string contains it."""
    import urllib.request
    from groq_extractor import extract_requirements_with_groq

    test_secret_key = "gsk_super_secret_private_token_xyz999"

    def raise_leaky_exc(req, timeout):
        raise RuntimeError(f"Connection failed to backend with token {test_secret_key} during handshake")

    monkeypatch.setattr(urllib.request, "urlopen", raise_leaky_exc)
    ok, reqs, msg = extract_requirements_with_groq("Sample JD", api_key=test_secret_key)
    assert ok is False
    assert reqs is None
    assert test_secret_key not in msg
    assert "[REDACTED]" in msg


def test_groq_live_smoke_test_when_missing_key(monkeypatch):
    """Verifies that run_groq_live_smoke_test returns CONFIG_MISSING without making any network call when key is absent."""
    from groq_extractor import run_groq_live_smoke_test
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    res = run_groq_live_smoke_test(api_key="")
    assert res["success"] is False
    assert res["status_category"] == "CONFIG_MISSING"
    assert res["status_code"] is None
    assert res["validated_schema"] is False
    assert "GROQ_API_KEY is not set" in res["message"]


def test_groq_live_smoke_test_mocked_success(monkeypatch):
    """Verifies that run_groq_live_smoke_test succeeds and verifies schema with valid mocked 200 response."""
    import json
    import urllib.request
    from groq_extractor import run_groq_live_smoke_test

    mock_response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "job_title": "Software Engineer",
                        "alternative_titles": ["Backend Engineer"],
                        "required_skills": ["Python", "SQL"],
                        "preferred_skills": ["FastAPI"],
                        "tools_and_tech": ["PostgreSQL"],
                        "qualifications": ["3+ years"],
                        "education_or_certifications": [],
                        "experience_level": "3+ years",
                        "location": "Remote",
                        "employment_type": "Full-time",
                        "portfolio_required": False,
                        "mandatory_constraints": [],
                        "inferred_keywords": ["software", "engineering"],
                    })
                }
            }
        ]
    }

    class MockHTTPResponse:
        def read(self):
            return json.dumps(mock_response_payload).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: MockHTTPResponse())

    res = run_groq_live_smoke_test(api_key="gsk_test_key_abc", model="openai/gpt-oss-120b")
    assert res["success"] is True
    assert res["status_category"] == "SUCCESS_200"
    assert res["status_code"] == 200
    assert res["validated_schema"] is True
    assert res["extracted_summary"]["job_title"] == "Software Engineer"
    assert "Python" in res["extracted_summary"]["required_skills"]


import pytest
import os

@pytest.mark.skipif(not os.environ.get("RUN_LIVE_GROQ_TEST"), reason="Live Groq tests skipped by default. Set RUN_LIVE_GROQ_TEST=1 and GROQ_API_KEY to run.")
def test_groq_optional_live_api_smoke_test():
    """Optional live integration smoke test that executes against the real Groq API ONLY when explicitly enabled."""
    from groq_extractor import get_groq_api_key, get_groq_model, run_groq_live_smoke_test
    key = get_groq_api_key()
    assert key, "RUN_LIVE_GROQ_TEST was enabled but no GROQ_API_KEY was provided in env or .env."
    model = get_groq_model()
    res = run_groq_live_smoke_test(api_key=key, model=model)
    assert res["success"] is True, f"Live Groq test failed: {res['message']} (Category: {res['status_category']})"
    assert res["status_category"] == "SUCCESS_200"


def test_dotenv_explicit_project_dir_loading(tmp_path, monkeypatch):
    """Verifies that load_project_env loads .env explicitly from the specified path using python-dotenv."""
    from groq_extractor import load_project_env

    # 1. Non-existent path returns False safely
    assert load_project_env(tmp_path / ".non_existent_env") is False

    # 2. Valid .env file loaded
    fake_env = tmp_path / ".env"
    fake_env.write_text("GROQ_API_KEY=gsk_test_from_dot_env_12345\nGROQ_MODEL=openai/gpt-oss-120b\n", encoding="utf-8")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    loaded = load_project_env(fake_env, override=True)
    assert loaded is True
    assert os.getenv("GROQ_API_KEY") == "gsk_test_from_dot_env_12345"
    assert os.getenv("GROQ_MODEL") == "openai/gpt-oss-120b"


def test_groq_api_key_resolution_precedence(monkeypatch):
    """Verifies API key precedence:
    1. Explicit session override takes top priority.
    2. Environment variable GROQ_API_KEY is used as default.
    3. Missing / empty returns None.
    """
    from groq_extractor import resolve_groq_api_key

    # Monkeypatch load_project_env to avoid reading actual disk .env during precedence test
    monkeypatch.setattr("groq_extractor.load_project_env", lambda *a, **kw: False)

    # Case 1: Session override present -> overrides environment variable
    monkeypatch.setenv("GROQ_API_KEY", "gsk_env_key_default")
    assert resolve_groq_api_key(override_key="gsk_session_override_key") == "gsk_session_override_key"

    # Case 2: Session override empty/whitespace/None -> defaults to environment variable
    assert resolve_groq_api_key(override_key="") == "gsk_env_key_default"
    assert resolve_groq_api_key(override_key="   ") == "gsk_env_key_default"
    assert resolve_groq_api_key(override_key=None) == "gsk_env_key_default"

    # Case 3: No session override and no env variable -> returns None
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert resolve_groq_api_key(override_key=None) is None
    assert resolve_groq_api_key(override_key="") is None


def test_groq_missing_key_clear_message(monkeypatch):
    """Verifies that missing API key produces a clear message and local offline fallback without exposing secrets."""
    from groq_extractor import extract_requirements_with_groq, resolve_groq_api_key, run_groq_live_smoke_test

    monkeypatch.setattr("groq_extractor.load_project_env", lambda *a, **kw: False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert resolve_groq_api_key() is None

    # Extraction with missing key
    ok, reqs, msg = extract_requirements_with_groq("Role: Senior Engineer", api_key="")
    assert ok is False
    assert reqs is None
    assert "Groq API key not found" in msg
    assert "GROQ_API_KEY" in msg
    assert "Local rule-based extraction remains ready" in msg

    # Smoke test with missing key
    smoke = run_groq_live_smoke_test(api_key="")
    assert smoke["success"] is False
    assert smoke["status_category"] == "CONFIG_MISSING"
    assert "GROQ_API_KEY is not set" in smoke["message"]


def test_groq_connection_smoke_test_without_ui_entered_key(monkeypatch):
    """Verifies that Test Groq Connection succeeds using GROQ_API_KEY from environment without requiring UI input."""
    import io
    import json
    import urllib.request
    from groq_extractor import run_groq_live_smoke_test

    monkeypatch.setenv("GROQ_API_KEY", "gsk_mock_env_key_auto")

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "job_title": "Software Engineer",
                        "alternative_titles": ["Developer"],
                        "required_skills": ["Python", "SQL"],
                        "preferred_skills": ["Docker"],
                        "tools_and_tech": ["Git"],
                        "qualifications": ["3+ years experience"],
                        "education_or_certifications": [],
                        "experience_level": "3+ years",
                        "location": "Remote",
                        "employment_type": "Full-time",
                        "portfolio_required": False
                    })
                }
            }
        ]
    }

    class MockHTTPResponse:
        def read(self):
            return json.dumps(mock_response).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: MockHTTPResponse())

    # User enters nothing in the UI (api_key=None or api_key="")
    result_none = run_groq_live_smoke_test(api_key=None)
    assert result_none["success"] is True
    assert result_none["status_category"] == "SUCCESS_200"
    assert result_none["status_code"] == 200
    assert result_none["validated_schema"] is True

    result_empty = run_groq_live_smoke_test(api_key="")
    assert result_empty["success"] is True
    assert result_empty["status_category"] == "SUCCESS_200"


def test_no_api_key_prefill_in_app_ui():
    """Security audit: verifies that app.py never pre-fills or displays API keys in visible text fields."""
    app_py_path = Path(__file__).resolve().parent.parent / "app.py"
    content = app_py_path.read_text(encoding="utf-8")

    # Verify session override text input configuration
    assert 'key="groq_session_key_override"' in content
    assert 'type="password"' in content
    assert 'value=""' in content
    assert "resolve_groq_api_key" in content
    # Ensure raw API key is never passed to value= parameter
    assert 'value=detected_key' not in content
    assert 'value=groq_key_val' not in content


# --- 13. V0.5 Strict Zero-Budget & UI/UX Redesign Tests ---

def test_strict_zero_budget_policy():
    """Verifies that default provider is zero cost and paid endpoints are rejected."""
    from search_provider import GitHubSearchProvider, LocalFallbackProvider, get_search_provider

    # Default provider is LocalFallbackProvider
    default_p = get_search_provider()
    assert isinstance(default_p, LocalFallbackProvider)
    assert "Browser Link Mode" in default_p.name

    # GitHub provider is zero cost
    gh_p = get_search_provider("github")
    assert isinstance(gh_p, GitHubSearchProvider)
    assert "Zero Cost" in gh_p.name


def test_github_search_provider_candidate_parsing(monkeypatch):
    """Verifies that GitHubSearchProvider searches and parses public profiles without guessing contacts."""
    import io
    import json
    import urllib.request
    from search_provider import GitHubSearchProvider

    search_payload = {
        "total_count": 1,
        "items": [{"login": "dev_alex", "html_url": "https://github.com/dev_alex"}]
    }
    user_payload = {
        "login": "dev_alex",
        "name": "Alex Mercer",
        "html_url": "https://github.com/dev_alex",
        "bio": "Senior Python & ML Engineer",
        "company": "OpenSource Lab",
        "location": "Berlin, Germany",
        "blog": "https://alexmercer.dev",
        "email": "alex.public@example.com",
        "public_repos": 42,
        "followers": 150
    }

    class MockResp:
        def __init__(self, data, remaining="50"):
            self.data = data
            self.headers = {"X-RateLimit-Remaining": remaining, "X-RateLimit-Reset": "1793170000"}
        def read(self):
            return json.dumps(self.data).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "search/users" in url:
            return MockResp(search_payload)
        elif "users/dev_alex" in url:
            return MockResp(user_payload)
        return MockResp({})

    monkeypatch.setattr("search_provider.urlopen", mock_urlopen)

    provider = GitHubSearchProvider()
    res = provider.search_candidates("python machine learning", location="Berlin", num_results=5)

    assert res.rate_limited is False
    assert len(res.candidates) == 1
    c = res.candidates[0]
    assert c["name"] == "Alex Mercer"
    assert c["headline"] == "Senior Python & ML Engineer at OpenSource Lab"
    assert c["email"] == "alex.public@example.com"
    assert c["contact_status"] == "Publicly published on GitHub"
    assert "Public GitHub Profile" in c["contact_provenance"]
    assert c["phone"] == ""  # Never fabricated


def test_github_missing_contact_not_found(monkeypatch):
    """Verifies that when a GitHub user does not publish an email, it is left blank and labeled 'Not found'."""
    import json
    import urllib.request
    from search_provider import GitHubSearchProvider

    search_payload = {
        "total_count": 1,
        "items": [{"login": "silent_coder", "html_url": "https://github.com/silent_coder"}]
    }
    user_payload = {
        "login": "silent_coder",
        "name": "Silent Coder",
        "html_url": "https://github.com/silent_coder",
        "bio": "Systems programmer",
        "company": None,
        "location": "Remote",
        "blog": None,
        "email": None,  # No public email
        "public_repos": 10,
        "followers": 5
    }

    class MockResp:
        def __init__(self, data):
            self.data = data
            self.headers = {"X-RateLimit-Remaining": "45", "X-RateLimit-Reset": "1793170000"}
        def read(self):
            return json.dumps(self.data).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "search/users" in url:
            return MockResp(search_payload)
        return MockResp(user_payload)

    monkeypatch.setattr("search_provider.urlopen", mock_urlopen)

    provider = GitHubSearchProvider()
    res = provider.search_candidates("systems rust")

    assert len(res.candidates) == 1
    c = res.candidates[0]
    assert c["email"] == ""
    assert c["contact_status"] == "Not found"
    assert "Checked" in c["contact_provenance"]
    assert c["phone"] == ""  # Never guessed


def test_github_rate_limit_stops_safely(monkeypatch):
    """Verifies that an HTTP 403 / 429 stops immediately without looping or crashing."""
    import io
    import urllib.error
    import urllib.request
    from search_provider import GitHubSearchProvider

    def raise_403(req, timeout=10):
        fp = io.BytesIO(b'{"message": "API rate limit exceeded"}')
        headers = {"X-RateLimit-Reset": "1793170000"}
        raise urllib.error.HTTPError("https://api.github.com/search/users", 403, "Forbidden", headers, fp)

    monkeypatch.setattr("search_provider.urlopen", raise_403)

    provider = GitHubSearchProvider()
    res = provider.search_candidates("python")

    assert res.rate_limited is True
    assert "rate limit reached" in res.message.lower()
    assert len(res.candidates) == 0


def test_search_queries_generate_google_and_bing_links():
    """Verifies that SearchQuery instances generate both Google and Bing X-Ray links."""
    from keyword_extractor import JobRequirements
    from query_generator import generate_search_queries

    reqs = JobRequirements(
        job_title="Data Scientist",
        required_skills=["Python", "Machine Learning"],
        location="London",
    )
    queries = generate_search_queries(reqs)

    assert len(queries) >= 6
    for q in queries:
        assert q.google_url.startswith("https://www.google.com/search?q=")
        assert q.bing_url.startswith("https://www.bing.com/search?q=")
        assert "Data Scientist" in q.query_text or "Python" in q.query_text


def test_database_contact_columns_and_shortlist_removal(tmp_path):
    """Verifies candidate contact columns persistence and shortlist removal without record deletion."""
    from db import add_job, add_or_update_candidate, get_candidate, get_dashboard_metrics, init_db, list_shortlisted_candidates, remove_from_shortlist

    test_db = tmp_path / "test_contacts.db"
    conn = init_db(test_db)

    jid = add_job(conn, "Frontend Engineer", "React, TypeScript")

    cand_data = {
        "name": "Sarah Connor",
        "profile_url": "https://github.com/sconnor",
        "github_url": "https://github.com/sconnor",
        "portfolio_url": "https://sconnor.tech",
        "headline": "Lead UI Developer",
        "company": "Cyberdyne Systems",
        "location": "Los Angeles, CA",
        "email": "sarah@cyberdyne.org",
        "phone": "+1 555-0199",
        "contact_provenance": "Candidate submitted CV [2026-10-28 10:00]",
        "contact_status": "Publicly published",
        "evidence_text": "Expert in React, TypeScript, Redux, and modern web applications.",
        "notes": "Top tier candidate",
        "status": "Shortlisted",
    }

    ok, msg, cid = add_or_update_candidate(conn, cand_data, job_id=jid)
    assert ok is True
    assert cid is not None

    cand = get_candidate(conn, cid)
    assert cand["name"] == "Sarah Connor"
    assert cand["email"] == "sarah@cyberdyne.org"
    assert cand["phone"] == "+1 555-0199"
    assert cand["company"] == "Cyberdyne Systems"
    assert cand["github_url"] == "https://github.com/sconnor"
    assert cand["contact_status"] == "Publicly published"
    assert cand["status"] == "Shortlisted"

    # Shortlist retrieval
    shortlisted = list_shortlisted_candidates(conn, job_id=jid)
    assert len(shortlisted) == 1
    assert shortlisted[0]["id"] == cid

    # Remove from shortlist
    removed = remove_from_shortlist(conn, cid)
    assert removed is True

    # Record MUST still exist, but status is now 'Under Review'
    cand_after = get_candidate(conn, cid)
    assert cand_after is not None
    assert cand_after["status"] == "Under Review"

    # Shortlist is now empty
    assert len(list_shortlisted_candidates(conn, job_id=jid)) == 0

    # Dashboard metrics
    metrics = get_dashboard_metrics(conn)
    assert metrics["total_jobs"] == 1
    assert metrics["total_candidates"] == 1
    assert metrics["needing_review"] == 1
    assert metrics["shortlisted"] == 0

    conn.close()


def test_ui_navigation_structure():
    """Verifies that app.py defines the 7 persistent navigation sections required by the redesign."""
    app_py_path = Path(__file__).resolve().parent.parent / "app.py"
    content = app_py_path.read_text(encoding="utf-8")

    expected_sections = [
        "Overview",
        "JD Analyzer",
        "Find Candidates",
        "Candidates",
        "Shortlist",
        "Saved Jobs & Data",
        "Settings",
    ]
    for section in expected_sections:
        assert f'"{section}"' in content, f"Navigation section '{section}' missing from app.py"


def test_streamlit_text_area_min_height():
    """Regression test: verifies that all st.text_area() height arguments are >= 68 pixels to satisfy Streamlit requirements."""
    import re
    app_py_path = Path(__file__).resolve().parent.parent / "app.py"
    content = app_py_path.read_text(encoding="utf-8")
    
    for i, line in enumerate(content.splitlines(), 1):
        if "st.text_area" in line or "text_area(" in line:
            m = re.search(r"height\s*=\s*(\d+)", line)
            if m:
                h = int(m.group(1))
                assert h >= 68, f"Invalid text_area height {h}px on line {i}: must be at least 68 pixels."









