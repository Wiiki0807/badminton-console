"""Once-per-day LINE weather and AI news briefing."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import inference_hub, store


TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_LOCATION = "新北市板橋區"
NEWS_QUERIES = (
    "NVIDIA artificial intelligence AI latest news",
    "AI technology robotics humanoid robot latest news",
)


def taipei_date_key(now: datetime | None = None) -> str:
    current = now or datetime.now(TAIPEI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI)
    return current.astimezone(TAIPEI).strftime("%Y-%m-%d")


def _number(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "未知"
    try:
        numeric = float(value)
        rendered = str(int(numeric)) if numeric.is_integer() else f"{numeric:.1f}"
    except (TypeError, ValueError):
        rendered = str(value)
    return rendered + suffix


def _weather_line(location: str) -> str:
    forecast = inference_hub.get_daily_weather_forecast(location)
    place = str(forecast.get("location") or location)
    if location in {"新北市板橋區", "板橋", "板橋區"}:
        place = "板橋"
    return (
        f"🌦️ {place}今日：{forecast.get('weather', '天氣未知')}，"
        f"{_number(forecast.get('temperature_min_c'), '°C')}～"
        f"{_number(forecast.get('temperature_max_c'), '°C')}；"
        f"最高降雨機率 {_number(forecast.get('precipitation_probability_percent'), '%')}，"
        f"預估雨量 {_number(forecast.get('precipitation_mm'), ' mm')}。"
    )


def _search_news(date_key: str) -> list[dict[str, str]]:
    today = date.fromisoformat(date_key)
    start_date = (today - timedelta(days=1)).isoformat()
    end_date = (today + timedelta(days=1)).isoformat()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                inference_hub.search_recent_news,
                query,
                max_results=5,
                start_date=start_date,
                end_date=end_date,
            )
            for query in NEWS_QUERIES
        ]
        groups: list[list[dict[str, str]]] = []
        for future in futures:
            try:
                groups.append(future.result())
            except Exception:
                logging.exception("Daily Tavily news search failed")
                groups.append([])

    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for offset in range(5):
        for group in groups:
            if offset >= len(group):
                continue
            row = group[offset]
            key = str(row.get("url", "")).lower().rstrip("/")
            if not key or key in seen:
                continue
            seen.add(key)
            selected.append(row)
            if len(selected) >= 5:
                return selected
    return selected


def build_today(date_key: str | None = None) -> str:
    """Build a bounded digest; weather and news fail independently."""
    date_key = date_key or taipei_date_key()
    location = inference_hub._setting("DAILY_BRIEFING_LOCATION", DEFAULT_LOCATION)
    sections = [f"☀️ 小羽每日情報｜{date_key[5:].replace('-', '/')}（昨／今）"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        weather_future = executor.submit(_weather_line, location)
        news_future = executor.submit(_search_news, date_key)
        try:
            weather = weather_future.result()
        except Exception:
            logging.exception("Daily weather forecast failed")
            weather = f"🌦️ {location}天氣預報暫時無法取得。"
        try:
            rows = news_future.result()
        except Exception:
            logging.exception("Daily news collection failed")
            rows = []
    sections.append(weather)
    if rows:
        summaries = inference_hub.summarize_recent_news(rows)
        sections.append("\n🗞️ NVIDIA／AI／機器人焦點")
        for index, row in enumerate(rows):
            title = str(row.get("title") or "未命名新聞")[:180]
            fallback = str(row.get("description") or "")[:180]
            summary = summaries.get(index) or fallback or "請開啟來源查看完整內容。"
            sections.append(f"{index + 1}. {title}\n{summary}\n{row['url']}")
    else:
        sections.append("\n🗞️ 今日 AI 新聞搜尋暫時無法取得，稍後可直接問我最新消息。")
    return "\n\n".join(sections)[:4500]


def for_first_message(user_id: str, now: datetime | None = None) -> str:
    """Return the briefing only for this user's first private text message today."""
    date_key = taipei_date_key(now)
    if not store.claim_line_daily_briefing(user_id, date_key):
        return ""
    try:
        cached = store.load_line_daily_briefing(date_key)
        if cached:
            return cached
        content = build_today(date_key)
        store.save_line_daily_briefing(date_key, content)
        return content
    except Exception:
        logging.exception("Daily briefing generation failed")
        try:
            store.release_line_daily_briefing(user_id, date_key)
        except Exception:
            logging.exception("Daily briefing claim release failed")
        return ""
