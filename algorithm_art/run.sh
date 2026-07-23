#!/usr/bin/with-contenv bashio

# ── IMPORTANT ────────────────────────────────────────────────────────────────
# bashio::config returns the literal STRING "null" (not an empty value) when
# a key is absent from the add-on's saved options.json — e.g. because the
# add-on's config.yaml gained a new option after this instance was first
# installed, and the Configuration tab was never re-saved to populate it.
# `CHESS_CMD=$(bashio::config 'chess_cmd')` would then export CHESS_CMD=null
# as a real 5-character string, main.py's `os.environ.get("CHESS_CMD", ...)`
# would happily return it (the env var IS set, just to the wrong value), and
# every /generate/chess call would fail with `'null' not found` (Python's
# repr() of the string "null"). This is what was happening.
#
# Fixed two ways: (1) every bashio::config call below passes its own default
# as the second argument, which is bashio's own defined way of handling a
# missing key; (2) `clean()` is a second safety net that replaces a literal
# "null" (or empty string) with the intended default even if some bashio
# version/edge-case still lets one through.

clean() {
  # $1 = value read from bashio::config, $2 = fallback default
  local v="$1"
  if [ -z "$v" ] || [ "$v" = "null" ]; then
    echo "$2"
  else
    echo "$v"
  fi
}

PORT=$(clean "$(bashio::config 'port' '8765')" "8765")
DLA_CMD=$(clean "$(bashio::config 'dla_cmd' 'dla.x')" "dla.x")
FRACTAL_CMD=$(clean "$(bashio::config 'fractal_cmd' 'fractal.x')" "fractal.x")
GOBAN_CMD=$(clean "$(bashio::config 'goban_cmd' 'goban.x')" "goban.x")
MOIRE_CMD=$(clean "$(bashio::config 'moire_cmd' 'moire.x')" "moire.x")
CHESS_CMD=$(clean "$(bashio::config 'chess_cmd' 'chess2bmp.x')" "chess2bmp.x")
DISPLAY_WIDTH=$(clean "$(bashio::config 'display_width' '800')" "800")
DISPLAY_HEIGHT=$(clean "$(bashio::config 'display_height' '480')" "480")
DISPLAY_PORTRAIT=$(clean "$(bashio::config 'portrait' 'false')" "false")
# Default piece style is SVG figurines (bundled Cburnett set — see
# data/chess_svg/) with no on-image text, per the requested default look.
CHESS_PIECE_STYLE=$(clean "$(bashio::config 'chess_piece_style' 'svg')" "svg")
CHESS_SVG_DIR=$(clean "$(bashio::config 'chess_svg_dir' '/app/chess_svg')" "/app/chess_svg")
CHESS_FONT=$(clean "$(bashio::config 'chess_font' '')" "")
PHOTOFRAME_HOST=$(clean "$(bashio::config 'photoframe_host' 'photoframe.local')" "photoframe.local")

bashio::log.info "Starting AlgorithmArt generator sidecar on port ${PORT}"
bashio::log.info "Binaries: dla=${DLA_CMD}  fractal=${FRACTAL_CMD}  goban=${GOBAN_CMD}  moire=${MOIRE_CMD}  chess=${CHESS_CMD}"
bashio::log.info "Display: ${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}  portrait=${DISPLAY_PORTRAIT}"
bashio::log.info "Chess: piece_style=${CHESS_PIECE_STYLE}  svg_dir=${CHESS_SVG_DIR}"

export PORT
export DLA_CMD
export FRACTAL_CMD
export GOBAN_CMD
export MOIRE_CMD
export CHESS_CMD
export DISPLAY_WIDTH
export DISPLAY_HEIGHT
export DISPLAY_PORTRAIT
export CHESS_PIECE_STYLE
export CHESS_SVG_DIR
export CHESS_FONT
export PHOTOFRAME_HOST
export STATE_DIR="/data/state"
export SGF_DIR="/data/go_sgf"
export CHESS_PGN_DIR="/app/chess_pgn"
# User-uploaded / URL-imported PGNs live under /data (the add-on's
# persistent volume) so they survive container recreation, unlike /app
# which is reset to the image contents on every restart/update.
export CHESS_PGN_USER_DIR="/data/chess_pgn"

mkdir -p /data/state
mkdir -p /data/chess_pgn

exec python3 /app/main.py
