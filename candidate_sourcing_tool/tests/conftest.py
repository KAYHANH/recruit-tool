from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
import pytest

from db import init_db

# Create an isolated temporary test database directory for the entire pytest session
_temp_dir = tempfile.mkdtemp(prefix="candidate_sourcing_test_")
_test_db_path = Path(_temp_dir) / "test_candidate_sourcing.db"

# Set environment variable BEFORE any test module imports api.py
os.environ["CANDIDATE_SOURCING_DB_PATH"] = str(_test_db_path)


@pytest.fixture(scope="session", autouse=True)
def isolated_test_db():
    """Initializes a fresh, isolated temporary database for the test session
    and guarantees that automated tests NEVER mutate production candidate_sourcing.db.
    """
    conn = init_db(_test_db_path)
    conn.execute("""
        INSERT OR IGNORE INTO jobs (id, title, jd_text, location, extracted_data, created_at)
        VALUES (1, 'Digital Image Specialist', 'Stylized 3D asset creation and digital imaging. Blender, ZBrush, Adobe Creative Suite.', 'Bengaluru, India (Remote)', '{}', '2026-10-26T10:00:00')
    """)
    conn.execute("""
        INSERT OR IGNORE INTO jobs (id, title, jd_text, location, extracted_data, created_at)
        VALUES (2, 'Backend Engineer', 'Senior Python Backend Engineer. FastAPI, PostgreSQL, Docker.', 'Remote', '{}', '2026-10-26T11:00:00')
    """)
    conn.execute("""
        INSERT OR IGNORE INTO candidates (id, name, headline, location, experience, evidence_text, profile_url, source, status, created_at)
        VALUES (1, 'Maya Patel', 'Senior 3D Artist | Digital Image Specialist', 'Bengaluru, India (Remote)', '5+ years experience in stylized 3D art & digital imaging. Blender, ZBrush.', 'Stylized 3D art portfolio and assets.', 'https://linkedin.com/in/mayapatel-3d', 'Google X-Ray', 'Sourced', '2026-10-26T12:00:00')
    """)
    conn.execute("""
        INSERT OR IGNORE INTO candidates (id, name, headline, location, experience, evidence_text, profile_url, source, status, created_at)
        VALUES (2, 'Lucas Silva', 'Data Scientist & Python Modeler', 'Sao Paulo, Brazil', 'Data science and predictive modeling in Python.', 'Data science and predictive modeling in Python.', 'https://linkedin.com/in/lucassilva-art', 'Local DB', 'Sourced', '2026-10-26T13:00:00')
    """)
    conn.execute("""
        INSERT OR IGNORE INTO job_candidates (job_id, candidate_id, match_score, status, notes, updated_at)
        VALUES (1, 1, 95, 'Sourced', 'Initial match', '2026-10-26T14:00:00')
    """)
    conn.execute("""
        INSERT OR IGNORE INTO job_candidates (job_id, candidate_id, match_score, status, notes, updated_at)
        VALUES (1, 2, 80, 'Sourced', 'Initial match', '2026-10-26T14:00:00')
    """)
    conn.commit()
    from db import seed_candidate_experiences_if_empty
    seed_candidate_experiences_if_empty(conn)
    conn.close()

    try:
        import api
        api.set_db_path(_test_db_path)
    except Exception:
        pass

    yield _test_db_path

    try:
        shutil.rmtree(_temp_dir, ignore_errors=True)
    except Exception:
        pass
