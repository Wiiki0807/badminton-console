"""Validation and rendering helpers for structured OpenClaw market snapshots."""
from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import urlparse


MAX_QUOTES = 8


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        candidate = value.strip().replace(",", "").replace("$", "")
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", candidate):
            return None
        value = candidate
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and abs(number) < 1e15 else None


def _https_url(value: Any) -> str:
    candidate = str(value or "").strip()[:1500]
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return candidate


def validate(value: Any) -> dict[str, Any] | None:
    """Validate an untrusted callback payload and return a bounded snapshot."""
    if not isinstance(value, dict) or value.get("type") != "market_snapshot":
        return None
    quotes: list[dict[str, Any]] = []
    for raw in (value.get("quotes") or [])[:MAX_QUOTES]:
        if not isinstance(raw, dict):
            continue
        symbol = _text(raw.get("symbol"), 12).upper()
        price = _number(raw.get("price"))
        change = _number(raw.get("change"))
        percent = _number(raw.get("changePercent"))
        source_url = _https_url(raw.get("sourceUrl"))
        if not re.fullmatch(r"[A-Z0-9.-]{1,12}", symbol) or price is None or price < 0:
            continue
        if change is None or percent is None or not source_url:
            continue
        quote = {
            "name": _text(raw.get("name"), 50),
            "symbol": symbol,
            "price": price,
            "change": change,
            "changePercent": percent,
            "currency": _text(raw.get("currency") or "USD", 8).upper(),
            "open": _number(raw.get("open")),
            "high": _number(raw.get("high")),
            "low": _number(raw.get("low")),
            "volume": _number(raw.get("volume")),
            "sourceUrl": source_url,
        }
        quotes.append(quote)
    if not quotes:
        return None
    return {
        "type": "market_snapshot",
        "title": _text(value.get("title") or "市場報價", 60),
        "market": _text(value.get("market"), 30),
        "asOf": _text(value.get("asOf"), 80),
        "session": _text(value.get("session"), 30),
        "quotes": quotes,
    }


def _money(value: float, currency: str) -> str:
    prefix = "$" if currency == "USD" else f"{currency} "
    return f"{prefix}{value:,.2f}"


def fallback_text(snapshot: dict[str, Any]) -> str:
    lines = [snapshot["title"]]
    if snapshot.get("asOf"):
        lines.append(f"資料時間：{snapshot['asOf']}")
    for quote in snapshot["quotes"]:
        arrow = "▲" if quote["changePercent"] > 0 else "▼" if quote["changePercent"] < 0 else "—"
        lines.append(
            f"{quote['symbol']}  {_money(quote['price'], quote['currency'])}  "
            f"{arrow} {abs(quote['changePercent']):.2f}%"
        )
    return "\n".join(lines)[:4500]


def detail_text(snapshot: dict[str, Any]) -> str:
    lines = [f"📈 {snapshot['title']}"]
    if snapshot.get("asOf"):
        lines.append(f"資料時間：{snapshot['asOf']}")
    for quote in snapshot["quotes"]:
        lines.extend(["", f"{quote['name'] or quote['symbol']}（{quote['symbol']}）"])
        lines.append(f"價格：{_money(quote['price'], quote['currency'])}")
        lines.append(f"漲跌：{quote['change']:+,.2f}（{quote['changePercent']:+.2f}%）")
        if quote.get("open") is not None:
            lines.append(f"開盤：{_money(quote['open'], quote['currency'])}")
        if quote.get("high") is not None and quote.get("low") is not None:
            lines.append(
                f"區間：{_money(quote['low'], quote['currency'])}–"
                f"{_money(quote['high'], quote['currency'])}"
            )
        if quote.get("volume") is not None:
            lines.append(f"成交量：{quote['volume']:,.0f}")
        lines.append(quote["sourceUrl"])
    return "\n".join(lines)[:5000]
