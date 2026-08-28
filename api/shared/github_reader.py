"""Read bounded public GitHub repository metadata from fixed GitHub API hosts."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib import error, request
from urllib.parse import quote

GITHUB_REPO_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})(?:[/?#\s]|$)",
    re.IGNORECASE,
)
API_ROOT = "https://api.github.com"
MAX_API_BYTES = 2 * 1024 * 1024
MAX_README_CHARS = 10_000
MAX_TREE_ENTRIES = 300
MAX_CONTEXT_CHARS = 18_000
CACHE_TTL_SECONDS = 600
_CACHE: dict[str, tuple[float, dict[str, str]]] = {}


class GitHubReaderError(ValueError):
    """A safe GitHub reader error suitable for a LINE response."""


def extract_repository(text: str) -> tuple[str, str] | None:
    match = GITHUB_REPO_PATTERN.search(str(text or ""))
    if not match:
        return None
    owner = match.group(1)
    repo = match.group(2)
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not repo:
        return None
    return owner, repo


def _headers(accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": "RocketAI-LINE-GitHub-Reader",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read(url: str, *, accept: str = "application/vnd.github+json", allow_404: bool = False) -> bytes:
    req = request.Request(url, headers=_headers(accept))
    try:
        with request.urlopen(req, timeout=8) as response:
            raw = response.read(MAX_API_BYTES + 1)
    except error.HTTPError as exc:
        if allow_404 and exc.code == 404:
            return b""
        if exc.code == 404:
            raise GitHubReaderError("找不到這個公開 GitHub repository，私人 repository 目前不支援。") from exc
        if exc.code in {403, 429}:
            raise GitHubReaderError("GitHub API 暫時達到讀取限制，請稍後再試。") from exc
        raise GitHubReaderError("GitHub repository 暫時無法讀取。") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise GitHubReaderError("GitHub repository 連線失敗，請稍後再試。") from exc
    if len(raw) > MAX_API_BYTES:
        raise GitHubReaderError("GitHub repository 回傳資料過大，無法安全分析。")
    return raw


def _get_json(url: str) -> dict[str, Any]:
    try:
        value = json.loads(_read(url).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GitHubReaderError("GitHub API 回傳格式無法解析。") from exc
    if not isinstance(value, dict):
        raise GitHubReaderError("GitHub API 回傳格式無法解析。")
    return value


def _get_text(url: str, *, allow_404: bool = False) -> str:
    raw = _read(url, accept="application/vnd.github.raw+json", allow_404=allow_404)
    try:
        return raw.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return ""


def fetch_repository_context(owner: str, repo: str) -> dict[str, str]:
    """Return cached, bounded README/metadata/tree context for one public repository."""
    cache_key = f"{owner}/{repo}".lower()
    cached = _CACHE.get(cache_key)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]

    safe_owner = quote(owner, safe="")
    safe_repo = quote(repo, safe="")
    api_repo = f"{API_ROOT}/repos/{safe_owner}/{safe_repo}"
    metadata = _get_json(api_repo)
    full_name = str(metadata.get("full_name") or f"{owner}/{repo}")[:205]
    default_branch = str(metadata.get("default_branch") or "main")[:200]
    readme = _get_text(f"{api_repo}/readme", allow_404=True)[:MAX_README_CHARS]
    languages = _get_json(f"{api_repo}/languages")
    tree = _get_json(
        f"{api_repo}/git/trees/{quote(default_branch, safe='')}?recursive=1"
    )

    tree_rows = []
    for item in (tree.get("tree") or [])[:MAX_TREE_ENTRIES]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")[:300]
        item_type = str(item.get("type") or "")
        if path:
            size = item.get("size")
            suffix = f" ({size} bytes)" if isinstance(size, int) else ""
            tree_rows.append(f"- [{item_type}] {path}{suffix}")

    license_value = metadata.get("license") or {}
    context = (
        f"Repository: {full_name}\n"
        f"URL: https://github.com/{full_name}\n"
        f"Description: {str(metadata.get('description') or '未提供')}\n"
        f"Default branch: {default_branch}\n"
        f"Primary language: {str(metadata.get('language') or '未提供')}\n"
        f"Languages: {', '.join(str(key) for key in languages) or '未提供'}\n"
        f"License: {str(license_value.get('spdx_id') or '未提供')}\n"
        f"Archived: {bool(metadata.get('archived'))}\n"
        f"Tree truncated by GitHub: {bool(tree.get('truncated'))}\n\n"
        f"README:\n{readme or '找不到 README'}\n\n"
        "Repository tree (bounded):\n" + "\n".join(tree_rows)
    )[:MAX_CONTEXT_CHARS]
    result = {
        "label": f"GitHub repository {full_name}",
        "url": f"https://github.com/{full_name}",
        "content": context,
    }
    _CACHE[cache_key] = (now + CACHE_TTL_SECONDS, result)
    return result
