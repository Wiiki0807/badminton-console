#!/usr/bin/env python3
"""Post OpenClaw scheduled events through an Azure-SWA-safe custom header."""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("kind", choices=["reminder"])
parser.add_argument("url")
args = parser.parse_args()

settings = {}
try:
    for line in Path("/home/tommywu/.openclaw/.env").read_text(encoding="utf-8").splitlines():
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
    raise SystemExit("callback configuration rejected")

request = urllib.request.Request(
    args.url,
    data=json.dumps({"source": "openclaw-cron", "kind": args.kind}).encode(),
    method="POST",
    headers={"x-line-openclaw-token": token, "Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=30) as response:
    body = response.read().decode("utf-8", errors="replace")
    if response.status != 200:
        raise SystemExit(f"callback failed HTTP {response.status}")
print(body[:1000])
