"""Create production-only Inference Hub settings inside the deployable API artifact."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


TARGET = Path(__file__).resolve().parent / "shared" / "deployment_settings.json"


def inject_settings(env: Mapping[str, str] = os.environ, target: Path = TARGET) -> bool:
    url = env.get("INFERENCE_HUB_URL", "").strip()
    token = env.get("INFERENCE_HUB_TOKEN", "").strip()
    if not url and not token:
        target.write_text("{}\n", encoding="utf-8")
        print("Inference Hub deployment settings not injected")
        return False
    if not url or not token:
        raise RuntimeError("INFERENCE_HUB_URL and INFERENCE_HUB_TOKEN must be supplied together")

    settings = {
        "INFERENCE_HUB_URL": url,
        "INFERENCE_HUB_TOKEN": token,
        "INFERENCE_HUB_MODEL": env.get("INFERENCE_HUB_MODEL", "").strip()
        or "openai/openai/gpt-4o-mini",
        "INFERENCE_HUB_TIMEOUT_SECONDS": env.get("INFERENCE_HUB_TIMEOUT_SECONDS", "").strip() or "8",
    }
    target.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    print("Inference Hub deployment settings injected")
    return True


if __name__ == "__main__":
    inject_settings()
