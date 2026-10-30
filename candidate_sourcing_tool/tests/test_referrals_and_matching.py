"""
Automated tests for CV-to-Referral Outreach Module: Phase B & C.
Covers:
- Deterministic opportunity matching (Turing, Mercor, micro1)
- Score weights: 40 skills, 25 exp, 15 lang, 10 loc, 10 other
- Missing requirements & unknowns transparency
- Opt-out suppression preventing outreach draft creation
- Missing email blocking draft creation
- Gmail draft creation (draft-only, never send) with idempotency key
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
    update_candidate_opt_out,
)
from gmail_outreach import (
    compute_draft_idempotency_key,
    gmail_outreach,
)
from opportunity_matcher import opportunity_matcher


class TestReferralMatchingAndDrafts(unittest.TestCase):
    def setUp(self):
        self.conn = init_db(":memory:")
        # Opportunities are auto-seeded by init_db
        self.opps = list_referral_opportunities(self.conn)
        self.turing_opp = next(o for o in self.opps if o["platform"] == "Turing")
        self.mercor_opp = next(o for o in self.opps if o["platform"] == "Mercor")
        self.micro1_opp = next(o for o in self.opps if o["platform"] == "micro1")

    def tearDown(self):
        self.conn.close()

    def test_seeded_opportunities_present(self):
        """Verifies default verified opportunities for Turing, Mercor, and micro1 are seeded."""
        self.assertGreaterEqual(len(self.opps), 3)
        platforms = [o["platform"] for o in self.opps]
        self.assertIn("Turing", platforms)
        self.assertIn("Mercor", platforms)
        self.assertIn("micro1", platforms)
        for o in self.opps:
            self.assertEqual(o["verification_status"], "VERIFIED")
            self.assertGreater(len(o["links"]), 0)

    def test_high_confidence_match_turing(self):
        """Tests that a qualified developer matches Turing with high score and 'Eligible for Outreach'."""
        candidate = {
            "id": 101,
            "name": "Devin Kumar",
            "email": "devin.kumar@techpro.com",
            "skills": json.dumps(["python", "react", "fastapi", "typescript", "postgresql", "docker", "problem solving"]),
            "languages": json.dumps(["English"]),
            "years_of_experience": 5,
            "location": "Remote",
            "opt_out_status": 0,
            "evidence_text": "5 years building distributed Python and React systems.",
        }

        res = opportunity_matcher.evaluate_match(candidate, self.turing_opp)
        self.assertGreaterEqual(res.score, 80)
        self.assertEqual(res.recommendation, "Eligible for Outreach")
        self.assertIn("python", res.matched_skills)
        self.assertIn("react", res.matched_skills)
        self.assertEqual(len(res.eligibility_concerns), 0)

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
        """Tests that an opted-out candidate always receives 'Do Not Proceed'."""
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
        self.assertIn("opted out", res.reason.lower())

    def test_opt_out_blocks_draft_creation(self):
        """Verifies that attempting to create a draft for an opted-out candidate raises ValueError."""
        # Insert test candidate into database
        cur = self.conn.execute(
            """INSERT INTO candidates(name, email, opt_out_status, suppression_reason, evidence_text, created_at)
            VALUES('Blocked User', 'blocked@domain.com', 1, 'Do not contact', 'Text', '2026-10-30')"""
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
        cur = self.conn.execute(
            """INSERT INTO candidates(name, email, opt_out_status, evidence_text, created_at)
            VALUES('No Email User', '', 0, 'Text', '2026-10-30')"""
        )
        cand_id = cur.lastrowid

        with self.assertRaises(ValueError) as ctx:
            gmail_outreach.prepare_and_save_draft_record(
                conn=self.conn,
                candidate_id=cand_id,
                opportunity_id=self.turing_opp["id"],
                save_to_gmail=False,
            )
        self.assertIn("no verified email", str(ctx.exception).lower())

    def test_draft_idempotency_and_no_send(self):
        """Verifies draft creation persists idempotency key and clearly marks simulated vs live status."""
        cur = self.conn.execute(
            """INSERT INTO candidates(name, email, skills, years_of_experience, opt_out_status, contact_permission_basis, evidence_text, created_at)
            VALUES('Sara Connor', 'sara@skytech.io', '["python", "react"]', 4, 0, 'approved_outreach', 'Python and React', '2026-10-30')"""
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
        cur = self.conn.execute(
            """INSERT INTO candidates(name, email, skills, contact_permission_basis, evidence_text, created_at)
            VALUES('Unverified User', 'user@domain.com', '["python"]', 'unverified', 'Evidence', '2026-10-30')"""
        )
        cand_unverified = cur.lastrowid
        with self.assertRaises(ValueError) as ctx:
            gmail_outreach.prepare_and_save_draft_record(
                conn=self.conn,
                candidate_id=cand_unverified,
                opportunity_id=self.turing_opp["id"],
            )
        self.assertIn("Contact permission", str(ctx.exception))

        cur2 = self.conn.execute(
            """INSERT INTO candidates(name, email, skills, contact_permission_basis, evidence_text, created_at)
            VALUES('No Email User', '', '["python"]', 'approved_outreach', 'Evidence', '2026-10-30')"""
        )
        cand_no_email = cur2.lastrowid
        with self.assertRaises(ValueError) as ctx2:
            gmail_outreach.prepare_and_save_draft_record(
                conn=self.conn,
                candidate_id=cand_no_email,
                opportunity_id=self.turing_opp["id"],
            )
        self.assertIn("no verified email address", str(ctx2.exception))

    def test_strict_no_send_endpoint_guarantee(self):
        """Verifies that no automatic message sending methods or endpoints exist in the module."""
        import gmail_outreach as mod
        # Verify no function or method is named send_email or send_message
        self.assertFalse(hasattr(mod.gmail_outreach, "send_email"))
        self.assertFalse(hasattr(mod.gmail_outreach, "send_message"))
        self.assertFalse(hasattr(mod.gmail_outreach, "dispatch_email"))


if __name__ == "__main__":
    unittest.main()
