"""Generate a narrated MP4 walkthrough for the badminton arrangement demo."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import edge_tts
import imageio_ffmpeg
from mutagen.mp3 import MP3
from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "video" / "build"
OUTPUT = ROOT / "周一First羽球隊_排點系統操作與模擬測試.mp4"
VOICE = "zh-TW-HsiaoChenNeural"

SCENES = [
    {
        "name": "01_overview",
        "view": "courts",
        "narration": "歡迎使用周一 First 羽球隊的羽球排點系統。團長是 Grace，活動地點在奧創板橋羽球。首頁可以即時查看場地、在場人數、進行中的球友、完成場次，以及下一組候選對戰。",
    },
    {
        "name": "02_smart_match",
        "view": "courts",
        "action": "smart_match",
        "narration": "系統會優先考慮等待時間、每個人已打的場數，以及兩隊的動態積分差。按下智慧排點後，就能把推薦組合安排到空場，並可使用語音叫號通知球友上場。",
    },
    {
        "name": "03_result",
        "view": "courts",
        "action": "result_modal",
        "narration": "比賽結束時，選擇結束比賽並輸入比分。系統會用雙打 Elo 公式比較兩隊原始實力。擊敗較強的對手會獲得較多積分，正常獲勝則調整較少，讓動態積分逐步反映實際程度。",
    },
    {
        "name": "04_members",
        "view": "members",
        "narration": "成員管理頁會分別顯示報名等級與動態積分。報名等級是球友登記的程度，例如等級七；動態積分則從七乘以一百，也就是七百分開始，之後再依每場賽果更新。",
    },
    {
        "name": "05_add_member",
        "view": "members",
        "action": "add_member",
        "narration": "新增球友時，只要輸入暱稱與報名等級，系統就會自動換算初始分數。半級也支援，例如七點五級會從七百五十分開始。加入後，球友會直接進入備戰區等待排點。",
    },
    {
        "name": "06_history",
        "view": "history",
        "narration": "對戰紀錄會保留每一場的隊伍、比分、時間、勝方與積分變化，也能匯出成 CSV，方便團長日後統計出席、勝率與球友成長。",
    },
    {
        "name": "07_simulation",
        "view": "simulation",
        "action": "run_simulation",
        "narration": "模擬測試會使用目前準備好的球友資料，批次執行三十場排點，而且不會影響正式紀錄。儀表板會檢查名單完整性、平均實力差、最大差距、所有球友的參與覆蓋，以及上場次數公平度。",
    },
    {
        "name": "08_results",
        "view": "simulation",
        "narration": "這次測試共有十六位在場球友。三十場的平均實力差約五分，最大差距十分，每人上場七到八場，場次差距只有一場，標準差零點五，五項品質驗證全部通過。團長也能逐場檢查隊伍組合與品質標籤。",
    },
    {
        "name": "09_end",
        "view": "settings",
        "narration": "最後，團長可以調整場地數量、每人場次上限、實力配對、避免重複搭檔、自動安排與語音播報。周一 First 羽球隊的排點系統，讓管理更輕鬆，也讓每位球友都有公平又好玩的比賽體驗。",
    },
]


def find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    runtime = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "bin"
    for folder in (runtime / "override", runtime / "fallback"):
        candidate = folder / "ffmpeg.exe"
        if candidate.exists():
            return str(candidate)
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def duration(audio: Path) -> float:
    return float(MP3(str(audio)).info.length)


async def capture_scenes() -> None:
    index_url = "file:///" + quote(str(ROOT / "index.html").replace("\\", "/"), safe="/:?")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        await page.goto(f"{index_url}?view=courts")
        await page.evaluate("localStorage.removeItem('badminton-club-state')")
        await page.reload()
        await page.wait_for_timeout(900)

        for scene in SCENES:
            await page.goto(f"{index_url}?view={scene['view']}")
            await page.wait_for_timeout(700)
            action = scene.get("action")
            if action == "smart_match":
                await page.locator("#auto-arrange").click()
                await page.wait_for_timeout(500)
            elif action == "result_modal":
                button = page.locator(".court-card:not(.idle) .court-actions button").filter(has_text="結束比賽").first
                await button.click()
                await page.wait_for_timeout(400)
            elif action == "add_member":
                await page.locator("#add-member").click()
                await page.locator("#new-name").fill("示範球友")
                await page.locator("#new-signup-level").fill("7")
                await page.wait_for_timeout(350)
            elif action == "run_simulation":
                await page.locator("#run-simulation").click()
                await page.wait_for_timeout(600)
            await page.screenshot(path=str(WORK / f"{scene['name']}.png"), full_page=False)
            if await page.locator("#modal.open").count():
                await page.locator(".modal-close").click()
        await browser.close()


async def synthesize_audio() -> None:
    for scene in SCENES:
        communicate = edge_tts.Communicate(scene["narration"], VOICE, rate="+4%", volume="+0%")
        await communicate.save(str(WORK / f"{scene['name']}.mp3"))


def compose_video() -> None:
    ffmpeg = find_ffmpeg()
    segments: list[Path] = []
    subtitle_lines: list[str] = []
    cursor = 0.0

    for scene in SCENES:
        stem = scene["name"]
        image, audio, segment = WORK / f"{stem}.png", WORK / f"{stem}.mp3", WORK / f"{stem}.mp4"
        seconds = duration(audio) + 0.7
        run([
            ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-i", str(image), "-i", str(audio),
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{seconds:.3f}", "-movflags", "+faststart", str(segment),
        ])
        segments.append(segment)
        subtitle_lines.extend([str(len(segments)), f"{srt_time(cursor)} --> {srt_time(cursor + seconds)}", scene["narration"], ""])
        cursor += seconds

    concat_file = WORK / "segments.txt"
    concat_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in segments), encoding="utf-8")
    run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", "-movflags", "+faststart", str(OUTPUT)])
    (ROOT / "video" / "周一First羽球隊_操作旁白.srt").write_text("\n".join(subtitle_lines), encoding="utf-8-sig")


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


async def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    print("1/3 擷取網站操作畫面…")
    await capture_scenes()
    print("2/3 使用 Edge TTS 產生繁體中文旁白…")
    await synthesize_audio()
    print("3/3 合成 MP4 與字幕…")
    compose_video()
    print(f"完成：{OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
