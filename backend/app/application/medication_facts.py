"""Conservative reconciliation of complete quotes within explicit source scopes."""

import re
from collections import defaultdict

from ..contracts.medication_facts import FactCoverage, UseFact, UseLabelEvidence


def extract_use_facts(label: UseLabelEvidence) -> tuple[UseFact, ...]:
    statements = []
    text = label.sections.get("indications_and_usage", "")
    names = "|".join(re.escape(name) for name in sorted(set(label.names), key=len, reverse=True))
    if names:
        subject = rf"\b(?:{names})(?: (?:extended[- ]release |delayed[- ]release )?"
        subject += r"(?:tablets?|capsules?|oral solution|oral suspension))?(?:,? USP)? (?:is|are) "
        for match in re.finditer(subject + r"(?:also )?(?:not )?indicated (?:for|as) [^.]+\.", text, re.I):
            # The entire bounded section is the quote. A period may be a decimal,
            # and a separate sentence may carry a restriction. Never guess that
            # a shorter sentence has the whole scope; long sections stay unparsed.
            if len(text) <= 600:
                statements.append(("indications_and_usage", text, match[0]))
    purpose = label.sections.get("purpose", "")
    # Purpose is a complete field, not an inferred or shortened indication.
    if 0 < len(purpose) <= 600 and not re.search(r"\b(?:not|except|unless)\b", purpose, re.I):
        statements.append(("purpose", purpose, purpose))
    result = []
    for field, quote, clause in dict.fromkeys(statements):
        population = re.search(
            r"\bin ((?:adults|children|patients|pediatric).*?)(?=,\s|;\s|\.(?:\s|$)|$)", quote, re.I,
        )
        claim = re.search(r"\bindicated for (?:the )?treatment of (.+?)(?: in (?:adults|children|patients)|\.$)",
                          clause, re.I)
        result.append(UseFact(
            source_id=label.source_id, ingredient_set=tuple(sorted(label.ingredient_set)),
            route_scope=label.route_scope, formulation_scope=label.formulation_scope,
            release_scope=label.release_scope, population_scope=population[1].casefold() if population else None,
            polarity="denied" if re.search(r"\bnot indicated\b", clause, re.I) else "affirmed",
            claim_key="treatment:" + " ".join(claim[1].casefold().split()) if claim else None,
            quote=quote, field=field,
        ))
    return tuple(result)


def reconcile_use_facts(facts: tuple[UseFact, ...]) -> FactCoverage:
    groups = defaultdict(list)
    for fact in facts:
        scope = (fact.ingredient_set, fact.route_scope, fact.formulation_scope,
                 fact.release_scope, fact.population_scope)
        # Missing evidence is not proof of an equivalent formulation/population.
        unknown = fact.source_id if any(part is None for part in scope) else None
        groups[(scope, unknown, fact.claim_key or (fact.source_id, fact.quote))].append(fact)
    supported, withheld = [], []
    conflict = False
    for rows in groups.values():
        opposed = {row.polarity for row in rows} == {"affirmed", "denied"}
        conflict |= opposed
        for row in rows:
            (withheld if opposed or row.polarity == "denied" else supported).append(row)
    return FactCoverage(
        groups=tuple(tuple(dict.fromkeys(row.source_id for row in rows)) for rows in groups.values()),
        supported=tuple(supported), withheld=tuple(withheld), reports_same_scope_conflict=conflict,
        reason=("true_scope_conflict" if conflict else
                "scoped_partial_evidence" if supported else "unsupported_use_scope"),
    )
