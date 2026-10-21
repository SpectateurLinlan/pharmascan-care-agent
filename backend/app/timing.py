"""Request-local aggregate timings; never retain URLs, identities or payloads."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class RequestTiming:
    milliseconds: dict[str, float] = field(default_factory=dict)
    data_requests: int = 0
    storage_requests: int = 0
    data_operations: dict[str, dict[str, float]] = field(default_factory=dict)

    def header(self) -> str:
        stages = [f"{name};dur={duration:.2f}" for name, duration in self.milliseconds.items()]
        stages.append(f'data_calls;desc="{self.data_requests}"')
        if self.storage_requests:
            stages.append(f'storage_calls;desc="{self.storage_requests}"')
        # Closed operation labels only. Bound header size even on large reads.
        for name, values in sorted(self.data_operations.items(), key=lambda item: -item[1]["ms"])[:12]:
            stages.append(
                f'{name};dur={values["ms"]:.2f};desc="calls={int(values["calls"])};'
                f'max_ms={values["max_ms"]:.2f};bytes={int(values["bytes"])}"'
            )
        return ", ".join(stages)


current_timing: ContextVar[RequestTiming | None] = ContextVar("request_timing", default=None)


@contextmanager
def timed_data_operation(path: str, method: str, params):
    # Never derive labels from identifiers, query values, or provider text.
    tables = {
        "patient_profiles", "patient_medications", "regimen_versions", "source_documents", "source_fields",
        "dose_rules", "dose_occurrences", "dose_events", "effective_dose_events", "dose_report_entries",
        "medication_evidence_tasks", "medication_source_links", "medication_images", "image_embeddings",
        "inventory_transactions", "medication_care_tasks", "health_observations", "dose_reminders",
        "adherence_barriers",
    }
    table = path.removeprefix("/rest/v1/")
    table = table if table in tables else "other"
    verb = "read" if method == "GET" else "write"
    filters = params or {}
    shape = "batch" if any(str(value).startswith("in.(") for value in filters.values()) else (
        "one" if any(key in filters for key in ("id", "occurrence_id", "generation_key")) else "list"
    )
    if shape == "list":
        if "regimen_id" in filters:
            shape = "regimen"
        elif "medication_id" in filters or "patient_medication_id" in filters:
            shape = "medication"
        elif "source_id" in filters:
            shape = "source"
        elif "and" in filters or "and_" in filters:
            shape = "window"
    name = f"db_{table}_{verb}_{shape}"
    timing = current_timing.get()
    stats = None
    if timing is not None:
        stats = timing.data_operations.setdefault(name, {"calls": 0, "ms": 0, "max_ms": 0, "bytes": 0})
        stats["calls"] += 1
    started = perf_counter()
    response_size = [0]
    try:
        yield response_size
    finally:
        if stats is not None:
            elapsed = (perf_counter() - started) * 1000
            stats["ms"] += elapsed
            stats["max_ms"] = max(stats["max_ms"], elapsed)
            stats["bytes"] += response_size[0]


@contextmanager
def timed_stage(name: str):
    timing = current_timing.get()
    if timing is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        timing.milliseconds[name] = timing.milliseconds.get(name, 0) + (perf_counter() - started) * 1000
