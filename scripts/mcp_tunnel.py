#!/usr/bin/env python3
"""MCP tunnel manager — start/stop/check SSH tunnel to remote MCP servers.

Usage:
  python3 -m scripts.mcp_tunnel start    # Start SSH tunnel in background
  python3 -m scripts.mcp_tunnel stop     # Kill SSH tunnel
  python3 -m scripts.mcp_tunnel check    # Test MCP connectivity
  python3 -m scripts.mcp_tunnel status   # Show tunnel status
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


def _load_env() -> dict[str, str]:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    env: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def find_tunnel_pid() -> int | None:
    try:
        r = subprocess.run(
            ["pgrep", "-f", "ssh.*9001:127.0.0.1:9001"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip().split()[0])
    except Exception:
        pass
    return None


def start_tunnel() -> None:
    env = _load_env()
    key = env.get("SSH_KEY", os.path.expanduser("~/.ssh/id_rsa"))
    user = env.get("SSH_USER", "ubuntu")
    host = env.get("SSH_HOST", "152.69.201.170")

    pid = find_tunnel_pid()
    if pid:
        print(f"SSH tunnel already running (PID {pid})")
        return

    cmd = [
        "ssh", "-i", key, "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-N",
        "-L", "9001:127.0.0.1:9001",
        "-L", "9002:127.0.0.1:9002",
        "-L", "9003:127.0.0.1:9003",
        f"{user}@{host}",
    ]
    print(f"Starting SSH tunnel: {user}@{host} (ports 9001/9002/9003)...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import time
    time.sleep(2)

    if proc.poll() is None:
        print(f"SSH tunnel started (PID {proc.pid})")
    else:
        print(f"SSH tunnel failed to start (exit code {proc.returncode})")
        sys.exit(1)


def stop_tunnel() -> None:
    pid = find_tunnel_pid()
    if pid is None:
        print("No SSH tunnel running")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"SSH tunnel stopped (PID {pid})")
    except ProcessLookupError:
        print("SSH tunnel process not found")


def check_connectivity() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from mcp_client import get_mcp_client

    client = get_mcp_client()
    servers = [
        ("Intel (9001)", lambda: client.call("is_trading_day", port=9001)),
        ("Risk  (9002)", lambda: client.call("get_blacklist", port=9002)),
        ("Exec  (9003)", lambda: client.get_balance()),
    ]
    all_ok = True
    for name, fn in servers:
        try:
            result = fn()
            print(f"  {name}: OK")
        except Exception as e:
            print(f"  {name}: FAIL — {e}")
            all_ok = False

    if all_ok:
        print("All MCP servers reachable")
    else:
        print("Some MCP servers unreachable — is the SSH tunnel running?")


def status() -> None:
    pid = find_tunnel_pid()
    if pid:
        print(f"SSH tunnel: RUNNING (PID {pid})")
    else:
        print("SSH tunnel: STOPPED")

    # Check local port listeners
    for port in [9001, 9002, 9003]:
        r = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            capture_output=True, text=True, timeout=5,
        )
        listening = "LISTEN" in r.stdout
        print(f"  Port {port}: {'LISTENING' if listening else 'CLOSED'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "start":
        start_tunnel()
    elif command == "stop":
        stop_tunnel()
    elif command == "check":
        check_connectivity()
    elif command == "status":
        status()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
