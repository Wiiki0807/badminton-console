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
```

For a requested photo, run `snapshot --view <requested view>`, parse its JSON, and return a short caption
followed by exactly `MEDIA:<media path from JSON>`. Do not invent or rewrite the
path. Streaming URLs are private Tailscale endpoints; provide them only to the
paired owner and never call them public URLs.
