---
name: x1-vision-camera
description: Safely inspect the X1 head camera, capture one current frame, or report its private tailnet streaming endpoints.
metadata: { "openclaw": { "emoji": "📷" } }
---

# X1 Vision Camera

Use only `/home/tommywu/.openclaw/x1_camera_control.py`. Never enumerate arbitrary
cameras, change the active camera, open `/dev/video*`, or expose port 8080 through
Funnel. The wrapper verifies that the active device is `USB Camera #3` with USB ID
`vid_1bcf&pid_0b15` before returning a frame.

Commands:

```bash
/home/tommywu/.openclaw/x1_camera_control.py status
/home/tommywu/.openclaw/x1_camera_control.py streams
/home/tommywu/.openclaw/x1_camera_control.py snapshot
```

For a requested photo, run `snapshot`, parse its JSON, and return a short caption
followed by exactly `MEDIA:<media path from JSON>`. Do not invent or rewrite the
path. Streaming URLs are private Tailscale endpoints; provide them only to the
paired owner and never call them public URLs.
