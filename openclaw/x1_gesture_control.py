#!/usr/bin/env python3
"""Allow-listed X1 Laban controller shared by LINE and OpenClaw.

The caller supplies gesture stems, never paths or joint values.  All commands end
at the resident player's Unix socket so there is only one ROS2 trajectory owner.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import time
from typing import Any


ROOT = Path(os.environ.get("X1_ROOT", "/mnt/c/nvidia/besek_x1")).resolve()
LIBRARY = ROOT / "laban" / "gestures" / "library"
SOCKET = Path(os.environ.get("X1_LABAN_SOCKET", "/tmp/x1_laban_real.sock"))
CONTROL_STATE_DIR = Path(
    os.environ.get("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw"))
) / "state"
EPOCH_FILE = CONTROL_STATE_DIR / "x1_laban_control_epoch"
GESTURE_FILES = {
    "away": "away",
    "away2": "away2",
    "good": "good",
    "happy": "happy4",
    "hello": "hello",
    "come": "come",
    "bad": "bad",
    "thanks": "thanks",
    "goodbye": "goodbye",
    "nice": "nice",
    "surprised": "surprised",
    "wave-happily": "wave happily",
    "open-two-arms": "open two arms",
}
SAFE_GESTURES = frozenset(GESTURE_FILES)
MAX_SEQUENCE_STEPS = 5


def _request(payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(SOCKET))
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        raw = client.recv(65536)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("resident player returned an invalid response")
    return value


def _gesture_path(name: str) -> Path:
    if name not in SAFE_GESTURES:
        raise ValueError(f"gesture is not allow-listed: {name}")
    path = (LIBRARY / f"{GESTURE_FILES[name]}.json").resolve()
    if path.parent != LIBRARY or not path.is_file():
        raise ValueError(f"gesture is unavailable: {name}")
    return path


def _epoch() -> int:
    try:
        return int(EPOCH_FILE.read_text(encoding="ascii").strip())
    except (FileNotFoundError, OSError, ValueError):
        return 0


def _cancel_sequences() -> int:
    value = _epoch() + 1
    EPOCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    EPOCH_FILE.write_text(str(value), encoding="ascii")
    return value


def status() -> dict[str, Any]:
    result = _request({"cmd": "status"}, timeout=3.0)
    result["safe_gestures"] = sorted(SAFE_GESTURES)
    return result


def play(name: str, *, real: bool) -> dict[str, Any]:
    _cancel_sequences()
    return _play(name, real=real)


def _play(name: str, *, real: bool) -> dict[str, Any]:
    return _request({
        "cmd": "play",
        "gesture": str(_gesture_path(name)),
        "speed": 1.0,
        "approach": 2.0,
        "no_head": True,
        "return_ready": True,
        "isaac_only": not real,
    })


def stop() -> dict[str, Any]:
    _cancel_sequences()
    return _request({"cmd": "stop"}, timeout=3.0)


def sequence(names: list[str], *, real: bool, pause: float) -> dict[str, Any]:
    if not 1 <= len(names) <= MAX_SEQUENCE_STEPS:
        raise ValueError(f"sequence must contain 1 to {MAX_SEQUENCE_STEPS} steps")
    for name in names:
        _gesture_path(name)
    run_epoch = _cancel_sequences()
    completed: list[dict[str, Any]] = []
    for name in names:
        if _epoch() != run_epoch:
            return {"ok": False, "cancelled": True, "completed": completed}
        result = _play(name, real=real)
        completed.append({"gesture": name, "result": result})
        if not result.get("ok"):
            return {"ok": False, "completed": completed}
        deadline = time.monotonic() + float(result.get("duration_s", 0.0)) + pause
        while time.monotonic() < deadline:
            if _epoch() != run_epoch:
                _request({"cmd": "stop"}, timeout=3.0)
                return {"ok": False, "cancelled": True, "completed": completed}
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    return {"ok": True, "mode": "real" if real else "preview", "completed": completed}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    play_parser = sub.add_parser("play")
    play_parser.add_argument("gesture", choices=sorted(SAFE_GESTURES))
    play_parser.add_argument("--real", action="store_true")
    sub.add_parser("stop")
    sequence_parser = sub.add_parser("sequence")
    sequence_parser.add_argument("gestures", nargs="+", choices=sorted(SAFE_GESTURES))
    sequence_parser.add_argument("--real", action="store_true")
    sequence_parser.add_argument("--pause", type=float, default=0.5)
    args = parser.parse_args()

    if args.action == "status":
        result = status()
    elif args.action == "play":
        result = play(args.gesture, real=args.real)
    elif args.action == "stop":
        result = stop()
    else:
        if not 0 <= args.pause <= 3:
            raise ValueError("pause must be between 0 and 3 seconds")
        result = sequence(args.gestures, real=args.real, pause=args.pause)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
