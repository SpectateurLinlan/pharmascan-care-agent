"""Conservative read-only comparison of trusted, otherwise equivalent products."""

import re
from decimal import Decimal

from ..contracts.medication_dialogue import MedicationOption


def comparative_option(text: str, candidates: list[MedicationOption], rows: list[dict]) -> list[MedicationOption]:
    higher = bool(re.search(r"\b(?:stronger|higher strength)\b|较高规格|更高规格|高规格", text, re.I))
    lower = bool(re.search(r"\b(?:weaker|lower strength)\b|较低规格|更低规格|低规格", text, re.I))
    if higher == lower or len(candidates) < 2:
        return candidates
    by_id = {str(row["medication_id"]): row for row in rows}
    products, strengths = [], []
    for candidate in candidates:
        row = by_id[str(candidate.medication_id)]
        basis = row.get("comparison_basis")
        ingredients = tuple(sorted(name.casefold() for name in candidate.ingredient_names))
        if not basis or len(ingredients) != 1:
            return candidates
        # Require equivalent product family, brand, form, route and known release.
        # Do not convert concentrations, combination products or different units.
        if (
            not basis.get("form")
            or not basis.get("route")
            or basis.get("release") not in {"standard", "modified_release", "enteric"}
        ):
            return candidates
        strength = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(mg|mcg|g)\s*", row.get("strength_text") or "", re.I)
        if not strength or Decimal(strength[1]) <= 0:
            return candidates
        products.append(
            (
                ingredients,
                tuple(
                    str(basis.get(key) or "").casefold()
                    for key in ("product_name", "brand", "form", "route", "release")
                ),
                strength[2].casefold(),
            )
        )
        strengths.append(Decimal(strength[1]))
    if len(set(products)) != 1:
        return candidates
    target = max(strengths) if higher else min(strengths)
    matches = [candidate for candidate, strength in zip(candidates, strengths, strict=True) if strength == target]
    return matches if len(matches) == 1 else candidates
