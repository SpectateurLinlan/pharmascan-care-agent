"""Actual local API/application/Agent, synthetic patient and cached labels only."""

from .correctness02_support import build_harness

if __name__ == "__main__":
    import uvicorn

    harness = build_harness()

    @harness.app.middleware("http")
    async def advance_synthetic_request_clock(request, call_next):
        # Frozen fixtures still need distinct sequential turn timestamps, just
        # like Harness.ask. Otherwise ties make a restore's order artificial.
        harness.root.clock.advance(microseconds=1)
        return await call_next(request)

    uvicorn.run(harness.app, host="127.0.0.1", port=8769, log_level="warning")
