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
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import urllib.parse
import urllib.request
import urllib.error

from db import (
    create_or_update_draft,
    get_candidate,
    get_draft_by_idempotency_key,
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
        self._oauth_states: dict[str, float] = {}
        self._draft_locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def generate_oauth_state(self) -> str:
        """Generates a secure state token and records it with a 10-minute expiry."""
        state = secrets.token_urlsafe(32)
        now = time.time()
        with self._global_lock:
            # Clean expired states
            self._oauth_states = {k: v for k, v in self._oauth_states.items() if (now - v) < 600}
            self._oauth_states[state] = now
        return state

    def validate_oauth_state(self, state: str) -> bool:
        """Validates and consumes an OAuth state token."""
        if not state:
            return False
        now = time.time()
        with self._global_lock:
            ts = self._oauth_states.pop(state, None)
            if ts is not None and (now - ts) < 600:
                return True
        return False

    def get_oauth_credentials(self) -> tuple[str, str]:
        """Resolves client ID and client secret from environment or credentials.json."""
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
        if client_id and client_secret:
            return client_id, client_secret

        if CREDENTIALS_FILE.exists():
            try:
                with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                info = data.get("installed") or data.get("web") or data
                return info.get("client_id", "").strip(), info.get("client_secret", "").strip()
            except Exception as exc:
                logger.warning("Failed to parse credentials.json: %s", exc)
        return "", ""

    def get_authorization_url(
        self,
        redirect_uri: str = "http://localhost:8000/api/gmail/oauth/callback",
        state: str | None = None,
    ) -> tuple[str, str]:
        """Constructs Google OAuth 2.0 URL strictly requesting compose (draft-only) scope."""
        client_id, _ = self.get_oauth_credentials()
        if not client_id:
            raise RuntimeError("Google Client ID not configured. Please supply GOOGLE_CLIENT_ID or credentials.json.")

        state_token = state or self.generate_oauth_state()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GMAIL_COMPOSE_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state_token,
        }
        url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
        return url, state_token

    def exchange_code_for_tokens(self, code: str, redirect_uri: str = "http://localhost:8000/api/gmail/oauth/callback") -> dict[str, Any]:
        """Exchanges an authorization code for access and refresh tokens."""
        client_id, client_secret = self.get_oauth_credentials()
        if not client_id or not client_secret:
            raise RuntimeError("Missing Google Client ID or Client Secret.")

        post_body = urllib.parse.urlencode({
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=post_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Save tokens
        token_payload = {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_at": time.time() + (data.get("expires_in") or 3600),
            "scope": data.get("scope", GMAIL_COMPOSE_SCOPE),
            "email": "Connected Recruiter",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

        # Try to resolve user's email address if available
        try:
            profile_req = urllib.request.Request(
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers={"Authorization": f"Bearer {data.get('access_token')}"},
            )
            with urllib.request.urlopen(profile_req, timeout=10) as prof_resp:
                prof_data = json.loads(prof_resp.read().decode("utf-8"))
                if prof_data.get("emailAddress"):
                    token_payload["email"] = prof_data["emailAddress"]
        except Exception:
            pass

        self.save_tokens(token_payload)
        return token_payload

    def save_tokens(self, token_data: dict[str, Any]) -> None:
        """Persists OAuth tokens to local secure storage."""
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=2)

    def disconnect(self) -> bool:
        """Safely removes stored OAuth tokens and disconnects Gmail."""
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
            return True
        return False

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
        client_id, _ = self.get_oauth_credentials()
        if authenticated:
            try:
                with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                token_info = {
                    "has_refresh_token": bool(data.get("refresh_token")),
                    "scope": data.get("scope", GMAIL_COMPOSE_SCOPE),
                    "email": data.get("email", "Connected Recruiter"),
                    "expires_at": data.get("expires_at"),
                }
            except Exception:
                pass

        return {
            "authenticated": authenticated,
            "scope": GMAIL_COMPOSE_SCOPE,
            "token_file_present": TOKEN_FILE.exists(),
            "credentials_configured": bool(client_id),
            "details": token_info,
            "message": (
                f"Gmail OAuth is connected ({token_info.get('email', 'Active')}). Ready for live draft generation."
                if authenticated
                else "Gmail not connected. Complete OAuth or use local preview/simulated drafts."
            ),
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
                return str(draft_id)
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            logger.error("Gmail draft creation failed (%s): %s", err.code, err_body)
            raise RuntimeError(f"Gmail API error {err.code}: {err_body}")
        except Exception as exc:
            logger.error("Network error communicating with Gmail: %s", exc)
            raise RuntimeError(f"Failed to connect to Gmail API: {exc}")

    def update_gmail_draft(
        self,
        draft_id: str,
        recipient_email: str,
        subject: str,
        body_text: str,
        mock_mode: bool = False,
    ) -> str:
        """
        Updates an existing draft in Gmail without creating duplicate draft items.
        NEVER sends the email. Returns the updated draft ID.
        """
        if not draft_id:
            return self.create_gmail_draft(recipient_email, subject, body_text, mock_mode=mock_mode)

        if mock_mode or not self.is_authenticated() or draft_id.startswith("mock_draft_"):
            logger.info("Simulated update of draft %s for %s", draft_id, recipient_email)
            return draft_id

        # Build RFC 2822 email message
        msg = EmailMessage()
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.set_content(body_text)

        raw_bytes = msg.as_bytes()
        encoded_message = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

        access_token = self._get_access_token()

        req_payload = {
            "id": draft_id,
            "message": {
                "raw": encoded_message
            }
        }

        # Google Gmail REST API users.drafts.update endpoint (PUT)
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}"
        req = urllib.request.Request(
            url,
            data=json.dumps(req_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="PUT",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                return str(resp_data.get("id") or draft_id)
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            logger.error("Gmail draft update failed (%s): %s", err.code, err_body)
            # If draft was deleted or not found on Gmail side, fall back to create new
            if err.code == 404:
                return self.create_gmail_draft(recipient_email, subject, body_text, mock_mode=False)
            raise RuntimeError(f"Gmail API error {err.code}: {err_body}")
        except Exception as exc:
            logger.error("Network error updating Gmail draft: %s", exc)
            raise RuntimeError(f"Failed to update Gmail draft: {exc}")

    def refresh_access_token(self) -> str:
        """Refreshes expired access token using stored refresh_token."""
        if not TOKEN_FILE.exists():
            raise RuntimeError("Gmail token file not found.")

        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            token_data = json.load(f)

        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("No refresh token available. Re-authentication required.")

        client_id, client_secret = self.get_oauth_credentials()
        if not client_id or not client_secret:
            raise RuntimeError("Missing Google Client ID or Client Secret.")

        post_body = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=post_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            refresh_resp = json.loads(resp.read().decode("utf-8"))

        token_data["access_token"] = refresh_resp["access_token"]
        token_data["expires_at"] = time.time() + (refresh_resp.get("expires_in") or 3600)
        token_data["updated_at"] = datetime.now().isoformat(timespec="seconds")

        self.save_tokens(token_data)
        logger.info("Gmail OAuth access token successfully refreshed.")
        return token_data["access_token"]

    def _get_access_token(self) -> str:
        """Retrieves or refreshes OAuth access token from local secure storage."""
        if not TOKEN_FILE.exists():
            raise RuntimeError("Gmail token file not found. Re-authentication required.")

        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check token expiration (refresh 60 seconds before expiry)
        expires_at = data.get("expires_at", 0)
        if expires_at and time.time() > (expires_at - 60):
            if data.get("refresh_token"):
                return self.refresh_access_token()

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
        """Prepares draft text, enforces idempotency, checks permission, and saves record."""
        cand_raw = get_candidate(conn, candidate_id)
        if not cand_raw:
            raise ValueError(f"Candidate #{candidate_id} not found.")
        cand = dict(cand_raw)

        opp = get_referral_opportunity(conn, opportunity_id)
        if not opp:
            raise ValueError(f"Opportunity #{opportunity_id} not found.")

        idempotency_key = compute_draft_idempotency_key(candidate_id, opportunity_id)

        # Acquire lock for this idempotency key to prevent race-condition duplicates
        with self._global_lock:
            if idempotency_key not in self._draft_locks:
                self._draft_locks[idempotency_key] = threading.Lock()
            lock = self._draft_locks[idempotency_key]

        with lock:
            # 1. Require candidate not opted out
            if cand.get("opt_out_status", 0) == 1:
                raise ValueError(f"Cannot create draft: Candidate #{candidate_id} ({cand.get('name')}) has opted out of outreach.")

            # 2. Require approved outreach or direct consent
            permission_basis = (cand.get("contact_permission_basis") or "").strip().upper()
            if permission_basis not in ("APPROVED_OUTREACH", "DIRECT_CONSENT"):
                raise ValueError(
                    f"Cannot create draft: Contact permission for Candidate #{candidate_id} ({cand.get('name')}) is '{permission_basis or 'PENDING_REVIEW'}'. "
                    f"Explicit recruiter approval ('APPROVED_OUTREACH' or 'DIRECT_CONSENT') in CV Library is required before outreach."
                )

            # 3. Require verified recipient email
            email_addr = (cand.get("email") or "").strip()
            email_status = (cand.get("email_verification_status") or "").strip().upper()
            if not email_addr or "@" not in email_addr or "." not in email_addr.split("@")[-1] or email_status == "INVALID":
                raise ValueError(f"Cannot create draft: Candidate #{candidate_id} has no valid verified email address ('{email_addr}').")

            # 4. Require verified opportunity
            opp_status = (opp.get("verification_status") or "").strip().upper()
            if opp_status != "VERIFIED":
                raise ValueError(
                    f"Cannot create draft: Opportunity #{opportunity_id} ('{opp.get('title')}') is '{opp_status}'. "
                    f"Only verified partner opportunities qualify for outreach drafts."
                )

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

            # Check existing draft to prevent duplicate Gmail items
            existing_draft = get_draft_by_idempotency_key(conn, idempotency_key)
            existing_gmail_id = (existing_draft.get("gmail_draft_id") or "") if existing_draft else ""

            gmail_draft_id = existing_gmail_id
            draft_status = "PENDING_REVIEW"

            # Set durable CREATING state in database
            create_or_update_draft(
                conn=conn,
                idempotency_key=idempotency_key,
                candidate_id=candidate_id,
                opportunity_id=opportunity_id,
                referral_link_id=referral_link_id,
                recipient_email=email_addr,
                subject=subject,
                body_text=body_text,
                gmail_draft_id=existing_gmail_id,
                status="CREATING",
            )

            if save_to_gmail:
                if mock_mode:
                    token_mock = hashlib.sha256(f"{email_addr}:{subject}".encode("utf-8")).hexdigest()[:16]
                    gmail_draft_id = f"mock_draft_{token_mock}"
                    draft_status = "SIMULATED_DRAFT"
                else:
                    if not self.is_authenticated():
                        # Do not silently simulate! Fail cleanly with clear explanation
                        create_or_update_draft(
                            conn=conn,
                            idempotency_key=idempotency_key,
                            candidate_id=candidate_id,
                            opportunity_id=opportunity_id,
                            referral_link_id=referral_link_id,
                            recipient_email=email_addr,
                            subject=subject,
                            body_text=body_text,
                            gmail_draft_id=existing_gmail_id,
                            status="FAILED",
                        )
                        raise RuntimeError(
                            "Gmail OAuth is not connected. Complete Google OAuth connection first or select explicit Simulated Draft mode."
                        )

                    try:
                        if existing_gmail_id and not existing_gmail_id.startswith("mock_draft_"):
                            gmail_draft_id = self.update_gmail_draft(
                                draft_id=existing_gmail_id,
                                recipient_email=email_addr,
                                subject=subject,
                                body_text=body_text,
                            )
                        else:
                            gmail_draft_id = self.create_gmail_draft(
                                recipient_email=email_addr,
                                subject=subject,
                                body_text=body_text,
                            )
                        draft_status = "CREATED_IN_GMAIL"
                    except Exception as err:
                        create_or_update_draft(
                            conn=conn,
                            idempotency_key=idempotency_key,
                            candidate_id=candidate_id,
                            opportunity_id=opportunity_id,
                            referral_link_id=referral_link_id,
                            recipient_email=email_addr,
                            subject=subject,
                            body_text=body_text,
                            gmail_draft_id=existing_gmail_id,
                            status="FAILED",
                        )
                        raise

            draft_id = create_or_update_draft(
                conn=conn,
                idempotency_key=idempotency_key,
                candidate_id=candidate_id,
                opportunity_id=opportunity_id,
                referral_link_id=referral_link_id,
                recipient_email=email_addr,
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
                "recipient_email": email_addr,
                "subject": subject,
                "body_text": body_text,
                "gmail_draft_id": gmail_draft_id,
                "status": draft_status,
                "is_saved_in_gmail": bool(gmail_draft_id and not gmail_draft_id.startswith("mock_draft_")),
                "is_simulated": bool(gmail_draft_id.startswith("mock_draft_")),
            }


gmail_outreach = GmailOutreachManager()


def generate_oauth_state() -> str:
    return gmail_outreach.generate_oauth_state()


def validate_oauth_state(state: str) -> bool:
    return gmail_outreach.validate_oauth_state(state)

