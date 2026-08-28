"""Natural-language LINE reminder commands and user-facing formatting."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from shared import inference_hub, store


TAIPEI = ZoneInfo("Asia/Taipei")


def _local_time(epoch_ms: int) -> str:
    value = datetime.fromtimestamp(epoch_ms / 1000, timezone.utc).astimezone(TAIPEI)
    return value.strftime("%Y/%m/%d（%a）%H:%M").replace(
        "Mon", "一"
    ).replace("Tue", "二").replace("Wed", "三").replace(
        "Thu", "四"
    ).replace("Fri", "五").replace("Sat", "六").replace("Sun", "日")


def _list_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "你目前沒有待處理的提醒。"
    lines = ["⏰ 你的提醒"]
    for row in rows[:10]:
        lines.append(
            f"• {row['shortId']}｜{_local_time(int(row['dueAt']))}\n  {row['title']}"
        )
    if len(rows) > 10:
        lines.append(f"另有 {len(rows) - 10} 筆未顯示。")
    lines.append("\n可輸入「取消提醒 編號」或「修改提醒 編號 明天下午四點」。")
    return "\n".join(lines)


def handle(text: str, user_id: str, history: list[dict[str, str]] | None = None) -> str | None:
    """Execute one reminder command. Return None when text is not a reminder request."""
    if not inference_hub.looks_like_reminder_request(text):
        return None
    if not user_id:
        return "無法取得你的 LINE user ID，因此目前不能建立私人提醒。"

    command = inference_hub.parse_reminder_command(text, history=history or [])
    action = str(command.get("action", "none"))
    if action in {"none", "unavailable"}:
        return "提醒語意解析暫時無法使用，請稍後再試，或輸入「查看提醒」。"
    if command.get("needs_clarification"):
        return str(command.get("clarification") or "請提供更明確的提醒日期與時間。")[:500]

    if action == "list":
        return _list_text(store.list_line_reminders(user_id))

    if action == "create":
        row = store.create_line_reminder(
            user_id,
            user_id,
            str(command.get("title", "")),
            int(command.get("due_at_ms", 0)),
        )
        return (
            f"⏰ 已設定提醒 {row['shortId']}\n"
            f"時間：{_local_time(int(row['dueAt']))}\n"
            f"事項：{row['title']}"
        )

    identifier = str(command.get("reminder_id") or command.get("title") or "").strip()
    if action == "cancel":
        result = store.cancel_line_reminder(user_id, identifier)
        if result["status"] == "not_found":
            return "找不到符合的待處理提醒，請先輸入「查看提醒」確認編號。"
        if result["status"] == "ambiguous":
            return "找到多筆相似提醒，請輸入「取消提醒 編號」。\n\n" + _list_text(result["rows"])
        if result["status"] == "cancelled_all":
            return f"已取消全部 {result['count']} 筆待處理提醒。"
        row = result["row"]
        return f"已取消提醒 {row['shortId']}：{row['title']}。"

    if action == "update":
        result = store.update_line_reminder(
            user_id,
            identifier,
            title=str(command.get("new_title") or "").strip(),
            due_at_ms=int(command.get("due_at_ms", 0)),
        )
        if result["status"] == "not_found":
            return "找不到符合的待處理提醒，請先輸入「查看提醒」確認編號。"
        if result["status"] == "ambiguous":
            return "找到多筆相似提醒，請使用提醒編號修改。\n\n" + _list_text(result["rows"])
        row = result["row"]
        return (
            f"已更新提醒 {row['shortId']}\n"
            f"時間：{_local_time(int(row['dueAt']))}\n"
            f"事項：{row['title']}"
        )

    return "目前支援新增、查看、修改與取消提醒。"


def notification_text(row: dict[str, Any]) -> str:
    return f"⏰ 小羽提醒你\n\n{str(row.get('title', '提醒事項'))[:1000]}"
