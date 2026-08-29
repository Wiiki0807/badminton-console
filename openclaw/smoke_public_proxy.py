"""Non-destructive Windows gateway to WSL bridge smoke test."""
from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.request


token = Path(
    r"C:\Nvidia\robot_voice_hub\hub-data\line-chat-gateway-token.txt"
).read_text(encoding="utf-8").strip()
req = urllib.request.Request(
    "http://127.0.0.1:8791/openclaw/v1/tasks",
    data=json.dumps({
        "userId": "U12345678",
        "text": "smoke test",
        "callbackUrl": (
            "https://mango-bay-0083f4c00.7.azurestaticapps.net/"
            "api/line-openclaw-callback"
        ),
    }).encode(),
    method="POST",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
)
try:
    urllib.request.urlopen(req, timeout=15)
    raise AssertionError("unpaired user was unexpectedly accepted")
except urllib.error.HTTPError as exc:
    assert exc.code == 403, exc.code
    assert json.loads(exc.read()).get("error") == "owner only"
print("OPENCLAW_PUBLIC_PROXY_SMOKE_OK")
