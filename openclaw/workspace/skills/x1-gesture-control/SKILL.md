---
name: x1-gesture-control
description: Safely query, preview, play, stop, or sequence allow-listed Laban gestures on the X1 robot. Use when the paired LINE owner asks OpenClaw to control X1 gestures or include gestures in a longer workflow.
metadata: { "openclaw": { "emoji": "🤖" } }
---

# X1 Gesture Control

Use only `/home/tommywu/.openclaw/x1_gesture_control.py`. Never call ROS2 topics,
`laban_ctl.py`, `run_player.sh`, the Unix socket, or arbitrary gesture files directly.

Allowed gestures are `away`, `away2`, and `thanks`. Never invent another name.
Run status before a motion workflow. Real motion is allowed only when the paired
owner explicitly requests the physical X1 robot; otherwise use preview mode.

Commands:

```bash
/home/tommywu/.openclaw/x1_gesture_control.py status
/home/tommywu/.openclaw/x1_gesture_control.py play away
/home/tommywu/.openclaw/x1_gesture_control.py play thanks --real
/home/tommywu/.openclaw/x1_gesture_control.py sequence away thanks
/home/tommywu/.openclaw/x1_gesture_control.py sequence away thanks --real
/home/tommywu/.openclaw/x1_gesture_control.py stop
```

`play` and `sequence` default to Isaac-only preview. `--real` drives the physical
robot and its Isaac mirror. A sequence accepts at most five gestures and returns
to ready after every step. Stop immediately when the user asks to stop; do not
finish the remaining plan. Report the returned JSON accurately and never claim
motion succeeded when `ok` is false.
