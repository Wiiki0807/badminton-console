"""LINE Messaging API helpers for the RocketAI official account."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any
from urllib import error, request

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"


def verify_signature(raw_body: bytes, signature: str, channel_secret: str) -> bool:
    if not signature or not channel_secret:
        return False
    digest = hmac.new(channel_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)


def _event_summary(state: dict[str, Any]) -> str:
    event = state.get("event") or {}
    session = state.get("session") or {}
    courts = state.get("courts") or []
    playing = sum(1 for court in courts if court.get("status") == "playing")
    lines = [
        f"🏸 {event.get('name') or '今日羽球場次'}",
        f"📅 {event.get('date') or '日期未設定'}",
        f"📍 {event.get('venue') or '地點未設定'}",
        f"⏰ {session.get('label') or session.get('key') or '時段未設定'}",
        f"🏟️ {session.get('courts') or len(courts)} 面場｜{playing} 面比賽中",
    ]
    live_url = os.environ.get("LIVE_BOARD_URL", "").strip()
    if live_url:
        lines.extend(["", f"即時看板：{live_url}"])
    return "\n".join(lines)


def _court_summary(state: dict[str, Any]) -> str:
    courts = state.get("courts") or []
    playing = [court for court in courts if court.get("status") == "playing"]
    if not playing:
        return "目前沒有進行中的比賽。"
    lines = ["🏟️ 目前場上"]
    for court in playing:
        team_a = "／".join(court.get("a") or []) or "待確認"
        team_b = "／".join(court.get("b") or []) or "待確認"
        detail = " · ".join(x for x in (court.get("matchType"), court.get("activity")) if x)
        lines.append(f"球場 {court.get('id')}｜{team_a} vs {team_b}")
        if detail:
            lines.append(f"　{detail} · {court.get('minutes', 0)} 分鐘")
    return "\n".join(lines)


def _score_summary(state: dict[str, Any]) -> str:
    recent = state.get("recent") or []
    if not recent:
        return "目前還沒有已完成的比分。"
    lines = ["🏆 最新比分"]
    for match in recent[:3]:
        team_a = "／".join(match.get("a") or [])
        team_b = "／".join(match.get("b") or [])
        lines.append(f"球場 {match.get('court')}｜{team_a} {match.get('score', '')} {team_b}")
        if match.get("review"):
            lines.append(f"　{match['review']}")
    return "\n".join(lines)


def _stats_summary(state: dict[str, Any], query: str = "") -> str:
    stats = state.get("stats") or []
    query = query.strip().casefold()
    if query:
        matches = [item for item in stats if query in str(item.get("name", "")).casefold()]
        if not matches:
            return "找不到這位球友的今日戰績，請確認姓名。"
        item = matches[0]
        return (
            f"📊 {item.get('name')} 今日戰績\n"
            f"勝場 {item.get('wins', 0)}｜得分 {item.get('pointsFor', 0)}｜"
            f"失分 {item.get('pointsAgainst', 0)}｜得失分 {int(item.get('diff', 0)):+d}"
        )
    if not stats:
        return "目前還沒有今日戰績。"
    lines = ["📊 今日戰績榜"]
    for index, item in enumerate(stats[:5], 1):
        lines.append(
            f"{index}. {item.get('name')}｜{item.get('wins', 0)} 勝｜"
            f"得失分 {int(item.get('diff', 0)):+d}"
        )
    lines.append("\n輸入「戰績 姓名」可查個人成績。")
    return "\n".join(lines)


def help_message() -> str:
    return (
        "我是 RocketAI 🏸\n"
        "可查詢目前羽球活動：\n"
        "• 今日場次\n"
        "• 場上\n"
        "• 最新比分\n"
        "• 戰績\n"
        "• 戰績 姓名（例如：戰績 阿力）\n"
        "• 看板"
    )


def answer(text: str, state: dict[str, Any]) -> str:
    normalized = "".join(str(text or "").strip().split())
    if not normalized:
        return help_message()
    if normalized in {"幫助", "說明", "help", "指令", "功能"}:
        return help_message()
    if normalized in {"今日", "今日場次", "場次", "活動", "今天打球"}:
        return _event_summary(state)
    if normalized in {"場上", "現在誰打", "誰在打", "即時場地", "目前場上"}:
        return _court_summary(state)
    if normalized in {"比分", "最新比分", "結果", "賽果"}:
        return _score_summary(state)
    if normalized.startswith("戰績"):
        return _stats_summary(state, normalized[2:])
    if normalized in {"看板", "即時看板", "連結"}:
        live_url = os.environ.get("LIVE_BOARD_URL", "").strip()
        return f"🏸 球友即時看板\n{live_url}" if live_url else "即時看板網址尚未設定。"
    return "我目前還不懂這句話。\n\n" + help_message()


def reply(reply_token: str, text: str, access_token: str) -> None:
    payload = json.dumps(
        {"replyToken": reply_token, "messages": [{"type": "text", "text": text[:5000]}]},
        ensure_ascii=False,
    ).encode("utf-8")
    req = request.Request(
        LINE_REPLY_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=8) as response:
            response.read()
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LINE reply failed ({exc.code}): {body}") from exc
