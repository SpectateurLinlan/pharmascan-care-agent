"""Request-owned subprocess: hard timeout kills the worker, never detaches it."""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from ..contracts.notifications import DispatchResult


class DispatchTimeout(Exception):
    pass


class DispatchUnavailable(Exception):
    pass


class ProcessDispatchRunner:
    def __init__(self, *, execute: Callable = subprocess.run, root: Path | None = None):
        self._execute = execute
        self._root = root

    def run(self) -> DispatchResult:
        # Vercel's Python build may vendor this package separately from the
        # project root. Its documented working directory is the project root;
        # callers can inject it explicitly when constructing the ASGI entry.
        root = self._root or Path(__file__).resolve().parents[3]
        try:
            result = self._execute(
                [sys.executable, str(root / "scripts/run_reminders.py"), "--json", "--limit", "5", "--budget", "20"],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=25,
                check=False,
            )
            if result.returncode:
                raise DispatchUnavailable
            return DispatchResult.model_validate_json(result.stdout.strip())
        except subprocess.TimeoutExpired:
            # subprocess.run kills and waits before raising. Previously claimed
            # sends remain 'sending', later recovered as uncertain, never replayed.
            raise DispatchTimeout from None
        except (OSError, ValueError):
            raise DispatchUnavailable from None
