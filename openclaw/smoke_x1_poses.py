#!/usr/bin/env python3
"""Isaac-only solve/play smoke for every LINE X1 Quick Reply pose."""
from __future__ import annotations

import json
import time

import x1_gesture_control as x1


def main() -> None:
    results = []
    for gesture in sorted(x1.SAFE_GESTURES):
        result = x1.play(gesture, real=False)
        results.append({"gesture": gesture, "ok": bool(result.get("ok")), "result": result})
        time.sleep(0.5)
        x1.stop()
    print(json.dumps({
        "ok": all(item["ok"] for item in results),
        "mode": "preview",
        "results": results,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
