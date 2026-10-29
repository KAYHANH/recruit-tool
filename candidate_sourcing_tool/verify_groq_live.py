from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from groq_extractor import (
    DEFAULT_GROQ_MODEL,
    extract_requirements_with_groq,
    get_groq_api_key,
    get_groq_model,
    load_project_env,
    resolve_groq_api_key,
    run_groq_live_smoke_test,
)
from jd_parser import parse_document
from keyword_extractor import extract_requirements
from title_extractor import extract_job_title


def mask_key(key: str | None) -> str:
    if not key:
        return "<Not Configured / Empty>"
    return "******** [Configured via project .env or environment]"


def run_live_verification(test_pdf_path: Path | None = None) -> int:
    print("=" * 70)
    print(" Candidate Finder -- Groq Live Connectivity & Model Verification")
    print("=" * 70)

    # 1. Resolve configuration
    api_key = get_groq_api_key()
    configured_model = get_groq_model()

    print(f"Configured Model : {configured_model}")
    print(f"Detected API Key : {mask_key(api_key)}")
    print(f"Default Fallback : {DEFAULT_GROQ_MODEL}")
    print("-" * 70)

    if not api_key:
        print("RESULT: SKIPPED (No API Key)")
        print("Explanation:")
        print("  - GROQ_API_KEY is not set in environment variables or a local .env file.")
        print("  - Candidate Finder runs 100% offline in Local Mode by default.")
        print("  - To enable live verification, create a .env file with:")
        print("      GROQ_API_KEY=gsk_your_key_here")
        print(f"      GROQ_MODEL={configured_model}")
        print("  - Unit tests will continue to run with mocked responses.")
        print("=" * 70)
        return 0

    # 2. Execute minimal smoke test (PRIVACY: Synthetic string only, NO candidate/DB data)
    print("Executing minimal live smoke test against Groq endpoint...")
    t0 = time.time()
    result = run_groq_live_smoke_test(api_key=api_key, model=configured_model)
    elapsed = time.time() - t0

    print(f"Elapsed Time     : {elapsed:.2f}s")
    print(f"Status Category  : {result['status_category']}")
    print(f"HTTP Status Code : {result['status_code']}")
    print(f"Schema Validated : {result['validated_schema']}")
    print(f"Message          : {result['message']}")

    if not result["success"]:
        print("\nDIAGNOSTIC GUIDANCE:")
        if result["status_category"] == "AUTH_ERROR_401":
            print("  - Your API key was rejected by Groq. Verify the key on https://console.groq.com/keys.")
        elif result["status_category"] == "MODEL_NOT_FOUND_404":
            print(f"  - Model '{configured_model}' was not found or is not accessible on your account.")
            print("  - Check active models at https://console.groq.com/docs/models and update GROQ_MODEL.")
        elif result["status_category"] == "BAD_REQUEST_400":
            print(f"  - Model '{configured_model}' returned 400 Bad Request.")
            print("  - This model may not support 'response_format': {'type': 'json_object'}.")
        elif result["status_category"] == "RATE_LIMIT_429":
            print("  - Groq rate limit was hit. Try again later or switch to local offline extractor.")
        print("-" * 70)
        return 1

    print("\n✅ Live smoke test passed successfully!")

    # 3. Optional validation of Competitive Data Scientist PDF if available
    pdf_candidates = [
        test_pdf_path,
        Path("C:/Users/Asus/Downloads/Competitive_Data_Scientist (2).pdf"),
        Path("C:/Users/Asus/Downloads/Competitive_Data_Scientist.pdf"),
        PROJECT_ROOT / "Competitive_Data_Scientist (2).pdf",
    ]
    target_pdf = next((p for p in pdf_candidates if p and p.exists()), None)

    if target_pdf:
        print("\n" + "-" * 70)
        print(f"Validating Real Input: {target_pdf.name}")
        print("-" * 70)
        try:
            pdf_bytes = target_pdf.read_bytes()
            jd_text = parse_document(pdf_bytes, target_pdf.name)
            
            print(f"Parsed PDF text length: {len(jd_text)} characters.")
            print(f"Calling Groq model ({configured_model}) with sanitized JD text...")
            
            ok_jd, reqs_jd, msg_jd = extract_requirements_with_groq(
                jd_text=jd_text,
                api_key=api_key,
                model=configured_model,
                timeout=25.0,
            )

            if ok_jd and reqs_jd:
                print("Extracted fields via Groq:")
                print(f"  - Job Title          : {reqs_jd.job_title}")
                print(f"  - Employment Type    : {reqs_jd.employment_type}")
                print(f"  - Location           : {reqs_jd.location}")
                print(f"  - Required Skills    : {reqs_jd.required_skills}")
                print(f"  - Preferred Skills   : {reqs_jd.preferred_skills}")
                print(f"  - Tools / Platforms  : {reqs_jd.tools_and_tech}")
            else:
                print(f"⚠️ Groq extraction on PDF failed: {msg_jd}")
                print("Falling back to local offline extractor verification.")
        except Exception as exc:
            print(f"Error reading or extracting PDF: {exc}")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Candidate Finder — Live Groq Verification")
    parser.add_argument("--pdf", type=str, default=None, help="Optional path to a test JD PDF")
    args = parser.parse_args()

    pdf_p = Path(args.pdf).resolve() if args.pdf else None
    sys.exit(run_live_verification(pdf_p))
