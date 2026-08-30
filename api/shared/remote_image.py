"""Bounded public-image fetcher for OpenClaw results sent through LINE."""
from __future__ import annotations

import ipaddress
from io import BytesIO
import socket
from urllib import error, request
from urllib.parse import urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_EDGE = 4096
MAX_LINE_ORIGINAL_BYTES = 9 * 1024 * 1024


def validate_public_https_url(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 2000:
        raise ValueError("invalid image URL")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        raise ValueError("image URL must be public HTTPS")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".local", ".internal")):
        raise ValueError("private image host is not allowed")
    try:
        addresses = {
            row[4][0]
            for row in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError("image host cannot be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise ValueError("private image address is not allowed")
    return candidate


class _PublicHttpsRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        validate_public_https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_public_image(url: str) -> tuple[bytes, str]:
    """Download and normalize one public image into a LINE-compatible JPEG."""
    safe_url = validate_public_https_url(url)
    req = request.Request(
        safe_url,
        headers={
            "Accept": "image/jpeg,image/png,image/webp;q=0.9,*/*;q=0.1",
            "User-Agent": "RocketAI-LINE-Image-Fetcher/1",
        },
    )
    opener = request.build_opener(_PublicHttpsRedirectHandler())
    try:
        with opener.open(req, timeout=12) as response:
            validate_public_https_url(response.geturl())
            declared = int(response.headers.get("Content-Length", "0") or 0)
            if declared > MAX_DOWNLOAD_BYTES:
                raise ValueError("remote image is too large")
            raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (error.HTTPError, error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("remote image download failed") from exc
    if not raw or len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("remote image is too large")
    try:
        with Image.open(BytesIO(raw)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("remote image has too many pixels")
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="JPEG", quality=90, optimize=True)
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise ValueError("remote content is not a supported image") from exc
    normalized = output.getvalue()
    if not normalized or len(normalized) > MAX_LINE_ORIGINAL_BYTES:
        raise ValueError("normalized image is too large for LINE")
    return normalized, "image/jpeg"
