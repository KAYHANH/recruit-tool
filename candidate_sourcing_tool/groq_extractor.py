from __future__ import annotations

import io
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from keyword_extractor import JobRequirements
from title_extractor import resolve_safe_title

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

# Project directory resolution
PROJECT_DIR = Path(__file__).resolve().parent
PROJECT_ENV_FILE = PROJECT_DIR / ".env"
_env_loaded = False


def load_project_env(env_path: Path | str | None = None, override: bool = False) -> bool:
    """Loads environment variables from the project's .env file using python-dotenv.
    Resolves the path relative to the project directory or parent directory rather than relying on current working directory.
    Does not log or expose any secrets.
    """
    global _env_loaded
    if env_path:
        target = Path(env_path).resolve()
        if target.exists() and target.is_file():
            load_dotenv(dotenv_path=target, override=override)
            return True
        return False

    if not _env_loaded or override:
        for candidate in [PROJECT_ENV_FILE, PROJECT_DIR.parent / ".env"]:
            if candidate.exists() and candidate.is_file():
                load_dotenv(dotenv_path=candidate, override=override)
                _env_loaded = True
                return True
    return False


# Automatically load project .env on module import
load_project_env()


def resolve_groq_api_key(override_key: str | None = None) -> str | None:
    """Resolves the Groq API key according to strict precedence:
    1. Explicit session-level override provided by user (if non-empty)
    2. os.getenv("GROQ_API_KEY") loaded from project .env or system environment

    Never prints, logs, or exposes the key value.
    """
    # 1. Explicit session-level override takes precedence
    if override_key and str(override_key).strip():
        return str(override_key).strip()

    # 2. Ensure project .env is evaluated on initial load
    if not _env_loaded:
        load_project_env()

    # 3. Default to environment variable (populated by project .env or system environment)
    env_key = os.getenv("GROQ_API_KEY", "").strip()
    if env_key:
        return env_key

    return None


def get_groq_api_key(override_key: str | None = None, search_dir: Path | str | None = None) -> str | None:
    """Retrieves the Groq API key. Alias for resolve_groq_api_key."""
    if search_dir:
        load_project_env(Path(search_dir) / ".env")
    return resolve_groq_api_key(override_key=override_key)


def get_groq_model(override_model: str | None = None, search_dir: Path | str | None = None) -> str:
    """Retrieves the configured Groq model ID.
    Priority order:
    1. Explicit override provided by user (if non-empty)
    2. os.getenv("GROQ_MODEL") from project .env or system environment
    3. DEFAULT_GROQ_MODEL ('openai/gpt-oss-120b')
    """
    if override_model and str(override_model).strip():
        return str(override_model).strip()

    if search_dir:
        load_project_env(Path(search_dir) / ".env")
    else:
        load_project_env()

    env_model = os.getenv("GROQ_MODEL", "").strip()
    if env_model:
        return env_model
    return DEFAULT_GROQ_MODEL


def extract_requirements_with_groq(
    jd_text: str,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 15.0,
) -> tuple[bool, JobRequirements | None, str]:
    """Uses Groq's high-speed inference to extract structured recruitment requirements.
    
    SECURITY & PRIVACY GUARANTEE:
    - Transmits ONLY the sanitized text of the job description.
    - NEVER transmits candidate records, CV text, recruiter notes, or database contents.
    - Requires an explicit recruiter action; never called automatically in the background.
    - Gracefully falls back to local rule-based extraction on missing key, timeout, rate-limit,
      model deprecation, or unsupported structured output.
    """
    if not jd_text or not jd_text.strip():
        return False, None, "Job description text is empty. Please provide JD text."

    active_model = get_groq_model(override_model=model)

    # Resolve key using single canonical resolution function
    resolved_key = resolve_groq_api_key(override_key=api_key)
    if not resolved_key:
        return (
            False,
            None,
            "Groq API key not found. Add GROQ_API_KEY to your project's .env file, set it as an environment variable, "
            "or enter an optional session key in the UI. Local rule-based extraction remains ready and 100% offline.",
        )

    # Sanitize and truncate excessively large text (>30,000 chars) to prevent payload abuse
    sanitized_text = jd_text.strip()
    if len(sanitized_text) > 30000:
        sanitized_text = sanitized_text[:30000]

    system_prompt = (
        "You are an expert recruitment analyst. Analyze the provided Job Description and return "
        "a strictly formatted JSON object with precise recruitment requirements. "
        "Do not invent skills that are not supported by the JD text. "
        "Required JSON schema:\n"
        "{\n"
        '  "job_title": string (exact primary job title),\n'
        '  "alternative_titles": list of strings (genuine alternative or similar role titles, exclude the primary title),\n'
        '  "required_skills": list of strings (explicit must-have core skills/competencies),\n'
        '  "preferred_skills": list of strings (nice-to-have, bonus, or huge plus skills),\n'
        '  "tools_and_tech": list of strings (software, tools, libraries, competition platforms),\n'
        '  "qualifications": list of strings (experience, degrees, mandatory credentials),\n'
        '  "education_or_certifications": list of strings,\n'
        '  "experience_level": string (e.g. "3+ years", "Freshers welcome"),\n'
        '  "location": string (e.g. "Remote", "London, UK"),\n'
        '  "employment_type": string (e.g. "Contractor", "Full-time", "Part-time"),\n'
        '  "portfolio_required": boolean,\n'
        '  "mandatory_constraints": list of strings (legal, location, or clearance constraints),\n'
        '  "inferred_keywords": list of strings (salient domain terms, excluding boilerplate stopwords),\n'
        '  "uncertainty_flags": list of strings (ambiguous requirements or unstated constraints),\n'
        '  "evidence": dict of string to string (mapping key extracted fields to verbatim phrases from the JD)\n'
        "}\n"
        "Respond with raw JSON only. Do not wrap in markdown backticks or include commentary."
    )

    payload = {
        "model": active_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Extract structured recruitment requirements from this Job Description:\n\n{sanitized_text}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 1500,
    }

    req_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {resolved_key}",
        "Content-Type": "application/json",
        "User-Agent": "CandidateFinder/1.0",
    }

    req = urllib.request.Request(GROQ_API_URL, data=req_bytes, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_bytes = resp.read()
            resp_data = json.loads(resp_bytes.decode("utf-8"))
    except urllib.error.HTTPError as http_err:
        status = http_err.code
        detail_msg = ""
        try:
            err_body = http_err.read().decode("utf-8", errors="replace")
            if err_body:
                err_json = json.loads(err_body)
                detail_msg = err_json.get("error", {}).get("message", "")
        except Exception:
            pass

        if not detail_msg:
            detail_msg = getattr(http_err, "reason", "HTTP Error")

        # Redact any accidental key leakage in error responses
        if resolved_key and resolved_key in detail_msg:
            detail_msg = detail_msg.replace(resolved_key, "[REDACTED]")

        if status == 400:
            return (
                False,
                None,
                f"Groq API error (HTTP 400 Bad Request): {detail_msg}. "
                f"Model '{active_model}' may not support structured JSON object output or request parameters are invalid. "
                "Falling back to local offline extractor.",
            )
        elif status == 401:
            return (
                False,
                None,
                "Groq API error (HTTP 401 Unauthorized): Invalid or expired API key. "
                "Check GROQ_API_KEY in your environment or project .env file. "
                "Falling back to local offline extractor.",
            )
        elif status == 404:
            return (
                False,
                None,
                f"Groq API error (HTTP 404 Not Found): Model '{active_model}' is not found or not accessible on your Groq tier. "
                "Check GROQ_MODEL in your environment/.env or use local offline extractor.",
            )
        elif status == 429:
            return (
                False,
                None,
                f"Groq API error (HTTP 429 Rate Limit Exceeded): {detail_msg}. "
                "Falling back to local offline extractor.",
            )
        elif status in (500, 502, 503, 504):
            return (
                False,
                None,
                f"Groq service error (HTTP {status}): Groq servers are temporarily unavailable ({detail_msg}). "
                "Falling back to local offline extractor.",
            )
        else:
            return (
                False,
                None,
                f"Groq API error (HTTP {status}): {detail_msg}. Falling back to local offline extractor.",
            )
    except urllib.error.URLError as url_err:
        return (
            False,
            None,
            f"Groq network error: Connection failed ({url_err.reason}). "
            "Check internet connection or use local offline extractor (100% offline).",
        )
    except TimeoutError:
        return (
            False,
            None,
            f"Groq request timed out after {timeout}s. Falling back to local offline extractor.",
        )
    except Exception as exc:
        exc_str = str(exc)
        if resolved_key and resolved_key in exc_str:
            exc_str = exc_str.replace(resolved_key, "[REDACTED]")
        return False, None, f"Unexpected error during Groq API call: {exc_str}"

    # Extract JSON content
    try:
        choices = resp_data.get("choices", [])
        if not choices:
            return False, None, "Groq response returned no completion choices."
        raw_content = choices[0].get("message", {}).get("content", "").strip()

        # Parse JSON
        parsed_json = json.loads(raw_content)

        # Validate structured fields
        job_title = resolve_safe_title(parsed_json.get("job_title", ""), jd_text=jd_text, fallback="AI Generalist")
        alt_titles = [str(x).strip() for x in parsed_json.get("alternative_titles", []) if str(x).strip()]
        req_skills = [str(x).strip() for x in parsed_json.get("required_skills", []) if str(x).strip()]
        pref_skills = [str(x).strip() for x in parsed_json.get("preferred_skills", []) if str(x).strip()]
        tools = [str(x).strip() for x in parsed_json.get("tools_and_tech", []) if str(x).strip()]
        qualifications = [str(x).strip() for x in parsed_json.get("qualifications", []) if str(x).strip()]
        edu_certs = [str(x).strip() for x in parsed_json.get("education_or_certifications", []) if str(x).strip()]
        exp = str(parsed_json.get("experience_level", "")).strip()
        loc = str(parsed_json.get("location", "")).strip() or "Remote"
        emp = str(parsed_json.get("employment_type", "")).strip() or "Full-time"
        portfolio_req = bool(parsed_json.get("portfolio_required", False))
        constraints = [str(x).strip() for x in parsed_json.get("mandatory_constraints", []) if str(x).strip()]
        inferred = [str(x).strip() for x in parsed_json.get("inferred_keywords", []) if str(x).strip()]
        uncertainty_flags = [str(x).strip() for x in parsed_json.get("uncertainty_flags", []) if str(x).strip()]
        raw_evidence = parsed_json.get("evidence", {})
        evidence = (
            {str(k).strip(): str(v).strip() for k, v in raw_evidence.items() if str(k).strip() and str(v).strip()}
            if isinstance(raw_evidence, dict)
            else {}
        )

        requirements = JobRequirements(
            job_title=job_title,
            alternative_titles=alt_titles,
            required_skills=req_skills,
            preferred_skills=pref_skills,
            tools_and_tech=tools,
            qualifications=qualifications,
            education_or_certifications=edu_certs,
            experience_level=exp,
            location=loc,
            employment_type=emp,
            portfolio_required=portfolio_req,
            mandatory_constraints=constraints,
            inferred_keywords=inferred,
            uncertainty_flags=uncertainty_flags,
            evidence=evidence,
        )
        return True, requirements, f"Requirements successfully extracted using Groq AI ({active_model})."
    except json.JSONDecodeError as json_err:
        return False, None, f"Failed to parse Groq AI response as JSON: {json_err}"
    except Exception as exc:
        return False, None, f"Validation error processing Groq response: {exc}"


def run_groq_live_smoke_test(
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 12.0,
) -> dict:
    """Executes a minimal live smoke test against the Groq API.
    
    PRIVACY & SAFETY GUARANTEE:
    - NEVER sends candidate records, CV text, recruiter notes, or SQLite contents.
    - Sends only a minimal synthetic job description string (under 100 characters).
    - Does NOT print, log, or persist the API key.
    - Returns structured status categories, HTTP codes, and sanitized messages.
    """
    resolved_key = resolve_groq_api_key(override_key=api_key)
    active_model = get_groq_model(override_model=model)

    if not resolved_key:
        return {
            "success": False,
            "status_category": "CONFIG_MISSING",
            "status_code": None,
            "model": active_model,
            "message": "GROQ_API_KEY is not set in project .env or environment variables. Live verification skipped.",
            "validated_schema": False,
            "extracted_summary": None,
        }

    # Minimal synthetic JD for smoke testing (never uses candidate or DB data)
    minimal_jd = "Role: Software Engineer. Location: Remote. Required: Python, SQL. Experience: 3+ years."

    ok, reqs, msg = extract_requirements_with_groq(
        jd_text=minimal_jd,
        api_key=resolved_key,
        model=active_model,
        timeout=timeout,
    )

    if ok and reqs:
        return {
            "success": True,
            "status_category": "SUCCESS_200",
            "status_code": 200,
            "model": active_model,
            "message": f"Successfully connected to Groq API. Model '{active_model}' is accessible and supported.",
            "validated_schema": True,
            "extracted_summary": {
                "job_title": reqs.job_title,
                "required_skills": reqs.required_skills,
                "location": reqs.location,
                "experience_level": reqs.experience_level,
            },
        }

    # Categorize error
    status_cat = "UNKNOWN_ERROR"
    status_code = None
    if "401" in msg:
        status_cat = "AUTH_ERROR_401"
        status_code = 401
    elif "404" in msg:
        status_cat = "MODEL_NOT_FOUND_404"
        status_code = 404
    elif "400" in msg:
        status_cat = "BAD_REQUEST_400"
        status_code = 400
    elif "429" in msg:
        status_cat = "RATE_LIMIT_429"
        status_code = 429
    elif any(f"HTTP {code}" in msg for code in (500, 502, 503, 504)):
        status_cat = "SERVER_ERROR_5XX"
        status_code = 500
    elif "timed out" in msg.lower():
        status_cat = "TIMEOUT"
    elif "network error" in msg.lower():
        status_cat = "NETWORK_ERROR"

    return {
        "success": False,
        "status_category": status_cat,
        "status_code": status_code,
        "model": active_model,
        "message": msg,
        "validated_schema": False,
        "extracted_summary": None,
    }
