"""Reset the isolated local demo database and run API plus Vite until Ctrl+C."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DB = ROOT / ".demo" / "block4-local.db"
URL = f"sqlite:///{DB.as_posix()}"


def wait_for(url: str, process: subprocess.Popen[bytes], name: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{name} exited with code {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    raise TimeoutError(f"{name} did not start at {url}")


def stop_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("Node.js is required", file=sys.stderr)
        return 2
    for port in (8000, 5173):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                print(f"Port {port} is already in use", file=sys.stderr)
                return 2
    os.environ.update({"DEMO_MODE": "true", "DATABASE_URL": URL})
    sys.path.insert(0, str(ROOT))
    from scripts.reset_demo import reset_demo
    from scripts.seed_accounts import write_credentials

    credentials = reset_demo(URL)
    write_credentials(credentials)
    env = os.environ.copy()
    processes: list[subprocess.Popen[bytes]] = []
    try:
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.api.main:app",
                                "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT, env=env)
        processes.append(api)
        web = subprocess.Popen([node, "node_modules/vite/bin/vite.js", "--host", "127.0.0.1"],
                               cwd=FRONTEND, env=env)
        processes.append(web)
        wait_for("http://127.0.0.1:8000/api/v1/health", api, "API")
        wait_for("http://127.0.0.1:5173", web, "Vite")
        print(f"\nDemo ready at http://127.0.0.1:5173\nCredentials: {ROOT / '.demo' / 'credentials.json'}\nPress Ctrl+C to stop both servers.", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
        return next((p.returncode or 1 for p in processes if p.poll() is not None), 1)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, TimeoutError) as exc:
        print(f"Demo startup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        for process in reversed(processes):
            stop_tree(process)


if __name__ == "__main__":
    raise SystemExit(main())
