from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus

from keyword_extractor import JobRequirements


@dataclass
class SearchQuery:
    id: int
    label: str
    strategy: str
    query_text: str
    google_url: str
    description: str
    bing_url: str = ""


def _quote(term: str) -> str:
    """Wraps a term in quotes if it contains spaces or symbols and isn't already quoted."""
    term = term.strip()
    if term.startswith('"') and term.endswith('"'):
        return term
    return f'"{term}"'


def _format_or_group(items: list[str]) -> str:
    """Formats a list of terms into an (A OR B OR C) clause."""
    quoted = [_quote(x) for x in items if x.strip()]
    if not quoted:
        return ""
    if len(quoted) == 1:
        return quoted[0]
    return f"({' OR '.join(quoted)})"


def generate_search_queries(
    requirements: JobRequirements,
    user_location: str = "",
    user_extra_titles: str = "",
) -> list[SearchQuery]:
    """Generates 6-12 varied, high-quality Boolean and Google X-Ray queries.
    Uses exact phrases, OR grouping, recruiter exclusions, and varied specificity levels.
    """
    primary_title = requirements.job_title.strip() or "Candidate Search"
    
    # Collect genuine alternative titles (excluding exact matches to primary title)
    titles = [primary_title]
    has_genuine_alternatives = False
    if user_extra_titles:
        for t in re.split(r"[,;\n|]", user_extra_titles):
            t_clean = t.strip()
            if t_clean and t_clean.lower() != primary_title.lower() and t_clean.lower() not in [x.lower() for x in titles]:
                titles.append(t_clean)
                has_genuine_alternatives = True
    for alt in requirements.alternative_titles:
        if alt.strip() and alt.strip().lower() != primary_title.lower() and alt.lower() not in [x.lower() for x in titles]:
            titles.append(alt.strip())
            has_genuine_alternatives = True

    # Location / Work Arrangement clause
    target_loc = user_location.strip() or requirements.location.strip()
    loc_items: list[str] = []
    if target_loc:
        parts = [p.strip() for p in re.split(r"[,;\n|]", target_loc) if p.strip()]
        loc_items = parts[:3]
        if "Remote" not in loc_items:
            loc_items.append("Remote")
    else:
        loc_items = ["Remote"]
    loc_clause = _format_or_group(loc_items)

    # Detect if we have actual geographic cities or countries vs purely remote/global
    geo_locations = [
        item for item in loc_items
        if item.lower() not in {"remote", "global", "worldwide", "anywhere", "work from home", "wfh"}
    ]

    # Core required skills (must-have) vs preferred skills (bonus)
    core_skills = requirements.required_skills[:4]
    tools = requirements.tools_and_tech
    pref_skills = requirements.preferred_skills[:4]

    # Creative / visual indicators in title or skills
    is_creative = any(
        kw in primary_title.lower() or any(kw in s.lower() for s in core_skills + tools)
        for kw in ["artist", "3d", "image", "visual", "animat", "design", "modeler", "blender", "zbrush", "photoshop", "creative"]
    )

    is_tech = any(
        kw in primary_title.lower() or any(kw in s.lower() for s in core_skills + tools)
        for kw in ["engineer", "developer", "backend", "frontend", "fullstack", "python", "software", "devops", "cloud", "data", "ml", "scientist"]
    )

    # Competition platforms for competitive data science roles
    KNOWN_COMPETITION_PLATFORMS = [
        "kaggle", "drivendata", "zindi", "aicrowd", "numerai", "datasource.ai", "codalab"
    ]
    detected_comp_platforms = [
        t for t in tools if any(p in t.lower() for p in KNOWN_COMPETITION_PLATFORMS)
    ]
    has_competitions = bool(detected_comp_platforms or "competitive" in primary_title.lower() or any("compet" in s.lower() for s in core_skills))

    recruiter_exclusions = "-intitle:jobs -inurl:jobs -job -jobs -hiring -careers -recruiter -apply"
    queries_data: list[tuple[str, str, str, str]] = []

    # 1. High-Precision: Exact Title + ALL Core Required Skills (Strict Evaluation)
    if core_skills:
        # Include all identified required skills up to 4 for true high precision
        skills_part = " ".join(_quote(s) for s in core_skills[:4])
        q1 = f'site:linkedin.com/in/ {_quote(primary_title)} {skills_part} {loc_clause} {recruiter_exclusions}'
        queries_data.append((
            "High Precision: Title + All Core Skills",
            "High Precision",
            q1,
            "Targets candidates with the exact job title who explicitly list all core required skills.",
        ))

    # 2. Alternative Titles OR Skill Synergy (Truthful Strategy Labeling)
    if has_genuine_alternatives:
        title_clause = _format_or_group(titles[:4])
        tools_or_skills = _format_or_group(tools[:3] if tools else core_skills[:3])
        q2 = f'site:linkedin.com/in/ {title_clause} {tools_or_skills} {loc_clause} {recruiter_exclusions}'
        queries_data.append((
            "Alternative Titles + Key Competencies",
            "Alternative Titles",
            q2,
            "Captures candidates using related role titles who work with core required skills or software.",
        ))
    else:
        # When no genuine alternative titles exist, replace with a Core Skill Synergy strategy
        if len(core_skills) >= 2:
            skill_a = _quote(core_skills[0])
            skill_b = _quote(core_skills[1])
            q2 = f'site:linkedin.com/in/ {_quote(primary_title)} {skill_a} {skill_b} {loc_clause} {recruiter_exclusions}'
            queries_data.append((
                "Core Skill Synergy: Primary Competencies",
                "Skill Synergy",
                q2,
                f"Targets practitioners with the exact title matching primary competencies ({core_skills[0]} and {core_skills[1]}).",
            ))

    # 3. Competition Experience (Dedicated strategy for competitive platforms)
    if has_competitions:
        comp_clause = _format_or_group(KNOWN_COMPETITION_PLATFORMS)
        q3 = f'site:linkedin.com/in/ {_quote(primary_title)} {comp_clause} {loc_clause} {recruiter_exclusions}'
        queries_data.append((
            "Competition Experience: Kaggle & Data Contests",
            "Competition Experience",
            q3,
            "Targets candidates highlighting competitive ML platforms (Kaggle, DrivenData, Zindi, AIcrowd, Numerai, CodaLab).",
        ))

    # 4. Evidence / Code Showcase Variation
    if is_creative or requirements.portfolio_required:
        portfolio_clause = '(portfolio OR "artstation.com" OR "behance.net" OR "dribbble.com")'
        q4 = f'site:linkedin.com/in/ {_quote(primary_title)} {portfolio_clause} {loc_clause} {recruiter_exclusions}'
        queries_data.append((
            "Creative Showcase: Profiles with Portfolios",
            "Portfolio / Evidence",
            q4,
            "Finds artists and specialists who link their ArtStation, Behance, or creative portfolio in their bio.",
        ))
    elif is_tech:
        code_clause = '("github.com" OR "gitlab.com" OR portfolio OR "open source")'
        q4 = f'site:linkedin.com/in/ {_quote(primary_title)} {code_clause} {loc_clause} {recruiter_exclusions}'
        queries_data.append((
            "Technical Showcase: Repositories & Open Source",
            "Portfolio / Evidence",
            q4,
            "Finds technical talent who highlight code repositories or open-source projects in their profiles.",
        ))

    # 5. Tool & Workflow Centric (Discovers practitioners based on toolstack rather than rigid title)
    if tools and core_skills:
        combined_tools = []
        for x in tools[:3] + core_skills[:2]:
            if x not in combined_tools:
                combined_tools.append(x)
        tool_or_skill = _format_or_group(combined_tools[:4])
        q5 = f'site:linkedin.com/in/ {tool_or_skill} {loc_clause} ("senior" OR "lead" OR "specialist" OR "practitioner") {recruiter_exclusions}'
        queries_data.append((
            "Workflow & Tool Centric Search",
            "Skill Centric",
            q5,
            "Discovers talent based on daily tool usage and techniques rather than exact title wording.",
        ))
    elif core_skills:
        skills_clause = " ".join(_quote(s) for s in core_skills[:3])
        q5 = f'site:linkedin.com/in/ {skills_clause} {loc_clause} {recruiter_exclusions}'
        queries_data.append((
            "Skill Density Match",
            "Skill Centric",
            q5,
            "Matches candidates with strong multi-skill profiles in your domain.",
        ))

    # 6. Location Focus OR Work Arrangement (Truthful Strategy Labeling)
    if geo_locations:
        region_clause = _format_or_group(geo_locations[:2])
        tool_or_skill = _quote(tools[0]) if tools else (_quote(core_skills[0]) if core_skills else "")
        q6 = f'site:linkedin.com/in/ {_quote(primary_title)} {tool_or_skill} {region_clause} {recruiter_exclusions}'
        queries_data.append((
            "Location-Targeted Search",
            "Location Focus",
            q6,
            f"Filters candidates specifically residing in or around {', '.join(geo_locations[:2])}.",
        ))
    else:
        # Pure remote/global arrangement
        work_arr_clause = '("Remote" OR "Worldwide" OR "Global" OR "Work from home")'
        q6 = f'site:linkedin.com/in/ {_quote(primary_title)} {work_arr_clause} {recruiter_exclusions}'
        queries_data.append((
            "Work Arrangement: Remote & Global Availability",
            "Work Arrangement",
            q6,
            "Targets professionals explicitly indicating remote, global, or work-from-home availability.",
        ))

    # 7. Available / Contract / Freelance Talent (Dedicated Contractor query)
    avail_terms = '("contractor" OR "freelance" OR "open to work" OR "consultant" OR "available")'
    q7 = f'site:linkedin.com/in/ {_quote(primary_title)} {avail_terms} {loc_clause} {recruiter_exclusions}'
    queries_data.append((
        "Active Talent: Contractor & Freelance",
        "Availability",
        q7,
        "Identifies specialists explicitly signaling contractor, freelance, or immediate consulting availability.",
    ))

    # 8. Broad Role Discovery (Exact Title Baseline)
    q8 = f'site:linkedin.com/in/ {_quote(primary_title)} {loc_clause} {recruiter_exclusions}'
    queries_data.append((
        "Broad Discovery: Exact Title Baseline",
        "Broad Discovery",
        q8,
        "Baseline search across all candidate profiles with this exact job title.",
    ))

    # 9. Multi-tool / Platform Synergy (if 2+ tools exist)
    if len(tools) >= 2:
        two_tools = " ".join(_quote(t) for t in tools[:2])
        q9 = f'site:linkedin.com/in/ {two_tools} {_quote(primary_title)} {loc_clause} {recruiter_exclusions}'
        queries_data.append((
            "Tool Synergy Search",
            "Tool Synergy",
            q9,
            f"Requires proficiency in both {tools[0]} and {tools[1]} simultaneously.",
        ))

    # 10. Preferred / Bonus Qualifications Search (Separated from required skills)
    if pref_skills:
        pref_clause = _format_or_group(pref_skills[:3])
        q10 = f'site:linkedin.com/in/ {_quote(primary_title)} {pref_clause} {loc_clause} {recruiter_exclusions}'
        queries_data.append((
            "Bonus Qualifications: Preferred Skills Synergy",
            "Preferred Skills",
            q10,
            "Targets candidates with the core title who also highlight preferred/bonus qualifications.",
        ))

    # 11. Public Web Candidate Search (Outside LinkedIn)
    evidence_terms = '(resume OR CV OR portfolio OR "about me" OR "profile")'
    skill_snippet = _quote(core_skills[0]) if core_skills else (_quote(tools[0]) if tools else "")
    q11 = f'{_quote(primary_title)} {skill_snippet} {loc_clause} {evidence_terms} -intitle:jobs -jobs -careers'
    queries_data.append((
        "Public Web: Resumes & Portfolios Outside LinkedIn",
        "Public Web",
        q11,
        "Searches personal websites, PDF resumes, and talent directories outside LinkedIn.",
    ))

    # Build final list, normalizing whitespace and deduplicating
    results: list[SearchQuery] = []
    seen_queries = set()
    query_id = 1

    for label, strategy, raw_q, desc in queries_data:
        normalized_q = re.sub(r"\s+", " ", raw_q).strip()
        if normalized_q not in seen_queries:
            seen_queries.add(normalized_q)
            results.append(
                SearchQuery(
                    id=query_id,
                    label=label,
                    strategy=strategy,
                    query_text=normalized_q,
                    google_url="https://www.google.com/search?q=" + quote_plus(normalized_q),
                    description=desc,
                    bing_url="https://www.bing.com/search?q=" + quote_plus(normalized_q),
                )
            )
            query_id += 1

    return results
