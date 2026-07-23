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
sequential  — cycle through games in library order (bundled files first,
              then user-added files, each sorted by filename then
              in-file game index)
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
import zlib
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("algorithm_art.chess_state")

# Where the *bundled* PGN game library lives inside the container (copied
# in at image-build time by the Dockerfile — see data/chess_pgn/). Static
# assets belong under /app so they are not hidden by HA's /data mount
# (same reasoning as SGF_DIR in goban_state.py).
PGN_DIR = Path(os.environ.get("CHESS_PGN_DIR", "/app/chess_pgn"))

# Where *user*-added PGNs go — uploads via /chess/upload and imports via
# /chess/import-url both land here. This is under /data (the add-on's
# persistent volume) rather than /app, because anything written to /app
# at runtime is lost the next time the container is recreated (add-on
# restart/update); /data survives that.
USER_PGN_DIR = Path(os.environ.get("CHESS_PGN_USER_DIR", "/data/chess_pgn"))

# Both directories are scanned directly (see _scan_all) rather than
# driven by a hand-maintained index file — drop a .pgn file in either
# one (or POST it to /chess/upload / /chess/import-url) and it shows up
# on the next scan, multi-game files included.

STATE_FILE = Path("/data/state/chess_state.json")

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


def _stable_id(source: str, filename: str, game_index: int) -> int:
    """Deterministic positive id for (source, filename, game_index).

    Using a hash instead of a sequential position means a game's id does
    NOT shift when other files are added/removed/renamed elsewhere in
    the library — so a persisted ``current_game_id`` / ``manual_game_id``
    in chess_state.json stays valid across rescans instead of silently
    pointing at the wrong game (or a game that no longer exists at that
    position), which is what produced "Game id N not found" errors
    whenever the library contents changed between restarts. ``source``
    is included so a user-uploaded file can't collide with a bundled one
    that happens to share a filename.
    """
    h = zlib.crc32(f"{source}:{filename}:{game_index}".encode("utf-8"))
    return h & 0x7FFFFFFF


def _extract_tag(game_text: str, tag: str) -> str:
    m = re.search(rf'\[{tag}\s+"([^"]*)"\]', game_text)
    return m.group(1).strip() if m else ""


def _scan_dir(dir_path: Path, source: str) -> list[dict]:
    """Scan one directory for *.pgn files and split each into games.

    A single file (e.g. ``chess.pgn``) may contain any number of games —
    each becomes its own library entry with its own stable id, its own
    ``game_index`` (1-based, matching chess2bmp's own ``-game`` flag),
    and metadata read straight from that game's own PGN tags.
    """
    entries: list[dict] = []

    if not dir_path.exists():
        _LOGGER.info("PGN directory does not exist yet: %s", dir_path)
        return entries

    pgn_paths = sorted(dir_path.glob("*.pgn"))
    _LOGGER.info("Scanning %s (%s): found %d .pgn file(s)", dir_path, source, len(pgn_paths))

    for path in pgn_paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _LOGGER.warning("Could not read %s: %s", path, exc)
            continue

        games_in_file = _split_pgn_games(text)
        for idx, game_text in enumerate(games_in_file, start=1):
            if not game_text.strip():
                continue
            entries.append({
                "id":          _stable_id(source, path.name, idx),
                "filename":    path.name,
                "game_index":  idx,
                "source":      source,          # "bundled" | "user"
                "white":       _extract_tag(game_text, "White") or "?",
                "black":       _extract_tag(game_text, "Black") or "?",
                "event":       _extract_tag(game_text, "Event") or path.stem,
                "date":        _extract_tag(game_text, "Date"),
                "result":      _extract_tag(game_text, "Result") or "*",
                "total_moves": max(1, _count_plies(game_text)),
            })

    return entries


def _scan_all() -> list[dict]:
    """Build the full game library by scanning both the bundled and the
    user-added PGN directories. Re-run on startup and on every
    ``/chess/rescan`` call — dropping a new .pgn file into either
    directory (or editing an existing one) picks it up with no restart
    and no hand-maintained index file required.
    """
    entries = _scan_dir(PGN_DIR, "bundled") + _scan_dir(USER_PGN_DIR, "user")
    entries.sort(key=lambda g: (g["source"] != "user", g["filename"], g["game_index"]))
    _LOGGER.info(
        "PGN library: %d game(s) total (bundled dir=%s, user dir=%s)",
        len(entries), PGN_DIR, USER_PGN_DIR,
    )
    return entries


def _load_directory() -> list:
    """Build the game library by scanning both PGN directories."""
    return _scan_all()


def _sanitize_pgn_filename(name: str) -> str:
    """Turn an arbitrary filename/URL-derived name into a safe .pgn
    filename with no path components."""
    name = os.path.basename((name or "").strip().replace("\\", "/"))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "game"
    if not name.lower().endswith(".pgn"):
        name += ".pgn"
    return name


def save_user_pgn(filename: str, content: bytes) -> Path:
    """Save PGN bytes into the user library directory and return the path.

    Used by both /chess/upload (browser file upload) and
    /chess/import-url (server-side URL fetch) — the sidecar validates
    it's parseable PGN before saving (raises ValueError otherwise), then
    the caller should call ChessStateManager.reload_games() to pick it up.
    """
    text = content.decode("utf-8", errors="replace")
    if "[Event" not in text and "1." not in text:
        raise ValueError("Doesn't look like a valid PGN file (no tags or moves found)")

    USER_PGN_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_pgn_filename(filename)
    dest = USER_PGN_DIR / safe_name

    # Avoid clobbering an existing different file that happens to share a
    # sanitized name (e.g. two uploads both named "game.pgn"); an upload
    # of the *same* name is treated as "replace/update" and allowed.
    if dest.exists():
        try:
            if dest.read_bytes() == content:
                return dest  # identical content already present, no-op
        except OSError:
            pass
        stem, suffix = dest.stem, dest.suffix
        n = 2
        while dest.exists():
            dest = USER_PGN_DIR / f"{stem}-{n}{suffix}"
            n += 1

    dest.write_bytes(content)
    _LOGGER.info("Saved uploaded PGN: %s (%d bytes)", dest, len(content))
    return dest


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
        base = USER_PGN_DIR if game.get("source") == "user" else PGN_DIR
        path = base / game["filename"]
        if not path.exists():
            raise RuntimeError(f"PGN file not found: {path}")
        return path

    def _count_plies_for(self, game: dict | None) -> int:
        if game is None:
            return 1
        # The scan already computes and caches this per-game — only fall
        # back to re-parsing the file if an entry is somehow missing it
        # (e.g. hand-constructed for testing).
        cached = game.get("total_moves")
        if isinstance(cached, int) and cached > 0:
            return cached
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
