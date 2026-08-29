#!/usr/bin/env python3
"""Allow-listed, bounded Robot Voice Hub operations for the OpenClaw owner."""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request


BASE = os.environ.get("ROBOT_VOICE_HUB_URL", "http://100.94.194.108:8790").rstrip("/")


def call(path: str, method: str = "GET") -> dict:
    token = os.environ.get("NV_INFER_HUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Robot Hub token is unavailable")
    req = urllib.request.Request(
        BASE + path,
        data=b"{}" if method == "POST" else None,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        value = json.loads(response.read())
    return value if isinstance(value, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    restart = sub.add_parser("restart")
    restart.add_argument("robot_id")
    args = parser.parse_args()

    if args.action == "status":
        state = call("/api/admin/state")
        hub = state.get("hub") or {}
        robots = state.get("robots") or []
        result = {
            "hub_ready": bool(hub.get("ready")),
            "online_robots": int(hub.get("online_robots", 0)),
            "robots": [
                {
                    "id": str(item.get("robot_id") or item.get("id") or ""),
                    "online": bool(item.get("online")),
                    "active_model": str(item.get("active_model") or ""),
                }
                for item in robots[:20]
            ],
        }
    else:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", args.robot_id):
            raise ValueError("invalid robot id")
        result = call(f"/api/admin/robots/{args.robot_id}/restart", method="POST")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"Robot Hub HTTP {exc.code}: {body}") from exc
