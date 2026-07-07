"""AlgorithmArt sidecar — Flask API + Web UI + Auto-scheduler.

Endpoints
---------
GET  /health
GET  /status                      full state snapshot, polled by UI every 5s

── DLA ────────────────────────────────────────────────────────────────────────
POST /generate/dla                { "frame": N, "walkers": N }
POST /generate/dla/reset          {}

── Fractal ────────────────────────────────────────────────────────────────────
POST /generate/fractal            { "fg", "bg", "single", "frames", "has_state" }
POST /fractal/reset               {}

── Goban ──────────────────────────────────────────────────────────────────────
POST /generate/goban              { goban params … }
GET  /goban/games                 list all games from sgf_directory.py
POST /goban/mode                  { "mode": "random"|"sequential"|"manual" }
POST /goban/select                { "game_id": N }
POST /goban/restart               {}
POST /goban/skip                  {}
POST /goban/move                  { "move": N }

── Scheduler ──────────────────────────────────────────────────────────────────
POST /scheduler/settings          { enabled, interval_seconds, frames_per_update,
                                    active_generator, dla_walkers,
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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request

sys.path.insert(0, "/app")

from goban_state import GobanStateManager
from scheduler import Scheduler, INTERVAL_PRESETS
from web_ui import ui as ui_blueprint

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("algorithm_art")

app = Flask(__name__)
app.register_blueprint(ui_blueprint)

# ── Config ────────────────────────────────────────────────────────────────────
DLA_CMD         = os.environ.get("DLA_CMD",         "dla.x")
FRACTAL_CMD     = os.environ.get("FRACTAL_CMD",     "fractalgen.x")
GOBAN_CMD       = os.environ.get("GOBAN_CMD",       "goban.x")
DEFAULT_WIDTH   = int(os.environ.get("DISPLAY_WIDTH",  "600"))
DEFAULT_HEIGHT  = int(os.environ.get("DISPLAY_HEIGHT", "448"))
PHOTOFRAME_HOST = os.environ.get("PHOTOFRAME_HOST", "photoframe.local")
STATE_DIR       = Path(os.environ.get("STATE_DIR",  "/data/state"))
PORT            = int(os.environ.get("PORT", "8765"))

FRACTAL_STATE_FILE = STATE_DIR / "fractal_state.json"
SGF_MAX_BYTES      = 2 * 1024 * 1024

# ── Shared state ──────────────────────────────────────────────────────────────
_goban = GobanStateManager()

_dla_next_frame    = 1
_fractal_zoom_step = 0
_last_source       = "generative"
_last_art_type     = "dla"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _available(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(argv: list[str]) -> None:
    _LOGGER.info("Running: %s", " ".join(str(a) for a in argv))
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


# ── Scheduler generate function ───────────────────────────────────────────────

def _scheduler_generate(generator: str, state: dict) -> bytes | None:
    """Called by the scheduler on each tick. Returns BMP bytes or None."""
    port = int(os.environ.get("PORT", "8765"))
    base = f"http://localhost:{port}"

    try:
        if generator == "dla":
            resp = requests.post(f"{base}/generate/dla", json={
                "walkers": state.get("dla_walkers", 5),
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
                "white_color":     state.get("goban_white_color",   "green"),
                "black_color":     state.get("goban_black_color",   "black"),
                "grid_thickness":  state.get("goban_grid_thickness", 1),
                "highlight":       state.get("goban_highlight",     "ring"),
            }, timeout=180)

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
        "generators": {
            "dla":     _available(DLA_CMD),
            "fractal": _available(FRACTAL_CMD),
            "goban":   _available(GOBAN_CMD),
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

    return jsonify({
        "image_source": _last_source,
        "art_type":     _last_art_type,
        "dla": {
            "next_frame":      _dla_next_frame,
            "sequence_length": 120,
        },
        "fractal": {
            "zoom_step":    _fractal_zoom_step,
            "state_exists": FRACTAL_STATE_FILE.exists(),
        },
        "goban": {
            "selection_mode":  gs.get("selection_mode", "random"),
            "current_game_id": current_id,
            "game_name":       game_name,
            "game_path":       game_path,
            "current_move":    gs.get("current_move", 0),
            "total_moves":     gs.get("total_moves",  0),
        },
        "scheduler": {
            "enabled":           sch.get("enabled",           False),
            "interval_seconds":  sch.get("interval_seconds",  300),
            "frames_per_update": sch.get("frames_per_update", 1),
            "active_generator":  sch.get("active_generator",  "dla"),
            "last_fire":         sch.get("last_fire"),
            "next_fire":         sch.get("next_fire"),
            # Per-generator options (for UI to restore)
            "dla_walkers":           sch.get("dla_walkers",           5),
            "fractal_fg":            sch.get("fractal_fg",            "white"),
            "fractal_bg":            sch.get("fractal_bg",            "black"),
            "fractal_mode":          sch.get("fractal_mode",          "single"),
            "goban_bg":              sch.get("goban_bg",              "white"),
            "goban_board":           sch.get("goban_board",           "yellow"),
            "goban_white_color":     sch.get("goban_white_color",     "green"),
            "goban_black_color":     sch.get("goban_black_color",     "black"),
            "goban_grid_thickness":  sch.get("goban_grid_thickness",  1),
            "goban_highlight":       sch.get("goban_highlight",       "ring"),
            "goban_mode":            sch.get("goban_mode",            "random"),
        },
        "interval_presets": [{"label": l, "seconds": s} for l, s in INTERVAL_PRESETS],
    })


# ── DLA ───────────────────────────────────────────────────────────────────────

@app.post("/generate/dla")
def generate_dla():
    global _dla_next_frame, _last_source, _last_art_type

    if not _available(DLA_CMD):
        return jsonify({"error": f"{DLA_CMD!r} not found"}), 503

    data    = request.get_json(force=True) or {}
    raw     = data.get("frame", None)
    try:
        frame = int(raw) if raw not in (None, "__next__") else _dla_next_frame
    except (ValueError, TypeError):
        frame = _dla_next_frame

    walkers = int(data.get("walkers", _scheduler.state.get("dla_walkers", 5)))

    if not (1 <= frame <= 120):
        return jsonify({"error": "frame must be 1–120"}), 400

    out_dir = tempfile.mkdtemp(prefix="dla_")
    try:
        if frame == 1:
            # Pass --walkers on --init if the binary supports it;
            # fall back silently if it doesn't accept that flag.
            init_argv = [DLA_CMD, out_dir, "--init", "--walkers", str(walkers)]
            try:
                _run(init_argv)
            except RuntimeError as exc:
                if "walkers" in str(exc).lower() or "flag" in str(exc).lower():
                    _LOGGER.warning(
                        "dla.x does not support --walkers, retrying without it"
                    )
                    _run([DLA_CMD, out_dir, "--init"])
                else:
                    raise

        _run([DLA_CMD, out_dir, "--to", str(frame)])

        bmp = Path(out_dir) / "latest_display.bmp"
        if not bmp.exists() or bmp.stat().st_size == 0:
            return jsonify({"error": "DLA produced no output"}), 500

        data_bytes = bmp.read_bytes()
        _dla_next_frame = (frame % 120) + 1
        _last_source    = "generative"
        _last_art_type  = "dla"

        _LOGGER.info(
            "DLA: %d bytes  frame=%d  walkers=%d  next=%d",
            len(data_bytes), frame, walkers, _dla_next_frame,
        )
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

    out_dir  = tempfile.mkdtemp(prefix="fractal_")
    out_path = Path(out_dir)
    state_in = out_path / "state.json"

    try:
        if has_state and FRACTAL_STATE_FILE.exists():
            shutil.copy2(FRACTAL_STATE_FILE, state_in)

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

        _last_source   = "generative"
        _last_art_type = "fractal"
        _LOGGER.info("Fractal: %d bytes", len(data_bytes))
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
    return jsonify({"status": "reset"})


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
            sgf_text, move = _goban.next_frame()
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
            "-white-color",    data.get("white_color",     "green"),
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


# ── Scheduler ─────────────────────────────────────────────────────────────────

@app.post("/scheduler/settings")
def scheduler_settings():
    data = request.get_json(force=True) or {}
    allowed = {
        "enabled", "interval_seconds", "frames_per_update", "active_generator",
        "dla_walkers",
        "fractal_fg", "fractal_bg", "fractal_mode",
        "goban_bg", "goban_board", "goban_white_color", "goban_black_color",
        "goban_grid_thickness", "goban_highlight", "goban_mode",
    }
    updates = {k: v for k, v in data.items() if k in allowed}
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
        return jsonify({"error": "No image data"}), 400

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
        return jsonify({"error": f"Cannot reach {target_host}: {exc}"}), 503
    except requests.exceptions.Timeout:
        return jsonify({"error": "Device push timed out"}), 504


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _LOGGER.info(
        "AlgorithmArt starting on :%d  (dla=%s  fractal=%s  goban=%s  device=%s)",
        PORT, DLA_CMD, FRACTAL_CMD, GOBAN_CMD, PHOTOFRAME_HOST,
    )
    _LOGGER.info("SGF library: %d games loaded", len(_goban.games))
    _LOGGER.info("Web UI: http://localhost:%d/ui", PORT)
    _scheduler.start()
    app.run(host="0.0.0.0", port=PORT)
