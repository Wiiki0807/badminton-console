"""Blob + Table storage layer, replacing the JSON files used by the retired server.py."""
from __future__ import annotations

import json
import hashlib
import os
import time
import uuid
from itertools import islice
from typing import Any

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.data.tables import EntityProperty, EdmType, TableClient, UpdateMode
from azure.storage.blob import BlobClient

CONTAINER = "live"
STATE_BLOB = "state.json"
PARTITION = "default"
MAX_ITEMS = 80
ALLOWED_REACTIONS = ("👍", "🔥", "🏸", "👏")
WISH_COSTS = {"partner": 3, "opponent": 4, "mixed": 3, "boss": 5}
EMPTY_STATE = {"courts": [], "recent": [], "stats": []}
LINE_MEMORY_TABLE = "lineMemory"
LINE_MEMORY_MAX_MESSAGES = 12
LINE_MEMORY_RETENTION_MS = 7 * 24 * 60 * 60 * 1000

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
