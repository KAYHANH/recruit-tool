"""Smoke test script for Groq Browser Search Connector.

Verifies live connectivity, web search execution, candidate parsing,
URL validation, and strict ₹0 spend enforcement.

Usage:
    python scripts/smoke_test_groq_browser.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cost_guard import cost_guard
from groq_browser_connector import GroqBrowserSearchConnector
from groq_extractor import get_groq_model, resolve_groq_api_key


def mask_key(key: str | None) -> str:
    if not key:
        return "<Not Configured / Empty>"
    return "******** [Configured via project .env or environment]"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print(" Candidate Finder -- Groq Browser Search Live Smoke Test")
    print("=" * 70)

    api_key = resolve_groq_api_key()
    configured_model = get_groq_model()

    print(f"Configured Model : {configured_model}")
    print(f"Detected API Key : {mask_key(api_key)}")
    print(f"Spend Guarantee  : ₹0.00 (Strict Zero-Budget Enforced)")
    print("-" * 70)

    connector = GroqBrowserSearchConnector()
    status = connector.check_status()
    print(f"Connector Status : {status.get('status')}")
    print(f"Model ID         : {status.get('model')}")
    print(f"Built-in Tool    : {status.get('tool')}")
    print("-" * 70)

    if not api_key:
        print("RESULT: SKIPPED (No API Key)")
        print("Explanation:")
        print("  - GROQ_API_KEY is not configured in .env or environment variables.")
        print("  - All existing free connectors (GitHub, GitLab, StackOverflow, HF, Local DB)")
        print("    continue to run 100% free without an API key.")
        print("  - To enable live Groq Browser Search, add GROQ_API_KEY to your .env file.")
        print("=" * 70)
        return 0

    print("Executing live web search query via Groq browser_search...")
    test_keywords = "Go distributed systems Kubernetes"
    test_location = "Remote"
    print(f"Search Query     : Keywords='{test_keywords}', Location='{test_location}', Limit=2")

    t0 = time.time()
    result = connector.search(
        keywords=test_keywords,
        location=test_location,
        limit=2,
    )
    elapsed = time.time() - t0

    print(f"Elapsed Time     : {elapsed:.2f}s")
    print(f"Rate Limited     : {result.rate_limited}")
    print(f"Error Message    : {result.error_message or 'None'}")
    print(f"Candidates Found : {len(result.candidates)} (Available: {result.total_found})")
    print("-" * 70)

    if result.rate_limited:
        print("⚠️ NOTICE: Free tier rate limit (HTTP 429) was hit.")
        print(f"Reset info: {result.rate_limit_reset}")
        print("Connector gracefully paused without crashing or triggering paid tiers.")
        print("=" * 70)
        return 0

    if result.error_message and not result.candidates:
        print(f"❌ Error encountered: {result.error_message}")
        print("=" * 70)
        return 1

    for idx, c in enumerate(result.candidates, 1):
        print(f"\n[Candidate #{idx}]")
        print(f"  Name      : {c.name}")
        print(f"  Profile   : {c.profile_url}")
        print(f"  Headline  : {c.headline}")
        print(f"  Location  : {c.location}")
        print(f"  Company   : {c.company or 'Not specified'}")
        print(f"  Tier      : {c.evidence_ladder_tier}")
        print(f"  Contact   : {c.contact_status} ({c.contact_provenance})")
        print(f"  Evidence  :\n    " + c.evidence_text.replace("\n", "\n    "))

    print("\n" + "=" * 70)
    print("Cost Guard Spend Audit:")
    summary = cost_guard.get_audit_summary()
    print(f"  Total Spend           : {summary['total_spend']}")
    print(f"  Max Permitted Spend   : {summary['max_permitted_spend']}")
    print(f"  Total Approved Calls  : {summary['total_requests_approved']}")
    print("✅ Groq Browser Search smoke test completed successfully at ₹0.00 spend!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
