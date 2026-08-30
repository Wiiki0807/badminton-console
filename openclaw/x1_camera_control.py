#!/usr/bin/env python3
"""Bounded access to the allow-listed X1 cameras served by cam host port 8080."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any
from urllib import request


BASE_URL = os.environ.get("X1_CAMERA_BASE_URL", "http://100.94.194.108:8080").rstrip("/")
WORKSPACE = Path(
    os.environ.get("OPENCLAW_WORKSPACE_DIR", str(Path.home() / ".openclaw" / "workspace"))
).resolve()
MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024
SWITCH_TIMEOUT_SECONDS = 30

# DirectShow indexes change after USB reconnects. The instance fragments
# distinguish the otherwise identical left/right hand cameras.
CAMERA_PROFILES = {
    "head": {"label": "USB Camera #3", "usb_id": "vid_1bcf&pid_0b15", "instance": "7&1340e285&0&0000", "description": "X1 頭部視角"},
    "left-hand": {"label": "USB Camera #1", "usb_id": "vid_0bda&pid_5846", "instance": "8&7755205&0&0000", "description": "X1 左手視角"},
    "right-hand": {"label": "USB Camera #2", "usb_id": "vid_0bda&pid_5846", "instance": "8&195c6859&0&0000", "description": "X1 右手視角"},
}


def _json_request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 6) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{BASE_URL}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with request.urlopen(req, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("camera server returned invalid JSON")
    return value


def _json_get(path: str) -> dict[str, Any]:
    return _json_request(path)


def _profile_for_device(device: dict[str, Any]) -> str | None:
    unique_id = str(device.get("unique_id", "")).lower()
    label = str(device.get("display_name", ""))
    for view, profile in CAMERA_PROFILES.items():
        if label == profile["label"] and profile["usb_id"] in unique_id and profile["instance"] in unique_id:
            return view
    return None


def _devices() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cameras = _json_get("/cameras")
    devices = [item for item in cameras.get("devices", []) if isinstance(item, dict)]
    return cameras, devices


def status() -> dict[str, Any]:
    health = _json_get("/health")
    cameras, devices = _devices()
    active = next((item for item in devices if item.get("active")), {})
    active_view = _profile_for_device(active)
    live = bool(health.get("is_live") and health.get("has_frame"))
    available = {
        view: {"available": any(_profile_for_device(item) == view for item in devices), "camera": profile["label"], "description": profile["description"]}
        for view, profile in CAMERA_PROFILES.items()
    }
    return {
        "ok": active_view is not None and live,
        "camera": str(health.get("camera_label", "")),
        "active_view": active_view,
        "is_head_camera": active_view == "head",
        "is_live": live,
        "switch_pending": bool(health.get("camera_switch_pending")),
        "switchable": bool(cameras.get("switchable")),
        "available_views": available,
        "view_mode": str(health.get("view_mode", "")),
        "width": int(health.get("mjpeg_width", health.get("actual_width", 0)) or 0),
        "height": int(health.get("mjpeg_height", health.get("actual_height", 0)) or 0),
        "source_width": int(health.get("actual_width", 0) or 0),
        "source_height": int(health.get("actual_height", 0) or 0),
        "fps": float(health.get("capture_fps", 0) or 0),
        "frame_age_ms": int(health.get("last_frame_age_ms", 0) or 0),
        "last_error": health.get("last_error"),
        "snapshot_api": f"{BASE_URL}/snapshot",
        "mjpeg_api": f"{BASE_URL}/stream",
        "hls_api": f"{BASE_URL}/hls/live.m3u8",
        "viewer": f"{BASE_URL}/h264",
    }


def select(view: str, *, timeout: float = SWITCH_TIMEOUT_SECONDS) -> dict[str, Any]:
    if view not in CAMERA_PROFILES:
        raise RuntimeError("camera view is not allow-listed")
    _, devices = _devices()
    target = next((item for item in devices if _profile_for_device(item) == view), None)
    if target is None:
        raise RuntimeError(f"{view} camera is not available")
    if target.get("active"):
        current = status()
        if current["is_live"]:
            return current
    accepted = _json_request("/cameras/select", method="POST", payload={"unique_id": str(target.get("unique_id", ""))}, timeout=8)
    if not accepted.get("ok"):
        raise RuntimeError(str(accepted.get("error") or "camera switch was rejected"))
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        time.sleep(0.5)
        latest = status()
        if latest.get("active_view") == view and latest.get("is_live") and not latest.get("switch_pending"):
            return latest
        if latest.get("last_error") and not latest.get("switch_pending"):
            break
    detail = latest.get("last_error") or f"timed out after {timeout:g}s"
    raise RuntimeError(f"unable to switch to {view}: {detail}")


def snapshot(view: str = "head") -> dict[str, Any]:
    current = select(view)
    if current.get("active_view") != view or not current.get("is_live"):
        raise RuntimeError(f"{view} camera has no live frame")
    req = request.Request(f"{BASE_URL}/snapshot", headers={"Accept": "image/jpeg"})
    with request.urlopen(req, timeout=8) as response:
        declared = int(response.headers.get("Content-Length", "0") or 0)
        if declared > MAX_SNAPSHOT_BYTES:
            raise RuntimeError("snapshot is too large")
        raw = response.read(MAX_SNAPSHOT_BYTES + 1)
    if len(raw) > MAX_SNAPSHOT_BYTES or not raw.startswith(b"\xff\xd8") or not raw.endswith(b"\xff\xd9"):
        raise RuntimeError("camera server returned an invalid JPEG")
    target_dir = WORKSPACE / "camera"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"x1-{view}-{stamp}.jpg"
    fd, temporary = tempfile.mkstemp(prefix=f"x1-{view}-", suffix=".jpg", dir=target_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {**current, "ok": True, "requested_view": view, "description": CAMERA_PROFILES[view]["description"], "media": str(target), "bytes": len(raw)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "snapshot", "streams", "select"))
    parser.add_argument("--view", choices=tuple(CAMERA_PROFILES), default="head")
    args = parser.parse_args()
    if args.action == "snapshot":
        result = snapshot(args.view)
    elif args.action == "select":
        result = select(args.view)
    else:
        result = status()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
