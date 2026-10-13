"""生成 SCHEMA_FIXTURE 与契约审计；不访问服务、不修改业务代码。"""

from __future__ import annotations

import copy
import hashlib
import html
import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "docs/external/pharmascan-api-openapi-0.8.0.json"
FIXTURES = ROOT / "tests/fixtures/stage2/v0_8_0"
OUTPUTS = ROOT / "outputs"
MODEL = "SCHEMA-model-v0.8.0"
SPACE = "SCHEMA-space-v0.8.0"
PREPROCESS = "SCHEMA-preprocess-v0.8.0"
NOTE = "SCHEMA_FIXTURE / demo_only：合成视觉证据，不确认药品、剂量、安全性或服药。"
SCHEMA_NAMES = {
    "model_info_success": "ModelInfo",
    "detect_success": "DetectResponse",
    "detect_unreliable_count": "DetectResponse",
    "embed_success": "Embedding",
    "match_success": "MatchResponse",
    "match_unknown": "MatchResponse",
    "match_ambiguous": "MatchResponse",
    "identify_success": "IdentifyResponse",
    "scan_success": "ScanResponse",
    "read_label_success": "ReadLabelResponse",
    "read_label_missing_directions": "ReadLabelResponse",
    "common_error": "Error",
}


SCHEMA_URI = "urn:pharmascan:openapi:0.8.0"


def validator(document: dict, name: str) -> Draft202012Validator:
    return validator_for_fragment(document, {"$ref": f"{SCHEMA_URI}#/components/schemas/{name}"})


def seed(document: dict, schema: dict):
    """由真实 schema 递归生成非空值；业务语义在 fixtures 中显式覆写。"""
    if "$ref" in schema:
        return seed(document, document["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]])
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        return seed(document, next(branch for branch in schema["anyOf"] if branch.get("type") != "null"))
    kind = schema.get("type")
    if kind == "object":
        return (
            {key: seed(document, value) for key, value in schema["properties"].items()}
            if "properties" in schema
            else {"synthetic": "demo_only"}
        )
    if kind == "array":
        return [seed(document, schema.get("items", {})) for _ in range(max(1, schema.get("minItems", 1)))]
    if kind == "boolean":
        return True
    if kind in {"number", "integer"}:
        return max(1, schema.get("minimum", 1))
    return "SCHEMA-demo-only"


def make_fixtures(document: dict) -> dict:
    schemas = document["components"]["schemas"]
    payloads = {name: seed(document, schemas[schema]) for name, schema in SCHEMA_NAMES.items()}
    for payload in payloads.values():
        for field, value in {
            "model_version": MODEL,
            "embedding_space_id": SPACE,
            "preprocess_version": PREPROCESS,
        }.items():
            if field in payload:
                payload[field] = value
        if "limits" in payload:
            payload["limits"] = NOTE
    model = payloads["model_info_success"]
    model.update(
        api_version="0.8.0",
        embedding_dim=256,
        normalized=True,
        crop_window=1.4,
        threshold=0.8,
        margin=0.05,
        calibration={"provenance": "SCHEMA_FIXTURE", "demo_only": True, "note": "合成决策参数，不是临床校准结果"},
        imprint={"synthetic": "demo_only", "enabled": False},
        training_coverage="SCHEMA_FIXTURE：未知真实训练覆盖",
        known_limits=[NOTE],
    )
    embedding = payloads["embed_success"]
    embedding.update(
        embedding=[1.0] + [0.0] * 255,
        dim=256,
        normalized=True,
        framed_by="box",
        imprint_reads=None,
        text_reading="not_requested",
    )
    input_check = {
        "type": "loose_pills",
        "checked": True,
        "abstained": False,
        "caption": "SCHEMA 合成散装药片",
        "message": None,
    }
    for name in ("detect_success", "detect_unreliable_count"):
        payloads[name].update(
            boxes=[[10, 20, 50, 60]],
            box_flags=[[]],
            pill_count=1,
            count_reliable=True,
            flags=[],
            found_by="SCHEMA-stand-in-finder",
            input_check=copy.deepcopy(input_check),
        )
    payloads["detect_success"].pop("message")
    payloads["detect_unreliable_count"].update(
        boxes=[[10, 20, 50, 60], [35, 20, 70, 60]],
        box_flags=[["merged"], ["merged"]],
        pill_count=2,
        count_reliable=False,
        flags=["count_uncertain"],
        message=None,
    )
    for name, decision, similarity, runner in (
        ("match_success", "match", 0.99, 0.4),
        ("match_unknown", "unknown", 0.3, 0.2),
        ("match_ambiguous", "ambiguous", 0.99, 0.98),
    ):
        result = {
            "decision": decision,
            "medication_id": "med-1" if decision == "match" else None,
            "name": "Demo medicine" if decision == "match" else None,
            "similarity": similarity,
            "closest": {
                "medication_id": "med-1",
                "name": "Demo medicine",
                "similarity": similarity,
            },
            "runner_up": {
                "medication_id": "med-2",
                "name": "Demo runner-up medicine",
                "similarity": runner,
            },
            "message": NOTE,
            "imprint_check": None,
            "imprint_read_for": [],
        }
        payloads[name].update(results=[result], threshold=model["threshold"], margin=model["margin"])
    identified = payloads["identify_success"]
    candidate = identified["candidates"][0]
    candidate.update(
        pill_id="SCHEMA-pill-a",
        name="Demo medicine",
        rxnorm_name="SCHEMA synthetic name",
        generic_name="SCHEMA synthetic ingredient",
        manufacturer="SCHEMA synthetic manufacturer",
        ingredients=["SCHEMA synthetic ingredient"],
        images=[{"url": "/demo_only/synthetic-pill.png", "kind": "SCHEMA-synthetic-not-fetched"}],
        similarity=0.99,
        imprint_match=False,
        imprint_read=0.0,
        imprint="SCHEMA-A",
        strength="SCHEMA synthetic strength",
        rxcui="SCHEMA-not-a-real-rxcui",
    )
    identified.update(
        notes=[NOTE],
        note=NOTE,
        confidence=None,
        catalogue_fit="weak",
        verdict="uncertain",
        verdict_message=NOTE,
        imprint_reads=None,
        input_check=copy.deepcopy(input_check),
        text_reading="not_requested",
    )
    scan = payloads["scan_success"]
    scan.update(
        found_by="SCHEMA-stand-in-finder",
        detection={key: copy.deepcopy(payloads["detect_success"][key]) for key in schemas["Detection"]["required"]},
        pills=[
            {
                "box": [10, 20, 50, 60],
                "quality_flags": [],
                "counted": True,
                "imprint_reads": None,
                **copy.deepcopy(payloads["match_success"]["results"][0]),
            }
        ],
        input_check=copy.deepcopy(input_check),
        message=None,
        text_reading="not_requested",
    )
    scan["dose"].update(deprecated=True, note="SCHEMA 合成旧式 advisory；后端拥有剂量决策，不用于临床")
    scan["dose"]["summary"].update(
        pills_seen=1,
        matched=1,
        unknown=0,
        unsure=0,
        all_ok=True,
        all_visually_matched=True,
        count_reliable=True,
        text=NOTE,
    )
    scan["dose"]["alerts"][0].update(
        type="SCHEMA_demo_only",
        severity="SCHEMA-nonclinical",
        message=NOTE,
        medication_ids=["med-1"],
        source="SCHEMA_FIXTURE",
        severity_graded=False,
        colour="SCHEMA-not-graded",
        speak=False,
        notify_caregiver=False,
        details={"demo_only": True},
    )

    def printed(value: str) -> dict:
        return {"value": value, "line": value}

    for name in ("read_label_success", "read_label_missing_directions"):
        label = payloads[name]
        label.update(note=NOTE, ocr_model=MODEL, source="photo", message=None)
        item = label["candidates"][0]
        item.update(
            name="Demo medicine",
            brand="SCHEMA synthetic brand",
            ingredients=[{"rxcui": "SCHEMA-not-a-real-rxcui", "name": "SCHEMA synthetic ingredient"}],
            strength="SCHEMA synthetic strength",
            rxcui="SCHEMA-not-a-real-rxcui",
            rxnorm_name="SCHEMA synthetic name",
            found_in=["Demo medicine"],
            first_line=0,
            fields={
                "directions": printed("Take 1 tablet at 08:00"),
                "quantity": printed("30"),
                "dose_form": printed("tablet"),
                "date": printed("2026-10-13"),
                "expiry_date": printed("2027-10-13"),
            },
            list_check={"status": "not_on_list", "medication_id": None, "message": NOTE},
        )
    payloads["read_label_missing_directions"]["candidates"][0]["fields"]["directions"] = None
    payloads["common_error"].update(code="invalid_input", detail="SCHEMA 合成错误，未发送任何请求", retry_after=None)
    return payloads


def schema_summary(document: dict, schema: dict) -> dict:
    resolved = document["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]] if "$ref" in schema else schema
    properties = resolved.get("properties", {})
    required = resolved.get("required", [])
    return {
        "schema": schema,
        "unconstrained": not schema,
        "type": resolved.get("type"),
        "required": required,
        "additional_properties": resolved.get("additionalProperties", True),
        "fields": {
            key: {
                "required": key in required,
                "nullable": validator_for_fragment(document, fragment).is_valid(None),
                "schema": fragment,
            }
            for key, fragment in properties.items()
        },
    }


def validator_for_fragment(document: dict, fragment: dict) -> Draft202012Validator:
    resource = Resource.from_contents(document, default_specification=DRAFT202012)
    registry = Registry().with_resource(SCHEMA_URI, resource)
    return Draft202012Validator({**fragment, "components": document["components"]}, registry=registry)


def audit(document: dict, source_hash: str, manifest: dict, generated_at: str) -> dict:
    operations = []
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            body = operation.get("requestBody", {})
            responses = {
                status: {
                    "description": response.get("description"),
                    "content": {
                        mime: schema_summary(document, media.get("schema", {}))
                        for mime, media in response.get("content", {}).items()
                    },
                }
                for status, response in operation["responses"].items()
            }
            operations.append(
                {
                    "path": path,
                    "method": method.upper(),
                    "operation_id": operation["operationId"],
                    "description": operation.get("description"),
                    "scope": "额外记录图片 endpoint，未请求" if "/image/" in path else "用户 endpoint",
                    "execution": "LIVE GET 仅见 stage2_live_smoke.json"
                    if path in {"/health", "/v1/model-info"}
                    else "仅审计 schema，未请求；feedback POST/DELETE 仅记录"
                    if "/feedback" in path
                    else "仅审计 schema，未请求",
                    "request": {
                        "body_required": body.get("required", False),
                        "content": {
                            mime: schema_summary(document, media.get("schema", {}))
                            for mime, media in body.get("content", {}).items()
                        },
                        "parameters": [
                            {**parameter, "schema_summary": schema_summary(document, parameter["schema"])}
                            for parameter in operation.get("parameters", [])
                        ],
                    },
                    "response_200": responses.get("200"),
                    "error_responses": {status: response for status, response in responses.items() if status != "200"},
                }
            )
    old = ROOT / "docs/external/pharmascan-api-openapi-0.4.0.json"
    return {
        "audit_kind": "OPENAPI_SCHEMA_CONTRACT_AUDIT",
        "generated_at_utc": generated_at,
        "nonclinical": True,
        "not_model_performance_evidence": True,
        "source": {
            "file": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": source_hash,
            "openapi": document["openapi"],
            "api_version": document["info"]["version"],
        },
        "historical_snapshot": {
            "file": old.relative_to(ROOT).as_posix(),
            "version": json.loads(old.read_text(encoding="utf-8"))["info"]["version"],
            "sha256": hashlib.sha256(old.read_bytes()).hexdigest(),
            "modified": False,
        },
        "operations": operations,
        "components": {
            name: schema_summary(document, schema) for name, schema in document["components"]["schemas"].items()
        },
        "fixtures": manifest,
        "omitted_vs_null": {
            "field": "DetectResponse.message",
            "required": False,
            "nullable": True,
            "omitted_fixture": "detect_success.json",
            "explicit_null_fixture": "detect_unreliable_count.json",
            "meaning": "字段省略不等同显式 null；均为契约合法值，不推断未打印的 directions。",
            "required_nullable_examples": [
                "MatchResult.medication_id",
                "MatchResult.name",
                "MatchResult.runner_up",
                "LabelCandidate.brand",
                "Ingredient.rxcui",
            ],
        },
        "contract_gaps": [
            {
                "field": "Embedding.embedding",
                "fact": "array<number> 无 minItems/maxItems；dim 无 const 256；256 仅为描述/运行时 model-info 的值",
                "schema_dimension_guaranteed": False,
                "schema_fixture_model_info_dim": manifest["metadata"]["embedding_dim"],
                "endpoint_description": document["paths"]["/v1/embed"]["post"].get("description"),
                "extra_safety_requirement": (
                    "256 维、有限数值、单位范数、normalized=true、metadata 一致；非 OpenAPI 长度保证"
                ),
            },
            {
                "field": "MatchRequest",
                "fact": "queries/gallery 外层 minItems=1，内层向量无长度约束；版本字段非 required",
                "extra_safety_requirement": "至少一个版本/space 标识、实际匹配模型与预处理及 space；不能只依赖 schema",
            },
            {
                "field": "Detection.boxes / ScanPill.box",
                "fact": "PIXEL xyxy 描述，数组无四元素约束；不使用 x/y/w/h",
                "extra_safety_requirement": "四个有限像素坐标、边界合法；count_reliable=false 不自动计数",
            },
            {
                "field": "ScanPill",
                "fact": "仅 box required、additionalProperties=true；decision/candidates 未类型化",
                "extra_safety_requirement": "合成 scan 扩展使用完整 MatchResult；测试另验该扩展，不声称 OpenAPI 强制",
            },
            {"field": "/v1/tools 200", "fact": "schema={}，不能证明任何输出字段存在"},
            {
                "field": "/v1/pills/{pill_id}/image/{n} 200",
                "fact": "描述 JPEG，但声明 application/json schema={}；未请求",
            },
            {"field": "ModelInfo.calibration / imprint", "fact": "自由对象，无内部 required；合成数据不得冒充校准"},
            {
                "field": "MatchResult.decision",
                "fact": "match/unknown/ambiguous enum；无跨字段决策约束",
                "extra_safety_requirement": "0.99 相似度非 99% 识别概率；合成阈值不提供临床性能证据",
            },
            {
                "field": "ReadLabelResponse / DocumentFields",
                "fact": "source 默认 photo 非 required；fields/directions 可省略或 null",
                "extra_safety_requirement": "directions 仅引用 synthetic Printed.value/line；缺失绝不补造用药指令",
            },
            {
                "field": "safety endpoints",
                "fact": "无 alert 不等于安全；coverage 与 source 必须保留；剂量决策属于主后端",
            },
        ],
        "live_evidence_file": "outputs/stage2_live_smoke.json",
        "live_get_summary": (
            json.loads((OUTPUTS / "stage2_live_smoke.json").read_text(encoding="utf-8"))
            if (OUTPUTS / "stage2_live_smoke.json").exists()
            else None
        ),
        "prohibited_actions_executed": [],
    }


def write_json(path: Path, value: dict) -> str:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def render_html(report: dict) -> str:
    esc = html.escape
    rows = []
    for operation in report["operations"]:
        success = operation["response_200"]["content"]
        summary = next(iter(success.values()), {})
        request = operation["request"]
        request_names = [value["schema"].get("$ref", "内联 schema") for value in request["content"].values()]
        request_names += [f"{p['in']}:{p['name']}{' *' if p['required'] else ''}" for p in request["parameters"]]
        details = esc(
            json.dumps(
                {
                    "request": {
                        "body_required": request["body_required"],
                        "body_schemas": {
                            mime: {"schema": item["schema"], "required": item["required"]}
                            for mime, item in request["content"].items()
                        },
                        "parameters": [
                            {key: parameter[key] for key in ("name", "in", "required", "schema")}
                            for parameter in request["parameters"]
                        ],
                    },
                    "200": summary.get("schema", {}),
                    "errors": {
                        status: {mime: item["schema"] for mime, item in response["content"].items()}
                        for status, response in operation["error_responses"].items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        rows.append(
            f"<tr><td><b>{esc(operation['method'])}</b> <code>{esc(operation['path'])}</code>"
            f"<small>{esc(operation['execution'])}</small></td><td>{esc(', '.join(request_names) or '无 body/参数')}"
            f"</td><td><code>{esc(summary.get('schema', {}).get('$ref', '空 schema'))}</code>"
            f"<small>required: {esc(', '.join(summary.get('required', [])) or '无')}</small></td>"
            f"<td>{esc(', '.join(operation['error_responses']))}<details><summary>请求 / 200 / 错误详情</summary>"
            f"<pre>{details}</pre></details></td></tr>"
        )
    gaps = "".join(
        f"<li><b>{esc(gap['field'])}</b> — {esc(gap['fact'])}"
        f"<small>{esc(gap.get('extra_safety_requirement', ''))}</small></li>"
        for gap in report["contract_gaps"]
    )
    live = report.get("live_get_summary")
    live_section = "<section><h2>LIVE GET 非临床证据</h2><p>尚未采集，不宣称成功。</p></section>"
    if live:
        live_rows = "".join(
            f"<li><code>{esc(item['url'])}</code> — HTTP {item['status']}, "
            f"{esc(str(item['content_type']))}, {item['response_bytes']} bytes, "
            f"schema errors={len(item['schema_errors'])}, passed={item['passed']}"
            f"<small>{esc(item['started_at_utc'])} → {esc(item['completed_at_utc'])}</small>"
            f"<small>SHA-256: {esc(str(item['sha256']))}</small></li>"
            for item in live["requests"]
        )
        live_section = (
            f"<section><h2>LIVE GET 非临床证据</h2><p>总体 passed={live['passed']}；"
            f"blockers={len(live['blockers_for_main_agent'])}。不证明图像识别或临床安全。</p><ul>{live_rows}</ul></section>"
        )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>PharmaScan 0.8.0 契约审计</title><style>"
        "body{font:15px/1.6 system-ui,sans-serif;background:#f5f8fc;color:#203047;margin:0}"
        "main{max-width:1250px;margin:auto;padding:32px}section{background:white;border:1px solid #dce5ef;"
        "border-radius:12px;padding:20px;margin:20px 0}h1{margin-bottom:8px}h2{font-size:20px}"
        ".badge{background:#e0f2fe;color:#075985;border-radius:6px;padding:5px 10px;display:inline-block}"
        "table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:10px;"
        "border-bottom:1px solid #e2e8f0;vertical-align:top}th{background:#eff6ff}"
        "small{display:block;color:#526579}code{overflow-wrap:anywhere}pre{white-space:pre-wrap;"
        "overflow-wrap:anywhere;max-height:350px;overflow:auto;background:#f8fafc;padding:10px}"
        "li{margin:12px 0}.scroll{overflow:auto}summary{cursor:pointer;color:#0369a1}</style><main>"
        '<h1>PharmaScan Stage2 · v0.8.0</h1><span class="badge">OpenAPI 契约审计 · 非模型性能评测</span>'
        f"<p>时间：{esc(report['generated_at_utc'])}<br>来源：{esc(report['source']['file'])}"
        f"<br><small>SHA-256：{esc(report['source']['sha256'])}</small></p>"
        "<section><h2>证据边界</h2><p>12 个 SCHEMA_FIXTURE 均为 demo_only 合成数据，provenance 在 sidecar manifest；"
        "payload 保持原响应结构。未 POST、DELETE、上传图片、使用 token 或跟随 redirect。</p>"
        "<p>实时仅 health 与 model-info 的 HTTPS GET；实际状态、时间、哈希及漂移见 "
        "<code>outputs/stage2_live_smoke.json</code>，不将 schema 合法或 0.99 相似度视为临床成功。</p>"
        "<p>历史 0.4.0 snapshot 保留，版本与 SHA-256 见 JSON 报告。</p></section>"
        f"{live_section}"
        '<section><h2>用户 endpoint 全量审计（含额外图片路径记录）</h2><div class="scroll">'
        "<table><thead><tr><th>操作 / 执行边界</th><th>请求</th><th>200 / required</th><th>错误 schema</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>"
        f"<section><h2>关键契约缺口与额外安全要求</h2><ul>{gaps}</ul></section>"
        "<section><h2>省略与 null</h2><p>detect_success.message 省略；detect_unreliable_count.message 显式 null。"
        "两者均合法但语义不同。MatchResult 的 medication_id/name/runner_up 为 required 且 nullable，"
        "不得省略。missing directions=null，不补造指令。</p>"
        "<p>Take 1 tablet at 08:00 只在合成标签 Printed.value/line 中，非真实处方或建议。</p></section>"
        "</main></html>\n"
    )


def main() -> None:
    document = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert document["info"]["version"] == "0.8.0"
    for schema in document["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    generated_at = datetime.now(UTC).isoformat()
    payloads = make_fixtures(document)
    FIXTURES.mkdir(exist_ok=True)
    entries = {}
    for name, payload in payloads.items():
        validator(document, SCHEMA_NAMES[name]).validate(payload)
        digest = write_json(FIXTURES / f"{name}.json", payload)
        entries[f"{name}.json"] = {
            "provenance": "SCHEMA_FIXTURE",
            "demo_only": True,
            "nonclinical": True,
            "schema_ref": f"#/components/schemas/{SCHEMA_NAMES[name]}",
            "sha256": digest,
            "schema_errors": [],
            "synthetic_data": True,
            "live_request_performed": False,
        }
    manifest = {
        "provenance": "SCHEMA_FIXTURE",
        "demo_only": True,
        "nonclinical": True,
        "generator": "tests/fixtures/stage2/generate_v0_8_0.py",
        "generated_at_utc": generated_at,
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": source_hash,
        "api_version": "0.8.0",
        "metadata": {
            "model_version": MODEL,
            "embedding_space_id": SPACE,
            "preprocess_version": PREPROCESS,
            "embedding_dim": 256,
            "normalized": True,
        },
        "synthetic_directions": "Take 1 tablet at 08:00",
        "directions_are_not_medical_advice": True,
        "thresholds_are_synthetic_not_calibrated": True,
        "known_regression": {
            "fixture": "detect_unreliable_count.json",
            "note": "合成一物体两重叠框，仅回归形状，不是 LIVE 再现；不得自动计数",
        },
        "entries": entries,
    }
    write_json(FIXTURES / "manifest.json", manifest)
    report = audit(document, source_hash, manifest, generated_at)
    write_json(OUTPUTS / "stage2_contract_audit.json", report)
    (OUTPUTS / "stage2_contract_audit.html").write_text(render_html(report), encoding="utf-8")
    print(
        f"SCHEMA_FIXTURE: {len(entries)} validated; OpenAPI components: {len(document['components']['schemas'])}; "
        f"audited operations: {len(report['operations'])}; source SHA-256: {source_hash}"
    )


if __name__ == "__main__":
    main()
