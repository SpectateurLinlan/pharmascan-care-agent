"""Opt-in Gemini + real isolated SQL/RLS integration; cached source labels are explicit.

python -m tests.backend.accept_release_gemini_sql --run-live --free-tier-attested
Requires THREADS_TEST_DSN localhost. Uses the same cumulative wire budget as other release QA.
"""

import argparse
import json

import httpx
from google import genai

from .accept_release_gemini import OUT, GeminiModel, Settings, WireBudget, bounded_retry_response, gemini_http_options
from .test_conversation_threads_sql import db
from .test_correctness02_sql import exercise_sql_patient_reads


def run():
    settings = Settings.from_env()
    budget = WireBudget(60)
    first = len(budget.requests)
    model = GeminiModel(
        model=settings.gemini_model,
        client_factory=lambda: genai.Client(
            api_key=settings.gemini_api_key,
            http_options={
                **gemini_http_options(),
                "httpx_client": httpx.Client(
                    transport=budget, timeout=12, event_hooks={"response": [bounded_retry_response]}
                ),
            },
        ),
    )
    # Reuse the guarded local fixture, including all migrations/platform shims.
    environment = db.__wrapped__()
    connection = next(environment)
    try:
        rows = exercise_sql_patient_reads(
            connection,
            model=model,
            first_question="Could you walk me through the medicines on my active treatment list?",
            write_report=False,
        )
        result = {
            "model": settings.gemini_model,
            "actual_api_requests": len(budget.requests) - first,
            "wire_range": [first + 1, len(budget.requests)],
            "rows": rows,
            "mode": "Real Gemini + FastAPI + PostgreSQL/authenticated RLS; cached openFDA fixture",
            "assessment": (
                "PASS assertions: actual medication facts, selection, owned session, foreign denial, zero dose writes"
            ),
        }
        (OUT / "gemini-sql.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}))
    finally:
        environment.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True)
    parser.add_argument("--free-tier-attested", action="store_true", required=True)
    parser.parse_args()
    run()
