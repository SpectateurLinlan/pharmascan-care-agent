"""Shared text minimisation; untrusted text stays data, never authority."""

import re


def bounded_text(text: str, limit: int) -> str:
    text = re.sub(r"eyJ[\w-]+\.[\w-]+\.[\w-]+|sb_secret_[\w-]+|AKID[\w]+|AIza[\w-]+", "[redacted]", text)
    return text[:limit]
