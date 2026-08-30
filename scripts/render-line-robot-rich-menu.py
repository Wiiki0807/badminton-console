"""Render deterministic X1 Rich Menu assets for the LINE Messaging API."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "line-rich-menu"
WIDTH, HEIGHT = 2500, 1686
COLS, ROWS = 5, 4
CELL_W, CELL_H = WIDTH // COLS, HEIGHT // ROWS
POSES = (
    "away", "away2", "good", "happy", "hello",
    "come", "bad", "thanks", "goodbye", "nice",
    "surprised", "wave-happily", "open-two-arms",
)


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
    title_font = font(58, bold=True)
    pose_font = font(44, bold=True)
    small_font = font(35, bold=True)
    active = "#f5a623"
    active_fill = "#392607"

    top_labels = (
        "X1 實機", "查詢\n狀態", "立即\n停止", "動作\n列表", "控制\n說明",
    )
    for index, label in enumerate(top_labels):
        x0, y0 = index * CELL_W, 0
        x1, y1 = x0 + CELL_W, CELL_H
        selected = index == 0
        fill = active_fill if selected else "#101b11"
        outline = active if selected else "#315133"
        draw.rounded_rectangle(
            (x0 + 16, y0 + 16, x1 - 16, y1 - 16), radius=34,
            fill=fill, outline=outline, width=8,
        )
        center_text(draw, (x0, y0, x1, y1), label,
                    title_font if index == 0 else small_font,
                    "#ffffff" if selected else "#dce8dd")
        if selected:
            draw.rectangle((x0 + 55, y1 - 42, x1 - 55, y1 - 28), fill=active)

    for index, pose in enumerate(POSES):
        row, col = divmod(index, COLS)
        x0, y0 = col * CELL_W, (row + 1) * CELL_H
        x1, y1 = x0 + CELL_W, y0 + CELL_H
        draw.rounded_rectangle(
            (x0 + 16, y0 + 16, x1 - 16, y1 - 16), radius=34,
            fill="#0c170d", outline="#29452b", width=6,
        )
        center_text(draw, (x0 + 20, y0 + 20, x1 - 20, y1 - 20),
                    pose.replace("wave-happily", "wave\nhappily").replace(
                        "open-two-arms", "open two\narms"
                    ), pose_font, "#f4f7f4")

    # Two unused cells are intentionally non-tappable and carry safety context.
    for index, label in ((13, "OWNER\nONLY"), (14, "周圍淨空\n再操作")):
        row, col = divmod(index, COLS)
        x0, y0 = col * CELL_W, (row + 1) * CELL_H
        x1, y1 = x0 + CELL_W, y0 + CELL_H
        draw.rounded_rectangle(
            (x0 + 16, y0 + 16, x1 - 16, y1 - 16), radius=34,
            fill="#080d08", outline="#1c2a1d", width=4,
        )
        center_text(draw, (x0, y0, x1, y1), label, small_font, "#829083")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "x1-control.png"
    image.save(target, format="PNG", optimize=True)
    return target


if __name__ == "__main__":
    path = render()
    print(f"Rendered {path} ({path.stat().st_size} bytes)")
