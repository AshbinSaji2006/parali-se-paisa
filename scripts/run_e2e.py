"""Run Playwright with tracked local servers and deterministic Windows cleanup."""
from __future__ import annotations

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
DB = (ROOT / ".demo" / "block4-playwright.db").as_posix()


def wait_for(url: str, process: subprocess.Popen[bytes], name: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{name} exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    raise TimeoutError(f"{name} did not become ready at {url}")


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
        print("node is required for Playwright", file=sys.stderr)
        return 2
    for port in (8000, 5173):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                print(f"Port {port} is already in use; stop the existing service before E2E", file=sys.stderr)
                return 2
    env = os.environ.copy()
    env.update({
        "DEMO_MODE": "true",
        "DATABASE_URL": f"sqlite:///{DB}",
        "JWT_SECRET": "playwright-only-demo-secret-32-characters-long",
    })
    servers: list[subprocess.Popen[bytes]] = []
    result = 1
    try:
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.api.main:app",
                                "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT, env=env)
        servers.append(api)
        web = subprocess.Popen([node, "node_modules/vite/bin/vite.js", "--host", "127.0.0.1"],
                               cwd=FRONTEND, env=env)
        servers.append(web)
        wait_for("http://127.0.0.1:8000/api/v1/health", api, "API")
        wait_for("http://127.0.0.1:5173", web, "Vite")
        result = subprocess.run([node, "node_modules/@playwright/test/cli.js", "test"],
                                cwd=FRONTEND, env=env, check=False).returncode
    except (OSError, RuntimeError, TimeoutError) as exc:
        print(f"E2E startup failed: {exc}", file=sys.stderr)
        result = 1
    finally:
        for process in reversed(servers):
            stop_tree(process)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
