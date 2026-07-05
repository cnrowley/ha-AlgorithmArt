"""AlgorithmArt sidecar — Flask API for image generation.

Runs inside the HA add-on container alongside Home Assistant.
The photopainter_art HACS integration calls this over HTTP on port 8765.

Endpoints
---------
POST /generate/dla
    { "frame": <int 1-120> }
    → BMP bytes

POST /generate/fractal
    { "fg": "white", "bg": "black",
      "single": true, "frames": 1, "has_state": false }
    → BMP bytes

POST /generate/goban
    { "sgf_source": "library",   # library | url | inline
      "library_id": "shusaku_ear_reddening",
      "sgf_url": "", "sgf_text": "",
      "move": 0,
      "bg": "white", "board": "yellow",
      "white_color": "green", "black_color": "black",
      "grid_thickness": 1, "highlight": "ring" }
    → BMP bytes

POST /fractal/reset
    {}  → resets zoom state file

GET /health
    → { "status": "ok", "generators": { "dla": bool, "fractal": bool, "goban": bool } }

Errors: { "error": "<message>" } with HTTP 400 / 500 / 503.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("algorithm_art")

app = Flask(__name__)

# ── Binary names ────────────────────────────────────────────────────────────
DLA_CMD     = os.environ.get("DLA_CMD",     "dla.x")
FRACTAL_CMD = os.environ.get("FRACTAL_CMD", "fractalgen.x")
GOBAN_CMD   = os.environ.get("GOBAN_CMD",   "goban.x")

DEFAULT_WIDTH  = int(os.environ.get("DISPLAY_WIDTH",  "600"))
DEFAULT_HEIGHT = int(os.environ.get("DISPLAY_HEIGHT", "448"))

STATE_DIR             = Path(os.environ.get("STATE_DIR", "/data/state"))
FRACTAL_STATE_FILE    = STATE_DIR / "fractal_state.json"

SGF_MAX_BYTES = 2 * 1024 * 1024


# ── Helpers ─────────────────────────────────────────────────────────────────

def _available(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(argv: list[str]) -> None:
    """Run a subprocess; raise RuntimeError on non-zero exit."""
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


def _resolve_sgf(data: dict) -> str:
    """Return literal SGF text from whichever source the request specifies."""
    source = data.get("sgf_source", "library")

    if source == "inline":
        text = data.get("sgf_text", "").strip()
        if not text:
            raise ValueError("sgf_source is 'inline' but sgf_text is empty")
        return text

    if source == "library":
        game = _LIBRARY.get(data.get("library_id", ""))
        if game is None:
            game = next(iter(_LIBRARY.values()), None)
        if game is None:
            raise ValueError("SGF library is empty")
        return game

    if source == "url":
        url = data.get("sgf_url", "").strip()
        if not url:
            raise ValueError("sgf_source is 'url' but sgf_url is empty")
        _LOGGER.info("Downloading SGF from %s", url)
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            if len(resp.content) > SGF_MAX_BYTES:
                raise ValueError(f"SGF too large ({len(resp.content)} bytes)")
            text = resp.content.decode("utf-8", errors="replace").strip()
            if not text.startswith("("):
                raise ValueError(f"Response from {url!r} does not look like SGF")
            return text
        except requests.RequestException as exc:
            raise ValueError(f"Failed to download SGF: {exc}") from exc

    raise ValueError(f"Unknown sgf_source: {source!r}")


# ── Bundled SGF library ──────────────────────────────────────────────────────

_LIBRARY: dict[str, str] = {
    "shusaku_ear_reddening": """\
(;GM[1]FF[4]CA[UTF-8]SZ[19]
PB[Inoue Genan Inseki]PW[Honinbo Shusaku]
RE[W+2]DT[1846-08-08]GN[The Ear-Reddening Game]
;B[qd];W[dd];B[dq];W[pq];B[oc];W[qo];B[de];W[ce];B[cf];W[cd]
;B[df];W[fc];B[ed];W[ec];B[fd];W[gd];B[ge];W[hd];B[gc];W[gb]
;B[hc];W[ib];B[he];W[ie];B[id];W[hb];B[jd];W[fb];B[cn];W[qf]
;B[nd];W[rd];B[qc];W[qk];B[mp];W[po];B[mn];W[ec];B[gq];W[oj])""",

    "shusaku_fuseki": """\
(;GM[1]FF[4]CA[UTF-8]SZ[19]GN[Shusaku Fuseki demo]
;B[qd];W[dc];B[dp];W[pq];B[oc];W[qc];B[pc];W[qd];B[qe];W[re]
;B[qf];W[rf];B[qg];W[pb];B[ob];W[qb];B[nc];W[rd])""",

    "classic_9x9": """\
(;GM[1]FF[4]CA[UTF-8]SZ[9]GN[Classic 9x9 opening study]
;B[ee];W[gc];B[cg];W[cc];B[gg];W[ge];B[fd];W[gd];B[fe];W[ff]
;B[fg];W[gf];B[hf];W[he];B[hg];W[ed];B[fc];W[dc];B[fb];W[ec])""",

    "balanced_13x13": """\
(;GM[1]FF[4]CA[UTF-8]SZ[13]GN[13x13 balanced study]
;B[jj];W[dd];B[jd];W[dj];B[gg];W[cg];B[gj];W[jg];B[md];W[mj]
;B[dm];W[jm];B[cm];W[gm];B[gd];W[md])""",

    "handicap_demo": """\
(;GM[1]FF[4]CA[UTF-8]SZ[19]HA[4]
AB[pd][dp][dd][pp]GN[Four-stone handicap opening demo]
;W[nc];B[pf];W[jd];B[fq];W[cf];B[ec];W[hc];B[cn];W[cl];B[en])""",
}


# ── Routes ───────────────────────────────────────────────────────────────────

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


# ── DLA ──────────────────────────────────────────────────────────────────────

@app.post("/generate/dla")
def generate_dla():
    if not _available(DLA_CMD):
        return jsonify({"error": f"{DLA_CMD!r} not found"}), 503

    data  = request.get_json(force=True) or {}
    frame = int(data.get("frame", 1))

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
        _LOGGER.info("DLA: returning %d bytes", len(data_bytes))
        return Response(data_bytes, mimetype="image/bmp")

    except RuntimeError as exc:
        _LOGGER.error("DLA failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


# ── Fractal ───────────────────────────────────────────────────────────────────

@app.post("/generate/fractal")
def generate_fractal():
    """Call fractalgen.x.

    CLI flags (from fractalgen.go):
        -width  int       image width
        -height int       image height
        -out    string    output directory  (writes <out>/current.bmp)
        -frames int       number of frames (ignored with -single)
        -single           generate exactly one frame
        -state  string    state JSON file for zoom continuation
        -fg     string    foreground colour
        -bg     string    background colour
    """
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
        # Load persistent zoom state if this is a sequence call
        if has_state and FRACTAL_STATE_FILE.exists():
            shutil.copy2(FRACTAL_STATE_FILE, state_in)
            _LOGGER.info("Fractal: loaded zoom state from %s", FRACTAL_STATE_FILE)

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

        # Persist updated state for next zoom step
        if has_state and state_in.exists():
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(state_in, FRACTAL_STATE_FILE)
            _LOGGER.info("Fractal: saved zoom state to %s", FRACTAL_STATE_FILE)

        _LOGGER.info("Fractal: returning %d bytes", len(data_bytes))
        return Response(data_bytes, mimetype="image/bmp")

    except RuntimeError as exc:
        _LOGGER.error("Fractal failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


@app.post("/fractal/reset")
def fractal_reset():
    """Delete the persistent zoom state so the next call starts fresh."""
    if FRACTAL_STATE_FILE.exists():
        FRACTAL_STATE_FILE.unlink()
        _LOGGER.info("Fractal: zoom state deleted")
        return jsonify({"status": "reset"})
    return jsonify({"status": "no_state_to_reset"})


# ── Goban ─────────────────────────────────────────────────────────────────────

@app.post("/generate/goban")
def generate_goban():
    """Call goban.x.

    CLI flags (from goban.go):
        -input          string   SGF file path
        -move           int      move number (0 = final position)
        -output         string   output BMP path  (default "frame.bmp")
        -bg             string   white|black
        -board          string   yellow|white
        -white-color    string   white|green|blue|red
        -black-color    string   black|red
        -grid-thickness int      1 or 2
        -highlight      string   dot|ring|none
    """
    if not _available(GOBAN_CMD):
        return jsonify({"error": f"{GOBAN_CMD!r} not found"}), 503

    data = request.get_json(force=True) or {}

    try:
        sgf_text = _resolve_sgf(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    work_dir   = tempfile.mkdtemp(prefix="goban_")
    work_path  = Path(work_dir)
    sgf_file   = work_path / "game.sgf"
    output_bmp = work_path / "frame.bmp"

    try:
        sgf_file.write_text(sgf_text, encoding="utf-8")

        _run([
            GOBAN_CMD,
            "-input",          str(sgf_file),
            "-move",           str(int(data.get("move", 0))),
            "-output",         str(output_bmp),
            "-bg",             data.get("bg",           "white"),
            "-board",          data.get("board",         "yellow"),
            "-white-color",    data.get("white_color",   "green"),
            "-black-color",    data.get("black_color",   "black"),
            "-grid-thickness", str(int(data.get("grid_thickness", 1))),
            "-highlight",      data.get("highlight",     "ring"),
        ])

        if not output_bmp.exists() or output_bmp.stat().st_size == 0:
            return jsonify({"error": "goban.x produced no output"}), 500

        data_bytes = output_bmp.read_bytes()
        _LOGGER.info("Goban: returning %d bytes", len(data_bytes))
        return Response(data_bytes, mimetype="image/bmp")

    except RuntimeError as exc:
        _LOGGER.error("Goban failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    _LOGGER.info(
        "AlgorithmArt sidecar starting on :%d  "
        "(dla=%s  fractal=%s  goban=%s)",
        port,
        DLA_CMD, FRACTAL_CMD, GOBAN_CMD,
    )
    app.run(host="0.0.0.0", port=port)
