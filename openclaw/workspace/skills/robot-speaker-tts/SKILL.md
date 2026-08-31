---
name: robot-speaker-tts
description: Safely speak operator-supplied text through an online Robot Voice Hub speaker using streaming TTS. Use when the paired owner asks OpenClaw to say, announce, read aloud, or play specific text through a robot speaker.
metadata: { "openclaw": { "emoji": "🔊" } }
---

# Robot Speaker TTS

Use only `/home/tommywu/.openclaw/speaker_tts_control.py`. Never call the TTS
endpoint directly, create audio files, invoke a local audio player, or control
arbitrary network speakers.

The wrapper sends text to Robot Voice Hub, which streams PCM to the selected
online Robot Edge connection. Text must be explicitly supplied by the paired
owner and is limited to 500 characters per command.

Commands:

```bash
/home/tommywu/.openclaw/speaker_tts_control.py status
/home/tommywu/.openclaw/speaker_tts_control.py speak --text "大家好，我是小羽。"
/home/tommywu/.openclaw/speaker_tts_control.py speak --robot mac-mini-edge-test --text "系統測試完成。"
```

If exactly one speaker is online, `--robot` may be omitted. If multiple speakers
are online, ask the user which robot should speak. Report acceptance briefly;
do not claim the user heard it when only delivery acceptance is known.
