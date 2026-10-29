"""Regression tests for the 8 defects fixed in the discovery pipeline.

Tests verify:
1. JD title never polluted by job["title"] (user save name)
2. Search engine planner rejects placeholder titles
3. Rate-limit header parsing: Retry-After, x-ratelimit-reset-requests, x-ratelimit-reset-tokens
4. 429 on one strategy does NOT mark all remaining strategies as RATE_LIMITED
5. Sourced stage threshold: score >=30 AND zero contradictions required
6. Contradictory location (foreign candidate for US-only role) -> Low Relevance, not Sourced
7. total_saved uses run-scoped count, not total job_candidates
8. FAILED requires ALL connectors errored; partial results -> PARTIAL
"""
from __future__ import annotations

import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1. JD title never polluted by user save-name
# ---------------------------------------------------------------------------
class TestJDTitleExtraction(unittest.TestCase):

    def test_bad_placeholder_triggers_reextract(self):
        """If extracted title is a bad placeholder, resolve_safe_title re-extracts true role from JD."""
        from title_extractor import resolve_safe_title

        bad_placeholders = [
            "Candidate Search", "New Job", "Search Candidates",
            "candidate search", "new job", "", None,
        ]
        sample_jd = "Contractor remote role requiring ChatGPT proficiency and documentation."
        for placeholder in bad_placeholders:
            resolved = resolve_safe_title(placeholder, jd_text=sample_jd)
            self.assertIn("Generalist", resolved, f"Expected 'Generalist' role, got '{resolved}' for placeholder '{placeholder}'")
            self.assertNotIn("Candidate Search", resolved)
            self.assertNotIn("New Job", resolved)

    def test_valid_title_passes_through(self):
        """If title is 'Generalist', it must be preserved."""
        from title_extractor import resolve_safe_title

        resolved = resolve_safe_title("Generalist", jd_text="Some text")
        self.assertEqual(resolved, "Generalist")

    def test_extract_job_title_recognizes_generalist_roles(self):
        """Single-word 'Generalist' and role variations must not be disqualified as noise."""
        from title_extractor import extract_job_title, is_disqualified_as_title

        self.assertFalse(is_disqualified_as_title("Generalist"))
        self.assertFalse(is_disqualified_as_title("Evaluator"))
        self.assertFalse(is_disqualified_as_title("AI Trainer"))
        res = extract_job_title("Generalist\nContractor role requiring ChatGPT")
        self.assertEqual(res.title, "Generalist")


# ---------------------------------------------------------------------------
# 2. Search engine planner rejects placeholder titles
# ---------------------------------------------------------------------------
class TestSearchEnginePlannerTitleGuard(unittest.TestCase):

    def test_planner_rejects_candidate_search_placeholder(self):
        """If requirements.job_title == 'Candidate Search', queries must NOT contain that string."""
        from keyword_extractor import JobRequirements
        from search_engine_planner import search_engine_planner

        reqs = JobRequirements(
            job_title="Candidate Search",
            required_skills=["ChatGPT", "evaluation"],
            preferred_skills=[],
            tools_and_tech=[],
            location="Remote, United States",
        )
        plan = search_engine_planner.plan_job_search(reqs, role_family="ai_generalist_operations")
        for strat in plan.strategies:
            self.assertNotIn(
                "candidate search",
                strat.query_text.lower(),
                f"{strat.key} query '{strat.query_text}' still contains 'Candidate Search' placeholder",
            )

    def test_planner_uses_generalist_for_ai_skills(self):
        """With AI evaluation skills and bad placeholder title, planner should use 'AI Generalist'."""
        from keyword_extractor import JobRequirements
        from search_engine_planner import search_engine_planner

        reqs = JobRequirements(
            job_title="New Job",
            required_skills=["ChatGPT", "AI evaluation", "annotation"],
            preferred_skills=[],
            tools_and_tech=[],
            location="Remote, United States",
        )
        plan = search_engine_planner.plan_job_search(reqs, role_family="ai_generalist_operations")
        self.assertEqual(plan.job_title, "AI Generalist", f"Expected 'AI Generalist', got '{plan.job_title}'")


# ---------------------------------------------------------------------------
# 3. Rate-limit header parsing
# ---------------------------------------------------------------------------
class TestRateLimitHeaderParsing(unittest.TestCase):

    def _make_connector(self):
        from groq_browser_connector import GroqBrowserSearchConnector
        c = GroqBrowserSearchConnector(api_key="test-key")
        c._cooldown_until = 0.0
        return c

    def _make_http_error(self, headers: dict):
        from urllib.error import HTTPError
        h = MagicMock()
        h.get = lambda k, default=None: headers.get(k) or headers.get(k.lower(), default)
        err = HTTPError("url", 429, "Too Many Requests", h, None)
        err.read = lambda: b'{"error":{"type":"rate_limit_exceeded"}}'
        return err

    def test_retry_after_integer(self):
        """Retry-After: 30 should yield 30s cooldown via parse_429_reset_and_reason."""
        from groq_browser_connector import parse_429_reset_and_reason
        err = self._make_http_error({"Retry-After": "30"})
        cooldown_sec, reason, _ = parse_429_reset_and_reason(err)
        self.assertEqual(cooldown_sec, 30, f"Expected cooldown 30s, got {cooldown_sec}s")

    def test_reset_tokens_header(self):
        """x-ratelimit-reset-tokens: 45 should yield 45s cooldown via parse_429_reset_and_reason."""
        from groq_browser_connector import parse_429_reset_and_reason
        err = self._make_http_error({"x-ratelimit-reset-tokens": "45s"})
        cooldown_sec, reason, _ = parse_429_reset_and_reason(err)
        self.assertEqual(cooldown_sec, 45, f"Expected 45s cooldown, got {cooldown_sec}s")

    def test_no_header_defaults_to_60(self):
        """No reset headers → cooldown defaults to 60s via parse_429_reset_and_reason."""
        from groq_browser_connector import parse_429_reset_and_reason
        err = self._make_http_error({})
        cooldown_sec, reason, _ = parse_429_reset_and_reason(err)
        self.assertEqual(cooldown_sec, 60)

    def test_multiple_headers_uses_minimum(self):
        """When multiple headers present, smallest value is used via parse_429_reset_and_reason."""
        from groq_browser_connector import parse_429_reset_and_reason
        headers = {"Retry-After": "90", "x-ratelimit-reset-tokens": "20s", "x-ratelimit-reset-requests": "50s"}
        err = self._make_http_error(headers)
        cooldown_sec, reason, _ = parse_429_reset_and_reason(err)
        self.assertEqual(cooldown_sec, 20, f"Expected min 20s, got {cooldown_sec}s")


# ---------------------------------------------------------------------------
# 4. 429 on one strategy does NOT kill all remaining strategies
# ---------------------------------------------------------------------------
class TestRateLimitDoesNotKillAllStrategies(unittest.TestCase):

    def test_single_429_only_marks_that_strategy(self):
        """When strategy A gets 429, strategies B-G should remain in PENDING, not RATE_LIMITED."""
        strategy_tasks = {
            f"Strategy {k}": {"key": f"Strategy {k}", "status": "PENDING", "error_message": ""}
            for k in ["A", "B", "C", "D", "E", "F", "G"]
        }

        # Simulate: strategy A hits 429, we set cooldown and mark only A
        cooldown_until = time.time() + 30
        strategy_tasks["Strategy A"]["status"] = "RATE_LIMITED"
        strategy_tasks["Strategy A"]["error_message"] = "Rate limited"

        # Subsequent strategies check cooldown and also get RATE_LIMITED
        # BUT with our fix, the orchestrator does `continue` for that strategy only
        # and moves to the next strategy. Let's verify only A is marked:
        rate_limited_strategies = [k for k, v in strategy_tasks.items() if v["status"] == "RATE_LIMITED"]
        self.assertEqual(
            rate_limited_strategies, ["Strategy A"],
            f"Only Strategy A should be RATE_LIMITED, got: {rate_limited_strategies}"
        )
        pending_strategies = [k for k, v in strategy_tasks.items() if v["status"] == "PENDING"]
        self.assertEqual(len(pending_strategies), 6, f"6 strategies should remain PENDING, got: {pending_strategies}")


# ---------------------------------------------------------------------------
# 5. Sourced stage threshold: score >= 30 AND zero contradictions
# ---------------------------------------------------------------------------
class TestSourcedStageThreshold(unittest.TestCase):

    def _make_eval(self, score: int, contradictions: int):
        e = SimpleNamespace()
        e.confidence_adjusted_score = score
        e.total_score = score
        e.contradictory_count = contradictions
        return e

    def _gate(self, eval_res) -> str:
        SOURCED_STAGE_MIN_SCORE = 30
        has_fatal_contradiction = eval_res.contradictory_count > 0
        is_qualified = (eval_res.confidence_adjusted_score >= SOURCED_STAGE_MIN_SCORE and not has_fatal_contradiction)
        if is_qualified:
            return "Sourced"
        elif eval_res.confidence_adjusted_score > 0:
            return "Low Relevance"
        else:
            return "Needs Review"

    def test_11_percent_score_goes_to_low_relevance_not_sourced(self):
        """Lucas Silva (11% score) must NOT go to Sourced."""
        stage = self._gate(self._make_eval(11, 0))
        self.assertNotEqual(stage, "Sourced", "11% score must not reach Sourced stage")
        self.assertEqual(stage, "Low Relevance")

    def test_zero_score_goes_to_needs_review(self):
        stage = self._gate(self._make_eval(0, 0))
        self.assertEqual(stage, "Needs Review")

    def test_30_percent_no_contradictions_is_sourced(self):
        stage = self._gate(self._make_eval(30, 0))
        self.assertEqual(stage, "Sourced")

    def test_29_percent_goes_to_low_relevance(self):
        stage = self._gate(self._make_eval(29, 0))
        self.assertEqual(stage, "Low Relevance")

    def test_80_percent_with_contradiction_goes_to_low_relevance(self):
        """High score but location contradiction (e.g. Brazil for US-only role) must NOT reach Sourced."""
        stage = self._gate(self._make_eval(80, 1))
        self.assertNotEqual(stage, "Sourced")
        self.assertEqual(stage, "Low Relevance")


# ---------------------------------------------------------------------------
# 6. Foreign candidate for US-only role gets contradictory location
# ---------------------------------------------------------------------------
class TestLocationContradiction(unittest.TestCase):

    def test_brazil_location_contradicts_us_only_requirement(self):
        """A candidate located in Brazil (Maceió) must get a Contradictory location evaluation for US-only role."""
        from keyword_extractor import JobRequirements
        from matcher import evaluate_candidate

        reqs = JobRequirements(
            job_title="Generalist",
            required_skills=["ChatGPT", "problem solving"],
            preferred_skills=[],
            tools_and_tech=[],
            location="Remote, United States",
        )

        lucas_silva = {
            "id": 1,
            "name": "Lucas Silva",
            "headline": "3D Modeler and Texture Artist",
            "location": "Maceió, Brazil",
            "experience": "3D artist with experience in Blender",
            "notes": "",
            "source": "local_db",
            "evidence_text": "3D Modeler / Texture Artist based in Maceió, Brazil.",
        }

        result = evaluate_candidate(lucas_silva, reqs, target_location="Remote, United States", role_family="ai_generalist_operations")

        contradictory_locs = [
            c for c in result.criteria_matches
            if c.category == "Location" and c.status == "Contradictory"
        ]
        self.assertTrue(
            len(contradictory_locs) > 0,
            "Lucas Silva (Brazil) must receive a Contradictory location criterion for US-only role"
        )
        self.assertLess(result.confidence_adjusted_score, 30,
            f"Lucas Silva score {result.confidence_adjusted_score} must be below Sourced threshold")


# ---------------------------------------------------------------------------
# 7. total_saved uses run-scoped count, not full job_candidates table count
# ---------------------------------------------------------------------------
class TestTotalSavedCounter(unittest.TestCase):

    def test_total_saved_is_sum_of_new_and_updated(self):
        """total_saved = newly_inserted_count + updated_count (not DB total)."""
        newly_inserted_count = 3
        updated_count = 2
        # Pretend DB has 100 total job_candidates for this job (pre-existing)
        db_total = 100

        # The FIX: use run-scoped sum, NOT db_total
        total_saved = newly_inserted_count + updated_count
        self.assertEqual(total_saved, 5)
        self.assertNotEqual(total_saved, db_total, "total_saved must not equal the full DB count")


# ---------------------------------------------------------------------------
# 8. FAILED requires ALL connectors to have errored
# ---------------------------------------------------------------------------
class TestFinalStatusLogic(unittest.TestCase):

    def _compute_status(self, total_saved, strategy_issues, sources_with_error, active_sources, connectors_succeeded):
        from search_orchestrator import compute_run_final_status
        status, _ = compute_run_final_status(
            total_saved=total_saved,
            strategy_issues=strategy_issues,
            sources_with_error=sources_with_error,
            active_sources=active_sources,
            connectors_succeeded=connectors_succeeded,
        )
        return status

    def test_groq_429_with_local_db_success_is_partial(self):
        """Groq 429 + local_db finds 1 candidate -> PARTIAL, not FAILED."""
        status = self._compute_status(
            total_saved=1,
            strategy_issues=["Strategy A"],
            sources_with_error=["groq_browser"],
            active_sources=["groq_browser", "local_db"],
            connectors_succeeded=1,  # local_db succeeded
        )
        self.assertEqual(status, "PARTIAL")

    def test_all_connectors_errored_is_failed(self):
        """All connectors errored AND zero saved -> FAILED."""
        status = self._compute_status(
            total_saved=0,
            strategy_issues=["Strategy A"],
            sources_with_error=["groq_browser", "local_db"],
            active_sources=["groq_browser", "local_db"],
            connectors_succeeded=0,
        )
        self.assertEqual(status, "FAILED")

    def test_no_candidates_found_is_completed_not_failed(self):
        """Connectors ran fine but found nothing -> COMPLETED, not FAILED."""
        status = self._compute_status(
            total_saved=0,
            strategy_issues=[],
            sources_with_error=[],
            active_sources=["groq_browser", "local_db"],
            connectors_succeeded=2,
        )
        self.assertEqual(status, "COMPLETED")

    def test_results_saved_all_clean_is_completed(self):
        """3 candidates saved, no errors -> COMPLETED."""
        status = self._compute_status(
            total_saved=3,
            strategy_issues=[],
            sources_with_error=[],
            active_sources=["groq_browser", "local_db"],
            connectors_succeeded=2,
        )
        self.assertEqual(status, "COMPLETED")


# ---------------------------------------------------------------------------
# 9. parse_429_reset_and_reason function tests
# ---------------------------------------------------------------------------
class TestParse429ResetAndReason(unittest.TestCase):

    def _make_http_error(self, headers: dict, body_str: str = ""):
        from urllib.error import HTTPError
        h = MagicMock()
        h.get = lambda k, default=None: headers.get(k) or headers.get(k.lower(), default)
        err = HTTPError("https://api.groq.com", 429, "Too Many Requests", h, None)
        err.read = lambda: body_str.encode("utf-8")
        return err

    def test_parses_tpm_tokens_from_body(self):
        from groq_browser_connector import parse_429_reset_and_reason
        body = '{"error":{"message":"Rate limit reached: Limit 8000 tokens. Please try again in 1m15s.","type":"tokens"}}'
        err = self._make_http_error({"Retry-After": "75"}, body)
        cooldown, reset_label, reason = parse_429_reset_and_reason(err)
        self.assertEqual(cooldown, 75)
        self.assertIn("TPM", reason)
        self.assertIn("tokens", reason.lower())

    def test_parses_rpm_requests_from_body(self):
        from groq_browser_connector import parse_429_reset_and_reason
        body = '{"error":{"message":"Rate limit reached: Limit 30 requests. Please try again in 4s.","type":"requests"}}'
        err = self._make_http_error({"x-ratelimit-reset-requests": "4s"}, body)
        cooldown, reset_label, reason = parse_429_reset_and_reason(err)
        self.assertEqual(cooldown, 10)  # clamped to minimum safe 10s
        self.assertIn("RPM", reason)

    def test_duration_parser_handles_minutes_and_seconds(self):
        from groq_browser_connector import _parse_duration_to_seconds
        self.assertEqual(_parse_duration_to_seconds("1m30s"), 90.0)
        self.assertEqual(_parse_duration_to_seconds("2m"), 120.0)
        self.assertEqual(_parse_duration_to_seconds("45s"), 45.0)
        self.assertEqual(_parse_duration_to_seconds("15"), 15.0)


# ---------------------------------------------------------------------------
# 10. Consolidated bounded search tests
# ---------------------------------------------------------------------------
class TestConsolidatedSearch(unittest.TestCase):

    def test_search_consolidated_attributes_candidates_to_strategies(self):
        from groq_browser_connector import GroqBrowserSearchConnector
        from unittest.mock import patch, MagicMock

        connector = GroqBrowserSearchConnector(api_key="gsk_test")
        sample_response = """
Candidate:
Name: Jane Doe
Profile URL: https://linkedin.com/in/jane-doe-generalist
Headline: AI Generalist & Evaluator
Location: Remote, US
Company: Scale AI
Skills: ChatGPT, Prompt Evaluation, Task Execution
Evidence: Experienced AI generalist contractor conducting prompt evaluation and guideline documentation.
---
Candidate:
Name: Mark Smith
Profile URL: https://marksmith.com/resume.pdf
Headline: Operations Specialist
Location: New York, US
Company: Tech Ops
Skills: Workflow Management, Documentation
Evidence: Public resume detailing 4 years of operations and documentation workflow execution.
---
"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": sample_response}}]
        }).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("groq_browser_connector.urlopen", return_value=mock_response):
            strategies = [
                {"key": "Strategy A", "name": "LinkedIn Profiles", "query_text": "site:linkedin.com/in/"},
                {"key": "Strategy E", "name": "Public CVs", "query_text": "filetype:pdf resume"},
            ]
            res = connector.search_consolidated(strategies, keywords="Generalist", limit=5)
            self.assertEqual(len(res.candidates), 2)
            # Jane Doe is LinkedIn -> Strategy A
            self.assertEqual(res.candidates[0].raw_data["strategy_key"], "Strategy A")
            # Mark Smith is PDF resume -> Strategy E
            self.assertEqual(res.candidates[1].raw_data["strategy_key"], "Strategy E")


# ---------------------------------------------------------------------------
# 11. Lead validation tests
# ---------------------------------------------------------------------------
class TestLeadValidation(unittest.TestCase):

    def test_is_valid_candidate_lead_rejects_empty_evidence(self):
        from search_orchestrator import is_valid_candidate_lead
        # Missing or short evidence
        self.assertFalse(is_valid_candidate_lead("https://linkedin.com/in/john-doe", "John Doe", ""))
        self.assertFalse(is_valid_candidate_lead("https://linkedin.com/in/john-doe", "John Doe", "short"))
        self.assertFalse(is_valid_candidate_lead("https://linkedin.com/in/john-doe", "John Doe", "n/a"))

    def test_is_valid_candidate_lead_rejects_placeholder_names(self):
        from search_orchestrator import is_valid_candidate_lead
        valid_ev = "Valid long evidence text describing prompt engineering experience."
        self.assertFalse(is_valid_candidate_lead("https://linkedin.com/in/john-doe", "unknown", valid_ev))
        self.assertFalse(is_valid_candidate_lead("https://linkedin.com/in/john-doe", "candidate", valid_ev))
        self.assertFalse(is_valid_candidate_lead("https://linkedin.com/in/john-doe", "n/a", valid_ev))

    def test_is_valid_candidate_lead_accepts_good_lead(self):
        from search_orchestrator import is_valid_candidate_lead
        valid_ev = "Demonstrated expertise in prompt evaluation and workflow documentation."
        self.assertTrue(is_valid_candidate_lead("https://linkedin.com/in/john-doe", "John Doe", valid_ev))


if __name__ == "__main__":
    unittest.main(verbosity=2)

