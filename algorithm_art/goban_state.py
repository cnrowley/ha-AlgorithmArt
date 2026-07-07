"""Goban game state manager for AlgorithmArt sidecar.

Tracks the current game and move position across Generate calls.
State is persisted to /data/state/goban_state.json so it survives
container restarts.

Selection modes
---------------
random      — pick a random game from the SGF library on each new game
sequential  — cycle through games in id order
manual      — stay on the game the user explicitly selected

Game progression
----------------
Each Generate call advances the move counter by MOVES_PER_FRAME (default 1).
When the move counter reaches total_moves the game is "complete" and the
next Generate call starts a new game according to the selection mode.

The move counter starts at 1 (first move) not 0 (final/all moves).
Move 0 is used by goban.x to mean "render the final position" — we use
that only when the user explicitly requests it or when we're showing the
final position before rolling over to the next game.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("algorithm_art.goban_state")

# Where game files live inside the container.
# Static assets belong under /app so they are not hidden by HA's /data mount.
#SGF_DIR = Path(os.environ.get("SGF_DIR", "/app/go_sgf"))
SGF_DIR=Path("/app/go_sgf")


STATE_FILE = Path("/data/state/goban_state.json")
DIR_FILE = Path("/app/go_sgf/sgf_directory.py")

# How many moves to advance per Generate press (1 = step-by-step)
MOVES_PER_FRAME = 1

# How long to show the final position before moving to the next game
HOLD_FINAL_FRAMES = 3


def _count_moves(sgf_text: str) -> int:
    """Count the number of moves in an SGF string.

    Each move is a node beginning with B[ or W[ that is not part of the
    root node (setup stones AB/AW are not moves). We count semicolons
    that are followed by B[ or W[, which reliably identifies move nodes.
    """
    return len(re.findall(r";\s*[BW]\[", sgf_text))


def _load_directory() -> list:
    """Load SGF_FILES from sgf_directory.py via exec."""
    _LOGGER.info("Looking for SGF directory at: %s", SGF_DIR)
    _LOGGER.info("SGF_DIR exists: %s", SGF_DIR.exists())

    if SGF_DIR.exists():
        contents = list(SGF_DIR.iterdir())
        _LOGGER.info(
            "SGF_DIR contents (%d items): %s",
            len(contents),
            [p.name for p in contents[:10]],
        )

    if not DIR_FILE.exists():
        _LOGGER.warning(
            "sgf_directory.py not found at %s — "
            "check that data/go_sgf/ was copied correctly in the Dockerfile.",
            DIR_FILE,
        )
        return []

    namespace: dict[str, Any] = {}

    try:
        exec(DIR_FILE.read_text(encoding="utf-8"), namespace)  # noqa: S102
        files = namespace.get("SGF_FILES", [])
        _LOGGER.info("Loaded %d games from %s", len(files), DIR_FILE)
        return files
    except Exception as exc:
        _LOGGER.error("Failed to exec sgf_directory.py: %s", exc)
        return []


class GobanStateManager:
    """Manages which game is being rendered and how far through it we are."""

    def __init__(self) -> None:
        self._games: list[dict] = []
        self._state: dict[str, Any] = {}
        self._load_games()
        self._load_state()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def games(self) -> list:
        return self._games

    @property
    def state(self) -> dict[str, Any]:
        """Return a copy of the current state (safe to serialise)."""
        return dict(self._state)

    def reload_games(self) -> int:
        """Reload the game directory from disk. Returns new game count."""
        self._games = _load_directory()
        return len(self._games)

    def set_mode(self, mode: str) -> None:
        """Set selection mode: random | sequential | manual."""
        if mode not in ("random", "sequential", "manual"):
            raise ValueError(f"Unknown mode: {mode!r}")
        self._state["selection_mode"] = mode
        self._save_state()

    def select_game(self, game_id: int) -> dict:
        """Manually select a game by id. Switches to manual mode."""
        game = self._game_by_id(game_id)
        if game is None:
            raise ValueError(f"Game id {game_id} not found")

        self._state["selection_mode"] = "manual"
        self._state["manual_game_id"] = game_id
        self._state["current_game_id"] = game_id
        self._state["current_move"] = 1
        self._state["total_moves"] = self._count_moves_for(game)
        self._state["hold_counter"] = 0
        self._save_state()
        return game

    def next_frame(self) -> tuple[str, int]:
        """Advance the state machine and return (sgf_text, move_number)."""

        if not self._games:
            raise RuntimeError("No games loaded — check SGF_DIR")

        if not self._state.get("current_game_id"):
            self._start_new_game()

        game = self._game_by_id(self._state["current_game_id"])

        if game is None:
            self._start_new_game()
            game = self._game_by_id(self._state["current_game_id"])

        total = self._state.get("total_moves", 1)
        move = self._state.get("current_move", 1)
        hold = self._state.get("hold_counter", 0)

        if move > total:
            if hold < HOLD_FINAL_FRAMES:
                self._state["hold_counter"] = hold + 1
                self._save_state()
                sgf_text = self._read_sgf(game)
                return sgf_text, 0

            self._start_new_game()
            game = self._game_by_id(self._state["current_game_id"])
            total = self._state.get("total_moves", 1)
            move = self._state.get("current_move", 1)

        sgf_text = self._read_sgf(game)

        next_move = move + MOVES_PER_FRAME

        if next_move > total:
            self._state["current_move"] = total + 1
            self._state["hold_counter"] = 0
        else:
            self._state["current_move"] = next_move

        self._save_state()
        return sgf_text, move

    def skip_to_next_game(self) -> None:
        self._start_new_game()

    def restart_current_game(self) -> None:
        self._state["current_move"] = 1
        self._state["hold_counter"] = 0
        self._save_state()

    def set_move(self, move: int) -> None:
        self._state["current_move"] = max(0, move)
        self._state["hold_counter"] = 0
        self._save_state()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _start_new_game(self) -> None:
        mode = self._state.get("selection_mode", "random")
        game_id = self._pick_next_game_id(mode)
        game = self._game_by_id(game_id)
        total = self._count_moves_for(game) if game else 1

        _LOGGER.info(
            "Starting new game: id=%d mode=%s total_moves=%d",
            game_id,
            mode,
            total,
        )

        self._state.update(
            {
                "current_game_id": game_id,
                "current_move": 1,
                "total_moves": total,
                "hold_counter": 0,
            }
        )
        self._save_state()

    def _pick_next_game_id(self, mode: str) -> int:
        ids = [g["id"] for g in self._games]

        if not ids:
            return 1

        if mode == "manual":
            manual_id = self._state.get("manual_game_id")
            if manual_id and manual_id in ids:
                return manual_id
            return ids[0]

        if mode == "sequential":
            current = self._state.get("current_game_id", 0)
            try:
                idx = ids.index(current)
                return ids[(idx + 1) % len(ids)]
            except ValueError:
                return ids[0]

        current = self._state.get("current_game_id")
        choices = [i for i in ids if i != current] or ids
        return random.choice(choices)

    def _game_by_id(self, game_id: int) -> dict | None:
        for g in self._games:
            if g["id"] == game_id:
                return g
        return None

    def _read_sgf(self, game: dict) -> str:
        path = SGF_DIR / game["filename"]

        if not path.exists():
            raise RuntimeError(f"SGF file not found: {path}")

        return path.read_text(encoding="utf-8", errors="replace")

    def _count_moves_for(self, game: dict | None) -> int:
        if game is None:
            return 1

        try:
            text = self._read_sgf(game)
            count = _count_moves(text)
            return max(count, 1)

        except Exception as exc:
            _LOGGER.warning("Could not count moves for %s: %s", game, exc)
            return 100

    def _load_games(self) -> None:
        self._games = _load_directory()

    def _load_state(self) -> None:
        if STATE_FILE.exists():
            try:
                self._state = json.loads(STATE_FILE.read_text())
                _LOGGER.info("Loaded goban state: %s", self._state)
                return
            except Exception as exc:
                _LOGGER.warning("Failed to load goban state: %s", exc)

        self._state = {
            "selection_mode": "random",
            "current_game_id": None,
            "current_move": 1,
            "total_moves": 0,
            "hold_counter": 0,
            "manual_game_id": None,
        }

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(self._state, indent=2))
        except Exception as exc:
            _LOGGER.error("Failed to save goban state: %s", exc)

