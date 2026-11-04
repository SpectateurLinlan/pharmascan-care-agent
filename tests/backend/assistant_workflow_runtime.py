"""Opt-in loopback workflow acceptance over the existing frozen-knowledge runtime."""

from .assistant_knowledge_runtime import create_app as knowledge_app


def create_app():
    return knowledge_app(workflows_enabled=True)
