"""Real end-to-end regression tests verifying that title extraction, resolution,
query generation, and database updates never produce placeholder titles like 'Candidate Search'.
"""
from __future__ import annotations

import json
import unittest
from keyword_extractor import JobRequirements
from title_extractor import (
    ROLE_KEYWORDS,
    METADATA_DISQUALIFIERS,
    clean_title_candidate,
    extract_job_title,
    is_disqualified_as_title,
    is_placeholder_title,
    resolve_safe_title,
)
from query_generator import generate_search_queries
from search_engine_planner import search_engine_planner


class TestRealTitleExtractionAndResolution(unittest.TestCase):

    def test_role_keywords_includes_generalist_and_operational_roles(self):
        """ROLE_KEYWORDS must include 'generalist', 'evaluator', 'trainer', 'rater', etc."""
        self.assertIn("generalist", ROLE_KEYWORDS)
        self.assertIn("generalists", ROLE_KEYWORDS)
        self.assertIn("evaluator", ROLE_KEYWORDS)
        self.assertIn("trainer", ROLE_KEYWORDS)
        self.assertIn("rater", ROLE_KEYWORDS)
        self.assertIn("operator", ROLE_KEYWORDS)

    def test_single_word_generalist_not_disqualified(self):
        """Single-word title 'Generalist' must NOT be disqualified as noise."""
        self.assertFalse(is_disqualified_as_title("Generalist"))
        self.assertFalse(is_disqualified_as_title("generalist"))
        self.assertFalse(is_disqualified_as_title("Evaluator"))
        self.assertFalse(is_disqualified_as_title("AI Trainer"))

    def test_metadata_labels_properly_disqualified(self):
        """Field labels like 'Type: Contractor' or 'Location: Remote' must be disqualified."""
        self.assertTrue(is_disqualified_as_title("Type: Contractor"))
        self.assertTrue(is_disqualified_as_title("Job Type: Full-time"))
        self.assertTrue(is_disqualified_as_title("Location: Remote, United States"))
        self.assertTrue(is_disqualified_as_title("Pay: $50/hour"))

    def test_extract_job_title_from_generalist_header(self):
        """JD text with 'Generalist' heading extracts 'Generalist' cleanly."""
        jd_text = "Generalist\nContractor remote role requiring ChatGPT proficiency and documentation."
        res = extract_job_title(jd_text)
        self.assertEqual(res.title, "Generalist")

    def test_resolve_safe_title_with_stub_jd_recovers_ai_generalist(self):
        """When JD text is only a one-line stub without an explicit header, resolve_safe_title recovers 'AI Generalist'."""
        stub_jd = "Contractor remote role requiring ChatGPT proficiency and documentation."
        resolved = resolve_safe_title(None, jd_text=stub_jd)
        self.assertEqual(resolved, "AI Generalist")

        resolved_from_empty = resolve_safe_title("", jd_text=stub_jd)
        self.assertEqual(resolved_from_empty, "AI Generalist")

        resolved_from_placeholder = resolve_safe_title("Candidate Search", jd_text=stub_jd)
        self.assertEqual(resolved_from_placeholder, "AI Generalist")

    def test_resolve_safe_title_strips_test_role_suffixes(self):
        """Test names like 'Generalist XRay Test Role (#47)' are cleaned to 'Generalist'."""
        resolved = resolve_safe_title("Generalist XRay Test Role (#47)", jd_text="")
        self.assertEqual(resolved, "Generalist")

        resolved2 = resolve_safe_title("AI Generalist XRay Test Role", jd_text="")
        self.assertEqual(resolved2, "AI Generalist")

    def test_query_generator_never_outputs_candidate_search(self):
        """query_generator.generate_search_queries must never include 'Candidate Search' in query strings."""
        reqs = JobRequirements(
            job_title="Candidate Search",  # bad placeholder passed in
            required_skills=["ChatGPT", "documentation"],
            preferred_skills=[],
            tools_and_tech=[],
            location="Remote, United States",
        )
        queries = generate_search_queries(reqs, user_location="Remote, US")
        self.assertTrue(len(queries) > 0)
        for q in queries:
            self.assertNotIn("Candidate Search", q.query_text)
            self.assertNotIn('"Candidate Search"', q.query_text)
        self.assertTrue(any("Generalist" in q.query_text for q in queries))

    def test_search_engine_planner_never_outputs_candidate_search(self):
        """search_engine_planner.plan_job_search must never include 'Candidate Search' in any strategy."""
        reqs = JobRequirements(
            job_title="New Job",  # bad placeholder
            required_skills=["ChatGPT", "AI evaluation"],
            preferred_skills=[],
            tools_and_tech=[],
            location="Remote, United States",
        )
        plan = search_engine_planner.plan_job_search(reqs, target_location="Remote, US")
        self.assertEqual(plan.job_title, "AI Generalist")
        for s in plan.strategies:
            self.assertNotIn("Candidate Search", s.query_text)
            self.assertNotIn("New Job", s.query_text)
        self.assertTrue(any("AI Generalist" in s.query_text for s in plan.strategies))
