#!/usr/bin/env bashio
set -e

MODE="$(bashio::config 'mode')"
bashio::log.info "Starting Image Streamer in mode: ${MODE}"

python3 /app/server.py
