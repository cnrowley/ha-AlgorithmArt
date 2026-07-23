"""Auto-generate scheduler for AlgorithmArt sidecar.

Runs a background thread that fires every ``interval_seconds``, calls
the active generator, and pushes the result to the PhotoPainter device.

All settings persist to /data/state/scheduler_state.json so they survive
container restarts.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_LOGGER = logging.getLogger("algorithm_art.scheduler")

STATE_FILE = Path("/data/state/scheduler_state.json")

# Preset interval options shown in the UI dropdown (seconds)
INTERVAL_PRESETS = [
    ("30 seconds",  30),
    ("1 minute",    60),
    ("2 minutes",   120),
    ("5 minutes",   300),
    ("10 minutes",  600),
    ("15 minutes",  900),
    ("30 minutes",  1800),
    ("1 hour",      3600),
    ("2 hours",     7200),
    ("6 hours",     21600),
    ("12 hours",    43200),
    ("24 hours",    86400),
]

DEFAULT_STATE: dict[str, Any] = {
    "enabled":           False,
    "interval_seconds":  300,
    "frames_per_update": 1,
    "active_generator":  "dla",
    "last_fire":         None,
    "next_fire":         None,
    # Fractal options
    "fractal_fg":        "white",
    "fractal_bg":        "black",
    "fractal_mode":      "single",      # single | zoom_sequence
    # Goban options
    "goban_bg":          "white",
    "goban_board":       "yellow",
    "goban_white_color": "green",
    "goban_black_color": "black",
    "goban_grid_thickness": 1,
    "goban_highlight":   "ring",
    "goban_mode":        "random",      # random | sequential | manual
    # Moire options
    "moire_pattern":     "honeycomb",
    "moire_background":  "white",
    "moire_linecolor":   "black",
    # Chess options
    "chess_mode":              "random",   # random | sequential | manual
    "chess_piece_style":       "shape",    # shape | glyph | svg
    "chess_white_color":       "white",
    "chess_black_color":       "black",
    "chess_light_square":      "white",
    "chess_dark_square":       "green",
    "chess_show_coordinates":  False,
    "chess_show_move_text":    True,
    "chess_show_player_names": True,
    "chess_show_result":       True,
    "chess_reset_after_game":  True,
}


class Scheduler:
    """Background scheduler that auto-generates and pushes images."""

    def __init__(self, generate_fn: Callable) -> None:
        """
        Parameters
        ----------
        generate_fn:
            Callable(generator: str, state: dict) -> bytes
            Called on each tick to produce image bytes.
            Receives the active generator name and a copy of the full state.
        """
        self._generate_fn = generate_fn
        self._state: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._load_state()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def update(self, updates: dict[str, Any]) -> None:
        """Apply a partial state update and restart the timer only if the
        enabled flag or interval actually changed value.

        The web UI resaves the full settings payload on every user edit
        (colors, board style, etc.) — those always include "enabled" and
        "interval_seconds" even when unchanged, so we compare values here
        rather than just checking key presence. Restarting on every save
        would reset next_fire and make the countdown never progress.
        """
        with self._lock:
            restart = False
            if "enabled" in updates and updates["enabled"] != self._state.get("enabled"):
                restart = True
            if ("interval_seconds" in updates
                    and updates["interval_seconds"] != self._state.get("interval_seconds")):
                restart = True
            self._state.update(updates)
            self._save_state_locked()

        if restart:
            self._restart()

    def start(self) -> None:
        """Start the scheduler thread (idempotent)."""
        self._restart()

    def stop(self) -> None:
        """Stop the scheduler thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        _LOGGER.info("Scheduler stopped")

    def trigger_now(self) -> None:
        """Fire immediately regardless of the timer (non-blocking)."""
        t = threading.Thread(target=self._fire, daemon=True, name="scheduler-manual")
        t.start()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _restart(self) -> None:
        """Stop any existing thread and start a new one if enabled."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        self._stop_event.clear()
        enabled = self._state.get("enabled", False)

        if enabled:
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="scheduler"
            )
            self._thread.start()
            _LOGGER.info(
                "Scheduler started — interval=%ds  generator=%s",
                self._state.get("interval_seconds", 300),
                self._state.get("active_generator", "dla"),
            )
        else:
            _LOGGER.info("Scheduler disabled")

    def _run(self) -> None:
        """Main scheduler loop."""
        interval = self._state.get("interval_seconds", 300)
        self._set_next_fire(interval)

        while not self._stop_event.is_set():
            # Sleep in 1-second chunks so we can respond to stop quickly
            for _ in range(interval):
                if self._stop_event.is_set():
                    return
                time.sleep(1)

            if self._stop_event.is_set():
                return

            self._fire()
            # Re-read interval in case it changed while we were sleeping
            with self._lock:
                interval = self._state.get("interval_seconds", 300)
            self._set_next_fire(interval)

    def _fire(self) -> None:
        """Generate an image and push it to the device."""
        with self._lock:
            state_copy = dict(self._state)

        generator = state_copy.get("active_generator", "dla")
        _LOGGER.info("Scheduler firing — generator=%s", generator)

        try:
            image_bytes = self._generate_fn(generator, state_copy)
            if image_bytes:
                _LOGGER.info(
                    "Scheduler: generated %d bytes, pushing to device", len(image_bytes)
                )
                # Push via the sidecar's own /push endpoint
                import requests
                port = int(os.environ.get("PORT", "8765"))
                host = os.environ.get("PHOTOFRAME_HOST", "photoframe.local")
                resp = requests.post(
                    f"http://localhost:{port}/push",
                    data=image_bytes,
                    headers={"Content-Type": "image/bmp"},
                    timeout=60,
                )
                if resp.status_code == 200:
                    _LOGGER.info("Scheduler: image pushed successfully")
                else:
                    _LOGGER.error("Scheduler: push failed HTTP %d", resp.status_code)
        except Exception as exc:
            _LOGGER.error("Scheduler fire failed: %s", exc, exc_info=True)

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._state["last_fire"] = now
            self._save_state_locked()

    def _set_next_fire(self, interval: int) -> None:
        next_ts = datetime.fromtimestamp(
            time.time() + interval, tz=timezone.utc
        ).isoformat()
        with self._lock:
            self._state["next_fire"] = next_ts
            self._save_state_locked()

    def _load_state(self) -> None:
        if STATE_FILE.exists():
            try:
                loaded = json.loads(STATE_FILE.read_text())
                self._state = {**DEFAULT_STATE, **loaded}
                # Never restore "enabled" as True on startup — require
                # explicit re-enable so a broken state doesn't spam the device
                self._state["enabled"] = False
                self._state["next_fire"] = None
                _LOGGER.info("Loaded scheduler state from %s", STATE_FILE)
                return
            except Exception as exc:
                _LOGGER.warning("Failed to load scheduler state: %s", exc)
        self._state = dict(DEFAULT_STATE)

    def _save_state_locked(self) -> None:
        """Save state to disk. Must be called with self._lock held."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(self._state, indent=2))
        except Exception as exc:
            _LOGGER.error("Failed to save scheduler state: %s", exc)
