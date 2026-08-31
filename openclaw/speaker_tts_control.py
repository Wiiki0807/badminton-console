#!/usr/bin/env python3
"""Allow-listed TTS playback through one online Robot Voice Hub speaker."""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any
from urllib import error, parse, request


BASE_URL = os.environ.get(
    "ROBOT_VOICE_HUB_URL", "http://100.94.194.108:8790"
).rstrip("/")
DEFAULT_ROBOT = os.environ.get("TTS_SPEAKER_ROBOT_ID", "").strip()
ROBOT_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
MAX_TEXT_CHARS = 500


def _token() -> str:
    value = os.environ.get("NV_INFER_HUB_TOKEN", "").strip()
    if not value:
        raise RuntimeError("Robot Voice Hub token is unavailable")
    return value


def _call(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        BASE_URL + path,
        data=body,
        method="GET" if body is None else "POST",
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            value = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Robot Voice Hub HTTP {exc.code}: {detail}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Robot Voice Hub returned invalid JSON")
    return value


def _online_robots() -> list[str]:
    state = _call("/api/admin/state")
    return [
        str(item.get("robot_id") or item.get("id") or "")
        for item in state.get("robots", [])
        if isinstance(item, dict) and item.get("online")
    ]


def _resolve_robot(requested: str) -> str:
    robot_id = requested.strip() or DEFAULT_ROBOT
    if robot_id:
        if not ROBOT_ID_RE.fullmatch(robot_id):
            raise ValueError("invalid robot id")
        return robot_id
    online = _online_robots()
    if len(online) != 1:
        raise RuntimeError("specify --robot when zero or multiple speakers are online")
    return online[0]


def speak(text: str, robot: str = "") -> dict[str, Any]:
    normalized = " ".join(text.split())
    if not 1 <= len(normalized) <= MAX_TEXT_CHARS:
        raise ValueError("speech text must contain 1-500 characters")
    robot_id = _resolve_robot(robot)
    result = _call(
        f"/api/admin/robots/{parse.quote(robot_id, safe='')}/speak",
        {"text": normalized},
    )
    return {
        "ok": bool(result.get("success")),
        "accepted": bool(result.get("accepted")),
        "robot_id": robot_id,
        "characters": len(normalized),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    speak_parser = sub.add_parser("speak")
    speak_parser.add_argument("--text", required=True)
    speak_parser.add_argument("--robot", default="")
    args = parser.parse_args()
    if args.action == "status":
        result = {"ok": True, "online_speakers": _online_robots()}
    else:
        result = speak(args.text, args.robot)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
