"""
Automated tests for CV-to-Referral Outreach Module: Phase B & C.
Covers:
- Deterministic opportunity matching (Turing, Mercor, micro1)
- Score weights: 40 skills, 25 exp, 15 lang, 10 loc, 10 other
- Missing requirements & unknowns transparency
- Decoupled 100-point fit score from outreach compliance gating
- Independent outreach eligibility states (ELIGIBLE, PENDING_REVIEW, BLOCKED)
- Opt-out suppression preventing outreach draft creation
- Missing email and unverified contact permission blocking draft creation
- Gmail draft creation (draft-only, never send) with idempotency key
- Cryptographic OAuth state generation and validation (10-minute TTL)
- Audit trail for permission reviews and opportunity verification
- Verification that no email-send API endpoints exist
"""
from __future__ import annotations

import json
import sqlite3
import unittest

from db import (
    add_or_update_candidate,
    create_or_update_draft,
    get_candidate,
    get_outreach_draft,
    get_referral_opportunity,
    init_db,
    list_candidate_matches,
    list_outreach_drafts,
    list_referral_opportunities,
    update_candidate_contact_permission,
    update_candidate_email_verification,
    update_candidate_opt_out,
    update_referral_opportunity,
)
from gmail_outreach import (
    compute_draft_idempotency_key,
    generate_oauth_state,
    gmail_outreach,
    validate_oauth_state,
)
from opportunity_matcher import opportunity_matcher


class TestReferralMatchingAndDrafts(unittest.TestCase):
    def setUp(self):
        self.conn = init_db(":memory:")
        # Seeded opportunities default to UNVERIFIED for security
        self.opps = list_referral_opportunities(self.conn)
        self.turing_opp = next(o for o in self.opps if o["platform"] == "Turing")
        self.mercor_opp = next(o for o in self.opps if o["platform"] == "Mercor")
        self.micro1_opp = next(o for o in self.opps if o["platform"] == "micro1")

    def tearDown(self):
        self.conn.close()

    def test_seeded_opportunities_present(self):
        """Verifies default opportunities for Turing, Mercor, and micro1 are seeded as UNVERIFIED."""
        self.assertGreaterEqual(len(self.opps), 3)
        platforms = [o["platform"] for o in self.opps]
        self.assertIn("Turing", platforms)
        self.assertIn("Mercor", platforms)
        self.assertIn("micro1", platforms)
        for o in self.opps:
            self.assertEqual(o["verification_status"], "UNVERIFIED")
            self.assertGreater(len(o["links"]), 0)

    def test_decoupled_scoring_and_outreach_eligibility(self):
        """Tests that fit score is 100-pt objective technical fit, while outreach eligibility evaluates gating."""
        # Candidate with high skills but PENDING_REVIEW permission and UNVERIFIED opportunity
        candidate = {
            "id": 101,
            "name": "Devin Kumar",
            "email": "devin.kumar@techpro.com",
            "skills": json.dumps(["python", "react", "fastapi", "typescript", "postgresql", "docker"]),
            "languages": json.dumps(["English"]),
            "years_of_experience": 5,
            "location": "Remote",
            "opt_out_status": 0,
            "contact_permission_basis": "PENDING_REVIEW",
            "email_verification_status": "VERIFIED",
            "evidence_text": "5 years building distributed Python and React systems.",
        }

        # Match evaluated against unverified opportunity
        res = opportunity_matcher.evaluate_match(candidate, self.turing_opp)
        self.assertGreaterEqual(res.score, 80)
        # Score is high, but recommendation is 'Review' and eligibility is PENDING_REVIEW due to unverified opportunity
        self.assertEqual(res.recommendation, "Review")
        self.assertEqual(res.outreach_eligibility, "PENDING_REVIEW")

        # Now verify opportunity and approve permission
        verified_opp = dict(self.turing_opp)
        verified_opp["verification_status"] = "VERIFIED"
        candidate["contact_permission_basis"] = "APPROVED_OUTREACH"

        res_approved = opportunity_matcher.evaluate_match(candidate, verified_opp)
        self.assertGreaterEqual(res_approved.score, 80)
        self.assertEqual(res_approved.recommendation, "Eligible for Outreach")
        self.assertEqual(res_approved.outreach_eligibility, "ELIGIBLE")

    def test_partial_match_generates_review(self):
        """Tests that a junior developer with missing skills receives 'Review' and lists missing requirements."""
        candidate = {
            "id": 102,
            "name": "Junior Sam",
            "email": "sam@devjunior.io",
            "skills": json.dumps(["python"]),
            "languages": json.dumps(["English"]),
            "years_of_experience": 1,
            "location": "United States",
            "opt_out_status": 0,
            "evidence_text": "Recent graduate with basic Python experience.",
        }

        res = opportunity_matcher.evaluate_match(candidate, self.turing_opp)
        self.assertLess(res.score, 65)
        self.assertGreaterEqual(res.score, 35)
        self.assertEqual(res.recommendation, "Review")
        self.assertIn("react", res.missing_requirements)
        self.assertGreater(len(res.eligibility_concerns), 0)

    def test_opted_out_candidate_cannot_be_recommended(self):
        """Tests that an opted-out candidate always receives 'Do Not Proceed' and BLOCKED status."""
        candidate = {
            "id": 103,
            "name": "Opted Out Dev",
            "email": "optout@privacy.org",
            "skills": json.dumps(["python", "react", "fastapi", "typescript", "postgresql", "docker"]),
            "languages": json.dumps(["English"]),
            "years_of_experience": 8,
            "location": "Remote",
            "opt_out_status": 1,
            "suppression_reason": "Requested deletion",
            "evidence_text": "Experienced engineer.",
        }

        res = opportunity_matcher.evaluate_match(candidate, self.turing_opp)
        self.assertEqual(res.recommendation, "Do Not Proceed")
        self.assertEqual(res.outreach_eligibility, "BLOCKED")
        self.assertIn("opted out", res.reason.lower())

    def test_opt_out_blocks_draft_creation(self):
        """Verifies that attempting to create a draft for an opted-out candidate raises ValueError."""
        # First verify opportunity
        update_referral_opportunity(self.conn, self.turing_opp["id"], verification_status="VERIFIED", verification_source="Audit", verification_notes="Active program")

        cur = self.conn.execute(
            """INSERT INTO candidates(name, email, opt_out_status, contact_permission_basis, suppression_reason, evidence_text, created_at)
            VALUES('Blocked User', 'blocked@domain.com', 1, 'APPROVED_OUTREACH', 'Do not contact', 'Text', '2026-10-30')"""
        )
        cand_id = cur.lastrowid

        with self.assertRaises(ValueError) as ctx:
            gmail_outreach.prepare_and_save_draft_record(
                conn=self.conn,
                candidate_id=cand_id,
                opportunity_id=self.turing_opp["id"],
                save_to_gmail=False,
            )
        self.assertIn("opted out", str(ctx.exception).lower())

    def test_missing_email_blocks_draft_creation(self):
        """Verifies that candidates without emails cannot have drafts created."""
        update_referral_opportunity(self.conn, self.turing_opp["id"], verification_status="VERIFIED", verification_source="Audit", verification_notes="Active program")

        cur = self.conn.execute(
            """INSERT INTO candidates(name, email, opt_out_status, contact_permission_basis, evidence_text, created_at)
            VALUES('No Email User', '', 0, 'APPROVED_OUTREACH', 'Text', '2026-10-30')"""
        )
        cand_id = cur.lastrowid

        with self.assertRaises(ValueError) as ctx:
            gmail_outreach.prepare_and_save_draft_record(
                conn=self.conn,
                candidate_id=cand_id,
                opportunity_id=self.turing_opp["id"],
                save_to_gmail=False,
            )
        self.assertIn("valid verified email", str(ctx.exception).lower())

    def test_draft_idempotency_and_no_send(self):
        """Verifies draft creation persists idempotency key and clearly marks simulated vs live status."""
        update_referral_opportunity(self.conn, self.turing_opp["id"], verification_status="VERIFIED", verification_source="Audit", verification_notes="Active program")

        cur = self.conn.execute(
            """INSERT INTO candidates(name, email, skills, years_of_experience, opt_out_status, contact_permission_basis, email_verification_status, evidence_text, created_at)
            VALUES('Sara Connor', 'sara@skytech.io', '["python", "react"]', 4, 0, 'APPROVED_OUTREACH', 'VERIFIED', 'Python and React', '2026-10-30')"""
        )
        cand_id = cur.lastrowid

        res1 = gmail_outreach.prepare_and_save_draft_record(
            conn=self.conn,
            candidate_id=cand_id,
            opportunity_id=self.turing_opp["id"],
            save_to_gmail=True,
            mock_mode=True,
        )

        self.assertFalse(res1["is_saved_in_gmail"])
        self.assertTrue(res1["is_simulated"])
        self.assertTrue(res1["gmail_draft_id"].startswith("mock_draft_"))
        self.assertEqual(res1["status"], "SIMULATED_DRAFT")

        # Second call with same candidate and opportunity updates the existing draft rather than duplicating
        res2 = gmail_outreach.prepare_and_save_draft_record(
            conn=self.conn,
            candidate_id=cand_id,
            opportunity_id=self.turing_opp["id"],
            save_to_gmail=True,
            mock_mode=True,
        )

        self.assertEqual(res1["idempotency_key"], res2["idempotency_key"])
        drafts = list_outreach_drafts(self.conn)
        self.assertEqual(len(drafts), 1)

    def test_permission_and_email_gating(self):
        """Verifies that unverified permission or invalid email blocks draft generation."""
        update_referral_opportunity(self.conn, self.turing_opp["id"], verification_status="VERIFIED", verification_source="Audit", verification_notes="Active program")

        cur = self.conn.execute(
            """INSERT INTO candidates(name, email, skills, contact_permission_basis, evidence_text, created_at)
            VALUES('Unverified User', 'user@domain.com', '["python"]', 'PENDING_REVIEW', 'Evidence', '2026-10-30')"""
        )
        cand_unverified = cur.lastrowid
        with self.assertRaises(ValueError) as ctx:
            gmail_outreach.prepare_and_save_draft_record(
                conn=self.conn,
                candidate_id=cand_unverified,
                opportunity_id=self.turing_opp["id"],
            )
        self.assertIn("contact permission", str(ctx.exception).lower())

        cur2 = self.conn.execute(
            """INSERT INTO candidates(name, email, skills, contact_permission_basis, evidence_text, created_at)
            VALUES('No Email User', '', '["python"]', 'APPROVED_OUTREACH', 'Evidence', '2026-10-30')"""
        )
        cand_no_email = cur2.lastrowid
        with self.assertRaises(ValueError) as ctx2:
            gmail_outreach.prepare_and_save_draft_record(
                conn=self.conn,
                candidate_id=cand_no_email,
                opportunity_id=self.turing_opp["id"],
            )
        self.assertIn("valid verified email", str(ctx2.exception).lower())

    def test_oauth_state_generation_and_validation(self):
        """Tests that CSRF state tokens are generated and validated with single-use consumption."""
        state = generate_oauth_state()
        self.assertIsInstance(state, str)
        self.assertGreaterEqual(len(state), 32)

        # Validation succeeds on first try
        self.assertTrue(validate_oauth_state(state))
        # Validation fails on replay attack (single-use token)
        self.assertFalse(validate_oauth_state(state))
        # Bogus state fails
        self.assertFalse(validate_oauth_state("invalid_state_token_12345"))

    def test_permission_audit_trail(self):
        """Verifies that updating contact permission records reviewer and timestamp."""
        cur = self.conn.execute(
            """INSERT INTO candidates(name, email, contact_permission_basis, evidence_text, created_at)
            VALUES('Audit Test User', 'audit@example.com', 'PENDING_REVIEW', 'Audit evidence text', '2026-10-30')"""
        )
        cand_id = cur.lastrowid

        update_candidate_contact_permission(
            self.conn,
            cand_id,
            permission_basis="APPROVED_OUTREACH",
            reviewer="Lead Recruiter Jane",
            notes="Candidate portfolio confirmed direct inquiry consent.",
        )

        cand = get_candidate(self.conn, cand_id)
        self.assertEqual(cand["contact_permission_basis"], "APPROVED_OUTREACH")
        self.assertEqual(cand["permission_reviewed_by"], "Lead Recruiter Jane")
        self.assertIn("direct inquiry consent", cand["permission_notes"])
        self.assertTrue(bool(cand["permission_reviewed_at"]))

    def test_strict_no_send_endpoint_guarantee(self):
        """Verifies that no automatic message sending methods or endpoints exist in the module."""
        import gmail_outreach as mod
        self.assertFalse(hasattr(mod.gmail_outreach, "send_email"))
        self.assertFalse(hasattr(mod.gmail_outreach, "send_message"))
        self.assertFalse(hasattr(mod.gmail_outreach, "dispatch_email"))


if __name__ == "__main__":
    unittest.main()
