#!/usr/bin/env python3
"""Run a non-physical OpenClaw X1 skill smoke test on cam."""
from __future__ import annotations

import json

import line_openclaw_bridge as bridge


def main() -> None:
    result = bridge._openclaw(
        "agent",
        "--agent",
        "main",
        "--message",
        "請先查詢 X1 機器人狀態，再只在 Isaac 預覽依序播放 away、thanks，最後回報結果，不要驅動實機",
        "--session-key",
        "agent:main:x1-smoke-2",
        "--timeout",
        "180",
        "--json",
        timeout=210,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
