from __future__ import annotations

import gzip
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode, urlparse
from urllib.request import Request, urlopen

from cost_guard import cost_guard


@dataclass
class RawCandidateProfile:
    name: str
    headline: str
    profile_url: str
    source: str
    location: str = ""
    company: str = ""
    email: str = ""
    phone: str = ""
    github_url: str = ""
    gitlab_url: str = ""
    stackoverflow_url: str = ""
    huggingface_url: str = ""
    portfolio_url: str = ""
    evidence_text: str = ""
    contact_provenance: str = ""
    contact_status: str = "Not found"
    external_id: str = ""
    evidence_ladder_tier: str = "Unclassified"
    raw_data: dict = field(default_factory=dict)


def classify_github_evidence(user_details: dict, bio: str, keywords: str, repos: list[dict] | None = None) -> dict[str, str]:
    """Applies the 4-tier evidence model:
    Distinguishes authentic technical contribution evidence from vanity / weak signals.
    """
    public_repos = int(user_details.get("public_repos") or 0)
    followers = int(user_details.get("followers") or 0)

    # Check keyword alignment in bio, repo names, and repo descriptions
    kw_words = [w.lower() for w in keywords.split() if len(w) > 2]
    bio_text = (bio or "").lower()
    repos = repos or []
    repo_text = " ".join([f"{r.get('name', '')} {r.get('description', '')} {r.get('language', '')}" for r in repos]).lower()
    combined_signal = f"{bio_text} {repo_text}"

    matched_signals = [w for w in kw_words if w in combined_signal]

    if (public_repos >= 3 and matched_signals) or (len(repos) >= 2 and any(r.get("stargazers_count", 0) >= 2 for r in repos)):
        tier = "Tier 1: Strong Technical Evidence"
        rationale = (
            f"Active repository ownership ({public_repos} public repos) with verified project "
            f"and technology alignment: {', '.join(matched_signals) if matched_signals else 'active codebases'}."
        )
    elif public_repos >= 1 or matched_signals or bio_text:
        tier = "Tier 2: Moderate Technical Evidence"
        rationale = (
            f"Public repository presence ({public_repos} repos) with domain or profile alignment."
        )
    elif public_repos > 0 or followers > 0:
        tier = "Tier 3: Weak / Contextual Signal"
        rationale = (
            f"Sparse public repository footprint; follower count ({followers}) is treated as a discounted weak signal without direct code evidence."
        )
    else:
        tier = "Tier 4: Insufficient Evidence"
        rationale = (
            "Empty profile without public repositories or verifiable technical code samples."
        )

    return {
        "tier": tier,
        "rationale": rationale,
    }


@dataclass
class ConnectorSearchResult:
    source_name: str
    source_id: str
    candidates: list[RawCandidateProfile] = field(default_factory=list)
    total_found: int = 0
    rate_limited: bool = False
    rate_limit_reset: str | None = None
    error_message: str | None = None
    is_free: bool = True


class BaseSourceConnector(ABC):
    """Abstract interface for all zero-budget candidate sourcing connectors."""

    source_id: str = "base"
    name: str = "Base Connector"
    is_free: bool = True
    requires_api_key: bool = False

    @abstractmethod
    def search(
        self,
        keywords: str,
        location: str = "",
        limit: int = 5,
        **kwargs: Any,
    ) -> ConnectorSearchResult:
        pass

    def check_status(self) -> dict:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "is_free": self.is_free,
            "status": "Available",
            "zero_budget_verified": True,
        }


class GitHubConnector(BaseSourceConnector):
    """Official public GitHub API candidate sourcing connector.
    Zero budget ($0 / ₹0). Strictly stops when rate-limited.
    """

    source_id: str = "github"
    name: str = "GitHub Public API"
    is_free: bool = True

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

    def check_status(self) -> dict:
        url = "https://api.github.com/rate_limit"
        req = Request(url, headers=self._get_headers())
        try:
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                search = data.get("resources", {}).get("search", {})
                return {
                    "source_id": self.source_id,
                    "name": self.name,
                    "is_free": True,
                    "status": "Active & Ready",
                    "remaining": search.get("remaining", 10),
                    "limit": search.get("limit", 10),
                    "authenticated": bool(self.token),
                    "zero_budget_verified": True,
                }
        except Exception as exc:
            return {
                "source_id": self.source_id,
                "name": self.name,
                "is_free": True,
                "status": f"Warning: {exc}",
                "authenticated": bool(self.token),
                "zero_budget_verified": True,
            }

    def search(
        self,
        keywords: str,
        location: str = "",
        limit: int = 5,
        **kwargs: Any,
    ) -> ConnectorSearchResult:
        cost_guard.verify_provider(self.source_id)
        clean_kw = keywords.strip()
        if not clean_kw:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message="No keywords provided.",
            )

        cost_guard.log_request(self.source_id, "search", f"Keywords: {clean_kw}, Limit: {limit}")
        q_parts = [clean_kw]
        if location and location.strip():
            first_loc = location.split(",")[0].split(";")[0].strip()
            if first_loc.lower() not in {"remote", "global", "worldwide", "anywhere"}:
                q_parts.append(f'location:"{first_loc}"')
        q_parts.append("type:user")
        query_str = " ".join(q_parts)

        params = {"q": query_str, "per_page": min(10, max(1, limit))}
        search_url = f"https://api.github.com/search/users?{urlencode(params)}"
        req = Request(search_url, headers=self._get_headers())

        try:
            with urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                total_found = payload.get("total_count", 0)
                items = payload.get("items", [])
        except HTTPError as exc:
            if exc.code in (403, 429):
                reset_ts = exc.headers.get("X-RateLimit-Reset") if exc.headers else None
                reset_str = datetime.fromtimestamp(int(reset_ts)).strftime("%H:%M:%S") if reset_ts else "cooldown"
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    rate_limited=True,
                    rate_limit_reset=reset_str,
                    error_message=f"GitHub rate limit reached (HTTP {exc.code}). Resets at {reset_str}.",
                )
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"GitHub API error (HTTP {exc.code}): {exc.reason}",
            )
        except Exception as exc:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"GitHub search failed: {exc}",
            )

        candidates: list[RawCandidateProfile] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        for item in items:
            login = item.get("login", "")
            html_url = item.get("html_url", f"https://github.com/{login}")

            user_details = {}
            detail_url = f"https://api.github.com/users/{login}"
            detail_req = Request(detail_url, headers=self._get_headers())
            try:
                with urlopen(detail_req, timeout=6) as u_resp:
                    user_details = json.loads(u_resp.read().decode("utf-8"))
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
            email = raw_email if raw_email else ""
            phone = ""  # Never fabricated

            if email:
                contact_prov = f"Public GitHub Profile ({html_url}) [Retrieved {now_str}]"
                contact_status = "Publicly published on GitHub"
            else:
                contact_prov = f"GitHub Profile ({html_url}) [Checked {now_str}]"
                contact_status = "Not found"

            # Fetch recent public repositories for direct technical evidence
            repos_data: list[dict] = []
            try:
                repos_url = f"https://api.github.com/users/{login}/repos?sort=updated&per_page=3"
                repos_req = Request(repos_url, headers=self._get_headers())
                with urlopen(repos_req, timeout=4) as r_resp:
                    repos_data = json.loads(r_resp.read().decode("utf-8"))
            except Exception:
                repos_data = []

            # 4-tier Evidence Evaluation
            ladder_eval = classify_github_evidence(user_details, bio, clean_kw, repos=repos_data)
            user_details["evidence_ladder"] = ladder_eval

            headline = bio if bio else f"GitHub Developer ({login})"
            if company:
                headline = f"{headline} at {company}"

            repo_lines = []
            for r in repos_data:
                r_name = r.get("name", "")
                r_lang = r.get("language") or ""
                r_desc = (r.get("description") or "").strip()
                r_stars = r.get("stargazers_count", 0)
                line = f"- {r_name}"
                if r_lang:
                    line += f" ({r_lang})"
                if r_stars:
                    line += f" [{r_stars}★]"
                if r_desc:
                    line += f": {r_desc}"
                repo_lines.append(line)

            evidence_parts = [
                f"Candidate: {cand_name} (@{login})",
                f"Profile: {html_url}",
                f"Evidence Tier: {ladder_eval['tier']}",
                f"Evidence Analysis: {ladder_eval['rationale']}",
                f"Bio: {bio or 'None'}",
                f"Public Repos: {user_details.get('public_repos', 0)}, Followers: {user_details.get('followers', 0)}",
                f"Company: {company or 'None'}, Location: {cand_loc or 'None'}",
                f"Portfolio: {blog or 'None'}",
            ]
            if repo_lines:
                evidence_parts.append("Recent Public Repositories:\n" + "\n".join(repo_lines))

            evidence = "\n".join(evidence_parts)

            candidates.append(
                RawCandidateProfile(
                    name=cand_name,
                    headline=headline,
                    profile_url=html_url,
                    source="GitHub Public API",
                    location=cand_loc,
                    company=company,
                    email=email,
                    phone=phone,
                    github_url=html_url,
                    portfolio_url=blog,
                    evidence_text=evidence,
                    contact_provenance=contact_prov,
                    contact_status=contact_status,
                    external_id=f"gh_{login}",
                    evidence_ladder_tier=ladder_eval["tier"],
                    raw_data=user_details,
                )
            )

        return ConnectorSearchResult(
            source_name=self.name,
            source_id=self.source_id,
            candidates=candidates,
            total_found=total_found,
        )


class GitLabConnector(BaseSourceConnector):
    """Official public GitLab API candidate sourcing connector.
    Zero budget ($0 / ₹0). Discovers public repository creators and active users.
    """

    source_id: str = "gitlab"
    name: str = "GitLab Public API"
    is_free: bool = True

    def __init__(self, token: str | None = None):
        self.token = (token or os.getenv("GITLAB_TOKEN", "")).strip()

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CandidateFinder/1.0",
            "Accept": "application/json",
        }
        if self.token:
            headers["PRIVATE-TOKEN"] = self.token
        return headers

    def search(
        self,
        keywords: str,
        location: str = "",
        limit: int = 5,
        **kwargs: Any,
    ) -> ConnectorSearchResult:
        cost_guard.verify_provider(self.source_id)
        clean_kw = keywords.strip().split()[0] if keywords.strip() else ""
        if not clean_kw:
            return ConnectorSearchResult(source_name=self.name, source_id=self.source_id, error_message="No keywords")

        cost_guard.log_request(self.source_id, "search", f"Keywords: {clean_kw}, Limit: {limit}")

        params = {"search": clean_kw, "per_page": min(10, max(1, limit))}
        url = f"https://gitlab.com/api/v4/projects?{urlencode(params)}"
        req = Request(url, headers=self._get_headers())

        try:
            with urlopen(req, timeout=8) as resp:
                projects = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (403, 429):
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    rate_limited=True,
                    error_message=f"GitLab API rate limited or restricted (HTTP {exc.code}).",
                )
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"GitLab API error (HTTP {exc.code})",
            )
        except Exception as exc:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"GitLab query failed: {exc}",
            )

        candidates: list[RawCandidateProfile] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        seen_users = set()

        for p in projects:
            ns = p.get("namespace", {})
            if ns and ns.get("kind") == "user":
                username = ns.get("path") or ns.get("name")
                if not username or username in seen_users:
                    continue
                seen_users.add(username)

                name = ns.get("name", username)
                web_url = ns.get("web_url", f"https://gitlab.com/{username}")
                proj_name = p.get("name", "Project")
                proj_desc = p.get("description", "") or ""

                stars = int(p.get("star_count", 0) or 0)
                forks = int(p.get("forks_count", 0) or 0)
                tags = p.get("tag_list") or []

                if stars >= 2 or len(tags) >= 2 or (proj_desc and len(proj_desc) > 40):
                    gl_tier = "Tier 1: Strong Technical Evidence"
                elif stars >= 1 or proj_desc:
                    gl_tier = "Tier 2: Moderate Technical Evidence"
                else:
                    gl_tier = "Tier 3: Weak Technical Evidence"

                headline = f"GitLab Developer ({username}) — {proj_name}"
                evidence = (
                    f"Candidate: {name} (@{username} on GitLab)\n"
                    f"Profile: {web_url}\n"
                    f"Evidence Tier: {gl_tier}\n"
                    f"Project: {proj_name}\n"
                    f"Description: {proj_desc or 'None listed'}\n"
                    f"Project Tags: {', '.join(tags) if tags else 'None'}\n"
                    f"GitLab Project Stars: {stars}, Forks: {forks}"
                )

                candidates.append(
                    RawCandidateProfile(
                        name=name,
                        headline=headline,
                        profile_url=web_url,
                        source="GitLab Public API",
                        location=location,
                        company="",
                        email="",
                        phone="",
                        gitlab_url=web_url,
                        evidence_text=evidence,
                        contact_provenance=f"GitLab Public Profile ({web_url}) [Checked {now_str}]",
                        contact_status="Not found",
                        external_id=f"gl_{username}",
                        evidence_ladder_tier=gl_tier,
                        raw_data=p,
                    )
                )

        return ConnectorSearchResult(
            source_name=self.name,
            source_id=self.source_id,
            candidates=candidates,
            total_found=len(candidates),
        )


class StackExchangeConnector(BaseSourceConnector):
    """Official public Stack Exchange API connector for discovering active technical contributors.
    Zero budget ($0 / ₹0). Uses https://api.stackexchange.com/2.3/users.
    """

    source_id: str = "stackoverflow"
    name: str = "Stack Overflow Public API"
    is_free: bool = True

    def search(
        self,
        keywords: str,
        location: str = "",
        limit: int = 5,
        **kwargs: Any,
    ) -> ConnectorSearchResult:
        cost_guard.verify_provider(self.source_id)
        # Use first technical keyword for inname or tag matching
        words = [w for w in keywords.strip().split() if len(w) > 2]
        clean_kw = words[0] if words else "developer"

        cost_guard.log_request(self.source_id, "search", f"Keyword: {clean_kw}, Limit: {limit}")

        params = {
            "order": "desc",
            "sort": "reputation",
            "site": "stackoverflow",
            "inname": clean_kw,
            "pagesize": min(10, max(1, limit)),
        }
        url = f"https://api.stackexchange.com/2.3/users?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "CandidateFinder/1.0 (Recruitment Assistant)"})

        try:
            with urlopen(req, timeout=8) as resp:
                raw_bytes = resp.read()
                try:
                    payload = json.loads(gzip.decompress(raw_bytes))
                except Exception:
                    payload = json.loads(raw_bytes.decode("utf-8"))
                items = payload.get("items", [])
        except HTTPError as exc:
            if exc.code in (403, 429):
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    rate_limited=True,
                    error_message="Stack Exchange rate limit reached.",
                )
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"Stack Exchange HTTP {exc.code}: {exc.reason}",
            )
        except Exception as exc:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"Stack Exchange search failed: {exc}",
            )

        candidates: list[RawCandidateProfile] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        for u in items:
            name = u.get("display_name", "Stack Overflow User").strip()
            link = u.get("link", "")
            user_loc = (u.get("location") or location or "").strip()
            website = (u.get("website_url") or "").strip()
            reputation = u.get("reputation", 0)
            badges = u.get("badge_counts", {})
            gold = badges.get("gold", 0)
            silver = badges.get("silver", 0)
            bronze = badges.get("bronze", 0)

            if reputation >= 2500 or gold > 0:
                so_tier = "Tier 2: Moderate Technical Evidence"
            elif reputation >= 200 or silver > 0:
                so_tier = "Tier 3: Weak Technical Evidence"
            else:
                so_tier = "Tier 4: Insufficient Evidence"

            headline = f"Stack Overflow Contributor ({reputation:,} Rep)"
            evidence = (
                f"Candidate: {name}\n"
                f"Profile: {link}\n"
                f"Evidence Tier: {so_tier}\n"
                f"Reputation: {reputation:,}\n"
                f"Badges: {gold} Gold, {silver} Silver, {bronze} Bronze\n"
                f"Location: {user_loc or 'Not specified'}\n"
                f"Website / Portfolio: {website or 'None listed'}"
            )

            contact_prov = f"Stack Overflow Profile ({link}) [Checked {now_str}]"
            contact_status = "Not found"

            candidates.append(
                RawCandidateProfile(
                    name=name,
                    headline=headline,
                    profile_url=link,
                    source="Stack Overflow",
                    location=user_loc,
                    company="",
                    email="",
                    phone="",
                    stackoverflow_url=link,
                    portfolio_url=website,
                    evidence_text=evidence,
                    contact_provenance=contact_prov,
                    contact_status=contact_status,
                    external_id=f"so_{u.get('user_id')}",
                    evidence_ladder_tier=so_tier,
                    raw_data=u,
                )
            )

        return ConnectorSearchResult(
            source_name=self.name,
            source_id=self.source_id,
            candidates=candidates,
            total_found=len(candidates),
        )


class HuggingFaceConnector(BaseSourceConnector):
    """Official public Hugging Face Hub API connector for AI/ML and Data Science roles.
    Zero budget ($0 / ₹0). Discovers active model creators and practitioners.
    """

    source_id: str = "huggingface"
    name: str = "Hugging Face Hub API"
    is_free: bool = True

    def search(
        self,
        keywords: str,
        location: str = "",
        limit: int = 5,
        **kwargs: Any,
    ) -> ConnectorSearchResult:
        cost_guard.verify_provider(self.source_id)
        # Check if the keywords contain AI/ML relevant terms
        ai_markers = {"ai", "ml", "data", "model", "llm", "deep", "nlp", "vision", "python", "pytorch", "tensorflow", "transformer"}
        kw_lower = keywords.lower()
        if not any(m in kw_lower for m in ai_markers):
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                candidates=[],
                total_found=0,
                error_message="Skipped: Hugging Face connector runs for AI/ML/Data Science roles.",
            )

        words = [w for w in keywords.strip().split() if len(w) > 2]
        clean_kw = words[0] if words else "model"
        cost_guard.log_request(self.source_id, "search", f"Keyword: {clean_kw}, Limit: {limit}")

        params = {"search": clean_kw, "limit": min(10, max(1, limit))}
        url = f"https://huggingface.co/api/models?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "CandidateFinder/1.0"})

        try:
            with urlopen(req, timeout=8) as resp:
                models = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (403, 429):
                return ConnectorSearchResult(
                    source_name=self.name,
                    source_id=self.source_id,
                    rate_limited=True,
                    error_message=f"Hugging Face rate limit (HTTP {exc.code}).",
                )
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"Hugging Face HTTP {exc.code}: {exc.reason}",
            )
        except Exception as exc:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message=f"Hugging Face query failed: {exc}",
            )

        candidates: list[RawCandidateProfile] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        seen_authors = set()

        for m in models:
            model_id = m.get("id", "")
            if "/" not in model_id:
                continue
            author = model_id.split("/")[0].strip()
            if not author or author.lower() in {"google", "microsoft", "meta", "facebook", "openai", "huggingface", "stabilityai"}:
                # Skip massive corporate org accounts
                continue
            if author in seen_authors:
                continue
            seen_authors.add(author)

            author_url = f"https://huggingface.co/{author}"
            downloads = m.get("downloads", 0)
            likes = m.get("likes", 0)
            pipeline = m.get("pipeline_tag", "AI Model")

            tags = m.get("tags") or []
            if downloads >= 100 or likes >= 5:
                hf_tier = "Tier 1: Strong Technical Evidence"
            elif downloads > 0 or likes > 0:
                hf_tier = "Tier 2: Moderate Technical Evidence"
            else:
                hf_tier = "Tier 3: Weak Technical Evidence"

            headline = f"AI / ML Creator on Hugging Face ({author}) — {pipeline}"
            evidence = (
                f"Candidate: {author} (Hugging Face)\n"
                f"Profile: {author_url}\n"
                f"Evidence Tier: {hf_tier}\n"
                f"Published Model: {model_id}\n"
                f"Pipeline / Domain: {pipeline}\n"
                f"Model Downloads: {downloads:,}, Likes: {likes}\n"
                f"Tags: {', '.join(tags[:6]) if tags else 'None'}"
            )

            contact_prov = f"Hugging Face Public Profile ({author_url}) [Checked {now_str}]"

            candidates.append(
                RawCandidateProfile(
                    name=author,
                    headline=headline,
                    profile_url=author_url,
                    source="Hugging Face",
                    location=location,
                    company="",
                    email="",
                    phone="",
                    huggingface_url=author_url,
                    evidence_text=evidence,
                    contact_provenance=contact_prov,
                    contact_status="Not found",
                    external_id=f"hf_{author}",
                    evidence_ladder_tier=hf_tier,
                    raw_data=m,
                )
            )

        return ConnectorSearchResult(
            source_name=self.name,
            source_id=self.source_id,
            candidates=candidates,
            total_found=len(candidates),
        )


class LocalDatabaseConnector(BaseSourceConnector):
    """Local SQLite Candidate Rediscovery Connector.
    100% offline, ₹0.00 spend.
    Searches previously saved candidates for relevant skills to match the new JD.
    """

    source_id: str = "local_db"
    name: str = "Local Talent Rediscovery (SQLite)"
    is_free: bool = True

    def __init__(self, db_conn=None):
        self.conn = db_conn

    def search(
        self,
        keywords: str,
        location: str = "",
        limit: int = 5,
        **kwargs: Any,
    ) -> ConnectorSearchResult:
        cost_guard.verify_provider(self.source_id)
        if not self.conn:
            return ConnectorSearchResult(
                source_name=self.name,
                source_id=self.source_id,
                error_message="No database connection supplied.",
            )

        cost_guard.log_request(self.source_id, "search", f"Keywords: {keywords}, Limit: {limit}")
        clean_words = [w.strip() for w in keywords.lower().split() if len(w.strip()) > 2]
        if not clean_words:
            return ConnectorSearchResult(source_name=self.name, source_id=self.source_id)

        rows = self.conn.execute("SELECT * FROM candidates ORDER BY id DESC").fetchall()
        matched: list[RawCandidateProfile] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        for r in rows:
            text_corpus = f"{r['name']} {r['headline']} {r['evidence_text']} {r['notes']}".lower()
            hit_count = sum(1 for w in clean_words if w in text_corpus)
            if hit_count > 0:
                tier = (r["evidence_ladder_tier"] if "evidence_ladder_tier" in r.keys() and r["evidence_ladder_tier"] else "Tier 2: Moderate Technical Evidence")
                matched.append(
                    RawCandidateProfile(
                        name=r["name"],
                        headline=r["headline"] or "Previously Saved Candidate",
                        profile_url=r["profile_url"] or f"local://candidate/{r['id']}",
                        source="Local DB Rediscovery",
                        location=r["location"] or "",
                        company=r["company"] or "",
                        email=r["email"] or "",
                        phone=r["phone"] or "",
                        github_url=r["github_url"] or "",
                        portfolio_url=r["portfolio_url"] or "",
                        evidence_text=f"[Rediscovered from Local Database]\nOriginal Source: {r['source']}\n{r['evidence_text']}",
                        contact_provenance=r["contact_provenance"] or f"Local SQLite DB [Retrieved {now_str}]",
                        contact_status=r["contact_status"] or ("Publicly published" if r["email"] else "Not found"),
                        external_id=f"local_{r['id']}",
                        evidence_ladder_tier=tier,
                        raw_data=dict(r),
                    )
                )

        return ConnectorSearchResult(
            source_name=self.name,
            source_id=self.source_id,
            candidates=matched[:limit],
            total_found=len(matched),
        )


def get_all_connectors(db_conn=None) -> list[BaseSourceConnector]:
    """Returns all verified zero-budget sourcing connectors."""
    from groq_browser_connector import GroqBrowserSearchConnector

    return [
        GitHubConnector(),
        GitLabConnector(),
        StackExchangeConnector(),
        HuggingFaceConnector(),
        LocalDatabaseConnector(db_conn=db_conn),
        GroqBrowserSearchConnector(),
    ]
