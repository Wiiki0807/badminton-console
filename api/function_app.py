"""HTTP API for the badminton console, replacing the endpoints previously served by server.py."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import azure.functions as func

from shared import store
from shared import line_bot
from shared import inference_hub
from shared import pdf_summary
from shared import reminders
from shared import line_openclaw
from shared import news_digest
from shared import market_snapshot
from shared import remote_image

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

MAX_BODY_BYTES = 1_000_000
# Browsers assume UTF-8 for JSON, but other clients fall back to ISO-8859-1 without this.
JSON_CONTENT_TYPE = "application/json; charset=utf-8"
TAIPEI = ZoneInfo("Asia/Taipei")
DAILY_OPENCLAW_PROMPT = (
    "請製作今天的 RocketAI 每日情報並推送給主人。第一則必須是新北市板橋區今日天氣預報，"
    "請用 web_fetch 讀取 Open-Meteo 今日預報 JSON："
    "https://api.open-meteo.com/v1/forecast?latitude=25.0143&longitude=121.4672&"
    "daily=weather_code,temperature_2m_max,temperature_2m_min,"
    "precipitation_probability_max,precipitation_sum&timezone=Asia%2FTaipei&forecast_days=1；"
    "摘要需包含天氣、最高／最低溫、最高降雨機率與預估雨量。"
    "其餘最多四則整理過去 24 小時 NVIDIA、AI 新技術與機器人相關新聞。"
    "新聞必須使用 verified-news-digest 流程：Tavily 搜尋候選、web_fetch 打開重要原始來源、"
    "交叉整理並附實際來源連結；標示官方確認、多方報導、單一來源或未獲證實。"
    "輸出適合 LINE Flex Carousel 的 verified_news_digest JSON。"
)


def _welcome_for_message(source: dict, message_type: str) -> str:
    """Return only a non-owner's one-time welcome; chat never triggers a briefing."""
    user_id = str(source.get("userId", "")).strip()
    if message_type != "text" or not user_id or line_bot.is_group_source(source):
        return ""
    if inference_hub.is_line_owner(user_id):
        return ""
    return line_bot.welcome_message() if store.claim_line_welcome(user_id) else ""


def _reply_with_welcome(
    reply_token: str,
    text: str,
    access_token: str,
    welcome: str,
) -> None:
    messages = [text]
    if welcome.strip():
        messages.append(welcome.strip())
    line_bot.reply_texts(reply_token, messages, access_token)


def _push_image_processing_notice(
    source: dict, webhook_event_id: str, access_token: str
) -> None:
    """Push exactly one visible notice when a long image operation actually starts."""
    target_id = line_bot.push_target_id(source)
    if not target_id:
        return
    seed = str(webhook_event_id or uuid.uuid4())
    retry_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"rocketai:image-progress:{seed}"))
    line_bot.push_text(
        target_id,
        "🎨 圖片處理中，請稍等一下……",
        access_token,
        retry_key=retry_key,
    )


def json_response(value, status: int = 200, headers: dict[str, str] | None = None) -> func.HttpResponse:
    merged = {"Cache-Control": "no-store", "Content-Type": JSON_CONTENT_TYPE}
    merged.update(headers or {})
    return func.HttpResponse(
        json.dumps(value, ensure_ascii=False),
        status_code=status,
        mimetype=JSON_CONTENT_TYPE,
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


def _openclaw_artifact(value: object) -> dict | None:
    """Validate and decode a bounded artifact received from the private cam bridge."""
    if not isinstance(value, dict):
        return None
    filename = str(value.get("name", ""))
    content_type = str(value.get("contentType", "application/octet-stream"))[:100]
    encoded = str(value.get("base64", ""))
    if not filename or len(filename) > 120 or len(encoded) > 700_000:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    if not raw or len(raw) > 512 * 1024 or value.get("size") != len(raw):
        return None
    return {"name": filename, "contentType": content_type, "size": len(raw), "raw": raw}


def _openclaw_artifacts(body: dict) -> list[dict]:
    """Accept up to three bounded artifacts while retaining legacy singular payloads."""
    values = body.get("artifacts")
    if not isinstance(values, list):
        values = [body.get("artifact")]
    result: list[dict] = []
    total = 0
    for value in values[:3]:
        artifact = _openclaw_artifact(value)
        if artifact is None:
            continue
        total += artifact["size"]
        if total > 768 * 1024:
            break
        result.append(artifact)
    return result


def _openclaw_image_urls(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:4]:
        candidate = str(item or "").strip()
        if candidate.startswith("https://") and len(candidate) <= 2000 and candidate not in result:
            result.append(candidate)
    return result


@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Dependency-free liveness endpoint for Container Apps revisions."""
    return json_response({"ok": True, "service": "badminton-api"})


def summarize_line_pdf_message(message: dict, access_token: str) -> str:
    """Download, extract and summarize one bounded LINE PDF file message."""
    file_name = str(message.get("fileName", "document.pdf"))[:120]
    if not file_name.lower().endswith(".pdf"):
        return "目前只支援 PDF 摘要，請傳送副檔名為 .pdf 的檔案。"
    try:
        declared_size = int(message.get("fileSize") or 0)
    except (TypeError, ValueError):
        declared_size = 0
    try:
        raw_pdf = line_bot.get_message_pdf(
            str(message.get("id", "")), access_token, declared_size
        )
        extracted = pdf_summary.extract_pdf_text(raw_pdf)
        request_text = (
            "請以繁體中文摘要這份 PDF，包含：文件主旨、重要重點、主要結論，"
            "以及文件中明確出現的待辦或決策。不可捏造文件未提供的資訊。"
        )
        text = inference_hub.generate_reply(
            request_text,
            {},
            document_text=extracted["text"],
            document_name=file_name,
        ) or "PDF 已解析，但 AI 摘要服務暫時無法回覆，請稍後再試。"
        if extracted["truncated"]:
            text = (
                text[:4300]
                + f"\n\n註：此 PDF 共 {extracted['page_count']} 頁，"
                + f"本次摘要使用前 {extracted['pages_processed']} 頁或文字上限內的內容。"
            )
        return text
    except pdf_summary.PdfSummaryError as exc:
        return str(exc)
    except (ValueError, RuntimeError):
        logging.exception("LINE PDF download failed")
        return "PDF 下載失敗或檔案過大，請確認檔案小於 10 MB 後再試。"


@app.route(route="line-webhook", methods=["POST"])
def line_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """Receive RocketAI webhook events and reply with the current public match state."""
    raw = req.get_body()
    channel_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    signature = req.headers.get("x-line-signature", "")
    if not channel_secret or not access_token:
        logging.error("LINE environment variables are not configured")
        return json_response({"error": "LINE 尚未完成設定"}, 503)
    if not line_bot.verify_signature(raw, signature, channel_secret):
        return json_response({"error": "invalid signature"}, 401)

    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return json_response({"error": "invalid body"}, 400)

    # LINE's Verify action sends an empty events array and expects HTTP 200.
    for event in body.get("events") or []:
        message = event.get("message") or {}
        reply_token = event.get("replyToken", "")
        if event.get("type") == "postback" and reply_token:
            try:
                if not store.claim_line_webhook_event(str(event.get("webhookEventId", ""))):
                    continue
                source = event.get("source") or {}
                values = parse_qs(str((event.get("postback") or {}).get("data", "")))
                action = values.get("action", [""])[0]
                user_id = str(source.get("userId", ""))
                if action == "robot_pose_cancel":
                    line_bot.reply(reply_token, "已取消 X1 實機動作。", access_token)
                    continue
                if action == "robot_pose":
                    robot = values.get("robot", [""])[0].lower()
                    gesture = values.get("pose", [""])[0].lower()
                    pose = line_openclaw.X1_POSE_BY_ID.get(gesture)
                    if not inference_hub.is_line_owner(user_id):
                        text = "這個 X1 動作控制只允許已設定的主人使用。"
                    elif robot != "x1" or not pose:
                        text = "這個機器人或動作不在允許清單中。"
                    else:
                        preview = values.get("preview", [""])[0] == "1"
                        confirmed = values.get("confirmed", [""])[0] == "1"
                        if not preview and not confirmed:
                            line_bot.reply_messages(
                                reply_token,
                                [line_bot.robot_pose_confirmation(robot, gesture)],
                                access_token,
                            )
                            continue
                        result = line_openclaw.robot_command(
                            user_id, "play", gesture, robot=robot, preview=preview
                        )
                        mode = "Isaac 預覽" if preview else "實機"
                        text = (
                            f"▶️ X1 已接受動作：{gesture}（{mode}）。"
                            if result.get("ok") else f"X1 無法播放動作：{gesture}。"
                        )
                    line_bot.reply_messages(
                        reply_token,
                        [line_bot.robot_pose_quick_reply(
                            "x1", line_openclaw.X1_POSES, text=text
                        )],
                        access_token,
                    )
                    continue
                if action == "robot_control":
                    robot = values.get("robot", [""])[0].lower()
                    command = values.get("command", [""])[0].lower()
                    if not inference_hub.is_line_owner(user_id):
                        text = "這個 X1 動作控制只允許已設定的主人使用。"
                    elif robot != "x1" or command not in {"status", "stop", "list", "help", "robots"}:
                        text = "這個機器人控制指令不在允許清單中。"
                    elif command == "list":
                        line_bot.reply_messages(
                            reply_token,
                            [line_bot.robot_pose_catalog("x1", line_openclaw.X1_ALL_POSES)],
                            access_token,
                        )
                        continue
                    elif command == "robots":
                        line_bot.reply_messages(
                            reply_token, [line_bot.robot_selector_flex()], access_token
                        )
                        continue
                    elif command == "help":
                        text = (
                            "X1 實機控制說明\n"
                            "• 點選 pose 後還要再次確認才會移動。\n"
                            "• 一般 pose 會依 Laban 同步頭部。\n"
                            "• nod／shake-head／look-at 只控制頭部。\n"
                            "• 執行前請確認機器人周圍淨空。\n"
                            "• 發現異常請立即按「停止」。\n"
                            "• 此選單只連結給已設定的主人。"
                        )
                    else:
                        result = line_openclaw.robot_command(
                            user_id, command, robot=robot
                        )
                        if command == "stop":
                            text = "⏹️ X1 已收到停止指令。" if result.get("ok") else "X1 目前無法停止。"
                        else:
                            text = (
                                "X1 狀態\n"
                                f"• 動作中：{'是' if result.get('playing') else '否'}\n"
                                f"• 關節資料：{'正常' if result.get('joint_states') else '無資料'}\n"
                                f"• Isaac mirror：{'在線' if result.get('isaac_mirror') else '離線'}\n"
                                f"• 安全動作：{len(result.get('safe_gestures') or [])} 個"
                            ) if result.get("ok") else "X1 狀態目前無法取得。"
                    line_bot.reply(reply_token, text, access_token)
                    continue
                task_id = str(uuid.UUID(values.get("task", [""])[0]))
                if action == "news_detail":
                    item_index = int(values.get("item", ["-1"])[0])
                    item = store.get_line_openclaw_news_item(task_id, user_id, item_index)
                    text = (
                        news_digest.detail_text(item) if item else
                        "這則摘要不存在、已過期，或不屬於你的帳號。"
                    )
                    line_bot.reply(reply_token, text, access_token)
                elif action == "market_details":
                    raw_snapshot = store.get_line_openclaw_market_snapshot(task_id, user_id)
                    snapshot = market_snapshot.validate(raw_snapshot)
                    text = (
                        market_snapshot.detail_text(snapshot) if snapshot else
                        "這組報價不存在、已過期，或不屬於你的帳號。"
                    )
                    line_bot.reply(reply_token, text, access_token)
                elif action == "market_refresh":
                    raw_snapshot = store.get_line_openclaw_market_snapshot(task_id, user_id)
                    row = store.get_line_openclaw_task(task_id) if raw_snapshot else None
                    prompt = str((row or {}).get("prompt", "")).strip()
                    if not prompt:
                        line_bot.reply(reply_token, "這組報價已無法更新，請重新輸入查詢。", access_token)
                    else:
                        try:
                            new_task_id = str(uuid.uuid4())
                            store.create_line_openclaw_task(new_task_id, user_id, prompt)
                            line_openclaw.submit_task(user_id, prompt, task_id=new_task_id)
                            text = f"📈 已開始更新報價 {new_task_id[:8]}，完成後小羽會通知你。"
                        except PermissionError:
                            text = "這個更新操作只允許已配對的主人使用。"
                        except Exception:
                            logging.exception("LINE market refresh failed")
                            text = "報價更新服務暫時無法接受任務，請稍後再試。"
                        line_bot.reply(reply_token, text, access_token)
            except (ValueError, TypeError):
                logging.warning("Rejected malformed LINE news-detail postback")
            except Exception:
                logging.exception("LINE news-detail postback failed")
            continue
        message_type = message.get("type")
        if event.get("type") != "message" or message_type not in {"text", "image", "file"} or not reply_token:
            continue
        try:
            source = event.get("source") or {}
            try:
                if not store.claim_line_webhook_event(str(event.get("webhookEventId", ""))):
                    logging.info("Skipped duplicate LINE webhook event")
                    continue
            except Exception:
                # Deduplication is protective rather than required for availability.
                logging.exception("LINE webhook deduplication unavailable; processing event")
            conversation_id = line_bot.conversation_id(source)
            image_context_id = line_bot.image_context_id(source)
            incoming_text = str(message.get("text", "")) if message_type == "text" else ""
            try:
                history = store.list_line_memory(conversation_id)
            except Exception:
                logging.exception("LINE memory read failed; continuing without history")
                history = []
            if line_bot.is_group_source(source):
                if not line_bot.should_handle_group_message(message, history):
                    continue
                if message_type == "text" and line_bot.is_explicit_bot_wake(message):
                    incoming_text = line_bot.strip_bot_wake_text(message)
            welcome = _welcome_for_message(source, message_type)
            if message_type == "text" and line_bot.is_memory_reset(incoming_text):
                store.clear_line_memory(conversation_id)
                _reply_with_welcome(
                    reply_token, "已清除這個對話最近的記憶。", access_token, welcome
                )
                continue
            robot_command = (
                line_openclaw.parse_robot_command(incoming_text)
                if message_type == "text" and not line_bot.is_group_source(source)
                else None
            )
            if robot_command:
                user_id = str(source.get("userId", ""))
                if not inference_hub.is_line_owner(user_id):
                    text = "這個 X1 動作控制只允許已設定的主人使用。"
                elif robot_command["action"] == "list":
                    line_bot.reply_messages(
                        reply_token,
                        [line_bot.robot_pose_catalog("x1", line_openclaw.X1_ALL_POSES)],
                        access_token,
                    )
                    continue
                else:
                    try:
                        result = line_openclaw.robot_command(
                            user_id,
                            robot_command["action"],
                            robot_command.get("gesture", ""),
                            robot=robot_command["robot"],
                            preview=robot_command.get("preview") == "true",
                        )
                        action = robot_command["action"]
                        if action == "status":
                            online = bool(
                                result.get("ok")
                                and result.get("joint_states")
                                and int(result.get("left_subs", 0)) > 0
                                and int(result.get("right_subs", 0)) > 0
                            )
                            text = (
                                f"🤖 X1 {'在線' if online else '尚未就緒'}\n"
                                f"動作：{'播放中' if result.get('playing') else '待命'}\n"
                                f"Isaac 鏡像：{'已連線' if result.get('isaac_mirror') else '未連線'}"
                            )
                        elif action == "stop":
                            text = "⏹️ X1 動作已停止。" if result.get("ok") else "X1 動作停止失敗。"
                        else:
                            gesture = robot_command.get("gesture", "")
                            mode = (
                                "Isaac 預覽"
                                if robot_command.get("preview") == "true"
                                else "實機"
                            )
                            text = (
                                f"▶️ X1 已接受動作：{gesture}（{mode}）。"
                                if result.get("ok")
                                else f"X1 無法播放動作：{gesture}。"
                            )
                    except PermissionError:
                        text = "這個 X1 動作控制只允許已配對的主人使用。"
                    except Exception:
                        logging.exception("LINE X1 robot command failed")
                        text = "X1 動作控制目前無法連線，請稍後再試。"
                _reply_with_welcome(reply_token, text, access_token, welcome)
                continue
            openclaw_command = (
                line_openclaw.parse_command(incoming_text)
                if message_type == "text" and not line_bot.is_group_source(source)
                else None
            )
            if openclaw_command:
                user_id = str(source.get("userId", ""))
                try:
                    if openclaw_command["action"] == "pair":
                        line_openclaw.pair(user_id, openclaw_command["code"])
                        text = "🔐 OpenClaw 已和你的 LINE ID 安全配對。"
                    else:
                        task_id = str(uuid.uuid4())
                        store.create_line_openclaw_task(
                            task_id, user_id, openclaw_command["text"]
                        )
                        line_openclaw.submit_task(
                            user_id, openclaw_command["text"], task_id=task_id
                        )
                        text = (
                            f"🦞 OpenClaw 已接受長任務 {task_id[:8]}。\n"
                            "完成後小羽會主動通知你。"
                        )
                except PermissionError:
                    text = "這個 OpenClaw 指令只允許已配對的主人使用。"
                except Exception:
                    logging.exception("LINE OpenClaw command failed")
                    text = "OpenClaw 目前無法接受任務，請稍後再試。"
                _reply_with_welcome(reply_token, text, access_token, welcome)
                continue
            try:
                line_bot.show_loading_animation(source, access_token, loading_seconds=25)
            except Exception:
                logging.exception("LINE loading animation failed; continuing without it")
            if message_type == "text" and inference_hub.looks_like_reminder_request(incoming_text):
                try:
                    text = reminders.handle(
                        incoming_text,
                        str(source.get("userId", "")),
                        history=[] if line_bot.is_group_source(source) else history,
                    ) or "目前無法辨識提醒指令。"
                except (ValueError, RuntimeError) as exc:
                    logging.warning("LINE reminder command rejected: %s", exc)
                    text = "提醒內容、時間或 OpenClaw 排程服務暫時無效，請稍後再試。"
                _reply_with_welcome(
                    reply_token, text, access_token, welcome
                )
                try:
                    store.add_line_memory(conversation_id, "user", incoming_text)
                    store.add_line_memory(conversation_id, "assistant", text)
                except Exception:
                    logging.exception("LINE memory write failed; reminder reply was delivered")
                continue
            image_intent = (
                line_bot.image_request_intent(incoming_text, history)
                if message_type == "text"
                else "chat"
            )
            if image_intent == "image_generate":
                try:
                    try:
                        _push_image_processing_notice(
                            source, str(event.get("webhookEventId", "")), access_token
                        )
                    except Exception:
                        logging.exception("LINE image processing notice failed; continuing")
                    generated, generated_type = inference_hub.generate_image(incoming_text)
                    original_url, preview_url = store.upload_line_generated_image(
                        generated, generated_type
                    )
                    text = "🎨 小羽已完成圖片。"
                    line_bot.reply_image(
                        reply_token, text, original_url, preview_url, access_token
                    )
                    try:
                        store.add_line_memory(conversation_id, "user", incoming_text)
                        store.add_line_memory(conversation_id, "assistant", text)
                    except Exception:
                        logging.exception("LINE memory write failed; generated image was still delivered")
                except Exception:
                    logging.exception("LINE text-to-image generation failed")
                    line_bot.reply(
                        reply_token,
                        "影像產生服務目前暫時失敗，請稍後再試一次。",
                        access_token,
                    )
                continue
            if image_intent == "image_edit":
                if line_bot.should_edit_recent_image(incoming_text, history):
                    try:
                        recent_image_data_url = store.load_line_recent_image(image_context_id)
                    except Exception:
                        logging.exception("LINE recent image read failed for image edit")
                        recent_image_data_url = ""
                    if recent_image_data_url:
                        try:
                            try:
                                _push_image_processing_notice(
                                    source, str(event.get("webhookEventId", "")), access_token
                                )
                            except Exception:
                                logging.exception("LINE image processing notice failed; continuing")
                            generated, generated_type = inference_hub.edit_image(
                                recent_image_data_url, incoming_text
                            )
                            original_url, preview_url = store.upload_line_generated_image(
                                generated, generated_type
                            )
                            text = "🎨 小羽已依照最近一張照片完成修改。"
                            line_bot.reply_image(
                                reply_token, text, original_url, preview_url, access_token
                            )
                            try:
                                store.add_line_memory(
                                    conversation_id,
                                    "user",
                                    f"[使用者要求修改最近圖片] {incoming_text}",
                                )
                                store.add_line_memory(conversation_id, "assistant", text)
                            except Exception:
                                logging.exception(
                                    "LINE memory write failed; recent image edit was delivered"
                                )
                        except Exception:
                            logging.exception("LINE recent image edit failed")
                            line_bot.reply(
                                reply_token,
                                "影像修改服務目前暫時失敗，請稍後再試一次。",
                                access_token,
                            )
                        continue
                text = "請傳送要修改的圖片；收到後小羽會依照這項要求處理。"
                _reply_with_welcome(
                    reply_token, text, access_token, welcome
                )
                try:
                    store.add_line_memory(
                        conversation_id, "user", f"[待處理圖片編輯] {incoming_text}"
                    )
                    store.add_line_memory(conversation_id, "assistant", text)
                except Exception:
                    logging.exception("LINE memory write failed; image edit request was acknowledged")
                continue
            display_name = ""
            if line_bot.needs_profile(incoming_text):
                display_name = line_bot.get_display_name(str(source.get("userId", "")), access_token)
            if message_type == "file":
                file_name = str(message.get("fileName", "document.pdf"))[:120]
                text = summarize_line_pdf_message(message, access_token)
                line_bot.reply(reply_token, text, access_token)
                try:
                    store.add_line_memory(conversation_id, "user", f"[使用者傳送 PDF：{file_name}]")
                    store.add_line_memory(conversation_id, "assistant", text)
                except Exception:
                    logging.exception("LINE memory write failed; PDF reply was still delivered")
                continue
            image_data_url = ""
            memory_text = incoming_text
            if message_type == "text" and line_bot.references_recent_image(incoming_text, history):
                try:
                    image_data_url = store.load_line_recent_image(image_context_id)
                except Exception:
                    logging.exception("LINE recent image read failed")
                    image_data_url = ""
                if image_data_url:
                    image_data_url = line_bot.focus_recent_image_region(
                        image_data_url, incoming_text
                    )
                    if not line_bot.image_question_needs_detail(incoming_text):
                        image_data_url = line_bot.prepare_data_url_for_vlm(image_data_url)
                    incoming_text = line_bot.recent_image_question_prompt(incoming_text)
                else:
                    text = "最近一張圖片已不存在或超過 24 小時，請重新傳送圖片。"
                    _reply_with_welcome(
                        reply_token, text, access_token, welcome
                    )
                    try:
                        store.add_line_memory(conversation_id, "user", memory_text)
                        store.add_line_memory(conversation_id, "assistant", text)
                    except Exception:
                        logging.exception("LINE memory write failed; missing-image reply was delivered")
                    continue
            if message_type == "image":
                original_image_data_url, image_data_url = line_bot.get_message_image_pair(
                    str(message.get("id", "")), access_token
                )
                try:
                    store.save_line_recent_image(image_context_id, original_image_data_url)
                except Exception:
                    logging.exception("LINE recent image save failed; continuing with current image")
                edit_request = line_bot.history_image_edit_request(history)
                if edit_request:
                    try:
                        try:
                            _push_image_processing_notice(
                                source, str(event.get("webhookEventId", "")), access_token
                            )
                        except Exception:
                            logging.exception("LINE image processing notice failed; continuing")
                        generated, generated_type = inference_hub.edit_image(
                            image_data_url, edit_request
                        )
                        original_url, preview_url = store.upload_line_generated_image(
                            generated, generated_type
                        )
                        text = "🎨 小羽已依照你的要求完成圖片。"
                        line_bot.reply_image(
                            reply_token, text, original_url, preview_url, access_token
                        )
                        try:
                            store.add_line_memory(
                                conversation_id, "user", "[使用者傳送一張圖片，要求影像生成／編輯]"
                            )
                            store.add_line_memory(conversation_id, "assistant", text)
                        except Exception:
                            logging.exception("LINE memory write failed; generated image was still delivered")
                    except Exception:
                        logging.exception("LINE image generation failed")
                        line_bot.reply(
                            reply_token,
                            "影像產生服務目前暫時失敗，請稍後再傳一次圖片。",
                            access_token,
                        )
                    continue
                ocr_requested = line_bot.history_requests_image_ocr(history)
                incoming_text = line_bot.image_prompt(history)
                if ocr_requested:
                    image_data_url = original_image_data_url
                    memory_text = "[使用者傳送一張圖片，明確要求 OCR]"
                else:
                    memory_text = "[使用者傳送一張圖片，要求一般圖片理解]"
            text = line_bot.answer(
                incoming_text,
                store.read_state(),
                display_name,
                history=history,
                image_data_url=image_data_url,
            )
            _reply_with_welcome(
                reply_token, text, access_token, welcome
            )
            try:
                store.add_line_memory(conversation_id, "user", memory_text)
                store.add_line_memory(conversation_id, "assistant", text)
            except Exception:
                logging.exception("LINE memory write failed; reply was still delivered")
        except Exception:
            logging.exception("LINE message processing failed")
            # A 200 response prevents LINE from repeatedly redelivering a message whose
            # reply failed after the webhook itself was validated successfully.
    return json_response({"ok": True})


@app.route(route="line-reminders-dispatch", methods=["POST"])
def line_reminders_dispatch(req: func.HttpRequest) -> func.HttpResponse:
    """Lease due reminders and deliver idempotent LINE Push messages."""
    candidate = req.headers.get("x-line-reminder-token", "").strip()
    callback_candidate = req.headers.get("x-line-openclaw-token", "").strip()
    callback_ok = inference_hub.openclaw_callback_token_matches(callback_candidate)
    if not inference_hub.reminder_dispatch_token_matches(candidate) and not callback_ok:
        return json_response({"error": "unauthorized"}, 401)
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not access_token:
        return json_response({"error": "LINE 尚未完成設定"}, 503)
    try:
        claimed = store.claim_due_line_reminders(limit=20)
    except Exception:
        logging.exception("LINE reminder claim failed")
        return json_response({"error": "reminder storage unavailable"}, 503)

    sent = 0
    failed = 0
    for row in claimed:
        try:
            line_bot.push_text(
                row["targetId"], reminders.notification_text(row), access_token,
                retry_key=row["id"],
            )
            store.finish_line_reminder(row, sent=True)
            sent += 1
        except Exception as exc:
            logging.exception("LINE reminder push failed id=%s", row.get("shortId"))
            try:
                store.finish_line_reminder(row, sent=False, error_message=str(exc))
            except Exception:
                logging.exception("LINE reminder failure state update failed")
            failed += 1
    return json_response({"ok": True, "claimed": len(claimed), "sent": sent, "failed": failed})


@app.route(route="line-openclaw-callback", methods=["POST"])
def line_openclaw_callback(req: func.HttpRequest) -> func.HttpResponse:
    """Receive one authenticated long-task completion and Push it to its owner."""
    supplied = req.headers.get("x-line-openclaw-token", "").strip()
    if not inference_hub.openclaw_callback_token_matches(supplied):
        return json_response({"error": "unauthorized"}, 401)
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not access_token:
        return json_response({"error": "LINE 尚未完成設定"}, 503)
    try:
        body = read_body(req)
        task_id = str(body.get("taskId", ""))
        row = store.get_line_openclaw_task(task_id)
        if not row:
            return json_response({"error": "unknown task"}, 404)
        status = str(body.get("status", "failed"))
        result_text = str(body.get("text", "任務沒有輸出"))[:4500]
        prefix = "✅ OpenClaw 任務完成" if status == "completed" else "⚠️ OpenClaw 任務失敗"
        digest = news_digest.validate(body.get("newsDigest")) if status == "completed" else None
        snapshot = (
            market_snapshot.validate(body.get("marketSnapshot"))
            if status == "completed" else None
        )
        artifacts = _openclaw_artifacts(body) if status == "completed" else []
        image_urls = _openclaw_image_urls(body.get("imageUrls")) if status == "completed" else []
        if artifacts:
            try:
                if all(item["contentType"] in {"image/jpeg", "image/png", "image/webp"} for item in artifacts):
                    image_pairs = [
                        store.upload_line_generated_image(item["raw"], item["contentType"])
                        for item in artifacts
                    ]
                    line_bot.push_images(
                        str(row.get("targetId", "")), task_id, image_pairs,
                        f"{prefix} {task_id[:8]}\n\n{result_text}", access_token,
                    )
                else:
                    artifact = artifacts[0]
                    download_url = store.upload_line_artifact(
                        artifact["raw"], artifact["name"], artifact["contentType"]
                    )
                    line_bot.push_artifact(
                        str(row.get("targetId", "")), task_id, artifact["name"], download_url,
                        artifact["size"], result_text, access_token,
                    )
            except Exception:
                logging.exception("LINE OpenClaw artifact delivery failed")
                line_bot.push_text(
                    str(row.get("targetId", "")),
                    f"{prefix} {task_id[:8]}\n\n{result_text}\n\n檔案上傳失敗，請重新執行任務。",
                    access_token, retry_key=task_id,
                )
        elif image_urls:
            delivered_images: list[tuple[str, str]] = []
            for image_url in image_urls:
                try:
                    image_raw, image_type = remote_image.fetch_public_image(image_url)
                    delivered_images.append(store.upload_line_generated_image(image_raw, image_type))
                except Exception:
                    logging.exception("OpenClaw remote image rejected url=%s", image_url[:200])
            if delivered_images:
                line_bot.push_images(
                    str(row.get("targetId", "")), task_id, delivered_images,
                    f"{prefix} {task_id[:8]}\n\n{result_text}", access_token,
                )
            else:
                line_bot.push_text(
                    str(row.get("targetId", "")),
                    f"{prefix} {task_id[:8]}\n\n{result_text}\n\n圖片暫時無法下載，請稍後再試。",
                    access_token, retry_key=task_id,
                )
        elif snapshot:
            store.save_line_openclaw_market_snapshot(task_id, snapshot)
            try:
                chart_url = ""
                chart_png = market_snapshot.render_price_chart(snapshot)
                if chart_png:
                    chart_url, _ = store.upload_line_generated_image(chart_png, "image/png")
                line_bot.push_market_snapshot(
                    str(row.get("targetId", "")), task_id, snapshot, access_token,
                    chart_url=chart_url,
                )
            except Exception:
                logging.exception("LINE Flex market snapshot failed; falling back to text")
                line_bot.push_text(
                    str(row.get("targetId", "")),
                    market_snapshot.fallback_text(snapshot), access_token,
                )
        elif digest:
            store.save_line_openclaw_news_digest(task_id, digest)
            try:
                line_bot.push_news_digest(
                    str(row.get("targetId", "")), task_id, digest, access_token
                )
            except Exception:
                logging.exception("LINE Flex news digest failed; falling back to text")
                line_bot.push_text(
                    str(row.get("targetId", "")), news_digest.fallback_text(digest), access_token
                )
        else:
            line_bot.push_text(
                str(row.get("targetId", "")),
                f"{prefix} {task_id[:8]}\n\n{result_text}",
                access_token,
                retry_key=task_id,
            )
        store.finish_line_openclaw_task(task_id, status)
        return json_response({"ok": True})
    except ValueError:
        return json_response({"error": "invalid body"}, 400)
    except Exception:
        logging.exception("LINE OpenClaw completion callback failed")
        return json_response({"error": "callback failed"}, 502)


@app.route(route="line-openclaw-daily-dispatch", methods=["POST"])
def line_openclaw_daily_dispatch(req: func.HttpRequest) -> func.HttpResponse:
    """Create one owner-only OpenClaw weather/news task from the cam cron job."""
    supplied = req.headers.get("x-line-openclaw-token", "").strip()
    if not inference_hub.openclaw_callback_token_matches(supplied):
        return json_response({"error": "unauthorized"}, 401)
    try:
        body = read_body(req)
        if body.get("kind") != "daily-briefing":
            return json_response({"error": "invalid kind"}, 400)
        owner_id = inference_hub._setting("LINE_OWNER_USER_ID").strip()
        if not owner_id or not line_openclaw.configured():
            return json_response({"error": "daily dispatch is not configured"}, 503)
        scheduled_date = str(body.get("scheduledDate", "")).strip()
        if not scheduled_date:
            scheduled_date = datetime.now(TAIPEI).date().isoformat()
        try:
            datetime.strptime(scheduled_date, "%Y-%m-%d")
        except ValueError:
            return json_response({"error": "invalid scheduled date"}, 400)
        task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"rocketai-owner-daily:{scheduled_date}"))
        existing = store.get_line_openclaw_task(task_id)
        if existing:
            return json_response({
                "ok": True, "taskId": task_id,
                "status": str(existing.get("status", "accepted")), "duplicate": True,
            })
        prompt = f"排程日期：{scheduled_date}（Asia/Taipei）。\n\n{DAILY_OPENCLAW_PROMPT}"
        store.create_line_openclaw_task(task_id, owner_id, prompt)
        line_openclaw.submit_task(owner_id, prompt, task_id=task_id)
        return json_response({"ok": True, "taskId": task_id, "status": "accepted"}, 202)
    except Exception:
        logging.exception("Scheduled OpenClaw daily briefing dispatch failed")
        return json_response({"error": "daily dispatch failed"}, 502)


@app.route(route="line-inference-smoke", methods=["POST"])
def line_inference_smoke(req: func.HttpRequest) -> func.HttpResponse:
    """Exercise Azure -> Funnel -> Hub using a fixed prompt and no user-controlled content."""
    # Static Web Apps reserves Authorization for its own authentication layer, so use a
    # narrowly scoped custom header for this fixed diagnostic route.
    candidate = req.headers.get("x-line-inference-smoke-token", "").strip()
    if not inference_hub.token_matches(candidate):
        return json_response({"error": "unauthorized"}, 401)
    if not inference_hub.configured():
        return json_response({"error": "Inference Hub is not configured"}, 503)

    reply = inference_hub.generate_reply("請只回答 AZURE_HUB_OK", {})
    if not reply:
        return json_response({"error": "Inference Hub request failed"}, 502)
    return json_response({"ok": True, "reply": reply})


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
    # no-cache, not no-store: the browser must keep a copy to revalidate against, or it
    # aborts the 304 because there is nothing to revalidate.
    revalidate = {"ETag": etag, "Cache-Control": "no-cache"}
    if req.headers.get("If-None-Match") == etag:
        return func.HttpResponse(status_code=304, headers=revalidate)
    return func.HttpResponse(
        payload,
        status_code=200,
        mimetype=JSON_CONTENT_TYPE,
        headers={**revalidate, "Content-Type": JSON_CONTENT_TYPE},
    )


@app.route(route="live-state", methods=["POST"])
def publish_state(req: func.HttpRequest) -> func.HttpResponse:
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
