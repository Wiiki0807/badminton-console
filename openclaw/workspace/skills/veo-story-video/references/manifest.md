# Approved Veo manifest

Write UTF-8 JSON with this shape:

```json
{
  "project": "Project title",
  "character_bible": {
    "Character name": "Exact stable English appearance description"
  },
  "style_bible": "Stable cinematography, palette, period and realism",
  "reference_images": ["planned reference image descriptions or workspace paths"],
  "shots": [
    {
      "id": "shot-01",
      "duration_seconds": 8,
      "who": "Who is visible, using the exact character-bible wording",
      "where": "Fixed scene, time and light",
      "action": "One visible action",
      "camera": "Shot size, movement and lens language",
      "audio": "Ambience, music and short dialogue",
      "dialogue": "One optional 8-14 character Mandarin sentence",
      "end_frame": "Exact final pose and composition",
      "prompt": "Final English Veo prompt"
    }
  ]
}
```

For a two-minute story use 15 shots. Each prompt uses this order:

1. `8-second single continuous cinematic shot.`
2. `CHARACTER CONTINUITY:` exact relevant character-bible descriptions.
3. `SCENE:` location, time, weather and lighting.
4. `VISIBLE ACTION:` one action with a clear beginning and end.
5. `CAMERA:` distance, framing, lens and one camera move.
6. `AUDIO:` ambience, music and at most one short Mandarin line.
7. `END FRAME:` the composition that the following shot inherits.
8. `STYLE CONTINUITY:` exact style-bible text.

Do not add alternative actions, montage language, multiple cuts, explanatory
backstory, subtitles, captions or on-screen text unless the shot specifically
requires one readable prop/screen. A shot that needs two events must be split.
