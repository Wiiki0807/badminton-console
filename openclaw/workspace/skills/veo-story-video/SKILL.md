---
name: veo-story-video
description: Plan and render coherent narrative short videos with Google Veo 3.1. Use when the paired owner asks OpenClaw to turn a plot, screenplay, or story idea into a multi-shot video.
metadata: { "openclaw": { "emoji": "🎬" } }
---

# Veo Story Video

Use a gated two-stage workflow. Never spend video-generation credits before the
owner approves the storyboard.

## Stage 1: storyboard only

First write a character bible, then a shot script. Do not begin with long Veo
prompts and do not call the renderer yet.

For a two-minute result, make at most 15 shots of exactly 8 seconds. Every shot
must contain one clear visible event and these fields:

- who: repeat each visible character's age, build, face/hair, clothing and stable features
- where: one fixed place, time and lighting setup
- action: one visible action only
- camera: framing, distance, movement and lens language
- audio: ambience, music and at most one short spoken line
- end frame: a precise pose/composition that the next shot starts from

Keep Mandarin dialogue to one sentence and roughly 8-14 Chinese characters per
shot. Avoid combining long dialogue, complex body motion, fast camera movement
and several interacting characters in one shot.

The character bible must define consistent text descriptions and propose 1-3
fixed reference images: protagonist front/side full body, primary location, and
important prop/style. Current Voice Hub Veo access is text-to-video only; these
images are continuity references for planning and review, not actual Veo image
conditioning. Never claim that a first frame, last frame, or video extension was
sent unless the endpoint later exposes and verifies that capability.

Present the storyboard in Traditional Chinese and ask for explicit approval or
edits. Include the expected number of Veo jobs and total duration. LINE tasks use
isolated sessions, so persist the complete Stage 1 result before replying:

1. Choose a short lowercase ASCII project slug containing only letters, digits
   and hyphens.
2. Create `/home/tommywu/.openclaw/workspace/veo-projects/<slug>/`.
3. Write the character bible and shot script, without final prompts, to
   `storyboard.md` in that directory.
4. Tell the owner the slug and ask them to reply
   `OpenClaw 批准影片專案 <slug>` or request edits with the same slug.

Never depend on chat memory to recover a prior storyboard. If an approval omits
the slug and more than one project exists, ask which project; do not guess.

## Stage 2: approved manifest and rendering

After approval, read that project's `storyboard.md` and
[references/manifest.md](references/manifest.md). Write the approved JSON
manifest as `manifest.json` in the same project directory. Build each English prompt
from the fixed structure in that reference; repeat character appearance verbatim
in every shot where the character appears. The next shot must open on the prior
shot's `end_frame`. Prefer cuts during motion.

For a LINE-triggered approval, keep the original task open until all reference
images, `manifest.json`, and validation are complete. Do not delegate this stage
to a subagent and do not call `sessions_yield`: a yielded task ends the original
LINE callback before the later completion message can be delivered. Return one
explicit final message that says Stage 2 is complete, states the validated shot
count and duration, says that paid rendering has not started, and includes the
exact next command `OpenClaw 渲染影片專案 <slug>`.

Before writing final prompts, create or prepare 1-3 fixed reference images chosen
in Stage 1. Generate only the references the owner approved, one call at a time:

```bash
/home/tommywu/.openclaw/veo_story_video.py reference --project <slug> --kind character --prompt '<bounded English reference description>'
/home/tommywu/.openclaw/veo_story_video.py reference --project <slug> --kind scene --prompt '<bounded English reference description>'
/home/tommywu/.openclaw/veo_story_video.py reference --project <slug> --kind prop --prompt '<bounded English reference description>'
```

Record returned paths in `reference_images`. These images establish the reviewed
visual bible; current Veo calls remain text-only and must not claim to ingest them.

Validate before rendering:

```bash
/home/tommywu/.openclaw/veo_story_video.py validate /home/tommywu/.openclaw/workspace/<manifest>.json
```

State the exact job count and ask once more before a paid full render. The final
confirmation should name the slug, for example
`OpenClaw 渲染影片專案 <slug>` or `...先渲染第一鏡`. For a single-shot proof,
the owner may approve `--limit 1`. Render only with:

```bash
/home/tommywu/.openclaw/veo_story_video.py render /home/tommywu/.openclaw/workspace/veo-projects/<slug>/manifest.json
```

The renderer is resumable: clips whose prompt hash already exists are reused.
Never delete or regenerate successful clips merely to retry a failed later shot.
On success, report duration and output path; do not emit a large MP4 as base64
or `MEDIA:`. The LINE bridge recognizes a
completed render command, uploads `final.mp4` directly through a short-lived
Azure Blob write ticket, and returns a 24-hour Flex download card automatically.
If the owner needs the card again, they can send
`OpenClaw 下載影片專案 <slug>`; do not rerender successful shots for a download.
