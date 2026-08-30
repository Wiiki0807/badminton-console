#!/usr/bin/env python3
"""Bounded, resumable Veo storyboard renderer for the OpenClaw owner."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request


WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE_DIR", "/home/tommywu/.openclaw/workspace"))
HUB_BASE = os.environ.get("NV_INFER_HUB_URL", "http://100.94.194.108:8790").rstrip("/")
MODEL = "gcp/google/veo-3.1-generate-001"
IMAGE_MODEL = "openai/openai/gpt-image-2"
MAX_SHOTS = 15
MAX_PROMPT = 4_000
MAX_VIDEO_BYTES = 64 * 1024 * 1024
SHOT_FIELDS = ("who", "where", "action", "camera", "audio", "end_frame", "prompt")
VIDEO_ID_RE = re.compile(r"video_[A-Za-z0-9_=+-]{32,2048}\Z")


def fail(message: str) -> None:
    raise ValueError(message)


def secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value.strip("\"'")
    try:
        for raw in (Path.home() / ".openclaw" / ".env").read_text(encoding="utf-8-sig").splitlines():
            if raw.strip().startswith(f"{name}="):
                return raw.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return ""


def workspace_file(raw: str) -> Path:
    root = WORKSPACE.resolve(strict=True)
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        fail("manifest must be a file inside the OpenClaw workspace")
    return path


def validate_manifest(raw: object) -> dict:
    if not isinstance(raw, dict):
        fail("manifest must be a JSON object")
    project = str(raw.get("project", "")).strip()
    if not 1 <= len(project) <= 80:
        fail("project must contain 1-80 characters")
    bible = raw.get("character_bible")
    if not isinstance(bible, dict) or not 1 <= len(bible) <= 12:
        fail("character_bible must contain 1-12 named entries")
    for name, description in bible.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(description, str):
            fail("character_bible entries must be named text")
        if not 10 <= len(description.strip()) <= 1_000:
            fail(f"character description is invalid: {name}")
    shots = raw.get("shots")
    if not isinstance(shots, list) or not 1 <= len(shots) <= MAX_SHOTS:
        fail(f"shots must contain 1-{MAX_SHOTS} entries")
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(shots, 1):
        if not isinstance(item, dict):
            fail(f"shot {index} must be an object")
        shot_id = str(item.get("id", f"shot-{index:02d}")).strip().lower()
        if not re.fullmatch(r"shot-[0-9]{2}", shot_id) or shot_id in seen:
            fail(f"shot {index} has an invalid or duplicate id")
        seen.add(shot_id)
        shot: dict[str, object] = {"id": shot_id, "duration_seconds": 8}
        if item.get("duration_seconds", 8) != 8:
            fail(f"{shot_id} must be exactly 8 seconds")
        for field in SHOT_FIELDS:
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                fail(f"{shot_id}.{field} is required")
            value = value.strip()
            if field == "prompt" and len(value) > MAX_PROMPT:
                fail(f"{shot_id}.prompt exceeds {MAX_PROMPT} characters")
            shot[field] = value
        dialogue = str(item.get("dialogue", "")).strip()
        if len(re.sub(r"[\s，。！？,.!?『』「」\"']", "", dialogue)) > 14:
            fail(f"{shot_id}.dialogue is longer than 14 characters")
        shot["dialogue"] = dialogue
        normalized.append(shot)
    return {
        "project": project,
        "character_bible": bible,
        "style_bible": str(raw.get("style_bible", "")).strip(),
        "reference_images": raw.get("reference_images", []),
        "shots": normalized,
    }


def load_manifest(path: Path) -> dict:
    return validate_manifest(json.loads(path.read_text(encoding="utf-8")))


def request_json(
    method: str, url: str, token: str, payload: dict | None = None,
    timeout: int = 90, max_bytes: int = 512 * 1024,
) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise RuntimeError("API JSON response is too large")
        value = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(2_000).decode("utf-8", "replace")
        raise RuntimeError(f"Veo API returned HTTP {exc.code}: {detail[:500]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Veo API returned invalid JSON")
    return value


def generate_reference(project: str, kind: str, prompt: str, token: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", project):
        fail("project must be a lowercase ASCII slug")
    if kind not in {"character", "scene", "prop"}:
        fail("reference kind must be character, scene, or prop")
    prompt = prompt.strip()
    if not 20 <= len(prompt) <= 1_600:
        fail("reference prompt must contain 20-1600 characters")
    digest = hashlib.sha256(prompt.encode()).hexdigest()[:10]
    directory = WORKSPACE / "veo-projects" / project / "references"
    directory.mkdir(parents=True, exist_ok=True)
    existing = list(directory.glob(f"{kind}-{digest}.*"))
    if existing:
        return {"project": project, "kind": kind, "file": str(existing[0]), "reused": True}
    result = request_json(
        "POST", f"{HUB_BASE}/images/generations", token,
        {
            "model": IMAGE_MODEL,
            "prompt": (
                "Create one production reference image for a coherent cinematic video. "
                "Neutral reference presentation, consistent proportions and materials, no captions, "
                "no watermark, no logo. " + prompt
            ),
            "size": "1536x1024", "quality": "low", "n": 1,
        }, timeout=180, max_bytes=20 * 1024 * 1024,
    )
    encoded = str(((result.get("data") or [{}])[0]).get("b64_json") or "")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RuntimeError("image endpoint returned invalid base64") from exc
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    elif raw.startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
    else:
        raise RuntimeError("image endpoint returned an unsupported format")
    if not 1 <= len(raw) <= 16 * 1024 * 1024:
        raise RuntimeError("reference image is empty or too large")
    output = directory / f"{kind}-{digest}{suffix}"
    output.write_bytes(raw)
    return {"project": project, "kind": kind, "file": str(output), "bytes": len(raw)}


def render_shot(shot: dict, output: Path, token: str, poll_seconds: int, timeout_seconds: int) -> dict:
    job = request_json("POST", f"{HUB_BASE}/videos", token, {"model": MODEL, "prompt": shot["prompt"]})
    video_id = str(job.get("id", ""))
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise RuntimeError("Veo API did not return a valid video id")
    deadline = time.monotonic() + timeout_seconds
    while True:
        status = request_json("GET", f"{HUB_BASE}/videos/{video_id}", token)
        state = str(status.get("status", "")).lower()
        if state == "completed":
            break
        if state in {"failed", "cancelled", "expired"}:
            raise RuntimeError(f"Veo job ended with status {state}: {status.get('error')}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Veo job timed out: {shot['id']}")
        time.sleep(poll_seconds)
    request = urllib.request.Request(
        f"{HUB_BASE}/videos/{video_id}/content",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        raw = response.read(MAX_VIDEO_BYTES + 1)
    if not 1 <= len(raw) <= MAX_VIDEO_BYTES:
        raise RuntimeError("generated video is empty or too large")
    output.write_bytes(raw)
    return {"id": shot["id"], "video_id": video_id, "file": str(output), "bytes": len(raw)}


def concat_videos(clips: list[Path], output: Path) -> None:
    ffmpeg = Path("/usr/bin/ffmpeg")
    if not ffmpeg.is_file():
        raise RuntimeError("ffmpeg is not installed")
    concat = output.parent / "concat.txt"
    concat.write_text("".join(f"file '{clip.name}'\n" for clip in clips), encoding="utf-8")
    completed = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(output)],
        cwd=output.parent, capture_output=True, text=True, timeout=300, check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"ffmpeg concat failed: {completed.stderr[-800:]}")


def project_slug(name: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return ascii_slug or f"story-{hashlib.sha256(name.encode()).hexdigest()[:10]}"


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("manifest")
    render = sub.add_parser("render")
    render.add_argument("manifest")
    render.add_argument("--limit", type=int, default=MAX_SHOTS)
    render.add_argument("--poll-seconds", type=int, default=5)
    render.add_argument("--timeout-per-shot", type=int, default=600)
    reference = sub.add_parser("reference")
    reference.add_argument("--project", required=True)
    reference.add_argument("--kind", required=True, choices=("character", "scene", "prop"))
    reference.add_argument("--prompt", required=True)
    args = parser.parse_args()

    if args.command == "reference":
        token = secret("NV_INFER_HUB_TOKEN")
        if not token:
            raise RuntimeError("NV_INFER_HUB_TOKEN is unavailable")
        print(json.dumps(generate_reference(args.project, args.kind, args.prompt, token), ensure_ascii=False))
        return

    path = workspace_file(args.manifest)
    manifest = load_manifest(path)
    if args.command == "validate":
        print(json.dumps({"valid": True, "project": manifest["project"], "shots": len(manifest["shots"]), "duration_seconds": len(manifest["shots"]) * 8}, ensure_ascii=False))
        return

    token = secret("NV_INFER_HUB_TOKEN")
    if not token:
        raise RuntimeError("NV_INFER_HUB_TOKEN is unavailable")
    limit = min(max(args.limit, 1), len(manifest["shots"]))
    output_dir = WORKSPACE / "veo-projects" / project_slug(manifest["project"])
    output_dir.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    jobs: list[dict] = []
    for shot in manifest["shots"][:limit]:
        digest = hashlib.sha256(str(shot["prompt"]).encode()).hexdigest()[:10]
        clip = output_dir / f"{shot['id']}-{digest}.mp4"
        if clip.is_file() and clip.stat().st_size > 0:
            jobs.append({"id": shot["id"], "file": str(clip), "reused": True})
        else:
            print(f"rendering {shot['id']} ({len(clips) + 1}/{limit})", file=sys.stderr, flush=True)
            jobs.append(render_shot(shot, clip, token, args.poll_seconds, args.timeout_per_shot))
        clips.append(clip)
    final = output_dir / ("final.mp4" if limit == len(manifest["shots"]) else f"preview-{limit}.mp4")
    concat_videos(clips, final)
    state = {"project": manifest["project"], "shots": jobs, "output": str(final), "duration_seconds": limit * 8, "complete": limit == len(manifest["shots"])}
    (output_dir / "render-state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
