#!/usr/bin/env python3
"""Safe OpenClaw wrapper for X1 LocateAnything detection on the active camera."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any
from urllib import parse, request


# This wrapper runs beside LocateAnything in the same WSL instance. Avoid a
# Tailscale hairpin back to the host; it is not reliably routable from WSL.
BASE_URL = os.environ.get("X1_LOCATE_BASE_URL", "http://127.0.0.1:8090").rstrip("/")
STATE_DIR = Path(os.environ.get("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw")))
WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE_DIR", str(STATE_DIR / "workspace"))).resolve()
CAMERA_CONTROL = STATE_DIR / "x1_camera_control.py"
MAX_JPEG_BYTES = 5 * 1024 * 1024
QUERY_RE = re.compile(r"[\w\s,，\-\u3400-\u9fff]+", re.UNICODE)


def _json_get(path: str, params: dict[str, str] | None = None, timeout: float = 8) -> dict[str, Any]:
    suffix = f"?{parse.urlencode(params)}" if params else ""
    with request.urlopen(f"{BASE_URL}{path}{suffix}", timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("LocateAnything returned invalid JSON")
    return value


def _validate_query(query: str) -> str:
    value = query.strip().replace("，", ",")
    categories = [item.strip() for item in value.split(",") if item.strip()]
    if not value or len(value) > 120 or len(categories) > 8 or not QUERY_RE.fullmatch(value):
        raise RuntimeError("query must contain 1-8 short object names")
    return ",".join(categories)


def _select_camera(view: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["/usr/bin/python3", str(CAMERA_CONTROL), "select", "--view", view],
        check=False, capture_output=True, text=True, timeout=40, env=os.environ.copy(),
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("camera controller returned invalid JSON") from exc
    if completed.returncode or not isinstance(value, dict) or not value.get("ok"):
        raise RuntimeError(str(value.get("error") if isinstance(value, dict) else "camera switch failed"))
    return value


def _fresh_detection(query: str, timeout: float = 45) -> dict[str, Any]:
    before = _json_get("/json")
    before_age = float(before.get("boxes_age", 0) or 0)
    same_query = before.get("task") == "detect" and str(before.get("query", "")) == query
    accepted = _json_get("/set", {"task": "detect", "q": query, "grid": "1", "coords": "1"})
    if not accepted.get("ok"):
        raise RuntimeError("LocateAnything rejected the query")
    started = time.monotonic()
    latest: dict[str, Any] = {}
    while time.monotonic() - started < timeout:
        time.sleep(0.5)
        latest = _json_get("/json")
        elapsed = time.monotonic() - started
        age = float(latest.get("boxes_age", 0) or 0)
        result_matches = latest.get("task") == "detect" and str(latest.get("query", "")) == query
        refreshed = same_query or (elapsed >= 0.7 and age + 0.25 < before_age + elapsed)
        if result_matches and refreshed and age <= 2.0 and not latest.get("error"):
            return latest
    raise RuntimeError(str(latest.get("error") or "LocateAnything detection timed out"))


def _overlay_snapshot() -> Path:
    req = request.Request(f"{BASE_URL}/stream", headers={"Accept": "multipart/x-mixed-replace"})
    data = bytearray()
    with request.urlopen(req, timeout=12) as response:
        while len(data) <= MAX_JPEG_BYTES:
            chunk = response.read(65536)
            if not chunk:
                break
            data.extend(chunk)
            start = data.find(b"\xff\xd8")
            end = data.find(b"\xff\xd9", max(0, start + 2)) if start >= 0 else -1
            if start >= 0 and end >= 0:
                raw = bytes(data[start:end + 2])
                break
        else:
            raw = b""
    if "raw" not in locals() or not raw or len(raw) > MAX_JPEG_BYTES:
        raise RuntimeError("LocateAnything overlay image is unavailable")
    target_dir = WORKSPACE / "camera"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"x1-locate-{stamp}.jpg"
    fd, temporary = tempfile.mkstemp(prefix="x1-locate-", suffix=".jpg", dir=target_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def detect(query: str, view: str = "head", include_image: bool = True) -> dict[str, Any]:
    query = _validate_query(query)
    camera = _select_camera(view)
    result = _fresh_detection(query)
    width, height = int(camera.get("width", 0)), int(camera.get("height", 0))
    boxes = []
    for item in result.get("boxes", []):
        if not isinstance(item, dict):
            continue
        x1, y1, x2, y2 = (float(item.get(key, 0) or 0) for key in ("x1", "y1", "x2", "y2"))
        boxes.append({
            "label": str(item.get("label", "")),
            "bbox_normalized": [x1, y1, x2, y2],
            "bbox_1000": [round(x1 * 1000), round(y1 * 1000), round(x2 * 1000), round(y2 * 1000)],
            "center_1000": [round((x1 + x2) * 500), round((y1 + y2) * 500)],
            "bbox_pixels": [round(x1 * width), round(y1 * height), round(x2 * width), round(y2 * height)],
        })
    output = {
        "ok": True, "query": query, "camera_view": view,
        "camera": camera.get("camera"), "width": width, "height": height,
        "count": len(boxes), "boxes": boxes,
        "infer_ms": int(result.get("infer_ms", 0) or 0),
        "coordinate_system": "origin top-left; x right; y down; normalized and 0-1000",
    }
    if include_image:
        output["media"] = str(_overlay_snapshot())
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "detect"))
    parser.add_argument("--query", default="")
    parser.add_argument("--view", choices=("head", "left-hand", "right-hand"), default="head")
    parser.add_argument("--no-image", action="store_true")
    args = parser.parse_args()
    result = _json_get("/json") if args.action == "status" else detect(args.query, args.view, not args.no_image)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
