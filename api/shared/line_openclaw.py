"""Authenticated client and command routing for the cam OpenClaw bridge."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import uuid
from typing import Any
from urllib import error, request

from shared import inference_hub


COMMAND_RE = re.compile(
    r"^(?:openclaw|小羽[，, ]*(?:執行|任務|長任務|幫我執行))\s*[：:]?\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)
PAIR_RE = re.compile(r"^(?:openclaw|小羽)\s*配對\s+([A-Za-z0-9_-]{6,80})$", re.IGNORECASE)
X1_POSES = (
    {"id": "away", "label": "away"},
    {"id": "away2", "label": "away2"},
    {"id": "good", "label": "good"},
    {"id": "happy", "label": "happy"},
    {"id": "hello", "label": "hello"},
    {"id": "come", "label": "come"},
    # The owner has physically verified bad and thanks despite conservative model contact flags.
    {"id": "bad", "label": "bad"},
    {"id": "thanks", "label": "thanks"},
    {"id": "goodbye", "label": "goodbye"},
    {"id": "nice", "label": "nice"},
    {"id": "surprised", "label": "surprised"},
    {"id": "wave-happily", "label": "wave happily"},
    {"id": "open-two-arms", "label": "open two arms"},
)
X1_HEAD_POSES = (
    {"id": "nod", "label": "點頭 nod", "headOnly": True},
    {"id": "shake-head", "label": "搖頭 shake", "headOnly": True},
    {"id": "look-at", "label": "注視 look at", "headOnly": True},
)
X1_ALL_POSES = X1_POSES + X1_HEAD_POSES
X1_POSE_BY_ID = {str(item["id"]): item for item in X1_ALL_POSES}
X1_EXTRA_POSES: set[str] = set()
X1_POSE_PATTERN = "|".join(
    re.escape(value) for value in sorted((*X1_POSE_BY_ID, *X1_EXTRA_POSES), key=len, reverse=True)
)
ROBOT_PLAY_RE = re.compile(
    rf"^(?:小羽|rocketai)\s*(?:請\s*)?(?:"
    rf"x1\s*(?:播放(?:動作|手勢)?|做(?:動作|手勢)?|手勢)\s*[：:]?\s*({X1_POSE_PATTERN})|"
    rf"(?:播放(?:動作|手勢)?|做(?:動作|手勢)?|手勢)\s*x1\s*[：:]?\s*({X1_POSE_PATTERN})"
    rf")\s*$",
    re.IGNORECASE,
)
ROBOT_STOP_RE = re.compile(
    r"^(?:小羽|rocketai)\s*(?:請\s*)?(?:x1\s*(?:停止|停下|取消)(?:動作|手勢)?|"
    r"(?:停止|停下|取消)\s*x1(?:的)?(?:動作|手勢)?)\s*$",
    re.IGNORECASE,
)
ROBOT_STATUS_RE = re.compile(
    r"^(?:小羽|rocketai)\s*(?:請\s*)?(?:x1\s*(?:查詢|查看|回報)?\s*(?:的)?\s*(?:狀態|狀況)|"
    r"(?:查詢|查看|回報)\s*x1\s*(?:的)?\s*(?:狀態|狀況))\s*$",
    re.IGNORECASE,
)
ROBOT_LIST_RE = re.compile(
    r"^(?:小羽|rocketai)\s*(?:請\s*)?(?:x1\s*(?:動作|手勢|pose)\s*(?:列表|清單)|"
    r"(?:列出|查看|顯示)\s*x1\s*(?:動作|手勢|pose)|(?:動作|手勢|pose)\s*x1\s*(?:列表|清單))\s*$",
    re.IGNORECASE,
)


def configured() -> bool:
    return bool(
        inference_hub._setting("INFERENCE_HUB_URL")
        and inference_hub._setting("INFERENCE_HUB_TOKEN")
        and inference_hub._setting("LINE_OPENCLAW_CALLBACK_URL")
    )


def parse_command(text: str) -> dict[str, str] | None:
    bounded = str(text or "").strip()[:8500]
    paired = PAIR_RE.fullmatch(bounded)
    if paired:
        return {"action": "pair", "code": paired.group(1)}
    matched = COMMAND_RE.fullmatch(bounded)
    if matched and matched.group(1).strip():
        return {"action": "task", "text": matched.group(1).strip()[:8000]}
    return None


def parse_robot_command(text: str) -> dict[str, str] | None:
    """Parse only explicit, bounded X1 commands; normal conversation must not move it."""
    bounded = str(text or "").strip()[:160]
    matched = ROBOT_PLAY_RE.fullmatch(bounded)
    if matched:
        gesture = str(matched.group(1) or matched.group(2)).lower()
        result = {"action": "play", "robot": "x1", "gesture": gesture}
        if bool((X1_POSE_BY_ID.get(gesture) or {}).get("previewOnly")):
            result["preview"] = "true"
        return result
    if ROBOT_STOP_RE.fullmatch(bounded):
        return {"action": "stop", "robot": "x1"}
    if ROBOT_STATUS_RE.fullmatch(bounded):
        return {"action": "status", "robot": "x1"}
    if ROBOT_LIST_RE.fullmatch(bounded):
        return {"action": "list", "robot": "x1"}
    return None


def _post(path: str, payload: dict[str, Any], timeout: float = 12) -> dict[str, Any]:
    base = inference_hub._setting("INFERENCE_HUB_URL").rstrip("/")
    token = inference_hub._setting("INFERENCE_HUB_TOKEN")
    if not base or not token:
        raise RuntimeError("OpenClaw bridge is not configured")
    req = request.Request(
        f"{base}/openclaw{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise PermissionError(body) if exc.code == 403 else RuntimeError("OpenClaw bridge failed") from exc
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("OpenClaw bridge unavailable") from exc
    return value if isinstance(value, dict) else {}


def pair(user_id: str, code: str) -> None:
    _post("/v1/pair", {"userId": user_id, "code": code})


def submit_task(user_id: str, text: str, task_id: str = "") -> str:
    task_id = task_id or str(uuid.uuid4())
    result = _post("/v1/tasks", {
        "userId": user_id,
        "text": text,
        "taskId": task_id,
        "callbackUrl": inference_hub._setting("LINE_OPENCLAW_CALLBACK_URL"),
    })
    return str(result.get("taskId") or task_id)


def robot_command(
    user_id: str, action: str, gesture: str = "", *, robot: str, preview: bool = False
) -> dict[str, Any]:
    payload: dict[str, Any] = {"userId": user_id, "robot": robot, "action": action}
    if gesture:
        payload["gesture"] = gesture
    if preview:
        payload["preview"] = True
    return _post("/v1/robot", payload, timeout=15)


def sync_reminder(action: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    if action == "cancel":
        _post("/v1/reminders", {
            "action": "cancel", "reminderIds": [str(row["id"]) for row in rows]
        })
        return
    row = rows[0]
    due = datetime.fromtimestamp(int(row["dueAt"]) / 1000, timezone.utc).isoformat()
    _post("/v1/reminders", {
        "action": "schedule",
        "reminderId": str(row["id"]),
        "dueAt": due,
        "callbackUrl": inference_hub._setting("LINE_OPENCLAW_REMINDER_CALLBACK_URL"),
    })
