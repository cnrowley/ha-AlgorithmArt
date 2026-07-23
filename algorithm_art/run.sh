#!/usr/bin/with-contenv bashio

PORT=$(bashio::config 'port')
DLA_CMD=$(bashio::config 'dla_cmd')
FRACTAL_CMD=$(bashio::config 'fractal_cmd')
GOBAN_CMD=$(bashio::config 'goban_cmd')
MOIRE_CMD=$(bashio::config 'moire_cmd')
CHESS_CMD=$(bashio::config 'chess_cmd')
DISPLAY_WIDTH=$(bashio::config 'display_width')
DISPLAY_HEIGHT=$(bashio::config 'display_height')
DISPLAY_PORTRAIT=$(bashio::config 'portrait')
CHESS_PIECE_STYLE=$(bashio::config 'chess_piece_style')
CHESS_SVG_DIR=$(bashio::config 'chess_svg_dir')
CHESS_FONT=$(bashio::config 'chess_font')

bashio::log.info "Starting AlgorithmArt generator sidecar on port ${PORT}"
bashio::log.info "Binaries: dla=${DLA_CMD}  fractal=${FRACTAL_CMD}  goban=${GOBAN_CMD}  moire=${MOIRE_CMD}  chess=${CHESS_CMD}"
bashio::log.info "Display: ${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}  portrait=${DISPLAY_PORTRAIT}"

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
PHOTOFRAME_HOST=$(bashio::config 'photoframe_host')
export PHOTOFRAME_HOST
export STATE_DIR="/data/state"
export SGF_DIR="/data/go_sgf"
export CHESS_PGN_DIR="/app/chess_pgn"

mkdir -p /data/state

exec python3 /app/main.py
