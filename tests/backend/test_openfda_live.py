"""Opt-in single public-label request; no patient data, Gemini, Stage2 or Supabase."""

import json
import os
import time
from pathlib import Path

import httpx
import pytest
from app.contracts.medication_knowledge import KnowledgeProduct
from app.infrastructure.memory_repos import SystemClock
from app.infrastructure.openfda_knowledge import OpenFDAKnowledge


@pytest.mark.skipif(os.getenv("RUN_OPENFDA_LIVE") != "1", reason="opt-in one public openFDA request")
def test_openfda_amlodipine_live():
    with httpx.Client() as client:
        result = OpenFDAKnowledge(client, SystemClock(), monotonic=time.monotonic).lookup(
            KnowledgeProduct(
                name="Amlodipine besylate",
                ingredients=["Amlodipine besylate"],
                form="tablet",
                route="oral",
                strength="5 mg",
                release="standard",
            )
        )
    report = {
        "classification": "OPENFDA LIVE",
        "status": result.status,
        "reason": result.reason,
        "candidate_count": result.candidate_count,
        "sources": [row.model_dump(mode="json", exclude={"sections"}) for row in result.sources],
    }
    target = Path("outputs/medication-understanding")
    target.mkdir(parents=True, exist_ok=True)
    (target / "live-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert result.status == "matched", result.reason
    assert result.use_statement and result.sources and result.sources[0].version
