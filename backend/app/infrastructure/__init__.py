"""Infrastructure adapters. Every implementation here is a local, in-memory
or network adapter that satisfies a Port in backend/app/contracts/ports.py.

SIMULATED markers are mandatory: nothing in this package may be presented as
a live database, live Stage2 API or live LLM result.
"""
