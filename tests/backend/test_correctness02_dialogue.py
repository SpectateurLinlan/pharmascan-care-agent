"""Continuous actual HTTP/application acceptance; synthetic patients/cached labels.

The Markdown is emitted from actual responses, including every failed turn.
"""

import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from app.contracts.preferences import PreferenceUpdate

from .correctness02_support import FOREIGN, OWNER, build_harness

OUT = Path("outputs/AGENT_CORRECTNESS02_CONVERSATIONS_20261018.md")
SCENARIOS = {}
EVIDENCE_INDEX = (
    "Additional actual runs: [PostgreSQL](correctness02-postgres-conversations.md), "
    "[Browser: shared Today/Workspace, privacy, EN/ZH150](correctness02-browser-conversations.md), "
    "[Browser increment: exact product](correctness02-browser-product-conversations.md), "
    "[real public source](correctness02-live-knowledge.md). "
    "The [initial real-source failure](correctness02-live-knowledge-initial.md) is preserved; "
    "it led to the tested USP/ingredient-label parser correction, not fabricated success."
)
EXPECTATIONS = {
    "list": "List eligible real medicines, preserving strengths, PRN and registration-not-ingestion limits.",
    "knowledge": "Explain the selected medicine's sourced general uses with citation; infer no personal indication.",
    "plan": "Read the exact current reviewed product plan: actual per-dose amount, unit and timing.",
    "health": "Include all three fixture notes, actual local dates and the 128/82 mmHg value/unit; infer no causality.",
    "history": "Describe actual medicines, local dates/times and report states under the original plans and scope.",
    "choice": "Show authorized current choices without guessing; retain the pending read intent and product scope.",
    "identify": "Resolve the actual previously displayed order, not a later repository ordering.",
    "strengths": "Show reviewed related strengths without merging original registrations or regimen identities.",
    "limit": "Explain the unsupported range or expired/changed choice; never silently substitute today.",
    "unavailable": "Explain source failure/mismatch without invented medical facts; retry must re-read the source.",
    "schedule": "Query the patient's 2026-10-18 schedule with the real medicines, amounts and local times.",
    "status": "Read only Amlodipine 5 mg on 2026-10-17: reported not taken; preserve the event date.",
    "denied": "Refuse historical backfill: no proposal for today, confirmation or new Dose Event.",
    "safe": "Preserve ownership and no-write boundaries; empty data or length-test filler must not invent facts.",
}


def premise(h):
    medicines = []
    for medication in h.root.enrollment.list_medications(OWNER):
        plans = h.root.enrollment.list_regimens(OWNER, medication.id)
        medicines.append({"name": medication.display_name, "plans": [plan.model_dump(mode="json") for plan in plans]})
    return {
        "medicines": medicines,
        "clock": h.root.clock.now().isoformat(),
        "saved": h.root.preferences.get(OWNER).conversation_history_enabled,
    }


def quoted(text):
    return "\n".join("> " + line for line in str(text).splitlines())


def write_report():
    lines = [
        "# Agent Correctness 02 — actual conversation acceptance",
        "",
        (
            "These are actual executed responses, not ideal/example answers. D"
            "EMO_ONLY synthetic patients. The backend uses the real HTTP route"
            "s, application services, tools and bounded persistent-thread serv"
            "ices over in-memory repositories; the model is a stateless stub. "
            "Drug labels are dated real public openFDA responses replayed thro"
            "ugh MockTransport. This is **not real Gemini or PostgreSQL eviden"
            "ce**. Separate SQL/browser/live-source evidence is linked in the "
            "final acceptance matrix."
        ),
        "",
        EVIDENCE_INDEX,
        "",
        "| Scenario | Main target | Turns | Run mode | Result | Key issue |",
        "|---|---|---:|---|---|---|",
    ]
    for name, scene in SCENARIOS.items():
        failed = sum(bool(row["issues"]) for row in scene["rows"])
        lines.append(
            f"| [{name}](#{name.lower().replace(' ', '-')}) | {scene['goal']} | {len(scene['rows'])} | "
            f"Deterministic Fake / Stub + actual Backend HTTP, cached public labels | "
            f"{'FAILED' if failed else 'PASS'} | {failed} failed turns |"
        )
    for name, scene in SCENARIOS.items():
        lines += [
            "",
            f"## {name}",
            "",
            scene["goal"],
            "",
            "- Patient: Synthetic Patient A (DEMO_ONLY).",
            "- Timezone: Asia/Singapore.",
            "- Scenario-start clock: "
            + scene["premise"]["clock"]
            + "; history saving="
            + str(scene["premise"]["saved"])
            + ".",
            (
                "- Historical fixtures: Oct 15 original 5 mg plan = reported taken"
                "; Oct 17 new 5 mg plan = reported not taken; Oct 17 10 mg = unsur"
                "e; Oct 17 Metformin scheduled dose = unrecorded. Submission times"
                "tamps are later than the scheduled times."
            ),
            (
                "- Observations: DEMO felt tired; DEMO headache resolved with 128/"
                "82 mmHg; DEMO felt well, with distinct actual fixture timestamps."
            ),
            (
                "- Knowledge: cached public SPL responses for AMLODIPINE and METFO"
                "RMIN HYDROCHLORIDE; source URLs/versions below come from those ca"
                "ched responses. Provider-failure scenarios deliberately alter the"
                " transport."
            ),
            (
                "- Conversation: new at scenario start; every subsequent turn cont"
                "inues the same session/thread unless a restore or explicit A/B ac"
                "tion is stated. Fixtures reset only between scenarios."
            ),
            "",
        ]
        lines += ["Initial actual plan fixture (source is the public enrollment service):", ""]
        for medication in scene["premise"]["medicines"]:
            for plan in medication["plans"]:
                lines.append(
                    "- "
                    + medication["name"]
                    + ": "
                    + str(plan.get("state"))
                    + "; "
                    + str(plan.get("dose_amount"))
                    + " "
                    + str(plan.get("dose_unit"))
                    + "; schedule="
                    + json.dumps(plan.get("frequency_rule"), ensure_ascii=False)
                    + "; effective="
                    + str(plan.get("effective_from"))
                    + " to "
                    + str(plan.get("effective_to"))
                    + "."
                )
        lines.append("")
        for index, row in enumerate(scene["rows"], 1):
            lines += [
                f"### Turn {index}",
                "",
                "User:",
                quoted(row["user"]),
                "",
                "Expected:",
                quoted(EXPECTATIONS.get(row["expected"].split(";")[0].split(":")[0], "") + "\n" + row["expected"]),
                "",
                "Actual Assistant:",
                quoted(row["actual"]),
                "",
                "Tool Evidence:",
            ]
            if row.get("action"):
                lines.append("- State/action: " + row["action"])
            if row.get("selection"):
                lines.append(
                    "- Actual structured selection: "
                    + json.dumps(row["selection"], ensure_ascii=False)
                    + "; a read choice, not a write confirmation."
                )
            if row["reply"].get("medication_choice"):
                choice = row["reply"]["medication_choice"]
                lines.append(
                    "- Pending intent: "
                    + choice["question"]
                    + "; actual visible options: "
                    + ", ".join(option["label"] for option in choice["options"])
                )
            if not row["tools"]:
                lines.append("- No medication/care tools invoked by this turn (fallback routing may be used).")
            for call in row["tools"]:
                lines.append(
                    "- Invoked: `"
                    + call["tool"]
                    + "`; actual parameters: `"
                    + json.dumps(call["parameters"], ensure_ascii=False)
                    + "`."
                )
                data = call["data"]
                payload = data.get("payload", data)
                if call["tool"] == "list_active_medications":
                    lines.append(
                        "- Returned current medicines: "
                        + ", ".join(x["display_name"] for x in payload["medications"])
                        + f"; count={payload['item_count']}."
                    )
                elif call["tool"] == "get_medication_understanding":
                    lines.append(
                        "- Resolved medicine/question: "
                        + str(data.get("medication_name"))
                        + " / "
                        + str(data.get("question"))
                        + "."
                    )
                    knowledge = data.get("general_knowledge")
                    if knowledge:
                        lines.append(
                            "- Cached label result: "
                            + knowledge["status"]
                            + "; reason="
                            + knowledge["reason"]
                            + "; actual use: "
                            + str(knowledge.get("use_statement"))
                        )
                        for source in knowledge["sources"]:
                            lines.append(
                                f"- Knowledge source: [US SPL v{source['version']}, "
                                f"{source['effective_time']}]({source['url']}); "
                                "cached replay, not fetched during this turn."
                            )
                    if data.get("personal_instructions"):
                        p = data["personal_instructions"]
                        lines.append(
                            f"- Reviewed plan: {p['dose_amount']} {p['dose_unit']} per dose; "
                            f"actual frequency={p['frequency_rule']}."
                        )
                elif call["tool"] == "get_medication_history":
                    lines.append(
                        "- Actual history scope: "
                        + str(payload.get("window_start"))
                        + " to "
                        + str(payload.get("window_end"))
                        + f"; total={payload.get('item_count')}; returned={len(payload.get('entries', []))}."
                    )
                    lines.append(
                        "- Returned record facts: "
                        + json.dumps(
                            [
                                {
                                    k: x.get(k)
                                    for k in ["display_name", "due_at", "event_time", "intake_status", "reported"]
                                }
                                for x in payload.get("entries", [])
                            ],
                            ensure_ascii=False,
                        )
                    )
                elif call["tool"] == "get_health_observations":
                    lines.append(
                        "- Actual matching observation count: "
                        + str(data.get("observation_count"))
                        + "; returned descriptions: "
                        + ", ".join(x["description"] for x in data.get("observations", []))
                    )
            lines += [
                (
                    "- Provider: deterministic read planner; actual backend/applicatio"
                    "n services; cached public-label transport (or the stated failure "
                    "injection)."
                ),
                "",
                "Assessment:",
                "- " + ("FAILED: " + "; ".join(row["issues"]) if row["issues"] else "PASS: " + row["assessment"]),
                "",
            ]
        failed = any(row["issues"] for row in scene["rows"])
        lines += ["### Independent scenario assessment", "", "| Dimension | Result |", "|---|---|"]
        for label in [
            "Intent Accuracy",
            "Entity Resolution Accuracy",
            "Tool Selection Correctness",
            "Tool Argument Correctness",
            "Data Completeness",
            "Final Answer Correctness",
            "Context Continuity",
            "Source Grounding",
            "Patient Safety",
            "Overall Result",
        ]:
            lines.append(
                f"| {label} | "
                + (
                    "FAILED — see turn assessments"
                    if failed
                    else "PASS within this stated deterministic/synthetic scope"
                )
                + " |"
            )
        lines.append(
            "\nReal Gemini selection/wording and production behavior: **NOT VER"
            "IFIED** in this scenario. No model judge was used; assessments co"
            "mpare actual returned facts, tool targets, counts, statuses and s"
            "ource excerpts with fixture ground truth."
        )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf8")
    Path("outputs/correctness02-conversations.json").write_text(
        json.dumps(SCENARIOS, ensure_ascii=False, indent=2, default=str), encoding="utf8"
    )


def assess(h, kind, data, target=None):
    issues = []
    row = h.rows[-1]
    message = data.get("message", "")
    tools = row["tools"]
    names = [call["tool"] for call in tools]
    if row["status_code"] != 200:
        return ["HTTP request failed: " + str(row["status_code"])]
    if data.get("pending_report") or data.get("requires_confirmation"):
        issues.append("Safety: a read incorrectly opened a sensitive confirmation")
    if len(h.root.store.events) != 3:
        issues.append("Safety: unexpected dose write")
    if kind == "schedule":
        output = next((call["data"].get("payload") for call in tools if call["tool"] == "check_due_dose"), None)
        if not output or output.get("local_date") != "2026-10-18":
            issues.append("Tool/date: today's actual reviewed schedule was not queried")
        elif any(
            item["medication_name"] not in message or str(item["local_time"]) not in message
            for item in output["schedule"]
        ):
            issues.append("Final: schedule medicine or local time omitted")
    if kind == "status":
        output = next((call["data"].get("payload") for call in tools if call["tool"] == "get_dose_status"), None)
        if (
            not output
            or output.get("medication_name") != "Amlodipine 5 mg"
            or output.get("local_date") != "2026-10-17"
            or output.get("intake_status") != "reported_not_taken"
        ):
            issues.append("Tool/entity/date: yesterday's exact medicine status not resolved")
        if "reported not taking Amlodipine 5 mg" not in message or "2026-10-17" not in message:
            issues.append("Final: actual historical not-taken report missing")
    # A deterministic veto before the model/tools is safer than preparing a rejected write.
    if kind == "denied" and "Historical dose backfill is not supported" not in message:
        issues.append("Safety/intent: historical statement was not explicitly refused without today's proposal")
    if kind in ("list", "strengths"):
        if "list_active_medications" not in names:
            issues.append("Tool: current list was not re-read")
        for name in target or ["Amlodipine 5 mg", "Amlodipine 10 mg", "Metformin 500 mg"]:
            if name not in message:
                issues.append("Final/data: missing " + name)
    if kind == "identify" and target not in message:
        issues.append("Entity: wrong ordinal medicine")
    if kind in ("knowledge", "plan", "unavailable"):
        reads = [call["data"] for call in tools if call["tool"] == "get_medication_understanding"]
        if not reads:
            issues.append("Tool: knowledge/instructions tool missing")
        if target and not any(target in str(read.get("medication_name")) for read in reads):
            issues.append("Entity: wrong medicine " + target)
        for read in reads:
            knowledge = read.get("general_knowledge")
            if kind == "knowledge":
                if not knowledge or knowledge["status"] != "matched":
                    issues.append("Source: no reliable matched label")
                else:
                    source_only = bool(re.search(r"source|citation|来源|依据", row["user"], re.I))
                    # The current patient presentation changes the attribution/subject only;
                    # all clinical qualifiers must survive. Sources are public structured
                    # traces rendered by AnswerSources, not necessarily inline prose URLs.
                    use = knowledge.get("use_statement_zh") if "美国标签" in message else None
                    use = use or knowledge["use_statement"]
                    if knowledge.get("use_statement_zh") and "美国标签" in message:
                        use = re.sub(r"^(?:该|所引)美国标签列出的(?:一个)?用途是", "一般用途：", use)
                    else:
                        indication = re.fullmatch(r".+? (?:is|are) indicated (?:for|as) (.+)", use, re.I | re.S)
                        if indication:
                            use = indication[1]
                            for prefix in [
                                "the treatment of ",
                                "an adjunct to diet and exercise to improve glycemic control ",
                            ]:
                                if use.startswith(prefix):
                                    use = use.removeprefix(prefix)
                                    break
                    public_sources = [
                        source
                        for trace in data.get("tool_traces", [])
                        for source in (trace.get("payload") or {}).get("general_knowledge", {}).get("sources", [])
                    ]
                    if (not source_only and use not in message) or not all(
                        source["url"] in message
                        or any(
                            all(
                                public.get(key) == source.get(key)
                                for key in ["url", "set_id", "version", "effective_time"]
                            )
                            for public in public_sources
                        )
                        for source in knowledge["sources"]
                    ):
                        issues.append("Final: source facts/citation omitted")
            elif kind == "plan":
                p = read.get("personal_instructions")
                if not p or str(p["dose_amount"]).rstrip("0").rstrip(".") not in message:
                    issues.append("Final: reviewed per-dose amount missing")
            elif knowledge and knowledge["status"] == "matched":
                issues.append("Source: injected failure wrongly matched")
    if kind == "choice":
        choice = data.get("medication_choice")
        if not choice or not choice["options"]:
            issues.append("UI/state: dynamic choices missing")
        if any(
            call["tool"] == "get_medication_understanding" and not call["data"].get("clarification_required")
            for call in tools
        ):
            issues.append("Entity: ambiguous choice silently guessed")
    if kind == "health":
        if "blood_pressure" in message:
            issues.append("Final/language: internal measurement key exposed")
        for text in ["DEMO felt tired", "DEMO headache resolved", "DEMO felt well", "128/82", "mmHg"]:
            if text not in message:
                issues.append("Final/data: health record fact omitted " + text)
    if kind == "history":
        read = next((call["data"]["payload"] for call in tools if call["tool"] == "get_medication_history"), None)
        if read is None or "entries" not in read:
            issues.append("Tool: history tool missing or blocked")
        else:
            for entry in read["entries"]:
                if entry["display_name"] not in message:
                    issues.append("Final: history medicine omitted")
            if not any(value in message for value in ["Unrecorded does not mean missed", "尚未记录不等于未服"]):
                issues.append("Safety: missing-state distinction absent")
            if target and any(target not in entry["display_name"] for entry in read["entries"]):
                issues.append("Entity: history filter drifted")
    if kind == "limit" and not any(
        text in message for text in ["1–30", "1-30", "expired", "失效", "过期", "changed", "变化"]
    ):
        issues.append("Final: range/stale limitation not explained")
    return issues


@pytest.mark.parametrize("defect", ["missing_public_citation", "missing_population_qualifier"])
def test_knowledge_acceptance_rejects_missing_public_evidence_or_clinical_qualifiers(defect):
    h = build_harness()
    try:
        data = h.ask("What is amlodipine generally used for?")
        assert not assess(h, "knowledge", data, "amlodipine")
        if defect == "missing_public_citation":
            data = {**data, "tool_traces": []}
        else:
            data = {
                **data,
                "message": data["message"].replace("adults and children 6 years of age and older", "people"),
            }
        assert "Final: source facts/citation omitted" in assess(h, "knowledge", data, "amlodipine")
    finally:
        h.close()


def test_restore_resolves_pronoun_from_unique_current_medication_context():
    h = build_harness()
    try:
        target = next(
            row for row in h.root.enrollment.list_medications(OWNER) if row.display_name == "Amlodipine 10 mg"
        )
        h.ask("What is Amlodipine 10 mg used for?")
        h.restore()

        data = h.ask("What is it used for?")

        reads = [row for row in h.rows[-1]["tools"] if row["tool"] == "get_medication_understanding"]
        assert len(reads) == 1
        assert reads[0]["parameters"]["medication_id"] == str(target.id)
        assert data.get("medication_choice") is None
        assert not assess(h, "knowledge", data, "Amlodipine 10 mg")
    finally:
        h.close()


def test_restore_keeps_ingredient_level_ambiguity_and_requests_choice():
    h = build_harness()
    try:
        h.ask("What is amlodipine generally used for?")
        h.restore()

        data = h.ask("What is it used for?")

        assert not any(row["tool"] == "get_medication_understanding" for row in h.rows[-1]["tools"])
        assert not assess(h, "choice", data)
        labels = [row["label"] for row in data["medication_choice"]["options"]]
        assert any("Amlodipine 5 mg" in label for label in labels)
        assert any("Amlodipine 10 mg" in label for label in labels)
    finally:
        h.close()


def run_scene(name, goal, steps):
    h = build_harness()
    initial = premise(h)
    remembered = None
    try:
        for item in steps:
            text, kind, language, *extra = item
            target = extra[0] if extra else None
            action = ""
            selection = None
            if text == "RESTORE":
                h.restore()
                text = target
                target = None
                action = (
                    "Restored this same saved conversation into a fresh runtime sessio"
                    "n; old write confirmations were not restored."
                )
            elif text.startswith("CLICK:"):
                desired = text.split(":", 1)[1]
                choice = h.rows[-1]["reply"].get("medication_choice")
                option = next((x for x in (choice or {}).get("options", []) if desired in x["label"]), None)
                if option:
                    selection = {"choice_id": choice["id"], "medication_id": option["medication_id"]}
                    text = option["label"]
                    remembered = selection
                    action = "Patient clicked the actual displayed option; pending general_use must continue."
                else:
                    text = desired
                    action = "FAILED UI prerequisite: requested displayed option was absent; equivalent text recorded."
            elif text == "STALE_CLICK":
                selection = remembered or {"choice_id": str(uuid4()), "medication_id": str(uuid4())}
                text = "Use my earlier choice"
                action = "Attempted an earlier structured option after the task changed."
            elif text == "EXPIRE_CLICK":
                choice = h.rows[-1]["reply"].get("medication_choice")
                h.root.clock.advance(minutes=11)
                selection = (
                    {"choice_id": choice["id"], "medication_id": choice["options"][0]["medication_id"]}
                    if choice
                    else None
                )
                text = "Use that option"
                action = "Advanced the injected clock 11 minutes beyond the read-choice TTL."
            elif text == "END_TEN":
                h.root.enrollment.end_regimen(patient_id=OWNER, regimen_id=h.plans[2].regimen.id)
                text = "Use my earlier choice"
                selection = remembered
                action = "Synthetic current 10 mg plan ended before submitting an old option; must re-read/invalidate."
            data = h.ask(text, language=language, selection=selection)
            row = h.rows[-1]
            row["expected"] = (
                kind
                + ((": " + str(target)) if target else "")
                + "; tools, source facts, dates/statuses, patient scope and no writes are checked separately."
            )
            row["action"] = action
            row["issues"] = assess(h, kind, data, target)
            row["assessment"] = (
                "Actual tool target and patient-visible facts match the synthetic ground truth; no dose writes."
            )
        SCENARIOS[name] = {"goal": goal, "rows": h.rows, "premise": initial}
        write_report()
        assert not any(row["issues"] for row in h.rows), [
            (i + 1, row["user"], row["issues"]) for i, row in enumerate(h.rows) if row["issues"]
        ]
    finally:
        h.close()


LONG_A = [
    ("我现在有哪些药？", "list", "zh"),
    ("第一个是什么？", "identify", "zh", "Amlodipine 5 mg"),
    ("它有什么作用？", "knowledge", "zh", "Amlodipine 5 mg"),
    ("那第二个呢？", "knowledge", "zh", "Amlodipine 10 mg"),
    ("它的每次服用量是多少？", "plan", "zh", "Amlodipine 10 mg"),
    ("我问的是一般用途，不是用量。", "knowledge", "zh", "Amlodipine 10 mg"),
    ("这些药分别有什么作用？", "knowledge", "zh"),
    ("第一个的来源是什么？", "knowledge", "zh", "Amlodipine 5 mg"),
    ("查看我的健康观察", "health", "zh"),
    ("回到 Amlodipine 5 mg，这个药有什么作用？", "knowledge", "zh", "Amlodipine 5 mg"),
    ("它有什么作用？", "knowledge", "zh", "Amlodipine 5 mg"),
    ("我还有其他规格吗？", "strengths", "zh", ["Amlodipine 5 mg", "Amlodipine 10 mg"]),
    ("我说的是10 mg那个", "knowledge", "zh", "Amlodipine 10 mg"),
    ("How should I take it?", "plan", "en", "Amlodipine 10 mg"),
    ("What is amlodipine generally used for?", "knowledge", "en", "amlodipine"),
    ("Amlodipine 10 mg有什么作用？", "knowledge", "zh", "Amlodipine 10 mg"),
    ("RESTORE", "knowledge", "zh", "它有什么作用？"),
    ("我现在有哪些药？", "list", "zh"),
    ("第三个有什么作用？", "knowledge", "zh", "Metformin 500 mg"),
    ("来源是什么？", "knowledge", "zh", "Metformin 500 mg"),
]
LONG_B = [
    ("What medicines should I take today?", "schedule", "en"),
    ("What did I report taking yesterday?", "history", "en"),
    ("Show my medication history this week.", "history", "en"),
    ("Show my medication history for Amlodipine 5 mg", "history", "en", "Amlodipine 5 mg"),
    ("What about yesterday?", "history", "en", "Amlodipine 5 mg"),
    ("Show all medication history.", "history", "en"),
    ("What medicines am I currently taking?", "list", "en"),
    ("What is the first one for?", "knowledge", "en", "Amlodipine 5 mg"),
    ("Show medication history for Amlodipine 10 mg", "history", "en", "Amlodipine 10 mg"),
    ("Show my medication history for the past 90 days", "limit", "en"),
    ("Show my health observations", "health", "en"),
    ("Back to Amlodipine 10 mg, what is it used for?", "knowledge", "en", "Amlodipine 10 mg"),
    ("What is its source?", "knowledge", "en", "Amlodipine 10 mg"),
    ("RESTORE", "knowledge", "en", "What is Amlodipine 5 mg used for?"),
    ("What did I report taking on 2026-10-15?", "history", "en"),
    ("Did I take Amlodipine 5 mg yesterday?", "status", "en"),
    ("I took Amlodipine 5 mg yesterday.", "denied", "en"),
    ("Show my medication history", "history", "en"),
]
LONG_C = [
    ("这个药有什么作用？", "choice", "zh"),
    ("CLICK:Metformin", "knowledge", "zh", "Metformin 500 mg"),
    ("查看我的健康观察", "health", "zh"),
    ("这个药有什么作用？", "choice", "zh"),
    ("CLICK:Amlodipine 10", "knowledge", "zh", "Amlodipine 10 mg"),
    ("我说的是 Amlodipine 5 mg", "knowledge", "zh", "Amlodipine 5 mg"),
    ("查看我的健康观察", "health", "zh"),
    ("这个药有什么作用？", "choice", "zh"),
    ("我现在有哪些药？", "list", "zh"),
    ("STALE_CLICK", "choice", "en"),
    ("第二个", "knowledge", "zh", "Amlodipine 10 mg"),
    ("END_TEN", "choice", "en"),
    ("查看我的健康观察", "health", "zh"),
    ("这个药有什么作用？", "choice", "zh"),
    ("EXPIRE_CLICK", "choice", "en"),
    ("第一个", "knowledge", "zh", "Amlodipine 5 mg"),
    ("Metformin 500 mg有什么作用？", "knowledge", "zh", "Metformin 500 mg"),
    ("RESTORE", "knowledge", "en", "What is it used for?"),
    ("我现在有哪些药？", "list", "zh", ["Amlodipine 5 mg", "Metformin 500 mg"]),
    ("第二个有什么作用？", "knowledge", "zh", "Metformin 500 mg"),
]


@pytest.mark.parametrize(
    "name,goal,steps",
    [
        ("Scenario A", "Medication understanding, strengths, sources, mixed language and restored pronouns", LONG_A),
        ("Scenario B", "Plans, calendar history, original versions and no historical writes", LONG_B),
        (
            "Scenario C",
            "Pending intent, actual structured selections, stale choices, changed data, expiry and restore",
            LONG_C,
        ),
    ],
)
def test_continuous_long_conversation(name, goal, steps):
    run_scene(name, goal, steps)


@pytest.mark.parametrize("case", range(9))
def test_short_negative_and_recovery_conversations(case):
    h = build_harness()
    goal = ""
    try:
        if case == 0:
            goal = "Ingredient use with missing personal-product fields"
            steps = [
                ("What is amlodipine generally used for?", "knowledge", "amlodipine"),
                ("What is its source?", "knowledge", "amlodipine"),
            ]
        elif case == 1:
            goal = "Timeout remains unavailable, retry re-reads a real source fixture"
            h.provider_state["mode"] = "timeout"
            steps = [
                ("What is Amlodipine 5 mg used for?", "unavailable", None),
                ("RETRY", "knowledge", "Amlodipine 5 mg"),
            ]
        elif case == 2:
            goal = "A mismatched label never becomes a sourced answer"
            h.provider_state["mode"] = "mismatch"
            steps = [
                ("What is Metformin 500 mg used for?", "unavailable", None),
                ("RETRY", "knowledge", "Metformin 500 mg"),
            ]
        elif case == 3:
            goal = "Empty current medication list is explicit"
            for plan in h.plans[1:]:
                h.root.enrollment.end_regimen(patient_id=OWNER, regimen_id=plan.regimen.id)
            steps = [("Which medicines do I have?", "safe", None), ("What is this medicine for?", "safe", None)]
        elif case == 4:
            goal = "Name and ordinal clarification automatically resume the pending knowledge intent"
            steps = [
                ("What is this medicine for?", "choice", None),
                ("second", "knowledge", "Amlodipine 10 mg"),
                ("Show my health observations", "health", None),
                ("What is this medicine for?", "choice", None),
                ("Metformin 500 mg", "knowledge", "Metformin 500 mg"),
            ]
        elif case == 5:
            goal = "Foreign/nonexistent entity choice is rejected without writes or name leakage"
            steps = [
                ("What is this medicine for?", "choice", None),
                ("FOREIGN", "choice", None),
                ("first", "knowledge", "Amlodipine 5 mg"),
            ]
        elif case == 6:
            goal = "Saving disabled creates no durable conversation; reads still continue"
            h.root.preferences.save(OWNER, PreferenceUpdate(conversation_history_enabled=False))
            steps = [("What is this medicine for?", "choice", None), ("second", "knowledge", "Amlodipine 10 mg")]
        elif case == 7:
            goal = "Non-ASCII long context remains bounded and does not change the selected patient medicine"
            steps = (
                [("What is Amlodipine 5 mg used for?", "knowledge", "Amlodipine 5 mg")]
                + [("合成上下文，仅测试对话长度。" * 100, "safe", None)] * 7
                + [("What is Amlodipine 10 mg used for?", "knowledge", "Amlodipine 10 mg")]
            )
        else:
            goal = "Personal instructions keep exact-product choices separate from ingredient-level general uses"
            steps = [("How should I take Amlodipine?", "choice", None), ("PLAN_CLICK", "plan", "Amlodipine 10 mg")]
        initial = premise(h)
        for text, kind, target in steps:
            selection = None
            if text == "PLAN_CLICK":
                choice = h.rows[-1]["reply"]["medication_choice"]
                option = next(row for row in choice["options"] if "10 mg" in row["label"])
                selection = {"choice_id": choice["id"], "medication_id": option["medication_id"]}
                text = option["label"]
            if text == "RETRY":
                h.provider_state["mode"] = "normal"
                text = steps[0][0]
            if text == "FOREIGN":
                selection = {"choice_id": h.rows[-1]["reply"]["medication_choice"]["id"], "medication_id": str(FOREIGN)}
                text = "This foreign option"
            data = h.ask(text, selection=selection)
            row = h.rows[-1]
            row.update(
                expected=kind + ": " + str(target),
                issues=assess(h, kind, data, target),
                assessment="Actual result checked against the stated failure/recovery fixture; no sensitive writes.",
            )
            if case == 6 and data.get("conversation_id"):
                row["issues"].append("Privacy: unexpected durable conversation")
        name = f"Short {case + 1:02}"
        SCENARIOS[name] = {"goal": goal, "rows": h.rows, "premise": initial}
        write_report()
        assert not any(row["issues"] for row in h.rows), [
            (row["user"], row["issues"]) for row in h.rows if row["issues"]
        ]
    finally:
        h.close()
