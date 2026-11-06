"""Offline SQL artifact scope checks; actual trigger execution is verified separately."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "supabase/review/assistant_workflows"
FUNCTION = re.compile(
    r"CREATE OR REPLACE FUNCTION public\.assistant_enrollment_review_guard\(\) RETURNS trigger\s+"
    r"LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS \$\$.*?\$\$;",
    re.DOTALL,
)


def test_forward_repair_contains_only_existing_guard_replacement_in_bounded_transaction():
    candidate = (ROOT / "medication.up.sql").read_text(encoding="utf-8")
    repair = (ROOT / "enrollment-review-guard-repair.up.sql").read_text(encoding="utf-8")
    candidate_function = FUNCTION.search(candidate)
    repair_function = FUNCTION.search(repair)
    assert candidate_function is not None and repair_function is not None
    assert repair_function.group() == candidate_function.group()
    # The reviewed repair may replace this function only: no grants, policies,
    # role changes, clinical writes or unrelated function replacements.
    surrounding = repair[: repair_function.start()] + repair[repair_function.end() :]
    surrounding = re.sub(r"--[^\n]*", "", surrounding)
    assert surrounding.split() == [
        "BEGIN;",
        "SET",
        "LOCAL",
        "lock_timeout='5s';",
        "SET",
        "LOCAL",
        "statement_timeout='30s';",
        "COMMIT;",
    ]
