# Candidate Finder — Zero-Budget Personal Recruitment Platform

A modern, local-first web application for recruitment candidate sourcing, Job Description analysis, Boolean/Google/Bing X-Ray query generation, official public GitHub API candidate discovery, deterministic evidence-based heuristic ranking, and formula-injection sanitized CSV shortlists.

**Strict ₹0.00 Budget Guarantee:**
- No paid API keys, paid credits, paid scrapers, or billable third-party services.
- 100% local database storage in SQLite (`candidate_sourcing.db`).
- Candidate personal data and notes never leave your computer.

---

## Architecture Overview

Candidate Finder has migrated from a prototype UI to a high-performance, modern web application:

- **Frontend:** React 19 + Vite 8 + TypeScript + Tailwind CSS
  - 7 Dedicated Views:
    1. **Overview Dashboard:** Live metrics (Active Jobs, Candidates, Under Review, Shortlisted), recent jobs, and sourcing activities.
    2. **JD Analyzer:** 4-step guided intake (PDF/DOCX/TXT/MD upload or text paste, Local/Groq engine selection, tag-based requirements editor, and SQLite persistence).
    3. **Find Candidates:** Official public GitHub API candidate discovery (zero-cost, rate-limit aware) + Browser Boolean/X-Ray query links (Google and Bing) + Quick profile intake form.
    4. **Candidate Directory & Matcher:** Deterministic, evidence-based candidate scoring, status management, and candidate inspection drawer.
    5. **Shortlist Pipeline:** Shortlisted candidates table, in-place recruiter notes editor, non-destructive shortlist removal, and formula-injection sanitized CSV export.
    6. **Data & Backups:** Job editing/deletion and transactional SQLite backup creation and restoration.
    7. **Settings & Health:** Zero-budget policy enforcement, Local Extractor details, Groq test, and GitHub rate limit checker.
- **Backend:** Python FastAPI (`api.py`)
  - RESTful API with Pydantic v2 validation and CORS configuration.
  - Endpoints for jobs, candidate matching, Boolean queries, document parsing, GitHub sourcing, and database backups.
- **Database:** Local SQLite database (`candidate_sourcing.db`) with automatic migrations and transactional backup API.

---

## Requirements

- **Windows 10 / 11**
- **Python 3.10+** (Python 3.11 tested)
- **Node.js 18+** (Node.js 22 tested)
- No cloud account, paid subscription, or credit card required.

---

## How to Run

### Quick Start (Windows)
Double-click `run_app.bat` in the project root.

The launcher script will:
1. Start the FastAPI backend on `http://127.0.0.1:8000`
2. Start the React Vite frontend on `http://localhost:5173`
3. Automatically open your web browser to `http://localhost:5173`

### Manual Start (PowerShell)

**Terminal 1 — FastAPI Backend:**
```powershell
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```
API Documentation (Swagger UI) is available at: `http://127.0.0.1:8000/docs`

**Terminal 2 — React Vite Frontend:**
```powershell
cd frontend
npm run dev
```
Frontend UI is available at: `http://localhost:5173`

---

## Automated Test Suites

The project features comprehensive automated tests running 100% offline with zero network dependencies:

```powershell
# Run all tests (Core business logic + FastAPI endpoints)
python -m pytest

# Run FastAPI endpoint tests
python -m pytest tests/test_api.py -v

# Run extraction & matcher unit tests
python -m pytest tests/test_candidate_finder.py -v
```

---

## Optional Groq AI Configuration

Candidate Finder defaults to the 100% offline, local rule-based extractor. If you wish to enable the optional Groq AI extractor on its **Free plan**:
1. Copy `.env.example` to `.env`.
2. Configure `GROQ_API_KEY=gsk_...` and `GROQ_MODEL=openai/gpt-oss-120b` in `.env`.
3. Candidate Finder loads `.env` automatically via `python-dotenv`.
4. Only the Job Description text is sent to Groq; candidate profiles, CVs, and database records are **never** transmitted externally.
