"""独立 OpenAPI 3.1 / Draft202012 契约测试；不导入 adapter、不访问网络。"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import runpy
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/external/pharmascan-api-openapi-0.8.0.json"
DIRECTORY = ROOT / "tests/fixtures/stage2/v0_8_0"
DOCUMENT = json.loads(SOURCE.read_text(encoding="utf-8"))
CASES = {
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
MODEL = "SCHEMA-model-v0.8.0"
SPACE = "SCHEMA-space-v0.8.0"
PREPROCESS = "SCHEMA-preprocess-v0.8.0"


def load(name: str) -> dict:
    return json.loads((DIRECTORY / f"{name}.json").read_text(encoding="utf-8"))


SCHEMA_URI = "urn:pharmascan:independent-test:0.8.0"
REGISTRY = Registry().with_resource(SCHEMA_URI, Resource.from_contents(DOCUMENT, default_specification=DRAFT202012))


def fragment_validator(fragment: dict) -> Draft202012Validator:
    return Draft202012Validator({**fragment, "components": DOCUMENT["components"]}, registry=REGISTRY)


def validator(name: str) -> Draft202012Validator:
    # 独立加载 snapshot，ref 仅由 referencing 解析，禁止网络检索或导入主 adapter。
    return fragment_validator({"$ref": f"{SCHEMA_URI}#/components/schemas/{name}"})


def resolve(schema: dict) -> dict:
    if "$ref" in schema:
        return DOCUMENT["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    return schema


def object_nodes(value, schema: dict, path: tuple = ()):
    schema = resolve(schema)
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            check = fragment_validator(branch)
            if check.is_valid(value):
                yield from object_nodes(value, branch, path)
                break
    elif isinstance(value, dict):
        yield path, value, schema
        for key, fragment in schema.get("properties", {}).items():
            if key in value:
                yield from object_nodes(value[key], fragment, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from object_nodes(item, schema.get("items", {}), (*path, index))


def error_tree(errors):
    for error in errors:
        yield error
        yield from error_tree(error.context)


def at_path(payload, path: tuple):
    for key in path:
        payload = payload[key]
    return payload


def enforce_embedding_safety(payload: dict, metadata: dict) -> None:
    """额外测试策略，非 OpenAPI minItems 或实际临床门限。"""
    if any(payload[key] != metadata[key] for key in ("model_version", "embedding_space_id", "preprocess_version")):
        raise ValueError("metadata mismatch")
    vector = payload["embedding"]
    if payload["dim"] != 256 or len(vector) != 256:
        raise ValueError("dimension mismatch")
    if not all(type(value) in (int, float) and math.isfinite(value) for value in vector):
        raise ValueError("non-finite vector")
    if payload["normalized"] is not True or not math.isclose(sum(value * value for value in vector), 1, abs_tol=1e-6):
        raise ValueError("normalization mismatch")


def enforce_request_space(payload: dict) -> None:
    if not payload.get("model_version") and not payload.get("embedding_space_id"):
        raise ValueError("missing model/space")
    if payload.get("model_version", MODEL) != MODEL or payload.get("embedding_space_id", SPACE) != SPACE:
        raise ValueError("mismatched model/space")
    vectors = payload["queries"] + [vector for med in payload["gallery"] for vector in med["embeddings"]]
    if any(len(vector) != 256 or not all(math.isfinite(v) for v in vector) for vector in vectors):
        raise ValueError("invalid request vectors")


@pytest.mark.parametrize("name,schema_name", CASES.items())
def test_all_fixtures_validate_via_draft202012_refs(name: str, schema_name: str) -> None:
    check = validator(schema_name)
    check.check_schema(check.schema)
    errors = list(check.iter_errors(load(name)))
    assert not errors, [(list(error.absolute_path), error.message) for error in errors]


@pytest.mark.parametrize("name,schema_name", CASES.items())
def test_every_present_nested_required_field_is_enforced(name: str, schema_name: str) -> None:
    payload = load(name)
    check = validator(schema_name)
    tested = 0
    for path, value, schema in object_nodes(payload, {"$ref": f"#/components/schemas/{schema_name}"}):
        for field in schema.get("required", []):
            assert field in value
            mutated = copy.deepcopy(payload)
            del at_path(mutated, path)[field]
            assert any(
                error.validator == "required" and tuple(error.absolute_path) == path
                for error in error_tree(check.iter_errors(mutated))
            ), (name, path, field)
            tested += 1
    assert tested > 0


@pytest.mark.parametrize("name,schema_name", CASES.items())
def test_nullable_and_nonnullable_fields_follow_schema(name: str, schema_name: str) -> None:
    payload = load(name)
    for path, _value, schema in object_nodes(payload, {"$ref": f"#/components/schemas/{schema_name}"}):
        for field, fragment in schema.get("properties", {}).items():
            mutated = copy.deepcopy(payload)
            at_path(mutated, path)[field] = None
            expected = fragment_validator(fragment).is_valid(None)
            assert validator(schema_name).is_valid(mutated) is expected, (name, path, field)


@pytest.mark.parametrize("name,schema_name", CASES.items())
def test_declared_additional_fields_are_allowed(name: str, schema_name: str) -> None:
    payload = load(name)
    for path, _value, schema in object_nodes(payload, {"$ref": f"#/components/schemas/{schema_name}"}):
        if schema.get("additionalProperties", True) is True:
            mutated = copy.deepcopy(payload)
            at_path(mutated, path)["schema_future_field"] = {"synthetic": True}
            validator(schema_name).validate(mutated)


def test_versions_provenance_hashes_and_payload_boundaries() -> None:
    assert DOCUMENT["openapi"] == "3.1.0"
    assert DOCUMENT["info"]["version"] == "0.8.0"
    old = ROOT / "docs/external/pharmascan-api-openapi-0.4.0.json"
    assert json.loads(old.read_text(encoding="utf-8"))["info"]["version"] == "0.4.0"
    manifest = load("manifest")
    assert set(manifest["entries"]) == {f"{name}.json" for name in CASES}
    assert manifest["source_sha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert manifest["provenance"] == "SCHEMA_FIXTURE" and manifest["demo_only"] is True
    for filename, entry in manifest["entries"].items():
        assert entry["provenance"] == "SCHEMA_FIXTURE"
        assert entry["demo_only"] is True and entry["nonclinical"] is True
        assert entry["synthetic_data"] is True and entry["live_request_performed"] is False
        assert entry["sha256"] == hashlib.sha256((DIRECTORY / filename).read_bytes()).hexdigest()
        assert entry["schema_ref"] == f"#/components/schemas/{CASES[filename.removesuffix('.json')]}"
        assert entry["schema_errors"] == []
        assert "provenance" not in load(filename.removesuffix(".json"))
    report = json.loads((ROOT / "outputs/stage2_contract_audit.json").read_text(encoding="utf-8"))
    assert report["historical_snapshot"]["sha256"] == hashlib.sha256(old.read_bytes()).hexdigest()
    assert report["source"]["sha256"] == manifest["source_sha256"]


@pytest.mark.parametrize("name,schema_name", CASES.items())
def test_invalid_required_field_types_are_rejected(name: str, schema_name: str) -> None:
    payload = load(name)
    schema = DOCUMENT["components"]["schemas"][schema_name]
    for field in schema["required"]:
        for invalid in ([], {}, "wrong", 42, True):
            if not fragment_validator(schema["properties"][field]).is_valid(invalid):
                assert not validator(schema_name).is_valid({**payload, field: invalid}), (name, field, invalid)
                break
        else:
            pytest.fail(f"未找到 required 字段非法类型：{name}.{field}")


def test_all_components_are_valid_draft202012_schemas() -> None:
    for schema in DOCUMENT["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)


def test_user_endpoint_audit_is_complete_and_records_all_errors() -> None:
    report = json.loads((ROOT / "outputs/stage2_contract_audit.json").read_text(encoding="utf-8"))
    expected = {
        ("GET", "/health"),
        ("GET", "/v1/model-info"),
        ("GET", "/v1/tools"),
        ("POST", "/v1/detect"),
        ("POST", "/v1/embed"),
        ("POST", "/v1/match"),
        ("POST", "/v1/identify"),
        ("POST", "/v1/scan"),
        ("POST", "/v1/read-label"),
        ("GET", "/v1/pills/search"),
        ("GET", "/v1/pills/{pill_id}"),
        ("POST", "/v1/safety/medications"),
        ("POST", "/v1/safety/dose"),
        ("GET", "/v1/safety/label"),
        ("POST", "/v1/feedback"),
        ("DELETE", "/v1/feedback/{consent_id}"),
    }
    operations = {(item["method"], item["path"]): item for item in report["operations"]}
    expected.add(("GET", "/v1/pills/{pill_id}/image/{n}"))
    assert expected == operations.keys()
    assert set(operations) == {
        (method.upper(), path) for path, methods in DOCUMENT["paths"].items() for method in methods
    }
    for (method, path), recorded in operations.items():
        actual = DOCUMENT["paths"][path][method.lower()]
        assert recorded["request"]["body_required"] == actual.get("requestBody", {}).get("required", False)
        assert set(recorded["error_responses"]) == set(actual["responses"]) - {"200"}
        for error in recorded["error_responses"].values():
            assert error["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Error"}
        for field, facts in recorded["response_200"]["content"]["application/json"]["fields"].items():
            assert facts["required"] == (field in recorded["response_200"]["content"]["application/json"]["required"])
    assert operations[("GET", "/v1/tools")]["response_200"]["content"]["application/json"]["unconstrained"] is True
    assert report["nonclinical"] is True and report["not_model_performance_evidence"] is True


def test_field_omission_differs_from_explicit_null() -> None:
    assert "message" not in load("detect_success")
    assert load("detect_unreliable_count")["message"] is None
    required_nullable = load("match_unknown")["results"][0]
    assert required_nullable["medication_id"] is None and required_nullable["name"] is None
    assert required_nullable["runner_up"] is not None
    missing = copy.deepcopy(required_nullable)
    del missing["medication_id"]
    assert not validator("MatchResult").is_valid(missing)
    explicit_null = {**required_nullable, "runner_up": None}
    validator("MatchResult").validate(explicit_null)


def test_embedding_metadata_dimension_and_normalization_are_extra_safety_policy() -> None:
    embedding = load("embed_success")
    model = load("model_info_success")
    assert embedding["embedding"] == [1.0] + [0.0] * 255
    assert model["embedding_dim"] == embedding["dim"] == 256
    assert model["normalized"] is True
    enforce_embedding_safety(embedding, model)
    for name in CASES:
        payload = load(name)
        for field, expected in {
            "model_version": MODEL,
            "embedding_space_id": SPACE,
            "preprocess_version": PREPROCESS,
        }.items():
            if field in payload:
                assert payload[field] == expected
    schema = DOCUMENT["components"]["schemas"]["Embedding"]
    assert "minItems" not in schema["properties"]["embedding"]
    assert "maxItems" not in schema["properties"]["embedding"]
    assert "const" not in schema["properties"]["dim"]
    truncated = {**embedding, "embedding": [1.0], "dim": 1}
    validator("Embedding").validate(truncated)
    with pytest.raises(ValueError, match="dimension"):
        enforce_embedding_safety(truncated, model)


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("model_version", "other-model"),
        ("embedding_space_id", "other-space"),
        ("preprocess_version", "other-preprocess"),
        ("dim", 255),
        ("normalized", False),
        ("embedding", [0.0] * 256),
        ("embedding", [float("nan")] + [0.0] * 255),
        ("embedding", [float("inf")] + [0.0] * 255),
    ],
)
def test_embedding_extra_safety_rejects_bad_metadata_and_vectors(field: str, bad_value) -> None:
    with pytest.raises(ValueError):
        enforce_embedding_safety({**load("embed_success"), field: bad_value}, load("model_info_success"))


def test_match_request_description_is_not_a_schema_version_or_vector_constraint() -> None:
    vector = load("embed_success")["embedding"]
    request = {"queries": [vector], "gallery": [{"medication_id": "SCHEMA-a", "embeddings": [vector]}]}
    validator("MatchRequest").validate(request)
    with pytest.raises(ValueError, match="missing model/space"):
        enforce_request_space(request)
    request["model_version"] = MODEL
    request["embedding_space_id"] = SPACE
    enforce_request_space(request)
    for field, bad in (("model_version", "other"), ("embedding_space_id", "other"), ("queries", [[1.0]])):
        mutated = {**request, field: bad}
        validator("MatchRequest").validate(mutated)
        with pytest.raises(ValueError):
            enforce_request_space(mutated)
    for field in ("queries", "gallery"):
        assert not validator("MatchRequest").is_valid({**request, field: []})
    assert not validator("GalleryMedication").is_valid({"medication_id": "SCHEMA-a", "embeddings": []})


@pytest.mark.parametrize(
    "name,decision",
    [
        ("match_success", "match"),
        ("match_unknown", "unknown"),
        ("match_ambiguous", "ambiguous"),
    ],
)
def test_match_fixture_decisions_refs_and_synthetic_rule(name: str, decision: str) -> None:
    payload = load(name)
    result = payload["results"][0]
    assert result["decision"] == decision
    for field in ("closest", "runner_up"):
        validator("Ref").validate(result[field])
        assert result[field]["medication_id"] and result[field]["name"]
    assert result["similarity"] == result["closest"]["similarity"]
    if decision == "match":
        assert result["similarity"] == 0.99 and result["medication_id"] == result["closest"]["medication_id"]
        assert result["medication_id"] == "med-1" and result["name"] == "Demo medicine"
        assert result["similarity"] >= payload["threshold"]
        assert result["similarity"] - result["runner_up"]["similarity"] >= payload["margin"]
    else:
        assert result["medication_id"] is None and result["name"] is None
        if decision == "unknown":
            assert result["similarity"] < payload["threshold"]
        else:
            assert result["similarity"] >= payload["threshold"]
            assert result["similarity"] - result["runner_up"]["similarity"] < payload["margin"]
    assert not validator("MatchResult").is_valid({**result, "decision": "confirmed_identity"})


def test_detection_and_scan_use_pixel_xyxy_and_expose_unreliable_overlap() -> None:
    scan = load("scan_success")
    detection = load("detect_success")
    validator("Detection").validate(scan["detection"])
    validator("MatchResult").validate(scan["pills"][0])
    for payload in (detection, load("detect_unreliable_count"), scan["detection"]):
        assert payload["pill_count"] == len(payload["boxes"]) == len(payload["box_flags"])
        for box in payload["boxes"]:
            assert isinstance(box, list) and len(box) == 4
            assert all(math.isfinite(value) for value in box)
            assert 0 <= box[0] < box[2] and 0 <= box[1] < box[3]
    assert scan["pills"][0]["box"] == scan["detection"]["boxes"][0] == [10, 20, 50, 60]
    bad = load("detect_unreliable_count")
    assert bad["count_reliable"] is False and bad["flags"] == ["count_uncertain"]
    first, second = bad["boxes"]
    assert max(first[0], second[0]) < min(first[2], second[2])
    assert max(first[1], second[1]) < min(first[3], second[3])
    assert all("merged" in flags for flags in bad["box_flags"])
    assert DOCUMENT["components"]["schemas"]["ScanPill"]["required"] == ["box"]
    untyped = {**scan["pills"][0], "decision": {"unexpected": True}, "candidates": "not-an-array"}
    validator("ScanPill").validate(untyped)
    assert not validator("MatchResult").is_valid(untyped)
    validator("ScanPill").validate({"box": [1]})  # 四元素需求属于额外安全策略。
    assert scan["dose"]["deprecated"] is True
    assert scan["dose"]["alerts"][0]["notify_caregiver"] is False


def test_labels_have_complete_candidates_printed_evidence_and_no_inferred_directions() -> None:
    success = load("read_label_success")
    missing = load("read_label_missing_directions")
    for payload in (success, missing):
        assert payload["source"] == "photo" and payload["ocr_model"] == MODEL
        assert payload["candidates"]
        for candidate in payload["candidates"]:
            assert set(DOCUMENT["components"]["schemas"]["LabelCandidate"]["required"]) <= candidate.keys()
            assert candidate["ingredients"] and candidate["found_in"]
            validator("LabelCandidate").validate(candidate)
            for field in ("quantity", "dose_form", "date", "expiry_date"):
                printed = candidate["fields"][field]
                validator("Printed").validate(printed)
                assert printed["value"] and printed["line"]
    assert success["candidates"][0]["fields"]["directions"] == {
        "value": "Take 1 tablet at 08:00",
        "line": "Take 1 tablet at 08:00",
    }
    assert missing["candidates"][0]["fields"]["directions"] is None
    fields = success["candidates"][0]["fields"]
    assert fields["quantity"] == {"value": "30", "line": "30"}
    assert fields["date"] == {"value": "2026-10-13", "line": "2026-10-13"}
    assert success["candidates"][0]["name"] == "Demo medicine"
    for candidate in success["candidates"]:
        for field in ("brand", "strength", "rxcui", "rxnorm_name"):
            assert candidate[field]
    assert "directions" not in DOCUMENT["components"]["schemas"]["DocumentFields"].get("required", [])


def test_identify_required_nested_candidate_and_visual_only_evidence() -> None:
    payload = load("identify_success")
    assert payload["candidates"] and payload["notes"]
    candidate = payload["candidates"][0]
    validator("Candidate").validate(candidate)
    assert candidate["ingredients"] and candidate["images"]
    assert candidate["similarity"] == 0.99 and payload["confidence"] is None
    assert payload["verdict"] == "uncertain"
    for name in ("model_info_success", "embed_success", "match_success", "identify_success", "scan_success"):
        assert load(name)["evidence"] == "visual"


def test_generator_reproduces_payloads_without_network() -> None:
    generator = runpy.run_path(str(ROOT / "tests/fixtures/stage2/generate_v0_8_0.py"))
    assert generator["make_fixtures"](DOCUMENT) == {name: load(name) for name in CASES}


def fake_live_capture(monkeypatch, body: bytes, status: int = 200, content_type: str = "application/json"):
    module = runpy.run_path(str(ROOT / "tests/fixtures/stage2/capture_live_get.py"))
    writes = {}
    requests = []

    class Socket:
        def settimeout(self, seconds):
            assert 0 < seconds <= 20

    class Response:
        def __init__(self):
            self.status = status
            self.offset = 0
            self.length = len(body)

        def getheader(self, key):
            return {"Content-Type": content_type, "Content-Length": str(len(body))}.get(key)

        def read1(self, size):
            chunk = body[self.offset : self.offset + size]
            self.offset += len(chunk)
            self.length -= len(chunk)
            return chunk

        def isclosed(self):
            return self.length == 0

    class Connection:
        def __init__(self, host, timeout, context):
            assert host == "davidpansx-pharmascan-api.hf.space"
            assert timeout <= 20 and context.check_hostname is True
            self.sock = Socket()

        def connect(self):
            return None

        def request(self, method, path, headers):
            assert method == "GET" and path == "/health"
            assert set(headers) == {"Accept", "Accept-Encoding", "User-Agent"}
            requests.append((method, path))

        def getresponse(self):
            return Response()

        def close(self):
            return None

    monkeypatch.setattr(module["http"].client, "HTTPSConnection", Connection)
    monkeypatch.setattr(Path, "write_bytes", lambda path, raw: writes.setdefault(path.name, bytes(raw)))
    result = module["capture"]("/health", "Health", "health_live.json", DOCUMENT)
    assert requests == [("GET", "/health")]
    return result, writes


@pytest.mark.parametrize(
    "body,status,content_type,expected_outcome",
    [
        (b"<html>sleeping</html>", 200, "text/html", "http_or_response_condition_failure"),
        (b"<html>redirect</html>", 302, "text/html", "http_or_response_condition_failure"),
        (b'{"code":"error","detail":"upstream failed"}', 500, "application/json", "http_or_response_condition_failure"),
        (b"not-json", 200, "application/json", "network_or_payload_failure"),
        (b"{}", 200, "application/json", "live_json_schema_drift"),
    ],
)
def test_live_capture_keeps_failed_raw_bytes_without_fake_success(
    monkeypatch, body, status, content_type, expected_outcome
) -> None:
    (record, _payload), writes = fake_live_capture(monkeypatch, body, status, content_type)
    assert record["passed"] is False
    assert record["status"] == status and record["content_type"] == content_type
    assert record["outcome"] == expected_outcome
    if record["schema_validation_performed"] and status == 200:
        assert writes["health_live.json"] == body
    else:
        assert writes == {} and record["raw_payload_file"] is None
    assert record["sha256"] == hashlib.sha256(body).hexdigest()
    if status == 500:
        assert record["schema_validation_performed"] is False and record["schema_errors"] == []
    if status == 302:
        assert "redirect_response_not_followed" in record["condition_errors"]


def test_live_capture_does_not_read_declared_oversized_body(monkeypatch) -> None:
    (record, _payload), writes = fake_live_capture(monkeypatch, b"x" * (1024 * 1024 + 1))
    assert record["passed"] is False and record["body_complete"] is False
    assert record["response_bytes"] == 0
    assert "response_content_length_exceeds_1MiB" in record["condition_errors"]
    assert writes == {} and record["raw_payload_file"] is None


def test_live_capture_rejects_other_targets_and_expired_deadline() -> None:
    module = runpy.run_path(str(ROOT / "tests/fixtures/stage2/capture_live_get.py"))
    with pytest.raises(ValueError, match="TARGETS"):
        module["capture"]("/v1/tools", "Health", "health_live.json", DOCUMENT)
    with pytest.raises(TimeoutError):
        module["remaining"](time.monotonic() - 1)


def test_saved_live_evidence_is_truthful_and_separate_from_schema_fixtures() -> None:
    report = json.loads((ROOT / "outputs/stage2_live_smoke.json").read_bytes())
    manifest = load("live_manifest")
    assert report["source_sha256"] == manifest["source_sha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert manifest["provenance"] == "LIVE" and manifest["synthetic_data"] is False
    assert len(report["requests"]) == 2
    for record in report["requests"]:
        if record["raw_payload_file"]:
            entry = manifest["entries"][Path(record["raw_payload_file"]).name]
            assert entry["sha256"] == record["sha256"] and entry["status"] == record["status"]
    assert {record["url"].split(".space", 1)[1] for record in report["requests"]} == {"/health", "/v1/model-info"}
    for record in report["requests"]:
        conditions = record["conditions"]
        assert conditions["method"] == "GET" and conditions["https_only"] is True
        assert conditions["timeout_seconds"] == 20 and conditions["max_response_bytes"] == 1024 * 1024
        for key in (
            "follow_redirects",
            "token_used",
            "authentication_used",
            "body_sent",
            "images_uploaded",
            "post_performed",
            "delete_performed",
            "proxy_environment_used",
        ):
            assert conditions[key] is False
        assert record["elapsed_seconds"] >= 0
        if record["raw_payload_file"]:
            raw = (ROOT / record["raw_payload_file"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == record["sha256"]
            assert len(raw) == record["response_bytes"] <= 1024 * 1024
            entry = manifest["entries"][Path(record["raw_payload_file"]).name]
            assert entry["sha256"] == record["sha256"] and entry["status"] == record["status"]
            if record["schema_validation_performed"]:
                errors = list(validator(record["schema_ref"].rsplit("/", 1)[1]).iter_errors(json.loads(raw)))
                assert [(list(error.absolute_path), error.message) for error in errors] == [
                    (error["instance_path"], error["message"]) for error in record["schema_errors"]
                ]
        expected_passed = (
            record["status"] == 200
            and record["body_complete"]
            and record["schema_validation_performed"]
            and not record["schema_errors"]
            and not record["condition_errors"]
        )
        assert record["passed"] is bool(expected_passed)
    assert report["passed"] is (
        all(record["passed"] for record in report["requests"]) and not report["cross_endpoint_errors"]
    )


def test_saved_live_evidence_matches_raw_bytes_and_actual_schema() -> None:
    report = json.loads((ROOT / "outputs/stage2_live_smoke.json").read_text(encoding="utf-8"))
    manifest = load("live_manifest")
    assert manifest["provenance"] == "LIVE" and manifest["synthetic_data"] is False
    assert manifest["nonclinical"] is True and manifest["clinical_safety_verified"] is False
    assert report["source_sha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert len(report["requests"]) == 2
    assert [item["url"] for item in report["requests"]] == [
        "https://davidpansx-pharmascan-api.hf.space/health",
        "https://davidpansx-pharmascan-api.hf.space/v1/model-info",
    ]
    for item in report["requests"]:
        conditions = item["conditions"]
        assert item["method"] == "GET" and conditions["timeout_seconds"] == 20
        assert conditions["max_response_bytes"] == 1024 * 1024
        for field in (
            "follow_redirects",
            "token_used",
            "authentication_used",
            "body_sent",
            "images_uploaded",
            "post_performed",
            "delete_performed",
        ):
            assert conditions[field] is False
        if item["raw_payload_file"]:
            path = ROOT / item["raw_payload_file"]
            raw = path.read_bytes()
            assert len(raw) == item["response_bytes"] <= 1024 * 1024
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            assert manifest["entries"][path.name]["sha256"] == item["sha256"]
            schema_name = item["schema_ref"].rsplit("/", 1)[1]
            errors = list(validator(schema_name).iter_errors(json.loads(raw)))
            assert len(errors) == len(item["schema_errors"])
        assert item["passed"] is (
            item["status"] == 200
            and item["body_complete"]
            and item["schema_validation_performed"]
            and not item["schema_errors"]
            and not item["condition_errors"]
        )
    assert report["passed"] is (
        all(item["passed"] for item in report["requests"]) and not report["cross_endpoint_errors"]
    )


@pytest.mark.parametrize(
    "status,mime,body,declared,expected",
    [
        (302, "text/html", b"redirect", "8", "redirect_response_not_followed"),
        (200, "text/html", b"sleeping", "8", "content_type_not_application_json"),
        (200, "application/json", b"{}", str(1024 * 1024 + 1), "response_content_length_exceeds_1MiB"),
        (200, "application/json", b"not-json", "8", "network_or_payload_error"),
        (200, "application/json", b"{}", "2", "api_version_drift"),
    ],
)
def test_live_get_failures_are_recorded_without_network_or_fake_success(
    monkeypatch,
    status: int,
    mime: str,
    body: bytes,
    declared: str,
    expected: str,
) -> None:
    module = runpy.run_path(str(ROOT / "tests/fixtures/stage2/capture_live_get.py"))
    calls = []
    writes = []

    class FakeResponse:
        fp = None

        def __init__(self):
            self.status = status
            self.length = len(body)
            self.buffer = body

        def getheader(self, name):
            return {"Content-Type": mime, "Content-Length": declared}.get(name)

        def read1(self, size):
            chunk, self.buffer = self.buffer[:size], self.buffer[size:]
            self.length -= len(chunk)
            return chunk

        def isclosed(self):
            return not self.buffer

    class FakeConnection:
        def __init__(self, host, timeout, context):
            assert host == "davidpansx-pharmascan-api.hf.space"
            assert 0 < timeout <= 20 and context.verify_mode != 0
            self.sock = self

        def connect(self):
            calls.append("connect")

        def settimeout(self, seconds):
            assert 0 < seconds <= 20

        def request(self, method, path, headers):
            assert method == "GET" and path == "/health"
            assert "Authorization" not in headers and "Cookie" not in headers
            calls.append((method, path))

        def getresponse(self):
            return FakeResponse()

        def close(self):
            calls.append("close")

    monkeypatch.setattr(module["http"].client, "HTTPSConnection", FakeConnection)
    monkeypatch.setattr(Path, "write_bytes", lambda path, raw: writes.append((path, raw)) or len(raw))
    record, _payload = module["capture"]("/health", "Health", "health_live.json", DOCUMENT)
    assert record["passed"] is False and expected in record["condition_errors"]
    assert calls == ["connect", ("GET", "/health"), "close"]
    if expected == "api_version_drift":
        assert record["schema_errors"] and record["outcome"] == "live_json_schema_drift"
    if record["schema_validation_performed"] and status == 200:
        assert len(writes) == 1 and bytes(writes[0][1]) == body
    else:
        assert writes == []


def test_live_get_deadline_rejects_expired_budget() -> None:
    module = runpy.run_path(str(ROOT / "tests/fixtures/stage2/capture_live_get.py"))
    with pytest.raises(TimeoutError, match="deadline"):
        module["remaining"](time.monotonic() - 1)


def test_live_evidence_revalidates_raw_bytes_without_assuming_service_success() -> None:
    report = json.loads((ROOT / "outputs/stage2_live_smoke.json").read_text(encoding="utf-8"))
    manifest = load("live_manifest")
    assert manifest["provenance"] == "LIVE" and manifest["synthetic_data"] is False
    assert manifest["nonclinical"] is True and report["clinical_safety_verified"] is False
    assert manifest["source_sha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert [item["url"] for item in report["requests"]] == [
        "https://davidpansx-pharmascan-api.hf.space/health",
        "https://davidpansx-pharmascan-api.hf.space/v1/model-info",
    ]
    for item in report["requests"]:
        assert item["method"] == "GET" and item["conditions"]["max_attempts_per_endpoint"] == 1
        assert item["conditions"]["timeout_seconds"] == 20
        assert item["conditions"]["max_response_bytes"] == 1024 * 1024
        for forbidden in (
            "follow_redirects",
            "token_used",
            "authentication_used",
            "body_sent",
            "images_uploaded",
            "post_performed",
            "delete_performed",
        ):
            assert item["conditions"][forbidden] is False
        assert item["response_bytes"] <= 1024 * 1024
        if item["raw_payload_file"]:
            raw = (ROOT / item["raw_payload_file"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            assert len(raw) == item["response_bytes"]
            errors = list(validator(item["schema_ref"].rsplit("/", 1)[1]).iter_errors(json.loads(raw)))
            assert len(errors) == len(item["schema_errors"])
            entry = manifest["entries"][Path(item["raw_payload_file"]).name]
            assert entry["provenance"] == "LIVE" and entry["synthetic_data"] is False
            assert entry["sha256"] == item["sha256"]
        if item["passed"]:
            assert item["status"] == 200 and item["body_complete"] is True
            assert item["schema_validation_performed"] is True
            assert item["schema_errors"] == item["condition_errors"] == []
    assert report["passed"] == (
        all(item["passed"] for item in report["requests"]) and not report["cross_endpoint_errors"]
    )


@pytest.mark.parametrize(
    "status,content_type,body,declared,failure,outcome",
    [
        (302, "text/html", b"redirect", None, None, "http_or_response_condition_failure"),
        (
            503,
            "application/json",
            b'{"code":"not_ready","detail":"test"}',
            None,
            None,
            "http_or_response_condition_failure",
        ),
        (200, "text/html", b"sleeping", None, None, "http_or_response_condition_failure"),
        (200, "application/json", b"{}", str(1024 * 1024 + 1), None, "http_or_response_condition_failure"),
        (200, "application/json", b"x" * (1024 * 1024 + 1), None, None, "http_or_response_condition_failure"),
        (200, "application/json", b"not JSON", None, None, "network_or_payload_failure"),
        (200, "application/json", b"{}", None, None, "live_json_schema_drift"),
        (None, None, b"", None, TimeoutError("synthetic timeout"), "network_timeout"),
        (None, None, b"", None, OSError("synthetic failure"), "network_or_payload_failure"),
    ],
    ids=[
        "redirect",
        "unavailable",
        "html",
        "declared_oversize",
        "stream_oversize",
        "invalid_json",
        "schema_drift",
        "timeout",
        "network_error",
    ],
)
def test_capture_failures_are_honest_bounded_get_only_with_memory_output(
    status,
    content_type,
    body,
    declared,
    failure,
    outcome,
    monkeypatch,
) -> None:
    module = runpy.run_path(str(ROOT / "tests/fixtures/stage2/capture_live_get.py"))
    namespace = module["capture"].__globals__
    calls = []
    writes = []

    class MemoryFile:
        def __truediv__(self, name):
            return self

        def write_bytes(self, value):
            writes.append(bytes(value))

        def relative_to(self, root):
            return Path("tests/fixtures/stage2/v0_8_0/SIMULATED-memory-only.json")

    class Socket:
        def settimeout(self, seconds):
            assert 0 < seconds <= 20

    class Response:
        length = None

        def __init__(self):
            self.status = status
            self.offset = 0
            self.fp = None

        def getheader(self, name):
            return {"Content-Type": content_type, "Content-Length": declared}.get(name)

        def read1(self, limit):
            assert 0 < limit <= 65536
            chunk = body[self.offset : self.offset + limit]
            self.offset += len(chunk)
            return chunk

        def isclosed(self):
            return self.offset >= len(body)

    class Connection:
        sock = Socket()

        def __init__(self, host, timeout, context):
            assert host == "davidpansx-pharmascan-api.hf.space" and 0 < timeout <= 20
            calls.append("constructed")

        def connect(self):
            if failure:
                raise failure

        def request(self, method, path, headers):
            calls.append((method, path))
            assert method == "GET" and path == "/health"
            assert "Authorization" not in headers and "Cookie" not in headers

        def getresponse(self):
            return Response()

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(namespace["http"].client, "HTTPSConnection", Connection)
    monkeypatch.setitem(namespace, "DIRECTORY", MemoryFile())
    record, _payload = module["capture"]("/health", "Health", "health_live.json", DOCUMENT)
    assert record["passed"] is False and record["outcome"] == outcome
    assert record["response_bytes"] <= 1024 * 1024
    assert calls.count(("GET", "/health")) <= 1 and calls[-1] == "closed"
    if status == 302:
        assert "redirect_response_not_followed" in record["condition_errors"]
    if declared:
        assert record["response_bytes"] == 0 and writes == []
    if outcome == "live_json_schema_drift":
        assert record["schema_errors"] and writes == [body]
    if failure:
        assert record["schema_validation_performed"] is False and writes == []
    with pytest.raises(TimeoutError):
        module["remaining"](time.monotonic() - 1)
