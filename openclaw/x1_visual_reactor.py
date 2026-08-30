#!/usr/bin/env python3
"""Lightweight persistent LocateAnything -> X1 gesture event reactor."""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
import urllib.request
import uuid

from x1_locate_control import _json_get, _overlay_snapshot


STATE_DIR = Path(os.environ.get("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw")))
CONFIG_FILE = STATE_DIR / "visual-reactor.json"
RUNTIME_FILE = STATE_DIR / "visual-reactor-state.json"
ENV_FILE = STATE_DIR / ".env"
GESTURE_CONTROL = STATE_DIR / "x1_gesture_control.py"
POLL_SECONDS = 0.25
MAX_EVENT_IMAGE_BYTES = 512 * 1024


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default.copy()
    except (OSError, json.JSONDecodeError):
        return default.copy()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f"{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _settings() -> dict[str, str]:
    values = dict(os.environ)
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def _artifact(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if not raw.startswith(b"\xff\xd8") or len(raw) > MAX_EVENT_IMAGE_BYTES:
        raise RuntimeError("visual event image is invalid")
    return {
        "name": path.name, "contentType": "image/jpeg", "size": len(raw),
        "base64": base64.b64encode(raw).decode("ascii"),
    }


def _notify(config: dict[str, Any], count: int, image: Path, action_ok: bool) -> None:
    settings = _settings()
    prefix = settings.get("OPENCLAW_LINE_CALLBACK_URL_PREFIX", "")
    token = settings.get("OPENCLAW_LINE_CALLBACK_TOKEN", "")
    if not prefix.startswith("https://") or not token:
        raise RuntimeError("LINE visual callback is not configured")
    payload = {
        "eventId": str(uuid.uuid4()), "robot": "x1", "query": config["query"],
        "count": count, "actions": config["actions"], "view": config["view"],
        "actionOk": action_ok, "artifact": _artifact(image),
    }
    req = urllib.request.Request(
        prefix + "line-visual-reactor-event",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"x-line-openclaw-token": token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        response.read()


def _set_query(query: str) -> None:
    value = _json_get("/set", {"task": "detect", "q": query, "grid": "1", "coords": "1"})
    if not value.get("ok"):
        raise RuntimeError("LocateAnything rejected visual reactor query")


def _run_actions(actions: list[str]) -> bool:
    completed = subprocess.run(
        [str(GESTURE_CONTROL), "sequence", *actions, "--real"], check=False,
        capture_output=True, text=True, timeout=120, env=os.environ.copy(),
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        value = {}
    return completed.returncode == 0 and bool(value.get("ok"))


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    revision: object = None
    first_seen = 0.0
    absent_since = 0.0
    present = False
    next_action_at = 0.0
    runtime: dict[str, Any] = {"running": True, "enabled": False, "phase": "idle"}
    while True:
        config = _read_json(CONFIG_FILE, {"enabled": False, "revision": 0})
        if config.get("revision") != revision:
            revision = config.get("revision")
            first_seen = absent_since = next_action_at = 0.0
            present = False
            runtime = {
                "running": True, "enabled": bool(config.get("enabled")),
                "phase": "arming" if config.get("enabled") else "stopped",
                "revision": revision, "query": config.get("query"),
                "actions": config.get("actions", []), "view": config.get("view"),
            }
            _write_json(RUNTIME_FILE, runtime)
            if config.get("enabled"):
                try:
                    subprocess.run(
                        [str(STATE_DIR / "x1_camera_control.py"), "select", "--view", str(config["view"])],
                        check=True, capture_output=True, text=True, timeout=40,
                    )
                    _set_query(str(config["query"]))
                except Exception as exc:
                    runtime.update(phase="error", error=str(exc)[:300])
                    _write_json(RUNTIME_FILE, runtime)
                    time.sleep(1)
                    continue
        if not config.get("enabled"):
            time.sleep(POLL_SECONDS)
            continue
        now = time.monotonic()
        try:
            result = _json_get("/json")
            if result.get("task") != "detect" or str(result.get("query", "")) != str(config["query"]):
                _set_query(str(config["query"]))
                first_seen = 0.0
                time.sleep(POLL_SECONDS)
                continue
            fresh = not result.get("error") and float(result.get("boxes_age", 99) or 99) <= 2.0
            count = int(result.get("count", 0) or 0) if fresh else 0
            runtime.update(
                enabled=True, count=count, inferMs=int(result.get("infer_ms", 0) or 0),
                resultAge=float(result.get("boxes_age", 0) or 0), error=result.get("error"),
                updatedAt=int(time.time()),
            )
            if count > 0:
                absent_since = 0.0
                first_seen = first_seen or now
                runtime["phase"] = "present" if present else "confirming"
                runtime["confirmElapsed"] = round(now - first_seen, 2)
                if not present and now - first_seen >= float(config["confirmSeconds"]):
                    present = True
                    runtime["phase"] = "triggering"
                    image = _overlay_snapshot()
                    action_ok = _run_actions(list(config["actions"]))
                    runtime.update(
                        phase="cooldown", lastTriggeredAt=int(time.time()),
                        lastCount=count, lastActionOk=action_ok,
                    )
                    next_action_at = time.monotonic() + float(config["repeatSeconds"])
                    try:
                        _notify(config, count, image, action_ok)
                        runtime["lastNotificationAt"] = int(time.time())
                        runtime.pop("notificationError", None)
                    except Exception as exc:
                        logging.exception("visual event notification failed")
                        runtime["notificationError"] = str(exc)[:300]
                elif present and now >= next_action_at:
                    action_ok = _run_actions(list(config["actions"]))
                    runtime.update(
                        phase="cooldown", lastTriggeredAt=int(time.time()),
                        lastCount=count, lastActionOk=action_ok,
                    )
                    next_action_at = time.monotonic() + float(config["repeatSeconds"])
            else:
                first_seen = 0.0
                absent_since = absent_since or now
                runtime["phase"] = "clearing" if present else "waiting"
                if present and now - absent_since >= float(config.get("clearSeconds", 1.0)):
                    present = False
                    next_action_at = 0.0
                    runtime.update(phase="waiting", lastDisappearedAt=int(time.time()))
            runtime["objectPresent"] = present
            if next_action_at:
                runtime["nextActionIn"] = round(max(0.0, next_action_at - time.monotonic()), 1)
            _write_json(RUNTIME_FILE, runtime)
        except Exception as exc:
            logging.exception("visual reactor loop failed")
            runtime.update(phase="error", error=str(exc)[:300], updatedAt=int(time.time()))
            _write_json(RUNTIME_FILE, runtime)
            time.sleep(1)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
