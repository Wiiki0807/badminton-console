"""Validation and rendering helpers for structured OpenClaw market snapshots."""
from __future__ import annotations

import math
import re
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont


MAX_QUOTES = 30


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
        quote_date = _text(raw.get("date"), 20)
        if quote_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", quote_date):
            quote_date = ""
        quote = {
            "date": quote_date,
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
        "chartRequested": value.get("chartRequested") is True,
        "quotes": quotes,
    }


def render_price_chart(snapshot: dict[str, Any]) -> bytes | None:
    """Render validated dated quotes into a LINE-friendly PNG line chart."""
    if snapshot.get("chartRequested") is not True:
        return None
    dated = [
        quote for quote in snapshot.get("quotes", [])
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(quote.get("date", "")))
    ]
    dates = sorted({str(quote["date"]) for quote in dated})
    if len(dates) < 2:
        return None
    series: dict[str, dict[str, float]] = {}
    for quote in dated:
        series.setdefault(str(quote["symbol"]), {})[str(quote["date"])] = float(quote["price"])
    series = {symbol: points for symbol, points in series.items() if len(points) >= 2}
    if not series:
        return None
    prices = [price for points in series.values() for price in points.values()]
    low, high = min(prices), max(prices)
    padding = max((high - low) * 0.12, max(abs(high), 1.0) * 0.01)
    low -= padding
    high += padding

    width, height = 1000, 540
    left, top, right, bottom = 105, 75, 45, 95
    chart_w, chart_h = width - left - right, height - top - bottom
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 24)
        small = ImageFont.truetype("DejaVuSans.ttf", 18)
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 30)
    except OSError:
        font = small = title_font = ImageFont.load_default()
    symbols = ", ".join(series)
    draw.text((left, 24), f"{symbols} price trend", fill="#202124", font=title_font)
    for step in range(5):
        ratio = step / 4
        y = top + chart_h * ratio
        value = high - (high - low) * ratio
        draw.line((left, y, width - right, y), fill="#E2E6EA", width=2)
        draw.text((12, y - 11), f"{value:,.2f}", fill="#5F6368", font=small)
    for index, date in enumerate(dates):
        x = left + (chart_w * index / max(1, len(dates) - 1))
        draw.text((x - 28, height - bottom + 18), date[5:], fill="#5F6368", font=small)
    palette = ["#2E7D32", "#1565C0", "#D32F2F", "#7B1FA2", "#EF6C00"]
    for series_index, (symbol, points) in enumerate(series.items()):
        color = palette[series_index % len(palette)]
        coordinates = []
        for index, date in enumerate(dates):
            if date not in points:
                continue
            x = left + (chart_w * index / max(1, len(dates) - 1))
            y = top + (high - points[date]) / (high - low) * chart_h
            coordinates.append((x, y))
        if len(coordinates) >= 2:
            draw.line(coordinates, fill=color, width=6, joint="curve")
            for x, y in coordinates:
                draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline="white", width=2)
        legend_x = left + series_index * 170
        draw.line((legend_x, height - 30, legend_x + 36, height - 30), fill=color, width=6)
        draw.text((legend_x + 45, height - 42), symbol, fill="#202124", font=font)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _money(value: float, currency: str) -> str:
    prefix = "$" if currency == "USD" else f"{currency} "
    return f"{prefix}{value:,.2f}"


def fallback_text(snapshot: dict[str, Any]) -> str:
    lines = [snapshot["title"]]
    if snapshot.get("asOf"):
        lines.append(f"資料時間：{snapshot['asOf']}")
    for quote in snapshot["quotes"]:
        arrow = "▲" if quote["changePercent"] > 0 else "▼" if quote["changePercent"] < 0 else "—"
        label = quote.get("date") or quote["symbol"]
        lines.append(
            f"{label}  {_money(quote['price'], quote['currency'])}  "
            f"{arrow} {abs(quote['changePercent']):.2f}%"
        )
    return "\n".join(lines)[:4500]


def detail_text(snapshot: dict[str, Any]) -> str:
    lines = [f"📈 {snapshot['title']}"]
    if snapshot.get("asOf"):
        lines.append(f"資料時間：{snapshot['asOf']}")
    for quote in snapshot["quotes"]:
        lines.extend(["", f"{quote['name'] or quote['symbol']}（{quote['symbol']}）"])
        if quote.get("date"):
            lines.append(f"交易日：{quote['date']}")
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
