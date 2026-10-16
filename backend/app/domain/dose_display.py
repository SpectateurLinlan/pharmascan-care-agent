"""Conservative pure display arithmetic. Unknown evidence always abstains."""

import re
from decimal import Decimal

from ..contracts.dose_display import DoseDisplay, DoseDisplayInput


def dose_display(data: DoseDisplayInput) -> DoseDisplay:
    basis = data.basis

    def unknown(reason: str) -> DoseDisplay:
        return DoseDisplay(status="not_calculated", reason=reason)

    if not basis.patient_checked or not basis.instructions_text.strip():
        return unknown("Check the original dose instructions before showing a total.")
    if basis.form not in {"tablet", "capsule"} or basis.single_ingredient is not True or basis.formulation == "unknown":
        return unknown(
            "A simple single-ingredient solid product and formulation are needed; no liquid or combination conversion."
        )
    if data.dose_unit.strip().casefold() not in {basis.form, basis.form + "s"}:
        return DoseDisplay(status="conflict", reason="The dose unit and product form do not agree.")
    amount = Decimal(str(data.units_per_dose))
    if amount != amount.to_integral_value() and (
        amount != Decimal("0.5") or basis.form != "tablet" or basis.formulation != "standard"
    ):
        return unknown(
            "Do not infer splitting for capsules or modified-release/enteric products. Check with your pharmacist."
        )
    strength = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*mg\s*", basis.strength_text, re.I)
    if not strength or Decimal(strength[1]) <= 0:
        return unknown("Strength is incomplete or uses an unsupported concentration or unit.")
    text = basis.instructions_text.lower()
    conditional = r"\b(?:no|not|never|avoid|or|taper|if|unless|then|instead)\b|don['’]t|不|勿|禁止|避免|如果|若|然后"
    if re.search(conditional, text):
        return unknown("Conditional or negative instructions need pharmacist review; no total is inferred.")
    # Every count mention matters, including a later count without another 'take'
    # and bilingual duplicates. Do not silently select one instruction branch.
    counts = re.findall(r"(?:\d+(?:\.\d+)?|1/2|half|半)\s*(?:(?:tablets?|capsules?)\b|片|粒)", text)
    if not counts:
        return unknown("No explicit supported count instruction was found. Do not infer units from strength.")
    if len(counts) > 1 or len(re.findall(r"\b(?:take|use)\s+", text)) > 1:
        return unknown("Multiple dose instructions need review before showing a total.")
    if re.search(r"\b(?:mg|mcg|micrograms?|milligrams?|grams?)\b|\d\s*g\b|[µμ]g|毫克|微克|克", text):
        # A mass in the directions could describe strength or total dose. This
        # display-only parser does not have evidence to disambiguate the two.
        return unknown("Mass instructions need review against the product strength; no total is inferred.")
    stated = re.search(r"\b(?:take|use)\s+(\d+(?:\.\d+)?|half|1/2)\s+(tablet|capsule)s?\b", text)
    chinese_counts = re.findall(r"(?:每次|服用|服)\s*(\d+(?:\.\d+)?|半)\s*(片|粒)", text)
    if len(chinese_counts) > 1:
        return unknown("Multiple dose instructions need review before showing a total.")
    chinese = re.search(r"(?:每次|服用|服)\s*(\d+(?:\.\d+)?|半)\s*(片|粒)", text)
    if stated:
        count = Decimal("0.5") if stated[1] in {"half", "1/2"} else Decimal(stated[1])
        unit = stated[2]
    elif chinese:
        count = Decimal("0.5") if chinese[1] == "半" else Decimal(chinese[1])
        unit = "tablet" if chinese[2] == "片" else "capsule"
    else:
        return unknown("No explicit supported count instruction was found. Do not infer units from strength.")
    if count != amount or unit != basis.form:
        return DoseDisplay(
            status="conflict", reason="The entered count differs from the written instructions. Please review."
        )
    return DoseDisplay(
        status="calculated",
        total_amount=float(Decimal(strength[1]) * amount),
        total_unit="mg",
        reason="Arithmetic display from patient-checked source details; review the original instructions.",
    )
