"""Render deterministic X1 Rich Menu assets for the LINE Messaging API."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "line-rich-menu"
WIDTH, HEIGHT = 2500, 1686
TAB_HEIGHT = 270


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/msjhbd.ttc" if bold else "C:/Windows/Fonts/msjh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    raise FileNotFoundError("No supported CJK font found")


def center_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str,
                text_font: ImageFont.FreeTypeFont, fill: str) -> None:
    left, top, right, bottom = box
    lines = text.split("\n")
    spacing = 8
    bounds = [draw.textbbox((0, 0), line, font=text_font) for line in lines]
    heights = [bound[3] - bound[1] for bound in bounds]
    total = sum(heights) + spacing * (len(lines) - 1)
    y = top + (bottom - top - total) / 2
    for line, bound, line_height in zip(lines, bounds, heights):
        line_width = bound[2] - bound[0]
        draw.text(((left + right - line_width) / 2, y), line, font=text_font, fill=fill)
        y += line_height + spacing


def render() -> Path:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#071008")
    draw = ImageDraw.Draw(image)
    tab_font = font(52, bold=True)
    card_font = font(76, bold=True)
    subtitle_font = font(35)

    # Robot tabs. X1 is the active robot; the right tab opens the robot selector.
    tabs = ((0, WIDTH // 2, "X1 ROBOT", True),
            (WIDTH // 2, WIDTH, "切換機器人", False))
    for left, right, label, selected in tabs:
        fill = "#173000" if selected else "#101b11"
        outline = "#76b900" if selected else "#315133"
        draw.rounded_rectangle(
            (left + 18, 16, right - 18, TAB_HEIGHT - 12), radius=38,
            fill=fill, outline=outline, width=8,
        )
        center_text(draw, (left, 0, right, TAB_HEIGHT), label, tab_font, "#ffffff")
        if selected:
            draw.rectangle((left + 90, TAB_HEIGHT - 40, right - 90, TAB_HEIGHT - 25),
                           fill="#76b900")

    card_top = TAB_HEIGHT + 12
    card_height = (HEIGHT - card_top) // 2
    cards = (
        (0, 0, "動作控制", "開啟 13 個 Pose"),
        (1, 0, "查詢狀態", "連線・關節・Isaac"),
        (0, 1, "立即停止", "緊急停止目前動作"),
        (1, 1, "控制說明", "OWNER ONLY・實機"),
    )
    for col, row, title, subtitle in cards:
        x0, x1 = col * WIDTH // 2, (col + 1) * WIDTH // 2
        y0, y1 = card_top + row * card_height, card_top + (row + 1) * card_height
        danger = title == "立即停止"
        draw.rounded_rectangle(
            (x0 + 20, y0 + 18, x1 - 20, y1 - 18), radius=48,
            fill="#251014" if danger else "#0d190f",
            outline="#e64b62" if danger else "#315b35", width=8,
        )
        center_text(draw, (x0, y0 + 30, x1, y1 - 70), title, card_font, "#ffffff")
        center_text(draw, (x0, y1 - 145, x1, y1 - 30), subtitle,
                    subtitle_font, "#f093a1" if danger else "#9db79f")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "x1-control.png"
    image.save(target, format="PNG", optimize=True)
    return target


if __name__ == "__main__":
    path = render()
    print(f"Rendered {path} ({path.stat().st_size} bytes)")
