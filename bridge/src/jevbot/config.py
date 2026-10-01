import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self

LOOPBACK_HOST = "127.0.0.1"
MAX_PORT = 65_535


@dataclass(frozen=True)
class Settings:
    host: str = LOOPBACK_HOST
    port: int = 8765
    model: str = "jev-1.13.0"
    jev_timeout_s: float = 1.2
    max_tokens_per_s: int = 85_000
    max_requests_per_s: int = 35
    price_per_mtok: float = 0.042
    log_dir: Path = Path("logs")
    game_idle_close_s: int = 120
    game_reset_gap_s: int = 60
    max_body_bytes: int = 262_144

    def __post_init__(self) -> None:
        if self.host != LOOPBACK_HOST:
            raise ValueError(f"host must be {LOOPBACK_HOST}, got {self.host!r}")
        if not 0 <= self.port <= MAX_PORT:
            raise ValueError(f"port must be between 0 and {MAX_PORT}, got {self.port}")

    @classmethod
    def from_env(cls) -> Self:
        defaults = cls()
        port = _read_env("JEVBOT_PORT")
        log_dir = _read_env("JEVBOT_LOG_DIR")
        model = _read_env("JEVBOT_MODEL")
        return cls(
            port=defaults.port if port is None else _parse_port(port),
            log_dir=defaults.log_dir if log_dir is None else Path(log_dir).expanduser(),
            model=defaults.model if model is None else model,
        )


def _read_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is not None and not value.strip():
        raise ValueError(f"{name} is set but empty")
    return value


def _parse_port(raw: str) -> int:
    if not (raw.isascii() and raw.isdigit()):
        raise ValueError(f"JEVBOT_PORT must be a plain integer, got {raw!r}")
    port = int(raw)
    if port == 0:
        raise ValueError("JEVBOT_PORT must not be 0; bots need a fixed port to reach the bridge")
    return port
