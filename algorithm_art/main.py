"""AlgorithmArt sidecar — Flask API + Web UI.

Generator endpoints (called by the HA integration and the Web UI):
    GET  /health
    GET  /status               — full state snapshot for polling
    POST /generate/dla         { "frame": N }
    POST /generate/dla/reset   {}
    POST /generate/fractal     { "fg", "bg", "single", "frames", "has_state" }
    POST /fractal/reset        {}
    POST /generate/goban       { goban params … }
    POST /goban/mode           { "mode": "random"|"sequential"|"manual" }
    POST /goban/select         { "game_id": N }
    POST /goban/restart        {}
    POST /goban/skip           {}
    POST /goban/move           { "move": N }
    GET  /goban/games          — list of all games from sgf_directory.py
    POST /push                 raw image bytes → forwarded to photoframe

Web UI:
    GET  /ui                   — full management dashboard
    POST /ui/generate          { art_type, … } — generate + push from UI
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import sys
import os
sys.path.insert(0, '/app')  # ensure sibling modules are importable

import requests
from flask import Flask, Response, jsonify, request

from goban_state import GobanStateManager
from web_ui import ui as ui_blueprint

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("algorithm_art")

app = Flask(__name__)
app.register_blueprint(ui_blueprint)

# ── Config from env ──────────────────────────────────────────────────────────
DLA_CMD          = os.environ.get("DLA_CMD",          "dla.x")
FRACTAL_CMD      = os.environ.get("FRACTAL_CMD",      "fractalgen.x")
GOBAN_CMD        = os.environ.get("GOBAN_CMD",        "goban.x")
DEFAULT_WIDTH    = int(os.environ.get("DISPLAY_WIDTH",  "600"))
DEFAULT_HEIGHT   = int(os.environ.get("DISPLAY_HEIGHT", "448"))
PHOTOFRAME_HOST  = os.environ.get("PHOTOFRAME_HOST",  "photoframe.local")
STATE_DIR        = Path(os.environ.get("STATE_DIR",   "/data/state"))
PORT             = int(os.environ.get("PORT", "8765"))

FRACTAL_STATE_FILE = STATE_DIR / "fractal_state.json"
SGF_MAX_BYTES      = 2 * 1024 * 1024

# Shared goban state manager (persists across requests)
_goban = GobanStateManager()

# Simple in-memory counters for status endpoint
_dla_next_frame  = 1
_fractal_zoom_step = 0
_last_source     = "generative"
_last_art_type   = "dla"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _available(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(argv: list[str]) -> None:
    cmd_str = " ".join(str(a) for a in argv)
    _LOGGER.info("Running: %s", cmd_str)
    result = subprocess.run(
        [str(a) for a in argv],
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {argv[0]!r}\n{stderr}"
        )


# ── Health / status ───────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "generators": {
            "dla":     _available(DLA_CMD),
            "fractal": _available(FRACTAL_CMD),
            "goban":   _available(GOBAN_CMD),
        },
    })


@app.get("/status")
def status():
    """Full state snapshot — polled by the Web UI every 8 seconds."""
    global _dla_next_frame, _fractal_zoom_step, _last_source, _last_art_type

    gs = _goban.state
    current_id = gs.get("current_game_id")
    game_name  = "—"
    game_path  = "—"
    if current_id:
        game = next((g for g in _goban.games if g["id"] == current_id), None)
        if game:
            game_name = game.get("filename", "—")
            game_path = game.get("original_path", "—")

    return jsonify({
        "image_source": _last_source,
        "art_type":     _last_art_type,
        "dla": {
            "next_frame": _dla_next_frame,
            "sequence_length": 120,
        },
        "fractal": {
            "zoom_step": _fractal_zoom_step,
            "state_exists": FRACTAL_STATE_FILE.exists(),
        },
        "goban": {
            "selection_mode":  gs.get("selection_mode", "random"),
            "current_game_id": current_id,
            "game_name":       game_name,
            "game_path":       game_path,
            "current_move":    gs.get("current_move", 0),
            "total_moves":     gs.get("total_moves", 0),
            "hold_counter":    gs.get("hold_counter", 0),
        },
    })


# ── DLA ───────────────────────────────────────────────────────────────────────

@app.post("/generate/dla")
def generate_dla():
    global _dla_next_frame, _last_source, _last_art_type

    if not _available(DLA_CMD):
        return jsonify({"error": f"{DLA_CMD!r} not found"}), 503

    data  = request.get_json(force=True) or {}
    raw_frame = data.get("frame", None)
    try:
        frame = int(raw_frame) if raw_frame not in (None, "__next__") else _dla_next_frame
    except (ValueError, TypeError):
        frame = _dla_next_frame

    if not (1 <= frame <= 120):
        return jsonify({"error": "frame must be 1–120"}), 400

    out_dir = tempfile.mkdtemp(prefix="dla_")
    try:
        if frame == 1:
            _LOGGER.info("DLA: --init")
            _run([DLA_CMD, out_dir, "--init"])

        _LOGGER.info("DLA: --to %d", frame)
        _run([DLA_CMD, out_dir, "--to", str(frame)])

        bmp = Path(out_dir) / "latest_display.bmp"
        if not bmp.exists() or bmp.stat().st_size == 0:
            return jsonify({"error": "DLA produced no output"}), 500

        data_bytes = bmp.read_bytes()

        # Advance counter (wraps at 120 back to 1)
        _dla_next_frame = (frame % 120) + 1
        _last_source    = "generative"
        _last_art_type  = "dla"

        _LOGGER.info("DLA: returning %d bytes, next frame=%d", len(data_bytes), _dla_next_frame)
        return Response(data_bytes, mimetype="image/bmp")

    except RuntimeError as exc:
        _LOGGER.error("DLA failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


@app.post("/generate/dla/reset")
def dla_reset():
    global _dla_next_frame
    _dla_next_frame = 1
    _LOGGER.info("DLA: sequence reset to frame 1")
    return jsonify({"status": "reset", "next_frame": 1})


# ── Fractal ───────────────────────────────────────────────────────────────────

@app.post("/generate/fractal")
def generate_fractal():
    global _fractal_zoom_step, _last_source, _last_art_type

    if not _available(FRACTAL_CMD):
        return jsonify({"error": f"{FRACTAL_CMD!r} not found"}), 503

    data      = request.get_json(force=True) or {}
    fg        = data.get("fg", "white")
    bg        = data.get("bg", "black")
    single    = bool(data.get("single", True))
    frames    = int(data.get("frames", 1))
    has_state = bool(data.get("has_state", False))

    out_dir  = tempfile.mkdtemp(prefix="fractal_")
    out_path = Path(out_dir)
    state_in = out_path / "state.json"

    try:
        if has_state and FRACTAL_STATE_FILE.exists():
            shutil.copy2(FRACTAL_STATE_FILE, state_in)
            _LOGGER.info("Fractal: loaded zoom state")

        argv = [
            FRACTAL_CMD,
            "-width",  str(DEFAULT_WIDTH),
            "-height", str(DEFAULT_HEIGHT),
            "-out",    str(out_dir),
            "-fg",     fg,
            "-bg",     bg,
        ]
        if single:
            argv.append("-single")
        else:
            argv += ["-frames", str(max(1, frames))]
        if has_state and state_in.exists():
            argv += ["-state", str(state_in)]

        _run(argv)

        bmp = out_path / "current.bmp"
        if not bmp.exists() or bmp.stat().st_size == 0:
            return jsonify({"error": "fractalgen.x produced no output"}), 500

        data_bytes = bmp.read_bytes()

        if has_state and state_in.exists():
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(state_in, FRACTAL_STATE_FILE)
            _fractal_zoom_step += 1
            _LOGGER.info("Fractal: saved zoom state (step %d)", _fractal_zoom_step)

        _last_source   = "generative"
        _last_art_type = "fractal"
        _LOGGER.info("Fractal: returning %d bytes", len(data_bytes))
        return Response(data_bytes, mimetype="image/bmp")

    except RuntimeError as exc:
        _LOGGER.error("Fractal failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


@app.post("/fractal/reset")
def fractal_reset():
    global _fractal_zoom_step
    if FRACTAL_STATE_FILE.exists():
        FRACTAL_STATE_FILE.unlink()
    _fractal_zoom_step = 0
    _LOGGER.info("Fractal: zoom state deleted")
    return jsonify({"status": "reset"})


# ── Goban ─────────────────────────────────────────────────────────────────────

@app.get("/goban/games")
def goban_games():
    """Return full game list for the Web UI table."""
    return jsonify(_goban.games)


@app.post("/goban/mode")
def goban_mode():
    data = request.get_json(force=True) or {}
    mode = data.get("mode", "random")
    try:
        _goban.set_mode(mode)
        return jsonify({"status": "ok", "mode": mode})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/goban/select")
def goban_select():
    data    = request.get_json(force=True) or {}
    game_id = int(data.get("game_id", 0))
    try:
        game = _goban.select_game(game_id)
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

    data = request.get_json(force=True) or {}

    # Determine SGF source: "file" = use GobanStateManager (default),
    # other values (library, url, inline) handled directly.
    sgf_source = data.get("goban_source", data.get("sgf_source", "file"))

    try:
        if sgf_source == "file":
            sgf_text, move = _goban.next_frame()
        elif sgf_source == "inline":
            sgf_text = data.get("sgf_text", "").strip()
            if not sgf_text:
                return jsonify({"error": "sgf_source is 'inline' but sgf_text is empty"}), 400
            move = int(data.get("move", 0))
        elif sgf_source == "library":
            from sgf_library import _LIBRARY
            lib_id   = data.get("library_id", "")
            sgf_text = _LIBRARY.get(lib_id) or next(iter(_LIBRARY.values()), "")
            if not sgf_text:
                return jsonify({"error": "Library is empty"}), 500
            move = int(data.get("move", 0))
        elif sgf_source == "url":
            url = data.get("sgf_url", "").strip()
            if not url:
                return jsonify({"error": "sgf_url is empty"}), 400
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            if len(resp.content) > SGF_MAX_BYTES:
                return jsonify({"error": "SGF download too large"}), 400
            sgf_text = resp.content.decode("utf-8", errors="replace").strip()
            move     = int(data.get("move", 0))
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
            "-white-color",    data.get("white_color",     "green"),
            "-black-color",    data.get("black_color",     "black"),
            "-grid-thickness", str(int(data.get("grid_thickness", 1))),
            "-highlight",      data.get("highlight",       "ring"),
        ])

        if not output_bmp.exists() or output_bmp.stat().st_size == 0:
            return jsonify({"error": "goban.x produced no output"}), 500

        data_bytes = output_bmp.read_bytes()
        _last_source   = "generative"
        _last_art_type = "goban"
        _LOGGER.info("Goban: returning %d bytes (move %d)", len(data_bytes), move)
        return Response(data_bytes, mimetype="image/bmp")

    except RuntimeError as exc:
        _LOGGER.error("Goban failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Device push ───────────────────────────────────────────────────────────────

@app.post("/push")
def push_to_device():
    """Forward raw image bytes to the photoframe's /api/display-image.

    The target host defaults to PHOTOFRAME_HOST env var but can be
    overridden per-call with a ?host= query parameter — the HA integration
    passes the hostname configured in its config flow this way.
    """
    image_data = request.get_data()
    if not image_data:
        return jsonify({"error": "No image data"}), 400

    # Allow per-call host override from the HA integration
    target_host = request.args.get("host") or PHOTOFRAME_HOST

    if image_data[:2] == b"BM":
        content_type = "image/bmp"
    elif image_data[:8] == b"\x89PNG\r\n\x1a\n":
        content_type = "image/png"
    else:
        content_type = request.content_type or "image/jpeg"

    device_url = f"http://{target_host}/api/display-image"
    _LOGGER.info("Pushing %d bytes (%s) to %s", len(image_data), content_type, device_url)

    try:
        resp = requests.post(
            device_url,
            data=image_data,
            headers={"Content-Type": content_type},
            timeout=60,
        )
        if resp.status_code == 200:
            return jsonify({"status": "ok"})
        return jsonify({"error": f"Device returned HTTP {resp.status_code}"}), 502
    except requests.exceptions.ConnectionError as exc:
        return jsonify({"error": f"Cannot reach device at {target_host}: {exc}"}), 503
    except requests.exceptions.Timeout:
        return jsonify({"error": "Device push timed out"}), 504


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _LOGGER.info(
        "AlgorithmArt starting on :%d  "
        "(dla=%s  fractal=%s  goban=%s  device=%s)",
        PORT, DLA_CMD, FRACTAL_CMD, GOBAN_CMD, PHOTOFRAME_HOST,
    )
    _LOGGER.info("Web UI available at http://localhost:%d/ui", PORT)
    app.run(host="0.0.0.0", port=PORT)
