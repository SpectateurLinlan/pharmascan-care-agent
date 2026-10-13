"""Frozen v0.8.0 OpenAPI validation at the anti-corruption boundary.

The specification is injected; runtime code does not fetch or silently replace it.
Additional fields follow OpenAPI additionalProperties, not app DTO constraints.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TypeAlias

from app.contracts.vision import VisionSchemaError
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]


class Stage2Contract:
    def __init__(self, openapi: dict) -> None:
        if openapi.get("info", {}).get("version") != "0.8.0":
            raise ValueError("Stage2 adapter requires the frozen candidate v0.8.0")
        self._spec = deepcopy(openapi)
        self._registry = Registry().with_resource(
            "urn:pharmascan:0.8.0", Resource.from_contents(self._spec, default_specification=DRAFT202012)
        )

    def validate(self, schema_name: str, payload: object) -> JSONObject:
        schema = {"$ref": f"urn:pharmascan:0.8.0#/components/schemas/{schema_name}"}
        errors = list(Draft202012Validator(schema, registry=self._registry).iter_errors(payload))
        if errors or not isinstance(payload, dict):
            locations = ["/".join(map(str, e.absolute_path)) or "$" for e in errors[:6]]
            raise VisionSchemaError(f"Stage2 {schema_name} schema mismatch at {locations}")
        return payload
