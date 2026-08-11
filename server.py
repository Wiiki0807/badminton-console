from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "live-data"
STATE_FILE = DATA_DIR / "state.json"
COMMENTS_FILE = DATA_DIR / "comments.json"
WISHES_FILE = DATA_DIR / "wishes.json"
LOCK = threading.Lock()
ALLOWED_REACTIONS = {"👍", "🔥", "🏸", "👏"}
WISH_COSTS = {"partner": 3, "opponent": 4, "mixed": 3, "boss": 5}


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def write_json(path: Path, value):
    DATA_DIR.mkdir(exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def local_ip(port=None):
    candidates = socket.gethostbyname_ex(socket.gethostname())[2]
    local_network = [ip for ip in candidates if ip.startswith("192.168.")]
    if port:
        for ip in local_network:
            try:
                with socket.create_connection((ip, port), timeout=0.2):
                    return ip
            except OSError:
                continue
    if local_network:
        return local_network[0]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class BadmintonHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, value, status=200):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def read_body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > 1_000_000:
            raise ValueError("invalid body size")
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/live-bundle":
            with LOCK:
                bundle = {
                    "state": read_json(STATE_FILE, {"courts": [], "recent": [], "stats": []}),
                    "comments": read_json(COMMENTS_FILE, [])[-80:],
                    "wishes": read_json(WISHES_FILE, [])[-80:],
                }
            return self.send_json(bundle)
        if path == "/api/live-state":
            with LOCK:
                return self.send_json(read_json(STATE_FILE, {"courts": [], "recent": [], "stats": []}))
        if path == "/api/comments":
            with LOCK:
                comments = read_json(COMMENTS_FILE, [])
            return self.send_json(comments[-80:])
        if path == "/api/wishes":
            with LOCK:
                wishes = read_json(WISHES_FILE, [])
            return self.send_json(wishes[-80:])
        if path == "/api/info":
            return self.send_json({"playerUrl": f"http://{local_ip(self.server.server_port)}:{self.server.server_port}/live.html"})
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self.read_body()
            if path == "/api/live-state":
                if not isinstance(body, dict):
                    raise ValueError("state must be an object")
                with LOCK:
                    write_json(STATE_FILE, body)
                return self.send_json({"ok": True})
            if path == "/api/comments":
                name = str(body.get("name", "")).strip()[:18]
                message = str(body.get("message", "")).strip()[:120]
                match_id = str(body.get("matchId", "")).strip()[:80]
                match_label = str(body.get("matchLabel", "")).strip()[:80]
                if not name or not message:
                    return self.send_json({"error": "請輸入名字與留言"}, 400)
                comment = {"id": uuid.uuid4().hex, "name": name, "message": message, "matchId": match_id, "matchLabel": match_label, "createdAt": int(time.time() * 1000), "reactions": {}}
                with LOCK:
                    comments = read_json(COMMENTS_FILE, [])[-79:]
                    comments.append(comment)
                    write_json(COMMENTS_FILE, comments)
                return self.send_json(comment, 201)
            if path == "/api/wishes":
                player_name = str(body.get("playerName", "")).strip()[:18]
                wish_type = str(body.get("type", "")).strip()
                target = str(body.get("target", "")).strip()[:30]
                if not player_name or wish_type not in WISH_COSTS:
                    return self.send_json({"error": "請選擇球友與願望"}, 400)
                if wish_type in {"partner", "opponent"} and not target:
                    return self.send_json({"error": "指定搭檔或對手時請填寫名字"}, 400)
                wish = {"id": uuid.uuid4().hex, "playerName": player_name, "type": wish_type, "target": target, "cost": WISH_COSTS[wish_type], "status": "pending", "createdAt": int(time.time() * 1000)}
                with LOCK:
                    wishes = read_json(WISHES_FILE, [])[-79:]
                    wishes.append(wish)
                    write_json(WISHES_FILE, wishes)
                return self.send_json(wish, 201)
            if path == "/api/wishes/action":
                wish_id = str(body.get("id", ""))
                status = str(body.get("status", ""))
                if status not in {"fulfilled", "rejected"}:
                    return self.send_json({"error": "不支援的願望狀態"}, 400)
                with LOCK:
                    wishes = read_json(WISHES_FILE, [])
                    target_wish = next((item for item in wishes if item.get("id") == wish_id), None)
                    if not target_wish:
                        return self.send_json({"error": "找不到願望"}, 404)
                    target_wish["status"] = status
                    target_wish["updatedAt"] = int(time.time() * 1000)
                    write_json(WISHES_FILE, wishes)
                return self.send_json(target_wish)
            if path == "/api/reactions":
                comment_id = str(body.get("id", ""))
                emoji = str(body.get("emoji", ""))
                if emoji not in ALLOWED_REACTIONS:
                    return self.send_json({"error": "不支援的互動"}, 400)
                with LOCK:
                    comments = read_json(COMMENTS_FILE, [])
                    target = next((item for item in comments if item.get("id") == comment_id), None)
                    if not target:
                        return self.send_json({"error": "找不到留言"}, 404)
                    reactions = target.setdefault("reactions", {})
                    reactions[emoji] = int(reactions.get(emoji, 0)) + 1
                    write_json(COMMENTS_FILE, comments)
                return self.send_json(target)
            return self.send_json({"error": "not found"}, 404)
        except (ValueError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def log_message(self, format, *args):
        if urlparse(self.path).path.startswith("/api/"):
            return
        super().log_message(format, *args)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), BadmintonHandler)
    print(f"管理頁：http://127.0.0.1:{args.port}/?view=courts", flush=True)
    print(f"球友頁：http://{local_ip()}:{args.port}/live.html", flush=True)
    server.serve_forever()
