# AlgorithmArt

[Home Assistant](https://www.home-assistant.io/) integration and companion add-on for driving the [Waveshare ESP32-S3-PhotoPainter](https://www.waveshare.com/esp32-s3-photopainter.htm)
— with built-in generative art (diffusion-limited
aggregation, fractal zoom) and a Go (board game) SGF replay generator. This generates images on a Home Assistant server and pushes them to the Photopainter device.
This App runs as a separate Docker image with a web interface on the Home Assistant server
---

## Examples

AlgorithmArt is designed to generate visually interesting content for the
**PhotoPainter S3 7-color ACeP e-paper display** from Home Assistant. The
generated images can be displayed manually, on a schedule, or as part of a
Home Assistant automation.
[[https://www.waveshare.com/esp32-s3-photopainter.htm]]

### Diffusion-Limited Aggregation (DLA)

[DLA](https://en.wikipedia.org/wiki/Diffusion-d_aggregation is a
classic growth model in which particles perform random walks and stick when
they touch an existing structure. The resulting patterns resemble coral,
lightning, roots, snowflakes, and other natural branching forms.

![Diffes/dla.png

The DLA generator maintains state between updates, allowing a Home Assistant
automation or the built-in scheduler to grow the artwork over time and turn
the display into a continuously evolving piece of generative art.

### Mandelbrot Fractal Zoom

The fractal generator renders the
[Mandelbrot set](https://en.wikipedia.org/wiki/Mandelbrot_set), one of the
best-known exampleseeper
into the set, intricate self-similar structures emerge at every scale.

!Mandelbrot fractal example

AlgorithmArt adapts the rendering to the PhotoPainter's 7-color e-paper
palette, producing detailed mathematical artwork optimized for the display.

### Go (Board Game) Replay

https://en.wikipedia.org/wiki/Go_(game) is a classic abstract strategy
board game played for more than 2,500 years. AlgorithmArt can replay games
from standard SGF files, advancing move-by-move with each update.

examples/goban.png

By default, the renderer uses **red stones for one side** instead of the
traditional white stones. This improves contrast and readability on the
PhotoPainter's color e-paper display. Traditional black-and-white stones can
be selected through the generator options if preferred.

The included SGF library allows the display to slowly replay notable games,
turning the PhotoPainter into both an artwork display and a conversation
piece for Go enthusiasts.

---

## Architecture

The project has two independently-installed pieces that talk to each other
and to the physical device:

```
┌─────────────────────────┐        ┌──────────────────────────────┐        ┌────────────────┐
│  Home Assistant          │        │  AlgorithmArt add-on          │        │  PhotoPainter   │
│  custom_components/      │◄──────►│  (Docker sidecar, port 8765)  │◄──────►│  (ESP32 device) │
│  photopainter_art/       │  HTTP  │  main.py Flask API + web UI   │  HTTP  │  /api/*         │
└─────────────────────────┘        └──────────────────────────────┘        └────────────────┘
```

- **`custom_components/photopainter_art/`** — the HA integration. Config
  flow, a coordinator that polls the device's battery/sensor/system-info
  endpoints, and services (`rotate`, `display_image`, `generate_art`) that
  automations can call.
- **`algorithm_art/` add-on** — a sidecar container that runs the actual
  generator binaries (`dla.x`, `fractal.x`, `goban.x`), exposes a small
  Flask API, a self-contained web dashboard at `/ui`, and its own
  scheduler for hands-off auto-generation.
- **The device itself** exposes a small HTTP API
  (`/api/config`, `/api/display-image`, `/api/rotate`, `/api/battery`, …)
  that both the integration and the add-on call directly.

---

## Repository layout

```
custom_components/photopainter_art/
  const.py            Shared constants, domain, service/entity IDs
  config_flow.py       Setup wizard: connect, name-collision check, confirm
  coordinator.py        Polls device sensors/battery/status
  generative_art.py     Button/entities for the "Generate & display" flow
  services.py            rotate / display_image / generate_art service handlers
  strings.json            UI strings for the config flow and services

algorithm_art/  (add-on)
  Dockerfile              Builds dla.x / fractal.x / goban.x and the sidecar image
  config.yaml              Add-on options schema (port, host, binaries, log level, …)
  run.sh                    bashio entrypoint — exports config as env vars, starts main.py
  main.py                    Flask API: /generate/*, /push, /status, /health, /scheduler/*
  web_ui.py                   Web dashboard (Home page + per-generator sub-pages)
  scheduler.py                  Background auto-generate/push loop, persists to /data/state
  goban_state.py                 Tracks current SGF game + move position across calls
  sgf_directory.py                 Bundled public-domain SGF game index
  art_generator.py                  HTTP client the HA integration uses to call the sidecar

src/                       (Go sources for the generator binaries)
  dla/                       Diffusion-limited aggregation (dla.x)
  fractal/                    Mandelbrot zoom, 7-color ACeP palette (fractal.x)
  goban/                        SGF board renderer (goban.x)
```

---

## Installation

### 1. Add-on (AlgorithmArt sidecar)

1. Add this repository to your Home Assistant Supervisor's add-on store
   (or copy the `algorithm_art/` folder into `addons/`).
2. Install **AlgorithmArt Generator**, set its options (see below), and
   start it.
3. Confirm it's healthy: `http://<home-assistant-host>:8765/health`.

### 2. Integration (PhotopainterArt)

1. Copy `custom_components/photopainter_art/` into your HA
   `config/custom_components/` directory.
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → PhotopainterArt**,
   enter the PhotoFrame's IP/hostname. The config flow will verify
   connectivity, pull the device name, and configure the frame with your
   HA URL automatically.

---

## Configuration (add-on options)

| Option           | Default            | Notes                                                                 |
|------------------|---------------------|------------------------------------------------------------------------|
| `port`           | `8765`               | Sidecar API port                                                        |
| `photoframe_host`| `photoframe.local`    | Device IP/hostname the scheduler pushes to                              |
| `dla_cmd`        | `dla.x`                | Binary name/path for the DLA generator                                  |
| `fractal_cmd`    | `fractal.x`              | Binary name/path for the fractal generator                              |
| `goban_cmd`      | `goban.x`                 | Binary name/path for the Go board renderer                              |
| `display_width`  | `600`                      | **Must match the physical panel's pixel width** — see Troubleshooting   |
| `display_height` | `448`                        | **Must match the physical panel's pixel height** — see Troubleshooting  |
| `log_level`      | `info`                        | `debug` \| `info` \| `warning` \| `error`                               |

> ⚠️ `display_width`/`display_height` must match your PhotoPainter's actual
> panel resolution. A mismatch here is a common cause of the device
> rejecting pushed images with a generic error — double-check against your
> hardware's spec sheet if pushes are failing.

---

## Usage

### Web dashboard

Open `http://<home-assistant-host>:8765/ui`:

- **Home** — pick the active method (DLA / Fractal / Go), set the update
  period and frames-per-update, enable the scheduler, and see live status.
- **DLA / Fractal / Go pages** — each exposes exactly the flags that
  generator's binary accepts (colors, zoom mode, board style, SGF game
  selection, etc.), plus a manual "Generate & push" button.

### From Home Assistant

```yaml
# Advance the DLA sequence one frame and push it
service: photopainter_art.generate_art
data:
  art_type: dla

# Render a single fractal frame
service: photopainter_art.generate_art
data:
  art_type: fractal
  mb_fg: white
  mb_bg: black
  mb_mode: single

# Render the current Go game's next move
service: photopainter_art.generate_art
data:
  art_type: goban
  goban_source: library
```

Combine with an automation trigger (e.g. `time_pattern`) if you'd rather
schedule pushes from HA than use the add-on's built-in scheduler.

---

## Development

The generator binaries are plain Go programs under `src/`; the Dockerfile
builds them with `go build` and copies them into the sidecar image. To
iterate locally without rebuilding the container:

```bash
cd src/fractal && go build -o fractal.x .
cd src/dla     && go build -o dla.x .
cd src/goban   && go build -o goban.x .

export STATE_DIR=/tmp/state SGF_DIR=/tmp/sgf PORT=8765
export DLA_CMD=./dla.x FRACTAL_CMD=./fractal.x GOBAN_CMD=./goban.x
export DISPLAY_WIDTH=600 DISPLAY_HEIGHT=448
export PHOTOFRAME_HOST=photoframe.local
export LOG_LEVEL=debug
python3 algorithm_art/main.py
```

Then browse to `http://localhost:8765/ui`.

---

## Troubleshooting

Set the add-on's `log_level` option to `debug` for full diagnostics. The
sidecar logs, per request:

- The exact command run for each generator, its exit code, elapsed time,
  and full stdout/stderr — useful when a binary exits `0` but produces no
  usable output.
- A directory listing of the generator's working directory if the expected
  output file is missing or empty.
- On every push to the device: the BMP's actual width/height/bit-depth/
  compression, compared against the configured `display_width`/
  `display_height`, plus the device's raw response body when it rejects an
  image — the fastest way to tell a dimension mismatch apart from a format
  problem.

---

## License

TBD.
