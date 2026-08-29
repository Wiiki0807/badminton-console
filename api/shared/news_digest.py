"""Validation and compact rendering helpers for OpenClaw news digests."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


MAX_ITEMS = 5


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _https_url(value: Any) -> str:
    candidate = str(value or "").strip()[:1500]
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return candidate


def validate(value: Any) -> dict[str, Any] | None:
    """Return a bounded digest or None. Callback payloads are untrusted input."""
    if not isinstance(value, dict) or value.get("type") != "verified_news_digest":
        return None
    items: list[dict[str, Any]] = []
    for raw in (value.get("items") or [])[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        sources = []
        for source in (raw.get("sources") or [])[:3]:
            url = _https_url(source)
            if url and url not in sources:
                sources.append(url)
        title = _text(raw.get("title"), 120)
        summary = _text(raw.get("summary"), 1200)
        if not title or not summary or not sources:
            continue
        items.append({
            "title": title,
            "date": _text(raw.get("date"), 40),
            "shortSummary": _text(raw.get("shortSummary") or summary, 180),
            "summary": summary,
            "importance": _text(raw.get("importance"), 600),
            "confidence": _text(raw.get("confidence"), 20),
            "sources": sources,
        })
    if not items:
        return None
    return {
        "type": "verified_news_digest",
        "title": _text(value.get("title") or "近期新聞摘要", 80),
        "cutoff": _text(value.get("cutoff"), 80),
        "overallTrend": _text(value.get("overallTrend"), 600),
        "watchNext": _text(value.get("watchNext"), 600),
        "items": items,
    }


def fallback_text(digest: dict[str, Any]) -> str:
    lines = [digest["title"]]
    for index, item in enumerate(digest["items"], 1):
        lines.extend([f"{index}. {item['title']}", item["shortSummary"], item["sources"][0]])
    if digest.get("cutoff"):
        lines.append(f"資料截止：{digest['cutoff']}")
    return "\n".join(lines)[:4500]


def detail_text(item: dict[str, Any]) -> str:
    lines = [f"📰 {item['title']}"]
    if item.get("date"):
        lines.append(f"日期：{item['date']}")
    if item.get("confidence"):
        lines.append(f"可信度：{item['confidence']}")
    lines.extend(["", item["summary"]])
    if item.get("importance"):
        lines.extend(["", f"為何重要：{item['importance']}"])
    lines.extend(["", "來源：", *item["sources"]])
    return "\n".join(lines)[:5000]
