"""
Opportunity Matcher Engine — Transparent, deterministic candidate-to-opportunity scoring.

Weights (Total 100):
- Skills & role fit: 40
- Relevant experience: 25
- Required language / domain proficiency: 15
- Location, eligibility & availability: 10
- Other explicit requirements: 10

Generates complete evidence breakdown, missing requirements, eligibility concerns,
unknowns, and plain-English recommendations.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from db import (
    get_candidate,
    get_referral_opportunity,
    list_referral_opportunities,
    save_candidate_match,
)

logger = logging.getLogger("opportunity_matcher")


@dataclass
class MatchResult:
    candidate_id: int
    opportunity_id: int
    score: int
    score_breakdown: dict[str, int]
    matched_skills: list[str]
    missing_requirements: list[str]
    eligibility_concerns: list[str]
    unknowns: list[str]
    evidence: dict[str, Any]
    recommendation: str  # "Eligible for Outreach", "Review", "Do Not Proceed"
    reason: str


class OpportunityMatcher:
    """Deterministic, explainable rule-based matching engine."""

    def evaluate_match(self, candidate: dict, opportunity: dict) -> MatchResult:
        """Evaluates a single candidate against an opportunity."""
        cand_id = candidate["id"]
        opp_id = opportunity["id"]

        # Parse candidate skills and languages safely
        cand_skills: list[str] = []
        try:
            if candidate.get("skills"):
                raw = candidate["skills"]
                cand_skills = json.loads(raw) if isinstance(raw, str) else list(raw)
        except Exception:
            cand_skills = []
        cand_skills_lower = {s.lower().strip() for s in cand_skills}

        cand_langs: list[str] = []
        try:
            if candidate.get("languages"):
                raw = candidate["languages"]
                cand_langs = json.loads(raw) if isinstance(raw, str) else list(raw)
        except Exception:
            cand_langs = []
        cand_langs_lower = {l.lower().strip() for l in cand_langs}

        cand_exp = candidate.get("years_of_experience", 0) or 0
        cand_loc = (candidate.get("location") or "").lower().strip()
        cand_evidence = (candidate.get("evidence_text") or "").lower()

        # Opportunity requirements
        opp_reqs: list[str] = opportunity.get("requirements", [])
        if isinstance(opp_reqs, str):
            try:
                opp_reqs = json.loads(opp_reqs)
            except Exception:
                opp_reqs = []

        opp_langs: list[str] = opportunity.get("language_requirements", ["English"])
        if isinstance(opp_langs, str):
            try:
                opp_langs = json.loads(opp_langs)
            except Exception:
                opp_langs = ["English"]

        opp_min_exp = opportunity.get("experience_years_min", 0) or 0
        opp_loc_restr = (opportunity.get("location_restrictions") or "").lower()
        opp_ver_status = opportunity.get("verification_status", "UNVERIFIED")

        matched_skills: list[str] = []
        missing_skills: list[str] = []
        eligibility_concerns: list[str] = []
        unknowns: list[str] = []

        # 1. Skills & Role Fit (Max 40 points)
        skills_score = 0
        if opp_reqs:
            for req in opp_reqs:
                req_lower = req.lower().strip()
                if req_lower in cand_skills_lower or req_lower in cand_evidence:
                    matched_skills.append(req)
                else:
                    missing_skills.append(req)

            match_ratio = len(matched_skills) / len(opp_reqs)
            skills_score = int(round(match_ratio * 40))
        else:
            skills_score = 30  # No explicit skills required

        # 2. Relevant Experience (Max 25 points)
        exp_score = 0
        if opp_min_exp == 0:
            exp_score = 25
        elif cand_exp >= opp_min_exp:
            exp_score = 25
        elif cand_exp > 0:
            # Partial credit if within 1-2 years
            ratio = min(1.0, cand_exp / opp_min_exp)
            exp_score = int(round(ratio * 25))
            eligibility_concerns.append(f"Candidate has {cand_exp} yrs documented; opportunity asks for {opp_min_exp}+ yrs.")
        else:
            exp_score = 5
            unknowns.append("Years of professional experience could not be reliably verified from CV text.")

        # 3. Language & Domain Proficiency (Max 15 points)
        lang_score = 0
        matched_langs: list[str] = []
        for l in opp_langs:
            l_lower = l.lower().strip()
            if l_lower in cand_langs_lower or l_lower in cand_evidence or "english" in l_lower:
                matched_langs.append(l)
            else:
                unknowns.append(f"Language proficiency in {l} not explicitly confirmed.")

        if opp_langs:
            lang_score = int(round((len(matched_langs) / len(opp_langs)) * 15))
        else:
            lang_score = 15

        # 4. Location, Eligibility & Availability (Max 10 points)
        loc_score = 10
        if "remote" in opp_loc_restr or "global" in opp_loc_restr:
            loc_score = 10
        elif cand_loc and cand_loc != "unknown":
            if any(part in cand_loc for part in opp_loc_restr.split()):
                loc_score = 10
            else:
                loc_score = 3
                eligibility_concerns.append(f"Candidate location '{candidate.get('location')}' may conflict with restriction '{opportunity.get('location_restrictions')}'.")
        else:
            loc_score = 6
            unknowns.append("Specific geographic location and work authorization unknown.")

        # 5. Other Explicit Requirements & Verification Quality (Max 10 points)
        other_score = 10
        if opp_ver_status != "VERIFIED":
            other_score = 2
            eligibility_concerns.append("Opportunity verification status is UNVERIFIED; human confirmation required before outreach.")

        total_score = min(100, skills_score + exp_score + lang_score + loc_score + other_score)

        # Recommendation
        if candidate.get("opt_out_status", 0) == 1:
            recommendation = "Do Not Proceed"
            reason = f"Candidate has opted out of outreach (Reason: {candidate.get('suppression_reason', 'Opted-out')})."
        elif total_score >= 65 and opp_ver_status == "VERIFIED" and not eligibility_concerns:
            recommendation = "Eligible for Outreach"
            reason = f"Strong match ({total_score}/100) with {len(matched_skills)} verified skills and qualified experience."
        elif total_score >= 40:
            recommendation = "Review"
            reason = f"Moderate match ({total_score}/100). Review missing requirements ({', '.join(missing_skills[:3]) if missing_skills else 'None'}) before creating draft."
        else:
            recommendation = "Do Not Proceed"
            reason = f"Low relevance score ({total_score}/100). Insufficient skill or experience overlap."

        breakdown = {
            "skills_score": skills_score,
            "experience_score": exp_score,
            "language_score": lang_score,
            "location_score": loc_score,
            "other_score": other_score,
            "max_skills": 40,
            "max_experience": 25,
            "max_language": 15,
            "max_location": 10,
            "max_other": 10,
        }

        evidence_payload = {
            "matched_skills": matched_skills,
            "candidate_years_exp": cand_exp,
            "candidate_location": candidate.get("location") or "Unknown",
            "candidate_headline": candidate.get("headline") or "",
            "opportunity_title": opportunity.get("title"),
            "opportunity_platform": opportunity.get("platform"),
        }

        return MatchResult(
            candidate_id=cand_id,
            opportunity_id=opp_id,
            score=total_score,
            score_breakdown=breakdown,
            matched_skills=matched_skills,
            missing_requirements=missing_skills,
            eligibility_concerns=eligibility_concerns,
            unknowns=unknowns,
            evidence=evidence_payload,
            recommendation=recommendation,
            reason=reason,
        )

    def match_all_candidates_and_persist(
        self,
        conn: sqlite3.Connection,
        min_score: int = 40,
    ) -> int:
        """Evaluates all eligible candidates against active opportunities and persists matches."""
        candidates = conn.execute("SELECT * FROM candidates WHERE opt_out_status = 0").fetchall()
        opportunities = list_referral_opportunities(conn, is_active=True)

        matched_count = 0
        for cand_row in candidates:
            cand = dict(cand_row)
            for opp in opportunities:
                res = self.evaluate_match(cand, opp)
                if res.score >= min_score or res.recommendation != "Do Not Proceed":
                    save_candidate_match(
                        conn=conn,
                        candidate_id=res.candidate_id,
                        opportunity_id=res.opportunity_id,
                        score=res.score,
                        score_breakdown=res.score_breakdown,
                        evidence=res.evidence,
                        matched_requirements=res.matched_skills,
                        missing_requirements=res.missing_requirements,
                        contradictions=res.eligibility_concerns,
                        recommendation=res.recommendation,
                        opportunity_verification_status=opp.get("verification_status", "UNVERIFIED"),
                    )
                    matched_count += 1

        return matched_count


opportunity_matcher = OpportunityMatcher()
