"""LINE Messaging API helpers for the RocketAI official account."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any
from urllib import error, request

from shared import inference_hub

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
LINE_PROFILE_URL = "https://api.line.me/v2/bot/profile/{user_id}"
LINE_CONTENT_URL = "https://api-data.line.me/v2/bot/message/{message_id}/content"
MAX_LINE_IMAGE_BYTES = 6 * 1024 * 1024


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


def _normalize(value: Any) -> str:
    return "".join(str(value or "").strip().casefold().split())


def _player_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = state.get("players") or state.get("roster") or []
    return [item for item in rows if item.get("name")]


def _find_player(state: dict[str, Any], query: str, display_name: str = "") -> tuple[dict[str, Any] | None, str]:
    raw = str(query or "").strip()
    normalized_raw = _normalize(raw).rstrip("的")
    self_query = not raw or normalized_raw in {"自己", "自已", "本人", "我的", "我"}
    lookup = display_name.strip() if self_query else raw
    if not lookup:
        return None, "請輸入球友姓名，例如「戰績 阿力」。"
    normalized = _normalize(lookup)
    rows = _player_rows(state)
    exact = next((item for item in rows if _normalize(item.get("name")) == normalized), None)
    if exact:
        return exact, ""
    partial = [item for item in rows if normalized in _normalize(item.get("name")) or _normalize(item.get("name")) in normalized]
    if len(partial) == 1:
        return partial[0], ""
    if self_query and display_name:
        return None, f"LINE 顯示名稱「{display_name}」尚未對應到本場球友，請改輸入「戰績 姓名」。"
    return None, f"找不到球友「{lookup}」，請確認姓名。"


def _player_stats(state: dict[str, Any], name: str) -> dict[str, Any]:
    return next((item for item in state.get("stats") or [] if _normalize(item.get("name")) == _normalize(name)), {})


def _player_matches(state: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [
        match for match in state.get("recent") or []
        if any(_normalize(item) == _normalize(name) for item in [*(match.get("a") or []), *(match.get("b") or [])])
    ]


def _performance_summary(state: dict[str, Any], query: str, display_name: str = "") -> str:
    player, error_message = _find_player(state, query, display_name)
    if not player:
        return error_message
    name = str(player.get("name"))
    stats = _player_stats(state, name)
    matches = _player_matches(state, name)
    games = int(player.get("games", len(matches)) or 0)
    wins = int(stats.get("wins", player.get("wins", 0)) or 0)
    losses = int(player.get("losses", max(0, games - wins)) or 0)
    lines = [
        f"📊 {name} 本日戰績",
        f"已打 {games} 場｜{wins} 勝 {losses} 敗",
        f"得分 {int(stats.get('pointsFor', 0) or 0)}｜失分 {int(stats.get('pointsAgainst', 0) or 0)}｜得失分 {int(stats.get('diff', 0) or 0):+d}",
        f"⚔️ 目前動態積分 {int(player.get('rating', 0) or 0)}",
    ]
    if matches:
        lines.append("\n最近對戰：")
        for match in matches[:5]:
            team_a = "／".join(match.get("a") or [])
            team_b = "／".join(match.get("b") or [])
            lines.append(f"球場 {match.get('court')}｜{team_a} {match.get('score', '')} {team_b}")
    else:
        lines.append("\n今天尚無已完成的對戰比分。")
    return "\n".join(lines)


def _rating_summary(state: dict[str, Any], query: str, display_name: str = "") -> str:
    player, error_message = _find_player(state, query, display_name)
    if not player:
        return error_message
    name = str(player.get("name"))
    delta = 0
    for match in _player_matches(state, name):
        side_a = any(_normalize(item) == _normalize(name) for item in match.get("a") or [])
        delta += int(match.get("deltaA" if side_a else "deltaB", 0) or 0)
    return f"⚔️ {name} 目前動態積分：{int(player.get('rating', 0) or 0)}\n今日積分變化：{delta:+d}"


def _games_summary(state: dict[str, Any], query: str, display_name: str = "") -> str:
    player, error_message = _find_player(state, query, display_name)
    if not player:
        return error_message
    games = int(player.get("games", 0) or 0)
    target = int(player.get("targetGames", 0) or 0)
    target_text = f"／目標 {target} 場" if target else ""
    return f"🏸 {player.get('name')} 今日已打 {games} 場{target_text}"


def _next_match_summary(state: dict[str, Any]) -> str:
    next_up = state.get("nextUp") or {}
    team_a = next_up.get("a") or []
    team_b = next_up.get("b") or []
    if len(team_a) != 2 or len(team_b) != 2:
        return "目前還沒有可預測的下一組候選對戰。"
    lines = [
        "🔮 猜測下一組對戰",
        f"A隊｜{'／'.join(team_a)}",
        "VS",
        f"B隊｜{'／'.join(team_b)}",
    ]
    detail = " · ".join(
        item for item in (
            str(next_up.get("matchType") or ""),
            f"實力差 {int(next_up.get('diff', 0) or 0)} 分",
        ) if item
    )
    if detail:
        lines.append(detail)
    lines.append("候選名單仍可能因團主調整或球友狀態而變動。")
    return "\n".join(lines)


def help_message() -> str:
    return (
        "我是 RocketAI，多用途 AI 助手 🏸\n"
        "可以一般問答、寫作、翻譯、摘要、規劃與技術協助。\n"
        "也支援：\n"
        "• 傳送圖片進行內容理解與 OCR\n"
        "• 查詢現在日期、時間與即時天氣\n"
        "• 保留最近對話；輸入「清除記憶」可刪除\n\n"
        "羽球活動指令：\n"
        "• 今日場次\n"
        "• 場上\n"
        "• 最新比分\n"
        "• 戰績\n"
        "• 戰績 姓名（例如：戰績 阿力）\n"
        "• 我的戰績／戰績 自己\n"
        "• 積分 姓名／我的積分\n"
        "• 場數 姓名／我的場數\n"
        "• 猜下一組\n"
        "• 看板"
    )


def needs_profile(text: str) -> bool:
    normalized = _normalize(text)
    return any(word in normalized for word in ("自己", "自已", "本人", "我的"))


def is_memory_reset(text: str) -> bool:
    return _normalize(text) in {"忘記對話", "清除記憶", "重設對話", "resetmemory"}


def conversation_id(source: dict[str, Any]) -> str:
    for key, prefix in (("groupId", "group"), ("roomId", "room"), ("userId", "user")):
        value = str(source.get(key, "")).strip()
        if value:
            return f"{prefix}:{value}"
    return ""


def answer(
    text: str,
    state: dict[str, Any],
    display_name: str = "",
    history: list[dict[str, str]] | None = None,
    image_data_url: str = "",
) -> str:
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
    if normalized.startswith("查詢"):
        normalized = normalized[2:]
    if normalized in {"下一組", "下一場", "猜下一組", "猜測下一組", "猜測下一組對戰組合", "預測下一組", "候選對戰"}:
        return _next_match_summary(state)
    if normalized.startswith("我的戰績") or normalized in {"自己戰績", "自已戰績", "本人戰績"}:
        return _performance_summary(state, "自己", display_name)
    if normalized.startswith("戰績"):
        query = normalized[2:] or ""
        return _stats_summary(state) if not query else _performance_summary(state, query, display_name)
    if "本日戰績" in normalized or "今日戰績" in normalized or "對戰分數" in normalized:
        query = normalized.replace("本日戰績", "").replace("今日戰績", "").replace("和對戰分數", "").replace("與對戰分數", "").replace("對戰分數", "")
        return _performance_summary(state, query or "自己", display_name)
    if normalized.startswith("我的積分") or normalized in {"自己積分", "自已積分", "累積積分"}:
        return _rating_summary(state, "自己", display_name)
    if normalized.startswith("積分"):
        return _rating_summary(state, normalized[2:] or "自己", display_name)
    if "累積積分" in normalized:
        return _rating_summary(state, normalized.replace("累積積分", "") or "自己", display_name)
    if normalized.startswith("我的場數") or normalized in {"自己場數", "自已場數", "已打場數"}:
        return _games_summary(state, "自己", display_name)
    if normalized.startswith("場數"):
        return _games_summary(state, normalized[2:] or "自己", display_name)
    if "已打場數" in normalized:
        return _games_summary(state, normalized.replace("已打場數", "") or "自己", display_name)
    if normalized in {"看板", "即時看板", "連結"}:
        live_url = os.environ.get("LIVE_BOARD_URL", "").strip()
        return f"🏸 球友即時看板\n{live_url}" if live_url else "即時看板網址尚未設定。"
    llm_reply = inference_hub.generate_reply(
        text, state, display_name, history=history or [], image_data_url=image_data_url
    )
    return llm_reply or "我目前還不懂這句話。\n\n" + help_message()


def get_message_image(message_id: str, access_token: str) -> str:
    if not message_id:
        raise ValueError("missing LINE message id")
    req = request.Request(
        LINE_CONTENT_URL.format(message_id=message_id),
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            content_type = response.headers.get_content_type().lower()
            if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise ValueError("unsupported LINE image type")
            raw = response.read(MAX_LINE_IMAGE_BYTES + 1)
    except (error.HTTPError, error.URLError, TimeoutError) as exc:
        raise RuntimeError("LINE image download failed") from exc
    if not raw or len(raw) > MAX_LINE_IMAGE_BYTES:
        raise ValueError("LINE image is empty or too large")
    return f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"


def get_display_name(user_id: str, access_token: str) -> str:
    if not user_id:
        return ""
    req = request.Request(
        LINE_PROFILE_URL.format(user_id=user_id),
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return str(payload.get("displayName", "")).strip()
    except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError):
        return ""


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
