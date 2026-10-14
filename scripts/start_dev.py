"""Run the existing FastAPI and Vite development servers in one terminal."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def port_number(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 1 and 65535.")
    return port


def check_port(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def backend_python(root: Path, requested: str | None) -> str | None:
    """Reuse an installed environment; never install or modify dependencies."""
    candidates = (
        [requested]
        if requested
        else [
            str(root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
            sys.executable,
            str(Path.home() / ".workbuddy-ai/binaries/python/envs/default/Scripts/python.exe"),
        ]
    )
    for candidate in candidates:
        if candidate is None or not Path(candidate).is_file():
            continue
        probe = subprocess.run(
            [candidate, "-c", "import uvicorn, fastapi, pydantic, httpx, PIL; from google import genai"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if probe.returncode == 0:
            return candidate
    return None


def stop_process(process: subprocess.Popen[bytes]) -> None:
    """Stop only the process tree created by this launcher."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-port", type=port_number, default=8001)
    parser.add_argument("--frontend-port", type=port_number, default=5173)
    parser.add_argument("--python", help="Backend Python executable (optional explicit environment).")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    python = backend_python(root, args.python)
    if python is None or npm is None:
        print("Install backend dependencies in your Python environment and Node.js/npm first.", file=sys.stderr)
        return 1
    if not (root / "frontend/node_modules/.bin/vite").exists():
        print("Install frontend dependencies first: cd frontend; npm ci", file=sys.stderr)
        return 1
    if args.backend_port == args.frontend_port:
        parser.error("Backend and frontend ports must be different.")
    for port in (args.backend_port, args.frontend_port):
        try:
            check_port(port)
        except OSError:
            print(f"Port {port} is unavailable. Stop its server or choose another port.", file=sys.stderr)
            return 1

    backend_command = [
        python,
        "-m",
        "uvicorn",
        "app.transport.app_factory:create_app",
        "--factory",
        "--app-dir",
        "backend",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.backend_port),
        "--no-access-log",
    ]
    frontend_command = [
        npm,
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.frontend_port),
        "--strictPort",
    ]
    frontend_env = os.environ.copy()
    frontend_env["VITE_API_TARGET"] = f"http://127.0.0.1:{args.backend_port}"
    processes: list[subprocess.Popen[bytes]] = []
    print(f"Starting app: http://localhost:{args.frontend_port}", flush=True)
    print(f"API docs: http://127.0.0.1:{args.backend_port}/docs", flush=True)
    print("Press Ctrl+C to stop both servers. Startup progress appears below.", flush=True)
    try:
        for command, cwd, env in (
            (backend_command, root, os.environ.copy()),
            (frontend_command, root / "frontend", frontend_env),
        ):
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
                    if os.name == "nt"
                    else 0,
                    start_new_session=os.name != "nt",
                )
            )
        while all(process.poll() is None for process in processes):
            time.sleep(0.2)
        print("A development server exited; stopping the other server.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopping development servers...", flush=True)
        return 0
    except OSError:
        print("Could not start a development server. Check installed dependencies.", file=sys.stderr)
        return 1
    finally:
        for process in reversed(processes):
            stop_process(process)


if __name__ == "__main__":
    raise SystemExit(main())
