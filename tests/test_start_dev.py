"""Local launcher isolation: reload is development-only and remains optional."""

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("extra,reload_enabled", [([], True), (["--no-reload"], False)])
def test_launcher_reload_scope_and_override(monkeypatch, extra, reload_enabled):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("start_dev_under_test", root / "scripts" / "start_dev.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setattr(sys, "argv", ["start_dev.py", *extra])
    monkeypatch.setattr(launcher, "backend_python", lambda root, requested: sys.executable)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "DEMO-npm")
    monkeypatch.setattr(launcher, "check_port", lambda port: None)
    watched = []

    def snapshot(directory):
        watched.append(directory)
        return {}

    monkeypatch.setattr(launcher, "python_snapshot", snapshot)
    launched = []
    stopped = []
    instances = []

    class FinishedServer:
        def __init__(self, command, **kwargs):
            self.command = command
            launched.append((command, kwargs))
            instances.append(self)

        def poll(self):
            return 0

    monkeypatch.setattr(launcher.subprocess, "Popen", FinishedServer)
    monkeypatch.setattr(launcher, "stop_process", stopped.append)
    assert launcher.main() == 1  # Exit of either server stops only launcher-owned children.
    assert len(launched) == len(stopped) == 2
    backend, frontend = launched[0][0], launched[1][0]
    assert watched == ([root / "backend" / "app"] if reload_enabled else [])
    assert "--reload" not in backend  # Launcher supervises restarts, including on Windows.
    assert "--reload" not in frontend
    assert launched[1][1]["env"]["VITE_API_TARGET"] == "http://127.0.0.1:8001"
    assert stopped == list(reversed(instances))


def test_reload_detects_python_add_edit_delete_but_ignores_other_files(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "start_dev_snapshot_test", Path(__file__).resolve().parents[1] / "scripts" / "start_dev.py"
    )
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    before = launcher.python_snapshot(tmp_path)
    (tmp_path / "notes.md").write_text("DEMO", encoding="utf-8")
    assert launcher.python_snapshot(tmp_path) == before
    source = tmp_path / "demo.py"
    source.write_text("VALUE=1", encoding="utf-8")
    added = launcher.python_snapshot(tmp_path)
    assert added != before
    source.write_text("VALUE=200", encoding="utf-8")
    assert launcher.python_snapshot(tmp_path) != added
    source.unlink()
    assert launcher.python_snapshot(tmp_path) == before


@pytest.mark.parametrize("backend_exited", [False, True])
def test_reload_replaces_backend_without_restarting_frontend(monkeypatch, backend_exited):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("start_dev_restart_test", root / "scripts" / "start_dev.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setattr(sys, "argv", ["start_dev.py"])
    monkeypatch.setattr(launcher, "backend_python", lambda root, requested: sys.executable)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "DEMO-npm")
    monkeypatch.setattr(launcher, "check_port", lambda port: None)
    versions = iter([{}, {root / "backend" / "app" / "demo.py": (2, 10)}])
    monkeypatch.setattr(launcher, "python_snapshot", lambda directory: next(versions))
    created = []
    stopped = []

    class RunningServer:
        def __init__(self, command, cwd, env):
            self.command = command
            created.append(self)

        def poll(self):
            return 1 if backend_exited and self is created[0] else None

    def interrupt(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(launcher, "start_process", RunningServer)
    monkeypatch.setattr(launcher, "stop_process", stopped.append)
    monkeypatch.setattr(launcher.time, "sleep", interrupt)
    assert launcher.main() == 0
    assert len(created) == 3
    assert created[0].command == created[2].command  # The third child replaces the API only.
    assert created[1].command[0] == "DEMO-npm"
    assert stopped == [created[0], created[1], created[2]]
