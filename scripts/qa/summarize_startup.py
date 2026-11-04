"""Summarize content-free startup samples without pooling unlike conditions."""

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class StartupSample:
    cache: str
    viewport: str
    backend: str
    shell_ms: float | None
    essential_ms: float | None
    onboarding_blocked: bool = False
    cpu: str = "CDP_rate_1"

    def __post_init__(self):
        if self.cache not in {"normal-cache", "cold-browser", "cache-disabled"}:
            raise ValueError("Unknown cache condition")
        if self.viewport not in {"390x844", "1280x900"}:
            raise ValueError("Unsupported viewport condition")
        if self.backend != "running_memory_process" or self.cpu != "CDP_rate_1":
            raise ValueError("This report supports only the measured local runtime conditions")
        for value in (self.shell_ms, self.essential_ms):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("Timing must be finite, non-negative, or unknown")


@dataclass(frozen=True)
class TimingSummary:
    observed: int
    unknown: int
    p75_ms: float | None
    target_ms: int
    within_target: bool | None


@dataclass(frozen=True)
class StartupGroup:
    cache: str
    viewport: str
    backend: str
    cpu: str
    samples: int
    onboarding_blocked: int
    shell: TimingSummary
    essential: TimingSummary


@dataclass(frozen=True)
class StartupReport:
    groups: tuple[StartupGroup, ...]
    hosted_cold_start: str = "NOT_RUN"


def _timing(values: list[float | None], target: int) -> TimingSummary:
    observed = sorted(value for value in values if value is not None)
    unknown = len(values) - len(observed)
    p75 = observed[math.ceil(len(observed) * 0.75) - 1] if observed else None
    within_target = p75 <= target if p75 is not None and not unknown else None
    return TimingSummary(len(observed), unknown, p75, target, within_target)


def summarize_startup(samples: list[StartupSample]) -> StartupReport:
    conditions = sorted({(row.cache, row.viewport, row.backend, row.cpu) for row in samples})
    groups = []
    for cache, viewport, backend, cpu in conditions:
        rows = [row for row in samples if (row.cache, row.viewport, row.backend, row.cpu)
                == (cache, viewport, backend, cpu)]
        groups.append(StartupGroup(
            cache, viewport, backend, cpu, len(rows), sum(row.onboarding_blocked for row in rows),
            _timing([row.shell_ms for row in rows], 2000),
            _timing([None if row.onboarding_blocked else row.essential_ms for row in rows], 5000),
        ))
    return StartupReport(tuple(groups))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.samples.read_text(encoding="utf-8"))
    result = json.dumps(asdict(summarize_startup([StartupSample(**row) for row in raw])), indent=2) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
