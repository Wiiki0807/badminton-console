"""HTTP API for the badminton console, replacing the endpoints previously served by server.py."""
from __future__ import annotations

import hashlib
import json
import logging
import os

import azure.functions as func

from shared import store
from shared import line_bot
from shared import inference_hub
from shared import pdf_summary

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

MAX_BODY_BYTES = 1_000_000
# Browsers assume UTF-8 for JSON, but other clients fall back to ISO-8859-1 without this.
JSON_CONTENT_TYPE = "application/json; charset=utf-8"


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
        message_type = message.get("type")
        if event.get("type") != "message" or message_type not in {"text", "image", "file"} or not reply_token:
            continue
        processing_timer = None
        try:
            source = event.get("source") or {}
            conversation_id = line_bot.conversation_id(source)
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
            if message_type == "text" and line_bot.is_memory_reset(incoming_text):
                store.clear_line_memory(conversation_id)
                line_bot.reply(reply_token, "已清除這個對話最近的記憶。", access_token)
                continue
            processing_timer = line_bot.start_processing_notice(source, access_token)
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
            if message_type == "image":
                image_data_url = line_bot.get_message_image(str(message.get("id", "")), access_token)
                edit_request = line_bot.history_image_edit_request(history)
                if edit_request:
                    try:
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
            line_bot.reply(reply_token, text, access_token)
            try:
                store.add_line_memory(conversation_id, "user", memory_text)
                store.add_line_memory(conversation_id, "assistant", text)
            except Exception:
                logging.exception("LINE memory write failed; reply was still delivered")
        except Exception:
            logging.exception("LINE message processing failed")
            # A 200 response prevents LINE from repeatedly redelivering a message whose
            # reply failed after the webhook itself was validated successfully.
        finally:
            if processing_timer is not None:
                processing_timer.cancel()
    return json_response({"ok": True})


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
