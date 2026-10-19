"""Owner-opted-in live Gemini acceptance; synthetic local records only.

python -m tests.backend.accept_release_gemini --run-live --free-tier-attested
No Supabase signup, production writes, Billing changes or model fallback.
Wire-level budget includes every SDK retry. Reports never contain headers or reasoning.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
from app.agent.conversation import ConversationService  # noqa: E402
from app.application.ai_quota import QuotaAgent  # noqa: E402
from app.application.medication_understanding import MedicationUnderstandingService  # noqa: E402
from app.config import Settings  # noqa: E402
from app.infrastructure.gemini_model import GeminiModel, bounded_retry_response, gemini_http_options  # noqa: E402
from app.infrastructure.memory_quota import MemoryQuota  # noqa: E402
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository  # noqa: E402
from app.infrastructure.openfda_knowledge import OpenFDAKnowledge  # noqa: E402
from google import genai  # noqa: E402

from .correctness02_support import RecordingTools, build_harness  # noqa: E402

OUT = ROOT / "outputs/release"


class WireBudget(httpx.BaseTransport):
    def __init__(self, maximum: int):
        self.maximum = maximum
        journal = OUT / "gemini-wire.json"
        self.requests: list[dict] = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else []
        self.window = deque()
        self.last = 0.0
        self.cooldown = 0.0

    def handle_request(self, request):
        if len(self.requests) >= self.maximum:
            raise httpx.ConnectError("Acceptance request budget exhausted")
        estimated_tokens = len(request.content)  # Conservative UTF-8 upper bound.
        if estimated_tokens > 140000:
            raise httpx.ConnectError("Acceptance input budget exceeded")
        delay = max(0.0, self.last + 6.1 - time.monotonic(), self.cooldown - time.monotonic())
        if delay:
            time.sleep(delay)
        now = time.monotonic()
        while self.window and now - self.window[0][0] >= 60:
            self.window.popleft()
        if sum(value for _, value in self.window) + estimated_tokens > 140000:
            time.sleep(max(0, 60 - (now - self.window[0][0])))
            self.window.clear()
        self.last = time.monotonic()
        self.window.append((self.last, estimated_tokens))
        row = {"request": len(self.requests) + 1, "input_byte_bound": estimated_tokens}
        self.requests.append(row)
        try:
            with httpx.HTTPTransport(retries=0) as transport:
                response = transport.handle_request(request)
                response.read()
            row["status"] = response.status_code
            if response.status_code == 429:
                self.cooldown = time.monotonic() + 60
            if response.status_code < 400:
                payload = response.json()
                row["usage"] = payload.get("usage", {})
                row["tool_calls"] = [
                    {key: step[key] for key in ("name", "arguments") if key in step}
                    for step in payload.get("steps", payload.get("outputs", []))
                    if step.get("type") == "function_call"
                ]
            return response
        except httpx.HTTPError as error:
            row["error_type"] = type(error).__name__
            raise
        finally:
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / "gemini-wire.json").write_text(
                json.dumps(self.requests, indent=2, ensure_ascii=False), encoding="utf-8"
            )


SCENES = [
    (
        "EN medication/history continuity",
        "en",
        [
            "Could you walk me through the medicines on my active treatment list?",
            "What is due tonight?",
            "What are those medicines generally used for?",
            "Where does that information come from?",
            "What does the stronger amlodipine entry say about how much I take each time?",
            "Did I take Amlodipine 5 mg yesterday?",
            "Please show this week's medication reports with the dates and uncertain reports.",
            "What health observations have I saved lately?",
            "I took Amlodipine yesterday. Please record it.",
            "Help me prepare for a pharmacist visit using my saved observations and reports.",
            "What is this medicine for?",
            "Metformin",
        ],
    ),
    (
        "ZH mixed clarification/recovery",
        "zh",
        [
            "请把我正在使用的药列给我，规格不要混在一起。",
            "今晚有哪些计划需要查看？",
            "这个药有什么用？",
            "Metformin",
            "这个说明的来源是什么？",
            "查看昨天的服药自述，不要把没有记录算成未服。",
            "本周有哪些服药记录？",
            "最近记录过哪些健康数据？",
            "我昨天吃过药，帮我记到昨天。",
            "我想带着已保存的记录找医生复诊，应该询问哪些问题？",
            "What is this medicine generally used for?",
            "Amlodipine",
        ],
    ),
]


def run(maximum: int, targeted: bool = False, after_fix: bool = False):
    settings = Settings.from_env()
    assert settings.gemini_api_key, "Existing Gemini configuration required"
    budget = WireBudget(maximum)
    baseline_requests = len(budget.requests)
    report = {
        "model": settings.gemini_model,
        "mode": "Real Gemini + live openFDA + synthetic LOCAL memory, actual HTTP/services",
        "scenarios": [],
        "prior_requests": baseline_requests,
    }
    unavailable = 0
    scenes = (
        SCENES
        if not targeted
        else [
            (
                "Targeted repaired routes, button and restore",
                "en",
                [
                    "Could you walk me through the medicines on my active treatment list?",
                    "What are those medicines generally used for?",
                    "Where does that information come from?",
                    "Please show this week's medication reports with dates and uncertainty.",
                    "What does the stronger amlodipine entry say about how much I take each time?",
                    "[CLICK:1]",
                    "I took Amlodipine yesterday. Please record it.",
                    "Help me prepare for a pharmacist visit using my saved observations and reports.",
                    "[RESTORE] What health observations have I saved lately?",
                    "What is this medicine generally used for?",
                    "[CLICK:2]",
                ],
            )
        ]
    )
    if after_fix:
        scenes = [
            (
                "After-fix English continuous",
                "en",
                [
                    "Could you walk me through the medicines on my active treatment list?",
                    "What are those medicines generally used for?",
                    "Where does that information come from?",
                    "What does the stronger amlodipine entry say about how much I take each time?",
                    "[CLICK:1]",
                    "What is due tonight?",
                    "Did I take Amlodipine 5 mg yesterday?",
                    "Show medication records for this week.",
                    "What health observations have I saved lately?",
                    "Help me prepare for a pharmacist visit using my saved observations and reports.",
                    "What is this medicine generally used for?",
                    "[CLICK:2]",
                    "Where does that information come from?",
                    "[RESTORE] Please show this week's medication reports with dates and uncertainty.",
                    "I took Amlodipine yesterday. Please record it.",
                    "Can you list my current medication again, keeping different strengths separate?",
                ],
            ),
            (
                "After-fix Chinese focused continuity",
                "zh",
                [
                    "我吃的药分别有什么作用？",
                    "这些用途依据是什么来源？",
                    "Amlodipine 每次服用多少？",
                    "[CLICK:1]",
                    "查看本周服药记录，区分未服用和没有记录。",
                    "最近的健康观察有哪些？",
                    "帮我根据这些记录准备复诊问题。",
                    "[RESTORE] 我昨天吃了Amlodipine，请帮我记录。",
                ],
            ),
        ]
    capture = OUT / ("gemini-after-fix-final-20261019.json" if after_fix else "gemini-conversations.json")
    for title, language, questions in scenes:
        h = build_harness()
        with httpx.Client(timeout=12) as knowledge_http:
            knowledge = MedicationUnderstandingService(
                h.root.enrollment,
                OpenFDAKnowledge(knowledge_http, h.root.clock, monotonic=time.monotonic),
                h.root.clock,
            )
            tools = RecordingTools(
                registry=h.root.registry,
                fallback=h.root.orchestrator,
                medication_understanding=knowledge,
                long_term=h.root.long_term,
                enrollment=h.root.enrollment,
                observations=h.root.observations,
                clock=h.root.clock,
            )
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
            conversation = ConversationService(
                model=model,
                tools=tools,
                fallback=h.root.orchestrator,
                sessions=InMemoryAgentSessionRepository(h.root.store),
                ids=h.root.ids,
            )
            h.root.ai_agent = QuotaAgent(
                repository=MemoryQuota(clock=h.root.clock, nonce_factory=lambda: str(uuid4()), limit=200),
                conversation=conversation,
                fallback=h.root.orchestrator,
                daily_limit=200,
            )
            h.tools = tools
            scene = {
                "name": title,
                "ground_truth": {
                    "timezone": "Asia/Singapore",
                    "now": h.root.clock.now().isoformat(),
                    "medications": [p.medication.display_name for p in h.plans],
                    "reports": "Oct15 old5mg taken; Oct17 current5mg not_taken,10mg unsure,Metformin unrecorded",
                    "observations": "3 notes; tired, headache resolved 128/82mmHg, felt well",
                },
                "turns": [],
            }
            report["scenarios"].append(scene)
            for question in questions:
                start = len(budget.requests)
                selection = None
                original = question
                if question.startswith("[CLICK:"):
                    choice = h.rows[-1]["reply"]["medication_choice"]
                    index = int(question[7:-1])
                    selected = choice["options"][index]
                    selection = {"choice_id": choice["id"], "medication_id": selected["medication_id"]}
                    question = selected["label"]
                if question.startswith("[RESTORE] "):
                    assert (
                        h.client.get(
                            "/api/agent/conversations/" + h.conversation,
                            headers={"Authorization": "Bearer DEMO.correctness02-synthetic-token"},
                        ).status_code
                        == 200
                    )
                    h.session = None
                    question = question.removeprefix("[RESTORE] ")
                answer = h.ask(question, language=language, selection=selection)
                row = h.rows[-1]
                row["operation"] = original
                row["actual_api_requests"] = len(budget.requests) - start
                row["wire_range"] = [start + 1, len(budget.requests)] if len(budget.requests) > start else []
                row["no_unconfirmed_dose_write"] = len(h.root.store.events) == 3
                row["assessment"] = "NOT VERIFIED — awaiting fact/tool review"
                scene["turns"].append(row)
                report["actual_api_requests"] = len(budget.requests) - baseline_requests
                report["cumulative_api_requests"] = len(budget.requests)
                capture.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                print(
                    json.dumps(
                        {
                            "scene": title,
                            "turn": len(scene["turns"]),
                            "requests": row["actual_api_requests"],
                            "mode": answer.get("mode"),
                            "http": row["status_code"],
                        }
                    ),
                    flush=True,
                )
                if row["actual_api_requests"] and answer.get("mode") not in {"gemini", "records_only"}:
                    unavailable += 1
                if unavailable >= 2 or len(budget.requests) >= maximum:
                    report["stopped"] = "Repeated provider failure or wire budget reached; remaining scenarios NOT RUN"
                    capture.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                    return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True)
    parser.add_argument("--free-tier-attested", action="store_true", required=True)
    parser.add_argument("--max-requests", type=int, default=60, choices=range(1, 151))
    parser.add_argument("--targeted", action="store_true")
    parser.add_argument("--after-fix", action="store_true")
    args = parser.parse_args()
    run(args.max_requests, args.targeted, args.after_fix)
