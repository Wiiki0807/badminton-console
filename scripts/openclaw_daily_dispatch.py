#!/usr/bin/env python3
"""Trigger the owner-only Azure/OpenClaw daily briefing without exposing secrets."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import urllib.request
from zoneinfo import ZoneInfo


parser = argparse.ArgumentParser()
parser.add_argument("url")
args = parser.parse_args()

settings: dict[str, str] = {}
try:
    for raw in Path("/home/tommywu/.openclaw/.env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            settings[key.strip()] = value.strip()
except OSError:
    pass

prefix = settings.get("OPENCLAW_LINE_CALLBACK_URL_PREFIX") or os.environ.get(
    "OPENCLAW_LINE_CALLBACK_URL_PREFIX", ""
)
token = settings.get("OPENCLAW_LINE_CALLBACK_TOKEN") or os.environ.get(
    "OPENCLAW_LINE_CALLBACK_TOKEN", ""
)
if not prefix.startswith("https://") or not args.url.startswith(prefix) or not token:
    raise SystemExit("daily callback configuration rejected")

payload = {
    "source": "openclaw-cron",
    "kind": "daily-briefing",
    "scheduledDate": datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat(),
}
request = urllib.request.Request(
    args.url,
    data=json.dumps(payload).encode("utf-8"),
    method="POST",
    headers={
        "x-line-openclaw-token": token,
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(request, timeout=30) as response:
    body = response.read().decode("utf-8", errors="replace")
    if response.status not in {200, 202}:
        raise SystemExit(f"daily dispatch failed HTTP {response.status}")
print(body[:1000])
