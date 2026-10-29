from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode, urlparse
from urllib.request import Request, urlopen


@dataclass
class SearchResultItem:
    title: str
    url: str
    snippet: str
    source_provider: str = "Local"


@dataclass
class SearchProviderResult:
    provider_name: str
    items: list[SearchResultItem] = field(default_factory=list)
    total_results: int = 0
    is_fallback: bool = False
    error_message: str | None = None
    quota_exhausted: bool = False


class BaseSearchProvider:
    """Base class for search providers."""

    name: str = "Base"

    def search(self, query: str, num_results: int = 10) -> SearchProviderResult:
        raise NotImplementedError


class LocalFallbackProvider(BaseSearchProvider):
    """Default zero-budget local provider.
    Never makes external network calls.
    Directs users to open the search directly in their own browser.
    """

    name: str = "Local (Browser Link Mode)"

    def search(self, query: str, num_results: int = 10) -> SearchProviderResult:
        clean_q = query.strip()
        google_url = "https://www.google.com/search?q=" + quote_plus(clean_q)
        return SearchProviderResult(
            provider_name=self.name,
            items=[
                SearchResultItem(
                    title=f"Explore query in browser: {clean_q[:60]}...",
                    url=google_url,
                    snippet="Click to launch this search directly in your browser. All profile reviewing and saving is done manually by you.",
                    source_provider="Local",
                )
            ],
            total_results=1,
            is_fallback=True,
            error_message=None,
            quota_exhausted=False,
        )


class GoogleCseProvider(BaseSearchProvider):
    """Optional Google Custom Search JSON API provider.
    Requires GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX.
    Handles quota limits (429/403) cleanly and never bypasses access controls.
    """

    name: str = "Google Custom Search JSON API"

    def __init__(self, api_key: str, cx: str):
        self.api_key = api_key.strip()
        self.cx = cx.strip()

    def search(self, query: str, num_results: int = 10) -> SearchProviderResult:
        if not self.api_key or not self.cx:
            return SearchProviderResult(
                provider_name=self.name,
                is_fallback=True,
                error_message="Google CSE API Key or Search Engine ID (CX) is missing. Using local query mode.",
            )

        params = {
            "key": self.api_key,
            "cx": self.cx,
            "q": query.strip(),
            "num": min(10, max(1, num_results)),
        }
        url = f"https://www.googleapis.com/customsearch/v1?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "CandidateFinder-PersonalMVP/1.0"})

        try:
            with urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
                items = []
                for item in payload.get("items", []):
                    items.append(
                        SearchResultItem(
                            title=item.get("title", "No Title"),
                            url=item.get("link", ""),
                            snippet=item.get("snippet", ""),
                            source_provider=self.name,
                        )
                    )
                total = int(payload.get("searchInformation", {}).get("totalResults", len(items)))
                return SearchProviderResult(
                    provider_name=self.name,
                    items=items,
                    total_results=total,
                    is_fallback=False,
                )
        except HTTPError as exc:
            if exc.code in (429, 403):
                return SearchProviderResult(
                    provider_name=self.name,
                    is_fallback=True,
                    quota_exhausted=True,
                    error_message=f"Google CSE quota exceeded or access forbidden (HTTP {exc.code}). Gracefully falling back to local browser mode.",
                )
            return SearchProviderResult(
                provider_name=self.name,
                is_fallback=True,
                error_message=f"Google CSE error (HTTP {exc.code}): {exc.reason}. Local query generation remains functional.",
            )
        except (URLError, TimeoutError) as exc:
            return SearchProviderResult(
                provider_name=self.name,
                is_fallback=True,
                error_message=f"Network connection failed: {exc}. Local mode is active.",
            )
        except Exception as exc:
            return SearchProviderResult(
                provider_name=self.name,
                is_fallback=True,
                error_message=f"Unexpected error querying provider: {exc}.",
            )


class SerpApiProvider(BaseSearchProvider):
    """Optional SerpApi search provider.
    Requires SERPAPI_API_KEY.
    """

    name: str = "SerpApi"

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def search(self, query: str, num_results: int = 10) -> SearchProviderResult:
        if not self.api_key:
            return SearchProviderResult(
                provider_name=self.name,
                is_fallback=True,
                error_message="SerpApi API Key is unconfigured. Using local query mode.",
            )

        params = {
            "api_key": self.api_key,
            "engine": "google",
            "q": query.strip(),
            "num": min(10, max(1, num_results)),
        }
        url = f"https://serpapi.com/search.json?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "CandidateFinder-PersonalMVP/1.0"})

        try:
            with urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
                items = []
                for res in payload.get("organic_results", []):
                    items.append(
                        SearchResultItem(
                            title=res.get("title", "No Title"),
                            url=res.get("link", ""),
                            snippet=res.get("snippet", ""),
                            source_provider=self.name,
                        )
                    )
                return SearchProviderResult(
                    provider_name=self.name,
                    items=items,
                    total_results=len(items),
                    is_fallback=False,
                )
        except HTTPError as exc:
            if exc.code == 429:
                return SearchProviderResult(
                    provider_name=self.name,
                    is_fallback=True,
                    quota_exhausted=True,
                    error_message=f"SerpApi monthly quota exhausted (HTTP 429). Falling back to local browser mode.",
                )
            return SearchProviderResult(
                provider_name=self.name,
                is_fallback=True,
                error_message=f"SerpApi error (HTTP {exc.code}): {exc.reason}.",
            )
        except Exception as exc:
            return SearchProviderResult(
                provider_name=self.name,
                is_fallback=True,
                error_message=f"SerpApi query error: {exc}.",
            )


@dataclass
class GitHubCandidateResult:
    candidates: list[dict] = field(default_factory=list)
    total_found: int = 0
    rate_limited: bool = False
    rate_limit_remaining: int | None = None
    rate_limit_reset: str | None = None
    message: str = ""


class GitHubSearchProvider(BaseSearchProvider):
    """Zero-budget official public GitHub API candidate sourcing provider.
    - Zero cost ($0 / ₹0). No paid plans, no billing information required.
    - Uses official public endpoints: https://api.github.com/search/users and https://api.github.com/users/{username}.
    - Unauthenticated by default (60 requests/hr core, 10 searches/min).
    - Supports optional free personal token via GITHUB_TOKEN environment variable.
    - Strictly stops when rate-limited; never loops, bypasses, or abuses limits.
    - Collects public profile information and contact details only when publicly provided.
    - Missing email/phone are kept blank and labeled 'Not found'.
    """

    name: str = "GitHub Public API (Zero Cost)"

    def __init__(self, token: str | None = None):
        self.token = (token or os.getenv("GITHUB_TOKEN", "")).strip()

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": "CandidateFinder-PersonalMVP/1.0",
            "Accept": "application/vnd.github.v3+json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def check_rate_limit(self) -> dict:
        """Inspects current GitHub API rate limits."""
        url = "https://api.github.com/rate_limit"
        req = Request(url, headers=self._get_headers())
        try:
            with urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                core = data.get("resources", {}).get("core", {})
                search = data.get("resources", {}).get("search", {})
                return {
                    "success": True,
                    "core_limit": core.get("limit", 60),
                    "core_remaining": core.get("remaining", 0),
                    "core_reset": datetime.fromtimestamp(core.get("reset", 0)).strftime("%H:%M:%S") if core.get("reset") else "Unknown",
                    "search_limit": search.get("limit", 10),
                    "search_remaining": search.get("remaining", 0),
                    "search_reset": datetime.fromtimestamp(search.get("reset", 0)).strftime("%H:%M:%S") if search.get("reset") else "Unknown",
                    "authenticated": bool(self.token),
                }
        except HTTPError as exc:
            return {
                "success": False,
                "error": f"HTTP {exc.code}: {exc.reason}",
                "authenticated": bool(self.token),
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "authenticated": bool(self.token),
            }

    def search_candidates(
        self,
        keywords: str,
        location: str = "",
        num_results: int = 5,
    ) -> GitHubCandidateResult:
        """Searches GitHub for developer profiles matching role keywords and optional location.
        Respects rate limits and stops cleanly if throttled.
        """
        clean_kw = keywords.strip()
        if not clean_kw:
            return GitHubCandidateResult(message="No keywords provided for GitHub search.")

        # Construct query: e.g. "machine learning location:London type:user"
        q_parts = [clean_kw]
        if location and location.strip():
            first_loc = location.split(",")[0].split(";")[0].strip()
            if first_loc.lower() not in {"remote", "global", "worldwide", "anywhere"}:
                q_parts.append(f'location:"{first_loc}"')
        q_parts.append("type:user")
        query_str = " ".join(q_parts)

        params = {
            "q": query_str,
            "per_page": min(10, max(1, num_results)),
        }
        search_url = f"https://api.github.com/search/users?{urlencode(params)}"
        req = Request(search_url, headers=self._get_headers())

        try:
            with urlopen(req, timeout=10) as resp:
                resp_headers = resp.headers
                remaining = int(resp_headers.get("X-RateLimit-Remaining", 1))
                reset_ts = resp_headers.get("X-RateLimit-Reset")
                reset_time_str = datetime.fromtimestamp(int(reset_ts)).strftime("%H:%M:%S") if reset_ts else "soon"

                payload = json.loads(resp.read().decode("utf-8"))
                total_found = payload.get("total_count", 0)
                items = payload.get("items", [])

        except HTTPError as exc:
            if exc.code in (403, 429):
                reset_ts = exc.headers.get("X-RateLimit-Reset") if exc.headers else None
                reset_str = datetime.fromtimestamp(int(reset_ts)).strftime("%H:%M:%S") if reset_ts else "after cooldown"
                return GitHubCandidateResult(
                    rate_limited=True,
                    message=f"GitHub API search rate limit reached (HTTP {exc.code}). Resets at {reset_str}. Stopped gracefully. Manual browser links remain fully usable.",
                )
            return GitHubCandidateResult(
                message=f"GitHub API search error (HTTP {exc.code}): {exc.reason}.",
            )
        except Exception as exc:
            return GitHubCandidateResult(
                message=f"GitHub search failed: {exc}.",
            )

        candidates: list[dict] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        # For each candidate user item, fetch detailed public profile (if rate limits permit)
        for item in items:
            login = item.get("login")
            html_url = item.get("html_url", f"https://github.com/{login}")

            user_details = {}
            # Check user detail rate limits
            detail_url = f"https://api.github.com/users/{login}"
            detail_req = Request(detail_url, headers=self._get_headers())
            try:
                with urlopen(detail_req, timeout=6) as u_resp:
                    u_remaining = int(u_resp.headers.get("X-RateLimit-Remaining", 1))
                    user_details = json.loads(u_resp.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code in (403, 429):
                    user_details = {
                        "login": login,
                        "html_url": html_url,
                        "name": login,
                        "bio": "GitHub public developer",
                    }
                    break
                user_details = {"login": login, "html_url": html_url}
            except Exception:
                user_details = {"login": login, "html_url": html_url}

            cand_name = (user_details.get("name") or login or "GitHub User").strip()
            bio = (user_details.get("bio") or "").strip()
            company = (user_details.get("company") or "").strip().lstrip("@")
            cand_loc = (user_details.get("location") or location or "").strip()
            blog = (user_details.get("blog") or "").strip()
            if blog and not urlparse(blog).scheme:
                blog = "https://" + blog

            raw_email = (user_details.get("email") or "").strip()
            # Only record email if genuinely provided publicly
            email = raw_email if raw_email else ""
            phone = ""  # GitHub API does not support phone numbers; never fabricated

            if email:
                contact_prov = f"Public GitHub Profile ({html_url}) [Retrieved {now_str}]"
                contact_status = "Publicly published on GitHub"
            else:
                contact_prov = f"GitHub Profile ({html_url}) [Checked {now_str}]"
                contact_status = "Not found"

            headline = bio if bio else f"GitHub Developer ({login})"
            if company:
                headline = f"{headline} at {company}"

            evidence_parts = [
                f"Candidate: {cand_name} (@{login})",
                f"Profile: {html_url}",
                f"Headline / Bio: {bio}" if bio else f"GitHub user: {login}",
                f"Public Repositories: {user_details.get('public_repos', 'Public')}",
                f"Followers: {user_details.get('followers', 0)}",
                f"Company: {company}" if company else "Company: Not specified",
                f"Location: {cand_loc}" if cand_loc else "Location: Not specified",
                f"Website / Portfolio: {blog}" if blog else "Portfolio: None listed",
                f"Keywords matched: {clean_kw}",
            ]
            evidence_text = "\n".join(evidence_parts)

            candidates.append({
                "name": cand_name,
                "profile_url": html_url,
                "github_url": html_url,
                "portfolio_url": blog,
                "headline": headline,
                "company": company,
                "location": cand_loc,
                "email": email,
                "phone": phone,
                "contact_provenance": contact_prov,
                "contact_status": contact_status,
                "source": "GitHub Public API (Zero Cost)",
                "evidence_text": evidence_text,
                "status": "New",
            })

        return GitHubCandidateResult(
            candidates=candidates,
            total_found=total_found,
            message=f"Retrieved {len(candidates)} public GitHub developer profiles (out of {total_found} public matches).",
        )

    def search(self, query: str, num_results: int = 10) -> SearchProviderResult:
        res = self.search_candidates(keywords=query, num_results=num_results)
        items = [
            SearchResultItem(
                title=f"{c['name']} ({c['headline'][:60]})",
                url=c['profile_url'],
                snippet=c['evidence_text'][:150] + "...",
                source_provider=self.name,
            )
            for c in res.candidates
        ]
        return SearchProviderResult(
            provider_name=self.name,
            items=items,
            total_results=res.total_found,
            is_fallback=False,
            quota_exhausted=res.rate_limited,
            error_message=res.message if not res.candidates and res.message else None,
        )


def get_search_provider(
    provider_type: str = "local",
    api_key: str = "",
    extra_config: dict | None = None,
) -> BaseSearchProvider:
    """Factory returning the requested search provider.
    STRICT ZERO BUDGET POLICY:
    - Paid endpoints (Exa, Brave paid, SerpAPI, etc.) are strictly prohibited from billable usage.
    - Defaults safely to LocalFallbackProvider or GitHubSearchProvider.
    """
    extra = extra_config or {}
    p_type = provider_type.lower().strip()
    if p_type == "github":
        return GitHubSearchProvider(token=api_key or os.getenv("GITHUB_TOKEN"))
    elif p_type == "google_cse" and api_key and extra.get("cx"):
        return GoogleCseProvider(api_key=api_key, cx=extra["cx"])
    elif p_type == "serpapi" and api_key:
        return SerpApiProvider(api_key=api_key)
    return LocalFallbackProvider()
