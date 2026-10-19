"""Bounded public SPL lookup; exact product-family evidence, never a prescription."""

import json
import re
from collections.abc import Callable
from datetime import datetime
from html import unescape
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..contracts.medication_knowledge import KnowledgeProduct, KnowledgeResult, LabelSection, LabelSource
from ..contracts.ports import Clock

LABEL_URL = "https://api.fda.gov/drug/label.json"
MAX_RESPONSE_BYTES = 3_000_000


class Harmonized(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    generic_name: list[str] = Field(default_factory=list)
    brand_name: list[str] = Field(default_factory=list)
    substance_name: list[str] = Field(default_factory=list)
    route: list[str] = Field(default_factory=list)
    product_type: list[str] = Field(default_factory=list)
    rxcui: list[str] = Field(default_factory=list)


class Label(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: str
    set_id: str
    version: str
    effective_time: str
    openfda: Harmonized
    dosage_forms_and_strengths: list[str] = Field(default_factory=list)
    indications_and_usage: list[str] = Field(default_factory=list)
    purpose: list[str] = Field(default_factory=list)
    dosage_and_administration: list[str] = Field(default_factory=list)
    information_for_patients: list[str] = Field(default_factory=list)
    warnings_and_cautions: list[str] = Field(default_factory=list)
    boxed_warning: list[str] = Field(default_factory=list)
    description: list[str] = Field(default_factory=list)
    spl_product_data_elements: list[str] = Field(default_factory=list)


def normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def plain(text: str) -> str:
    # Label contents remain untrusted, quoted evidence, never model instructions.
    if re.search(r"ignore.{0,30}(?:instruction|previous)|system prompt|<script|\[INST\]", text, re.I):
        raise ValueError("Untrusted instruction-like label content")
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", text)).split())


def matches(product: KnowledgeProduct, label: Label) -> bool:
    """Compare full ingredient sets, route, form, release and stated strength.

    No salt equivalence, combination splitting or dose/strength conversion is inferred.
    Missing form/route/release evidence deliberately prevents a reliable product match.
    """
    facts = label.openfda
    if product.scope == "ingredient":
        # A harmonized exact generic/ingredient name is evidence for an
        # ingredient-level excerpt, never for this patient's physical product.
        generic = {normalized(value) for value in facts.generic_name}
        actual = {normalized(value) for value in facts.substance_name}
        expected = {normalized(value) for value in product.ingredients}
        name = normalized(product.name)
        identity = bool(expected and expected == actual) or (name in generic and len(actual) == 1)
        return (
            identity
            and bool(facts.product_type)
            and set(facts.product_type) <= {"HUMAN PRESCRIPTION DRUG", "HUMAN OTC DRUG"}
        )
    if product.rxcui and product.rxcui not in facts.rxcui:
        return False
    if normalized(product.name) not in {normalized(value) for value in facts.generic_name + facts.brand_name}:
        return False
    expected = {normalized(value) for value in product.ingredients}
    actual = {normalized(value) for value in facts.substance_name}
    if not expected:
        names = {normalized(value) for value in facts.generic_name}
        if normalized(product.name) not in names or len(actual) != 1:
            return False
    elif expected != actual:
        return False
    if {normalized(value) for value in facts.route} != {normalized(product.route or "")}:
        return False
    if not set(facts.product_type) <= {"HUMAN PRESCRIPTION DRUG", "HUMAN OTC DRUG"} or not facts.product_type:
        return False
    text = plain(" ".join(label.dosage_forms_and_strengths)).lower()
    forms = {
        form
        for form, pattern in {
            "tablet": r"\btablets?\b",
            "capsule": r"\bcapsules\b|\bcapsule(?![- ]shaped)\b",
            "solution": r"\bsolution\b",
            "suspension": r"\bsuspension\b",
        }.items()
        if re.search(pattern, text)
    }
    if forms != {product.form}:
        return False
    identity = (
        plain(" ".join(facts.generic_name + facts.brand_name + label.description + label.spl_product_data_elements))
        + " "
        + text
    )
    extended = bool(re.search(r"extended[- ]release|modified[- ]release|sustained[- ]release", identity, re.I))
    delayed = bool(re.search(r"delayed[- ]release|enteric", identity, re.I))
    release = "modified_release" if extended else "enteric" if delayed else "standard"
    if product.release != release or (extended and delayed):
        return False
    if product.strength:
        strength = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(mg|mcg|g)\s*", product.strength, re.I)
        if not strength or not re.search(rf"(?<![\d.]){re.escape(strength[1])}\s*{strength[2]}\b", text, re.I):
            return False
    return True


def use_statements(label: Label) -> list[str]:
    """Recognize complete directly printed statements; never infer an indication."""
    text = plain(" ".join(label.indications_and_usage))
    statements = []
    names = label.openfda.generic_name + label.openfda.brand_name
    if len(label.openfda.substance_name) == 1:
        names += label.openfda.substance_name
    for name in sorted(set(names), key=len, reverse=True):
        subject = (
            rf"\b{re.escape(name)}(?: (?:extended[- ]release |delayed[- ]release )?"
            r"(?:tablets?|capsules?|oral solution|oral suspension))?(?:,? USP)? (?:is|are) "
        )
        if re.search(subject + r"not indicated", text, re.I):
            return []
        for match in re.finditer(subject + r"indicated (?:for|as) [^.]{3,600}\.", text, re.I):
            if not re.search(r"\bnot\b", match[0], re.I):
                statements.append(match[0])
    if statements:
        return list(dict.fromkeys(statements))
    if label.purpose:
        text = plain(" ".join(label.purpose))
        if 0 < len(text) <= 600:
            return [text]
    return []


def use_statement(label: Label) -> str | None:
    statements = use_statements(label)
    return statements[0] if statements else None


def statement_key(text: str, label: Label) -> str:
    value = normalized(text)
    for name in sorted(label.openfda.generic_name + label.openfda.brand_name, key=len, reverse=True):
        value = value.replace(normalized(name), "product")
    return re.sub(r"\b(is|are)\b", "is", value)


def ingredient_use_key(text: str, label: Label) -> str:
    """Compare only a directly stated indication, not population/form equivalence.

    Returned answers still quote the source's full qualifying sentence.
    """
    match = re.search(r"\bindicated for (?:the )?treatment of ([^.,;]+)", text, re.I)
    if match:
        target = re.split(
            r"\s+(?:in (?:adults|children|patients|pediatric)|alone|in combination)\b", match[1], flags=re.I
        )[0]
        return "treatment:" + normalized(target)
    if re.search(
        r"indicated as an adjunct to diet and exercise to improve glycemic control .+type 2 diabetes mellitus",
        text,
        re.I,
    ):
        return "adjunct glycemic control in type 2 diabetes mellitus"
    return statement_key(text, label)


def chinese_use(text: str) -> str | None:
    """Small controlled translation surface; unsupported sentences stay in English."""
    if re.fullmatch(
        r".+ (?:is|are) indicated for the treatment of hypertension, to lower blood pressure\.", text, re.I
    ):
        return "该美国标签列出的一个用途是治疗高血压、降低血压；这里只解释这一项用途，并非完整适应症清单。"
    if re.fullmatch(
        r".+ (?:is|are) indicated as an adjunct to diet and exercise to improve glycemic control "
        r"in adults with type 2 diabetes mellitus\.",
        text,
        re.I,
    ):
        return "该美国标签列出的用途是配合饮食和运动，帮助成人2型糖尿病患者控制血糖。"
    if re.search(
        r"indicated as an adjunct to diet and exercise to improve glycemic control .+type 2 diabetes mellitus",
        text,
        re.I,
    ) and not re.search(r"\bnot\b", text, re.I):
        return "所引美国标签列出的用途是配合饮食和运动，帮助2型糖尿病患者控制血糖；具体适用年龄请核对标签原文。"
    if re.search(r"\bindicated for the treatment of hypertension\b", text, re.I) and not re.search(
        r"\bnot\b", text, re.I
    ):
        return "所引美国标签列出的一个用途是治疗高血压、降低血压。这里摘录一项用途，具体适用人群请核对标签原文。"
    return None


class OpenFDAKnowledge:
    def __init__(self, client: httpx.Client, clock: Clock, *, monotonic: Callable[[], float]):
        self._client, self._clock, self._monotonic = client, clock, monotonic

    def lookup(self, product: KnowledgeProduct) -> KnowledgeResult:
        if product.scope == "product" and (not product.form or not product.route or product.release == "unknown"):
            return KnowledgeResult(status="no_reliable_match", reason="missing_form_route_or_release")
        name = product.ingredients[0] if product.ingredients else product.name
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ()/+\-]{0,159}", name):
            return KnowledgeResult(status="no_reliable_match", reason="unsupported_search_name")
        search = f'openfda.substance_name.exact:"{name.upper()}" OR openfda.generic_name.exact:"{name.upper()}"'
        deadline = self._monotonic() + 12
        try:
            with self._client.stream(
                "GET",
                LABEL_URL,
                params={"search": search, "limit": 8},
                timeout=httpx.Timeout(6.0),
                follow_redirects=False,
                headers={"Accept": "application/json"},
            ) as response:
                if self._monotonic() >= deadline:
                    return KnowledgeResult(status="unavailable", reason="request_budget_exceeded")
                if response.status_code == 404:
                    return KnowledgeResult(status="no_reliable_match", reason="not_found")
                if response.status_code != 200:
                    return KnowledgeResult(status="unavailable", reason=f"http_{response.status_code}")
                if "application/json" not in response.headers.get("content-type", ""):
                    return KnowledgeResult(status="unavailable", reason="non_json")
                body = bytearray()
                for part in response.iter_bytes():
                    if self._monotonic() >= deadline:
                        return KnowledgeResult(status="unavailable", reason="request_budget_exceeded")
                    body.extend(part)
                    if len(body) > MAX_RESPONSE_BYTES:
                        return KnowledgeResult(status="unavailable", reason="response_too_large")
            raw = json.loads(body)
            rows = raw.get("results") if isinstance(raw, dict) else None
            if not isinstance(rows, list) or len(rows) > 8:
                return KnowledgeResult(status="unavailable", reason="invalid_response")
            # A malformed candidate cannot silently disappear from conflict evaluation.
            labels = [Label.model_validate(row) for row in rows]
            selected = [row for row in labels if matches(product, row)]
            latest: dict[str, Label] = {}
            for row in selected:
                UUID(row.set_id)
                UUID(row.id)
                if datetime.strptime(row.effective_time, "%Y%m%d").date() > self._clock.now().date():
                    return KnowledgeResult(status="no_reliable_match", reason="future_label")
                version = int(row.version)
                if row.set_id in latest and version == int(latest[row.set_id].version) and row != latest[row.set_id]:
                    return KnowledgeResult(status="no_reliable_match", reason="duplicate_version_conflict")
                if row.set_id not in latest or version > int(latest[row.set_id].version):
                    latest[row.set_id] = row
            selected = list(latest.values())
            statements = [(row, use_statement(row)) for row in selected]
            if not statements or any(statement is None for _, statement in statements):
                return KnowledgeResult(
                    status="no_reliable_match", reason="identity_or_use_not_supported", candidate_count=len(rows)
                )
            keys = [
                {
                    ingredient_use_key(value, row) if product.scope == "ingredient" else statement_key(value, row)
                    for value in use_statements(row)
                }
                for row in selected
            ]
            common = set.intersection(*keys)
            if (product.scope == "ingredient" and not common) or (
                product.scope == "product" and len({frozenset(key) for key in keys}) != 1
            ):
                return KnowledgeResult(
                    status="no_reliable_match", reason="conflicting_label_uses", candidate_count=len(rows)
                )
            # Evaluate all bounded candidates before picking reproducible, recent citations.
            selected.sort(
                key=lambda row: (
                    matches(product.model_copy(update={"scope": "product"}), row)
                    if product.scope == "ingredient"
                    else True,
                    row.effective_time,
                    row.set_id,
                ),
                reverse=True,
            )
            sources = []
            for row in selected[:2]:
                sections = []
                for field in (
                    "indications_and_usage",
                    "purpose",
                    "information_for_patients",
                    "boxed_warning",
                    "warnings_and_cautions",
                ):
                    content = plain(" ".join(getattr(row, field)))
                    if content:
                        sections.append(LabelSection(field=field, text=content[:650], truncated=len(content) > 650))
                sources.append(
                    LabelSource(
                        label_name=" / ".join(dict.fromkeys(row.openfda.brand_name + row.openfda.generic_name))[:240]
                        or None,
                        set_id=UUID(row.set_id),
                        label_id=UUID(row.id),
                        version=row.version,
                        effective_time=row.effective_time,
                        retrieved_at=self._clock.now().isoformat(),
                        url=f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={row.set_id}",
                        api_url=f"https://api.fda.gov/drug/label.json?search=id:%22{row.id}%22",
                        sections=sections,
                    )
                )
            statement = next(
                value
                for value in use_statements(selected[0])
                if product.scope == "product" or ingredient_use_key(value, selected[0]) in common
            )
            translated = chinese_use(statement)
            return KnowledgeResult(
                status="matched",
                reason="exact_ingredient_and_consistent_label_use"
                if product.scope == "ingredient"
                else "exact_product_family_and_consistent_use",
                match_scope="US_label_ingredient" if product.scope == "ingredient" else "US_label_product_family",
                candidate_count=len(rows),
                sources=sources,
                use_statement=statement,
                use_statement_zh=translated,
                translation_status="controlled_translation" if translated else "original_english_only",
            )
        except httpx.TimeoutException:
            return KnowledgeResult(status="unavailable", reason="timeout")
        except httpx.RequestError:
            return KnowledgeResult(status="unavailable", reason="network_error")
        except (ValueError, TypeError, ValidationError):
            return KnowledgeResult(status="unavailable", reason="invalid_response")
