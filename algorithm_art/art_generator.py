"""Art generator — HTTP client for the PhotopainterArt sidecar.

The generator binaries (dla.x, fractal.x, goban.x) run in a separate
HA add-on sidecar container.  This module calls that sidecar's Flask API
and returns raw BMP bytes, exactly as if the binaries had been called
directly.

Sidecar API (default base URL http://localhost:8765):

    POST /generate/dla          { "frame": N }
    POST /generate/fractal   { "fg", "bg", "single", "frames", "has_state" }
    POST /generate/goban        { "sgf_source", "library_id", "sgf_url",
                                  "sgf_text", "move", "bg", "board",
                                  "white_color", "black_color",
                                  "grid_thickness", "highlight" }
    POST /generate/moire        { "pattern", "iteration", "background",
                                  "linecolor", "width", "height" }
    POST /generate/chess        { "chess_source", "game", "move",
                                  "piece_style", "white_piece_color",
                                  "black_piece_color", "light_square",
                                  "dark_square", "board_background",
                                  "grid_color", "border_color",
                                  "show_coordinates", "show_move_text",
                                  "show_player_names", "show_result" }
    POST /fractal/reset      {}
    POST /generate/moire/reset  {}
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

# ── Fractal colour options ───────────────────────────────────────────────
FRACTAL_COLOURS = ["black", "white", "green", "blue", "red", "yellow", "orange"]

# ── Moire pattern / colour option lists ─────────────────────────────────────
# (must match moire's supported -pattern and colour values)
MOIRE_PATTERNS = [
    "honeycomb", "hexdots", "lines", "square", "triangular",
    "kagome", "circles", "spokes", "checkerboard",
]
MOIRE_RECOMMENDED_PATTERNS = ["honeycomb", "hexdots", "circles", "triangular"]
MOIRE_COLOURS = ["white", "black", "red", "green", "blue", "yellow"]

# ── Chess option lists ───────────────────────────────────────────────────────
# (used by HA entity option lists and the service schema; must match
# chess2bmp's AllowedPalette and -piece-style choices)
CHESS_SOURCES          = ["library", "url", "inline"]
CHESS_SELECTION_MODES  = ["random", "sequential", "manual"]
CHESS_PIECE_STYLES     = ["shape", "glyph", "svg"]
CHESS_COLOURS          = ["white", "black", "red", "green", "blue", "yellow"]


# ── Parameter dataclasses ───────────────────────────────────────────────────

@dataclass
class DLAParams:
    """Parameters for the DLA sequence generator."""
    frame: int = 1          # 1 … DLA_SEQUENCE_LENGTH; frame 1 triggers --init


@dataclass
class FractalParams:
    """Parameters for fractal.x.

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
class MoireParams:
    """Parameters for moire.

    moire always runs in ``-animate`` mode when driven from Home Assistant:
    rotation/translation/scale are derived deterministically from
    ``iteration`` by the binary itself, so HA only needs to track a
    monotonically increasing frame counter and the cosmetic options
    (pattern, colours, size, density).

    ``density`` (0.1-6, default 1.0) controls how tightly-packed the
    pattern's repeating unit is — higher values pack more repeats into
    the same canvas (smaller cells/tighter spacing), lower values spread
    it out. Passed straight through as moire's own ``-density`` flag.
    """
    pattern:    str = "honeycomb"
    iteration:  int = 0
    width:      int = DISPLAY_WIDTH
    height:     int = DISPLAY_HEIGHT
    background: str = "white"
    linecolor:  str = "black"
    density:    float = 1.0


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


@dataclass
class ChessParams:
    """Parameters for chess2bmp.

    ``chess_source="library"`` drives the sidecar's own ChessStateManager
    (persistent, advances one game at a time — see chess_state.py); the
    ``game``/``move`` fields below are only meaningful for "url"/"inline"
    sources, where HA is telling the sidecar exactly which ply of exactly
    which PGN text to render. ``move=-1`` renders the final position,
    matching chess2bmp's own convention.

    Orientation (portrait vs. landscape) is a sidecar-wide setting (the
    add-on's "portrait" option — see main.py's DISPLAY_PORTRAIT) rather
    than a per-call parameter, since the PhotoPainter's physical mounting
    doesn't change from one generate call to the next.
    """
    chess_source:       str = "library"
    pgn_text:           str = ""
    pgn_url:            str = ""
    game:               int = 1
    move:               int = -1
    piece_style:        str = "shape"
    white_piece_color:  str = "white"
    black_piece_color:  str = "black"
    light_square:       str = "white"
    dark_square:        str = "green"
    board_background:   str = "white"
    grid_color:         str = "black"
    border_color:       str = "black"
    show_coordinates:   bool = False
    show_move_text:     bool = True
    show_player_names:  bool = True
    show_result:        bool = True


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


async def generate_fractal(params: FractalParams) -> bytes:
    """Generate a Fractal frame via the sidecar and return BMP bytes."""
    is_zoom_sequence = bool(params.state_path)   # non-empty = zoom mode
    _LOGGER.info(
        "Fractal: fg=%s bg=%s single=%s zoom_sequence=%s",
        params.fg, params.bg, params.single, is_zoom_sequence,
    )
    return await _post("/generate/fractal", {
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


async def generate_chess(params: ChessParams) -> tuple[bytes, bool]:
    """Generate a chess frame via the sidecar and return (bmp_bytes, game_over).

    ``game_over`` mirrors chess2bmp's exit code 2 (GAME_OVER / PAST_END,
    surfaced by the sidecar as the ``X-Chess-Status: GAME_OVER`` response
    header) — the image is still valid and should still be displayed, this
    just tells the caller not to expect further progress on this game.

    Exit code 1 (FATAL) is NOT a return value here — the sidecar turns it
    into an HTTP 500 with the chess2bmp stderr as the error message, which
    surfaces as a RuntimeError from _post(), exactly like every other
    generator failure. Callers (see services.py) should catch RuntimeError,
    log it, and — per the spec — avoid auto-incrementing/retrying blindly.
    """
    _LOGGER.info(
        "Chess: source=%s game=%d move=%d piece_style=%s",
        params.chess_source, params.game, params.move, params.piece_style,
    )
    url = f"{SIDECAR_URL}/generate/chess"
    payload = {
        "chess_source":       params.chess_source,
        "pgn_text":           params.pgn_text,
        "pgn_url":            params.pgn_url,
        "game":               params.game,
        "move":               params.move,
        "piece_style":        params.piece_style,
        "white_piece_color":  params.white_piece_color,
        "black_piece_color":  params.black_piece_color,
        "light_square":       params.light_square,
        "dark_square":        params.dark_square,
        "board_background":   params.board_background,
        "grid_color":         params.grid_color,
        "border_color":       params.border_color,
        "show_coordinates":   params.show_coordinates,
        "show_move_text":     params.show_move_text,
        "show_player_names":  params.show_player_names,
        "show_result":        params.show_result,
    }
    timeout = aiohttp.ClientTimeout(total=180)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.read()
                    game_over = response.headers.get("X-Chess-Status") == "GAME_OVER"
                    return data, game_over

                try:
                    body = await response.json()
                    msg = body.get("error", str(body))
                except Exception:
                    msg = await response.text()
                raise RuntimeError(f"Sidecar /generate/chess returned HTTP {response.status}: {msg}")

    except aiohttp.ClientConnectorError as exc:
        raise RuntimeError(
            f"Cannot reach sidecar at {SIDECAR_URL} — is the "
            f"'PhotopainterArt Generator' add-on running? ({exc})"
        ) from exc
    except aiohttp.ClientError as exc:
        raise RuntimeError(f"HTTP error calling sidecar /generate/chess: {exc}") from exc


async def generate_moire(params: MoireParams) -> bytes:
    """Generate a Moire animation frame via the sidecar and return BMP bytes."""
    _LOGGER.info(
        "Moire: pattern=%s iteration=%d bg=%s line=%s density=%g",
        params.pattern, params.iteration, params.background, params.linecolor, params.density,
    )
    return await _post("/generate/moire", {
        "pattern":    params.pattern,
        "iteration":  params.iteration,
        "width":      params.width,
        "height":     params.height,
        "background": params.background,
        "linecolor":  params.linecolor,
        "density":    params.density,
    })


async def reset_moire_sequence() -> None:
    """Tell the sidecar to forget its last Moire state file (cosmetic only —
    the iteration counter itself lives in Home Assistant, see
    generative_art.MoireSequenceManager)."""
    url     = f"{SIDECAR_URL}/generate/moire/reset"
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url) as response:
                body = await response.json()
                _LOGGER.info("Moire reset: %s", body.get("status", "?"))
    except Exception as exc:
        _LOGGER.warning("Failed to reset moire state on sidecar: %s", exc)


async def reset_fractal_zoom() -> None:
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
