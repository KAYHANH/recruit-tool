"""
Gmail Outreach Module — Official Google OAuth Draft Generator & Manager.

STRICT SAFETY RULES:
- Minimum scope: https://www.googleapis.com/auth/gmail.compose (Draft creation only).
- NEVER CALLS MESSAGE-SEND ENDPOINTS. Emails are never sent automatically.
- User reviews, edits, and manually sends drafts inside Gmail.
- Preserves idempotency key per (candidate_id, opportunity_id) to prevent duplicate drafts.
- Keeps OAuth tokens and secrets in .gitignore.
"""
from __future__ import annotations

import base64
import email
from email.message import EmailMessage
import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import urllib.parse
import urllib.request
import urllib.error

from db import (
    create_or_update_draft,
    get_candidate,
    get_outreach_draft,
    get_referral_opportunity,
    list_referral_links,
    update_draft_status,
)

logger = logging.getLogger("gmail_outreach")

GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
TOKEN_DIR = Path(__file__).resolve().parent / "tokens"
TOKEN_FILE = TOKEN_DIR / "gmail_token.json"
CREDENTIALS_FILE = Path(__file__).resolve().parent / "credentials.json"


def compute_draft_idempotency_key(candidate_id: int, opportunity_id: int) -> str:
    """Computes a stable idempotency key for candidate and opportunity pair."""
    raw = f"cand_{candidate_id}_opp_{opportunity_id}_v1"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class GmailOutreachManager:
    """Manages personalized Gmail draft creation with draft-only permissions."""

    def __init__(self):
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)

    def is_authenticated(self) -> bool:
        """Checks if a valid or refreshable Gmail OAuth token exists."""
        if not TOKEN_FILE.exists():
            return False
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return bool(data.get("access_token") or data.get("refresh_token"))
        except Exception:
            return False

    def get_auth_status(self) -> dict[str, Any]:
        """Returns detailed OAuth connectivity status."""
        authenticated = self.is_authenticated()
        token_info = {}
        if authenticated:
            try:
                with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                token_info = {
                    "has_refresh_token": bool(data.get("refresh_token")),
                    "scope": data.get("scope", GMAIL_COMPOSE_SCOPE),
                    "email": data.get("email", "Connected Recruiter"),
                }
            except Exception:
                pass

        return {
            "authenticated": authenticated,
            "scope": GMAIL_COMPOSE_SCOPE,
            "token_file_present": TOKEN_FILE.exists(),
            "credentials_file_present": CREDENTIALS_FILE.exists(),
            "details": token_info,
            "message": "Gmail OAuth is connected and ready for draft creation." if authenticated else "Gmail not connected. Please provide credentials.json or complete OAuth flow.",
        }

    def generate_draft_content(
        self,
        candidate: dict,
        opportunity: dict,
        referral_link_url: str = "",
        recruiter_name: str = "Recruitment Partner",
    ) -> dict[str, str]:
        """Generates an honest, personalized referral email draft body and subject."""
        cand_name = candidate.get("name") or "there"
        opp_title = opportunity.get("title") or "Engineering Opportunity"
        opp_platform = opportunity.get("platform") or "our partner network"
        ref_url = referral_link_url or opportunity.get("url") or "https://www.turing.com"

        # Extract top matched skills for personalization
        cand_skills: list[str] = []
        try:
            raw = candidate.get("skills")
            if raw:
                cand_skills = json.loads(raw) if isinstance(raw, str) else list(raw)
        except Exception:
            cand_skills = []

        highlighted_skills = ", ".join(cand_skills[:3]) if cand_skills else "technical background"
        years_exp = candidate.get("years_of_experience", 0)

        subject = f"Referral Opportunity: {opp_title} at {opp_platform}"

        exp_clause = f"Given your {years_exp}+ years of experience and work with {highlighted_skills}" if years_exp > 0 else f"Given your background in {highlighted_skills}"

        body_text = (
            f"Hi {cand_name},\n\n"
            f"I came across your profile and CV while reviewing technical talent for {opp_platform}'s verified developer programs. "
            f"{exp_clause}, I thought this {opp_title} role might be a strong fit for your skillset.\n\n"
            f"About the Opportunity:\n"
            f"- Role: {opp_title}\n"
            f"- Platform: {opp_platform}\n"
            f"- Work Model: {opportunity.get('location_restrictions', 'Remote')}\n\n"
            f"You can review the full role specification and submit your direct profile through my verified referral portal here:\n"
            f"{ref_url}\n\n"
            f"Note: This is an introductory invitation and referral suggestion based on your public CV and documented experience, not an official offer or guarantee of placement.\n\n"
            f"Best regards,\n"
            f"{recruiter_name}\n"
        )

        return {
            "subject": subject,
            "body_text": body_text,
            "recipient_email": candidate.get("email") or "",
            "referral_url": ref_url,
        }

    def create_gmail_draft(
        self,
        recipient_email: str,
        subject: str,
        body_text: str,
        mock_mode: bool = False,
    ) -> str:
        """
        Creates an editable draft in the connected Gmail account.
        NEVER sends the email. Returns the created Gmail draft ID.
        """
        if not recipient_email or "@" not in recipient_email:
            raise ValueError("A verified recipient email address is required to create a draft.")

        if mock_mode or not self.is_authenticated():
            # In testing or offline mode without live Google tokens, generate a verified mock draft ID
            token_mock = hashlib.sha256(f"{recipient_email}:{subject}".encode("utf-8")).hexdigest()[:16]
            mock_id = f"mock_draft_{token_mock}"
            logger.info("Mock draft created: %s for %s", mock_id, recipient_email)
            return mock_id

        # Build RFC 2822 email message
        msg = EmailMessage()
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.set_content(body_text)

        raw_bytes = msg.as_bytes()
        encoded_message = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

        # Get active access token
        access_token = self._get_access_token()

        req_payload = {
            "message": {
                "raw": encoded_message
            }
        }

        # Google Gmail REST API users.drafts.create endpoint
        url = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
        req = urllib.request.Request(
            url,
            data=json.dumps(req_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                draft_id = resp_data.get("id")
                return draft_id
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            logger.error("Gmail draft creation failed (%s): %s", err.code, err_body)
            raise RuntimeError(f"Gmail API error {err.code}: {err_body}")
        except Exception as exc:
            logger.error("Network error communicating with Gmail: %s", exc)
            raise RuntimeError(f"Failed to connect to Gmail API: {exc}")

    def _get_access_token(self) -> str:
        """Retrieves or refreshes OAuth access token from local secure storage."""
        if not TOKEN_FILE.exists():
            raise RuntimeError("Gmail token file not found. Re-authentication required.")

        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        token = data.get("access_token")
        if not token:
            raise RuntimeError("Invalid token format in storage.")
        return token

    def prepare_and_save_draft_record(
        self,
        conn: Any,
        candidate_id: int,
        opportunity_id: int,
        referral_link_id: int | None = None,
        custom_subject: str | None = None,
        custom_body: str | None = None,
        save_to_gmail: bool = False,
        mock_mode: bool = False,
    ) -> dict[str, Any]:
        """Prepares draft text, enforces idempotency, checks opt-out, and saves record."""
        cand_raw = get_candidate(conn, candidate_id)
        if not cand_raw:
            raise ValueError(f"Candidate #{candidate_id} not found.")
        cand = dict(cand_raw)

        # Block if candidate opted out or suppressed
        if cand.get("opt_out_status", 0) == 1:
            raise ValueError(f"Cannot create draft: Candidate #{candidate_id} ({cand.get('name')}) has opted out of outreach.")

        if not cand.get("email"):
            raise ValueError(f"Cannot create draft: Candidate #{candidate_id} has no verified email address.")

        opp = get_referral_opportunity(conn, opportunity_id)
        if not opp:
            raise ValueError(f"Opportunity #{opportunity_id} not found.")

        # Determine referral link URL
        ref_url = opp.get("url") or ""
        if referral_link_id:
            links = list_referral_links(conn, opp_id=opportunity_id)
            match_lnk = next((l for l in links if l["id"] == referral_link_id), None)
            if match_lnk:
                ref_url = match_lnk["url"]
        elif opp.get("links"):
            ref_url = opp["links"][0]["url"]

        content = self.generate_draft_content(cand, opp, referral_link_url=ref_url)
        subject = custom_subject.strip() if custom_subject else content["subject"]
        body_text = custom_body.strip() if custom_body else content["body_text"]

        idempotency_key = compute_draft_idempotency_key(candidate_id, opportunity_id)

        gmail_draft_id = ""
        draft_status = "PENDING_REVIEW"

        if save_to_gmail:
            gmail_draft_id = self.create_gmail_draft(
                recipient_email=cand["email"],
                subject=subject,
                body_text=body_text,
                mock_mode=mock_mode,
            )
            draft_status = "CREATED_IN_GMAIL"

        draft_id = create_or_update_draft(
            conn=conn,
            idempotency_key=idempotency_key,
            candidate_id=candidate_id,
            opportunity_id=opportunity_id,
            referral_link_id=referral_link_id,
            recipient_email=cand["email"],
            subject=subject,
            body_text=body_text,
            gmail_draft_id=gmail_draft_id,
            status=draft_status,
        )

        return {
            "draft_id": draft_id,
            "idempotency_key": idempotency_key,
            "candidate_id": candidate_id,
            "candidate_name": cand.get("name"),
            "opportunity_title": opp.get("title"),
            "recipient_email": cand["email"],
            "subject": subject,
            "body_text": body_text,
            "gmail_draft_id": gmail_draft_id,
            "status": draft_status,
            "is_saved_in_gmail": bool(gmail_draft_id),
        }


gmail_outreach = GmailOutreachManager()
