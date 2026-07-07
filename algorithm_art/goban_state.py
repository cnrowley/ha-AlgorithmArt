"""Goban game state manager for AlgorithmArt sidecar.

Tracks the current game and move position across Generate calls.
State is persisted to /app/state/goban_state.json so it survives
container restarts.
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
_LOGGER.warning("goban_state.py imported")

# Where game files live inside the container.
SGF_DIR = Path(os.environ.get("SGF_DIR", "/app/go_sgf"))
STATE_FILE = Path("/data/state/goban_state.json")
DIR_FILE = SGF_DIR / "sgf_directory.py"

MOVES_PER_FRAME = 1
HOLD_FINAL_FRAMES = 3


def _count_moves(sgf_text: str) -> int:
    return len(re.findall(r";\s*[BW]\[", sgf_text))


def _load_directory() -> list_LOGGER.warning("===== Goban directory scan =====")
    _LOGGER.warning("SGF_DIR=%s", SGF_DIR)
    _LOGGER.warning("SGF_DIR exists=%s", SGF_DIR.exists())
    _LOGGER.warning("DIR_FILE=%s", DIR_FILE)
    _LOGGER.warning("DIR_FILE exists=%s", DIR_FILE.exists())

    if SGF_DIR.exists():
        try:
            entries = sorted(SGF_DIR.iterdir())
            _LOGGER.warning("SGF_DIR contains %d entries", len(entries))

            for p in entries[:100]:
                _LOGGER.warning(
                    "  %s (%s)",
                    p.name,
                    "dir" if p.is_dir() else "file",
                )
        except Exception as exc:
            _LOGGER.warning("Failed to list SGF_DIR: %s", exc)

    if not DIR_FILE.exists():
        _LOGGER.warning(
            "sgf_directory.py not found at %s",
            DIR_FILE,
        )
        return []

    namespace: dict[str, Any] = {}

    try:
        exec(DIR_FILE.read_text(encoding="utf-8"), namespace)  # noqa: S102

        files = namespace.get("SGF_FILES", [])

        _LOGGER.warning(
            "Loaded %d SGF entries from sgf_directory.py",
            len(files),
        )

        if files:
            _LOGGER.warning("First SGF entry: %s", files[0])

        return files

    except Exception as exc:
        _LOGGER.exception(
            "Failed to exec sgf_directory.py: %s",
            exc,
        )
        return []


class GobanStateManager:
    """Manages which game is being rendered and how far through it we are."""

    def __init__(self) -> None:
        _LOGGER.warning("GobanStateManager __init__ called")

        self._games: list[dict] = []
        self._state: dict[str, Any] = {}

        self._load_games()

        _LOGGER.warning(
            "Loaded %d games into manager",
            len(self._games),
        )

        self._load_state()

    @property
    def games(self) -> listreturn self._games

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def reload_games(self) -> int:
        self._games = _load_directory()
        return len(self._games)

    def set_mode(self, mode: str) -> None:
        if mode not in ("random", "sequential", "manual"):
            raise ValueError(f"Unknown mode: {mode!r}")
        self._state["selection_mode"] = mode
        self._save_state()

    def select_game(self, game_id: int) -> dict:
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
        if not self._games:
            raise RuntimeError("No games loaded — check /data/go_sgf/")

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

        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )

    def _count_moves_for(self, game: dict | None) -> int:
        if game is None:
            return 1

        try:
            text = self._read_sgf(game)
            count = _count_moves(text)

            return max(count, 1)

        except Exception as exc:
            _LOGGER.warning(
                "Could not count moves for %s: %s",
                game,
                exc,
            )
            return 100

    def _load_games(self) -> None:
        _LOGGER.warning("Loading goban game library...")
        self._games = _load_directory()
        _LOGGER.warning("Game library size: %d", len(self._games))

    def _load_state(self) -> None:
        if STATE_FILE.exists():
            try:
                self._state = json.loads(STATE_FILE.read_text())

                _LOGGER.info(
                    "Loaded goban state: %s",
                    self._state,
                )

                return

            except Exception as exc:
                _LOGGER.warning(
                    "Failed to load goban state: %s",
                    exc,
                )

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
            STATE_FILE.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            STATE_FILE.write_text(
                json.dumps(self._state, indent=2)
            )

        except Exception as exc:
            _LOGGER.error(
                "Failed to save goban state: %s",
                exc,
            )

