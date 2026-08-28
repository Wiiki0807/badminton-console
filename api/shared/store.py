"""Blob + Table storage layer, replacing the JSON files used by the retired server.py."""
from __future__ import annotations

import json
import base64
import hashlib
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from itertools import islice
from typing import Any

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.data.tables import EntityProperty, EdmType, TableClient, UpdateMode
from azure.storage.blob import (
    BlobClient,
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)
from PIL import Image, ImageOps

CONTAINER = "live"
STATE_BLOB = "state.json"
PARTITION = "default"
MAX_ITEMS = 80
ALLOWED_REACTIONS = ("👍", "🔥", "🏸", "👏")
WISH_COSTS = {"partner": 3, "opponent": 4, "mixed": 3, "boss": 5}
EMPTY_STATE = {"courts": [], "recent": [], "stats": []}
LINE_MEMORY_TABLE = "lineMemory"
LINE_WEBHOOK_TABLE = "lineWebhookEvents"
LINE_REMINDER_TABLE = "lineReminders"
LINE_MEMORY_MAX_MESSAGES = 12
LINE_MEMORY_RETENTION_MS = 7 * 24 * 60 * 60 * 1000
LINE_GENERATED_PREFIX = "line-generated/"
LINE_RECENT_IMAGE_PREFIX = "line-recent-image/"
LINE_RECENT_IMAGE_RETENTION = timedelta(hours=24)
MAX_LINE_RECENT_IMAGE_BYTES = 6 * 1024 * 1024
LINE_REMINDER_MAX_PENDING = 50
LINE_REMINDER_MAX_FUTURE_MS = 5 * 365 * 24 * 60 * 60 * 1000

# RowKey sorts newest-first so a plain top-N query returns the most recent rows.
_MAX_TICKS = 9_999_999_999_999


def _connection_string() -> str:
    value = os.environ.get("STORAGE_CONNECTION_STRING")
    if not value:
        raise RuntimeError("STORAGE_CONNECTION_STRING is not configured")
    return value


def _table(name: str) -> TableClient:
    client = TableClient.from_connection_string(_connection_string(), table_name=name)
    try:
        client.create_table()
    except ResourceExistsError:
        pass
    return client


def _blob() -> BlobClient:
    return BlobClient.from_connection_string(_connection_string(), container_name=CONTAINER, blob_name=STATE_BLOB)


def now_ms() -> int:
    return int(time.time() * 1000)


def _epoch(value: int) -> EntityProperty:
    """Table Storage defaults ints to Edm.Int32, which millisecond timestamps overflow."""
    return EntityProperty(value, EdmType.INT64)


def _as_int(value: Any) -> int:
    if isinstance(value, EntityProperty):
        value = value.value
    return int(value or 0)


def new_row_key() -> str:
    return f"{_MAX_TICKS - now_ms():013d}-{uuid.uuid4().hex}"


def read_state() -> dict[str, Any]:
    try:
        return json.loads(_blob().download_blob().readall().decode("utf-8"))
    except (ResourceNotFoundError, json.JSONDecodeError):
        return dict(EMPTY_STATE)


def write_state(value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
    _blob().upload_blob(payload, overwrite=True)


def _comment_from_entity(entity: Any) -> dict[str, Any]:
    try:
        reactions = json.loads(entity.get("reactionsJson") or "{}")
    except json.JSONDecodeError:
        reactions = {}
    return {
        "id": entity["RowKey"],
        "name": entity.get("name", ""),
        "message": entity.get("message", ""),
        "matchId": entity.get("matchId", ""),
        "matchLabel": entity.get("matchLabel", ""),
        "createdAt": _as_int(entity.get("createdAt")),
        "reactions": reactions,
    }


def _wish_from_entity(entity: Any) -> dict[str, Any]:
    wish = {
        "id": entity["RowKey"],
        "playerName": entity.get("playerName", ""),
        "type": entity.get("type", ""),
        "target": entity.get("target", ""),
        "cost": _as_int(entity.get("cost")),
        "status": entity.get("status", "pending"),
        "createdAt": _as_int(entity.get("createdAt")),
    }
    if entity.get("updatedAt"):
        wish["updatedAt"] = _as_int(entity["updatedAt"])
    return wish


def _list_recent(table_name: str, mapper) -> list[dict[str, Any]]:
    with _table(table_name) as table:
        query = table.query_entities(f"PartitionKey eq '{PARTITION}'", results_per_page=MAX_ITEMS)
        rows = list(islice(query, MAX_ITEMS))
    # Callers and the existing front end expect oldest-first, matching the old JSON files.
    return [mapper(row) for row in reversed(rows)]


def list_comments() -> list[dict[str, Any]]:
    return _list_recent("comments", _comment_from_entity)


def list_wishes() -> list[dict[str, Any]]:
    return _list_recent("wishes", _wish_from_entity)


def add_comment(name: str, message: str, match_id: str, match_label: str) -> dict[str, Any]:
    entity = {
        "PartitionKey": PARTITION,
        "RowKey": new_row_key(),
        "name": name,
        "message": message,
        "matchId": match_id,
        "matchLabel": match_label,
        "createdAt": _epoch(now_ms()),
        "reactionsJson": "{}",
    }
    with _table("comments") as table:
        table.create_entity(entity)
    return _comment_from_entity(entity)


def add_wish(player_name: str, wish_type: str, target: str) -> dict[str, Any]:
    entity = {
        "PartitionKey": PARTITION,
        "RowKey": new_row_key(),
        "playerName": player_name,
        "type": wish_type,
        "target": target,
        "cost": WISH_COSTS[wish_type],
        "status": "pending",
        "createdAt": _epoch(now_ms()),
    }
    with _table("wishes") as table:
        table.create_entity(entity)
    return _wish_from_entity(entity)


def set_wish_status(wish_id: str, status: str) -> dict[str, Any] | None:
    with _table("wishes") as table:
        try:
            entity = table.get_entity(PARTITION, wish_id)
        except ResourceNotFoundError:
            return None
        entity["status"] = status
        entity["updatedAt"] = _epoch(now_ms())
        table.update_entity(entity, mode=UpdateMode.MERGE)
    return _wish_from_entity(entity)


def add_reaction(comment_id: str, emoji: str) -> dict[str, Any] | None:
    with _table("comments") as table:
        for _ in range(4):
            try:
                entity = table.get_entity(PARTITION, comment_id)
            except ResourceNotFoundError:
                return None
            try:
                reactions = json.loads(entity.get("reactionsJson") or "{}")
            except json.JSONDecodeError:
                reactions = {}
            reactions[emoji] = int(reactions.get(emoji, 0)) + 1
            entity["reactionsJson"] = json.dumps(reactions, ensure_ascii=False)
            try:
                table.update_entity(
                    entity,
                    mode=UpdateMode.MERGE,
                    etag=entity.metadata["etag"],
                    match_condition=MatchConditions.IfNotModified,
                )
                return _comment_from_entity(entity)
            except ResourceModifiedError:
                continue
    return None


def _memory_partition(conversation_id: str) -> str:
    """Pseudonymize LINE identifiers before using them as storage keys."""
    return hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()


def list_line_memory(conversation_id: str) -> list[dict[str, str]]:
    if not conversation_id:
        return []
    partition = _memory_partition(conversation_id)
    cutoff = now_ms() - LINE_MEMORY_RETENTION_MS
    with _table(LINE_MEMORY_TABLE) as table:
        query = table.query_entities(
            f"PartitionKey eq '{partition}'", results_per_page=LINE_MEMORY_MAX_MESSAGES * 3
        )
        rows = list(islice(query, LINE_MEMORY_MAX_MESSAGES * 3))
    recent = [row for row in rows if _as_int(row.get("createdAt")) >= cutoff]
    return [
        {"role": str(row.get("role", "")), "content": str(row.get("content", ""))}
        for row in reversed(recent[:LINE_MEMORY_MAX_MESSAGES])
        if row.get("role") in {"user", "assistant"} and row.get("content")
    ]


def add_line_memory(conversation_id: str, role: str, content: str) -> None:
    if not conversation_id or role not in {"user", "assistant"} or not content.strip():
        return
    entity = {
        "PartitionKey": _memory_partition(conversation_id),
        "RowKey": new_row_key(),
        "role": role,
        "content": content.strip()[:4500],
        "createdAt": _epoch(now_ms()),
    }
    with _table(LINE_MEMORY_TABLE) as table:
        table.create_entity(entity)


def clear_line_memory(conversation_id: str) -> None:
    if not conversation_id:
        return
    partition = _memory_partition(conversation_id)
    with _table(LINE_MEMORY_TABLE) as table:
        rows = table.query_entities(f"PartitionKey eq '{partition}'", select=["PartitionKey", "RowKey"])
        for row in rows:
            table.delete_entity(row["PartitionKey"], row["RowKey"])


def claim_line_webhook_event(event_id: str) -> bool:
    """Atomically claim a LINE event so webhook redelivery cannot run it twice."""
    bounded = str(event_id or "").strip()[:200]
    if not bounded:
        return True
    entity = {
        "PartitionKey": PARTITION,
        "RowKey": hashlib.sha256(bounded.encode("utf-8")).hexdigest(),
        "createdAt": _epoch(now_ms()),
    }
    try:
        with _table(LINE_WEBHOOK_TABLE) as table:
            table.create_entity(entity)
        return True
    except ResourceExistsError:
        return False


def _reminder_partition(user_id: str) -> str:
    return hashlib.sha256(f"line-reminder:{user_id}".encode("utf-8")).hexdigest()


def _reminder_from_entity(row: dict[str, Any]) -> dict[str, Any]:
    reminder_id = str(row.get("RowKey", ""))
    return {
        "id": reminder_id,
        "shortId": reminder_id[:6].upper(),
        "title": str(row.get("title", "")),
        "dueAt": _as_int(row.get("dueAt")),
        "status": str(row.get("status", "")),
        "targetId": str(row.get("targetId", "")),
        "attempts": int(row.get("attempts", 0) or 0),
        "PartitionKey": str(row.get("PartitionKey", "")),
        "RowKey": reminder_id,
    }


def list_line_reminders(user_id: str) -> list[dict[str, Any]]:
    if not user_id:
        return []
    partition = _reminder_partition(user_id)
    with _table(LINE_REMINDER_TABLE) as table:
        rows = list(table.query_entities(
            f"PartitionKey eq '{partition}' and status eq 'pending'"
        ))
    pending = [_reminder_from_entity(row) for row in rows]
    return sorted(pending, key=lambda row: (int(row["dueAt"]), row["id"]))


def create_line_reminder(
    user_id: str, target_id: str, title: str, due_at_ms: int
) -> dict[str, Any]:
    bounded_title = " ".join(str(title or "").split())[:1000]
    current = now_ms()
    if not user_id or not target_id or not bounded_title:
        raise ValueError("invalid reminder")
    if due_at_ms <= current or due_at_ms > current + LINE_REMINDER_MAX_FUTURE_MS:
        raise ValueError("invalid reminder time")
    if len(list_line_reminders(user_id)) >= LINE_REMINDER_MAX_PENDING:
        raise ValueError("too many pending reminders")
    entity = {
        "PartitionKey": _reminder_partition(user_id),
        # LINE's retry header requires a UUID; keep the same UUID for every retry.
        "RowKey": str(uuid.uuid4()),
        "title": bounded_title,
        "dueAt": _epoch(due_at_ms),
        "targetId": target_id[:80],
        "timezone": "Asia/Taipei",
        "status": "pending",
        "attempts": 0,
        "leaseUntil": _epoch(0),
        "createdAt": _epoch(current),
        "updatedAt": _epoch(current),
    }
    with _table(LINE_REMINDER_TABLE) as table:
        table.create_entity(entity)
    return _reminder_from_entity(entity)


def _matching_reminders(user_id: str, identifier: str) -> list[dict[str, Any]]:
    rows = list_line_reminders(user_id)
    needle = " ".join(str(identifier or "").strip().split()).casefold()
    if not needle:
        return []
    exact_id = [row for row in rows if row["id"].casefold().startswith(needle)]
    if exact_id:
        return exact_id
    return [row for row in rows if needle in row["title"].casefold()]


def cancel_line_reminder(user_id: str, identifier: str) -> dict[str, Any]:
    if str(identifier).strip().casefold() in {"全部", "all", "所有提醒"}:
        rows = list_line_reminders(user_id)
        with _table(LINE_REMINDER_TABLE) as table:
            for row in rows:
                table.update_entity({
                    "PartitionKey": row["PartitionKey"], "RowKey": row["RowKey"],
                    "status": "cancelled", "updatedAt": _epoch(now_ms()),
                }, mode=UpdateMode.MERGE)
        return {"status": "cancelled_all", "count": len(rows)}
    matches = _matching_reminders(user_id, identifier)
    if not matches:
        return {"status": "not_found"}
    if len(matches) > 1:
        return {"status": "ambiguous", "rows": matches}
    row = matches[0]
    with _table(LINE_REMINDER_TABLE) as table:
        table.update_entity({
            "PartitionKey": row["PartitionKey"], "RowKey": row["RowKey"],
            "status": "cancelled", "updatedAt": _epoch(now_ms()),
        }, mode=UpdateMode.MERGE)
    row["status"] = "cancelled"
    return {"status": "cancelled", "row": row}


def update_line_reminder(
    user_id: str, identifier: str, *, title: str = "", due_at_ms: int = 0
) -> dict[str, Any]:
    matches = _matching_reminders(user_id, identifier)
    if not matches:
        return {"status": "not_found"}
    if len(matches) > 1:
        return {"status": "ambiguous", "rows": matches}
    row = matches[0]
    entity: dict[str, Any] = {
        "PartitionKey": row["PartitionKey"], "RowKey": row["RowKey"],
        "updatedAt": _epoch(now_ms()),
    }
    if title:
        entity["title"] = " ".join(title.split())[:1000]
    if due_at_ms:
        current = now_ms()
        if due_at_ms <= current or due_at_ms > current + LINE_REMINDER_MAX_FUTURE_MS:
            raise ValueError("invalid reminder time")
        entity["dueAt"] = _epoch(due_at_ms)
        entity["leaseUntil"] = _epoch(0)
    if len(entity) == 3:
        raise ValueError("missing reminder update")
    with _table(LINE_REMINDER_TABLE) as table:
        table.update_entity(entity, mode=UpdateMode.MERGE)
    row["title"] = str(entity.get("title", row["title"]))
    row["dueAt"] = due_at_ms or row["dueAt"]
    return {"status": "updated", "row": row}


def claim_due_line_reminders(limit: int = 20) -> list[dict[str, Any]]:
    """Lease due reminders atomically enough for overlapping scheduler invocations."""
    current = now_ms()
    with _table(LINE_REMINDER_TABLE) as table:
        query = table.query_entities(
            f"status eq 'pending' and dueAt le {current}L", results_per_page=max(1, min(limit * 3, 100))
        )
        candidates = list(islice(query, max(1, min(limit * 3, 100))))
        claimed: list[dict[str, Any]] = []
        for row in candidates:
            if len(claimed) >= limit or _as_int(row.get("leaseUntil")) > current:
                continue
            row["leaseUntil"] = _epoch(current + 2 * 60 * 1000)
            row["attempts"] = int(row.get("attempts", 0) or 0) + 1
            row["updatedAt"] = _epoch(current)
            try:
                table.update_entity(
                    row, mode=UpdateMode.MERGE, etag=row.metadata["etag"],
                    match_condition=MatchConditions.IfNotModified,
                )
            except ResourceModifiedError:
                continue
            claimed.append(_reminder_from_entity(row))
        return claimed


def finish_line_reminder(row: dict[str, Any], *, sent: bool, error_message: str = "") -> None:
    entity = {
        "PartitionKey": row["PartitionKey"], "RowKey": row["RowKey"],
        "status": "sent" if sent else "pending",
        "leaseUntil": _epoch(0 if sent else now_ms() + 60 * 1000),
        "updatedAt": _epoch(now_ms()),
        "lastError": "" if sent else str(error_message or "push failed")[:500],
    }
    if sent:
        entity["sentAt"] = _epoch(now_ms())
    with _table(LINE_REMINDER_TABLE) as table:
        table.update_entity(entity, mode=UpdateMode.MERGE)


def _recent_image_blob(conversation_id: str) -> BlobClient:
    digest = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()
    return BlobClient.from_connection_string(
        _connection_string(),
        container_name=CONTAINER,
        blob_name=f"{LINE_RECENT_IMAGE_PREFIX}{digest}",
    )


def save_line_recent_image(conversation_id: str, image_data_url: str) -> None:
    """Privately retain one original LINE image per sender context; next image overwrites it."""
    if not conversation_id:
        return
    match = re.fullmatch(
        r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\r\n]+)",
        image_data_url or "",
    )
    if not match:
        raise ValueError("invalid recent LINE image")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        raise ValueError("invalid recent LINE image base64") from exc
    if not raw or len(raw) > MAX_LINE_RECENT_IMAGE_BYTES:
        raise ValueError("recent LINE image is empty or too large")
    _recent_image_blob(conversation_id).upload_blob(
        raw,
        overwrite=True,
        content_settings=ContentSettings(content_type=match.group(1)),
        metadata={"retentionHours": "24"},
    )


def load_line_recent_image(conversation_id: str) -> str:
    """Return the conversation's private recent image only while it is within retention."""
    if not conversation_id:
        return ""
    blob = _recent_image_blob(conversation_id)
    try:
        properties = blob.get_blob_properties()
        last_modified = properties.last_modified
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last_modified > LINE_RECENT_IMAGE_RETENTION:
            blob.delete_blob()
            return ""
        raw = blob.download_blob().readall()
    except ResourceNotFoundError:
        return ""
    if not raw or len(raw) > MAX_LINE_RECENT_IMAGE_BYTES:
        return ""
    content_type = str(properties.content_settings.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        return ""
    return f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"


def upload_line_generated_image(raw: bytes, content_type: str) -> tuple[str, str]:
    """Upload a generated image plus LINE-sized preview and return one-hour SAS URLs."""
    if content_type not in {"image/png", "image/jpeg"} or not raw:
        raise ValueError("unsupported generated image")
    try:
        with Image.open(BytesIO(raw)) as source:
            preview = ImageOps.exif_transpose(source).convert("RGB")
            preview.thumbnail((512, 512), Image.Resampling.LANCZOS)
            preview_buffer = BytesIO()
            preview.save(preview_buffer, format="JPEG", quality=82, optimize=True)
    except OSError as exc:
        raise ValueError("invalid generated image") from exc

    connection_string = _connection_string()
    settings = {
        key.strip(): value.strip()
        for item in connection_string.split(";") if "=" in item
        for key, value in [item.split("=", 1)]
    }
    account_name = settings.get("AccountName", "")
    account_key = settings.get("AccountKey", "")
    if not account_name or not account_key:
        raise RuntimeError("storage account key is unavailable for LINE image URL")
    service = BlobServiceClient.from_connection_string(connection_string)
    image_id = uuid.uuid4().hex
    extension = "png" if content_type == "image/png" else "jpg"
    original_name = f"{LINE_GENERATED_PREFIX}{image_id}.{extension}"
    preview_name = f"{LINE_GENERATED_PREFIX}{image_id}-preview.jpg"
    original = service.get_blob_client(CONTAINER, original_name)
    preview_blob = service.get_blob_client(CONTAINER, preview_name)
    original.upload_blob(raw, content_settings=ContentSettings(content_type=content_type))
    preview_blob.upload_blob(
        preview_buffer.getvalue(), content_settings=ContentSettings(content_type="image/jpeg")
    )
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    def signed_url(blob_name: str, url: str) -> str:
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=CONTAINER,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )
        return f"{url}?{sas}"

    return signed_url(original_name, original.url), signed_url(preview_name, preview_blob.url)
