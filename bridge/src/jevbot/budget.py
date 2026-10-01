import threading
import time
from collections.abc import Callable

_CHARS_PER_TOKEN = 3
_TOKENS_PER_MTOK = 1_000_000


def estimate_tokens(json_body: str | bytes) -> int:
    return len(json_body) // _CHARS_PER_TOKEN


class _Bucket:
    def __init__(self, rate_per_s: float, now: float) -> None:
        self._capacity = rate_per_s
        self._rate_per_s = rate_per_s
        self._level = rate_per_s
        self._updated_at = now

    def refill(self, now: float) -> None:
        if now <= self._updated_at:
            return
        elapsed = now - self._updated_at
        self._level = min(self._capacity, self._level + elapsed * self._rate_per_s)
        self._updated_at = now

    def has(self, amount: float) -> bool:
        return self._level >= amount

    def take(self, amount: float) -> None:
        self._level -= amount


class SpendGovernor:
    def __init__(
        self,
        max_tokens_per_s: int,
        max_requests_per_s: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        now = clock()
        self._tokens = _Bucket(max_tokens_per_s, now)
        self._requests = _Bucket(max_requests_per_s, now)
        self._calls = 0
        self._input_tokens = 0

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def input_tokens(self) -> int:
        return self._input_tokens

    def cost_usd(self, price_per_mtok: float) -> float:
        return self._input_tokens * price_per_mtok / _TOKENS_PER_MTOK

    def try_acquire(self, estimated_tokens: int) -> bool:
        _require_non_negative("estimated_tokens", estimated_tokens)
        with self._lock:
            now = self._clock()
            self._tokens.refill(now)
            self._requests.refill(now)
            if not (self._requests.has(1) and self._tokens.has(estimated_tokens)):
                return False
            self._requests.take(1)
            self._tokens.take(estimated_tokens)
            self._calls += 1
            return True

    def record(self, estimated_tokens: int, actual_tokens: int) -> None:
        _require_non_negative("estimated_tokens", estimated_tokens)
        _require_non_negative("actual_tokens", actual_tokens)
        with self._lock:
            self._tokens.refill(self._clock())
            self._tokens.take(max(0, actual_tokens - estimated_tokens))
            self._input_tokens += actual_tokens


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value}")
