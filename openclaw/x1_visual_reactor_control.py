#!/usr/bin/env python3
"""Bounded owner control for the persistent X1 visual event reactor."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any

from x1_gesture_control import SAFE_GESTURES
from x1_locate_control import _validate_query


STATE_DIR = Path(os.environ.get("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw")))
CONFIG_FILE = STATE_DIR / "visual-reactor.json"
RUNTIME_FILE = STATE_DIR / "visual-reactor-state.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(value: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="visual-reactor.", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, CONFIG_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def start(query: str, actions: list[str], view: str, confirm: float, repeat: float) -> dict[str, Any]:
    query = _validate_query(query)
    if not 1 <= len(actions) <= 5 or any(item not in SAFE_GESTURES for item in actions):
        raise ValueError("actions must contain 1-5 allow-listed gestures")
    if not 1.0 <= confirm <= 3.0:
        raise ValueError("confirm-seconds must be between 1 and 3")
    if not 5.0 <= repeat <= 3600:
        raise ValueError("repeat-seconds must be between 5 and 3600")
    value = {
        "enabled": True, "revision": time.time_ns(), "query": query,
        "actions": actions, "view": view, "confirmSeconds": confirm,
        "repeatSeconds": repeat, "clearSeconds": 1.0,
    }
    _write(value)
    return {"ok": True, "config": value}


def stop() -> dict[str, Any]:
    value = _read(CONFIG_FILE)
    value.update(enabled=False, revision=time.time_ns())
    _write(value)
    completed = subprocess.run(
        [str(STATE_DIR / "x1_gesture_control.py"), "stop"], check=False,
        capture_output=True, text=True, timeout=8,
    )
    return {"ok": True, "enabled": False, "motionStopped": completed.returncode == 0}


def status() -> dict[str, Any]:
    config, runtime = _read(CONFIG_FILE), _read(RUNTIME_FILE)
    return {"ok": True, "enabled": bool(config.get("enabled")), "config": config, "runtime": runtime}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    begin = sub.add_parser("start")
    begin.add_argument("--query", required=True)
    begin.add_argument("--actions", nargs="+", required=True, choices=sorted(SAFE_GESTURES))
    begin.add_argument("--view", choices=("head", "left-hand", "right-hand"), default="head")
    begin.add_argument("--confirm-seconds", type=float, default=1.5)
    begin.add_argument("--repeat-seconds", type=float, default=30.0)
    sub.add_parser("stop")
    sub.add_parser("status")
    args = parser.parse_args()
    if args.action == "start":
        result = start(args.query, args.actions, args.view, args.confirm_seconds, args.repeat_seconds)
    elif args.action == "stop":
        result = stop()
    else:
        result = status()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
