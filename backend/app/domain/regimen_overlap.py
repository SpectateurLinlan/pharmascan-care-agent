"""Pure, conservative identity and inclusive course-window comparisons."""

from datetime import date
from uuid import UUID


def same_recorded_medicine(
    first_name: str, second_name: str, first_product_id: UUID | None, second_product_id: UUID | None
) -> bool:
    """Equal known product IDs or normalized names flag duplicates, never merge them.

    Dose amount and PRN/scheduled frequency do not establish different product
    identities. Unknown brand/ingredient aliases are not guessed.
    """
    return bool(first_product_id and first_product_id == second_product_id) or (
        " ".join(first_name.lower().split()) == " ".join(second_name.lower().split())
    )


def courses_overlap(*, first_start: date, first_end: date | None, second_start: date, second_end: date | None) -> bool:
    """An unspecified end is open; the printed last day is inclusive."""
    return first_start <= (second_end or date.max) and second_start <= (first_end or date.max)
