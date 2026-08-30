#!/usr/bin/env python3
"""Bounded access to the X1 head camera already served by cam host port 8080."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib import request


BASE_URL = os.environ.get("X1_CAMERA_BASE_URL", "http://100.94.194.108:8080").rstrip("/")
WORKSPACE = Path(
    os.environ.get("OPENCLAW_WORKSPACE_DIR", str(Path.home() / ".openclaw" / "workspace"))
).resolve()
EXPECTED_LABEL = "USB Camera #3"
EXPECTED_USB_ID = "vid_1bcf&pid_0b15"
MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024


def _json_get(path: str) -> dict[str, Any]:
    with request.urlopen(f"{BASE_URL}{path}", timeout=6) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("camera server returned invalid JSON")
    return value


def status() -> dict[str, Any]:
    health = _json_get("/health")
    cameras = _json_get("/cameras")
    active = next(
        (item for item in cameras.get("devices", []) if isinstance(item, dict) and item.get("active")),
        {},
    )
    label = str(health.get("camera_label", ""))
    unique_id = str(active.get("unique_id", "")).lower()
    is_head_camera = label == EXPECTED_LABEL and EXPECTED_USB_ID in unique_id
    live = bool(health.get("is_live") and health.get("has_frame"))
    return {
        "ok": is_head_camera and live,
        "camera": label,
        "is_head_camera": is_head_camera,
        "is_live": live,
        "view_mode": str(health.get("view_mode", "")),
        "width": int(health.get("mjpeg_width", health.get("actual_width", 0)) or 0),
        "height": int(health.get("mjpeg_height", health.get("actual_height", 0)) or 0),
        "source_width": int(health.get("actual_width", 0) or 0),
        "source_height": int(health.get("actual_height", 0) or 0),
        "fps": float(health.get("capture_fps", 0) or 0),
        "frame_age_ms": int(health.get("last_frame_age_ms", 0) or 0),
        "snapshot_api": f"{BASE_URL}/snapshot",
        "mjpeg_api": f"{BASE_URL}/stream",
        "hls_api": f"{BASE_URL}/hls/live.m3u8",
        "viewer": f"{BASE_URL}/h264",
    }


def snapshot() -> dict[str, Any]:
    current = status()
    if not current["is_head_camera"]:
        raise RuntimeError(f"active camera is not {EXPECTED_LABEL}")
    if not current["is_live"]:
        raise RuntimeError("head camera has no live frame")
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
    target = target_dir / f"x1-head-{stamp}.jpg"
    fd, temporary = tempfile.mkstemp(prefix="x1-head-", suffix=".jpg", dir=target_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {**current, "ok": True, "media": str(target), "bytes": len(raw)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "snapshot", "streams"))
    args = parser.parse_args()
    result = snapshot() if args.action == "snapshot" else status()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
