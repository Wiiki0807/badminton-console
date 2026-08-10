"""HTTP API for the badminton console, replacing the endpoints previously served by server.py."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

import azure.functions as func

from shared import auth, store

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

MAX_BODY_BYTES = 1_000_000


def json_response(value, status: int = 200, headers: dict[str, str] | None = None) -> func.HttpResponse:
    merged = {"Cache-Control": "no-store"}
    merged.update(headers or {})
    return func.HttpResponse(
        json.dumps(value, ensure_ascii=False),
        status_code=status,
        mimetype="application/json",
        headers=merged,
    )


def read_body(req: func.HttpRequest) -> dict:
    raw = req.get_body()
    if not raw or len(raw) > MAX_BODY_BYTES:
        raise ValueError("invalid body size")
    body = json.loads(raw.decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("body must be an object")
    return body


def require_admin(req: func.HttpRequest) -> func.HttpResponse | None:
    if auth.current_user(req):
        return None
    return json_response({"error": "請先登入管理端"}, 401)


@app.route(route="live-bundle", methods=["GET"])
def live_bundle(req: func.HttpRequest) -> func.HttpResponse:
    try:
        bundle = {
            "state": store.read_state(),
            "comments": store.list_comments(),
            "wishes": store.list_wishes(),
        }
    except Exception:
        logging.exception("live-bundle failed")
        return json_response({"error": "資料讀取失敗"}, 500)

    payload = json.dumps(bundle, ensure_ascii=False)
    etag = 'W/"%s"' % hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    if req.headers.get("If-None-Match") == etag:
        return func.HttpResponse(status_code=304, headers={"ETag": etag, "Cache-Control": "no-store"})
    return func.HttpResponse(
        payload,
        status_code=200,
        mimetype="application/json",
        headers={"ETag": etag, "Cache-Control": "no-store"},
    )


@app.route(route="live-state", methods=["POST"])
def publish_state(req: func.HttpRequest) -> func.HttpResponse:
    denied = require_admin(req)
    if denied:
        return denied
    try:
        store.write_state(read_body(req))
    except ValueError:
        return json_response({"error": "格式錯誤"}, 400)
    except Exception:
        logging.exception("live-state write failed")
        return json_response({"error": "寫入失敗"}, 500)
    return json_response({"ok": True})


@app.route(route="comments", methods=["POST"])
def create_comment(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = read_body(req)
    except ValueError:
        return json_response({"error": "格式錯誤"}, 400)
    name = str(body.get("name", "")).strip()[:18]
    message = str(body.get("message", "")).strip()[:120]
    if not name or not message:
        return json_response({"error": "請輸入名字與留言"}, 400)
    try:
        comment = store.add_comment(
            name,
            message,
            str(body.get("matchId", "")).strip()[:80],
            str(body.get("matchLabel", "")).strip()[:80],
        )
    except Exception:
        logging.exception("comment write failed")
        return json_response({"error": "留言儲存失敗"}, 500)
    return json_response(comment, 201)


@app.route(route="wishes", methods=["POST"])
def create_wish(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = read_body(req)
    except ValueError:
        return json_response({"error": "格式錯誤"}, 400)
    player_name = str(body.get("playerName", "")).strip()[:18]
    wish_type = str(body.get("type", "")).strip()
    target = str(body.get("target", "")).strip()[:30]
    if not player_name or wish_type not in store.WISH_COSTS:
        return json_response({"error": "請選擇球友與願望"}, 400)
    if wish_type in {"partner", "opponent"} and not target:
        return json_response({"error": "指定搭檔或對手時請填寫名字"}, 400)
    try:
        wish = store.add_wish(player_name, wish_type, target)
    except Exception:
        logging.exception("wish write failed")
        return json_response({"error": "願望儲存失敗"}, 500)
    return json_response(wish, 201)


@app.route(route="wishes/action", methods=["POST"])
def act_on_wish(req: func.HttpRequest) -> func.HttpResponse:
    denied = require_admin(req)
    if denied:
        return denied
    try:
        body = read_body(req)
    except ValueError:
        return json_response({"error": "格式錯誤"}, 400)
    status = str(body.get("status", ""))
    if status not in {"fulfilled", "rejected"}:
        return json_response({"error": "不支援的願望狀態"}, 400)
    try:
        wish = store.set_wish_status(str(body.get("id", "")), status)
    except Exception:
        logging.exception("wish update failed")
        return json_response({"error": "願望更新失敗"}, 500)
    if not wish:
        return json_response({"error": "找不到願望"}, 404)
    return json_response(wish)


@app.route(route="reactions", methods=["POST"])
def add_reaction(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = read_body(req)
    except ValueError:
        return json_response({"error": "格式錯誤"}, 400)
    emoji = str(body.get("emoji", ""))
    if emoji not in store.ALLOWED_REACTIONS:
        return json_response({"error": "不支援的互動"}, 400)
    try:
        comment = store.add_reaction(str(body.get("id", "")), emoji)
    except Exception:
        logging.exception("reaction update failed")
        return json_response({"error": "互動更新失敗"}, 500)
    if not comment:
        return json_response({"error": "找不到留言"}, 404)
    return json_response(comment)


@app.route(route="auth/login", methods=["POST"])
def login(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = read_body(req)
    except ValueError:
        return json_response({"error": "格式錯誤"}, 400)

    expected_user = os.environ.get("ADMIN_USERNAME", "")
    stored_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
    if not expected_user or not stored_hash:
        logging.error("admin credentials are not configured")
        return json_response({"error": "管理端尚未設定"}, 500)

    try:
        if auth.rate_limited(req):
            return json_response({"error": "嘗試次數過多，請稍後再試"}, 429)
    except Exception:
        logging.exception("rate limit check failed")

    username = str(body.get("username", ""))
    password = str(body.get("password", ""))
    # Both checks run regardless of outcome so a wrong username costs the same time as a wrong password.
    user_ok = hmac.compare_digest(username, expected_user)
    password_ok = auth.verify_password(password, stored_hash)
    if not (user_ok and password_ok):
        try:
            auth.record_failure(req)
        except Exception:
            logging.exception("rate limit write failed")
        return json_response({"error": "帳號或密碼錯誤"}, 401)

    try:
        auth.clear_failures(req)
    except Exception:
        logging.exception("rate limit clear failed")
    return json_response(
        {"authenticated": True, "user": expected_user},
        headers={"Set-Cookie": auth.session_cookie(auth.issue_token(expected_user))},
    )


@app.route(route="auth/logout", methods=["POST"])
def logout(req: func.HttpRequest) -> func.HttpResponse:
    return json_response({"authenticated": False}, headers={"Set-Cookie": auth.expired_cookie()})


@app.route(route="auth/me", methods=["GET"])
def me(req: func.HttpRequest) -> func.HttpResponse:
    user = auth.current_user(req)
    return json_response({"authenticated": bool(user), "user": user or ""})
