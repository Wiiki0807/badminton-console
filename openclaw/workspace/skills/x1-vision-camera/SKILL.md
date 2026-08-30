---
name: x1-vision-camera
description: Safely select, inspect, and capture X1 head, left-hand, or right-hand cameras, or report their private tailnet streaming endpoints.
metadata: { "openclaw": { "emoji": "📷" } }
---

# X1 Vision Camera

Use only `/home/tommywu/.openclaw/x1_camera_control.py`. Never call the camera
server's selection API directly, enumerate arbitrary cameras, open `/dev/video*`,
or expose port 8080 through Funnel. The wrapper allows exactly these named views
and verifies their stable DirectShow USB instance IDs before switching:

- `head`: X1 head, USB Camera #3
- `left-hand`: X1 left hand, USB Camera #1
- `right-hand`: X1 right hand, USB Camera #2

Port 8080 is a shared single-camera stream. Selecting another view changes the
view for every current viewer and consumer. Do not switch repeatedly or in a loop.

For open-vocabulary object detection, use only
`/home/tommywu/.openclaw/x1_locate_control.py`. It safely selects one of the same
three views and calls the private LocateAnything service on port 8090. Never call
`/set`, `/json`, or `/stream` directly. The query must contain 1-8 short object
names. Report the returned `count`, `center_1000`, and `bbox_1000`; coordinates use
top-left origin, x increases right, y increases down, and the frame is 0-1000.

Commands:

```bash
/home/tommywu/.openclaw/x1_camera_control.py status
/home/tommywu/.openclaw/x1_camera_control.py streams
/home/tommywu/.openclaw/x1_camera_control.py select --view head
/home/tommywu/.openclaw/x1_camera_control.py select --view left-hand
/home/tommywu/.openclaw/x1_camera_control.py select --view right-hand
/home/tommywu/.openclaw/x1_camera_control.py snapshot --view head
/home/tommywu/.openclaw/x1_camera_control.py snapshot --view left-hand
/home/tommywu/.openclaw/x1_camera_control.py snapshot --view right-hand
/home/tommywu/.openclaw/x1_locate_control.py status
/home/tommywu/.openclaw/x1_locate_control.py detect --view head --query "bottle"
/home/tommywu/.openclaw/x1_locate_control.py detect --view left-hand --query "bottle,cup"
```

For a requested photo, run `snapshot --view <requested view>`, parse its JSON, and return a short caption
followed by exactly `MEDIA:<media path from JSON>`. Do not invent or rewrite the
path. Streaming URLs are private Tailscale endpoints; provide them only to the
paired owner and never call them public URLs.

For detection, summarize the JSON result and append exactly `MEDIA:<media path>`
when `media` is present so LINE receives the annotated bounding-box image.

## Persistent visual rules

Use only `/home/tommywu/.openclaw/x1_visual_reactor_control.py` to start, update,
inspect, or stop a persistent LocateAnything-to-gesture rule. Never create loops,
cron jobs, or background shell processes yourself. The resident service confirms
continuous detection for 1-3 seconds, repeats actions only after the configured
5-3600 second interval, and sends one LINE image when an object first appears.
It does not notify again while the same object remains present; after disappearance
and reappearance it sends a new event.

```bash
/home/tommywu/.openclaw/x1_visual_reactor_control.py start --query light --actions nod shake-head --view head --confirm-seconds 1.5 --repeat-seconds 30
/home/tommywu/.openclaw/x1_visual_reactor_control.py status
/home/tommywu/.openclaw/x1_visual_reactor_control.py stop
```

`start` also updates an existing rule. Always state the selected query, actions,
view, confirmation time, and repeat interval. `stop` disables monitoring and
cancels current X1 motion.
