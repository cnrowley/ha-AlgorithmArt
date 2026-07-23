"""Chess game state manager for AlgorithmArt sidecar.

Tracks the current PGN game and ply (half-move) position across
/generate/chess calls, and drives the chess2bmp binary's exit-code
protocol (0 = OK / more moves remain, 2 = game over or past the end,
1 = fatal error).

State is persisted to /data/state/chess_state.json so it survives
container restarts — this satisfies the "state must persist across
restarts" requirement without needing any Home Assistant input_helpers;
HA only ever has to call the sidecar's /generate/chess endpoint and
look at the image it gets back (exactly like it already does for DLA,
Fractal, and Goban).

Selection modes
----------------
random      — pick a random game from the PGN library on each new game
sequential  — cycle through games in id order
manual      — stay on the game the user explicitly selected

Game progression
-----------------
Each call to next_frame() advances the ply counter by ``plies_per_frame``
(mirrors the scheduler's "frames per update" setting, exactly like
GobanStateManager.next_frame). When the counter passes the game's total
ply count the game is "complete"; the *next* call starts a new game
according to the selection mode (after holding on the final position for
HOLD_FINAL_FRAMES calls, so the finished board isn't only shown for a
single tick).

chess2bmp's own exit codes are handled here too:
    0 -> STATUS: OK          more plies remain after this render
    2 -> STATUS: GAME_OVER   or STATUS: PAST_END — render still happened,
                             but this is the end of the game
    1 -> STATUS: FATAL_ERROR -> chess2bmp produced no usable image at all;
                             callers (main.py) should NOT advance state
                             or push anything to the device in this case.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("algorithm_art.chess_state")

# Where the PGN game library lives inside the container. Static assets
# belong under /app so they are not hidden by HA's /data mount (same
# reasoning as SGF_DIR in goban_state.py).
PGN_DIR = Path(os.environ.get("CHESS_PGN_DIR", "/app/chess_pgn"))

STATE_FILE = Path("/data/state/chess_state.json")
DIR_FILE = PGN_DIR / "pgn_directory.py"

# Default number of plies to advance per Generate call when the caller
# doesn't specify one. The scheduler's "frames per update" setting
# overrides this on each call — see next_frame().
DEFAULT_PLIES_PER_FRAME = 1

# How long to hold the final position on screen before rolling over to
# the next game (mirrors goban_state.HOLD_FINAL_FRAMES).
HOLD_FINAL_FRAMES = 3

# chess2bmp exit codes (see the Technical Specification this module
# implements against).
EXIT_OK = 0
EXIT_BOUNDARY = 2   # GAME_OVER or PAST_END
EXIT_FATAL = 1


_MOVE_NUMBER_RE = re.compile(r"^\d+\.(\.\.)?$")
_RESULT_TOKENS = {"1-0", "0-1", "1/2-1/2", "*"}
_TAG_LINE_RE = re.compile(r"^\s*\[.*\]\s*$")


def _split_pgn_games(pgn_text: str) -> list[str]:
    """Split a (possibly multi-game) PGN file into individual game texts.

    A new game starts at a line beginning with ``[Event`` that isn't the
    very first tag block. This is a pragmatic PGN splitter, not a full
    parser — sufficient for well-formed PGN exports.
    """
    lines = pgn_text.splitlines()
    games: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.strip().startswith("[Event") and current and any(
            not _TAG_LINE_RE.match(l) and l.strip() for l in current
        ):
            games.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current and "\n".join(current).strip():
        games.append("\n".join(current).strip())
    return games or [pgn_text]


def _count_plies(game_text: str) -> int:
    """Count the number of plies (half-moves) in one game's movetext.

    Strips tag pairs (``[Key "Value"]``), comments (``{...}``), and
    result markers, then counts SAN move tokens (i.e. tokens that are
    not move-number markers like ``12.`` or ``12...``).
    """
    # Drop tag pairs
    text = re.sub(r"^\s*\[.*\]\s*$", "", game_text, flags=re.MULTILINE)
    # Drop comments and NAGs
    text = re.sub(r"\{[^}]*\}", " ", text)
    text = re.sub(r"\$\d+", " ", text)
    # Drop variations in parentheses (rare in exported game files, but
    # they would otherwise inflate the ply count)
    text = re.sub(r"\([^()]*\)", " ", text)

    plies = 0
    for token in text.split():
        if token in _RESULT_TOKENS:
            continue
        if _MOVE_NUMBER_RE.match(token):
            continue
        plies += 1
    return plies


def _load_directory() -> list:
    """Load PGN_FILES from pgn_directory.py via exec (same pattern used
    by goban_state._load_directory for sgf_directory.py)."""
    _LOGGER.info("Looking for PGN directory at: %s", PGN_DIR)
    _LOGGER.info("PGN_DIR exists: %s", PGN_DIR.exists())

    if PGN_DIR.exists():
        contents = list(PGN_DIR.iterdir())
        _LOGGER.info(
            "PGN_DIR contents (%d items): %s",
            len(contents),
            [p.name for p in contents[:10]],
        )

    if not DIR_FILE.exists():
        _LOGGER.warning(
            "pgn_directory.py not found at %s — "
            "check that data/chess_pgn/ was copied correctly in the Dockerfile.",
            DIR_FILE,
        )
        return []

    namespace: dict[str, Any] = {}
    try:
        exec(DIR_FILE.read_text(encoding="utf-8"), namespace)  # noqa: S102
        files = namespace.get("PGN_FILES", [])
        _LOGGER.info("Loaded %d games from %s", len(files), DIR_FILE)
        return files
    except Exception as exc:
        _LOGGER.error("Failed to exec pgn_directory.py: %s", exc)
        return []


class ChessStateManager:
    """Manages which PGN game is being replayed and how far through it we are.

    This is the direct chess counterpart of goban_state.GobanStateManager;
    see that module's docstring for the shared design rationale (why
    state lives here rather than in HA input_helpers, hold-final-frame
    behaviour, selection modes, etc).
    """

    def __init__(self) -> None:
        self._games: list[dict] = []
        self._state: dict[str, Any] = {}
        self._load_games()
        self._load_state()

    # ── Public API ───────────────────────────────────────────────────

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
        self._state["total_moves"] = self._count_plies_for(game)
        self._state["hold_counter"] = 0
        self._save_state()
        return game

    def next_frame(self, plies_per_frame: int = DEFAULT_PLIES_PER_FRAME) -> tuple[Path, int]:
        """Advance the state machine and return (pgn_path, target_ply).

        ``plies_per_frame`` lets a caller (e.g. the scheduler's "frames
        per update" setting) jump ahead by more than one ply per call,
        exactly like GobanStateManager.next_frame's moves_per_frame.
        """
        plies_per_frame = max(1, int(plies_per_frame or 1))

        if not self._games:
            raise RuntimeError("No games loaded — check CHESS_PGN_DIR")

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
                return self._pgn_path(game), -1  # -1 = render final position
            self._start_new_game()
            game = self._game_by_id(self._state["current_game_id"])
            total = self._state.get("total_moves", 1)
            move = self._state.get("current_move", 1)

        next_move = move + plies_per_frame
        if next_move > total:
            self._state["current_move"] = total + 1
            self._state["hold_counter"] = 0
        else:
            self._state["current_move"] = next_move

        self._save_state()
        return self._pgn_path(game), move

    def skip_to_next_game(self) -> None:
        self._start_new_game()

    def restart_current_game(self) -> None:
        self._state["current_move"] = 1
        self._state["hold_counter"] = 0
        self._save_state()

    def set_move(self, move: int) -> None:
        self._state["current_move"] = max(-1, move)
        self._state["hold_counter"] = 0
        self._save_state()

    def current_game(self) -> dict | None:
        return self._game_by_id(self._state.get("current_game_id"))

    # ── Private helpers ──────────────────────────────────────────────

    def _start_new_game(self) -> None:
        mode = self._state.get("selection_mode", "random")
        game_id = self._pick_next_game_id(mode)
        game = self._game_by_id(game_id)
        total = self._count_plies_for(game) if game else 1

        _LOGGER.info(
            "Starting new chess game: id=%s mode=%s total_plies=%d",
            game_id, mode, total,
        )

        self._state.update({
            "current_game_id": game_id,
            "current_move": 1,
            "total_moves": total,
            "hold_counter": 0,
        })
        self._save_state()

    def _pick_next_game_id(self, mode: str):
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

        # random
        current = self._state.get("current_game_id")
        choices = [i for i in ids if i != current] or ids
        return random.choice(choices)

    def _game_by_id(self, game_id) -> dict | None:
        for g in self._games:
            if g["id"] == game_id:
                return g
        return None

    def _pgn_path(self, game: dict) -> Path:
        path = PGN_DIR / game["filename"]
        if not path.exists():
            raise RuntimeError(f"PGN file not found: {path}")
        return path

    def _count_plies_for(self, game: dict | None) -> int:
        if game is None:
            return 1
        try:
            path = self._pgn_path(game)
            text = path.read_text(encoding="utf-8", errors="replace")
            games_in_file = _split_pgn_games(text)
            game_idx = int(game.get("game_index", 1)) - 1
            game_idx = max(0, min(game_idx, len(games_in_file) - 1))
            count = _count_plies(games_in_file[game_idx])
            return max(count, 1)
        except Exception as exc:
            _LOGGER.warning("Could not count plies for %s: %s", game, exc)
            return 80

    def _load_games(self) -> None:
        self._games = _load_directory()

    def _load_state(self) -> None:
        if STATE_FILE.exists():
            try:
                self._state = json.loads(STATE_FILE.read_text())
                _LOGGER.info("Loaded chess state: %s", self._state)
                return
            except Exception as exc:
                _LOGGER.warning("Failed to load chess state: %s", exc)

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
            _LOGGER.error("Failed to save chess state: %s", exc)
