"""Opt-in TWO public-label requests only. No Gemini, credentials or patient data."""

import json
import os
from pathlib import Path

import httpx
from app.agent.conversation import ConversationService
from app.application.ai_quota import QuotaAgent
from app.application.medication_understanding import MedicationUnderstandingService
from app.infrastructure.memory_quota import MemoryQuota
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository
from app.infrastructure.openfda_knowledge import OpenFDAKnowledge

from .correctness02_support import RecordingTools, StubModel, build_harness


def main():
    if os.environ.get("C02_PUBLIC_LABEL_PROBE") != "1":
        raise SystemExit("Explicit public-source probe opt-in required")
    harness = build_harness()
    requests = []

    def bound(request):
        if len(requests) >= 2:
            raise RuntimeError("Two-request public-source budget exhausted")
        requests.append(str(request.url))

    with httpx.Client(event_hooks={"request": [bound]}) as client:
        knowledge = MedicationUnderstandingService(
            harness.root.enrollment,
            OpenFDAKnowledge(client, harness.root.clock, monotonic=__import__("time").monotonic),
            harness.root.clock,
        )
        tools = RecordingTools(
            registry=harness.root.registry,
            fallback=harness.root.orchestrator,
            medication_understanding=knowledge,
            clock=harness.root.clock,
        )
        conversation = ConversationService(
            model=StubModel(),
            tools=tools,
            fallback=harness.root.orchestrator,
            sessions=InMemoryAgentSessionRepository(harness.root.store),
            ids=harness.root.ids,
        )
        harness.root.ai_agent = QuotaAgent(
            repository=MemoryQuota(
                clock=harness.root.clock, nonce_factory=lambda: str(harness.root.ids.new_id()), limit=200
            ),
            conversation=conversation,
            fallback=harness.root.orchestrator,
            daily_limit=200,
        )
        harness.tools = tools
        for question in ["What is amlodipine generally used for?", "What is Metformin 500 mg used for?"]:
            harness.ask(question)
    lines = [
        "# Real public drug-label provider — actual replies",
        "",
        (
            "Mode: actual Backend API/Application/Agent read planning + synthe"
            "tic patient + real public openFDA calls. Gemini NOT RUN. Request "
            "cap: two; no retries."
        ),
        "",
    ]
    for index, row in enumerate(harness.rows, 1):
        payload = row["tools"][-1]["data"] if row["tools"] else {}
        knowledge = payload.get("general_knowledge") or {}
        status = "PASS" if knowledge.get("status") == "matched" else "PARTIAL"
        lines += [
            f"## Turn {index}",
            "",
            "User:",
            "> " + row["user"],
            "",
            (
                "Expected: source-matched ingredient-level explanation with real c"
                "itation; no personal prescription inference."
            ),
            "",
            "Actual Assistant:",
            *["> " + line for line in row["actual"].splitlines()],
            "",
            f"Assessment: {status}; actual provider status={knowledge.get('status')}, "
            f"reason={knowledge.get('reason')}.",
            f"Actual query: {requests[index - 1] if index <= len(requests) else 'not sent'}",
            "",
            "Tool evidence: `get_medication_understanding`, "
            + json.dumps(row["tools"][-1]["parameters"], ensure_ascii=False)
            if row["tools"]
            else "No tool call",
            "",
        ]
    Path("outputs/correctness02-live-knowledge.md").write_text("\n".join(lines), encoding="utf8")
    Path("outputs/correctness02-live-knowledge.json").write_text(
        json.dumps({"requests": requests, "rows": harness.rows, "gemini_requests": 0}, ensure_ascii=False, indent=2),
        encoding="utf8",
    )
    print("Public openFDA requests:", len(requests))
    for row in harness.rows:
        result = (row["tools"][-1]["data"].get("general_knowledge") or {}) if row["tools"] else {}
        print(row["user"], result.get("status"), result.get("reason"))
    harness.close()


if __name__ == "__main__":
    main()
