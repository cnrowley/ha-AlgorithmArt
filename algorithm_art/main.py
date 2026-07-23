"""AlgorithmArt sidecar — Flask API + Web UI + Auto-scheduler.

Endpoints
---------
GET  /health
GET  /status                      full state snapshot, polled by UI every 5s

── DLA ────────────────────────────────────────────────────────────────────────
POST /generate/dla                { "frame": N }
POST /generate/dla/reset          {}

── Fractal ────────────────────────────────────────────────────────────────────
POST /generate/fractal            { "fg", "bg", "single", "frames", "has_state", "seed" }
                                   seed is optional — a fresh random one is generated
                                   per call if omitted, so repeated single-frame renders
                                   don't always produce the same image.
POST /fractal/reset               {}

── Goban ──────────────────────────────────────────────────────────────────────
POST /generate/goban              { goban params … }
GET  /goban/games                 list all games from sgf_directory.py
POST /goban/mode                  { "mode": "random"|"sequential"|"manual" }
POST /goban/select                { "game_id": N }
POST /goban/restart               {}
POST /goban/skip                  {}
POST /goban/move                  { "move": N }

── Moire ──────────────────────────────────────────────────────────────────────
POST /generate/moire              { "pattern", "iteration", "width", "height",
                                     "background", "linecolor", "density" }
                                   Always invoked as `moire -animate -iteration N`;
                                   rotation/translation/scale are derived by the
                                   binary itself from the iteration number.
                                   "density" (0.1-6, default 1.0) scales how
                                   tightly-packed the pattern repeats are.
POST /generate/moire/reset        {}  (clears the last moire_state.json — the
                                        iteration counter itself lives in HA)

── Chess ──────────────────────────────────────────────────────────────────────
POST /generate/chess              { chess_source, game, plies_per_frame,
                                     piece_style, white_piece_color,
                                     black_piece_color, light_square,
                                     dark_square, board_background,
                                     grid_color, border_color,
                                     show_coordinates, show_move_text,
                                     show_player_names, show_result }
                                   Runs chess2bmp; see chess_state.py for the
                                   exit-code (0/1/2) handling this implements.
GET  /chess/games                 list all games from the PGN library (scanned
                                   live from both the bundled and user PGN
                                   directories — see chess_state.py)
POST /chess/rescan                {}  re-scan both PGN directories on disk
POST /chess/upload                multipart/form-data, field "file" — upload
                                   a .pgn (single- or multi-game) into the
                                   user library
POST /chess/import-url            { "url", "filename"? } — download a PGN
                                   from a URL into the user library
POST /chess/mode                  { "mode": "random"|"sequential"|"manual" }
POST /chess/select                { "game_id": N }
POST /chess/restart               {}
POST /chess/skip                  {}
POST /chess/move                  { "move": N }   (-1 = final position)

── Scheduler ──────────────────────────────────────────────────────────────────
POST /scheduler/settings          { enabled, interval_seconds, frames_per_update,
                                    active_generator,
                                    fractal_fg, fractal_bg, fractal_mode,
                                    goban_bg, goban_board, goban_white_color,
                                    goban_black_color, goban_grid_thickness,
                                    goban_highlight, goban_mode }
POST /scheduler/trigger           fire immediately

── Device ─────────────────────────────────────────────────────────────────────
POST /push                        raw image bytes → device (?host= override)

── Web UI ─────────────────────────────────────────────────────────────────────
GET  /ui                          management dashboard
POST /ui/generate                 { art_type, … } generate + push from UI
"""

from __future__ import annotations

import logging
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request

sys.path.insert(0, "/app")

from goban_state import GobanStateManager
from chess_state import (
    ChessStateManager, EXIT_OK, EXIT_BOUNDARY, EXIT_FATAL, save_user_pgn,
    PGN_DIR as CHESS_PGN_DIR_PATH, USER_PGN_DIR as CHESS_PGN_USER_DIR_PATH,
)
from scheduler import Scheduler, INTERVAL_PRESETS
from web_ui import ui as ui_blueprint

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("algorithm_art")

app = Flask(__name__)
app.register_blueprint(ui_blueprint)

# ── Config ────────────────────────────────────────────────────────────────────
DLA_CMD         = os.environ.get("DLA_CMD",         "dla.x")
FRACTAL_CMD     = os.environ.get("FRACTAL_CMD",     "fractal.x")
GOBAN_CMD       = os.environ.get("GOBAN_CMD",       "goban.x")
MOIRE_CMD       = os.environ.get("MOIRE_CMD",       "moire.x")
CHESS_CMD       = os.environ.get("CHESS_CMD",       "chess2bmp.x")
DEFAULT_WIDTH   = int(os.environ.get("DISPLAY_WIDTH",  "600"))
DEFAULT_HEIGHT  = int(os.environ.get("DISPLAY_HEIGHT", "448"))
PHOTOFRAME_HOST = os.environ.get("PHOTOFRAME_HOST", "photoframe.local")
STATE_DIR       = Path(os.environ.get("STATE_DIR",  "/data/state"))
PORT            = int(os.environ.get("PORT", "8765"))

# ── Master orientation switch ───────────────────────────────────────────────
# A single add-on option ("portrait") controls every generator's notion of
# orientation. chess2bmp has its own native -portrait flag (swapping in a
# fixed 480x800 canvas per the Technical Specification), so it's passed
# straight through. The other generators are driven purely by
# DISPLAY_WIDTH/DISPLAY_HEIGHT, so when portrait mode is on and the operator
# hasn't already supplied portrait-shaped dimensions (width < height), the
# configured width/height are swapped for those generators automatically.
DISPLAY_PORTRAIT = os.environ.get("DISPLAY_PORTRAIT", "false").strip().lower() in ("1", "true", "yes", "on")
if DISPLAY_PORTRAIT and DEFAULT_WIDTH > DEFAULT_HEIGHT:
    DEFAULT_WIDTH, DEFAULT_HEIGHT = DEFAULT_HEIGHT, DEFAULT_WIDTH

CHESS_PIECE_STYLE = os.environ.get("CHESS_PIECE_STYLE", "shape")
CHESS_SVG_DIR     = os.environ.get("CHESS_SVG_DIR", "")
CHESS_FONT        = os.environ.get("CHESS_FONT", "")

FRACTAL_STATE_FILE = STATE_DIR / "fractal_state.json"
MOIRE_STATE_FILE   = STATE_DIR / "moire_state.json"
SGF_MAX_BYTES      = 2 * 1024 * 1024
DLA_SEQUENCE_LENGTH = 120

# ── Shared state ──────────────────────────────────────────────────────────────
_goban = GobanStateManager()
_chess = ChessStateManager()

_dla_next_frame    = 1
_fractal_zoom_step = 0
_moire_iteration   = 0
_last_source       = "generative"
_last_art_type     = "dla"
# Set whenever chess2bmp exits 1 (fatal). Cleared on the next successful
# call. Surfaced in /status and /health so the web UI / HA can show it,
# and used to gate the scheduler's auto-advance (see _scheduler_generate).
_chess_last_error: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _available(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(argv: list[str], timeout: int = 120,
         allowed_exit_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    """Run a generator binary and return the CompletedProcess.

    Always logs the command, exit code, elapsed time, and stdout/stderr
    (truncated) so that "ran fine but produced nothing useful" failures are
    diagnosable from the add-on log, not just "command failed" ones.

    `allowed_exit_codes` lets a caller treat a specific non-zero exit as an
    expected outcome rather than a failure — e.g. fractal.x exits 10 when
    the zoom sequence is intentionally exhausted, which isn't an error.
    """
    argv_str = [str(a) for a in argv]
    cmd_repr = " ".join(argv_str)
    _LOGGER.info("Running: %s", cmd_repr)
    start = time.monotonic()

    try:
        result = subprocess.run(argv_str, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        _LOGGER.error("Command not found: %r (%s)", argv_str[0], exc)
        raise RuntimeError(f"{argv_str[0]!r} not found on PATH: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        _LOGGER.error(
            "Command timed out after %ss: %s\nstdout so far: %s\nstderr so far: %s",
            timeout, cmd_repr,
            _truncate(exc.stdout), _truncate(exc.stderr),
        )
        raise RuntimeError(f"{argv_str[0]!r} timed out after {timeout}s") from exc

    elapsed = time.monotonic() - start
    stdout = result.stdout.decode(errors="replace").strip()
    stderr = result.stderr.decode(errors="replace").strip()

    _LOGGER.debug(
        "Finished in %.2fs (exit %d): %s\nstdout: %s\nstderr: %s",
        elapsed, result.returncode, cmd_repr, _truncate(stdout), _truncate(stderr),
    )

    if result.returncode not in allowed_exit_codes:
        _LOGGER.error(
            "Command failed (exit %d, %.2fs): %s\nstdout: %s\nstderr: %s",
            result.returncode, elapsed, cmd_repr, _truncate(stdout), _truncate(stderr),
        )
        detail = stderr or stdout or "(no output on stdout/stderr)"
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {argv_str[0]!r}\n{detail}"
        )

    return result


def _truncate(text, limit: int = 4000) -> str:
    if text is None:
        return "(none)"
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    text = text.strip()
    if not text:
        return "(empty)"
    return text if len(text) <= limit else text[:limit] + f"... [truncated, {len(text)} chars total]"


def _log_dir(path, label: str) -> None:
    """Log a directory's contents (name, size, mtime) for diagnostics."""
    p = Path(path)
    if not p.exists():
        _LOGGER.error("%s: directory does not exist: %s", label, p)
        return
    try:
        entries = sorted(p.iterdir())
    except Exception as exc:
        _LOGGER.error("%s: could not list %s: %s", label, p, exc)
        return
    if not entries:
        _LOGGER.warning("%s: directory is empty: %s", label, p)
        return
    lines = []
    for e in entries:
        try:
            st = e.stat()
            lines.append(f"  {e.name}  {st.st_size}B  mtime={st.st_mtime:.0f}")
        except OSError as exc:
            lines.append(f"  {e.name}  <stat failed: {exc}>")
    _LOGGER.info("%s: contents of %s:\n%s", label, p, "\n".join(lines))


def _bmp_info(data: bytes) -> dict | None:
    """Parse a BMP file header + DIB header for diagnostics.

    Returns None if `data` doesn't look like a BMP at all. Any field that
    can't be parsed (truncated file, unusual DIB header) is reported as
    None rather than raising, since this is purely diagnostic.
    """
    if len(data) < 54 or data[:2] != b"BM":
        return None
    try:
        file_size_hdr, data_offset = struct.unpack_from("<I4xI", data, 2)
        dib_size = struct.unpack_from("<I", data, 14)[0]
        info = {
            "file_size_declared": file_size_hdr,
            "file_size_actual":   len(data),
            "data_offset":        data_offset,
            "dib_header_size":    dib_size,
        }
        if dib_size >= 40 and len(data) >= 54:
            width, height, planes, bpp, compression, image_size = \
                struct.unpack_from("<iiHHII", data, 18)
            palette_bytes = data_offset - (14 + dib_size)
            info.update({
                "width":        width,
                "height":       height,
                "planes":       planes,
                "bpp":          bpp,
                "compression":  compression,
                "image_size_declared": image_size,
                "palette_bytes": palette_bytes if palette_bytes >= 0 else None,
                "palette_colors": (palette_bytes // 4) if palette_bytes and palette_bytes > 0 else 0,
            })
        return info
    except struct.error as exc:
        _LOGGER.warning("Could not parse BMP header: %s", exc)
        return None


def _log_bmp_info(data: bytes, label: str, expect_w: int | None = None,
                   expect_h: int | None = None) -> None:
    info = _bmp_info(data)
    if info is None:
        _LOGGER.warning("%s: not a parseable BMP (header=%s)", label, data[:16].hex())
        return

    _LOGGER.info(
        "%s: BMP %sx%s  %dbpp  compression=%d  palette_colors=%d  "
        "data_offset=%d  dib_header=%d  declared_size=%d  actual_size=%d",
        label, info.get("width"), info.get("height"), info.get("bpp", -1),
        info.get("compression", -1), info.get("palette_colors", 0),
        info["data_offset"], info["dib_header_size"],
        info["file_size_declared"], info["file_size_actual"],
    )

    if info["file_size_declared"] != info["file_size_actual"]:
        _LOGGER.warning(
            "%s: BMP header declares %d bytes but %d were actually sent — "
            "file may be truncated/corrupt",
            label, info["file_size_declared"], info["file_size_actual"],
        )
    if info.get("compression") not in (0, None):
        _LOGGER.warning(
            "%s: BMP uses compression=%d (non-zero) — many embedded/e-paper "
            "BMP decoders only support uncompressed (BI_RGB=0)",
            label, info["compression"],
        )
    if expect_w and expect_h and info.get("width") and info.get("height"):
        actual_h = abs(info["height"])
        if info["width"] != expect_w or actual_h != expect_h:
            _LOGGER.warning(
                "%s: BMP is %dx%d but display is configured for %dx%d — "
                "size mismatch can cause the device to reject the image",
                label, info["width"], actual_h, expect_w, expect_h,
            )
    if info.get("bpp") not in (None, 1, 4, 8, 24, 32):
        _LOGGER.warning(
            "%s: unusual bit depth %dbpp", label, info["bpp"],
        )
    if info.get("bpp") in (1, 4, 8) and info.get("palette_colors"):
        _LOGGER.info(
            "%s: BMP is %d-bit paletted (%d colours) — if the device only "
            "accepts 24-bit truecolor BMPs, this is a likely rejection cause; "
            "compare against a working DLA/Goban push's bpp",
            label, info["bpp"], info["palette_colors"],
        )


# ── Scheduler generate function ───────────────────────────────────────────────

def _scheduler_generate(generator: str, state: dict) -> bytes | None:
    """Called by the scheduler on each tick. Returns BMP bytes or None."""
    port = int(os.environ.get("PORT", "8765"))
    base = f"http://localhost:{port}"

    try:
        if generator == "dla":
            resp = requests.post(f"{base}/generate/dla", json={
                "frames_per_update": state.get("frames_per_update", 1),
            }, timeout=180)

        elif generator == "fractal":
            resp = requests.post(f"{base}/generate/fractal", json={
                "fg":        state.get("fractal_fg",   "white"),
                "bg":        state.get("fractal_bg",   "black"),
                "single":    state.get("fractal_mode", "single") == "single",
                "has_state": state.get("fractal_mode", "single") == "zoom_sequence",
            }, timeout=180)

        elif generator == "goban":
            resp = requests.post(f"{base}/generate/goban", json={
                "goban_source":    "file",
                "bg":              state.get("goban_bg",           "white"),
                "board":           state.get("goban_board",         "yellow"),
                "white_color":     state.get("goban_white_color",   "red"),
                "black_color":     state.get("goban_black_color",   "black"),
                "grid_thickness":  state.get("goban_grid_thickness", 1),
                "highlight":       state.get("goban_highlight",     "ring"),
                "moves_per_frame": state.get("frames_per_update",   1),
            }, timeout=180)

        elif generator == "moire":
            # Advance by frames_per_update so the "frames per update" setting
            # behaves the same way it does for the other generators, even
            # though moire itself just takes a single -iteration value.
            step = max(1, int(state.get("frames_per_update", 1) or 1))
            resp = requests.post(f"{base}/generate/moire", json={
                "pattern":    state.get("moire_pattern",    "honeycomb"),
                "background": state.get("moire_background", "white"),
                "linecolor":  state.get("moire_linecolor",  "black"),
                "density":    state.get("moire_density",    1.0),
                "step":       step,
            }, timeout=180)

        elif generator == "chess":
            resp = requests.post(f"{base}/generate/chess", json={
                "chess_source":        "library",
                "plies_per_frame":     state.get("frames_per_update",     1),
                "piece_style":         state.get("chess_piece_style",     CHESS_PIECE_STYLE),
                "white_piece_color":   state.get("chess_white_color",     "white"),
                "black_piece_color":   state.get("chess_black_color",     "black"),
                "light_square":        state.get("chess_light_square",    "white"),
                "dark_square":         state.get("chess_dark_square",     "green"),
                "show_coordinates":    state.get("chess_show_coordinates", False),
                "show_move_text":      state.get("chess_show_move_text",  True),
                "show_player_names":   state.get("chess_show_player_names", True),
                "show_result":         state.get("chess_show_result",    True),
            }, timeout=180)

            # Exit code 1 (FATAL) comes back as HTTP 500 from /generate/chess
            # — per the spec, halt auto-incrementing rather than retrying on
            # every tick. We do that simply by NOT touching the scheduler's
            # "enabled" flag here (auto-retry on the next tick is harmless
            # since state wasn't advanced) but we DO make sure the failure
            # is loud: it's already logged inside generate_chess, and the
            # error message is in _chess_last_error / persistent_notification
            # territory on the HA side (see docs).
            if resp.status_code != 200:
                try:
                    err = resp.json().get("error", f"HTTP {resp.status_code}")
                except Exception:
                    err = f"HTTP {resp.status_code}"
                _LOGGER.error("Chess generator failed (fatal, state not advanced): %s", err)
                return None

        else:
            _LOGGER.error("Unknown generator: %s", generator)
            return None

        if resp.status_code == 200:
            return resp.content
        try:
            err = resp.json().get("error", f"HTTP {resp.status_code}")
        except Exception:
            err = f"HTTP {resp.status_code}"
        _LOGGER.error("Generator %s failed: %s", generator, err)
        return None

    except Exception as exc:
        _LOGGER.error("Scheduler generate error: %s", exc)
        return None


# ── Scheduler singleton ───────────────────────────────────────────────────────
_scheduler = Scheduler(generate_fn=_scheduler_generate)


# ── Health / status ───────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "build": BUILD_MARKER,
        "generators": {
            "dla":     _available(DLA_CMD),
            "fractal": _available(FRACTAL_CMD),
            "goban":   _available(GOBAN_CMD),
            "moire":   _available(MOIRE_CMD),
            "chess":   _available(CHESS_CMD),
        },
    })


@app.get("/status")
def status():
    gs  = _goban.state
    sch = _scheduler.state

    current_id = gs.get("current_game_id")
    game_name  = "—"
    game_path  = "—"
    if current_id:
        game = next((g for g in _goban.games if g["id"] == current_id), None)
        if game:
            game_name = game.get("filename", "—")
            game_path = game.get("original_path", "—")

    cs = _chess.state
    chess_current_id = cs.get("current_game_id")
    chess_game_name  = "—"
    chess_event      = "—"
    if chess_current_id:
        cg = next((g for g in _chess.games if g["id"] == chess_current_id), None)
        if cg:
            chess_game_name = cg.get("filename", "—")
            chess_event     = cg.get("event", "—")

    return jsonify({
        "image_source": _last_source,
        "art_type":     _last_art_type,
        "display": {
            "width":    DEFAULT_WIDTH,
            "height":   DEFAULT_HEIGHT,
            "portrait": DISPLAY_PORTRAIT,
        },
        "dla": {
            "next_frame":      _dla_next_frame,
            "sequence_length": 120,
        },
        "fractal": {
            "zoom_step":    _fractal_zoom_step,
            "state_exists": FRACTAL_STATE_FILE.exists(),
        },
        "moire": {
            "iteration":    _moire_iteration,
            "state_exists": MOIRE_STATE_FILE.exists(),
        },
        "goban": {
            "selection_mode":  gs.get("selection_mode", "random"),
            "current_game_id": current_id,
            "game_name":       game_name,
            "game_path":       game_path,
            "current_move":    gs.get("current_move", 0),
            "total_moves":     gs.get("total_moves",  0),
        },
        "chess": {
            "selection_mode":  cs.get("selection_mode", "random"),
            "current_game_id": chess_current_id,
            "game_name":       chess_game_name,
            "event":           chess_event,
            "current_move":    cs.get("current_move", 0),
            "total_moves":     cs.get("total_moves",  0),
            "last_error":      _chess_last_error,
        },
        "scheduler": {
            "enabled":           sch.get("enabled",           False),
            "interval_seconds":  sch.get("interval_seconds",  300),
            "frames_per_update": sch.get("frames_per_update", 1),
            "active_generator":  sch.get("active_generator",  "dla"),
            "last_fire":         sch.get("last_fire"),
            "next_fire":         sch.get("next_fire"),
            # Per-generator options (for UI to restore)
            "fractal_fg":            sch.get("fractal_fg",            "white"),
            "fractal_bg":            sch.get("fractal_bg",            "black"),
            "fractal_mode":          sch.get("fractal_mode",          "single"),
            "goban_bg":              sch.get("goban_bg",              "white"),
            "goban_board":           sch.get("goban_board",           "yellow"),
            "goban_white_color":     sch.get("goban_white_color",     "red"),
            "goban_black_color":     sch.get("goban_black_color",     "black"),
            "goban_grid_thickness":  sch.get("goban_grid_thickness",  1),
            "goban_highlight":       sch.get("goban_highlight",       "ring"),
            "goban_mode":            sch.get("goban_mode",            "random"),
            "moire_pattern":         sch.get("moire_pattern",         "honeycomb"),
            "moire_background":      sch.get("moire_background",      "white"),
            "moire_linecolor":       sch.get("moire_linecolor",       "black"),
            "moire_density":         sch.get("moire_density",         1.0),
            "chess_mode":            sch.get("chess_mode",            "random"),
            "chess_piece_style":     sch.get("chess_piece_style",     CHESS_PIECE_STYLE),
            "chess_white_color":     sch.get("chess_white_color",     "white"),
            "chess_black_color":     sch.get("chess_black_color",     "black"),
            "chess_light_square":    sch.get("chess_light_square",    "white"),
            "chess_dark_square":     sch.get("chess_dark_square",     "green"),
            "chess_show_coordinates": sch.get("chess_show_coordinates", False),
            "chess_show_move_text":   sch.get("chess_show_move_text",  True),
            "chess_show_player_names": sch.get("chess_show_player_names", True),
            "chess_show_result":     sch.get("chess_show_result",     True),
            "chess_reset_after_game": sch.get("chess_reset_after_game", True),
        },
        "interval_presets": [{"label": l, "seconds": s} for l, s in INTERVAL_PRESETS],
    })


# ── DLA ───────────────────────────────────────────────────────────────────────

DLA_WORK_DIR = STATE_DIR / "dla_work"


@app.post("/generate/dla")
def generate_dla():
    """Advance the DLA sequence by one frame — or several at once.

    dla.x keeps its own aggregation state as files inside the working
    directory ("out"), so that directory must persist *between* calls —
    it is only (re)created on frame 1 and wiped once the 120-frame
    sequence completes, ready for the next --init.

        ./dla out --init        # frame 1: seed the cluster
        ./dla out --to N        # frames 2..120: grow + render out/current.bmp

    Because dla.x's ``--to N`` grows the existing aggregate all the way up
    to frame N in a single call, "skipping ahead" doesn't require calling
    the binary once per frame — a caller (e.g. the scheduler's "frames per
    update" setting) can just request a higher target frame and dla.x does
    the extra growth internally.
    """
    global _dla_next_frame, _last_source, _last_art_type

    if not _available(DLA_CMD):
        return jsonify({"error": f"{DLA_CMD!r} not found"}), 503

    data = request.get_json(force=True) or {}
    raw  = data.get("frame", None)

    try:
        frames_per_update = max(1, int(data.get("frames_per_update", 1) or 1))
    except (TypeError, ValueError):
        frames_per_update = 1

    starting_new_sequence = False
    try:
        if raw not in (None, "__next__"):
            frame = int(raw)
        else:
            # Normal (non-explicit) advance: jump ahead by frames_per_update
            # instead of always stepping a single frame.
            starting_new_sequence = (_dla_next_frame == 1)
            frame = min(_dla_next_frame + frames_per_update - 1, DLA_SEQUENCE_LENGTH)
    except (ValueError, TypeError):
        starting_new_sequence = (_dla_next_frame == 1)
        frame = _dla_next_frame

    if not (1 <= frame <= DLA_SEQUENCE_LENGTH):
        return jsonify({"error": f"frame must be 1–{DLA_SEQUENCE_LENGTH}"}), 400

    try:
        if starting_new_sequence or frame == 1:
            # Starting a new sequence: wipe any leftover state and re-init
            # with a fresh random seed so each cycle's starting cluster
            # layout differs. This also covers the frames_per_update case
            # where the skip-ahead target frame is > 1 even though we're
            # at the very start of a fresh sequence.
            shutil.rmtree(DLA_WORK_DIR, ignore_errors=True)
            DLA_WORK_DIR.mkdir(parents=True, exist_ok=True)
            seed = random.getrandbits(63)
            _LOGGER.info("DLA: starting new sequence (seed=%d)", seed)
            init_result = _run([DLA_CMD, str(DLA_WORK_DIR), "--init", "--seed", str(seed)])
            _LOGGER.debug(
                "DLA --init stdout: %s\nDLA --init stderr: %s",
                _truncate(init_result.stdout), _truncate(init_result.stderr),
            )

        if not DLA_WORK_DIR.exists():
            # Defensive: frame > 1 requested but no sequence in progress.
            seed = random.getrandbits(63)
            _LOGGER.warning(
                "DLA: frame=%d requested but %s is missing — re-initialising (seed=%d)",
                frame, DLA_WORK_DIR, seed,
            )
            DLA_WORK_DIR.mkdir(parents=True, exist_ok=True)
            _run([DLA_CMD, str(DLA_WORK_DIR), "--init", "--seed", str(seed)])

        to_result = _run([DLA_CMD, str(DLA_WORK_DIR), "--to", str(frame)])
        _LOGGER.debug(
            "DLA --to %d stdout: %s\nDLA --to %d stderr: %s",
            frame, _truncate(to_result.stdout), frame, _truncate(to_result.stderr),
        )

        bmp = DLA_WORK_DIR / "current.bmp"
        if not bmp.exists() or bmp.stat().st_size == 0:
            _LOGGER.error(
                "DLA: expected %s after 'dla.x %s --to %d' (exit %d) but it is %s",
                bmp, DLA_WORK_DIR, frame, to_result.returncode,
                "missing" if not bmp.exists() else "empty (0 bytes)",
            )
            _log_dir(DLA_WORK_DIR, "DLA")
            _LOGGER.error(
                "DLA --to %d stdout: %s\nDLA --to %d stderr: %s",
                frame, _truncate(to_result.stdout), frame, _truncate(to_result.stderr),
            )
            return jsonify({
                "error": "dla.x produced no output",
                "detail": f"expected {bmp} after --to {frame} (exit {to_result.returncode}); "
                          f"see add-on log for stdout/stderr and directory listing",
            }), 500

        data_bytes = bmp.read_bytes()
        _dla_next_frame = (frame % DLA_SEQUENCE_LENGTH) + 1
        _last_source    = "generative"
        _last_art_type  = "dla"

        _LOGGER.info(
            "DLA: %d bytes  frame=%d/%d  next=%d",
            len(data_bytes), frame, DLA_SEQUENCE_LENGTH, _dla_next_frame,
        )
        return Response(data_bytes, mimetype="image/bmp")

    except RuntimeError as exc:
        _LOGGER.error("DLA failed (frame=%d): %s", frame, exc)
        _log_dir(DLA_WORK_DIR, "DLA")
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        _LOGGER.error("DLA unexpected error (frame=%d): %s", frame, exc, exc_info=True)
        _log_dir(DLA_WORK_DIR, "DLA")
        return jsonify({"error": f"Unexpected error: {exc}"}), 500
    finally:
        if frame >= DLA_SEQUENCE_LENGTH:
            # Sequence complete — wipe the working directory so the next
            # cycle starts clean with a fresh --init.
            shutil.rmtree(DLA_WORK_DIR, ignore_errors=True)


@app.post("/generate/dla/reset")
def dla_reset():
    global _dla_next_frame
    _dla_next_frame = 1
    shutil.rmtree(DLA_WORK_DIR, ignore_errors=True)
    return jsonify({"status": "reset", "next_frame": 1})


# ── Fractal ───────────────────────────────────────────────────────────────────

@app.post("/generate/fractal")
def generate_fractal():
    global _fractal_zoom_step, _last_source, _last_art_type

    if not _available(FRACTAL_CMD):
        return jsonify({"error": f"{FRACTAL_CMD!r} not found"}), 503

    data      = request.get_json(force=True) or {}
    fg        = data.get("fg",        "white")
    bg        = data.get("bg",        "black")
    single    = bool(data.get("single",    True))
    frames    = int(data.get("frames",     1))
    has_state = bool(data.get("has_state", False))

    # A fresh random seed every call so a new sequence doesn't always start
    # from the same hardcoded point (fractal.x only actually uses this when
    # there's no existing --state to resume from — see fractal.go). Callers
    # can pass an explicit "seed" to reproduce a specific starting point.
    seed = data.get("seed")
    if seed is None:
        seed = random.getrandbits(63)
    else:
        seed = int(seed)

    out_dir  = tempfile.mkdtemp(prefix="fractal_")
    out_path = Path(out_dir)
    state_in = out_path / "state.json"

    try:
        if has_state and FRACTAL_STATE_FILE.exists():
            shutil.copy2(FRACTAL_STATE_FILE, state_in)
            _LOGGER.debug(
                "Fractal: reusing zoom state from %s (%d bytes)",
                FRACTAL_STATE_FILE, FRACTAL_STATE_FILE.stat().st_size,
            )
        elif has_state:
            _LOGGER.info(
                "Fractal: zoom_sequence requested but no prior state at %s — "
                "starting a fresh zoom (seed=%d)", FRACTAL_STATE_FILE, seed,
            )
        else:
            _LOGGER.info("Fractal: single-frame render (seed=%d)", seed)

        argv = [
            FRACTAL_CMD,
            "-width",  str(DEFAULT_WIDTH),
            "-height", str(DEFAULT_HEIGHT),
            "-out",    str(out_dir),
            "-fg",     fg,
            "-bg",     bg,
            "-seed",   str(seed),
        ]
        if single:
            argv.append("-single")
        else:
            argv += ["-frames", str(max(1, frames))]
        if has_state:
            # Always give fractal.x a --state path when in zoom_sequence
            # mode, even on the very first call of a new sequence when
            # nothing exists there yet — that's how it knows to *create*
            # and persist state.json in the first place. Gating this on
            # state_in.exists() would mean it's never told to save,
            # so the sequence could never bootstrap itself.
            argv += ["-state", str(state_in)]

        exhausted_retry_used = False
        while True:
            result = _run(argv, allowed_exit_codes=(0, 10))
            _LOGGER.debug(
                "Fractal stdout: %s\nFractal stderr: %s",
                _truncate(result.stdout), _truncate(result.stderr),
            )

            if result.returncode == 10:
                # fractal.x's own "structure exhausted / max zoom reached"
                # signal — an expected end to a zoom sequence, not an
                # error. Reset state and immediately start a fresh one so
                # the scheduler keeps cycling seamlessly instead of seeing
                # a failed push.
                if exhausted_retry_used:
                    # A *brand new* random start point also exhausted
                    # immediately — that's unexpected, don't loop forever.
                    raise RuntimeError(
                        "fractal.x reported the zoom exhausted even on a "
                        "freshly-reset start point (exit 10 twice in a row)"
                    )
                _LOGGER.info(
                    "Fractal: zoom sequence exhausted — resetting and "
                    "starting a new one"
                )
                FRACTAL_STATE_FILE.unlink(missing_ok=True)
                state_in.unlink(missing_ok=True)
                seed = random.getrandbits(63)
                argv[argv.index("-seed") + 1] = str(seed)
                exhausted_retry_used = True
                continue

            break

        bmp = out_path / "current.bmp"
        if not bmp.exists() or bmp.stat().st_size == 0:
            _LOGGER.error(
                "Fractal: expected %s after '%s' (exit %d) but it is %s",
                bmp, " ".join(str(a) for a in argv), result.returncode,
                "missing" if not bmp.exists() else "empty (0 bytes)",
            )
            _log_dir(out_path, "Fractal")
            _LOGGER.error(
                "Fractal stdout: %s\nFractal stderr: %s",
                _truncate(result.stdout), _truncate(result.stderr),
            )
            return jsonify({
                "error": "fractal.x produced no output",
                "detail": f"expected {bmp} (exit {result.returncode}); "
                          f"see add-on log for stdout/stderr and directory listing",
            }), 500

        data_bytes = bmp.read_bytes()

        if has_state and state_in.exists():
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(state_in, FRACTAL_STATE_FILE)
            _fractal_zoom_step += 1

        _last_source   = "generative"
        _last_art_type = "fractal"
        _LOGGER.info("Fractal: %d bytes  zoom_step=%d  seed=%d", len(data_bytes), _fractal_zoom_step, seed)
        return Response(data_bytes, mimetype="image/bmp")

    except RuntimeError as exc:
        _LOGGER.error("Fractal failed: %s", exc)
        _log_dir(out_path, "Fractal")
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        _LOGGER.error("Fractal unexpected error: %s", exc, exc_info=True)
        _log_dir(out_path, "Fractal")
        return jsonify({"error": f"Unexpected error: {exc}"}), 500
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


@app.post("/fractal/reset")
def fractal_reset():
    global _fractal_zoom_step
    if FRACTAL_STATE_FILE.exists():
        FRACTAL_STATE_FILE.unlink()
    _fractal_zoom_step = 0
    return jsonify({"status": "reset"})


# ── Moire ─────────────────────────────────────────────────────────────────────
#
# moire is a standalone CLI renderer with no interactive prompts and fully
# deterministic output for a given -iteration. All configuration (pattern,
# colours, size) is stateless per call; only the iteration counter needs to
# keep advancing so the moire pattern keeps evolving. When a caller (e.g.
# HA's own MoireSequenceManager) already tracks the iteration itself it can
# pass it explicitly; otherwise this endpoint auto-advances its own counter,
# mirroring how /generate/dla behaves when no explicit frame is given.

@app.post("/generate/moire")
def generate_moire():
    global _moire_iteration, _last_source, _last_art_type
    _LOGGER.info("MOIRE: " + str(MOIRE_CMD))

    if not _available(MOIRE_CMD):
        return jsonify({"error": f"{MOIRE_CMD!r} not found"}), 503

    data    = request.get_json(force=True) or {}
    pattern = data.get("pattern", "honeycomb")
    bg      = data.get("background", "white")
    line    = data.get("linecolor",  "black")
    width   = int(data.get("width",  DEFAULT_WIDTH)  or DEFAULT_WIDTH)
    height  = int(data.get("height", DEFAULT_HEIGHT) or DEFAULT_HEIGHT)

    # Pattern density: >1 packs the pattern tighter (more repeats), <1
    # spreads it out. Clamped to the same 0.1-6 range moire.go itself
    # validates, so a bad value fails fast here with a clear message
    # instead of as an opaque exit-1 from the binary.
    try:
        density = float(data.get("density", 1.0) or 1.0)
    except (TypeError, ValueError):
        return jsonify({"error": "density must be a number"}), 400
    if not (0.1 <= density <= 6):
        return jsonify({"error": "density must be between 0.1 and 6"}), 400

    raw = data.get("iteration", None)
    if raw is not None:
        try:
            iteration = int(raw)
        except (TypeError, ValueError):
            return jsonify({"error": "iteration must be an integer"}), 400
    else:
        try:
            step = max(1, int(data.get("step", 1) or 1))
        except (TypeError, ValueError):
            step = 1
        iteration = _moire_iteration
        _moire_iteration += step

    out_dir  = tempfile.mkdtemp(prefix="moire_")
    out_path = Path(out_dir)
    bmp      = out_path / "current.bmp"
    state    = out_path / "moire_state.json"

    try:
        argv = [
            MOIRE_CMD,
            "-animate",
            "-iteration",  str(iteration),
            "-pattern",    pattern,
            "-width",      str(width),
            "-height",     str(height),
            "-background", bg,
            "-linecolor",  line,
            "-density",    str(density),
            "-output",     str(bmp),
            "-state",      str(state),
        ]
        result = _run(argv)
        _LOGGER.debug(
            "Moire stdout: %s\nMoire stderr: %s",
            _truncate(result.stdout), _truncate(result.stderr),
        )

        if not bmp.exists() or bmp.stat().st_size == 0:
            _LOGGER.error(
                "Moire: expected %s after '%s' (exit %d) but it is %s",
                bmp, " ".join(str(a) for a in argv), result.returncode,
                "missing" if not bmp.exists() else "empty (0 bytes)",
            )
            _log_dir(out_path, "Moire")
            return jsonify({
                "error": "moire produced no output",
                "detail": f"expected {bmp} (exit {result.returncode}); "
                          f"see add-on log for stdout/stderr and directory listing",
            }), 500

        data_bytes = bmp.read_bytes()

        # Persist the state file for debugging/inspection (best-effort —
        # this is purely diagnostic, moire itself is fully deterministic
        # from -iteration alone so losing this file changes nothing).
        if state.exists():
            try:
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(state, MOIRE_STATE_FILE)
            except OSError as exc:
                _LOGGER.warning("Moire: could not persist state file: %s", exc)

        _last_source   = "generative"
        _last_art_type = "moire"
        _LOGGER.info(
            "Moire: %d bytes  pattern=%s  iteration=%d  bg=%s  line=%s  density=%g",
            len(data_bytes), pattern, iteration, bg, line, density,
        )
        return Response(data_bytes, mimetype="image/bmp")

    except RuntimeError as exc:
        _LOGGER.error("Moire failed (iteration=%d): %s", iteration, exc)
        _log_dir(out_path, "Moire")
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        _LOGGER.error("Moire unexpected error (iteration=%d): %s", iteration, exc, exc_info=True)
        _log_dir(out_path, "Moire")
        return jsonify({"error": f"Unexpected error: {exc}"}), 500
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


@app.post("/generate/moire/reset")
def moire_reset():
    global _moire_iteration
    _moire_iteration = 0
    if MOIRE_STATE_FILE.exists():
        MOIRE_STATE_FILE.unlink()
    return jsonify({"status": "reset", "iteration": 0})


# ── Goban ─────────────────────────────────────────────────────────────────────

@app.get("/goban/games")
def goban_games():
    return jsonify(_goban.games)


@app.post("/goban/mode")
def goban_mode():
    data = request.get_json(force=True) or {}
    try:
        _goban.set_mode(data.get("mode", "random"))
        return jsonify({"status": "ok"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/goban/select")
def goban_select():
    data = request.get_json(force=True) or {}
    try:
        game = _goban.select_game(int(data.get("game_id", 0)))
        return jsonify({"status": "ok", "game": game})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/goban/restart")
def goban_restart():
    _goban.restart_current_game()
    return jsonify({"status": "ok"})


@app.post("/goban/skip")
def goban_skip():
    _goban.skip_to_next_game()
    return jsonify({"status": "ok"})


@app.post("/goban/move")
def goban_move():
    data = request.get_json(force=True) or {}
    move = int(data.get("move", 0))
    _goban.set_move(move)
    return jsonify({"status": "ok", "move": move})


@app.post("/generate/goban")
def generate_goban():
    global _last_source, _last_art_type

    if not _available(GOBAN_CMD):
        return jsonify({"error": f"{GOBAN_CMD!r} not found"}), 503

    data       = request.get_json(force=True) or {}
    sgf_source = data.get("goban_source", data.get("sgf_source", "file"))

    try:
        if sgf_source == "file":
            moves_per_frame = int(data.get("moves_per_frame", data.get("frames_per_update", 1)) or 1)
            sgf_text, move = _goban.next_frame(moves_per_frame)
        elif sgf_source == "inline":
            sgf_text = data.get("sgf_text", "").strip()
            if not sgf_text:
                return jsonify({"error": "sgf_text is empty"}), 400
            move = int(data.get("move", 0))
        elif sgf_source == "url":
            url = data.get("sgf_url", "").strip()
            if not url:
                return jsonify({"error": "sgf_url is empty"}), 400
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            sgf_text = resp.content.decode("utf-8", errors="replace").strip()
            move = int(data.get("move", 0))
        else:
            return jsonify({"error": f"Unknown sgf_source: {sgf_source!r}"}), 400
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    work_dir   = tempfile.mkdtemp(prefix="goban_")
    work_path  = Path(work_dir)
    sgf_file   = work_path / "game.sgf"
    output_bmp = work_path / "frame.bmp"

    try:
        sgf_file.write_text(sgf_text, encoding="utf-8")

        _run([
            GOBAN_CMD,
            "-input",          str(sgf_file),
            "-move",           str(move),
            "-output",         str(output_bmp),
            "-bg",             data.get("bg",             "white"),
            "-board",          data.get("board",           "yellow"),
            "-white-color",    data.get("white_color",     "red"),
            "-black-color",    data.get("black_color",     "black"),
            "-grid-thickness", str(int(data.get("grid_thickness", 1))),
            "-highlight",      data.get("highlight",       "ring"),
        ])

        if not output_bmp.exists() or output_bmp.stat().st_size == 0:
            return jsonify({"error": "goban.x produced no output"}), 500

        data_bytes     = output_bmp.read_bytes()
        _last_source   = "generative"
        _last_art_type = "goban"
        _LOGGER.info("Goban: %d bytes (move %d)", len(data_bytes), move)
        return Response(data_bytes, mimetype="image/bmp")

    except RuntimeError as exc:
        _LOGGER.error("Goban failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Chess ─────────────────────────────────────────────────────────────────────
#
# chess2bmp replays a PGN file up to a target ply and renders an uncompressed
# 24-bit BMP. Its exit-code protocol (see the module docstring in
# chess_state.py) tells us three different things about the SAME successful
# render:
#
#   0  OK           more plies remain in the game after this one
#   2  BOUNDARY     this was the last ply (GAME_OVER) or -move was past the
#                   end of the game (PAST_END) — the image is still valid
#   1  FATAL        chess2bmp could not produce an image at all (bad PGN,
#                   missing font/SVG dir, invalid flags, ...)
#
# generate_chess() below implements exactly the "Exit Code Response Logic"
# from the spec: 0/2 return the rendered image and advance state (2 also
# resets/advances to the next game once the hold period elapses, handled
# inside ChessStateManager); 1 does NOT advance state, is logged with full
# stderr, and is surfaced to callers (and thus to the scheduler and HA) as
# an HTTP 500 with the raw chess2bmp error message.

@app.get("/chess/games")
def chess_games():
    return jsonify(_chess.games)


@app.post("/chess/rescan")
def chess_rescan():
    """Re-scan both PGN directories (bundled + user) without restarting
    the add-on. Call this after manually dropping a .pgn file into
    data/chess_pgn/ on disk, or just to pick up edits to an existing file."""
    count = _chess.reload_games()
    return jsonify({"status": "ok", "games": count})


@app.post("/chess/upload")
def chess_upload():
    """Accept a PGN file uploaded from the browser (multipart/form-data,
    field name 'file'), save it into the user PGN library, rescan, and
    return the resulting library entries so the caller can immediately
    show/select the new game(s) — handles multi-game files the same way
    the on-disk scanner does.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded (expected multipart field 'file')"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    content = f.read()
    if len(content) > SGF_MAX_BYTES:  # 2MB ceiling, same limit used for SGF uploads
        return jsonify({"error": f"File too large (max {SGF_MAX_BYTES // 1024 // 1024}MB)"}), 400

    try:
        saved_path = save_user_pgn(f.filename, content)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        _LOGGER.error("Chess upload: failed to save %s: %s", f.filename, exc)
        return jsonify({"error": f"Could not save file: {exc}"}), 500

    count = _chess.reload_games()
    new_games = [g for g in _chess.games if g["filename"] == saved_path.name]
    _LOGGER.info("Chess upload: saved %s, library now has %d game(s)", saved_path.name, count)
    return jsonify({"status": "ok", "filename": saved_path.name, "games": new_games, "total_games": count})


@app.post("/chess/import-url")
def chess_import_url():
    """Download a PGN from a URL, save it into the user PGN library,
    rescan, and return the resulting library entries. Distinct from
    /generate/chess's chess_source="url" (which renders one ply of a
    fetched PGN without saving it) — this permanently adds the game(s)
    to the library so they show up in the game table and participate in
    random/sequential rotation like any other library game.
    """
    data = request.get_json(force=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": f"Could not fetch {url}: {exc}"}), 502

    content = resp.content
    if len(content) > SGF_MAX_BYTES:
        return jsonify({"error": f"Downloaded file too large (max {SGF_MAX_BYTES // 1024 // 1024}MB)"}), 400

    filename_hint = data.get("filename") or url.rsplit("/", 1)[-1] or "imported.pgn"
    try:
        saved_path = save_user_pgn(filename_hint, content)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        _LOGGER.error("Chess import-url: failed to save from %s: %s", url, exc)
        return jsonify({"error": f"Could not save file: {exc}"}), 500

    count = _chess.reload_games()
    new_games = [g for g in _chess.games if g["filename"] == saved_path.name]
    _LOGGER.info("Chess import-url: saved %s from %s, library now has %d game(s)", saved_path.name, url, count)
    return jsonify({"status": "ok", "filename": saved_path.name, "games": new_games, "total_games": count})


@app.post("/chess/mode")
def chess_mode():
    data = request.get_json(force=True) or {}
    try:
        _chess.set_mode(data.get("mode", "random"))
        return jsonify({"status": "ok"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/chess/select")
def chess_select():
    data = request.get_json(force=True) or {}
    raw_id = data.get("game_id")
    if raw_id is None:
        return jsonify({"error": "game_id is required"}), 400
    try:
        game_id = int(raw_id)
    except (TypeError, ValueError):
        return jsonify({"error": f"game_id must be an integer, got {raw_id!r}"}), 400
    try:
        game = _chess.select_game(game_id)
        return jsonify({"status": "ok", "game": game})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/chess/restart")
def chess_restart():
    _chess.restart_current_game()
    return jsonify({"status": "ok"})


@app.post("/chess/skip")
def chess_skip():
    _chess.skip_to_next_game()
    return jsonify({"status": "ok"})


@app.post("/chess/move")
def chess_move():
    data = request.get_json(force=True) or {}
    move = int(data.get("move", 0))
    _chess.set_move(move)
    return jsonify({"status": "ok", "move": move})


@app.post("/generate/chess")
def generate_chess():
    """Render the next chess frame with chess2bmp and return BMP bytes.

    Request body (all optional; sensible defaults applied):
        chess_source     "library" | "url" | "inline"   (default "library")
        pgn_text         raw PGN text, required if chess_source == "inline"
        pgn_url          URL to fetch a PGN from, required if == "url"
        game             1-based game index within the PGN (default 1)
        plies_per_frame  how many plies to advance this call (default 1,
                          mirrors goban's moves_per_frame / the scheduler's
                          "frames per update" setting)
        piece_style      "shape" | "glyph" | "svg"
        white_piece_color / black_piece_color
        light_square / dark_square / board_background
        grid_color / border_color
        show_coordinates / show_move_text / show_player_names / show_result
    """
    global _last_source, _last_art_type, _chess_last_error

    if not _available(CHESS_CMD):
        return jsonify({"error": f"{CHESS_CMD!r} not found"}), 503

    data          = request.get_json(force=True) or {}
    chess_source  = data.get("chess_source", "library")

    work_dir   = tempfile.mkdtemp(prefix="chess_")
    work_path  = Path(work_dir)
    output_bmp = work_path / "frame.bmp"

    try:
        # ── Resolve which PGN file (and target ply) to render ──────────────
        if chess_source == "library":
            plies_per_frame = int(
                data.get("plies_per_frame", data.get("frames_per_update", 1)) or 1
            )
            pgn_path, target_ply = _chess.next_frame(plies_per_frame)
            game = int(_chess.current_game().get("game_index", 1)) if _chess.current_game() else 1

        elif chess_source == "inline":
            pgn_text = data.get("pgn_text", "").strip()
            if not pgn_text:
                return jsonify({"error": "pgn_text is empty"}), 400
            pgn_path = work_path / "inline.pgn"
            pgn_path.write_text(pgn_text, encoding="utf-8")
            target_ply = int(data.get("move", -1))
            game = int(data.get("game", 1))

        elif chess_source == "url":
            url = data.get("pgn_url", "").strip()
            if not url:
                return jsonify({"error": "pgn_url is empty"}), 400
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            pgn_path = work_path / "downloaded.pgn"
            pgn_path.write_text(resp.content.decode("utf-8", errors="replace"), encoding="utf-8")
            target_ply = int(data.get("move", -1))
            game = int(data.get("game", 1))

        else:
            return jsonify({"error": f"Unknown chess_source: {chess_source!r}"}), 400

        # target_ply == -1 means "render final position" (chess2bmp's own
        # convention for -move -1, reused by ChessStateManager for the same
        # purpose during the hold-on-final-position phase).
        argv = [
            CHESS_CMD,
            "-input",  str(pgn_path),
            "-output", str(output_bmp),
            "-game",   str(game),
            "-move",   str(target_ply),
            "-piece-style",       data.get("piece_style",       CHESS_PIECE_STYLE),
            "-white-piece-color", data.get("white_piece_color", "white"),
            "-black-piece-color", data.get("black_piece_color", "black"),
            "-light-square",      data.get("light_square",      "white"),
            "-dark-square",       data.get("dark_square",       "green"),
            "-board-background",  data.get("board_background",  "white"),
            "-grid-color",        data.get("grid_color",        "black"),
            "-border-color",      data.get("border_color",      "black"),
        ]
        if DISPLAY_PORTRAIT:
            argv.append("-portrait")
        if data.get("piece_style", CHESS_PIECE_STYLE) == "svg" and CHESS_SVG_DIR:
            argv += ["-svg-dir", CHESS_SVG_DIR]
        if CHESS_FONT:
            argv += ["-font", CHESS_FONT]
        if bool(data.get("show_coordinates", False)):
            argv.append("-show-coordinates")
        if bool(data.get("show_move_text", True)):
            argv.append("-show-move-text")
        if bool(data.get("show_player_names", True)):
            argv.append("-show-player-names")
        if bool(data.get("show_result", True)):
            argv.append("-show-result")

        # Exit codes 0 (OK) and 2 (BOUNDARY: GAME_OVER/PAST_END) both mean
        # chess2bmp produced a usable image — only 1 (FATAL) is a real
        # failure. _run() raises RuntimeError for anything outside
        # allowed_exit_codes, which is exactly the "exit 1" case here.
        result = _run(argv, allowed_exit_codes=(EXIT_OK, EXIT_BOUNDARY))
        stdout = result.stdout.decode(errors="replace").strip()
        _LOGGER.debug("chess2bmp stdout: %s\nchess2bmp stderr: %s",
                      _truncate(stdout), _truncate(result.stderr.decode(errors="replace")))

        if not output_bmp.exists() or output_bmp.stat().st_size == 0:
            _LOGGER.error(
                "Chess: expected %s after '%s' (exit %d) but it is %s",
                output_bmp, " ".join(argv), result.returncode,
                "missing" if not output_bmp.exists() else "empty (0 bytes)",
            )
            _log_dir(work_path, "Chess")
            return jsonify({
                "error": "chess2bmp produced no output",
                "detail": f"expected {output_bmp} (exit {result.returncode}); "
                          f"see add-on log for stdout/stderr",
            }), 500

        data_bytes      = output_bmp.read_bytes()
        _chess_last_error = None
        _last_source    = "generative"
        _last_art_type  = "chess"

        boundary = (result.returncode == EXIT_BOUNDARY)
        _LOGGER.info(
            "Chess: %d bytes  game=%d  ply=%d  exit=%d (%s)  status=%s",
            len(data_bytes), game, target_ply, result.returncode,
            "boundary/game-over" if boundary else "ok", stdout or "(no status line)",
        )
        return Response(
            data_bytes,
            mimetype="image/bmp",
            headers={"X-Chess-Status": "GAME_OVER" if boundary else "OK"},
        )

    except RuntimeError as exc:
        # Exit code 1 (FATAL) lands here. Per the spec: log stderr, do NOT
        # advance the move counter, and surface the error so the caller
        # (scheduler or HA service call) can notify the user and halt
        # auto-incrementing rather than silently pushing a stale/garbled
        # image or skipping ahead as if nothing happened.
        _chess_last_error = str(exc)
        _LOGGER.error("Chess FATAL (chess2bmp exit 1): %s", exc)
        _log_dir(work_path, "Chess")
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        _chess_last_error = str(exc)
        _LOGGER.error("Chess unexpected error: %s", exc, exc_info=True)
        _log_dir(work_path, "Chess")
        return jsonify({"error": f"Unexpected error: {exc}"}), 500
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Scheduler ─────────────────────────────────────────────────────────────────

@app.post("/scheduler/settings")
def scheduler_settings():
    data = request.get_json(force=True) or {}
    allowed = {
        "enabled", "interval_seconds", "frames_per_update", "active_generator",
        "fractal_fg", "fractal_bg", "fractal_mode",
        "goban_bg", "goban_board", "goban_white_color", "goban_black_color",
        "goban_grid_thickness", "goban_highlight", "goban_mode",
        "moire_pattern", "moire_background", "moire_linecolor", "moire_density",
        "chess_mode", "chess_piece_style", "chess_white_color", "chess_black_color",
        "chess_light_square", "chess_dark_square", "chess_show_coordinates",
        "chess_show_move_text", "chess_show_player_names", "chess_show_result",
        "chess_reset_after_game",
    }
    updates = {k: v for k, v in data.items() if k in allowed}

    # Defensive server-side clamping — the web UI enforces min/max on its
    # <input> elements, but /scheduler/settings can be hit directly (or by
    # any future client) with unvalidated values. An interval_seconds of 0
    # or less turns the scheduler's sleep loop into a busy loop that hits
    # the generator/device as fast as the CPU allows.
    if "interval_seconds" in updates:
        try:
            updates["interval_seconds"] = max(5, int(updates["interval_seconds"]))
        except (TypeError, ValueError):
            updates["interval_seconds"] = 300
    if "frames_per_update" in updates:
        try:
            updates["frames_per_update"] = min(50, max(1, int(updates["frames_per_update"])))
        except (TypeError, ValueError):
            updates["frames_per_update"] = 1
    if "moire_density" in updates:
        try:
            updates["moire_density"] = min(6.0, max(0.1, float(updates["moire_density"])))
        except (TypeError, ValueError):
            updates["moire_density"] = 1.0

    _scheduler.update(updates)
    return jsonify({"status": "ok", "state": _scheduler.state})


@app.post("/scheduler/trigger")
def scheduler_trigger():
    """Fire the scheduler immediately, regardless of the timer."""
    _scheduler.trigger_now()
    return jsonify({"status": "triggered"})


# ── Device push ───────────────────────────────────────────────────────────────

@app.post("/push")
def push_to_device():
    image_data  = request.get_data()
    if not image_data:
        _LOGGER.error("Push: no image data in request body")
        return jsonify({"error": "No image data"}), 400

    target_host = request.args.get("host") or PHOTOFRAME_HOST

    if image_data[:2] == b"BM":
        content_type = "image/bmp"
    elif image_data[:8] == b"\x89PNG\r\n\x1a\n":
        content_type = "image/png"
    else:
        content_type = request.content_type or "image/jpeg"

    device_url = f"http://{target_host}/api/display-image"
    header_preview = image_data[:16].hex()
    _LOGGER.info(
        "Pushing %d bytes (%s, header=%s) to %s",
        len(image_data), content_type, header_preview, device_url,
    )
    if content_type == "image/bmp":
        _log_bmp_info(image_data, "Push", expect_w=DEFAULT_WIDTH, expect_h=DEFAULT_HEIGHT)

    start = time.monotonic()
    try:
        resp = requests.post(
            device_url,
            data=image_data,
            headers={"Content-Type": content_type},
            timeout=60,
        )
        elapsed = time.monotonic() - start

        if resp.status_code == 200:
            _LOGGER.info("Push OK in %.2fs (%s)", elapsed, device_url)
            return jsonify({"status": "ok"})

        # Device rejected the image — log everything we know about why.
        body_preview = _truncate(resp.text, 2000)
        _LOGGER.error(
            "Device %s returned HTTP %d in %.2fs for a %d-byte %s push\n"
            "response headers: %s\nresponse body: %s",
            device_url, resp.status_code, elapsed, len(image_data), content_type,
            dict(resp.headers), body_preview,
        )
        return jsonify({
            "error": f"Device returned HTTP {resp.status_code}",
            "detail": body_preview,
        }), 502

    except requests.exceptions.ConnectionError as exc:
        _LOGGER.error("Push: cannot reach %s: %s", device_url, exc)
        return jsonify({"error": f"Cannot reach {target_host}: {exc}"}), 503
    except requests.exceptions.Timeout:
        elapsed = time.monotonic() - start
        _LOGGER.error(
            "Push: timed out after %.2fs pushing %d bytes to %s",
            elapsed, len(image_data), device_url,
        )
        return jsonify({"error": "Device push timed out"}), 504
    except Exception as exc:
        _LOGGER.error(
            "Push: unexpected error pushing %d bytes to %s: %s",
            len(image_data), device_url, exc, exc_info=True,
        )
        return jsonify({"error": f"Unexpected push error: {exc}"}), 500


# Bump this whenever a diagnostic/behavioral change is made, so the running
# container's log makes it obvious which build is actually deployed instead
# of having to infer it from which log lines are (or aren't) present.
BUILD_MARKER = "2026-07-22.1-bmp-diagnostics+dla-persist+push-diagnostics+moire+chess"

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _LOGGER.info("AlgorithmArt build: %s", BUILD_MARKER)
    _LOGGER.info(
        "AlgorithmArt starting on :%d  (dla=%s  fractal=%s  goban=%s  moire=%s  chess=%s  device=%s)",
        PORT, DLA_CMD, FRACTAL_CMD, GOBAN_CMD, MOIRE_CMD, CHESS_CMD, PHOTOFRAME_HOST,
    )
    _LOGGER.info(
        "Display: %dx%d (portrait=%s)", DEFAULT_WIDTH, DEFAULT_HEIGHT, DISPLAY_PORTRAIT,
    )
    _LOGGER.info("SGF library: %d games loaded", len(_goban.games))
    _LOGGER.info(
        "PGN library: %d games loaded (bundled=%s, user=%s)",
        len(_chess.games), CHESS_PGN_DIR_PATH, CHESS_PGN_USER_DIR_PATH,
    )
    _LOGGER.info("Web UI: http://localhost:%d/ui", PORT)
    _scheduler.start()
    app.run(host="0.0.0.0", port=PORT)

