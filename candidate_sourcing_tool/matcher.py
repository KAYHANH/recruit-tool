from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from keyword_extractor import KNOWN_SKILLS, KNOWN_TOOLS, JobRequirements
from talent_pool_mapper import talent_pool_mapper, ROLE_FAMILY_AI_GENERALIST_OPERATIONS


@dataclass
class CriterionMatch:
    requirement: str
    category: str  # "Core Skill", "Tool & Software", "Preferred Skill", "Role Alignment", "Location", "Portfolio"
    status: str    # "Matched", "Needs review", "Not found", "Contradictory"
    evidence_snippet: str = ""
    notes: str = ""


@dataclass
class ScoringWeights:
    core_skills: int = 40
    tools: int = 25
    role_alignment: int = 15
    location: int = 10
    portfolio: int = 10

    def total(self) -> int:
        return self.core_skills + self.tools + self.role_alignment + self.location + self.portfolio


@dataclass
class CandidateEvaluation:
    candidate_id: int | None
    candidate_name: str
    total_score: int  # 0 to 100
    confidence: str   # "High", "Medium", "Low"
    word_count: int
    criteria_matches: list[CriterionMatch] = field(default_factory=list)
    matched_count: int = 0
    needs_review_count: int = 0
    not_found_count: int = 0
    contradictory_count: int = 0
    verified_criteria_count: int = 0
    unverified_criteria_count: int = 0
    evidence_coverage_pct: int = 0
    confidence_adjusted_score: int = 0
    coverage_advisory: str = ""
    score_breakdown: dict[str, int] = field(default_factory=dict)
    summary_matched: list[str] = field(default_factory=list)
    summary_missing: list[str] = field(default_factory=list)
    evidence_tier: str = "Tier 2: Moderate Technical Evidence"
    source_reliability: str = "High (Verified Code / API)"
    contact_availability: str = "Profile Link Only"
    disclaimer: str = (
        "Scores are transparent heuristic indicators based solely on reviewed text. "
        "Missing evidence in a CV or snippet does NOT prove a candidate lacks ability. "
        "Manual recruiter verification is required."
    )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["criteria_matches"] = [asdict(c) for c in self.criteria_matches]
        return d


def _find_snippet(text: str, term: str, window: int = 60) -> str:
    """Finds a contextual sentence/phrase snippet around a matched keyword."""
    idx = text.lower().find(term.lower())
    if idx == -1:
        return ""
    start = max(0, idx - window)
    end = min(len(text), idx + len(term) + window)
    snippet = text[start:end].strip()
    # Add ellipsis if truncated
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def _check_contradiction(text_lower: str, term_lower: str) -> bool:
    """Detects explicit negative assertions (e.g. 'no Blender experience', 'not open to contract')."""
    negation_patterns = [
        rf"\b(?:no|not|never|lack|lacking|without)\b[^\n.]{{1,25}}\b{re.escape(term_lower)}\b",
        rf"\b{re.escape(term_lower)}\b[^\n.]{{1,25}}\b(?:not\s+supported|not\s+experienced|no\s+experience)\b",
    ]
    return any(re.search(p, text_lower) for p in negation_patterns)


def evaluate_candidate(
    candidate: dict,
    requirements: JobRequirements,
    target_location: str = "",
    weights: ScoringWeights | None = None,
    role_family: str = "",
) -> CandidateEvaluation:
    """Evaluates a candidate's supplied evidence against explicit job requirements.
    Classifies every criterion into Matched, Needs review, Not found, or Contradictory.
    Scoring weights are fully configurable via ScoringWeights.
    """
    if weights is None:
        weights = ScoringWeights()

    if not role_family:
        role_family = talent_pool_mapper.detect_role_family(requirements.job_title, requirements.required_skills)
    is_generalist_ops = (role_family == ROLE_FAMILY_AI_GENERALIST_OPERATIONS)

    cand_id = candidate.get("id")
    name = candidate.get("name") or "Unnamed candidate"
    headline = (candidate.get("headline") or "").strip()
    experience = (candidate.get("experience") or "").strip()
    notes = (candidate.get("notes") or "").strip()
    location = (candidate.get("location") or "").strip()
    evidence_text = (candidate.get("evidence_text") or "").strip()
    skills = (candidate.get("skills") or "").strip()

    candidate_text = f"{headline}\n{skills}\n{experience}\n{location}\n{evidence_text}".strip()
    cand_lower = candidate_text.lower()
    combined_text = f"{candidate_text}\n{notes}".strip()
    text_lower = combined_text.lower()

    # Word count and confidence evaluation
    words = [w for w in re.findall(r"\b\w+\b", candidate_text) if len(w) > 1]
    word_count = len(words)
    if word_count < 25:
        confidence = "Low"
    elif word_count < 80:
        confidence = "Medium"
    else:
        confidence = "High"

    criteria: list[CriterionMatch] = []
    summary_matched: list[str] = []
    summary_missing: list[str] = []

    # 1. Evaluate Core Required Skills
    req_skills_score = 0
    max_req_skills = max(1, len(requirements.required_skills))
    matched_req_skills = 0

    for skill in requirements.required_skills:
        aliases = KNOWN_SKILLS.get(skill.lower(), [skill])
        # Check contradiction only on candidate's own text (not recruiter notes)
        if _check_contradiction(cand_lower, skill):
            criteria.append(
                CriterionMatch(
                    requirement=skill,
                    category="Core Skill",
                    status="Contradictory",
                    evidence_snippet=_find_snippet(candidate_text, skill),
                    notes=f"Candidate profile explicitly states lack of experience in '{skill}'.",
                )
            )
            summary_missing.append(f"{skill} (Contradicted)")
            continue

        # Check positive match
        found_alias = None
        for a in aliases:
            pattern = rf"(?<!\w){re.escape(a.lower())}(?!\w)"
            if re.search(pattern, text_lower):
                found_alias = a
                break

        if found_alias:
            matched_req_skills += 1
            summary_matched.append(skill)
            criteria.append(
                CriterionMatch(
                    requirement=skill,
                    category="Core Skill",
                    status="Matched",
                    evidence_snippet=_find_snippet(combined_text, found_alias),
                    notes="Explicit evidence observed in supplied text.",
                )
            )
        else:
            # Check for partial/inferred match (e.g. single word in multiword skill)
            parts = [p for p in skill.split() if len(p) > 3 and p.lower() not in {"creation", "design", "workflow", "proficiency", "skills"}]
            partial = any(re.search(rf"\b{re.escape(p)}\b", text_lower) for p in parts)
            if partial:
                criteria.append(
                    CriterionMatch(
                        requirement=skill,
                        category="Core Skill",
                        status="Needs review",
                        evidence_snippet="",
                        notes="Partial keyword mention detected. Requires manual recruiter inspection.",
                    )
                )
            else:
                summary_missing.append(skill)
                criteria.append(
                    CriterionMatch(
                        requirement=skill,
                        category="Core Skill",
                        status="Not found",
                        evidence_snippet="",
                        notes="No evidence observed in supplied text; candidate may still possess this skill.",
                    )
                )

    # Core required skills scoring with configurable weight
    if requirements.required_skills:
        target_skill_count = min(6, max_req_skills)
        req_skills_score = round(min(weights.core_skills, (matched_req_skills / target_skill_count) * weights.core_skills))
    else:
        req_skills_score = 0

    # 2. Evaluate Tools & Software
    tools_score = 0
    has_explicit_tools = bool(requirements.tools_and_tech)

    if has_explicit_tools:
        max_tools = max(1, len(requirements.tools_and_tech))
        matched_tools = 0
        for tool in requirements.tools_and_tech:
            aliases = KNOWN_TOOLS.get(tool.lower(), [tool])
            if _check_contradiction(cand_lower, tool):
                criteria.append(
                    CriterionMatch(
                        requirement=tool,
                        category="Tool & Software",
                        status="Contradictory",
                        evidence_snippet=_find_snippet(candidate_text, tool),
                        notes=f"Candidate profile explicitly states lack of '{tool}' experience.",
                    )
                )
                continue

            found_tool = None
            for a in aliases:
                pattern = rf"(?<!\w){re.escape(a.lower())}(?!\w)"
                if re.search(pattern, text_lower):
                    found_tool = a
                    break

            if found_tool:
                matched_tools += 1
                summary_matched.append(tool)
                criteria.append(
                    CriterionMatch(
                        requirement=tool,
                        category="Tool & Software",
                        status="Matched",
                        evidence_snippet=_find_snippet(combined_text, found_tool),
                        notes="Tool proficiency confirmed in supplied evidence.",
                    )
                )
            else:
                summary_missing.append(tool)
                criteria.append(
                    CriterionMatch(
                        requirement=tool,
                        category="Tool & Software",
                        status="Not found",
                        evidence_snippet="",
                        notes=f"Tool '{tool}' not mentioned in supplied profile text.",
                    )
                )
        target_tool_count = min(3, max_tools)
        tools_score = round(min(weights.tools, (matched_tools / target_tool_count) * weights.tools))
    else:
        # Check if tools are in preferred skills or core skills
        inferred_tools = [s for s in (requirements.required_skills + requirements.preferred_skills) if s.lower() in KNOWN_TOOLS]
        if inferred_tools:
            matched_inf = sum(1 for t in inferred_tools if any(re.search(rf"(?<!\w){re.escape(a.lower())}(?!\w)", text_lower) for a in KNOWN_TOOLS.get(t.lower(), [t])))
            tools_score = round(min(weights.tools, (matched_inf / max(1, len(inferred_tools))) * weights.tools))
        else:
            tools_score = 0

    # 3. Role Title & Domain Alignment
    role_score = 0
    titles_to_check = [requirements.job_title] + requirements.alternative_titles
    title_matched = False
    for t in titles_to_check:
        t_clean = t.strip().lower()
        if t_clean and t_clean in text_lower:
            title_matched = True
            criteria.append(
                CriterionMatch(
                    requirement=t,
                    category="Role Alignment",
                    status="Matched",
                    evidence_snippet=_find_snippet(combined_text, t),
                    notes=f"Direct role title match '{t}' found in candidate headline or history.",
                )
            )
            break

    if title_matched:
        role_score = weights.role_alignment
    elif is_generalist_ops:
        gen_adjacent = [
            "ai generalist", "ai evaluator", "ai trainer", "model evaluator",
            "rlhf specialist", "data annotator", "quality rater", "operations specialist",
            "prompt evaluator", "content rater", "evaluation specialist"
        ]
        found_gen = next((g for g in gen_adjacent if g in text_lower), None)
        if found_gen:
            role_score = round(weights.role_alignment * 0.8)
            criteria.append(
                CriterionMatch(
                    requirement=requirements.job_title,
                    category="Role Alignment",
                    status="Matched",
                    evidence_snippet=_find_snippet(combined_text, found_gen),
                    notes=f"Adjacent generalist/operations title '{found_gen}' matched.",
                )
            )
        else:
            eng_titles = ["engineer", "developer", "architect", "programmer", "creator of fastapi", "backend", "fullstack"]
            is_eng = any(e in headline.lower() for e in eng_titles)
            if is_eng:
                role_score = 0
                criteria.append(
                    CriterionMatch(
                        requirement=requirements.job_title,
                        category="Role Alignment",
                        status="Not found",
                        notes=f"Candidate headline '{headline}' is technical engineering; distinct from Generalist role.",
                    )
                )
            else:
                criteria.append(
                    CriterionMatch(
                        requirement=requirements.job_title,
                        category="Role Alignment",
                        status="Not found",
                        notes="Job title not observed in candidate profile/headline.",
                    )
                )
    else:
        title_terms = [w for w in re.findall(r"\b\w+\b", requirements.job_title.lower()) if len(w) > 3]
        term_hits = sum(1 for w in title_terms if w in text_lower)
        if term_hits >= 1:
            role_score = round(weights.role_alignment * 0.5)
            criteria.append(
                CriterionMatch(
                    requirement=requirements.job_title,
                    category="Role Alignment",
                    status="Needs review",
                    notes="Related domain words present; exact role title not explicitly matched.",
                )
            )
        else:
            criteria.append(
                CriterionMatch(
                    requirement=requirements.job_title,
                    category="Role Alignment",
                    status="Not found",
                    notes="Job title not observed in candidate profile/headline.",
                )
            )

    # 4. Location & Country Constraint Alignment
    loc_score = 0
    active_loc = (target_location or requirements.location).strip().lower()
    cand_loc = location.strip()
    cand_loc_lower = cand_loc.lower()

    us_target = any(u in active_loc for u in ["united states", "usa", "u.s.", "u.s.a", " us"]) or active_loc == "us"
    foreign_to_us_indicators = [
        "germany", "berlin", "brazil", "maceió", "maceio", "india", "pakistan",
        "uk", "united kingdom", "london", "europe", "france", "paris", "canada",
        "toronto", "vancouver", "australia", "poland", "ukraine", "odesa", "kyiv",
        "turkey", "istanbul", "nigeria", "lagos", "egypt", "spain", "madrid", "italy",
        "netherlands", "amsterdam", "switzerland", "sweden", "japan", "tokyo", "china",
        "earth"
    ]
    us_loc_indicators = [
        "united states", "usa", "u.s.", "u.s.a", "california", "texas", "new york", "florida",
        "washington", "austin", "san francisco", "seattle", "chicago", "boston", "los angeles",
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in",
        "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv",
        "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn",
        "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy"
    ]

    if us_target:
        is_cand_us = any(re.search(rf"\b{re.escape(w)}\b", cand_loc_lower) for w in us_loc_indicators)
        is_cand_foreign = any(re.search(rf"\b{re.escape(w)}\b", cand_loc_lower) for w in foreign_to_us_indicators)

        if is_cand_foreign:
            loc_score = 0
            criteria.append(
                CriterionMatch(
                    requirement="Location: United States (Remote/Contract)",
                    category="Location",
                    status="Contradictory",
                    evidence_snippet=cand_loc,
                    notes=f"Candidate is based in '{cand_loc}', conflicting with mandatory United States location constraint.",
                )
            )
        elif is_cand_us:
            loc_score = weights.location
            criteria.append(
                CriterionMatch(
                    requirement="Location: United States (Remote/Contract)",
                    category="Location",
                    status="Matched",
                    evidence_snippet=cand_loc,
                    notes="Candidate location verified within United States.",
                )
            )
        elif "remote" in cand_loc_lower:
            loc_score = round(weights.location * 0.4)
            criteria.append(
                CriterionMatch(
                    requirement="Location: United States (Remote/Contract)",
                    category="Location",
                    status="Needs review",
                    notes="Candidate indicates remote availability; US contract eligibility requires confirmation.",
                )
            )
        else:
            loc_score = 0
            criteria.append(
                CriterionMatch(
                    requirement="Location: United States (Remote/Contract)",
                    category="Location",
                    status="Not found",
                    notes="Candidate location unspecified or unconfirmed for US contract eligibility.",
                )
            )
    else:
        is_remote_job = "remote" in active_loc or not active_loc
        if is_remote_job:
            loc_score = weights.location
            criteria.append(
                CriterionMatch(
                    requirement="Remote / Flexible Location",
                    category="Location",
                    status="Matched",
                    notes="Job is remote-friendly; candidate eligible regardless of region.",
                )
            )
        else:
            loc_parts = [p.strip() for p in re.split(r"[,;\n]", active_loc) if p.strip()]
            matched_loc_part = any(p in cand_loc_lower for p in loc_parts)
            if matched_loc_part:
                loc_score = weights.location
                criteria.append(
                    CriterionMatch(
                        requirement=target_location or requirements.location,
                        category="Location",
                        status="Matched",
                        evidence_snippet=cand_loc,
                        notes="Candidate location matches specified target region.",
                    )
                )
            elif "remote" in cand_loc_lower:
                loc_score = round(weights.location * 0.5)
                criteria.append(
                    CriterionMatch(
                        requirement=target_location or requirements.location,
                        category="Location",
                        status="Needs review",
                        notes="Candidate indicates remote availability; location differs from primary target.",
                    )
                )
            else:
                loc_score = 0
                criteria.append(
                    CriterionMatch(
                        requirement=target_location or requirements.location,
                        category="Location",
                        status="Not found",
                        notes="Candidate location not confirmed in target area.",
                    )
                )

    # 5. Portfolio Check
    portfolio_score = 0
    has_portfolio_evidence = bool(re.search(r"\b(?:portfolio|artstation|behance|dribbble|vimeo|promptfoo|substack|notion)\b", text_lower))
    if not is_generalist_ops:
        has_portfolio_evidence = has_portfolio_evidence or bool(re.search(r"\b(?:github|gitlab)\b", text_lower))

    if requirements.portfolio_required:
        if _check_contradiction(cand_lower, "portfolio"):
            criteria.append(
                CriterionMatch(
                    requirement="Portfolio / Work Samples",
                    category="Portfolio",
                    status="Contradictory",
                    evidence_snippet=_find_snippet(candidate_text, "portfolio"),
                    notes="Candidate profile indicates no portfolio or lack of work samples.",
                )
            )
        elif has_portfolio_evidence:
            portfolio_score = weights.portfolio
            criteria.append(
                CriterionMatch(
                    requirement="Portfolio / Work Samples",
                    category="Portfolio",
                    status="Matched",
                    evidence_snippet=_find_snippet(combined_text, "portfolio") or _find_snippet(combined_text, "github") or _find_snippet(combined_text, "artstation"),
                    notes="Work samples or portfolio links referenced.",
                )
            )
        else:
            criteria.append(
                CriterionMatch(
                    requirement="Portfolio / Work Samples",
                    category="Portfolio",
                    status="Not found",
                    notes="No portfolio link detected in text. Review candidate profile directly.",
                )
            )
    else:
        if is_generalist_ops:
            portfolio_score = 0
            criteria.append(
                CriterionMatch(
                    requirement="Portfolio / Work Samples",
                    category="Portfolio",
                    status="Not applicable",
                    notes="Portfolio not required for Generalist role; code repos do not confer bonus points.",
                )
            )
        elif has_portfolio_evidence:
            portfolio_score = weights.portfolio
            criteria.append(
                CriterionMatch(
                    requirement="Portfolio / Work Samples",
                    category="Portfolio",
                    status="Matched",
                    evidence_snippet=_find_snippet(combined_text, "github") or _find_snippet(combined_text, "portfolio"),
                    notes="Portfolio / work samples provided (bonus evidence).",
                )
            )
        else:
            portfolio_score = 0
            criteria.append(
                CriterionMatch(
                    requirement="Portfolio / Work Samples",
                    category="Portfolio",
                    status="Not found",
                    notes="Portfolio not required by JD and not observed in profile.",
                )
            )

    # 6. Evaluate Education or Certifications (if explicitly required)
    if requirements.education_or_certifications:
        for edu in requirements.education_or_certifications:
            edu_clean = re.sub(r"\s+or\s+(?:equivalent|related\s+(?:field|discipline)|similar)\b.*$", "", edu, flags=re.I).strip().lower()
            edu_words = [w for w in re.findall(r"\b[a-zA-Z]{3,}\b", edu_clean) if w not in {"degree", "equivalent", "related"}]
            matched_edu = (edu_clean in text_lower) or (edu.lower() in text_lower) or (bool(edu_words) and all(w in text_lower for w in edu_words))

            if _check_contradiction(cand_lower, edu) or _check_contradiction(cand_lower, edu_clean):
                criteria.append(
                    CriterionMatch(
                        requirement=edu,
                        category="Education / Certification",
                        status="Contradictory",
                        evidence_snippet=_find_snippet(candidate_text, edu) or _find_snippet(candidate_text, edu_clean),
                        notes=f"Candidate profile explicitly contradicts education requirement: '{edu}'.",
                    )
                )
            elif matched_edu:
                criteria.append(
                    CriterionMatch(
                        requirement=edu,
                        category="Education / Certification",
                        status="Matched",
                        evidence_snippet=_find_snippet(combined_text, edu_clean) or _find_snippet(combined_text, edu),
                        notes=f"Education or certification '{edu}' confirmed in text.",
                    )
                )
            else:
                criteria.append(
                    CriterionMatch(
                        requirement=edu,
                        category="Education / Certification",
                        status="Not found",
                        evidence_snippet="",
                        notes=f"Education or certification '{edu}' not mentioned; verify credentials directly.",
                    )
                )

    # 7. Evaluate Mandatory Constraints (if specified)
    if requirements.mandatory_constraints:
        for con in requirements.mandatory_constraints:
            con_clean = con.strip().lower()
            key_phrase = re.sub(r"^must\s+(?:have|be)\s+", "", con_clean).strip()
            matched_con = (con_clean in text_lower) or (key_phrase in text_lower)

            if _check_contradiction(cand_lower, con) or _check_contradiction(cand_lower, key_phrase):
                criteria.append(
                    CriterionMatch(
                        requirement=con,
                        category="Mandatory Constraint",
                        status="Contradictory",
                        evidence_snippet=_find_snippet(candidate_text, con) or _find_snippet(candidate_text, key_phrase),
                        notes=f"Candidate profile explicitly contradicts mandatory constraint: '{con}'.",
                    )
                )
            elif matched_con:
                criteria.append(
                    CriterionMatch(
                        requirement=con,
                        category="Mandatory Constraint",
                        status="Matched",
                        evidence_snippet=_find_snippet(combined_text, key_phrase) or _find_snippet(combined_text, con),
                        notes=f"Mandatory constraint '{con}' satisfied.",
                    )
                )
            else:
                criteria.append(
                    CriterionMatch(
                        requirement=con,
                        category="Mandatory Constraint",
                        status="Needs review",
                        evidence_snippet="",
                        notes=f"Mandatory constraint '{con}' requires recruiter verification.",
                    )
                )

    # Aggregate counts
    matched_count = sum(1 for c in criteria if c.status == "Matched")
    needs_review_count = sum(1 for c in criteria if c.status == "Needs review")
    not_found_count = sum(1 for c in criteria if c.status == "Not found")
    contradictory_count = sum(1 for c in criteria if c.status == "Contradictory")
    total_criteria = len(criteria)
    verified_criteria_count = matched_count
    unverified_criteria_count = needs_review_count + not_found_count + contradictory_count
    evidence_coverage_pct = round((matched_count / max(1, total_criteria)) * 100)

    # Determine applicable category weights
    applicable_weights = weights.core_skills + weights.role_alignment + weights.location
    if has_explicit_tools or tools_score > 0:
        applicable_weights += weights.tools
    if (requirements.portfolio_required or (not is_generalist_ops and has_portfolio_evidence)) and portfolio_score > 0:
        applicable_weights += weights.portfolio

    # Penalty for contradictory items
    penalty = contradictory_count * 20
    raw_sum = req_skills_score + tools_score + role_score + loc_score + portfolio_score
    if applicable_weights > 0:
        scaled_score = round((raw_sum / applicable_weights) * 100)
    else:
        scaled_score = raw_sum
    total_score = max(0, min(100, scaled_score - penalty))

    # Calculate confidence-adjusted credible score without flattening into 83%
    if confidence == "High":
        confidence_adjusted_score = total_score
    elif confidence == "Medium":
        confidence_adjusted_score = total_score if total_score < 70 else round(total_score * 0.90)
    else:
        confidence_adjusted_score = round(total_score * 0.60)

    # Coverage advisory for sparse or unverified evidence
    coverage_advisory = ""
    if confidence != "High" and total_score >= 80:
        coverage_advisory = (
            f"⚠️ Sparse evidence alert: Heuristic score is {total_score}/100, but confidence is "
            f"{confidence} ({word_count} words, {evidence_coverage_pct}% criteria coverage). "
            f"Confidence-adjusted score is {confidence_adjusted_score}/100. Manual recruiter verification required."
        )
    elif evidence_coverage_pct < 50 and total_score >= 60:
        coverage_advisory = (
            f"⚠️ Low criteria coverage: Only {evidence_coverage_pct}% of criteria have confirmed evidence. "
            f"Confidence-adjusted score is {confidence_adjusted_score}/100."
        )

    breakdown = {
        "Core Skills": req_skills_score,
        "Tools & Software": tools_score,
        "Role Alignment": role_score,
        "Location & Flexibility": loc_score,
        "Portfolio": portfolio_score,
    }

    source = (candidate.get("source") or "").lower()
    supplied_tier = candidate.get("evidence_ladder_tier") or ""

    if is_generalist_ops:
        has_eval_evidence = any(w in text_lower for w in ["chatgpt", "claude", "prompt", "evaluation", "rlhf", "annotation", "rater", "rubric", "quality assurance"])
        if matched_count >= 4 and has_eval_evidence:
            evidence_tier = "Tier 1: Strong Domain Evidence"
        elif matched_count >= 2 and has_eval_evidence:
            evidence_tier = "Tier 2: Moderate Domain Evidence"
        elif matched_count >= 1:
            evidence_tier = "Tier 3: Contextual / Weak Signal"
        else:
            evidence_tier = "Tier 4: Insufficient Evidence"
    else:
        if supplied_tier and "Tier" in supplied_tier:
            evidence_tier = supplied_tier
        elif matched_count >= 3 or ("github" in source and matched_count >= 2):
            evidence_tier = "Tier 1: Strong Technical Evidence"
        elif matched_count >= 1 or has_portfolio_evidence:
            evidence_tier = "Tier 2: Moderate Technical Evidence"
        elif word_count >= 20:
            evidence_tier = "Tier 3: Weak Technical Evidence"
        else:
            evidence_tier = "Tier 4: Insufficient Evidence"

    if "github" in source or "gitlab" in source:
        source_reliability = "High (Verified Code / API)"
    elif "local" in source:
        source_reliability = "High (Internal Talent Database)"
    elif "stackoverflow" in source or "huggingface" in source:
        source_reliability = "Moderate (Technical Contributor Profile)"
    else:
        source_reliability = "Contextual (Public Web Lead)"

    has_email = bool((candidate.get("email") or "").strip())
    has_phone = bool((candidate.get("phone") or "").strip())
    if has_email or has_phone:
        contact_availability = "Public Contact Details Available"
    elif candidate.get("profile_url") or candidate.get("github_url") or "http" in (candidate.get("evidence_text") or ""):
        contact_availability = "Profile Link Only"
    else:
        contact_availability = "Not Found"

    return CandidateEvaluation(
        candidate_id=cand_id,
        candidate_name=name,
        total_score=total_score,
        confidence=confidence,
        word_count=word_count,
        criteria_matches=criteria,
        matched_count=matched_count,
        needs_review_count=needs_review_count,
        not_found_count=not_found_count,
        contradictory_count=contradictory_count,
        verified_criteria_count=verified_criteria_count,
        unverified_criteria_count=unverified_criteria_count,
        evidence_coverage_pct=evidence_coverage_pct,
        confidence_adjusted_score=confidence_adjusted_score,
        coverage_advisory=coverage_advisory,
        score_breakdown=breakdown,
        summary_matched=list(set(summary_matched)),
        summary_missing=list(set(summary_missing)),
        evidence_tier=evidence_tier,
        source_reliability=source_reliability,
        contact_availability=contact_availability,
    )


def sanitize_csv_cell(value: object) -> object:
    """Sanitizes text cells against CSV formula injection (OWASP / Excel command execution).
    If a string cell starts with '=', '+', '-', '@', '\\t', or '\\r', it prepends a single quote.
    """
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{s}"
    return s


def sanitize_dataframe_for_csv(df: "pd.DataFrame") -> "pd.DataFrame":
    """Applies CSV formula injection protection across all cells in a pandas DataFrame."""
    clean_df = df.copy()
    for col in clean_df.columns:
        clean_df[col] = clean_df[col].apply(sanitize_csv_cell)
    return clean_df
