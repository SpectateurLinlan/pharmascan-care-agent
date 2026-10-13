"""仅捕获两个允许的 HTTPS GET；不上传、无认证、无重定向、无重试。"""

from __future__ import annotations

import hashlib
import http.client
import json
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "docs/external/pharmascan-api-openapi-0.8.0.json"
DIRECTORY = ROOT / "tests/fixtures/stage2/v0_8_0"
HOST = "davidpansx-pharmascan-api.hf.space"
TIMEOUT_SECONDS = 20
MAX_BYTES = 1024 * 1024
TARGETS = (("/health", "Health", "health_live.json"), ("/v1/model-info", "ModelInfo", "model_info_live.json"))
CONDITIONS = {
    "method": "GET",
    "https_only": True,
    "verify_tls": True,
    "follow_redirects": False,
    "timeout_seconds": TIMEOUT_SECONDS,
    "deadline": "单次 GET 总预算，连接及每次读取共享单调时钟 deadline",
    "max_response_bytes": MAX_BYTES,
    "max_attempts_per_endpoint": 1,
    "token_used": False,
    "authentication_used": False,
    "body_sent": False,
    "images_uploaded": False,
    "post_performed": False,
    "delete_performed": False,
    "proxy_environment_used": False,
    "nonclinical": True,
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("20-second total GET deadline exceeded")
    return seconds


def reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON constant: {value}")


def capture(path: str, schema_name: str, filename: str, document: dict) -> tuple[dict, object]:
    if (path, schema_name, filename) not in TARGETS:
        raise ValueError("仅允许 TARGETS 中的两个 HTTPS GET")
    started = time.monotonic()
    deadline = started + TIMEOUT_SECONDS
    record = {
        "provenance": "LIVE",
        "synthetic_data": False,
        "url": f"https://{HOST}{path}",
        "method": "GET",
        "started_at_utc": now(),
        "conditions": CONDITIONS,
        "status": None,
        "content_type": None,
        "response_bytes": 0,
        "sha256": None,
        "body_complete": False,
        "schema_ref": f"#/components/schemas/{schema_name}",
        "schema_validation_performed": False,
        "schema_errors": [],
        "condition_errors": [],
        "raw_payload_file": None,
        "outcome": "not_executed",
        "nonclinical": True,
    }
    body = bytearray()
    payload = None
    connection = http.client.HTTPSConnection(HOST, timeout=remaining(deadline), context=ssl.create_default_context())
    try:
        connection.connect()
        connection.sock.settimeout(remaining(deadline))
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "PharmaScan-Stage2-contract-smoke/0.8.0",
            },
        )
        connection.sock.settimeout(remaining(deadline))
        response = connection.getresponse()
        record["status"] = response.status
        record["content_type"] = response.getheader("Content-Type")
        record["content_length_header"] = response.getheader("Content-Length")
        record["server_date_header"] = response.getheader("Date")
        if 300 <= response.status < 400:
            record["condition_errors"].append("redirect_response_not_followed")
        declared = response.getheader("Content-Length")
        if declared is not None and int(declared) > MAX_BYTES:
            record["condition_errors"].append("response_content_length_exceeds_1MiB")
        else:
            while len(body) < MAX_BYTES:
                remaining(deadline)
                stream_socket = connection.sock
                if stream_socket is None and response.fp is not None:
                    stream_socket = response.fp.raw._sock  # http.client 的响应流持有关闭连接的 socket。
                if stream_socket is not None:
                    stream_socket.settimeout(remaining(deadline))
                chunk = response.read1(min(65536, MAX_BYTES - len(body)))
                if not chunk:
                    record["body_complete"] = True
                    break
                body.extend(chunk)
                remaining(deadline)
            if len(body) == MAX_BYTES:
                if response.isclosed() or response.length == 0:
                    record["body_complete"] = True
                else:
                    record["condition_errors"].append("response_reached_1MiB_cap_without_eof")
            if declared is not None and record["body_complete"] and len(body) != int(declared):
                record["condition_errors"].append("content_length_mismatch")
        media_type = (record["content_type"] or "").split(";", 1)[0].strip().lower()
        if response.status != 200:
            record["condition_errors"].append(f"http_status_{response.status}")
        if media_type != "application/json":
            record["condition_errors"].append("content_type_not_application_json")
        if response.status == 200 and media_type == "application/json" and record["body_complete"]:
            payload = json.loads(body, parse_constant=reject_json_constant)
            schema_uri = "urn:pharmascan:live-contract:0.8.0"
            registry = Registry().with_resource(
                schema_uri, Resource.from_contents(document, default_specification=DRAFT202012)
            )
            responses = document["paths"][path]["get"]["responses"]
            actual = responses.get(str(response.status), {}).get("content", {}).get("application/json")
            if actual is None:
                record["condition_errors"].append("undocumented_http_status")
            fragment = actual.get("schema", {}) if actual else {"$ref": f"#/components/schemas/{schema_name}"}
            record["schema_ref"] = fragment.get("$ref")
            check = Draft202012Validator({**fragment, "components": document["components"]}, registry=registry)
            record["schema_validation_performed"] = True
            record["schema_errors"] = [
                {
                    "instance_path": list(error.absolute_path),
                    "schema_path": list(error.absolute_schema_path),
                    "validator": error.validator,
                    "message": error.message,
                }
                for error in check.iter_errors(payload)
            ]
            if response.status == 200 and isinstance(payload, dict):
                if payload.get("api_version") != "0.8.0":
                    record["condition_errors"].append("api_version_drift")
                if schema_name == "Health" and payload.get("ready") is not True:
                    record["condition_errors"].append("service_not_ready")
                if schema_name == "ModelInfo":
                    if payload.get("embedding_dim") != 256:
                        record["condition_errors"].append("extra_safety_embedding_dim_not_256")
                    if payload.get("normalized") is not True:
                        record["condition_errors"].append("extra_safety_normalized_not_true")
                    for field in ("model_version", "embedding_space_id", "preprocess_version"):
                        if not isinstance(payload.get(field), str) or not payload[field].strip():
                            record["condition_errors"].append(f"extra_safety_missing_{field}")
            if not record["schema_errors"]:
                record["outcome"] = "live_json_schema_valid"
            else:
                record["outcome"] = "live_json_schema_drift"
        else:
            record["outcome"] = "http_or_response_condition_failure"
    except TimeoutError as error:
        record["outcome"] = "network_timeout"
        record["exception"] = {"type": type(error).__name__, "message": str(error)}
        record["condition_errors"].append("timeout")
    except (OSError, http.client.HTTPException, ValueError, UnicodeError) as error:
        record["outcome"] = "network_or_payload_failure"
        record["exception"] = {"type": type(error).__name__, "message": str(error)}
        record["condition_errors"].append("network_or_payload_error")
    finally:
        connection.close()
        record["completed_at_utc"] = now()
        record["elapsed_seconds"] = round(time.monotonic() - started, 6)
        record["response_bytes"] = len(body)
        record["sha256"] = hashlib.sha256(body).hexdigest() if record["status"] is not None else None
        if record["status"] == 200 and record["body_complete"] and record["schema_validation_performed"]:
            # 仅保存完整 200 JSON（包括漂移）；失败的时间、条件和 hash 保留在报告。
            (DIRECTORY / filename).write_bytes(body)
            record["raw_payload_file"] = (DIRECTORY / filename).relative_to(ROOT).as_posix()
    record["passed"] = (
        record["status"] == 200
        and record["body_complete"]
        and record["schema_validation_performed"]
        and not record["schema_errors"]
        and not record["condition_errors"]
    )
    return record, payload


def main() -> None:
    document = json.loads(SOURCE.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    report = {
        "evidence_kind": "LIVE_HTTPS_GET_NONCLINICAL",
        "started_at_utc": now(),
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": source_hash,
        "expected_api_version": "0.8.0",
        "conditions": CONDITIONS,
        "model_performance_tested": False,
        "clinical_safety_verified": False,
        "requests": [],
    }
    payloads = []
    for path, name, filename in TARGETS:
        record, payload = capture(path, name, filename, document)
        report["requests"].append(record)
        payloads.append(payload)
        print(
            f"LIVE GET {path}: status={record['status']} content_type={record['content_type']!r} "
            f"bytes={record['response_bytes']} schema_errors={len(record['schema_errors'])} "
            f"passed={record['passed']} outcome={record['outcome']} elapsed={record['elapsed_seconds']}s"
        )
    health, model = payloads
    cross_errors = []
    if isinstance(health, dict) and isinstance(model, dict) and isinstance(health.get("model"), dict):
        for field, health_field in (("model_version", "version"), ("embedding_space_id", "embedding_space_id")):
            if health["model"].get(health_field) != model.get(field):
                cross_errors.append(f"health.model.{health_field} != model-info.{field}")
    report["cross_endpoint_errors"] = cross_errors
    report["passed"] = all(record["passed"] for record in report["requests"]) and not cross_errors
    report["completed_at_utc"] = now()
    report["blockers_for_main_agent"] = [
        {
            "endpoint": record["url"],
            "outcome": record["outcome"],
            "condition_errors": record["condition_errors"],
            "schema_errors": record["schema_errors"],
        }
        for record in report["requests"]
        if not record["passed"]
    ]
    if cross_errors:
        report["blockers_for_main_agent"].append({"cross_endpoint_errors": cross_errors})
    report["status_files_modified"] = False
    report["next_action"] = (
        "主代理更新 BLOCKERS，禁止将失败/漂移报告为成功"
        if not report["passed"]
        else ("GET 契约证据已捕获；所有图像 POST、模型性能与临床安全仍未验证")
    )
    manifest = {
        "provenance": "LIVE",
        "nonclinical": True,
        "synthetic_data": False,
        "patient_data": False,
        "clinical_safety_verified": False,
        "generated_at_utc": report["completed_at_utc"],
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "expected_api_version": "0.8.0",
        "source_sha256": source_hash,
        "requests": report["requests"],
        "conditions": CONDITIONS,
        "entries": {},
    }
    for record in report["requests"]:
        if record["raw_payload_file"]:
            manifest["entries"][Path(record["raw_payload_file"]).name] = {
                "provenance": "LIVE",
                "nonclinical": True,
                "synthetic_data": False,
                "url": record["url"],
                "started_at_utc": record["started_at_utc"],
                "completed_at_utc": record["completed_at_utc"],
                "status": record["status"],
                "content_type": record["content_type"],
                "sha256": record["sha256"],
                "response_bytes": record["response_bytes"],
                "schema_ref": record["schema_ref"],
                "schema_errors": record["schema_errors"],
                "condition_errors": record["condition_errors"],
                "passed": record["passed"],
            }
    write_json(DIRECTORY / "live_manifest.json", manifest)
    write_json(ROOT / "outputs/stage2_live_smoke.json", report)
    print(
        f"LIVE smoke passed={report['passed']}; blockers={len(report['blockers_for_main_agent'])}; "
        "POST/DELETE/uploads/redirects=0; report=outputs/stage2_live_smoke.json"
    )


if __name__ == "__main__":
    main()
