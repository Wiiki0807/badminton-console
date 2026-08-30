"""Create and link the owner-only X1 physical-control Rich Menu."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import struct
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "assets" / "line-rich-menu" / "x1-control.png"
API = "https://api.line.me"
DATA_API = "https://api-data.line.me"
ALIAS = "x1-control"
WIDTH, HEIGHT = 2500, 1686
TAB_HEIGHT = 270


def area(x: int, y: int, width: int, height: int, data: str) -> dict[str, object]:
    return {
        "bounds": {"x": x, "y": y, "width": width, "height": height},
        "action": postback(data),
    }


def postback(data: str) -> dict[str, str]:
    return {"type": "postback", "data": data}


def menu_payload() -> dict[str, object]:
    content_top = TAB_HEIGHT
    content_height = HEIGHT - content_top
    half_width, half_height = WIDTH // 2, content_height // 2
    areas: list[dict[str, object]] = [
        area(half_width, 0, WIDTH - half_width, TAB_HEIGHT,
             "action=robot_control&robot=x1&command=robots"),
        area(0, content_top, half_width, half_height,
             "action=robot_control&robot=x1&command=list"),
        area(half_width, content_top, WIDTH - half_width, half_height,
             "action=robot_control&robot=x1&command=status"),
        area(0, content_top + half_height, half_width, HEIGHT - content_top - half_height,
             "action=robot_control&robot=x1&command=stop"),
        area(half_width, content_top + half_height, WIDTH - half_width,
             HEIGHT - content_top - half_height,
             "action=robot_control&robot=x1&command=help"),
    ]
    return {
        "size": {"width": WIDTH, "height": HEIGHT},
        "selected": True,
        "name": "RocketAI X1 physical control",
        "chatBarText": "X1 實機控制",
        "areas": areas,
    }


def validate_image(path: Path) -> None:
    raw = path.read_bytes()
    if len(raw) > 1024 * 1024 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Rich Menu image must be a PNG no larger than 1 MB")
    width, height = struct.unpack(">II", raw[16:24])
    if (width, height) != (WIDTH, HEIGHT):
        raise ValueError(f"Rich Menu image must be {WIDTH}x{HEIGHT}, got {width}x{height}")


class LineApi:
    def __init__(self, token: str):
        self.headers = {"Authorization": f"Bearer {token}"}

    def request(self, method: str, url: str, body: bytes | None = None,
                content_type: str = "application/json", allow_404: bool = False) -> dict:
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return {}
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"LINE API {method} failed ({exc.code}): {detail}") from exc
        return json.loads(raw) if raw else {}


def deploy(token: str, user_id: str, *, dry_run: bool = False) -> dict[str, object]:
    payload = menu_payload()
    validate_image(IMAGE)
    if dry_run:
        return {"ok": True, "dryRun": True, "areas": len(payload["areas"]), "image": str(IMAGE)}
    if not re.fullmatch(r"U[0-9a-fA-F]{32}", user_id):
        raise ValueError("LINE_OWNER_USER_ID is invalid")
    api = LineApi(token)
    previous = api.request(
        "GET", f"{API}/v2/bot/richmenu/alias/{ALIAS}", allow_404=True
    ).get("richMenuId", "")
    created = api.request(
        "POST", f"{API}/v2/bot/richmenu",
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    menu_id = str(created.get("richMenuId", ""))
    if not menu_id:
        raise RuntimeError("LINE API did not return a richMenuId")
    try:
        api.request(
            "POST", f"{DATA_API}/v2/bot/richmenu/{menu_id}/content",
            IMAGE.read_bytes(), "image/png",
        )
        if previous:
            api.request(
                "POST", f"{API}/v2/bot/richmenu/alias/{ALIAS}",
                json.dumps({"richMenuId": menu_id}).encode("utf-8"),
            )
        else:
            api.request(
                "POST", f"{API}/v2/bot/richmenu/alias",
                json.dumps({"richMenuAliasId": ALIAS, "richMenuId": menu_id}).encode("utf-8"),
            )
        api.request("POST", f"{API}/v2/bot/user/{user_id}/richmenu/{menu_id}")
    except Exception:
        api.request("DELETE", f"{API}/v2/bot/richmenu/{menu_id}")
        raise
    if previous and previous != menu_id:
        api.request("DELETE", f"{API}/v2/bot/richmenu/{previous}")
    return {"ok": True, "richMenuId": menu_id, "alias": ALIAS, "linked": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    user_id = os.environ.get("LINE_OWNER_USER_ID", "").strip()
    if not args.dry_run and (not token or not user_id):
        parser.error("LINE_CHANNEL_ACCESS_TOKEN and LINE_OWNER_USER_ID are required")
    print(json.dumps(deploy(token, user_id, dry_run=args.dry_run), ensure_ascii=False))


if __name__ == "__main__":
    main()
