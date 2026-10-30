# Candidate Finder — Zero-Budget Personal Recruitment Platform

A modern, local-first web application for recruitment candidate sourcing, Job Description analysis, Boolean/Google/Bing X-Ray query generation, official public GitHub API candidate discovery, deterministic evidence-based heuristic ranking, formula-injection sanitized CSV shortlists, and a high-scale CV-to-Referral Outreach Pipeline.

**Strict ₹0.00 Budget Guarantee:**
- No paid API keys, paid credits, paid scrapers, or billable third-party services.
- 100% local database storage in SQLite (`candidate_sourcing.db`).
- Candidate personal data, CVs, and notes never leave your computer.
- Draft-only Gmail integration (`gmail.compose` scope); emails are never sent automatically.

---

## Architecture Overview

Candidate Finder has evolved into a high-performance, modern recruitment and referral management suite:

- **Frontend:** React 19 + Vite 8 + TypeScript + Tailwind CSS
  - 8 Dedicated Application Views:
    1. **Overview Dashboard:** Live metrics (Active Jobs, Candidates, Under Review, Shortlisted), recent jobs, and sourcing activities.
    2. **JD Analyzer:** 4-step guided intake (PDF/DOCX/TXT/MD upload or text paste, Local/Groq engine selection, tag-based requirements editor, and SQLite persistence).
    3. **Find Candidates:** Official public GitHub API candidate discovery (zero-cost, rate-limit aware) + Browser Boolean/X-Ray query links (Google and Bing) + Quick profile intake form.
    4. **Candidate Directory & Matcher:** Deterministic, evidence-based candidate scoring, status management, and candidate inspection drawer.
    5. **Shortlist Pipeline:** Shortlisted candidates table, in-place recruiter notes editor, non-destructive shortlist removal, and formula-injection sanitized CSV export.
    6. **CV Outreach & Referral Engine:** Complete local CV-to-referral outreach system supporting 500–1,000 CV batches:
       - **Tab 1: Overview** — Metrics for indexed CVs, opportunities, candidate matches, and prepared drafts.
       - **Tab 2: Upload CVs** — Windows folder path scanner and drag-and-drop ZIP archive importer with DoS/ZIP-bomb protection.
       - **Tab 3: CV Library** — Searchable candidate directory with contact permission indicators, ambiguity review flags, and one-click opt-out suppression.
       - **Tab 4: Managed Opportunities** — Verified referral opportunities (Turing, Mercor, micro1, etc.) with recruiter audit verification workflow.
       - **Tab 5: Match Review** — 100-point deterministic match scoring (Skills 40, Experience 25, Language 15, Location 10, Other/Verification 10) with contradiction detection.
       - **Tab 6: Gmail Drafts** — Draft-only Google OAuth integration with live draft updates, simulated mock mode, and manual-send tracking.
       - **Tab 7: Import History** — Async batch job monitor with real-time progress, Pause/Resume, Cancel, and file-level error inspection.
    7. **Data & Backups:** Job editing/deletion and transactional SQLite backup creation and restoration.
    8. **Settings & Health:** Zero-budget policy enforcement, Local Extractor details, Groq test, and GitHub rate limit checker.

- **Backend:** Python FastAPI (`candidate_sourcing_tool/api.py`)
  - RESTful API with Pydantic v2 validation and CORS configuration.
  - Endpoints for jobs, candidate matching, Boolean queries, document parsing, GitHub sourcing, CV batch imports, referral matching, and Gmail OAuth drafts.
- **Database:** Local SQLite database (`candidate_sourcing.db`) with automatic migrations and transactional backup API.

---

## CV Outreach & Safety Guarantees

### 1. Privacy & Offline Processing
- **Zero Cloud AI for Candidate Data:** All CV text extraction (PDF, DOCX, TXT, RTF) and candidate matching run 100% locally on your machine. Candidate PII, resumes, and contact info are never uploaded to OpenAI, Groq, or any third party.

### 2. Strictly Draft-Only Gmail Integration
- **Compose Scope Only:** Connected via Google OAuth using `https://www.googleapis.com/auth/gmail.compose`. The application does not request `mail.send` permissions and has no code or endpoints to dispatch emails.
- **No Accidental Sends:** Every email draft is placed into your Gmail "Drafts" folder for human review. You review and click "Send" manually from the Gmail interface.
- **Draft Idempotency:** Updating an outreach email updates the existing Gmail draft via `PUT /gmail/v1/users/me/drafts/{id}`, preventing duplicate draft clutter.

### 3. Contact Permission Gating, Email Verification & Opt-Out Suppression
- **Permission Lifecycle:** New CV imports default to `PENDING_REVIEW`. Draft generation is strictly blocked until a recruiter conducts a manual review and records `APPROVED_OUTREACH` or `DIRECT_CONSENT` along with reviewer identity, timestamp, and audit notes.
- **Email Verification:** Status tracked as `VERIFIED`, `PENDING_VERIFICATION`, or `INVALID`. Bounced or invalid addresses are prevented from entering the outreach pipeline.
- **Identity Ambiguity Protection:** Candidates with matching names but distinct or unverified emails are isolated with `AMBIGUOUS_REVIEW` and `UNVERIFIED` permission to prevent accidental profile merges.
- **Suppression List:** Candidates who opt out (`opt_out_status = 1`) are immediately excluded from all matching recommendations and cannot receive outreach drafts.

### 4. Opportunity Verification Lifecycle
- **Recruiter Audit Workflow:** Seeded and custom partner opportunities (Turing, Mercor, micro1) default to `UNVERIFIED`.
- **Status Enum:** Strictly tracked through `UNVERIFIED`, `UNDER_REVIEW`, `VERIFIED`, and `EXPIRED_INACTIVE`.
- **URL Separation:** Clearly distinguishes between official public career portal URLs and private referral track links.
- **Audit Logging:** Every verification change logs the verification source, notes, and reviewer timestamp.

### 5. Decoupled Scoring & Compliance Gating
- **Pure Role Fit Score (0–100):** Evaluates candidate qualifications purely objectively:
  - Skills & Core Competencies: 40 points
  - Relevant Experience: 25 points
  - Language Proficiency: 15 points (requires explicit evidence on CV)
  - Location & Work Authorization: 10 points
  - Secondary Tool Breadth: 10 points
- **Independent Outreach Eligibility Gating:**
  - `ELIGIBLE`: Fit score >= 65, candidate permission is `APPROVED_OUTREACH` or `DIRECT_CONSENT`, candidate not opted out, opportunity is `VERIFIED` and active, email is valid and verified.
  - `PENDING_REVIEW`: Fit score >= 40, but compliance gates (permission, email verification, or opportunity status) need human review.
  - `BLOCKED`: Fit score < 40, candidate opted out, or invalid/missing email.

### 6. ZIP Safety, Streaming & Asynchronous Batch Processing
- **Archive Limits & Defense:**
  - Max ZIP archive size: 500 MB (streamed in 64KB disk chunks to prevent RAM exhaustion)
  - Max total expanded size: 1 GB
  - Max per-file size: 50 MB
  - Max file count: 2,500 files
  - Zip-Slip path traversal protection and symlink entry rejection
- **Crash Recovery:** Server startup automatically invokes `recover_interrupted_jobs`, moving interrupted `PROCESSING` jobs into `PAUSED` with resume capability.
- **Background Async Execution:** Folder and ZIP imports process in dedicated worker threads with real-time polling, pause, and resume capabilities.

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
cd candidate_sourcing_tool
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```
API Documentation (Swagger UI) is available at: `http://127.0.0.1:8000/docs`

**Terminal 2 — React Vite Frontend:**
```powershell
cd candidate_sourcing_tool\frontend
npm run dev
```
Frontend UI is available at: `http://localhost:5173`

---

## Automated Test Suites

The project features comprehensive automated tests running 100% offline with zero network dependencies:

```powershell
cd candidate_sourcing_tool

# Run all tests (Core business logic + CV import + referrals + FastAPI endpoints)
python -m pytest

# Run CV outreach and matching tests
python -m pytest tests/test_referrals_and_matching.py -v

# Run CV import, deduplication, and ZIP safety tests
python -m pytest tests/test_cv_import_and_dedup.py -v
```

---

## Optional Integrations

### 1. Google Gmail OAuth (Draft-Only)
To create live drafts directly in your personal/work Gmail account:
1. Obtain OAuth 2.0 Client credentials from the Google Cloud Console (Desktop/Web application).
2. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env` or click "Connect Gmail (OAuth)" in the CV Outreach tab.
3. In mock/simulation mode, the system creates preview drafts locally without connecting to Google.

### 2. Optional Groq AI Configuration
Candidate Finder defaults to the 100% offline, local rule-based extractor. If you wish to enable the optional Groq AI extractor on its **Free plan**:
1. Copy `.env.example` to `.env`.
2. Configure `GROQ_API_KEY=gsk_...` and `GROQ_MODEL=openai/gpt-oss-120b` in `.env`.
3. Candidate Finder loads `.env` automatically via `python-dotenv`.
4. Only the Job Description text is sent to Groq; candidate profiles, CVs, and database records are **never** transmitted externally.
