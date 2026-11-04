"""Timing reports keep missing readiness and measurement conditions explicit."""

from scripts.qa.summarize_startup import StartupSample, summarize_startup


def sample(value, **changes):
    return StartupSample(cache="normal-cache", viewport="390x844", backend="running_memory_process",
                         shell_ms=value, essential_ms=value, **changes)


def test_p75_uses_nearest_rank_and_missing_ready_is_unknown():
    report = summarize_startup([sample(value) for value in (1, 2, 3, 4)] + [sample(None)])
    assert report.groups[0].shell.p75_ms == 3
    assert report.groups[0].essential.p75_ms == 3
    assert report.groups[0].essential.unknown == 1


def test_cache_viewport_and_backend_conditions_are_never_pooled():
    samples = [sample(1), StartupSample(cache="cold-browser", viewport="390x844",
              backend="running_memory_process", shell_ms=10, essential_ms=20),
              StartupSample(cache="normal-cache", viewport="1280x900", backend="running_memory_process",
                            shell_ms=3, essential_ms=4)]
    assert len(summarize_startup(samples).groups) == 3


def test_onboarding_blocked_sample_cannot_be_reported_as_ready_or_as_zero():
    report = summarize_startup([sample(10, onboarding_blocked=True)])
    assert report.groups[0].shell.p75_ms == 10
    assert report.groups[0].essential.p75_ms is None
    assert report.groups[0].essential.unknown == 1
