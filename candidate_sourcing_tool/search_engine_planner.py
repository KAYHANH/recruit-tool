from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import quote_plus
from keyword_extractor import JobRequirements


@dataclass
class XRayStrategy:
    key: str  # "Strategy A", "Strategy B", etc.
    name: str
    target_platform: str  # "LinkedIn Profiles", "Public Web & CVs", "Code & Repositories", "General Web"
    category: str
    query_text: str
    google_url: str
    bing_url: str
    description: str
    search_operator_breakdown: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class XRaySearchPlan:
    job_id: int | None
    job_title: str
    location: str
    strategies: list[XRayStrategy] = field(default_factory=list)
    total_strategies: int = 0
    batch_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["strategies"] = [s.to_dict() for s in self.strategies]
        return d


def _quote(term: str) -> str:
    """Wraps a term in quotes if it contains spaces or symbols and isn't already quoted."""
    term = term.strip()
    if not term:
        return ""
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


class SearchEnginePlanner:
    """Generates structured, professional Google X-Ray and Boolean search strategies (A through G).
    Zero budget, zero scraping: queries are prepared for compliant browser-assisted recruiter sourcing.
    """

    RECRUITER_EXCLUSIONS = "-intitle:jobs -inurl:jobs -job -jobs -hiring -careers -recruiter -apply"

    def plan_job_search(
        self,
        requirements: JobRequirements,
        job_id: int | None = None,
        target_location: str = "",
        extra_titles: str = "",
        role_family: str = "",
    ) -> XRaySearchPlan:
        """Constructs Strategies A through G tailored to the job requirements."""
        from talent_pool_mapper import talent_pool_mapper, ROLE_FAMILY_AI_GENERALIST_OPERATIONS

        primary_title = requirements.job_title.strip() or "Software Engineer"

        # Safety guard: if the title is a known bad placeholder (user save name leaked through),
        # replace it with the role-appropriate default rather than building broken queries.
        _BAD_TITLE_PLACEHOLDERS = {
            "new job", "candidate search", "search candidates",
            "job title", "untitled", "test job", "test", "job",
        }
        if primary_title.lower() in _BAD_TITLE_PLACEHOLDERS:
            primary_title = "AI Generalist" if any(
                kw in " ".join(requirements.required_skills).lower()
                for kw in ["chatgpt", "ai", "evaluation", "annotation", "generalist"]
            ) else "Software Engineer"

        # Determine role family if not provided
        if not role_family:
            role_family = talent_pool_mapper.detect_role_family(primary_title, requirements.required_skills)

        # Build alternative titles
        titles = [primary_title]
        if extra_titles:
            for t in re.split(r"[,;\n|]", extra_titles):
                t_clean = t.strip()
                if t_clean and t_clean.lower() != primary_title.lower() and t_clean.lower() not in [x.lower() for x in titles]:
                    titles.append(t_clean)
        for alt in requirements.alternative_titles:
            alt_clean = alt.strip()
            if alt_clean and alt_clean.lower() != primary_title.lower() and alt_clean.lower() not in [x.lower() for x in titles]:
                titles.append(alt_clean)

        # Location parsing
        loc = target_location.strip() or requirements.location.strip()
        loc_items: list[str] = []
        if loc:
            parts = [p.strip() for p in re.split(r"[,;\n|]", loc) if p.strip()]
            loc_items = parts[:3]
            if "Remote" not in loc_items:
                loc_items.append("Remote")
        else:
            loc_items = ["Remote"]
        loc_clause = _format_or_group(loc_items)

        core_skills = requirements.required_skills
        tools = requirements.tools_and_tech
        pref_skills = requirements.preferred_skills

        # Eliminate duplicate title terms from skills to avoid "Generalist" "Generalist"
        effective_skills = [
            s for s in core_skills
            if s.strip().lower() != primary_title.lower()
            and s.strip().lower() not in primary_title.lower()
        ]
        if not effective_skills and core_skills:
            effective_skills = core_skills

        is_generalist_ops = (role_family == ROLE_FAMILY_AI_GENERALIST_OPERATIONS)

        strategies: list[XRayStrategy] = []

        # =====================================================================
        # Strategy A: Public LinkedIn Profile Discovery (site:linkedin.com/in/)
        # =====================================================================
        skills_subset = effective_skills[:3]
        skills_str = " ".join(_quote(s) for s in skills_subset) if skills_subset else ""
        raw_qa = f'site:linkedin.com/in/ {_quote(primary_title)} {skills_str} {loc_clause} {self.RECRUITER_EXCLUSIONS}'
        qa = re.sub(r"\s+", " ", raw_qa).strip()
        strategies.append(
            XRayStrategy(
                key="Strategy A",
                name="Public LinkedIn Profile Discovery",
                target_platform="LinkedIn Profiles",
                category="X-Ray Profiles",
                query_text=qa,
                google_url="https://www.google.com/search?q=" + quote_plus(qa),
                bing_url="https://www.bing.com/search?q=" + quote_plus(qa),
                description="Targets publicly indexed LinkedIn member profiles with the exact job title and core skills while filtering out job postings and recruiters.",
                search_operator_breakdown=[
                    "site:linkedin.com/in/ (restricts to individual profile pages)",
                    f'"{primary_title}" (exact title match)',
                    "Exclusions: -job -jobs -hiring -careers -recruiter",
                ],
            )
        )

        # =====================================================================
        # Strategy B: Exact Title & Core Skills (Strict Match)
        # =====================================================================
        if len(effective_skills) >= 2:
            exact_skills = " AND ".join(_quote(s) for s in effective_skills[:3])
            raw_qb = f'site:linkedin.com/in/ ({_quote(primary_title)}) {exact_skills} {loc_clause} {self.RECRUITER_EXCLUSIONS}'
        else:
            raw_qb = f'site:linkedin.com/in/ {_quote(primary_title)} {loc_clause} {self.RECRUITER_EXCLUSIONS}'
        qb = re.sub(r"\s+", " ", raw_qb).strip()
        strategies.append(
            XRayStrategy(
                key="Strategy B",
                name="Exact Title & Core Skills Synergy",
                target_platform="LinkedIn Profiles",
                category="High Precision",
                query_text=qb,
                google_url="https://www.google.com/search?q=" + quote_plus(qb),
                bing_url="https://www.bing.com/search?q=" + quote_plus(qb),
                description="Enforces strict co-occurrence of the exact job title and must-have core skills for high-fidelity sourcing.",
                search_operator_breakdown=[
                    "Strict multi-keyword boolean conjunction",
                    "Co-occurrence of primary qualifications",
                    "Zero noise job-board suppression",
                ],
            )
        )

        # =====================================================================
        # Strategy C: Alternative Titles & Related Terminology
        # =====================================================================
        alt_title_group = _format_or_group(titles[:4])
        tools_or_skills = _format_or_group(tools[:3] if tools else effective_skills[:3])
        raw_qc = f'site:linkedin.com/in/ {alt_title_group} {tools_or_skills} {loc_clause} {self.RECRUITER_EXCLUSIONS}'
        qc = re.sub(r"\s+", " ", raw_qc).strip()
        strategies.append(
            XRayStrategy(
                key="Strategy C",
                name="Alternative Titles & Synonyms",
                target_platform="LinkedIn Profiles",
                category="Title Diversity",
                query_text=qc,
                google_url="https://www.google.com/search?q=" + quote_plus(qc),
                bing_url="https://www.bing.com/search?q=" + quote_plus(qc),
                description="Captures qualified practitioners operating under alternative or modern variant role titles in the talent market.",
                search_operator_breakdown=[
                    f"Title grouping: {alt_title_group}",
                    "Captures non-standard corporate designations",
                    "Maintains technical skill requirements",
                ],
            )
        )

        # =====================================================================
        # Strategy D: Domain Expertise & Role Specialization
        # =====================================================================
        tech_elements = tools[:4] if tools else effective_skills[:4]
        if is_generalist_ops:
            qualifiers = '("evaluator" OR "specialist" OR "trainer" OR "contractor" OR "expert" OR "rater")'
        else:
            qualifiers = '("architect" OR "senior" OR "lead" OR "specialist" OR "engineer")'

        if tech_elements:
            tech_clause = " ".join(_quote(t) for t in tech_elements[:3])
            raw_qd = f'site:linkedin.com/in/ {tech_clause} {qualifiers} {loc_clause} {self.RECRUITER_EXCLUSIONS}'
        else:
            domain_terms = '("evaluation" OR "workflows" OR "operations")' if is_generalist_ops else '("framework" OR "platform" OR "cloud")'
            raw_qd = f'site:linkedin.com/in/ {_quote(primary_title)} {domain_terms} {loc_clause} {self.RECRUITER_EXCLUSIONS}'
        qd = re.sub(r"\s+", " ", raw_qd).strip()
        strategies.append(
            XRayStrategy(
                key="Strategy D",
                name="Domain Expertise & Role Specialization",
                target_platform="LinkedIn Profiles",
                category="Platform & Stack",
                query_text=qd,
                google_url="https://www.google.com/search?q=" + quote_plus(qd),
                bing_url="https://www.bing.com/search?q=" + quote_plus(qd),
                description="Discovers hands-on subject matter experts based on specific platform competencies, framework depth, and tooling seniority.",
                search_operator_breakdown=[
                    "Toolstack & platform-first indexing",
                    f"Seniority and specialization qualifiers: {qualifiers}",
                    "Discovers specialists regardless of exact title wording",
                ],
            )
        )

        # =====================================================================
        # Strategy E: Public CVs, Portfolios & Professional Websites
        # =====================================================================
        cv_indicators = '(filetype:pdf OR filetype:doc OR filetype:docx OR inurl:resume OR inurl:cv)'
        primary_skill = _quote(effective_skills[0]) if effective_skills else ""
        raw_qe = f'{_quote(primary_title)} {primary_skill} {cv_indicators} {loc_clause} -intitle:jobs -jobs -careers -templates -sample'
        qe = re.sub(r"\s+", " ", raw_qe).strip()
        strategies.append(
            XRayStrategy(
                key="Strategy E",
                name="Public CVs & Professional Resumes",
                target_platform="Public Web & CVs",
                category="Unindexed Resumes",
                query_text=qe,
                google_url="https://www.google.com/search?q=" + quote_plus(qe),
                bing_url="https://www.bing.com/search?q=" + quote_plus(qe),
                description="Finds public PDF and DOC resumes, portfolio documents, and curriculum vitae published openly on the web outside LinkedIn.",
                search_operator_breakdown=[
                    "filetype:pdf OR filetype:doc (direct resume documents)",
                    "inurl:resume OR inurl:cv (hosted candidate resume pages)",
                    "Negative filters: -templates -sample -jobs",
                ],
            )
        )

        # =====================================================================
        # Strategy F: Public Evidence & Domain Contributions
        # =====================================================================
        if is_generalist_ops:
            evidence_sites = '(site:medium.com OR site:substack.com OR inurl:blog OR site:notion.site OR site:linkedin.com/pulse)'
            domain_skill = _quote(effective_skills[0]) if effective_skills else '"AI tools"'
            raw_qf = f'{evidence_sites} {_quote(primary_title)} {domain_skill} ("evaluation" OR "prompt" OR "workflow" OR "guidelines" OR "documentation") -intitle:jobs -jobs'
        else:
            tech_sites = '(site:github.io OR site:gitlab.io OR site:medium.com OR site:dev.to OR inurl:blog)'
            code_skill = _quote(effective_skills[0]) if effective_skills else (_quote(tools[0]) if tools else "")
            raw_qf = f'{tech_sites} {_quote(primary_title)} {code_skill} ("portfolio" OR "projects" OR "open source" OR "author") -intitle:jobs -jobs'
        qf = re.sub(r"\s+", " ", raw_qf).strip()
        strategies.append(
            XRayStrategy(
                key="Strategy F",
                name="Public Evidence & Domain Contributions",
                target_platform="Code & Repositories" if not is_generalist_ops else "Articles & Professional Portfolios",
                category="Developer Evidence" if not is_generalist_ops else "Domain Evidence",
                query_text=qf,
                google_url="https://www.google.com/search?q=" + quote_plus(qf),
                bing_url="https://www.bing.com/search?q=" + quote_plus(qf),
                description="Identifies talent through public writing, project showcases, guidelines, and domain portfolio footprints.",
                search_operator_breakdown=[
                    "Domain publication hosts and personal portfolio sites",
                    "Evidence keywords tailored to role requirements",
                    "Excludes commercial job boards and aggregator postings",
                ],
            )
        )

        # =====================================================================
        # Strategy G: Broader Discovery (Adjacent Terminology & Global Scope)
        # =====================================================================
        broad_terms = _format_or_group(effective_skills[:2] + pref_skills[:2]) if (effective_skills or pref_skills) else _quote(primary_title)
        if is_generalist_ops:
            broad_qualifiers = '("specialist" OR "practitioner" OR "evaluator" OR "rater" OR "consultant")'
        else:
            broad_qualifiers = '("specialist" OR "practitioner" OR "consultant" OR "engineer")'
        raw_qg = f'site:linkedin.com/in/ {_quote(primary_title)} {broad_terms} {broad_qualifiers} {self.RECRUITER_EXCLUSIONS}'
        qg = re.sub(r"\s+", " ", raw_qg).strip()
        strategies.append(
            XRayStrategy(
                key="Strategy G",
                name="Broader Discovery & Adjacent Terminology",
                target_platform="General Web",
                category="Wide Net",
                query_text=qg,
                google_url="https://www.google.com/search?q=" + quote_plus(qg),
                bing_url="https://www.bing.com/search?q=" + quote_plus(qg),
                description="Casts an expanded net across adjacent terminology, consulting profiles, and cross-functional practitioners.",
                search_operator_breakdown=[
                    "Broad Boolean OR expansion across core and preferred skills",
                    "Expanded professional role classifications",
                    "Captures passive talent with non-linear career trajectories",
                ],
            )
        )

        # Batch URLs for 1-click batch browser launch (top 4 high-yield strategies: A, B, E, F)
        batch_urls = [s.google_url for s in strategies[:4]]

        return XRaySearchPlan(
            job_id=job_id,
            job_title=primary_title,
            location=loc,
            strategies=strategies,
            total_strategies=len(strategies),
            batch_urls=batch_urls,
        )


search_engine_planner = SearchEnginePlanner()
plan_job_search = search_engine_planner.plan_job_search
