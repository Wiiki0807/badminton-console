"""One-off helper: hash the admin password locally and push all secrets into SWA app settings.

Run with `python tools/set_admin_credentials.py`. The password is read from a hidden
prompt and never printed, logged, or written to disk.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import subprocess
import sys

SUBSCRIPTION = "e1c94f78-b17d-461a-b591-5c64881366f1"
RESOURCE_GROUP = "badminton"
STORAGE_ACCOUNT = "a9badminton"
STATIC_WEB_APP = "badminton-console"
ITERATIONS = 200_000


def run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, shell=os.name == "nt")
    if result.returncode != 0:
        sys.exit(f"命令失敗：{' '.join(args[:3])} …\n{result.stderr.strip()}")
    return result.stdout.strip()


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def hash_password(plain: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${b64(salt)}${b64(digest)}"


def main() -> None:
    username = input("管理端帳號: ").strip()
    if not username:
        sys.exit("帳號不可空白")
    password = getpass.getpass("管理端密碼: ")
    if len(password) < 12:
        sys.exit("密碼請至少 12 個字元")
    if password != getpass.getpass("再次輸入密碼: "):
        sys.exit("兩次輸入不一致")

    print("\n設定訂閱…")
    run(["az", "account", "set", "--subscription", SUBSCRIPTION])

    print("讀取 Storage 連線字串…")
    connection = run([
        "az", "storage", "account", "show-connection-string",
        "-g", RESOURCE_GROUP, "-n", STORAGE_ACCOUNT,
        "--query", "connectionString", "-o", "tsv",
    ])

    password_hash = hash_password(password)
    auth_secret = b64(os.urandom(32))

    print("寫入 Static Web App 設定…")
    run([
        "az", "staticwebapp", "appsettings", "set",
        "-n", STATIC_WEB_APP, "-g", RESOURCE_GROUP,
        "--setting-names",
        f"STORAGE_CONNECTION_STRING={connection}",
        f"ADMIN_USERNAME={username}",
        f"ADMIN_PASSWORD_HASH={password_hash}",
        f"AUTH_SECRET={auth_secret}",
        "-o", "none",
    ])

    local = {
        "IsEncrypted": False,
        "Values": {
            "FUNCTIONS_WORKER_RUNTIME": "python",
            "AzureWebJobsStorage": "",
            "STORAGE_CONNECTION_STRING": connection,
            "ADMIN_USERNAME": username,
            "ADMIN_PASSWORD_HASH": password_hash,
            "AUTH_SECRET": auth_secret,
        },
    }
    target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api", "local.settings.json")
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(local, handle, ensure_ascii=False, indent=2)

    print("\n完成。已設定 STORAGE_CONNECTION_STRING / ADMIN_USERNAME / ADMIN_PASSWORD_HASH / AUTH_SECRET")
    print(f"本機開發設定已寫入 {target}（已在 .gitignore 中）")


if __name__ == "__main__":
    main()
