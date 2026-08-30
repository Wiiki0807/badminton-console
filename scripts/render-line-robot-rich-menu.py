"""Render deterministic X1 Rich Menu assets for the LINE Messaging API."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "line-rich-menu"
WIDTH, HEIGHT = 2500, 1686
TAB_HEIGHT = 270


def draw_service_icon(draw: ImageDraw.ImageDraw, name: str, center: tuple[int, int],
                      color: str) -> None:
    """Draw simple, dependency-free line icons that remain legible in LINE."""
    cx, cy = center
    width = 13
    if name == "poses":
        for row in range(2):
            for col in range(2):
                x0 = cx - 94 + col * 106
                y0 = cy - 94 + row * 106
                draw.rounded_rectangle((x0, y0, x0 + 82, y0 + 82), radius=16,
                                       outline=color, width=width)
        draw.polygon(((cx - 18, cy - 34), (cx + 48, cy), (cx - 18, cy + 34)),
                     fill=color)
    elif name == "status":
        draw.ellipse((cx - 105, cy - 105, cx + 105, cy + 105), outline=color, width=width)
        points = ((cx - 72, cy + 8), (cx - 36, cy + 8), (cx - 10, cy - 48),
                  (cx + 22, cy + 58), (cx + 52, cy - 12), (cx + 80, cy - 12))
        draw.line(points, fill=color, width=width, joint="curve")
    elif name == "stop":
        points = []
        for dx, dy in ((-48, -112), (48, -112), (112, -48), (112, 48),
                       (48, 112), (-48, 112), (-112, 48), (-112, -48)):
            points.append((cx + dx, cy + dy))
        draw.polygon(points, outline=color, width=width)
        draw.rounded_rectangle((cx - 48, cy - 48, cx + 48, cy + 48), radius=10,
                               fill=color)
    else:
        draw.ellipse((cx - 105, cy - 105, cx + 105, cy + 105), outline=color, width=width)
        draw.text((cx, cy - 7), "i", font=font(142, bold=True), fill=color,
                  anchor="mm")


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
    card_font = font(70, bold=True)
    subtitle_font = font(32)
    watermark_font = font(42, bold=True)

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
        (0, 0, "動作控制", "選擇 13 個實機 Pose", "poses"),
        (1, 0, "查詢狀態", "連線・關節・執行狀態", "status"),
        (0, 1, "立即停止", "停止目前機器人動作", "stop"),
        (1, 1, "控制說明", "OWNER ONLY・X1 實機", "help"),
    )
    for col, row, title, subtitle, icon in cards:
        x0, x1 = col * WIDTH // 2, (col + 1) * WIDTH // 2
        y0, y1 = card_top + row * card_height, card_top + (row + 1) * card_height
        danger = title == "立即停止"
        draw.rounded_rectangle(
            (x0 + 20, y0 + 18, x1 - 20, y1 - 18), radius=48,
            fill="#241116" if danger else "#0d190f",
            outline="#e85a70" if danger else "#3b6940", width=7,
        )
        icon_color = "#ff6e83" if danger else "#76b900"
        draw_service_icon(draw, icon, ((x0 + x1) // 2, y0 + 245), icon_color)
        center_text(draw, (x0, y0 + 390, x1, y1 - 135), title, card_font, "#ffffff")
        center_text(draw, (x0, y1 - 155, x1, y1 - 52), subtitle,
                    subtitle_font, "#f093a1" if danger else "#9db79f")
        # Low-contrast branding behaves like a watermark without reducing readability.
        draw.text((x1 - 62, y0 + 42), "NVIDIA", font=watermark_font,
                  fill="#44242a" if danger else "#17351b", anchor="ra")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "x1-control.png"
    image.save(target, format="PNG", optimize=True)
    return target


if __name__ == "__main__":
    path = render()
    print(f"Rendered {path} ({path.stat().st_size} bytes)")
