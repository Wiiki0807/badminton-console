"""Non-destructive cam smoke test for bridge health and reminder CRUD."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid


def post(path: str, value: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:18890{path}",
        data=json.dumps(value).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {os.environ['OPENCLAW_BRIDGE_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


reminder_id = str(uuid.uuid4())
callback = os.environ["OPENCLAW_LINE_CALLBACK_URL_PREFIX"] + "line-reminders-dispatch"
status, created = post("/v1/reminders", {
    "action": "schedule",
    "reminderId": reminder_id,
    "dueAt": "2030-01-01T00:00:00+08:00",
    "callbackUrl": callback,
})
assert status == 200 and created.get("jobId"), (status, created)
status, removed = post("/v1/reminders", {
    "action": "cancel", "reminderId": reminder_id,
})
assert status == 200 and removed.get("removed") == 1, (status, removed)
status, rejected = post("/v1/tasks", {
    "userId": "U12345678", "text": "smoke test",
    "callbackUrl": os.environ["OPENCLAW_LINE_CALLBACK_URL_PREFIX"] + "line-openclaw-callback",
})
assert status == 403 and rejected.get("error") == "owner only", (status, rejected)
print("OPENCLAW_BRIDGE_SMOKE_OK")
