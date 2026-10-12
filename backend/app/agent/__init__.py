"""Agent layer: bounded orchestrator, typed tool registry and the
deterministic degraded-mode intent router.

Hard boundary (AGENTS.md rules 5, 21): the orchestrator NEVER touches SQL,
ORM entities or repository implementations. It may only invoke registered
typed tools, which in turn call application services.
"""
