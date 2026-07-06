"""Art generator — HTTP client for the PhotopainterArt sidecar.

The generator binaries (dla.x, mandelbrot.x, goban.x) run in a separate
HA add-on sidecar container.  This module calls that sidecar's Flask API
and returns raw BMP bytes, exactly as if the binaries had been called
directly.

Sidecar API (default base URL http://localhost:8765):

    POST /generate/dla          { "frame": N }
    POST /generate/mandelbrot   { "fg", "bg", "single", "frames", "has_state" }
    POST /generate/goban        { "sgf_source", "library_id", "sgf_url",
                                  "sgf_text", "move", "bg", "board",
                                  "white_color", "black_color",
                                  "grid_thickness", "highlight" }
    POST /mandelbrot/reset      {}
    GET  /health

The sidecar URL is read from the PHOTOPAINTER_SIDECAR_URL environment
variable, defaulting to http://localhost:8765.  Set it in the add-on's
run.sh or via HA's configuration if the sidecar runs on a different host.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import aiohttp

_LOGGER = logging.getLogger(__name__)

# ── Sidecar base URL ────────────────────────────────────────────────────────
SIDECAR_URL = os.environ.get(
    "PHOTOPAINTER_SIDECAR_URL", "http://localhost:8765"
).rstrip("/")

# ── Display geometry (informational — sidecar has its own defaults) ─────────
DISPLAY_WIDTH  = 600
DISPLAY_HEIGHT = 448

# ── DLA sequence config ─────────────────────────────────────────────────────
DLA_SEQUENCE_LENGTH = 120

# ── Goban colour / style option lists ──────────────────────────────────────
# (used by HA entity option lists and the service schema)
GOBAN_BG_COLOURS          = ["white", "black"]
GOBAN_BOARD_COLOURS       = ["yellow", "white"]
GOBAN_WHITE_STONE_COLOURS = ["white", "green", "blue", "red"]
GOBAN_BLACK_STONE_COLOURS = ["black", "red"]
GOBAN_GRID_THICKNESS      = [1, 2]
GOBAN_HIGHLIGHT_MODES     = ["dot", "ring", "none"]

# ── Mandelbrot colour options ───────────────────────────────────────────────
MANDELBROT_COLOURS = ["black", "white", "green", "blue", "red", "yellow", "orange"]


# ── Parameter dataclasses ───────────────────────────────────────────────────

@dataclass
class DLAParams:
    """Parameters for the DLA sequence generator."""
    frame: int = 1          # 1 … DLA_SEQUENCE_LENGTH; frame 1 triggers --init


@dataclass
class MandelbrotParams:
    """Parameters for mandelbrot.x.

    ``single=True``  → one frame at current zoom position.
    ``single=False`` → advance one zoom step (uses persistent state file in
                       the sidecar's /data/state directory).
    ``state_path`` is unused here (state lives in the sidecar); kept for
    API compatibility with callers that set it.
    """
    width:      int  = DISPLAY_WIDTH
    height:     int  = DISPLAY_HEIGHT
    fg:         str  = "white"
    bg:         str  = "black"
    single:     bool = True
    frames:     int  = 1
    state_path: str  = ""    # non-empty = zoom sequence mode


@dataclass
class GobanParams:
    """Parameters for goban.x."""
    sgf_source:      str = "library"
    sgf_text:        str = ""
    library_id:      str = ""
    sgf_url:         str = ""
    move:            int = 0
    bg:              str = "white"
    board:           str = "yellow"
    white_color:     str = "green"
    black_color:     str = "black"
    grid_thickness:  int = 1
    highlight:       str = "ring"


# ── Low-level HTTP helper ───────────────────────────────────────────────────

async def _post(endpoint: str, payload: dict) -> bytes:
    """POST JSON to the sidecar; return raw response bytes on success.

    Raises RuntimeError with a clear message on any failure (connection
    error, non-200 status, or JSON error body from the sidecar).
    """
    url = f"{SIDECAR_URL}{endpoint}"
    timeout = aiohttp.ClientTimeout(total=180)   # generators can be slow

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.read()
                    _LOGGER.debug(
                        "%s → %d bytes (Content-Type: %s)",
                        endpoint, len(data),
                        response.headers.get("Content-Type", "?"),
                    )
                    return data

                # Non-200: try to extract the error message from JSON body
                try:
                    body = await response.json()
                    msg = body.get("error", str(body))
                except Exception:
                    msg = await response.text()

                raise RuntimeError(
                    f"Sidecar {endpoint} returned HTTP {response.status}: {msg}"
                )

    except aiohttp.ClientConnectorError as exc:
        raise RuntimeError(
            f"Cannot reach sidecar at {SIDECAR_URL} — is the "
            f"'PhotopainterArt Generator' add-on running? ({exc})"
        ) from exc
    except aiohttp.ClientError as exc:
        raise RuntimeError(f"HTTP error calling sidecar {endpoint}: {exc}") from exc


# ── Public generator functions ──────────────────────────────────────────────

async def generate_dla(params: DLAParams) -> bytes:
    """Generate a DLA frame via the sidecar and return BMP bytes."""
    _LOGGER.info("DLA: requesting frame %d from sidecar", params.frame)
    return await _post("/generate/dla", {"frame": params.frame})


async def generate_mandelbrot(params: MandelbrotParams) -> bytes:
    """Generate a Mandelbrot frame via the sidecar and return BMP bytes."""
    is_zoom_sequence = bool(params.state_path)   # non-empty = zoom mode
    _LOGGER.info(
        "Mandelbrot: fg=%s bg=%s single=%s zoom_sequence=%s",
        params.fg, params.bg, params.single, is_zoom_sequence,
    )
    return await _post("/generate/mandelbrot", {
        "fg":        params.fg,
        "bg":        params.bg,
        "single":    params.single,
        "frames":    params.frames,
        "has_state": is_zoom_sequence,
    })


async def generate_goban(params: GobanParams) -> bytes:
    """Generate a Goban board image via the sidecar and return BMP bytes."""
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


async def reset_mandelbrot_zoom() -> None:
    """Tell the sidecar to delete the fractal zoom state file."""
    url     = f"{SIDECAR_URL}/fractal/reset"
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url) as response:
                body = await response.json()
                _LOGGER.info("Fractal reset: %s", body.get("status", "?"))
    except Exception as exc:
        _LOGGER.warning("Failed to reset fractal zoom on sidecar: %s", exc)


# Alias
reset_fractal_zoom = reset_mandelbrot_zoom


async def push_to_device(image_bytes: bytes, photoframe_host: str) -> None:
    """Tell the sidecar to push image bytes to a specific device host.

    Passes the photoframe_host from the HA config flow as a query param
    so the sidecar uses the correct address for this call.
    """
    url     = f"{SIDECAR_URL}/push?host={photoframe_host}"
    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                data=image_bytes,
                headers={"Content-Type": "image/bmp"},
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    raise RuntimeError(f"Push failed HTTP {response.status}: {body}")
    except aiohttp.ClientError as exc:
        raise RuntimeError(f"Push to sidecar failed: {exc}") from exc


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
