"""Groq AI Reasoning and Orchestration Engine for Candidate Finder.

Operates Groq as an intelligent recruitment reasoning layer across:
1. JD Intelligence: Structured requirement extraction, skill classification, uncertainty flags.
2. Search Planning: Dynamic query expansion, broadening strategies, negative filtering.
3. Local Function Calling: Model-driven tool calling across verified zero-budget connectors.
4. Profile Intelligence: Distinguishing direct technical evidence from weak vanity signals.
5. Candidate Match Explanations: Evidence-backed qualitative rationale supplementing deterministic matcher scores.
6. Deduplication Assistance: Probabilistic duplicate identity reasoning advising deterministic entity resolution.
7. Recruiter Feedback Calibration: Feedback analysis, strategy tuning, and SQLite version history.

Strict Zero-Budget and Security Guarantees:
- Server-side key resolution; never logged, printed, or sent to client.
- Operates under Groq Free Tier (1,000 req/day, 8,000 tokens/min).
- On HTTP 429 quota exhaustion, pauses gracefully without crashing or attempting paid tiers.
- Every function-call argument is strictly validated, sanitized, and bounded before execution.
- Bounded turn recursion prevents unbounded or recursive tool-call loops.
- Deterministic Python code remains the authoritative source of truth for scores, entity merges, and database persistence.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cost_guard import cost_guard
from db import save_strategy_version
from groq_extractor import DEFAULT_GROQ_MODEL, get_groq_model, resolve_groq_api_key
from keyword_extractor import JobRequirements
from source_connectors import (
    BaseSourceConnector,
    ConnectorSearchResult,
    RawCandidateProfile,
)

logger = logging.getLogger("groq_reasoning")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Whitelist of approved application tools for Groq function calling
APPROVED_TOOL_NAMES = {
    "search_github",
    "search_gitlab",
    "search_stackexchange",
    "search_huggingface",
    "search_local_candidates",
}

# Schemas for Groq function calling
APPROVED_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_github",
            "description": "Searches for public developer profiles on GitHub matching technical skills and optional location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "string",
                        "description": "Technical skills, programming languages, or role keywords (max 200 chars).",
                    },
                    "location": {
                        "type": "string",
                        "description": "Candidate city or country filter (optional, max 100 chars).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of profiles to return (1 to 10, default 5).",
                        "default": 5,
                    },
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_gitlab",
            "description": "Searches public project repositories and code creators on GitLab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "string",
                        "description": "Technical keywords or project topics (max 200 chars).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (1 to 10, default 5).",
                        "default": 5,
                    },
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stackexchange",
            "description": "Searches Stack Overflow public contributors by tag or username with reputation signals.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "string",
                        "description": "Core technology or tag name (e.g. python, rust, kubernetes).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max contributors to return (1 to 10, default 5).",
                        "default": 5,
                    },
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_huggingface",
            "description": "Searches public AI/ML model authors and creators on the Hugging Face Hub.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "string",
                        "description": "AI, ML, PyTorch, LLM, or model architecture keywords.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max model creators to return (1 to 10, default 5).",
                        "default": 5,
                    },
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_local_candidates",
            "description": "Searches previously saved candidates in the local SQLite database for talent rediscovery.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "string",
                        "description": "Skills, headline terms, or role keywords to rediscover.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max candidates to retrieve (1 to 10, default 5).",
                        "default": 5,
                    },
                },
                "required": ["keywords"],
            },
        },
    },
]


class ArgumentValidationError(Exception):
    """Raised when model-generated tool arguments fail validation checks."""
    pass


def validate_tool_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validates and sanitizes model-generated tool arguments before execution.
    Enforces argument bounds, type checks, and prevents malicious injection.
    """
    if tool_name not in APPROVED_TOOL_NAMES:
        raise ArgumentValidationError(f"Unauthorized tool requested: '{tool_name}'.")

    if not isinstance(arguments, dict):
        raise ArgumentValidationError("Tool arguments must be a JSON dictionary.")

    # Validate keywords
    raw_kw = str(arguments.get("keywords", "")).strip()
    if not raw_kw:
        raise ArgumentValidationError("Missing required 'keywords' parameter.")
    if len(raw_kw) > 200:
        raw_kw = raw_kw[:200]

    # Sanitize dangerous injection characters
    clean_kw = re.sub(r"[;\x00\r\n]", " ", raw_kw).strip()
    # Remove SQL comment indicators
    clean_kw = clean_kw.replace("--", "").replace("/*", "").replace("*/", "")
    clean_kw = re.sub(r"\s+", " ", clean_kw)

    # Validate location
    raw_loc = str(arguments.get("location", "")).strip()
    clean_loc = re.sub(r"[;\x00\r\n]", " ", raw_loc)[:100].strip()

    # Validate and clamp limit (1 to 10)
    try:
        raw_limit = int(arguments.get("limit", 5))
    except (ValueError, TypeError):
        raw_limit = 5
    clamped_limit = min(10, max(1, raw_limit))

    return {
        "keywords": clean_kw,
        "location": clean_loc,
        "limit": clamped_limit,
    }


def call_groq_chat_completion(
    messages: list[dict[str, Any]],
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, str] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    timeout: float = 25.0,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Internal helper to execute Groq API completions with zero-budget cost logging,
    HTTP 429 quota handling, and Cloudflare header compliance.
    """
    api_key = resolve_groq_api_key()
    if not api_key:
        return False, None, "GROQ_API_KEY is not configured in .env or environment."

    active_model = model or get_groq_model()

    cost_guard.log_request(
        "groq_extractor" if response_format else "groq_browser",
        "chat_completion",
        f"Model: {active_model}, Tools: {bool(tools)}, Structured: {bool(response_format)}",
    )

    body: dict[str, Any] = {
        "model": active_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if response_format:
        body["response_format"] = response_format

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "CandidateFinder/1.0",
    }

    req = Request(
        GROQ_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, data, None
    except HTTPError as http_err:
        code = http_err.code
        reset_hdr = http_err.headers.get("x-ratelimit-reset-tokens")
        if code == 429:
            msg = f"Groq Free Tier rate limit reached (HTTP 429). Reset: {reset_hdr or 'soon'}. Safe local fallback active."
            logger.warning(msg)
            return False, None, msg
        elif code == 401:
            return False, None, "Groq API key unauthorized (HTTP 401). Verify GROQ_API_KEY in .env."
        else:
            try:
                err_text = http_err.read().decode("utf-8")
            except Exception:
                err_text = str(http_err)
            return False, None, f"Groq HTTP {code}: {err_text[:200]}"
    except (URLError, TimeoutError) as net_err:
        return False, None, f"Network timeout or error connecting to Groq: {str(net_err)[:150]}"
    except Exception as exc:
        return False, None, f"Unexpected Groq client error: {str(exc)[:150]}"


# ==============================================================================
# 1. TOOL-CALLING ORCHESTRATION AGENT
# ==============================================================================

class GroqToolCallingOrchestrator:
    """Manages autonomous local function calling with Groq.
    Enforces strict recursion depth (max 3 turns), argument validation,
    and returns discovered raw candidate profiles without model hallucination.
    """

    def __init__(self, connectors: dict[str, BaseSourceConnector], max_turns: int = 3):
        self.connectors = connectors
        self.max_turns = max_turns

    def run_sourcing_session(
        self,
        requirements: JobRequirements,
        location: str = "",
        limit_per_tool: int = 5,
    ) -> tuple[list[RawCandidateProfile], list[dict[str, Any]], str]:
        """Runs an interactive multi-turn tool calling session where Groq reasons about
        which platforms to query based on role requirements.
        """
        api_key = resolve_groq_api_key()
        if not api_key:
            return [], [], "Groq API key not configured; skipping function calling session."

        system_msg = (
            "You are an expert talent sourcing coordinator. You have access to approved application tools "
            "to discover candidates across GitHub, GitLab, Stack Overflow, Hugging Face, and Local SQLite DB.\n\n"
            "RULES:\n"
            "1. Choose the most relevant platforms for the role. (e.g. Hugging Face for AI/ML, GitHub/GitLab for code, Stack Overflow for contributors).\n"
            "2. Execute tool calls with specific technical keywords, not generic words.\n"
            "3. Do NOT invent candidates. Candidates are ONLY returned from the tool executions.\n"
            "4. When results are returned, review them and conclude when sufficient candidates are found."
        )

        user_msg = (
            f"Plan and execute sourcing searches for this opening:\n"
            f"Role Title: {requirements.job_title}\n"
            f"Required Skills: {', '.join(requirements.required_skills[:5])}\n"
            f"Tools & Tech: {', '.join(requirements.tools_and_tech[:4])}\n"
            f"Location: {location or requirements.location or 'Remote'}\n"
            f"Please call the appropriate search tools to find candidate profiles."
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        accumulated_profiles: list[RawCandidateProfile] = []
        tool_call_audit: list[dict[str, Any]] = []

        for turn in range(self.max_turns):
            ok, data, err = call_groq_chat_completion(
                messages=messages,
                tools=APPROVED_TOOLS_SCHEMA,
                temperature=0.1,
            )

            if not ok or not data:
                logger.warning(f"Groq tool calling session turn {turn + 1} stopped: {err}")
                break

            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            messages.append(msg)

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                # Model concluded searches or provided final summary
                break

            for tc in tool_calls:
                call_id = tc.get("id", f"call_{turn}")
                fn_info = tc.get("function", {})
                fn_name = fn_info.get("name", "")
                raw_args_str = fn_info.get("arguments", "{}")

                try:
                    args_dict = json.loads(raw_args_str) if isinstance(raw_args_str, str) else raw_args_str
                except Exception:
                    args_dict = {}

                # 1. Validate arguments
                try:
                    valid_args = validate_tool_call(fn_name, args_dict)
                except ArgumentValidationError as val_err:
                    error_resp = {"status": "error", "message": str(val_err)}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(error_resp),
                    })
                    tool_call_audit.append({
                        "tool": fn_name,
                        "status": "VALIDATION_FAILED",
                        "error": str(val_err),
                    })
                    continue

                # 2. Dispatch to matching connector
                target_connector_id = fn_name.replace("search_", "").replace("candidates", "db")
                connector = self.connectors.get(target_connector_id)

                if not connector:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps({"status": "error", "message": f"Connector {fn_name} unavailable."}),
                    })
                    continue

                try:
                    res: ConnectorSearchResult = connector.search(
                        keywords=valid_args["keywords"],
                        location=valid_args.get("location", ""),
                        limit=min(limit_per_tool, valid_args["limit"]),
                    )

                    accumulated_profiles.extend(res.candidates)

                    # Return compact normalized summary to avoid token overflow
                    compact_results = [
                        {
                            "name": c.name,
                            "profile_url": c.profile_url,
                            "headline": c.headline,
                            "location": c.location,
                            "evidence_tier": c.evidence_ladder_tier,
                        }
                        for c in res.candidates[:5]
                    ]

                    tool_resp = {
                        "status": "success",
                        "candidates_found": len(res.candidates),
                        "total_available": res.total_found,
                        "candidates": compact_results,
                    }

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(tool_resp),
                    })

                    tool_call_audit.append({
                        "tool": fn_name,
                        "arguments": valid_args,
                        "status": "COMPLETED",
                        "candidates_found": len(res.candidates),
                    })

                except Exception as exc:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps({"status": "error", "message": str(exc)}),
                    })
                    tool_call_audit.append({
                        "tool": fn_name,
                        "arguments": valid_args,
                        "status": "FAILED",
                        "error": str(exc),
                    })

        return accumulated_profiles, tool_call_audit, "Session completed."


# ==============================================================================
# 2. SEARCH PLANNING & REASONING
# ==============================================================================

def plan_search_reasoning(
    requirements: JobRequirements,
    previous_feedback: list[dict[str, Any]] | None = None,
    broaden_search: bool = False,
) -> dict[str, Any]:
    """Generates an intelligent, feedback-informed Boolean search strategy with Groq.
    Expands alternative variations and handles broadening when initial yields are dry.
    Falls back gracefully to local rule-based generation.
    """
    api_key = resolve_groq_api_key()
    if not api_key:
        return _fallback_search_plan(requirements, broaden=broaden_search)

    feedback_notes = []
    if previous_feedback:
        for f in previous_feedback[:5]:
            r = f.get("rating", "")
            t = f.get("feedback_text", "")
            if t:
                feedback_notes.append(f"- Candidate rated '{r}': {t}")

    feedback_context = "\n".join(feedback_notes) if feedback_notes else "No previous feedback recorded."

    broaden_prompt = "Initial searches returned low yield. Generate broader, less restrictive variations." if broaden_search else ""

    system_prompt = (
        "You are an expert technical recruiting search architect. Generate structured search strategies "
        "and Boolean strings for sourcing candidates across public web sources.\n"
        "Return a strictly formatted JSON object with this schema:\n"
        "{\n"
        '  "primary_query": string (precise Boolean search string),\n'
        '  "alternative_queries": list of strings (3 to 4 varied search strings),\n'
        '  "negative_keywords": list of strings (exclusions, e.g. -jobs, -careers),\n'
        '  "broadened_queries": list of strings (expanded terms if yield is low),\n'
        '  "target_platforms": list of strings,\n'
        '  "strategy_rationale": string\n'
        "}\n"
        "Raw JSON only. Never invent unrealistic terms."
    )

    user_content = (
        f"Generate search strategies for:\n"
        f"Title: {requirements.job_title}\n"
        f"Required Skills: {', '.join(requirements.required_skills[:5])}\n"
        f"Tools: {', '.join(requirements.tools_and_tech[:4])}\n"
        f"Location: {requirements.location or 'Remote'}\n"
        f"Recruiter Calibration Context:\n{feedback_context}\n"
        f"{broaden_prompt}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    ok, data, err = call_groq_chat_completion(
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    if not ok or not data:
        return _fallback_search_plan(requirements, broaden=broaden_search)

    try:
        content = data["choices"][0]["message"]["content"]
        plan = json.loads(content)
        # Validate schema locally
        if not isinstance(plan.get("primary_query"), str) or not plan.get("primary_query"):
            return _fallback_search_plan(requirements, broaden=broaden_search)
        return plan
    except Exception:
        return _fallback_search_plan(requirements, broaden=broaden_search)


def _fallback_search_plan(requirements: JobRequirements, broaden: bool = False) -> dict[str, Any]:
    """Offline rule-based fallback search plan."""
    title = requirements.job_title or "Software Engineer"
    skills = requirements.required_skills[:3]
    skill_clause = " AND ".join(f'"{s}"' for s in skills) if skills else ""
    loc_clause = f'"{requirements.location}"' if requirements.location else "Remote"

    primary = f'"{title}" {skill_clause} {loc_clause} -jobs -careers'.strip()
    alts = [
        f'site:linkedin.com/in/ "{title}" {skill_clause} -jobs',
        f'site:github.com "{title}" {" ".join(skills)}',
        f'("resume" OR "cv") "{title}" {skill_clause} filetype:pdf -template',
    ]

    return {
        "primary_query": primary,
        "alternative_queries": alts,
        "negative_keywords": ["-jobs", "-careers", "-hiring", "-templates", "-sample"],
        "broadened_queries": [f'"{title}" ({loc_clause}) -jobs'],
        "target_platforms": ["LinkedIn Profiles", "GitHub", "Public CVs"],
        "strategy_rationale": "Rule-based fallback strategy targeting exact title and primary skills.",
    }


# ==============================================================================
# 3. CANDIDATE MATCH EXPLANATIONS (QUALITATIVE AI REASONING)
# ==============================================================================

def explain_candidate_match_with_groq(
    candidate: dict[str, Any],
    requirements: JobRequirements,
) -> dict[str, Any]:
    """Generates an evidence-backed qualitative match explanation with Groq.
    Analyzes verified source evidence against the approved JD.
    Highlights supporting evidence, missing information, and potential contradictions.
    DETERMINISTIC SCORE IS PRESERVED AND NOT OVERWRITTEN.
    """
    api_key = resolve_groq_api_key()
    if not api_key:
        return _fallback_match_explanation(candidate, requirements)

    # Privacy Protection: Send minimal public evidence, NOT full DB contents or private notes
    cand_name = candidate.get("name", "Candidate")
    headline = candidate.get("headline", "")
    evidence = candidate.get("evidence_text", "")[:1200]
    location = candidate.get("location", "")

    system_prompt = (
        "You are an objective recruitment evaluation analyst. Analyze the supplied candidate evidence "
        "against the job requirements and produce a strictly formatted JSON evaluation.\n"
        "RULES:\n"
        "1. Base findings ONLY on the provided candidate text. Do NOT hallucinate credentials.\n"
        "2. Clearly identify supported evidence versus missing information.\n"
        "Required JSON Schema:\n"
        "{\n"
        '  "summary": string (concise recruiter assessment, 1-2 sentences),\n'
        '  "strong_signals": list of strings (verified capabilities backed by evidence),\n'
        '  "missing_or_uncertain": list of strings (mandatory or preferred skills lacking evidence),\n'
        '  "contradictions": list of strings (any conflicting seniority, location, or tech signals),\n'
        '  "evidence_verdict": string ("High Match" | "Moderate Match" | "Potential / Adjacent" | "Insufficient Evidence"),\n'
        '  "uncertainty_flags": list of strings\n'
        "}\n"
        "Raw JSON only."
    )

    user_content = (
        f"JOB REQUIREMENTS:\n"
        f"Title: {requirements.job_title}\n"
        f"Required Skills: {', '.join(requirements.required_skills)}\n"
        f"Tools: {', '.join(requirements.tools_and_tech)}\n"
        f"Location: {requirements.location or 'Any'}\n\n"
        f"CANDIDATE PROFILE EVIDENCE:\n"
        f"Name: {cand_name}\n"
        f"Headline: {headline}\n"
        f"Location: {location}\n"
        f"Evidence Excerpt:\n{evidence}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    ok, data, err = call_groq_chat_completion(
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    if not ok or not data:
        return _fallback_match_explanation(candidate, requirements)

    try:
        content = data["choices"][0]["message"]["content"]
        expl = json.loads(content)
        # Validate schema
        if not isinstance(expl.get("summary"), str):
            return _fallback_match_explanation(candidate, requirements)
        return expl
    except Exception:
        return _fallback_match_explanation(candidate, requirements)


def _fallback_match_explanation(candidate: dict[str, Any], requirements: JobRequirements) -> dict[str, Any]:
    """Rule-based heuristic match explanation fallback."""
    name = candidate.get("name", "Candidate")
    evidence = (candidate.get("evidence_text") or "").lower()
    matched = [s for s in requirements.required_skills if s.lower() in evidence]
    missing = [s for s in requirements.required_skills if s.lower() not in evidence]

    return {
        "summary": f"{name} demonstrates keyword alignment for {len(matched)} required skills.",
        "strong_signals": [f"Evidence aligns with skill: {m}" for m in matched],
        "missing_or_uncertain": [f"Unverified requirement in source text: {m}" for m in missing],
        "contradictions": [],
        "evidence_verdict": "Moderate Match" if matched else "Insufficient Evidence",
        "uncertainty_flags": ["Generated via offline heuristic without external LLM."],
    }


# ==============================================================================
# 3B. PROFILE INTELLIGENCE (TECHNICAL EVIDENCE VS VANITY SIGNALS)
# ==============================================================================

def analyze_profile_intelligence(
    evidence_text: str,
    requirements: JobRequirements | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Analyzes candidate profile text and artifacts to extract direct technical evidence.
    
    Explicitly separates direct technical corroboration (authored commits, production deployments,
    system designs) from superficial vanity metrics (starred forks, follower vanity counts, passive memberships).
    Extracts:
    - supported_skills: list of dicts with {"skill": str, "evidence": str, "confidence": "high"|"medium"|"low"}
    - projects: list of dicts with {"name": str, "description": str, "technologies": list[str]}
    - tenure_signals: list of strings describing experience tenure or seniority indications
    - public_contact_or_links: list of strings (extracted URLs, public handles, emails)
    - vanity_signals: list of strings identified as vanity/superficial signals
    - uncertainty_flags: list of strings highlighting unverified claims or gaps
    """
    resolved_key = resolve_groq_api_key(override_key=api_key)
    if not resolved_key or not evidence_text or not evidence_text.strip():
        return _fallback_profile_intelligence(evidence_text, requirements)

    # Privacy and token guard: truncate evidence to 15,000 chars max
    sanitized_text = evidence_text.strip()
    if len(sanitized_text) > 15000:
        sanitized_text = sanitized_text[:15000]

    req_context = ""
    if requirements:
        req_context = (
            f"Target Role: {requirements.job_title}\n"
            f"Required Skills: {', '.join(requirements.required_skills)}\n"
            f"Tools & Tech: {', '.join(requirements.tools_and_tech)}\n"
        )

    system_prompt = (
        "You are an expert technical recruiter and talent intelligence analyst. "
        "Analyze the provided candidate profile/evidence text. "
        "CRITICAL RULE: You must rigorously distinguish between direct technical evidence (e.g. authored code, "
        "architecture implementations, libraries built, production deployments) and superficial vanity signals "
        "(e.g. followers, starred repositories without commits, passive group memberships, generic buzzwords). "
        "Never fabricate skills or projects not mentioned in the text.\n\n"
        "Return a strictly valid JSON object matching this schema:\n"
        "{\n"
        '  "supported_skills": [{"skill": string, "evidence": string, "confidence": "high"|"medium"|"low"}],\n'
        '  "projects": [{"name": string, "description": string, "technologies": [string]}],\n'
        '  "tenure_signals": [string],\n'
        '  "public_contact_or_links": [string],\n'
        '  "vanity_signals": [string],\n'
        '  "uncertainty_flags": [string]\n'
        "}\n"
        "Respond with raw JSON only without markdown formatting."
    )

    user_content = (
        f"{req_context}\n"
        f"CANDIDATE EVIDENCE TEXT:\n"
        f"{sanitized_text}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    ok, data, err = call_groq_chat_completion(
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
        model=model,
        timeout=timeout,
    )

    if not ok or not data:
        return _fallback_profile_intelligence(evidence_text, requirements)

    try:
        content = data["choices"][0]["message"]["content"]
        result = json.loads(content)
        if not isinstance(result, dict) or "supported_skills" not in result:
            return _fallback_profile_intelligence(evidence_text, requirements)
        return result
    except Exception:
        return _fallback_profile_intelligence(evidence_text, requirements)


def _fallback_profile_intelligence(
    evidence_text: str,
    requirements: JobRequirements | None = None,
) -> dict[str, Any]:
    """Offline heuristic profile intelligence extraction."""
    text = evidence_text or ""
    url_pattern = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.IGNORECASE)
    email_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")

    urls = list(set(url_pattern.findall(text)))
    emails = list(set(email_pattern.findall(text)))
    links_and_contacts = urls + emails

    supported_skills = []
    if requirements:
        target_skills = list(set(requirements.required_skills + requirements.preferred_skills + requirements.tools_and_tech))
    else:
        target_skills = ["Python", "FastAPI", "React", "TypeScript", "Docker", "SQL", "Git", "Go", "Java", "Kubernetes"]

    for sk in set(target_skills):
        if not sk:
            continue
        pattern = r"\b" + re.escape(sk) + r"\b"
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            start = max(0, matches[0].start() - 40)
            end = min(len(text), matches[0].end() + 60)
            snippet = text[start:end].strip()
            supported_skills.append({
                "skill": sk,
                "evidence": f"...{snippet}...",
                "confidence": "medium",
            })

    vanity_signals = []
    vanity_keywords = ["followers", "following", "starred", "stargazers", "profile views", "endorsements"]
    for vk in vanity_keywords:
        if re.search(r"\b" + re.escape(vk) + r"\b", text, re.IGNORECASE):
            vanity_signals.append(f"Identified mention of {vk} (classified as non-technical vanity metric).")

    tenure_signals = []
    years_match = re.findall(r"(\d+\+?\s*(?:years?|yrs?)(?:\s+of\s+experience)?)", text, re.IGNORECASE)
    for ym in years_match[:3]:
        tenure_signals.append(f"Mentioned tenure signal: {ym}")

    return {
        "supported_skills": supported_skills,
        "projects": [],
        "tenure_signals": tenure_signals,
        "public_contact_or_links": links_and_contacts[:5],
        "vanity_signals": vanity_signals,
        "uncertainty_flags": ["Profile intelligence derived via offline rule heuristic."],
    }


# ==============================================================================
# 4. DEDUPLICATION ASSISTANCE (PROBABILISTIC REASONING)
# ==============================================================================

def assist_deduplication_with_groq(
    candidate_a: dict[str, Any],
    candidate_b: dict[str, Any],
) -> dict[str, Any]:
    """Assists candidate deduplication by reasoning about whether two profile records
    from different sources belong to the same person.
    THE LOCAL ENTITY RESOLVER ENFORCES FINAL MERGE DECISION; NEVER MERGES SOLELY ON COMMON NAME.
    """
    api_key = resolve_groq_api_key()
    if not api_key:
        return _fallback_deduplication_check(candidate_a, candidate_b)

    # Privacy Protection: Send minimal public identifiers
    a_summary = (
        f"Name: {candidate_a.get('name')}, Source: {candidate_a.get('source')}, "
        f"Headline: {candidate_a.get('headline')}, Company: {candidate_a.get('company')}, "
        f"Location: {candidate_a.get('location')}, URL: {candidate_a.get('profile_url')}"
    )
    b_summary = (
        f"Name: {candidate_b.get('name')}, Source: {candidate_b.get('source')}, "
        f"Headline: {candidate_b.get('headline')}, Company: {candidate_b.get('company')}, "
        f"Location: {candidate_b.get('location')}, URL: {candidate_b.get('profile_url')}"
    )

    system_prompt = (
        "You are an entity resolution analyst. Determine whether these two candidate records "
        "refer to the EXACT same person across different recruitment sources.\n"
        "CRITICAL RULES:\n"
        "1. Never conclude duplicate based on common first/last names alone.\n"
        "2. Look for corroborating signals: username handles, company tenure, specific projects, location.\n"
        "Required JSON Schema:\n"
        "{\n"
        '  "is_likely_same_person": boolean,\n'
        '  "confidence": number (0.0 to 1.0),\n'
        '  "shared_signals": list of strings,\n'
        '  "conflicting_signals": list of strings,\n'
        '  "rationale": string\n'
        "}\n"
        "Raw JSON only."
    )

    user_content = f"PROFILE A:\n{a_summary}\n\nPROFILE B:\n{b_summary}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    ok, data, err = call_groq_chat_completion(
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    if not ok or not data:
        return _fallback_deduplication_check(candidate_a, candidate_b)

    try:
        content = data["choices"][0]["message"]["content"]
        res = json.loads(content)
        if not isinstance(res.get("is_likely_same_person"), bool):
            return _fallback_deduplication_check(candidate_a, candidate_b)
        return res
    except Exception:
        return _fallback_deduplication_check(candidate_a, candidate_b)


def _fallback_deduplication_check(cand_a: dict[str, Any], cand_b: dict[str, Any]) -> dict[str, Any]:
    """Deterministic heuristic duplicate assessment."""
    url_a = (cand_a.get("profile_url") or "").lower().rstrip("/")
    url_b = (cand_b.get("profile_url") or "").lower().rstrip("/")
    same_url = bool(url_a and url_b and url_a == url_b)

    email_a = (cand_a.get("email") or "").lower().strip()
    email_b = (cand_b.get("email") or "").lower().strip()
    same_email = bool(email_a and email_b and email_a == email_b)

    if same_url or same_email:
        return {
            "is_likely_same_person": True,
            "confidence": 0.95,
            "shared_signals": ["Exact profile URL or verified email match"],
            "conflicting_signals": [],
            "rationale": "High-confidence identity match via deterministic unique identifier.",
        }

    return {
        "is_likely_same_person": False,
        "confidence": 0.2,
        "shared_signals": [],
        "conflicting_signals": ["Different public URLs without corroborating identity tokens"],
        "rationale": "Insufficient common unique tokens to confirm identical individual.",
    }


# ==============================================================================
# 5. RECRUITER FEEDBACK CALIBRATION & STRATEGY VERSIONING
# ==============================================================================

def calibrate_sourcing_from_feedback(
    db_conn: sqlite3.Connection,
    job_id: int,
    feedback_items: list[dict[str, Any]],
    current_requirements: JobRequirements,
) -> dict[str, Any]:
    """Analyzes recruiter feedback history to propose search adjustments.
    Extracts negative keywords (e.g. from irrelevant profiles), suggests prioritizations,
    and saves an approved strategy version in SQLite with version history.
    NEVER SILENTLY CHANGES MANDATORY REQUIREMENTS.
    """
    api_key = resolve_groq_api_key()

    feedback_summary_lines = []
    for item in feedback_items:
        r = item.get("rating", "Feedback")
        txt = item.get("feedback_text", "")
        cand_name = item.get("candidate_name", "Candidate")
        feedback_summary_lines.append(f"- {cand_name} rated '{r}': {txt}")

    feed_text = "\n".join(feedback_summary_lines) if feedback_summary_lines else "No specific recruiter comments."

    if not api_key:
        return _fallback_feedback_calibration(db_conn, job_id, current_requirements, feed_text)

    system_prompt = (
        "You are a recruitment calibration expert. Analyze recruiter feedback on sourced candidates "
        "and suggest precise search adjustments to increase relevant yield.\n"
        "CONSTRAINTS:\n"
        "1. NEVER alter, remove, or relax the recruiter's approved mandatory requirements.\n"
        "2. Formulate negative exclusions (-terms) to eliminate noisy profiles.\n"
        "3. Propose source priority weightings based on where relevant candidates originated.\n"
        "Required JSON Schema:\n"
        "{\n"
        '  "strategy_name": string (e.g. "Calibration v2 - Filtered Junior Roles"),\n'
        '  "changes_summary": string,\n'
        '  "adjusted_keywords": string,\n'
        '  "negative_keywords": string (Boolean exclusion string e.g. "-junior -intern -sales"),\n'
        '  "source_priorities": dict (mapping source_id to priority rating "High" | "Medium" | "Low"),\n'
        '  "preserved_mandatory_skills": list of strings\n'
        "}\n"
        "Raw JSON only."
    )

    user_content = (
        f"Job Title: {current_requirements.job_title}\n"
        f"Mandatory Skills: {', '.join(current_requirements.required_skills)}\n"
        f"Tools: {', '.join(current_requirements.tools_and_tech)}\n\n"
        f"Recruiter Feedback Log:\n{feed_text}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    ok, data, err = call_groq_chat_completion(
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    if not ok or not data:
        return _fallback_feedback_calibration(db_conn, job_id, current_requirements, feed_text)

    try:
        content = data["choices"][0]["message"]["content"]
        res = json.loads(content)

        # Validate mandatory skills preservation
        res["preserved_mandatory_skills"] = current_requirements.required_skills

        # Persist to SQLite version history
        ver_id = save_strategy_version(
            conn=db_conn,
            job_id=job_id,
            strategy_name=res.get("strategy_name", "AI Calibrated Strategy"),
            changes_summary=res.get("changes_summary", "Calibrated from recruiter feedback."),
            adjusted_keywords=res.get("adjusted_keywords", " ".join(current_requirements.required_skills[:3])),
            negative_keywords=res.get("negative_keywords", "-jobs -careers"),
            source_priorities=res.get("source_priorities", {}),
        )
        res["version_id"] = ver_id
        return res

    except Exception as exc:
        logger.error(f"Error parsing calibration feedback: {exc}")
        return _fallback_feedback_calibration(db_conn, job_id, current_requirements, feed_text)


def _fallback_feedback_calibration(
    db_conn: sqlite3.Connection,
    job_id: int,
    reqs: JobRequirements,
    feed_text: str,
) -> dict[str, Any]:
    """Offline feedback calibration fallback."""
    strat_name = "Rule-Based Feedback Calibration"
    summary = f"Refined keywords based on {len(feed_text.splitlines())} feedback entries."
    kw = " ".join(reqs.required_skills[:3]) if reqs.required_skills else reqs.job_title
    neg = "-jobs -careers -recruiter -intern -junior"

    ver_id = save_strategy_version(
        conn=db_conn,
        job_id=job_id,
        strategy_name=strat_name,
        changes_summary=summary,
        adjusted_keywords=kw,
        negative_keywords=neg,
        source_priorities={"github": "High", "groq_browser": "High", "local_db": "Medium"},
    )

    return {
        "version_id": ver_id,
        "strategy_name": strat_name,
        "changes_summary": summary,
        "adjusted_keywords": kw,
        "negative_keywords": neg,
        "source_priorities": {"github": "High", "groq_browser": "High", "local_db": "Medium"},
        "preserved_mandatory_skills": reqs.required_skills,
    }
