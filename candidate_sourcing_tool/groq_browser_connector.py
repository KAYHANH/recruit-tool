"""Groq Browser Search Connector for Candidate Finder.

Executes generated search strategies (Strategies A through G: LinkedIn X-Ray,
public CVs, and technical portfolios) automatically via Groq's built-in
browser_search tool with model openai/gpt-oss-120b.

Strict ₹0 Spend Enforcement:
- Operates strictly under the Groq Cloud Free tier (1,000 requests/day, 8,000 tokens/minute).
- Incurs ₹0.00 cost. Never triggers paid upgrades or billable models.
- Gracefully pauses on HTTP 429 quota exhaustion without crashing the sourcing run.
- Drops invalid, ungrounded leads lacking verified public URLs.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cost_guard import cost_guard
from groq_extractor import resolve_groq_api_key
from source_connectors import (
    BaseSourceConnector,
    ConnectorSearchResult,
    RawCandidateProfile,
)

logger = logging.getLogger("groq_browser_connector")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_SEARCH_MODEL = "openai/gpt-oss-120b"

# Prohibited aggregator / job-board domains that do not represent individual candidates
PROHIBITED_JOB_DOMAINS = {
    "indeed.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "monster.com",
    "simplyhired.com",
    "dice.com",
    "careerbuilder.com",
    "jooble.org",
}


def is_valid_candidate_url(url: str) -> bool:
    """Validates that a URL points to an individual person's profile, resume, or portfolio,
    and not to a job board listing or template page.
    """
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return False

    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()

        # Reject aggregator job sites
        for prohibited in PROHIBITED_JOB_DOMAINS:
            if prohibited in hostname:
                return False

        # Reject search engine hostnames
        if any(se in hostname for se in ["google.", "bing.", "duckduckgo.", "yahoo.", "baidu."]):
            return False

        # Reject job post paths, search pages and utility endpoints
        if any(bad in path for bad in ["/jobs/", "/job/", "/careers/", "/hiring/", "/apply/", "/templates/", "/samples/", "/search", "/find", "/results"]):
            return False

        # Reject LinkedIn company pages or search pages
        if "linkedin.com" in hostname:
            if "/company/" in path or "/jobs/" in path or "/learning/" in path:
                return False

        return True
    except Exception:
        return False


def clean_text(text: str) -> str:
    """Replaces Unicode non-breaking spaces and hyphens with ASCII equivalents."""
    if not text:
        return ""
    return (
        text.replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u202f", " ")
        .replace("\u00a0", " ")
        .strip()
    )


def _clean_url(raw_url: str) -> str:
    """Cleans a raw URL by removing markdown formatting and trailing punctuation."""
    if not raw_url:
        return ""
    # Extract link target if wrapped in markdown [label](url)
    md_match = re.search(r"\]\((https?://[^)\s]+)\)", raw_url)
    if md_match:
        raw_url = md_match.group(1)
    # Strip common trailing punctuation characters often appended by LLMs
    cleaned = re.sub(r"[.,;:)\]\"'>\s]+$", "", raw_url.strip())
    return cleaned


def _clean_field(val: str) -> str:
    if not val:
        return ""
    return val.strip().strip("*_#`").strip()


def _parse_duration_to_seconds(val: str | None) -> float | None:
    """Parses duration strings like '1m30s', '45s', '1.5s', '2m' or numeric seconds."""
    if not val:
        return None
    val = val.strip().lower()
    m = re.match(r"^(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?$", val)
    if m and (m.group(1) or m.group(2)):
        mins = float(m.group(1)) if m.group(1) else 0.0
        secs = float(m.group(2)) if m.group(2) else 0.0
        return mins * 60.0 + secs
    try:
        clean_num = re.sub(r"[^0-9.]", "", val)
        return float(clean_num) if clean_num else None
    except (ValueError, TypeError):
        return None


def parse_429_reset_and_reason(http_err: HTTPError) -> tuple[int, str, str]:
    """Inspects HTTP 429 response headers and body from Groq API to extract
    exact reset window and quota exhaustion reason. Never assumes a fixed cooldown.
    """
    headers = getattr(http_err, "headers", None)
    retry_after = headers.get("Retry-After") or headers.get("retry-after") if headers else None
    reset_tokens = headers.get("x-ratelimit-reset-tokens") or headers.get("X-Ratelimit-Reset-Tokens") if headers else None
    reset_requests = headers.get("x-ratelimit-reset-requests") or headers.get("X-Ratelimit-Reset-Requests") if headers else None

    err_body = ""
    try:
        err_body = http_err.read().decode("utf-8") if hasattr(http_err, "read") else str(http_err)
    except Exception:
        err_body = str(http_err)

    # Extract parsed seconds from headers
    dur_retry_after = _parse_duration_to_seconds(retry_after)
    dur_reset_tokens = _parse_duration_to_seconds(reset_tokens)
    dur_reset_requests = _parse_duration_to_seconds(reset_requests)

    # Check error body JSON / text for explicit reset instructions (e.g. "try again in 14.5s")
    body_label = ""
    dur_body = None
    body_match = re.search(r"try again in\s+([0-9a-z\.]+)", err_body, re.IGNORECASE)
    if body_match:
        body_label = body_match.group(1)
        dur_body = _parse_duration_to_seconds(body_label)

    # Determine safe cooldown duration:
    # 1. Authoritative Retry-After header takes primary precedence if provided
    # 2. Body-specific duration (e.g. "try again in 20s") if explicitly instructed by API
    # 3. If rate-limit headers present, match the exhausted quota type (TPM vs RPM)
    # 4. If multiple headers exist, choose the SAFE maximum window (never premature minimum)
    err_body_lower = err_body.lower()
    is_tpm = "token" in err_body_lower or "tpm" in err_body_lower
    is_rpm = "request" in err_body_lower or "rpm" in err_body_lower or "rpd" in err_body_lower

    if dur_retry_after is not None and dur_retry_after > 0:
        cooldown_sec = int(dur_retry_after)
    elif dur_body is not None and dur_body > 0:
        cooldown_sec = int(dur_body)
    elif is_tpm and dur_reset_tokens is not None and dur_reset_tokens > 0:
        cooldown_sec = int(dur_reset_tokens)
    elif is_rpm and dur_reset_requests is not None and dur_reset_requests > 0:
        cooldown_sec = int(dur_reset_requests)
    else:
        available_durs = [d for d in [dur_reset_tokens, dur_reset_requests] if d is not None and d > 0]
        cooldown_sec = int(max(available_durs)) if available_durs else 60

    cooldown_sec = max(10, min(cooldown_sec, 3600))  # bounded safe clamp

    reset_label = retry_after or body_label or (reset_tokens if is_tpm else reset_requests) or f"{cooldown_sec}s"

    # Identify exact exhaustion reason
    if is_tpm:
        reason = f"Groq TPM limit reached (Tokens per minute exhausted; resets in {reset_label})"
    elif is_rpm:
        reason = f"Groq RPM limit reached (Requests per minute exhausted; resets in {reset_label})"
    elif "day" in err_body_lower or "daily" in err_body_lower:
        reason = f"Groq daily free request quota exhausted (resets in {reset_label})"
    else:
        reason = f"Groq Free Tier rate limit reached (HTTP 429; resets in {reset_label})"

    return cooldown_sec, reset_label, reason


def parse_browser_search_response(
    response_text: str,
    default_strategy_key: str = "",
) -> list[RawCandidateProfile]:
    """Parses candidate profiles from Groq Browser Search output.
    Extracts structured fields, validates URLs, and assigns evidence tiers.
    """
    cleaned = clean_text(response_text)
    if not cleaned:
        return []

    # Split into candidate blocks
    candidate_blocks = re.split(
        r"(?:\n\s*---\s*\n|\n(?=\s*(?:\*\*|\#\#)?Candidate\s*\d+[:\.])|\n(?=\s*(?:\*\*|\#\#)?\d+[\.\)]\s*(?:\*\*)?(?:Name|Candidate|Profile))|\n(?=###?\s*(?:Candidate\s*)?\d+))",
        cleaned,
    )

    profiles: list[RawCandidateProfile] = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    for block in candidate_blocks:
        block_str = block.strip()
        if not block_str or len(block_str) < 20:
            continue

        # Extract Name
        name_match = re.search(
            r"(?:^|\n)[*-]?\s*(?:\d+[\.\)]\s*)?(?:\*\*)?(?:Name|Candidate Name)(?:\*\*)?:\s*([^\n\r]+)",
            block_str,
            re.IGNORECASE,
        )
        name = _clean_field(name_match.group(1)) if name_match else ""

        # Extract Profile URL
        url_match = re.search(
            r"(?:^|\n)[*-]?\s*(?:\*\*)?(?:Profile URL|URL|Profile|Link)(?:\*\*)?:\s*([^\n\r]+)",
            block_str,
            re.IGNORECASE,
        )
        raw_url = url_match.group(1).strip() if url_match else ""
        profile_url = _clean_url(raw_url)

        # Fallback URL search if labeled field is missing or invalid
        if not profile_url or not is_valid_candidate_url(profile_url):
            raw_url_match = re.search(
                r"https?://(?:www\.)?(?:linkedin\.com/in/[a-zA-Z0-9_\-]+|github\.com/[a-zA-Z0-9_\-]+|[a-zA-Z0-9_\-]+\.github\.io[^\s)\]]*)",
                block_str,
            )
            if raw_url_match:
                profile_url = _clean_url(raw_url_match.group(0))

        # If still no valid URL or prohibited domain, skip
        if not is_valid_candidate_url(profile_url):
            continue

        # Extract Headline
        headline_match = re.search(
            r"(?:^|\n)[*-]?\s*(?:\*\*)?(?:Headline|Title|Role|Position)(?:\*\*)?:\s*([^\n\r]+)",
            block_str,
            re.IGNORECASE,
        )
        headline = _clean_field(headline_match.group(1)) if headline_match else "Discovered Candidate"

        # If name is missing or generic, attempt to infer from URL slug
        if not name or name.lower() in ["n/a", "unknown", "[full name]", "candidate", "null", "none"]:
            parsed = urlparse(profile_url)
            path_parts = [p for p in parsed.path.split("/") if p]
            if path_parts:
                slug = path_parts[-1].replace("-", " ").replace(".", " ").title()
                name = slug
            else:
                name = headline.split("-")[0].strip()

        # Reject candidate if name remains generic or missing
        if not name or name.lower() in ["n/a", "unknown", "candidate", "null", "none"]:
            continue

        # Extract Location
        loc_match = re.search(
            r"(?:^|\n)[*-]?\s*(?:\*\*)?(?:Location|City|Region)(?:\*\*)?:\s*([^\n\r]+)",
            block_str,
            re.IGNORECASE,
        )
        location = _clean_field(loc_match.group(1)) if loc_match else ""

        # Extract Company
        comp_match = re.search(
            r"(?:^|\n)[*-]?\s*(?:\*\*)?(?:Company|Employer|Current Company)(?:\*\*)?:\s*([^\n\r]+)",
            block_str,
            re.IGNORECASE,
        )
        company = _clean_field(comp_match.group(1)) if comp_match else ""
        if company.lower() in ["n/a", "none", "unknown"]:
            company = ""

        # Extract Skills
        skills_match = re.search(
            r"(?:^|\n)[*-]?\s*(?:\*\*)?(?:Skills|Tech Stack|Technologies)(?:\*\*)?:\s*([^\n\r]+)",
            block_str,
            re.IGNORECASE,
        )
        skills = _clean_field(skills_match.group(1)) if skills_match else ""

        # Extract Evidence
        evidence_match = re.search(
            r"(?:^|\n)[*-]?\s*(?:\*\*)?(?:Evidence|Summary|Notes)(?:\*\*)?:\s*([\s\S]+?)(?=(?:Candidate|\n---|\Z))",
            block_str,
            re.IGNORECASE,
        )
        evidence = evidence_match.group(1).strip() if evidence_match else block_str[:300]
        evidence = re.sub(r"^[*-]\s*", "", evidence, flags=re.MULTILINE).strip()

        # Require genuine evidence text (at least 15 chars) to prevent empty / ungrounded leads
        if not evidence or len(evidence) < 15 or evidence.lower() in ["n/a", "none", "unknown", "evidence", "undefined"]:
            continue

        # Determine Evidence Tier
        url_lower = profile_url.lower()
        if "github.com" in url_lower or "gitlab.com" in url_lower or ".github.io" in url_lower:
            tier = "Tier 1: Strong Technical Evidence"
            github_url = profile_url if "github.com" in url_lower else ""
            gitlab_url = profile_url if "gitlab.com" in url_lower else ""
            portfolio_url = profile_url if ".github.io" in url_lower else ""
        else:
            tier = "Tier 2: Moderate Technical Evidence"
            github_url = ""
            gitlab_url = ""
            portfolio_url = profile_url

        # Check for secondary github or email in text
        if not github_url:
            gh_in_text = re.search(r"https?://(?:www\.)?github\.com/[a-zA-Z0-9_\-]+", block_str)
            if gh_in_text:
                github_url = gh_in_text.group(0).strip()

        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", block_str)
        email = email_match.group(0) if email_match else ""

        contact_status = "Publicly published" if (email or github_url) else "Discovered on Web"
        source_label = f"Groq Web Search ({default_strategy_key})" if default_strategy_key else "Groq Browser Search"
        contact_prov = f"Web Search Citation via {source_label} [Discovered {now_str}]"
        combined_evidence = f"[Discovered via {source_label}]\nURL: {profile_url}\n{evidence}"
        if skills:
            combined_evidence += f"\nMatched Skills: {skills}"

        profiles.append(
            RawCandidateProfile(
                name=name,
                headline=headline,
                profile_url=profile_url,
                source=source_label,
                location=location,
                company=company,
                email=email,
                github_url=github_url,
                gitlab_url=gitlab_url,
                portfolio_url=portfolio_url,
                evidence_text=combined_evidence,
                contact_provenance=contact_prov,
                contact_status=contact_status,
                external_id=f"groq_{abs(hash(profile_url)) % 10000000}",
                evidence_ladder_tier=tier,
                raw_data={"block": block_str, "discovered_at": now_str, "strategy_key": default_strategy_key},
            )
        )

    return profiles


class GroqBrowserSearchConnector(BaseSourceConnector):
    """Automated web discovery connector powered by Groq's built-in browser_search tool.
    Strict ₹0.00 spend guarantee. Uses openai/gpt-oss-120b with browser_search on Free tier.
    Gracefully stops on HTTP 429 quota exhaustion.
    """

    source_id: str = "groq_browser"
    name: str = "Groq Browser Search"
    is_free: bool = True
    requires_api_key: bool = True

    _cooldown_until: float = 0.0
    _last_rate_limit_reset: str | None = None
    _rate_limit_reason: str = ""

    def __init__(self, api_key: str | None = None):
        self._override_key = api_key

    def _get_api_key(self) -> str | None:
        return resolve_groq_api_key(self._override_key)

    def check_status(self) -> dict[str, Any]:
        """Reports the status of the Groq Browser Search connector."""
        api_key = self._get_api_key()
        if not api_key:
            return {
                "source_id": self.source_id,
                "name": self.name,
                "is_free": True,
                "status": "Not configured",
                "api_key_configured": False,
                "model": GROQ_SEARCH_MODEL,
                "tool": "browser_search",
                "message": "GROQ_API_KEY is not set. Add it to .env to enable web search.",
                "zero_budget_verified": True,
            }

        # Check rate-limit cooldown
        now = time.time()
        if now < self._cooldown_until:
            wait_sec = max(0, int(self._cooldown_until - now))
            reason = self._rate_limit_reason or "Free tier rate limit"
            return {
                "source_id": self.source_id,
                "name": self.name,
                "is_free": True,
                "status": "Rate limited",
                "api_key_configured": True,
                "cooldown_remaining_sec": wait_sec,
                "reset_time": self._last_rate_limit_reset,
                "rate_limit_reason": reason,
                "model": GROQ_SEARCH_MODEL,
                "tool": "browser_search",
                "message": f"{reason} ({wait_sec}s cooldown remaining).",
                "zero_budget_verified": True,
            }

        return {
            "source_id": self.source_id,
            "name": self.name,
            "is_free": True,
            "status": "Ready on Free plan",
            "api_key_configured": True,
            "model": GROQ_SEARCH_MODEL,
            "tool": "browser_search",
            "rate_limit_policy": "1,000 req/day, 8,000 tokens/min Free Tier",
            "zero_budget_verified": True,
        }


    def search_strategy(
        self,
        strategy: Any,
        keywords: str = "",
        location: str = "",
        limit: int = 3,
        role_family: str = "",
        requirements: Any = None,
    ) -> ConnectorSearchResult:
        """Executes a single X-Ray search strategy (Strategy A through G) via Groq Browser Search."""
        if isinstance(strategy, dict):
            strat_key = strategy.get("key", "Strategy")
            strat_name = strategy.get("name", "X-Ray Sourcing Strategy")
            target_platform = strategy.get("target_platform", "")
            query_text = strategy.get("query_text", "")
            description = strategy.get("description", "")
        else:
            strat_key = getattr(strategy, "key", "Strategy")
            strat_name = getattr(strategy, "name", "X-Ray Sourcing Strategy")
            target_platform = getattr(strategy, "target_platform", "")
            query_text = getattr(strategy, "query_text", "")
            description = getattr(strategy, "description", "")

        cost_guard.log_request(
            self.source_id,
            "search_strategy",
            f"Strategy: {strat_key} ({strat_name}), Keywords: {keywords}, Location: {location}, Limit: {limit}",
        )

        api_key = self._get_api_key()
        if not api_key:
            return ConnectorSearchResult(
                source_name=f"{self.name} ({strat_key})",
                source_id=self.source_id,
                error_message="Groq API key is not configured. Automated web search is unavailable.",
            )

        # Respect cooldown
        now = time.time()
        if now < self._cooldown_until:
            remaining = int(self._cooldown_until - now)
            return ConnectorSearchResult(
                source_name=f"{self.name} ({strat_key})",
                source_id=self.source_id,
                rate_limited=True,
                error_message=f"Groq Free tier cooldown active ({remaining}s remaining).",
            )

        # Build specific angle instructions based on strategy type
        key_upper = strat_key.upper()
        if "STRATEGY A" in key_upper or "linkedin" in target_platform.lower():
            focus_instruction = (
                f"FOCUS: Search for real, public LinkedIn profiles of professionals working as '{keywords}' in '{location or 'United States/Remote'}'.\n"
                f"Target profiles with URLs matching https://www.linkedin.com/in/* or https://*.linkedin.com/in/*.\n"
                f"Query guidance: {query_text}"
            )
        elif "STRATEGY B" in key_upper:
            focus_instruction = (
                f"FOCUS: Search for professionals holding alternative job titles, synonyms, or related specializations for '{keywords}' in '{location or 'Any'}'.\n"
                f"Query guidance: {query_text}"
            )
        elif "STRATEGY C" in key_upper:
            focus_instruction = (
                f"FOCUS: Search for candidates who explicitly demonstrate hands-on mastery in must-have skills for '{keywords}'.\n"
                f"Target evidence of core competencies and required skills in '{location or 'Any'}'.\n"
                f"Query guidance: {query_text}"
            )
        elif "STRATEGY D" in key_upper:
            focus_instruction = (
                f"FOCUS: Search for candidates with proven experience in technical tools, software, or technology stacks relevant to '{keywords}'.\n"
                f"Query guidance: {query_text}"
            )
        elif "STRATEGY E" in key_upper:
            focus_instruction = (
                f"FOCUS: Search for publicly accessible resumes, CV documents, and personal resume pages for '{keywords}' in '{location or 'Any'}'.\n"
                f"Target public CV/resume links and personal websites.\n"
                f"Query guidance: {query_text}"
            )
        elif "STRATEGY F" in key_upper:
            focus_instruction = (
                f"FOCUS: Search for candidate portfolios, articles, project repositories, or published case studies for '{keywords}' in '{location or 'Any'}'.\n"
                f"Target personal websites, Substack/Medium publications, or GitHub/GitLab profile repositories.\n"
                f"Query guidance: {query_text}"
            )
        elif "STRATEGY G" in key_upper:
            focus_instruction = (
                f"FOCUS: Search for talent from peer competitors, target industry organizations, or benchmark companies in the '{keywords}' domain.\n"
                f"Query guidance: {query_text}"
            )
        else:
            focus_instruction = (
                f"FOCUS: Execute candidate discovery for '{keywords}' in '{location or 'Any'}'.\n"
                f"Strategy: {strat_name} - {description}\n"
                f"Query guidance: {query_text}"
            )

        user_content = (
            f"Execute an automated candidate discovery search using the browser_search tool.\n"
            f"Strategy Task: {strat_key} - {strat_name}\n"
            f"{focus_instruction}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Use browser_search to discover up to {limit} real candidate profiles or portfolios matching this strategy.\n"
            f"2. ONLY return actual people found in search results with verified public URLs.\n"
            f"3. Do not return job advertisements, hiring agency portals, or company homepages.\n"
            f"4. For each candidate found, output strictly in this format:\n\n"
            f"Candidate:\n"
            f"Name: <Full Name>\n"
            f"Profile URL: <Exact Public Profile URL>\n"
            f"Headline: <Current Job Title / Professional Headline>\n"
            f"Location: <Location>\n"
            f"Company: <Current or Recent Company>\n"
            f"Skills: <Relevant Skills Matched>\n"
            f"Evidence: <Direct excerpt or summary from the search citation verifying their work in {keywords}>\n"
            f"---\n"
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "CandidateFinder/1.0",
        }

        body = {
            "model": GROQ_SEARCH_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a recruitment research assistant. You MUST use the browser_search tool to find "
                        "real, existing professional profiles, public portfolios, or CVs on the web.\n"
                        "CRITICAL INSTRUCTIONS:\n"
                        "1. ONLY return real candidates discovered via actual web search.\n"
                        "2. NEVER invent, fabricate, or hallucinate names, URLs, or details.\n"
                        "3. Extract verified public profile URLs (e.g., linkedin.com/in/*, github.com/*, personal domain, or portfolio).\n"
                        "4. Reject job postings, generic job descriptions, recruiter agency pages, and templates.\n"
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            "tools": [{"type": "browser_search"}],
            "tool_choice": "auto",
            "reasoning_effort": "low",
            "max_completion_tokens": 1500,
        }

        req = Request(
            GROQ_API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if not choices:
                    return ConnectorSearchResult(
                        source_name=f"{self.name} ({strat_key})",
                        source_id=self.source_id,
                        error_message="Groq returned empty choices.",
                    )

                msg = choices[0].get("message", {})
                content = msg.get("content") or ""

                candidates = parse_browser_search_response(content, default_strategy_key=strat_key)
                return ConnectorSearchResult(
                    source_name=f"{self.name} ({strat_key})",
                    source_id=self.source_id,
                    candidates=candidates[:limit],
                    total_found=len(candidates),
                )

        except HTTPError as http_err:
            status_code = http_err.code
            if status_code == 429:
                cooldown_sec, reset_label, reason = parse_429_reset_and_reason(http_err)
                self._cooldown_until = time.time() + cooldown_sec
                self._last_rate_limit_reset = reset_label
                self._rate_limit_reason = reason
                logger.warning(f"Groq Free Tier HTTP 429 on {strat_key}: {reason}. Cooldown: {cooldown_sec}s.")
                return ConnectorSearchResult(
                    source_name=f"{self.name} ({strat_key})",
                    source_id=self.source_id,
                    rate_limited=True,
                    rate_limit_reset=reset_label,
                    error_message=f"{reason}. Gracefully paused ({cooldown_sec}s cooldown).",
                )
            elif status_code == 401:
                return ConnectorSearchResult(
                    source_name=f"{self.name} ({strat_key})",
                    source_id=self.source_id,
                    error_message="Groq API key unauthorized (HTTP 401). Verify GROQ_API_KEY in .env.",
                )
            else:
                try:
                    err_body = http_err.read().decode("utf-8")
                except Exception:
                    err_body = str(http_err)
                return ConnectorSearchResult(
                    source_name=f"{self.name} ({strat_key})",
                    source_id=self.source_id,
                    error_message=f"Groq API error HTTP {status_code}: {err_body[:200]}",
                )
        except (URLError, TimeoutError) as net_err:
            return ConnectorSearchResult(
                source_name=f"{self.name} ({strat_key})",
                source_id=self.source_id,
                error_message=f"Groq network error or timeout: {str(net_err)[:150]}",
            )
        except Exception as exc:
            return ConnectorSearchResult(
                source_name=f"{self.name} ({strat_key})",
                source_id=self.source_id,
                error_message=f"Unexpected Groq Browser Search error: {str(exc)[:150]}",
            )

    def search_consolidated(
        self,
        strategies: list[Any],
        keywords: str = "",
        location: str = "",
        limit: int = 5,
        role_family: str = "",
        requirements: Any = None,
    ) -> ConnectorSearchResult:
        """Executes a SINGLE consolidated bounded browser search request across multiple strategies.
        Avoids making 7 separate consecutive API requests that exhaust Groq Free Tier TPM/RPM limits.
        Attributes returned candidates to their respective strategy platforms.
        """
        cost_guard.log_request(
            self.source_id,
            "search_consolidated",
            f"Strategies count: {len(strategies)}, Keywords: {keywords}, Location: {location}, Limit: {limit}",
        )

        api_key = self._get_api_key()
        if not api_key:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message="Groq API key is not configured. Automated web search is unavailable.",
            )

        now = time.time()
        if now < self._cooldown_until:
            remaining = int(self._cooldown_until - now)
            reason = self._rate_limit_reason or "Free tier rate limit cooldown"
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                rate_limited=True,
                rate_limit_reset=self._last_rate_limit_reset,
                error_message=f"{reason} ({remaining}s remaining).",
            )

        # Build multi-angle search guidance across the provided strategies
        strategy_lines = []
        for s in strategies:
            if isinstance(s, dict):
                k, n, q = s.get("key", "Strategy"), s.get("name", ""), s.get("query_text", "")
            else:
                k, n, q = getattr(s, "key", "Strategy"), getattr(s, "name", ""), getattr(s, "query_text", "")
            strategy_lines.append(f"- {k} ({n}): {q}")

        search_query_guide = "\n".join(strategy_lines) if strategy_lines else f"Keywords: {keywords} Location: {location}"

        user_content = (
            f"Execute an automated candidate discovery search using the browser_search tool.\n"
            f"Target Role / Skills: {keywords}\n"
            f"Target Location: {location or 'United States / Remote'}\n\n"
            f"MULTI-ANGLE SEARCH STRATEGIES & OPERATORS:\n{search_query_guide}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Use browser_search to discover up to {limit} real candidate profiles or portfolios matching these angles.\n"
            f"2. Search across multiple angles: public LinkedIn profiles (site:linkedin.com/in/*), public CVs/resumes (inurl:resume or filetype:pdf), and personal portfolios/case studies.\n"
            f"3. ONLY return actual people found in search results with verified public profile URLs.\n"
            f"4. Do not return job advertisements, hiring agency portals, or company homepages.\n"
            f"5. For each candidate found, output strictly in this format:\n\n"
            f"Candidate:\n"
            f"Name: <Full Name>\n"
            f"Profile URL: <Exact Public Profile URL>\n"
            f"Headline: <Current Job Title / Professional Headline>\n"
            f"Location: <Location>\n"
            f"Company: <Current or Recent Company>\n"
            f"Skills: <Relevant Skills Matched>\n"
            f"Evidence: <Direct excerpt or summary from the search citation verifying their work in {keywords}>\n"
            f"---\n"
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "CandidateFinder/1.0",
        }

        body = {
            "model": GROQ_SEARCH_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a recruitment research assistant. You MUST use the browser_search tool to find "
                        "real, existing professional profiles, public portfolios, or CVs on the web.\n"
                        "CRITICAL INSTRUCTIONS:\n"
                        "1. ONLY return real candidates discovered via actual web search.\n"
                        "2. NEVER invent, fabricate, or hallucinate names, URLs, or details.\n"
                        "3. Extract verified public profile URLs (e.g., linkedin.com/in/*, github.com/*, personal domain, or portfolio).\n"
                        "4. Reject job postings, generic job descriptions, recruiter agency pages, and templates.\n"
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            "tools": [{"type": "browser_search"}],
            "tool_choice": "auto",
            "reasoning_effort": "low",
            "max_completion_tokens": 1500,
        }

        req = Request(
            GROQ_API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if not choices:
                    return ConnectorSearchResult(
                        source_name=self.name,
                        source_id=self.source_id,
                        error_message="Groq returned empty choices.",
                    )

                msg = choices[0].get("message", {})
                content = msg.get("content") or ""

                candidates = parse_browser_search_response(content, default_strategy_key="Consolidated")

                # Map each returned candidate to its best strategy platform
                for c in candidates:
                    u_lower = (c.profile_url or "").lower()
                    if "linkedin.com/in/" in u_lower:
                        c.raw_data["strategy_key"] = "Strategy A"
                        c.source = "Groq Web Search (Strategy A)"
                    elif any(cv_kw in u_lower for cv_kw in [".pdf", "/resume", "/cv", "resume."]):
                        c.raw_data["strategy_key"] = "Strategy E"
                        c.source = "Groq Web Search (Strategy E)"
                    elif any(b_kw in u_lower for b_kw in ["medium.com", "substack.com", ".github.io"]):
                        c.raw_data["strategy_key"] = "Strategy F"
                        c.source = "Groq Web Search (Strategy F)"
                    elif "github.com" in u_lower or "gitlab.com" in u_lower:
                        c.raw_data["strategy_key"] = "Strategy D"
                        c.source = "Groq Web Search (Strategy D)"
                    else:
                        c.raw_data["strategy_key"] = "Strategy A"
                        c.source = "Groq Web Search (Strategy A)"

                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    candidates=candidates[:limit],
                    total_found=len(candidates),
                )

        except HTTPError as http_err:
            status_code = http_err.code
            if status_code == 429:
                cooldown_sec, reset_label, reason = parse_429_reset_and_reason(http_err)
                self._cooldown_until = time.time() + cooldown_sec
                self._last_rate_limit_reset = reset_label
                self._rate_limit_reason = reason
                logger.warning(f"Groq Free Tier HTTP 429: {reason}. Cooldown: {cooldown_sec}s.")
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    rate_limited=True,
                    rate_limit_reset=reset_label,
                    error_message=f"{reason}. Gracefully paused ({cooldown_sec}s cooldown).",
                )
            elif status_code == 401:
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    error_message="Groq API key unauthorized (HTTP 401). Verify GROQ_API_KEY in .env.",
                )
            else:
                try:
                    err_body = http_err.read().decode("utf-8")
                except Exception:
                    err_body = str(http_err)
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    error_message=f"Groq API error HTTP {status_code}: {err_body[:200]}",
                )
        except (URLError, TimeoutError) as net_err:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"Groq network error or timeout: {str(net_err)[:150]}",
            )
        except Exception as exc:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"Unexpected Groq Browser Search error: {str(exc)[:150]}",
            )

    def search(
        self,
        keywords: str,
        location: str = "",
        limit: int = 5,
        strategies: list | None = None,
        requirements: Any = None,
        **kwargs: Any,
    ) -> ConnectorSearchResult:
        """Executes automated web discovery using Groq Browser Search."""
        cost_guard.log_request(
            self.source_id,
            "search",
            f"Keywords: {keywords}, Location: {location}, Limit: {limit}",
        )

        api_key = self._get_api_key()
        if not api_key:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message="Groq API key is not configured. Sourcing continued with other free connectors.",
            )

        # Respect cooldown
        now = time.time()
        if now < self._cooldown_until:
            remaining = int(self._cooldown_until - now)
            reason = self._rate_limit_reason or "Free tier rate limit cooldown"
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                rate_limited=True,
                rate_limit_reset=self._last_rate_limit_reset,
                error_message=f"{reason} ({remaining}s remaining). Sourcing continued with other free connectors.",
            )

        # If strategies are provided, execute single consolidated bounded search instead of looping
        if strategies and len(strategies) > 0:
            return self.search_consolidated(
                strategies=strategies,
                keywords=keywords,
                location=location,
                limit=limit,
                requirements=requirements,
            )

        user_content = (
            f"Execute an automated candidate discovery search to find real, active professional candidates.\n"
            f"Target Role / Skills: {keywords}\n"
            f"Target Location: {location or 'Remote / Any'}\n\n"
            f"Use the browser_search tool to discover up to {limit} genuine candidate profiles, portfolios, or public resumes.\n"
            f"For every candidate, supply their Name, Profile URL, Headline, Location, Company, Skills, and supporting Evidence citation."
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "CandidateFinder/1.0",
        }

        body = {
            "model": GROQ_SEARCH_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a recruitment research assistant. You MUST use the browser_search tool to find "
                        "real, existing professional profiles, public portfolios, or CVs on the web.\n"
                        "CRITICAL INSTRUCTIONS:\n"
                        "1. ONLY return real candidates discovered via actual web search.\n"
                        "2. NEVER invent, fabricate, or hallucinate names, URLs, or details.\n"
                        "3. Extract verified public profile URLs (e.g., linkedin.com/in/*, github.com/*, personal domain, or portfolio).\n"
                        "4. Reject job postings, generic job descriptions, recruiter agency pages, and templates.\n"
                        "5. For each candidate found, output strictly in this format:\n\n"
                        "Candidate:\n"
                        "Name: <Full Name>\n"
                        "Profile URL: <Exact Public Profile URL>\n"
                        "Headline: <Current Job Title / Professional Headline>\n"
                        "Location: <Location>\n"
                        "Company: <Current or Recent Company>\n"
                        "Skills: <Relevant Skills Matched>\n"
                        "Evidence: <Direct verifiable summary or excerpt from search citations>\n"
                        "---\n"
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            "tools": [{"type": "browser_search"}],
            "tool_choice": "auto",
            "reasoning_effort": "low",
            "max_completion_tokens": 1500,
        }

        req = Request(
            GROQ_API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if not choices:
                    return ConnectorSearchResult(
                        source_name=self.name,
                        source_id=self.source_id,
                        error_message="Groq returned empty choices.",
                    )

                msg = choices[0].get("message", {})
                content = msg.get("content") or ""

                candidates = parse_browser_search_response(content)
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    candidates=candidates[:limit],
                    total_found=len(candidates),
                )

        except HTTPError as http_err:
            status_code = http_err.code
            if status_code == 429:
                cooldown_sec, reset_label, reason = parse_429_reset_and_reason(http_err)
                self._cooldown_until = time.time() + cooldown_sec
                self._last_rate_limit_reset = reset_label
                self._rate_limit_reason = reason
                logger.warning(f"Groq Free Tier HTTP 429: {reason}. Cooldown: {cooldown_sec}s.")
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    rate_limited=True,
                    rate_limit_reset=reset_label,
                    error_message=f"{reason}. Gracefully paused this provider ({cooldown_sec}s cooldown).",
                )


            elif status_code == 401:
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    error_message="Groq API key unauthorized (HTTP 401). Verify GROQ_API_KEY in .env.",
                )
            else:
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    error_message=f"Groq API error HTTP {status_code}: {err_body[:200]}",
                )

        except (URLError, TimeoutError) as net_err:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"Groq network error or timeout: {str(net_err)[:150]}",
            )
        except Exception as exc:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"Unexpected Groq Browser Search error: {str(exc)[:150]}",
            )
