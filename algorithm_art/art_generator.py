"""Art generator — HTTP client for the AlgorithmArt sidecar.

Calls the Flask sidecar running in the HA add-on container and returns
raw BMP bytes.  The sidecar runs the actual generator binaries:
  - dla.x         (DLA diffusion-limited aggregation)
  - fractalgen.x  (Mandelbrot/fractal zoom)
  - goban.x       (Go board position)

Sidecar base URL is read from PHOTOPAINTER_SIDECAR_URL env var,
defaulting to http://localhost:8765.

Endpoints called:
    POST /generate/dla      { "frame": N }
    POST /generate/fractal  { "fg", "bg", "single", "frames", "has_state" }
    POST /generate/goban    { sgf params ... }
    POST /fractal/reset     {}
    GET  /health
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import aiohttp

_LOGGER = logging.getLogger(__name__)

SIDECAR_URL = os.environ.get(
    "PHOTOPAINTER_SIDECAR_URL", "http://localhost:8765"
).rstrip("/")

# ── Display geometry ────────────────────────────────────────────────────────
DISPLAY_WIDTH  = 600
DISPLAY_HEIGHT = 448

# ── DLA sequence config ─────────────────────────────────────────────────────
DLA_SEQUENCE_LENGTH = 120

# ── Fractal colour options (must match fractalgen.go colorMap) ───────────────
FRACTAL_COLOURS = ["black", "white", "green", "blue", "red", "yellow", "orange"]

# Keep MANDELBROT_COLOURS as an alias so any leftover import still works
MANDELBROT_COLOURS = FRACTAL_COLOURS

# ── Goban colour / style option lists ──────────────────────────────────────
GOBAN_BG_COLOURS          = ["white", "black"]
GOBAN_BOARD_COLOURS       = ["yellow", "white"]
GOBAN_WHITE_STONE_COLOURS = ["white", "green", "blue", "red"]
GOBAN_BLACK_STONE_COLOURS = ["black", "red"]
GOBAN_GRID_THICKNESS      = [1, 2]
GOBAN_HIGHLIGHT_MODES     = ["dot", "ring", "none"]


# ── Parameter dataclasses ───────────────────────────────────────────────────

@dataclass
class DLAParams:
    """Parameters for the DLA sequence generator."""
    frame: int = 1      # 1 … DLA_SEQUENCE_LENGTH; frame 1 triggers --init


@dataclass
class FractalParams:
    """Parameters for fractalgen.x.

    ``single=True``  → one frame at current zoom position.
    ``single=False`` → advance one zoom step (uses persistent state in sidecar).
    ``state_path``   → non-empty string means zoom-sequence mode; the actual
                       state file lives in the sidecar's /data/state directory.
    """
    width:      int  = DISPLAY_WIDTH
    height:     int  = DISPLAY_HEIGHT
    fg:         str  = "white"
    bg:         str  = "black"
    single:     bool = True
    frames:     int  = 1
    state_path: str  = ""   # non-empty = zoom sequence mode


# Keep MandelbrotParams as an alias so any leftover import still works
MandelbrotParams = FractalParams


@dataclass
class GobanParams:
    """Parameters for goban.x."""
    sgf_source:     str = "library"
    sgf_text:       str = ""
    library_id:     str = ""
    sgf_url:        str = ""
    move:           int = 0
    bg:             str = "white"
    board:          str = "yellow"
    white_color:    str = "green"
    black_color:    str = "black"
    grid_thickness: int = 1
    highlight:      str = "ring"


# ── Low-level HTTP helper ───────────────────────────────────────────────────

async def _post(endpoint: str, payload: dict) -> bytes:
    """POST JSON to the sidecar; return raw bytes on 200, raise on error."""
    url     = f"{SIDECAR_URL}{endpoint}"
    timeout = aiohttp.ClientTimeout(total=180)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.read()
                    _LOGGER.debug("%s → %d bytes", endpoint, len(data))
                    return data

                try:
                    body = await response.json()
                    msg  = body.get("error", str(body))
                except Exception:
                    msg  = await response.text()

                raise RuntimeError(
                    f"Sidecar {endpoint} returned HTTP {response.status}: {msg}"
                )

    except aiohttp.ClientConnectorError as exc:
        raise RuntimeError(
            f"Cannot reach sidecar at {SIDECAR_URL} — is the "
            f"'AlgorithmArt Generator' add-on running? ({exc})"
        ) from exc
    except aiohttp.ClientError as exc:
        raise RuntimeError(f"HTTP error calling sidecar {endpoint}: {exc}") from exc


# ── Public generator functions ──────────────────────────────────────────────

async def generate_dla(params: DLAParams) -> bytes:
    """Generate a DLA frame and return BMP bytes."""
    _LOGGER.info("DLA: requesting frame %d", params.frame)
    return await _post("/generate/dla", {"frame": params.frame})


async def generate_fractal(params: FractalParams) -> bytes:
    """Generate a fractal frame via fractalgen.x and return BMP bytes."""
    is_seq = bool(params.state_path)
    _LOGGER.info(
        "Fractal: fg=%s bg=%s single=%s zoom_sequence=%s",
        params.fg, params.bg, params.single, is_seq,
    )
    return await _post("/generate/fractal", {
        "fg":        params.fg,
        "bg":        params.bg,
        "single":    params.single,
        "frames":    params.frames,
        "has_state": is_seq,
    })


# Alias so any code still referencing generate_mandelbrot works unchanged
generate_mandelbrot = generate_fractal


async def generate_goban(params: GobanParams) -> bytes:
    """Generate a Goban board image via goban.x and return BMP bytes."""
    _LOGGER.info(
        "Goban: source=%s library_id=%r move=%d",
        params.sgf_source, params.library_id, params.move,
    )
    return await _post("/generate/goban", {
        "sgf_source":     params.sgf_source,
        "library_id":     params.library_id,
        "sgf_url":        params.sgf_url,
        "sgf_text":       params.sgf_text,
        "move":           params.move,
        "bg":             params.bg,
        "board":          params.board,
        "white_color":    params.white_color,
        "black_color":    params.black_color,
        "grid_thickness": params.grid_thickness,
        "highlight":      params.highlight,
    })


async def reset_fractal_zoom() -> None:
    """Tell the sidecar to delete its fractal zoom state file."""
    url     = f"{SIDECAR_URL}/fractal/reset"
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url) as response:
                body = await response.json()
                _LOGGER.info("Fractal reset: %s", body.get("status", "?"))
    except Exception as exc:
        _LOGGER.warning("Failed to reset fractal zoom on sidecar: %s", exc)


# Alias for any code still calling reset_mandelbrot_zoom
reset_mandelbrot_zoom = reset_fractal_zoom


async def sidecar_health() -> dict:
    """Return the sidecar /health JSON, or an error dict if unreachable."""
    url     = f"{SIDECAR_URL}/health"
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                return await response.json()
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)}
