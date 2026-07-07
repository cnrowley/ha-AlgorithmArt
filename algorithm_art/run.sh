#!/usr/bin/with-contenv bashio

PORT=$(bashio::config 'port')
DLA_CMD=$(bashio::config 'dla_cmd')
FRACTAL_CMD=$(bashio::config 'fractal_cmd')
GOBAN_CMD=$(bashio::config 'goban_cmd')
DISPLAY_WIDTH=$(bashio::config 'display_width')
DISPLAY_HEIGHT=$(bashio::config 'display_height')

bashio::log.info "Starting AlgorithmArt generator sidecar on port ${PORT}"
bashio::log.info "Binaries: dla=${DLA_CMD}  fractal=${FRACTAL_CMD}  goban=${GOBAN_CMD}"
bashio::log.info "Display: ${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}"

export PORT
export DLA_CMD
export FRACTAL_CMD
export GOBAN_CMD
export DISPLAY_WIDTH
export DISPLAY_HEIGHT
PHOTOFRAME_HOST=$(bashio::config 'photoframe_host')
export PHOTOFRAME_HOST
export STATE_DIR="/data/state"
export SGF_DIR="/data/go_sgf"

mkdir -p /data/state

exec python3 /app/main.py
