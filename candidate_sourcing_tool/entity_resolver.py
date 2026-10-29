from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse
from source_connectors import RawCandidateProfile


def normalize_profile_url(url: str) -> str:
    """Normalizes a profile URL for deduplication comparisons."""
    if not url:
        return ""
    clean = url.strip().rstrip("/")
    if not urlparse(clean).scheme:
        clean = "https://" + clean
    # Strip www and lower domain, keep path case
    parts = urlparse(clean)
    netloc = parts.netloc.lower().replace("www.", "")
    path = parts.path.rstrip("/")
    return f"https://{netloc}{path}"


def normalize_email(email: str) -> str:
    """Normalizes an email address."""
    if not email:
        return ""
    return email.strip().lower()


def normalize_name(name: str) -> str:
    """Normalizes a candidate's full name."""
    if not name:
        return ""
    # Remove emojis, special chars, multiple spaces
    clean = re.sub(r"[^\w\s\.-]", "", name).strip()
    return " ".join(clean.split()).lower()


@dataclass
class CanonicalCandidate:
    id: int | None
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
    status: str = "New"
    notes: str = ""
    evidence_ladder_tier: str = "Unclassified"
    raw_sources: list[str] = field(default_factory=list)
    match_score: int = 0
    match_details: str = "{}"


class EntityResolver:
    """Resolves identities across diverse public talent sources,
    deduplicates profiles, and non-destructively merges multi-source evidence.
    """

    def __init__(self, existing_db_candidates: list[dict] | None = None):
        self.url_map: dict[str, CanonicalCandidate] = {}
        self.email_map: dict[str, CanonicalCandidate] = {}
        self.name_loc_map: dict[str, CanonicalCandidate] = {}
        self.canonical_list: list[CanonicalCandidate] = []

        # Index existing candidates from DB if provided
        if existing_db_candidates:
            for c in existing_db_candidates:
                cand = CanonicalCandidate(
                    id=c.get("id"),
                    name=c.get("name", ""),
                    headline=c.get("headline", ""),
                    profile_url=c.get("profile_url", ""),
                    source=c.get("source", "Existing Database"),
                    location=c.get("location", ""),
                    company=c.get("company", ""),
                    email=c.get("email", ""),
                    phone=c.get("phone", ""),
                    github_url=c.get("github_url", ""),
                    gitlab_url=c.get("gitlab_url", ""),
                    stackoverflow_url=c.get("stackoverflow_url", ""),
                    huggingface_url=c.get("huggingface_url", ""),
                    portfolio_url=c.get("portfolio_url", ""),
                    evidence_text=c.get("evidence_text", ""),
                    contact_provenance=c.get("contact_provenance", ""),
                    contact_status=c.get("contact_status", "Not found"),
                    status=c.get("status", "New"),
                    notes=c.get("notes", ""),
                    raw_sources=[c.get("source", "Existing Database")],
                )
                self._index_candidate(cand)

    def _index_candidate(self, cand: CanonicalCandidate) -> None:
        self.canonical_list.append(cand)

        for u in [cand.profile_url, cand.github_url, cand.gitlab_url, cand.stackoverflow_url, cand.huggingface_url]:
            if u:
                norm_u = normalize_profile_url(u)
                if norm_u:
                    self.url_map[norm_u] = cand

        if cand.email:
            norm_e = normalize_email(cand.email)
            if norm_e:
                self.email_map[norm_e] = cand

        if cand.name:
            norm_n = normalize_name(cand.name)
            if norm_n and len(norm_n) > 3:
                # Name + Location key
                loc_key = f"{norm_n}|{cand.location.lower()[:15]}" if cand.location else f"{norm_n}|any"
                self.name_loc_map[loc_key] = cand

    def resolve(self, raw: RawCandidateProfile) -> tuple[CanonicalCandidate, bool]:
        """Resolves a raw candidate profile.
        Returns (canonical_candidate, is_duplicate).
        """
        match: CanonicalCandidate | None = None

        # Rule 1: Match by profile URL
        for u in [raw.profile_url, raw.github_url, raw.gitlab_url, raw.stackoverflow_url, raw.huggingface_url]:
            if u:
                norm_u = normalize_profile_url(u)
                if norm_u in self.url_map:
                    match = self.url_map[norm_u]
                    break

        # Rule 2: Match by verified public email
        if not match and raw.email:
            norm_e = normalize_email(raw.email)
            if norm_e in self.email_map:
                match = self.email_map[norm_e]

        # Rule 3: Match by high-confidence name + location
        if not match and raw.name and raw.location:
            norm_n = normalize_name(raw.name)
            loc_key = f"{norm_n}|{raw.location.lower()[:15]}"
            if loc_key in self.name_loc_map:
                match = self.name_loc_map[loc_key]

        if match:
            # Merge evidence non-destructively
            self._merge_into(match, raw)
            return match, True

        # Create new canonical candidate
        new_cand = CanonicalCandidate(
            id=None,
            name=raw.name,
            headline=raw.headline,
            profile_url=raw.profile_url,
            source=raw.source,
            location=raw.location,
            company=raw.company,
            email=raw.email,
            phone=raw.phone,
            github_url=raw.github_url,
            gitlab_url=raw.gitlab_url,
            stackoverflow_url=raw.stackoverflow_url,
            huggingface_url=raw.huggingface_url,
            portfolio_url=raw.portfolio_url,
            evidence_text=raw.evidence_text,
            contact_provenance=raw.contact_provenance,
            contact_status=raw.contact_status,
            evidence_ladder_tier=raw.evidence_ladder_tier,
            raw_sources=[raw.source],
        )
        self._index_candidate(new_cand)
        return new_cand, False

    def _merge_into(self, target: CanonicalCandidate, raw: RawCandidateProfile) -> None:
        """Merges raw profile evidence into target without overwriting stronger data."""
        if not target.headline and raw.headline:
            target.headline = raw.headline
        if not target.location and raw.location:
            target.location = raw.location
        if not target.company and raw.company:
            target.company = raw.company
        if not target.email and raw.email:
            target.email = raw.email
            target.contact_provenance = raw.contact_provenance
            target.contact_status = raw.contact_status
        if not target.github_url and raw.github_url:
            target.github_url = raw.github_url
        if not target.gitlab_url and raw.gitlab_url:
            target.gitlab_url = raw.gitlab_url
        if not target.stackoverflow_url and raw.stackoverflow_url:
            target.stackoverflow_url = raw.stackoverflow_url
        if not target.huggingface_url and raw.huggingface_url:
            target.huggingface_url = raw.huggingface_url
        if not target.portfolio_url and raw.portfolio_url:
            target.portfolio_url = raw.portfolio_url

        # Prefer higher evidence ladder tier: Tier 1 > Tier 2 > Tier 3
        if "Tier 1" in raw.evidence_ladder_tier or (not target.evidence_ladder_tier and raw.evidence_ladder_tier):
            target.evidence_ladder_tier = raw.evidence_ladder_tier
        elif "Tier 2" in raw.evidence_ladder_tier and "Tier 1" not in target.evidence_ladder_tier:
            target.evidence_ladder_tier = raw.evidence_ladder_tier

        if raw.source not in target.raw_sources:
            target.raw_sources.append(raw.source)
            target.source = f"{target.source} + {raw.source}"

        # Append new evidence text
        if raw.evidence_text and raw.evidence_text not in target.evidence_text:
            target.evidence_text = f"{target.evidence_text}\n\n[Additional Source Evidence from {raw.source}]:\n{raw.evidence_text}".strip()
