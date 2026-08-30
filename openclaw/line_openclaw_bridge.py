"""Narrow localhost bridge between the public LINE gateway and OpenClaw.

The bridge deliberately does not expose the OpenClaw gateway.  It accepts only
owner pairing/agent tasks and structured reminder scheduling operations.
"""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import threading
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


STATE_DIR = Path(os.environ.get("OPENCLAW_STATE_DIR", "/home/tommywu/.openclaw"))
OWNER_FILE = STATE_DIR / "line-owner.json"
NODE = "/home/tommywu/.nvm/versions/node/v24.20.0/bin/node"
OPENCLAW_ENTRY = (
    "/home/tommywu/.nvm/versions/node/v24.20.0/lib/node_modules/"
    "openclaw/dist/index.js"
)
MAX_BODY = 64 * 1024
MAX_TASK_CHARS = 8_000
MAX_ARTIFACT_BYTES = 512 * 1024
WORKSPACE_DIR = Path(
    os.environ.get("OPENCLAW_WORKSPACE_DIR", str(STATE_DIR / "workspace"))
)
X1_GESTURE_CONTROL = STATE_DIR / "x1_gesture_control.py"
X1_CAMERA_CONTROL = STATE_DIR / "x1_camera_control.py"
SAFE_X1_GESTURES = {
    "away", "away2", "good", "happy", "hello", "come", "bad", "thanks",
    "goodbye", "nice", "surprised", "wave-happily", "open-two-arms",
    "nod", "shake-head", "look-at",
}
AGENT_RUN_LOCK = threading.Lock()
MEDIA_RE = re.compile(
    r"MEDIA:\s*((?:/|[A-Za-z]:[\\/])[^\r\n)]+)", re.IGNORECASE
)
REMOTE_MEDIA_RE = re.compile(
    r"MEDIA:\s*(https://[^\s<>)]+)", re.IGNORECASE
)
ALLOWED_ARTIFACT_SUFFIXES = {
    ".csv", ".css", ".html", ".js", ".json", ".md", ".pdf", ".ps1",
    ".py", ".sh", ".ts", ".txt", ".yaml", ".yml", ".zip",
    ".jpg", ".jpeg", ".png", ".webp",
}
SENSITIVE_ARTIFACT_RE = re.compile(
    r"(?:^|[._-])(?:\.env|credentials?|private|secrets?|tokens?|id_rsa)(?:$|[._-])",
    re.IGNORECASE,
)
CALLBACK_RE = re.compile(r"https://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{1,1800}\Z")
NEWS_REQUEST_RE = re.compile(
    r"(?:新聞|最新消息|近期消息|產業動態|news|headlines?|company updates?)",
    re.IGNORECASE,
)
MARKET_REQUEST_RE = re.compile(
    r"(?:股價|股票報價|最新報價|收盤價|市場報價|stock prices?|market quotes?|quotes?.{0,12}(?:stock|ticker))",
    re.IGNORECASE,
)
MARKET_CHART_RE = re.compile(
    r"(?:圖表|曲線圖|折線圖|走勢圖|趨勢圖|chart|line\s*chart|plot)", re.IGNORECASE
)
X1_CAMERA_SNAPSHOT_RE = re.compile(
    r"(?=.*(?:X1|機器人))(?=.*(?:頭部|左手|右手|手部|視角|相機|camera))"
    r"(?=.*(?:照片|拍照|取像|snapshot|影像))",
    re.IGNORECASE | re.DOTALL,
)
NEWS_JSON_INSTRUCTION = """

LINE 顯示契約：完成 verified-news-digest 搜尋與交叉查證後，只輸出一個 JSON 物件，
不要 Markdown、不要 code fence、不要前後說明。格式：
{"type":"verified_news_digest","title":"摘要標題","cutoff":"Asia/Taipei 截止時間",
"overallTrend":"整體趨勢","watchNext":"後續觀察",
"items":[{"title":"標題","date":"日期","shortSummary":"80 字內卡片摘要",
"summary":"詳細摘要","importance":"為何重要","confidence":"官方確認/多方報導/單一來源/傳聞／未獲證實",
"sources":["https://直接支持內容的來源"]}]}
最多五則；每則至少一個 HTTPS 原始來源。來源 URL 必須來自實際搜尋／讀取結果，不可編造。
""".strip()
MARKET_JSON_INSTRUCTION = """

LINE 顯示契約：查找使用者指定股票在最近一個已完成交易時段的可靠報價，並只輸出一個 JSON 物件；
不要 Markdown、不要 code fence、不要前後說明。格式：
{"type":"market_snapshot","title":"美股收盤","market":"US","asOf":"含時區的資料日期時間",
"session":"美東收盤","chartRequested":false,"quotes":[{"date":"YYYY-MM-DD","name":"公司名稱","symbol":"NVDA","price":123.45,
"change":1.23,"changePercent":1.01,"currency":"USD","open":122.0,"high":125.0,
"low":121.0,"volume":12345678,"sourceUrl":"https://直接支持該報價的來源"}]}
price、change、changePercent 必須是 JSON 數字；open/high/low/volume 查不到時可為 null。
每個交易日／股票各用一筆 quote，date 必須是實際交易日；最近 N 天是最近 N 個已完成交易日，不是日曆日。
最多三十筆並依日期由舊到新排列。不可把搜尋摘要或模型記憶當即時報價；必須核對交易日期、時段、幣別，
且每檔提供實際讀取、直接支持數字的 HTTPS 來源。若市場尚未開盤，使用最近完成的交易時段並清楚標示 asOf/session。
""".strip()


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _runtime_env(name: str) -> str:
    """Read rotatable callback secrets from disk instead of stale service env."""
    try:
        for line in (STATE_DIR / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    except OSError:
        pass
    return _env(name)


def _openclaw(*args: str, timeout: int = 60) -> dict[str, Any]:
    completed = subprocess.run(
        [NODE, OPENCLAW_ENTRY, *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "no diagnostic output").strip()
        detail = re.sub(
            r"(?i)(bearer|token|secret|password)(\s*[=:]\s*)\S+",
            r"\1\2[redacted]",
            detail,
        )[-800:]
        raise RuntimeError(
            f"OpenClaw exited with code {completed.returncode}: {detail}"
        )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("OpenClaw returned an invalid response")
    return value


def _owner_id() -> str:
    try:
        value = json.loads(OWNER_FILE.read_text(encoding="utf-8"))
        return str(value.get("userId", "")).strip()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""


def _pair(user_id: str, code: str) -> bool:
    if _owner_id():
        return hmac.compare_digest(_owner_id(), user_id)
    if not hmac.compare_digest(code, _env("OPENCLAW_LINE_PAIR_CODE")):
        return False
    OWNER_FILE.write_text(json.dumps({"userId": user_id}), encoding="utf-8")
    OWNER_FILE.chmod(0o600)
    return True


def _x1_robot_command(body: dict[str, Any]) -> dict[str, Any]:
    """Execute one bounded direct LINE command through the shared X1 controller."""
    action = str(body.get("action", "")).lower()
    robot = str(body.get("robot", "")).lower()
    if robot != "x1":
        raise ValueError("unsupported robot")
    if action not in {"status", "play", "stop"}:
        raise ValueError("invalid robot action")
    command = ["/usr/bin/python3", str(X1_GESTURE_CONTROL), action]
    if action == "play":
        gesture = str(body.get("gesture", "")).lower()
        if gesture not in SAFE_X1_GESTURES:
            raise ValueError("gesture is not allow-listed")
        command.append(gesture)
        if not bool(body.get("preview")):
            command.append("--real")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env=os.environ.copy(),
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("X1 controller returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("X1 controller returned an invalid response")
    if completed.returncode or not value.get("ok"):
        raise RuntimeError(str(value.get("error") or "X1 command failed"))
    return value


def _callback(url: str, payload: dict[str, Any]) -> None:
    if not CALLBACK_RE.fullmatch(url):
        raise ValueError("invalid callback URL")
    configured = _env("OPENCLAW_LINE_CALLBACK_URL_PREFIX")
    if not url.startswith(configured):
        raise ValueError("callback URL is outside the allow-list")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "x-line-openclaw-token": _runtime_env("OPENCLAW_LINE_CALLBACK_TOKEN"),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def _news_task_message(text: str) -> str:
    if MARKET_REQUEST_RE.search(text):
        chart_rule = (
            "使用者明確要求圖表，所以 chartRequested 必須是 true。"
            if MARKET_CHART_RE.search(text)
            else "使用者沒有明確要求圖表，所以 chartRequested 必須是 false。"
        )
        return f"{text}\n\n{MARKET_JSON_INSTRUCTION}\n{chart_rule}"
    return f"{text}\n\n{NEWS_JSON_INSTRUCTION}" if NEWS_REQUEST_RE.search(text) else text


def _parse_news_digest(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fence:
        candidate = fence.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or value.get("type") != "verified_news_digest":
        return None
    if not isinstance(value.get("items"), list) or not value["items"]:
        return None
    return value


def _parse_market_snapshot(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fence:
        candidate = fence.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or value.get("type") != "market_snapshot":
        return None
    if not isinstance(value.get("quotes"), list) or not value["quotes"]:
        return None
    return value


def _extract_artifact(text: str) -> tuple[dict[str, Any] | None, str]:
    """Read one bounded, non-sensitive OpenClaw MEDIA file from its workspace."""
    match = MEDIA_RE.search(text)
    if not match:
        return None, text
    cleaned = MEDIA_RE.sub("", text).replace("()", "").strip()
    try:
        workspace = WORKSPACE_DIR.resolve(strict=True)
        candidate = Path(match.group(1).strip(" \t`'\"")).resolve(strict=True)
        if not candidate.is_relative_to(workspace) or not candidate.is_file():
            raise ValueError("artifact is outside the OpenClaw workspace")
        if candidate.suffix.lower() not in ALLOWED_ARTIFACT_SUFFIXES:
            raise ValueError("artifact type is not allowed")
        if SENSITIVE_ARTIFACT_RE.search(candidate.name):
            raise ValueError("sensitive artifact name is not allowed")
        size = candidate.stat().st_size
        if not 1 <= size <= MAX_ARTIFACT_BYTES:
            raise ValueError("artifact size is outside the allowed range")
        raw = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        return {
            "name": candidate.name,
            "contentType": content_type,
            "size": size,
            "base64": base64.b64encode(raw).decode("ascii"),
        }, cleaned
    except ValueError as exc:
        logging.warning("Rejected OpenClaw MEDIA artifact: %s", exc)
        return None, cleaned + "\n\n檔案已產生，但無法安全附加到 LINE。"
    except OSError:
        logging.exception("Unable to read OpenClaw MEDIA artifact")
        return None, cleaned + "\n\n檔案已產生，但無法安全附加到 LINE。"


def _extract_remote_images(text: str) -> tuple[list[str], str]:
    """Extract up to four HTTPS MEDIA URLs for Azure-side image normalization."""
    urls: list[str] = []
    for match in REMOTE_MEDIA_RE.finditer(text):
        candidate = match.group(1).rstrip(".,;:!?，。；：！？]}")
        if candidate not in urls:
            urls.append(candidate)
        if len(urls) == 4:
            break
    if not urls:
        return [], text
    cleaned = REMOTE_MEDIA_RE.sub("", text).replace("()", "").strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return urls, cleaned


def _requested_x1_camera_view(text: str) -> str:
    if re.search(r"(?:左手|左臂|left[ -]?(?:hand|arm))", text, re.IGNORECASE):
        return "left-hand"
    if re.search(r"(?:右手|右臂|right[ -]?(?:hand|arm))", text, re.IGNORECASE):
        return "right-hand"
    return "head"


def _capture_x1_snapshot(view: str = "head") -> tuple[dict[str, Any], str]:
    """Capture through the allow-listed wrapper, never arbitrary camera paths."""
    completed = subprocess.run(
        ["/usr/bin/python3", str(X1_CAMERA_CONTROL), "snapshot", "--view", view],
        check=False, capture_output=True, text=True, timeout=40,
        env=os.environ.copy(),
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("X1 camera controller returned invalid JSON") from exc
    if completed.returncode or not isinstance(value, dict) or not value.get("ok"):
        raise RuntimeError(str(value.get("error") if isinstance(value, dict) else "snapshot failed"))
    media = str(value.get("media", ""))
    artifact, _ = _extract_artifact(f"MEDIA:{media}")
    if not artifact:
        raise RuntimeError("X1 camera snapshot could not be attached")
    caption = (
        f"📷 {value.get('description', 'X1 視角')}（{value.get('camera', '')}，"
        f"{value.get('width', 0)}×{value.get('height', 0)}）"
    )
    return artifact, caption


def _run_agent(task_id: str, text: str, callback_url: str) -> None:
    try:
        if X1_CAMERA_SNAPSHOT_RE.search(text):
            artifact, caption = _capture_x1_snapshot(_requested_x1_camera_view(text))
            _callback(callback_url, {
                "taskId": task_id, "status": "completed", "text": caption,
                "artifact": artifact,
            })
            return
        market_chart_requested = bool(MARKET_CHART_RE.search(text))
        if re.search(r"Robot Voice Hub.{0,20}(?:狀態|在線|線上)", text, re.IGNORECASE):
            text = (
                "安全約束：只可呼叫 exec，且 command 必須完全是 "
                "'/home/tommywu/.openclaw/robot_control.py status'；"
                "不可使用 find、grep、cat、shell 組合或其他命令。執行後依使用者要求回覆。\n\n"
                f"使用者要求：{text}"
            )
        elif re.search(
            r"(?:(?:X1|機器人).{0,24}(?:手勢|動作|away|thanks)|"
            r"(?:away2?|thanks).{0,24}(?:手勢|動作|X1|機器人))",
            text,
            re.IGNORECASE,
        ):
            text = (
                "X1 安全約束：使用 x1-gesture-control skill；只可透過 exec 直接呼叫 "
                "/home/tommywu/.openclaw/x1_gesture_control.py。不得直接操作 ROS2、"
                "Unix socket、laban_ctl.py 或任意 gesture 檔。先查 status；除非使用者明確說"
                "實機／真機／physical，否則只能 Isaac 預覽。只允許 "
                "x1-gesture-control skill 文件列出的 gesture，最多五步，"
                "收到停止要求必須立刻 stop。\n\n"
                f"使用者要求：{text}"
            )
        text = _news_task_message(text)
        # One shared line-owner session allowed concurrent task threads to race
        # for the same OpenClaw session lock. Keep each task isolated and also
        # serialize the CLI so shared workspace tools cannot overlap.
        session_key = f"agent:main:line-task-{task_id.replace('-', '')[:16]}"
        with AGENT_RUN_LOCK:
            result = _openclaw(
                "agent", "--agent", "main", "--message", text,
                "--session-key", session_key, "--timeout", "1800", "--json",
                timeout=1860,
            )
        visible = str(
            ((result.get("result") or {}).get("meta") or {}).get("finalAssistantVisibleText")
            or (result.get("result") or {}).get("text")
            or result.get("text")
            or "任務已完成，但沒有文字輸出。"
        )[:30000]
        artifact, visible = _extract_artifact(visible)
        image_urls, visible = _extract_remote_images(visible)
        payload: dict[str, Any] = {
            "taskId": task_id, "status": "completed", "text": visible[:5000]
        }
        if artifact:
            payload["artifact"] = artifact
        if image_urls:
            payload["imageUrls"] = image_urls
        digest = _parse_news_digest(visible)
        snapshot = _parse_market_snapshot(visible)
        if snapshot:
            snapshot["chartRequested"] = market_chart_requested
            payload["marketSnapshot"] = snapshot
        elif digest:
            payload["newsDigest"] = digest
        _callback(callback_url, payload)
    except Exception as exc:
        logging.exception("OpenClaw task failed id=%s", task_id)
        try:
            _callback(callback_url, {
                "taskId": task_id,
                "status": "failed",
                "text": f"OpenClaw 任務失敗：{type(exc).__name__}",
            })
        except Exception:
            logging.exception("OpenClaw failure callback also failed id=%s", task_id)


def _cron_jobs() -> list[dict[str, Any]]:
    value = _openclaw("cron", "list", "--json")
    jobs = value.get("jobs") if isinstance(value, dict) else []
    return jobs if isinstance(jobs, list) else []


def _remove_declaration(declaration_key: str) -> bool:
    for job in _cron_jobs():
        if str(job.get("declarationKey", "")) == declaration_key:
            _openclaw("cron", "remove", str(job.get("id", "")), "--json")
            return True
    return False


def schedule_reminder(body: dict[str, Any]) -> dict[str, Any]:
    action = str(body.get("action", ""))
    reminder_ids = body.get("reminderIds") or [body.get("reminderId")]
    reminder_ids = [str(value) for value in reminder_ids if value]
    if not reminder_ids or any(not re.fullmatch(r"[0-9a-fA-F-]{32,36}", value) for value in reminder_ids):
        raise ValueError("invalid reminder id")
    if action == "cancel":
        return {
            "ok": True,
            "removed": sum(_remove_declaration(f"line-reminder-{value}") for value in reminder_ids),
        }
    if action != "schedule" or len(reminder_ids) != 1:
        raise ValueError("invalid reminder action")
    due_at = str(body.get("dueAt", ""))
    callback_url = str(body.get("callbackUrl", ""))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", due_at):
        raise ValueError("invalid reminder time")
    if not CALLBACK_RE.fullmatch(callback_url) or not callback_url.startswith(
        _env("OPENCLAW_LINE_CALLBACK_URL_PREFIX")
    ):
        raise ValueError("invalid reminder callback")
    reminder_id = reminder_ids[0]
    result = _openclaw(
        "cron", "add", "--name", f"line-reminder-{reminder_id[:8]}",
        "--at", due_at,
        "--command", f"/home/tommywu/.openclaw/azure_callback.py reminder {callback_url}",
        "--declaration-key", f"line-reminder-{reminder_id}",
        "--delete-after-run", "--no-deliver", "--json",
    )
    return {"ok": True, "jobId": str((result.get("job") or {}).get("id", ""))}


class Handler(BaseHTTPRequestHandler):
    server_version = "RocketAIOpenClawBridge/1"

    def log_message(self, fmt: str, *args: object) -> None:
        logging.info("%s - %s", self.address_string(), fmt % args)

    def _json(self, status: int, value: dict[str, Any]) -> None:
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, f"Bearer {_env('OPENCLAW_BRIDGE_TOKEN')}")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(200, {"status": "ok", "paired": bool(_owner_id())})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= MAX_BODY:
                raise ValueError("invalid body size")
            body = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
            if self.path == "/v1/pair":
                user_id = str(body.get("userId", ""))
                if not re.fullmatch(r"U[0-9A-Za-z]{8,80}", user_id):
                    raise ValueError("invalid LINE user id")
                if not _pair(user_id, str(body.get("code", ""))):
                    self._json(403, {"error": "pairing rejected"})
                    return
                self._json(200, {"ok": True, "paired": True})
                return
            if self.path == "/v1/tasks":
                user_id = str(body.get("userId", ""))
                if not _owner_id() or not hmac.compare_digest(user_id, _owner_id()):
                    self._json(403, {"error": "owner only"})
                    return
                text = " ".join(str(body.get("text", "")).split())
                callback_url = str(body.get("callbackUrl", ""))
                if not 1 <= len(text) <= MAX_TASK_CHARS:
                    raise ValueError("invalid task")
                task_id = str(body.get("taskId", "")) or str(uuid.uuid4())
                thread = threading.Thread(
                    target=_run_agent, args=(task_id, text, callback_url), daemon=True
                )
                thread.start()
                self._json(202, {"ok": True, "taskId": task_id, "status": "accepted"})
                return
            if self.path == "/v1/robot":
                user_id = str(body.get("userId", ""))
                if not _owner_id() or not hmac.compare_digest(user_id, _owner_id()):
                    self._json(403, {"error": "owner only"})
                    return
                self._json(200, _x1_robot_command(body))
                return
            if self.path == "/v1/admin/robot":
                # Private loopback entry for the Inference Hub Control UI. The
                # public Funnel gateway does not expose paths below /v1/admin.
                self._json(200, _x1_robot_command(body))
                return
            if self.path == "/v1/reminders":
                self._json(200, schedule_reminder(body))
                return
            self._json(404, {"error": "not found"})
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except (RuntimeError, subprocess.SubprocessError, OSError, urllib.error.URLError):
            logging.exception("Bridge request failed path=%s", self.path)
            self._json(502, {"error": "OpenClaw unavailable"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18890)
    args = parser.parse_args()
    for required in (
        "OPENCLAW_BRIDGE_TOKEN", "OPENCLAW_LINE_PAIR_CODE",
        "OPENCLAW_LINE_CALLBACK_TOKEN", "OPENCLAW_LINE_CALLBACK_URL_PREFIX",
    ):
        _env(required)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
