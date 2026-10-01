import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from jevbot.config import Settings

_TOKENS_PER_MTOK = 1_000_000


@dataclass
class _OpenGame:
    file: TextIO
    latest_game_time: float
    last_observed_at: float
    calls_at_open: int
    input_tokens_at_open: int


class GameLogs:
    def __init__(
        self,
        settings: Settings,
        governor_totals: Callable[[], tuple[int, int]],
        clock: Callable[[], float],
    ) -> None:
        self._settings = settings
        self._governor_totals = governor_totals
        self._clock = clock
        self._lock = threading.Lock()
        self._game: _OpenGame | None = None

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._game is not None

    def observe(self, game_time: float) -> None:
        with self._lock:
            now = self._clock()
            if self._game is not None and self._is_reset(self._game, game_time):
                self._close("reset")
            if self._game is None:
                self._game = self._open(game_time, now)
            self._game.latest_game_time = max(self._game.latest_game_time, game_time)
            self._game.last_observed_at = now

    def write(self, record: dict[str, Any]) -> None:
        with self._lock:
            if self._game is not None:
                _write_line(self._game.file, record)

    def close(self, reason: str) -> None:
        with self._lock:
            self._close(reason)

    def tick(self) -> None:
        with self._lock:
            if self._game is not None and self._is_idle(self._game):
                self._close("idle")

    def _is_reset(self, game: _OpenGame, game_time: float) -> bool:
        return game_time < game.latest_game_time - self._settings.game_reset_gap_s

    def _is_idle(self, game: _OpenGame) -> bool:
        return self._clock() - game.last_observed_at >= self._settings.game_idle_close_s

    def _open(self, game_time: float, now: float) -> _OpenGame:
        calls, input_tokens = self._governor_totals()
        return _OpenGame(
            file=_create_log_file(self._settings.log_dir),
            latest_game_time=game_time,
            last_observed_at=now,
            calls_at_open=calls,
            input_tokens_at_open=input_tokens,
        )

    def _close(self, reason: str) -> None:
        game, self._game = self._game, None
        if game is None:
            return
        calls, input_tokens = self._governor_totals()
        game_input_tokens = input_tokens - game.input_tokens_at_open
        summary = {
            "type": "spend_summary",
            "calls": calls - game.calls_at_open,
            "input_tokens": game_input_tokens,
            "cost_usd": game_input_tokens * self._settings.price_per_mtok / _TOKENS_PER_MTOK,
            "reason": reason,
        }
        try:
            _write_line(game.file, summary)
        finally:
            game.file.close()


def _write_line(file: TextIO, record: dict[str, Any]) -> None:
    file.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    file.flush()


def _create_log_file(log_dir: Path) -> TextIO:
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = f"game-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    path = log_dir / f"{stem}.jsonl"
    suffix = 1
    while True:
        try:
            return open(path, "a", encoding="utf-8", opener=_exclusive_opener)
        except FileExistsError:
            suffix += 1
            path = log_dir / f"{stem}_{suffix}.jsonl"


def _exclusive_opener(path: str, flags: int) -> int:
    return os.open(path, flags | os.O_EXCL, 0o666)
