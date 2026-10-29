from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TitleExtractionResult:
    title: str
    alternative_titles: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    confidence_level: str = "Low"  # "High", "Medium", "Low"
    detected_candidates: list[str] = field(default_factory=list)
    warning: str | None = None


# Known role keywords (singular/plural)
ROLE_KEYWORDS = {
    "specialist", "specialists", "engineer", "engineers", "developer", "developers",
    "artist", "artists", "modeler", "modelers", "designer", "designers",
    "architect", "architects", "manager", "managers", "lead", "leads",
    "director", "directors", "analyst", "analysts", "consultant", "consultants",
    "scientist", "scientists", "coordinator", "coordinators", "administrator", "administrators",
    "officer", "officers", "executive", "executives", "associate", "associates",
    "intern", "interns", "programmer", "programmers", "technician", "technicians",
    "recruiter", "recruiters", "counsel", "lawyer", "writer", "writers",
    "animator", "animators", "illustrator", "illustrators", "producer", "producers",
    "generalist", "generalists", "evaluator", "evaluators", "trainer", "trainers",
    "rater", "raters", "operator", "operators",
}

# Document metadata, section headers, and boilerplate phrases that should NEVER be treated as job titles
METADATA_DISQUALIFIERS = [
    r"^(?:type|job\s*type|employment\s*type|contract\s*type|location|work\s*location|pay|salary|rate|hourly\s*rate)\s*:",
    r"^(?:role\s*id|job\s*id|req(?:uisition)?\s*(?:id|#)?|posting\s*id)\b",
    r"^(?:positions?|openings?|active\s*openings?|vacanc(?:y|ies))\b",
    r"^(?:duration|start\s*date|end\s*date|rate|est(?:\.|\s*)earnings?|task\s*time|availability)\b",
    r"^(?:experience|qualification|qualifications|education|requirements?|responsibilities)\b",
    r"^(?:role\s*overview|position\s*overview|job\s*overview|job\s*summary|about\s*(?:us|the\s*role|the\s*company))\b",
    r"^(?:project\s*snapshot|snapshot|contract\s*details|compensation|benefits|what\s*you(?:'ll|\s*will)\s*do)\b",
    r"^(?:application\s*&\s*selection\s*process|how\s*to\s*apply|submission\s*process)\b",
    r"^(?:short-term|long-term|full-time|part-time|contract|contractor|permanent|temporary|remote|hybrid|on-site)\b",
    r"^(?:confidential|all\s*rights\s*reserved|internal\s*use\s*only|page\s*\d+)\b",
    r"^\d+\s*(?:active\s*)?(?:openings?|positions?|vacanc(?:y|ies))\b",
    r"^\d+\s*active\s*\+\s*\d+",
    r"^d:\s*\d+",
    r"^(?:prior|previous|proven|demonstrated|minimum|hands-on)?\s*experience\b",
    r"^(?:high|strong|deep|solid|proven)?\s*proficiency\b",
    r"^(?:strong|deep|solid|thorough|good|working|comprehensive)?\s*(?:understanding|knowledge)\b",
    r"^(?:ability|capacity|skill)\s+to\b",
    r"^(?:bachelor|master|degree|diploma|phd|b\.s|m\.s|b\.a|m\.a)\b",
    r"^(?:mentoring|leading|managing|collaborating|working|creating|producing|building)\b",
]


def clean_title_candidate(line: str) -> str:
    """Removes page markers, separator artifacts, bullets, and surrounding noise from a title candidate."""
    if not line:
        return ""

    # Remove markdown formatting & list numbering/bullets (e.g. "1. ", "1) ", "- ", "* ")
    # but do NOT strip leading digits from valid terms like "3D Artist" or "2D Animator"
    text = re.sub(r"^\s*(?:[#*\->•\uf0b7]+\s*|\d+[\.\)\]]\s+)", "", line).strip()

    # Strip page markers: e.g. " | 1", " | Page 1", " - Page 2 of 3", " / 1", " | 2"
    text = re.sub(r"\s*[|/–—\-]\s*(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?\s*$", "", text, flags=re.I)
    text = re.sub(r"^\s*(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?\s*[|/–—\-]\s*", "", text, flags=re.I)

    # Strip trailing numbers or parenthetical page numbers: " (1)", " [Page 2]"
    text = re.sub(r"\s*[\(\[]\s*(?:page\s*)?\d+\s*[\)\]]$", "", text, flags=re.I)

    # Strip common punctuation leftovers
    text = text.strip(" :|-#–—/\\")

    return text.strip()


def is_disqualified_as_title(text: str) -> bool:
    """Checks if a string is obviously document metadata, a section header, or noise."""
    lower = text.lower().strip()
    if not lower or len(lower) < 3 or len(lower) > 90:
        return True

    # Check disqualifying regexes
    for pattern in METADATA_DISQUALIFIERS:
        if re.search(pattern, lower, re.I):
            return True

    # If it consists mostly of numbers, currency, or symbols
    if re.match(r"^[\d\s$€£¥%:.\-–—/]+$", text):
        return True

    # Single-word brand or acronym alone with no role word (e.g., "FUTUREJOBS", "GOOGLE")
    words = lower.split()
    if len(words) == 1 and not any(kw in lower for kw in ROLE_KEYWORDS):
        return True

    return False


def extract_explicit_labeled_title(text: str) -> str | None:
    """Searches for explicit labels like 'Job Title: Digital Image Specialist' or 'ROLE\nBusiness Analyst'."""
    pattern = re.compile(
        r"^(?:job\s*title|position\s*title|position|role\s*title|role|title)(?:\s*[:\-–—]\s*|\s*\n\s*)([^\n\r]+)",
        re.I | re.MULTILINE,
    )
    for match in pattern.finditer(text):
        cand = clean_title_candidate(match.group(1))
        # Ensure it's not a generic word like "Overview" or "ID"
        if cand and not is_disqualified_as_title(cand):
            # Check if it has a role keyword or is a plausible 1-5 word capitalized title
            if any(re.search(rf"\b{kw}\b", cand, re.I) for kw in ROLE_KEYWORDS):
                return cand
            if 1 <= len(cand.split()) <= 5 and not re.search(r"[.?!;]", cand):
                return cand
    return None


def extract_alternative_titles_from_overview(text: str, primary_title: str = "") -> list[str]:
    """Finds genuine alternative job titles from explicit sections or role overview sentences.
    Iteratively strips leading articles and qualifying adjectives (e.g. 'detail-oriented', 'creative').
    Filters out candidates matching or trivial subsets of primary_title.
    """
    explicit_alternatives: list[str] = []

    # 1. Explicit alternative titles section (e.g. "Alternative Titles: Systems Analyst, Data Analyst" or "Similar roles: ...")
    explicit_alt_pattern = re.compile(
        r"^(?:alternative\s+titles?|also\s+known\s+as|similar\s+roles?|related\s+titles?)\s*[:\-–—]\s*(.+)$",
        re.I | re.MULTILINE,
    )
    for match in explicit_alt_pattern.finditer(text):
        for part in re.split(r"[,;|\n]", match.group(1)):
            part = clean_title_candidate(part)
            if part and not is_disqualified_as_title(part) and len(part.split()) <= 4 and part not in explicit_alternatives:
                explicit_alternatives.append(part)

    # 2. Match patterns like: "seeking ... <titles> who can / to ..."
    inferred_alternatives: list[str] = []
    seeking_pattern = re.compile(
        r"(?:seeking|looking for|hiring|in search of)\s+([^\n.]+?)\s+(?:who|to|with|for)\b",
        re.I,
    )
    for match in seeking_pattern.finditer(text):
        clause = match.group(1)
        # Split on commas, 'and', 'or'
        parts = re.split(r",|\band\b|\bor\b", clause)
        for part in parts:
            part = part.strip()
            # Iteratively strip leading articles, conjunctions, and qualifying adjectives
            while True:
                cleaned = re.sub(
                    r"^(?:a|an|the|and|or|creative|detail-oriented|detail\s+oriented|experienced|talented|motivated|exceptional|dynamic|passionate|fresh|emerging|skilled|senior|junior|lead|expert|strong|proven)\s+",
                    "",
                    part,
                    flags=re.I,
                ).strip()
                cleaned = re.sub(r"^[\s,;:\-–—]+", "", cleaned)
                if cleaned == part:
                    break
                part = cleaned

            part = clean_title_candidate(part)
            if part and not is_disqualified_as_title(part):
                if any(re.search(rf"\b{kw}\b", part, re.I) for kw in ROLE_KEYWORDS):
                    # Normalize plural to singular if obvious
                    singular = re.sub(r"specialists$", "Specialist", part, flags=re.I)
                    singular = re.sub(r"artists$", "Artist", singular, flags=re.I)
                    singular = re.sub(r"engineers$", "Engineer", singular, flags=re.I)
                    singular = re.sub(r"developers$", "Developer", singular, flags=re.I)
                    singular = re.sub(r"designers$", "Designer", singular, flags=re.I)
                    singular = re.sub(r"modelers$", "Modeler", singular, flags=re.I)
                    singular = re.sub(r"illustrators$", "Illustrator", singular, flags=re.I)
                    singular = re.sub(r"analysts$", "Analyst", singular, flags=re.I)
                    singular = re.sub(r"scientists$", "Scientist", singular, flags=re.I)
                    singular = " ".join(w.capitalize() if not re.match(r"^(?:3D|2D|UI|UX|API|AI|ML|NPR)$", w, re.I) else w.upper() for w in singular.split())
                    if len(singular.split()) <= 4 and singular not in inferred_alternatives:
                        inferred_alternatives.append(singular)

    # Discard inferred alternatives that are merely a subset of the primary title words (e.g. 'Data Scientists' for 'Competitive Data Scientist')
    if primary_title:
        pt_norm = primary_title.lower().strip()
        pt_stems = {re.sub(r"(?:ing|ed|s)$", "", w) for w in re.findall(r"\b\w+\b", pt_norm)}
        valid_inferred = []
        for a in inferred_alternatives:
            a_norm = a.lower().strip()
            a_words_stem = {re.sub(r"(?:ing|ed|s)$", "", w) for w in re.findall(r"\b\w+\b", a_norm)}
            if a_words_stem and a_words_stem.issubset(pt_stems):
                continue
            valid_inferred.append(a)
        inferred_alternatives = valid_inferred

    all_candidates = explicit_alternatives + [x for x in inferred_alternatives if x not in explicit_alternatives]

    # Discard alternatives matching the primary job title or trivial inflectional variations
    if primary_title:
        pt_norm = primary_title.lower().strip()
        pt_stem = re.sub(r"(?:ing|ed|s)$", "", pt_norm)
        filtered = []
        for a in all_candidates:
            a_norm = a.lower().strip()
            if a_norm == pt_norm or a_norm.rstrip("s") == pt_norm.rstrip("s"):
                continue
            # Discard if same words with only minor suffix change (e.g. 'digital image specialist' vs 'digital imaging specialist')
            a_stem = re.sub(r"(?:ing|ed|s)$", "", a_norm)
            if a_stem == pt_stem:
                continue
            filtered.append(a)
        all_candidates = filtered

    return all_candidates


def extract_job_title(jd_text: str) -> TitleExtractionResult:
    """Deterministically identifies the job title from job description text.
    Handles page markers (e.g. 'Title | 1'), metadata stripping, and confidence evaluation.
    """
    if not jd_text or not jd_text.strip():
        return TitleExtractionResult(
            title="Candidate Search",
            confidence_score=0.0,
            confidence_level="Low",
            warning="Job description is empty. Please paste or upload a JD.",
        )

    # Identify non-bullet standalone lines for primary title candidates
    raw_lines = jd_text.splitlines()
    non_empty_lines: list[str] = []
    for raw in raw_lines:
        s = raw.strip()
        if not s:
            continue
        # Lines with bullet markers or list numbers are bullet points, not titles
        if re.match(r"^(?:[\-*•·\uf0b7]|\d+[\.\)\]])\s+", s):
            continue
        cleaned = clean_title_candidate(s)
        if cleaned and not is_disqualified_as_title(cleaned):
            non_empty_lines.append(cleaned)

    # 1. First priority: Check for explicit label (e.g. "Job Title: ...")
    explicit = extract_explicit_labeled_title(jd_text)
    if explicit:
        alt_titles = extract_alternative_titles_from_overview(jd_text, primary_title=explicit)
        return TitleExtractionResult(
            title=explicit,
            alternative_titles=alt_titles[:4],
            confidence_score=0.95,
            confidence_level="High",
            detected_candidates=[explicit] + alt_titles,
        )

    # 2. Second priority: Search top 15 non-empty lines for prominent role titles
    title_candidates: list[tuple[str, float]] = []

    for i, line in enumerate(non_empty_lines[:15]):
        cleaned = clean_title_candidate(line)
        if is_disqualified_as_title(cleaned):
            continue

        # Check for role keywords
        matched_roles = [kw for kw in ROLE_KEYWORDS if re.search(rf"\b{kw}\b", cleaned, re.I)]
        if matched_roles:
            # Score this candidate:
            # Higher score for shorter lines (concise role names vs long sentences)
            word_count = len(cleaned.split())
            if word_count <= 5:
                # Top lines get higher position weight
                pos_weight = 1.0 - (i * 0.04)
                score = 0.8 * pos_weight
                # Boost if it matches title capitalization
                if cleaned[0].isupper():
                    score += 0.05
                title_candidates.append((cleaned, score))
            elif word_count <= 8 and not re.search(r"[.?!;]", cleaned):
                title_candidates.append((cleaned, 0.5 - (i * 0.02)))

    if title_candidates:
        # Sort candidates by score descending
        title_candidates.sort(key=lambda x: x[1], reverse=True)
        best_title, best_score = title_candidates[0]

        # Standardize capitalization of best title
        best_title_norm = " ".join(
            w.upper() if re.match(r"^(?:3D|2D|UI|UX|API|AI|ML|NPR)$", w, re.I) else w.capitalize()
            for w in best_title.split()
        )

        # Also extract alternative titles mentioned in body/overview using best_title_norm
        alt_from_body = extract_alternative_titles_from_overview(jd_text, primary_title=best_title_norm)

        # Collect alternatives
        all_alts = []
        for cand, _ in title_candidates[1:]:
            cand_norm = " ".join(
                w.upper() if re.match(r"^(?:3D|2D|UI|UX|API|AI|ML|NPR)$", w, re.I) else w.capitalize()
                for w in cand.split()
            )
            if cand_norm.lower() != best_title_norm.lower() and cand_norm not in all_alts:
                all_alts.append(cand_norm)

        for alt in alt_from_body:
            if alt.lower() != best_title_norm.lower() and alt not in all_alts:
                all_alts.append(alt)

        confidence_level = "High" if best_score >= 0.7 else "Medium"
        warning = None
        if len(all_alts) >= 2:
            warning = f"Multiple possible role titles detected ({', '.join([best_title_norm] + all_alts[:2])}). Please verify."

        return TitleExtractionResult(
            title=best_title_norm,
            alternative_titles=all_alts[:5],
            confidence_score=round(best_score, 2),
            confidence_level=confidence_level,
            detected_candidates=[best_title_norm] + all_alts[:5],
            warning=warning,
        )

    # 3. Fallback: If no role keyword found in top lines, check if alternative titles were found in body
    alt_from_body = extract_alternative_titles_from_overview(jd_text, primary_title="")
    if alt_from_body:
        primary = alt_from_body[0]
        alts = alt_from_body[1:]
        return TitleExtractionResult(
            title=primary,
            alternative_titles=alts[:4],
            confidence_score=0.6,
            confidence_level="Medium",
            detected_candidates=alt_from_body[:5],
            warning=f"Inferred title '{primary}' from job description text. Please verify or edit.",
        )

    # 4. Ultimate Fallback: Return first concise heading or default
    first_clean = non_empty_lines[0] if non_empty_lines and len(non_empty_lines[0].split()) <= 4 else "Candidate Search"
    return TitleExtractionResult(
        title=first_clean,
        alternative_titles=[],
        confidence_score=0.3,
        confidence_level="Low",
        detected_candidates=[first_clean],
        warning="Could not automatically confirm the exact job title with high confidence. Please edit before searching.",
    )


PLACEHOLDER_TITLES = {
    "", "candidate search", "new job", "search candidates", "job title",
    "untitled", "n/a", "none", "unknown", "test job", "test", "job",
}


def is_placeholder_title(title: str | None) -> bool:
    """Checks if a title is empty or a generic placeholder string."""
    if not title:
        return True
    clean = re.sub(r"\s*\(#?\d+\)\s*", "", title.strip().lower())
    clean = re.sub(r"\s*xray\s*test\s*role.*$", "", clean, flags=re.I).strip()
    if not clean or clean in PLACEHOLDER_TITLES:
        return True
    if any(p in clean for p in ["candidate search", "new job", "search candidates", "untitled"]):
        return True
    return False


def resolve_safe_title(raw_title: str | None, jd_text: str = "", fallback: str = "AI Generalist") -> str:
    """Canonical single-source-of-truth helper to resolve a clean, non-placeholder role title.
    1. If raw_title is valid and non-placeholder, normalizes and returns it (stripping test suffixes).
    2. If raw_title is missing/placeholder, attempts to extract a true title from jd_text.
    3. If extraction still yields a placeholder or jd_text is a stub, uses domain heuristics:
       - AI/ChatGPT/operations cues -> 'AI Generalist'
       - Developer/Backend/FastAPI cues -> 'Software Engineer'
       - Fallback argument.
    Guarantees 'Candidate Search' is NEVER returned.
    """
    if raw_title and not is_placeholder_title(raw_title):
        clean_name = re.sub(r"\s*XRay\s*Test\s*Role.*$", "", raw_title, flags=re.I).strip()
        if clean_name and not is_placeholder_title(clean_name):
            return clean_name
        return raw_title.strip()

    if jd_text and jd_text.strip():
        extracted = extract_job_title(jd_text)
        if extracted.title and not is_placeholder_title(extracted.title):
            return extracted.title

        jd_lower = jd_text.lower()
        if any(term in jd_lower for term in ["chatgpt", "generalist", "evaluator", "prompt", "ai training", "annotation", "documentation"]):
            return "AI Generalist"
        elif any(term in jd_lower for term in ["fastapi", "python", "backend", "fullstack", "react", "developer", "engineer"]):
            return "Software Engineer"

    return fallback

