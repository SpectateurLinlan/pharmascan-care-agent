"""Application services: use-cases, transactions, versioning, authorisation.

Services receive repositories, clock and id generator via constructor
injection; they never access HTTP/LLM/SQL directly (AGENTS.md rules 2/5)."""
