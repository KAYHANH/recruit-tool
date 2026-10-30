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


## Bulk CV Referral Outreach (new module)

The **CV Referral Outreach** sidebar module adds local PDF/DOCX parsing, email extraction, normalized-email deduplication, skill-based matching against manually verified Turing/Mercor/micro1 referral opportunities, and Gmail draft creation. It never sends email.

### Install dependencies

```powershell
python -m pip install -r requirements.txt
cd frontend
npm install
cd ..
```

### Gmail OAuth setup (one-time)

1. In Google Cloud Console, create/select a project and enable the Gmail API.
2. Configure the OAuth consent screen. Add your Google account as a test user if the app is in Testing mode.
3. Create an OAuth Client ID (Web application) and add this exact authorized redirect URI: `http://127.0.0.1:8000/api/bulk-outreach/gmail/callback`.
4. Download the client JSON and save it locally as `credentials.json` in this folder (never commit it).
5. Start Candidate Finder, open **CV Referral Outreach**, click **Connect Gmail**, and complete Google's authorization.
6. The app stores a local refresh token in `.gmail_token.json`. Keep this file private and backed up securely.

Optional environment variables: `GOOGLE_OAUTH_CLIENT_SECRETS`, `GMAIL_TOKEN_PATH`, `GOOGLE_OAUTH_REDIRECT_URI`, and `CANDIDATE_SOURCING_DB_PATH`.

### Use

1. Select up to 1,000 PDF/DOCX CV files in one batch. Files are processed locally; individual files are limited to 15 MB.
2. Confirm you have an appropriate basis to contact the candidates about relevant opportunities. This confirmation is an operator attestation, not proof that consent exists.
3. Add each opportunity manually with its role requirements and your own HTTPS referral URL. Verify the URL and platform terms before saving.
4. Review candidate-match evidence. Scanned PDFs need OCR and are reported as errors rather than silently treated as empty CVs.
5. Connect Gmail and create drafts one candidate/opportunity at a time. Review and send manually in Gmail.

### Important limitations

- Email extraction and name/skill parsing are heuristic; inspect the records before outreach.
- Matching is a simple keyword-overlap score, not an employer/platform screening decision.
- The first implementation stores the first valid email found per CV; additional email addresses are not yet offered for selection.
- Gmail compose scope is used for draft creation; the application has no send-email endpoint.
- No referral links, jobs, compensation or payout promises are supplied automatically.
- Contact candidates only where you have an appropriate legal basis and honor opt-outs. A CV containing an email address does not itself establish permission to send marketing messages.
