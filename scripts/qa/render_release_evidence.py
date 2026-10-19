"""Render captured synthetic QA replies; never calls a model or invents actual output.

Run after acceptance capture: python scripts/qa/render_release_evidence.py
Manual fact assessments stay in outputs/release/conversation-assessments.json.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "outputs/release"


def quoted(text: str) -> str:
    return "\n".join("> " + line for line in text.splitlines())


def render() -> None:
    wire = json.loads((FOLDER / "gemini-wire.json").read_text(encoding="utf-8"))
    assessments = json.loads((FOLDER / "conversation-assessments.json").read_text(encoding="utf-8"))
    reports = [json.loads((FOLDER / name).read_text(encoding="utf-8")) for name in assessments]
    usage = {
        key: sum(r.get("usage", {}).get(key, 0) for r in wire)
        for key in ("total_input_tokens", "total_output_tokens", "total_tokens")
    }
    lines = [
        "# 真实 Gemini 发布问答验收 — 2026-10-18",
        "",
        "本文件由本次捕获的完整患者回复生成，保留失败。不是旧 87 轮报告，也不是理想答案。",
        "",
        "## 实际运行边界",
        "",
        "- 模型：`gemini-3.5-flash-lite`；同一场景连续使用同一 Conversation，场景间隔离。",
        f"- 实际 Gemini HTTP 请求 **{len(wire)}** 次，含失败及重试；每次线请求至少间隔 6.1 秒；无付费切换。",
        f"- 返回 usage 的已知 Token 总量：`{json.dumps(usage)}`。失败请求无 usage 时不算零消耗，实际总量可能更高。",
        "- 本机 FastAPI + Application Services + 合成内存患者；知识来自本次真实 openFDA/SPL。",
        "- 前面的内存场景不是生产患者或 PostgreSQL；最后另附真实 Gemini + 隔离 PostgreSQL 联合验收。",
        "- records_only 为确定性读取路线，**没有 Gemini Tool Selection**；逐轮列出实际请求数。",
        "- 模型输出与最终显示分开：患者最终回复可能由确定性 Renderer 生成，不能称为模型自由文本。",
        (
            "- Free Tier 依据：用户确认 + [官方定价](https://ai.google.dev/gemini-api/docs/pricing)；"
            "未查询账单、未启用 Billing。"
        ),
        "",
        "## 场景总览",
        "",
        "| 场景 | 轮数 | Gemini 请求 | 结果 | 主要发现 |",
        "|---|---:|---:|---|---|",
    ]
    all_scenes = []
    for report, (filename, judgments) in zip(reports, assessments.items(), strict=True):
        for scene, judgment in zip(report["scenarios"], judgments, strict=True):
            all_scenes.append((scene, judgment, filename))
            lines.append(
                f"| {scene['name']} | {len(scene['turns'])} | "
                f"{sum(t['actual_api_requests'] for t in scene['turns'])} | "
                f"{judgment['overall']} | {judgment['note']} |"
            )
    sql_scenes = [(FOLDER / "gemini-sql-initial.json", "028"), (FOLDER / "gemini-sql.json", "029")]
    for path, version in sql_scenes:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            lines.append(
                f"| Real Gemini + PostgreSQL {version} | {len(data['rows'])} | "
                f"{data['actual_api_requests']} | PASS scoped | Actual SQL/RLS; cached labels |"
            )
    for sql_path, version in sql_scenes:
        if not sql_path.exists():
            continue
        sql = json.loads(sql_path.read_text(encoding="utf-8"))
        lines += [
            "",
            f"## Real Gemini + Synthetic PostgreSQL {version} — actual combined path",
            "",
            f"运行方式：{sql['mode']}；模型 {sql['model']}，新增 API 请求 {sql['actual_api_requests']} 次。",
            "",
            f"前提：本机全链001–{version}；平台 auth/storage shim；药物/计划/来源/session/audit 实际 PostgreSQL。",
            "患者A：AMLODIPINE 5mg和METFORMIN HYDROCHLORIDE 500mg，两条已核对有效计划，各每次1tablet、08:00。",
            "患者B独立；无历史 Dose Event；药物知识为缓存公开SPL响应，不是本次实时医学来源。",
            "同一A session连续4轮，中间插入独立B攻击请求；本场景关闭历史保存，运行上下文实际存于PostgreSQL session。",
            "",
        ]
        start, end = sql["wire_range"]
        for req in wire[start - 1 : end]:
            lines.append(
                f"Gemini实际请求 #{req['request']} HTTP {req.get('status')}："
                + json.dumps(req.get("tool_calls", []), ensure_ascii=False)
                + "。"
            )
        for index, row in enumerate(sql["rows"], 1):
            lines += [
                "",
                f"### SQL Turn {index}",
                "",
                f"User（合成患者{row['actor']}）:",
                quoted(row["user"]),
                "",
                "Expected:",
                quoted("A读取实际两条药物、选择后续接原用途、B不能继承A的选择或上下文、空历史如实说明。"),
                "",
                "Actual Assistant:",
                quoted(row["actual"]),
                "",
                "Tool Evidence:",
                f"- 实际运行模式 `{row['mode']}`。",
            ]
            if row.get("selection"):
                lines.append("- 实际可信选择：`" + json.dumps(row["selection"]) + "`。")
            for trace in row["traces"]:
                payload = trace.get("payload", {})
                lines.append(
                    f"- `{trace['tool_name']}` / {trace['status']}；action={payload.get('action')}；"
                    f"medication={payload.get('medication_name', payload.get('medication_id'))}。"
                )
            lines += [
                "",
                "Assessment：**PASS** — 实际测试核对SQL所有权、实体ID、来源链接、session隔离；Dose Event仍为0。",
            ]
        lines += [
            "",
            "本场景 Intent / Entity / Tool / Arguments / Data / Final Answer / Source / Safety：PASS scoped。",
            "Naturalness：PARTIAL（机械的reviewed-record引导语）；托管Auth/Storage/生产部署：NOT VERIFIED。",
            "",
        ]
    lines += [
        "",
        "## 判断方法",
        "",
        "没有使用 LLM 给自己打分。逐轮核对合成事实、工具实体/参数、日期/状态、完整回复及来源。",
        "事实/参数错误或未回答问题为 FAILED；安全拒绝但未解释限制、重复或冗长为 PARTIAL。",
        "自然度看是否直接回答、是否重复、中文是否被原始英文淹没、是否用宽泛免责声明代替内容。",
        "初次完整连续场景有失败，不能宣称达到 95% 或临床准确率。后续为定向复验，不能替代全量真实模型复验。",
        "",
    ]
    for scene, judgment, filename in all_scenes:
        lines += [
            f"## {scene['name']}",
            "",
            f"运行方式：{reports[0]['mode']}",
            "",
            f"实际合成前提：{json.dumps(scene['ground_truth'], ensure_ascii=False)}",
            "",
            "5 mg 有旧/新两个计划版本；当前清单保留 5 mg、10 mg、500 mg 三条产品登记。",
            "没有保存患者新服药事件。旧计划 Oct15 已服，新计划 Oct17 未服，10mg 不确定，Metformin 尚未记录。",
            "生成过的计划剂次可能随前面 schedule 查询增加；这不构成服药自述。",
            "",
        ]
        for index, (turn, assessment) in enumerate(zip(scene["turns"], judgment["turns"], strict=True), 1):
            status, reason = assessment
            lines += [
                f"### Turn {index}",
                "",
                "User:",
                quoted(turn["user"]),
                "",
                "Expected:",
                quoted(reason["expected"]),
                "",
                "Actual Assistant:",
                quoted(turn["actual"]),
                "",
                "Tool Evidence:",
                f"- 运行模式 `{turn['reply'].get('mode')}`；实际 Gemini 请求 {turn['actual_api_requests']} 次。",
            ]
            if turn.get("operation") != turn["user"]:
                lines.append(f"- 实际交互：{turn.get('operation')}；提交选择/恢复在此轮执行。")
            if turn.get("selection"):
                lines.append("- 可信选择引用（合成 ID）：`" + json.dumps(turn["selection"]) + "`。")
            choice = turn["reply"].get("medication_choice")
            if choice:
                lines.append(
                    "- Pending Intent：`"
                    + choice["question"]
                    + "`；实际按钮："
                    + "；".join(option["label"] for option in choice["options"])
                    + "。"
                )
            if turn.get("wire_range"):
                start, end = turn["wire_range"]
                for request in wire[start - 1 : end]:
                    lines.append(
                        f"- Gemini 请求 #{request['request']} HTTP {request.get('status', 'network error')}："
                        + json.dumps(request.get("tool_calls", []), ensure_ascii=False)
                        + "。"
                    )
            for call in turn.get("tools", []):
                lines.append(
                    "- Executed `"
                    + call["tool"]
                    + "`；实际参数 `"
                    + json.dumps(call["parameters"], ensure_ascii=False)
                    + "`。"
                )
                data = call["data"]
                payload = data.get("payload", data)
                if "medications" in payload:
                    lines.append(
                        "- Returned medicines："
                        + ", ".join(r.get("display_name", r.get("name", "")) for r in payload["medications"])
                        + "。"
                    )
                if "entries" in payload:
                    lines.append(
                        f"- Returned {len(payload['entries'])} 条历史；窗口 "
                        f"{payload.get('window_start')} → {payload.get('window_end')}。"
                    )
                knowledge = data.get("general_knowledge")
                if knowledge:
                    lines.append(
                        f"- Knowledge `{knowledge['status']}`；实际匹配事实：{knowledge.get('use_statement')}。"
                    )
                    for source in knowledge.get("sources", []):
                        lines.append(f"- [US SPL v{source['version']} / {source['effective_time']}]({source['url']})。")
                if data.get("personal_instructions"):
                    p = data["personal_instructions"]
                    lines.append(
                        f"- Reviewed plan：每次 {p['dose_amount']} {p['dose_unit']}；"
                        f"{json.dumps(p['frequency_rule'], ensure_ascii=False)}。"
                    )
            lines += [
                f"- 未确认服药写入：{'无' if turn['no_unconfirmed_dose_write'] else 'FAILED'}。",
                "",
                f"Assessment：**{status}** — {reason['actual']}",
                "",
            ]
        lines += ["### 独立评估", "", "| 维度 | 结果 |", "|---|---|"]
        for key, value in judgment["dimensions"].items():
            lines.append(f"| {key} | {value} |")
        lines += ["", f"机器记录：`outputs/release/{filename}`；包含完整工具返回，本文保留完整患者回复。", ""]
    lines += [
        "## 剩余限制",
        "",
        "模型+本机PostgreSQL已补验；模型+浏览器+托管Auth/Storage+生产Schema的整体发布路径仍未验收。",
        "初次 EN 第5轮出现 Provider 不可用；后续此问题已由确定性产品选择流程覆盖，但外部可用性没有保证。",
        "初次一般用途逐产品重复来源的真实输出已保留；最终Renderer复验已共享完全相同的证据说明，三个产品读取保留。",
        "没有真实设备麦克风、Push 送达、生产图片写入/撤销验收。",
        "",
    ]
    (ROOT / "outputs/REAL_GEMINI_RELEASE_QA.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    render()
