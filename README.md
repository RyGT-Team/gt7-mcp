# gt7-mcp

A small MCP server (stdio JSON-RPC, Python, only Pillow needed) that lets an agent drive GT7 running under RyGT /
shadGT on Windows. It launches the game with the RyGT launcher's settings, looks at the window, presses pad buttons,
and reads the game's logs. It was built for performance work: getting into the same race repeatably while
PresentMon and Nsight capture.

## Tools

| Tool | What it does |
|---|---|
| `gt7_launch` | Starts `GT7.exe` through `launch/gt7-direct.ps1` (PS4 Pro mode, 1080p, in-place ranges). `switches` adds environment variables, e.g. `{"SHADGT_HAPTICS_LOG": "6"}`. |
| `gt7_close` | Closes GT7: asks first, then forces it after 10 s. |
| `gt7_status` | Whether GT7 is running, whether its window is in front, and the last race-state line (`GAME-002` / `GAME-006`). |
| `gt7_screenshot` | A JPEG of the game window. |
| `gt7_clip` | 2-12 frames over time, tiled into one image. |
| `gt7_stream` | A live MJPEG view at `http://127.0.0.1:PORT/` (localhost only). |
| `gt7_press` | Pad buttons: cross, circle, triangle, square, options, D-pad, l1/r1, l2 (brake), r2 (throttle), l3/r3, touchpad, steer_left/right, stick_up/down. They're sent as the keyboard keys `user\input_config\default.ini` binds to them, held together, with `hold_ms` up to 30 s. |
| `gt7_log` | Lines of `stderr.log` / `stdout.log`, optionally filtered by a regex. |

## Setup

- Windows, Python 3.10+, `pip install pillow`.
- The game folder is `GT7_ROOT`; by default it's `GTSport-Ryty-shadGT-2026-10-16-4` next to this repository's folder.
  `GT7_LAUNCH` overrides the launch script.
- Register the server in `.mcp.json`:

```json
{
  "mcpServers": {
    "gt7": {
      "type": "stdio",
      "command": "python",
      "args": ["-I", "<path>\\gt7-mcp\\server.py"],
      "env": { "GT7_ROOT": "<path>\\GTSport-Ryty-shadGT-2026-10-16-4" }
    }
  }
}
```

- `python try_client.py gt7_status gt7_screenshot` talks to the server as a client would and saves screenshots as
  `shot-N.jpg`.

## Notes for agents

- **Menus:** press a button, then take a screenshot. The game sometimes misses the first press after a load, so
  repeat it if the screen didn't change.
- **Racing:** the test car is a manual (MT). Cross shifts up and square shifts down; holding only r2 leaves it on
  the limiter.
- **Steering:** the race lobby's gear icon → Assistance Settings → Auto-Drive = "Brake & Steering" lets the game
  steer and brake. Auto-Drive is a saved setting, so set it back to Off afterwards.
- **Driving by telemetry:** start GT7 with `SHADGT_HAPTICS_LOG=6`. The renderer then logs GT7's telemetry (speed,
  rpm, gear, wall contact; position and heading in DIAG-SGT-050 builds) to `stderr.log` about 10 times a second.
  `tools/gt7-drive.py SECONDS --out TRACE --log LOG` holds the throttle, shifts by rpm and records the path. It runs
  as one local loop, because round trips through `gt7_press` drop the throttle between calls. `--ref TRACE`
  (steering along a recorded path) is untested.
- **Captures:** when nsys records GPU metrics, its console window pops up over the game. Measure fps with
  PresentMon on its own first.
