"""Narrow localhost bridge between the public LINE gateway and OpenClaw.

The bridge deliberately does not expose the OpenClaw gateway.  It accepts only
owner pairing/agent tasks and structured reminder scheduling operations.
"""
from __future__ import annotations

import argparse
import hmac
import json
import logging
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
CALLBACK_RE = re.compile(r"https://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{1,1800}\Z")


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
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
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


def _run_agent(task_id: str, text: str, callback_url: str) -> None:
    try:
        if re.search(r"Robot Voice Hub.{0,20}(?:狀態|在線|線上)", text, re.IGNORECASE):
            text = (
                "安全約束：只可呼叫 exec，且 command 必須完全是 "
                "'/home/tommywu/.openclaw/robot_control.py status'；"
                "不可使用 find、grep、cat、shell 組合或其他命令。執行後依使用者要求回覆。\n\n"
                f"使用者要求：{text}"
            )
        result = _openclaw(
            "agent", "--agent", "main", "--message", text,
            "--session-key", "agent:main:line-owner", "--timeout", "1800", "--json",
            timeout=1860,
        )
        visible = str(
            ((result.get("result") or {}).get("meta") or {}).get("finalAssistantVisibleText")
            or (result.get("result") or {}).get("text")
            or result.get("text")
            or "任務已完成，但沒有文字輸出。"
        )[:5000]
        _callback(callback_url, {"taskId": task_id, "status": "completed", "text": visible})
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
            if self.path == "/v1/reminders":
                self._json(200, schedule_reminder(body))
                return
            self._json(404, {"error": "not found"})
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except (subprocess.SubprocessError, OSError, urllib.error.URLError):
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
