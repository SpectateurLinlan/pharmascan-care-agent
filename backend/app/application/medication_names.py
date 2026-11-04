"""Bounded suggestions; approximate names never establish a drug identity."""

import json
import re
import unicodedata
from difflib import SequenceMatcher
from importlib.resources import files

from ..contracts.medication_names import NameCandidate, NameQuery, NameResolution


def normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class MedicationNameResolver:
    def __init__(self, entries: tuple[dict, ...] | None = None):
        if entries is None:
            resource = files("app.resources").joinpath("medication_aliases.v1.json")
            entries = tuple(json.loads(resource.read_text(encoding="utf-8"))["entries"])
        self._entries = tuple(
            row for row in entries
            if row.get("reviewed") is True and row.get("scope") == "ingredient"
            and str(row.get("source_url", "")).startswith("https://") and row.get("source_checked_at")
        )

    def resolve(self, query: NameQuery, owned: tuple[NameCandidate, ...]) -> NameResolution:
        needle = normalized_name(query.text)
        aliases = {normalized_name(row["canonical_name"]): row for row in self._entries}
        exact_aliases = [row for row in self._entries if normalized_name(row["alias"]) == needle]
        canonicals = {normalized_name(row["canonical_name"]) for row in exact_aliases} or {needle}
        if query.purpose == "patient_product":
            pool = tuple(row for row in owned if row.medication_id is not None)
            exact = tuple(row for row in pool if needle == normalized_name(row.display_name))
            exact = exact or tuple(row for row in pool if normalized_name(row.canonical_name) in canonicals)
        else:
            pool = tuple(NameCandidate(
                id="ingredient:" + key, canonical_name=row["canonical_name"], display_name=row["canonical_name"],
                source_refs=tuple(sorted({entry["source_url"] for entry in self._entries
                                          if normalized_name(entry["canonical_name"]) == key})),
            ) for key, row in aliases.items())
            exact = tuple(row for row in pool if normalized_name(row.canonical_name) in canonicals)
        if exact:
            return NameResolution(
                status="resolved" if len(exact) == 1 else "ambiguous", original=query.text,
                canonical_name=exact[0].canonical_name if len(exact) == 1 else None, candidates=exact[:5],
            )
        def similarity(row):
            names = [row.canonical_name, row.display_name]
            if query.purpose == "general_use":
                names += [entry["alias"] for entry in self._entries
                          if normalized_name(entry["canonical_name"]) == normalized_name(row.canonical_name)]
            return max(SequenceMatcher(None, needle, normalized_name(name)).ratio() for name in names)

        scored = sorted(
            ((similarity(row), row) for row in pool),
            key=lambda item: (-item[0], item[1].id),
        )
        threshold = 0.65 if re.search(r"[\u3400-\u9fff]", needle) else 0.72
        suggestions = tuple(row for score, row in scored if score >= threshold)[:5]
        return NameResolution(
            status="needs_confirmation" if suggestions else "not_found", original=query.text, candidates=suggestions,
        )
