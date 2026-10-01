import logging
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from typesafe_sdk import (
    JSONContent,
    Question,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeAPITimeoutError,
    TypeSafeClient,
    TypeSafeError,
    TypeSafeRateLimitError,
)

from jevbot.config import Settings

Status = Literal["ok", "timeout", "rate_limited", "error"]

_NO_RETRIES = RetryPolicy(max_retries=0)
_ANSWER_FIELDS = {"choice", "probabilities", "confidence", "noul", "score"}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JevResult:
    status: Status
    answers: dict[str, dict[str, Any]]
    latency_ms: int
    input_tokens: int
    model: str


class Asker(Protocol):
    def ask(self, state: JSONContent, questions: Mapping[str, Question]) -> JevResult: ...


class JevCaller:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._idle_clients: list[TypeSafeClient] = []
        self._lock = threading.Lock()
        self._closed = False

    def ask(self, state: JSONContent, questions: Mapping[str, Question]) -> JevResult:
        started = time.perf_counter()
        if self._closed:
            return self._failure("error", started)
        try:
            with self._checked_out_client() as client:
                response = client.system_one(state, questions)
        except TypeSafeAPITimeoutError:
            return self._failure("timeout", started)
        except TypeSafeRateLimitError:
            return self._failure("rate_limited", started)
        except TypeSafeError as error:
            logger.warning("Jev call failed: %r", error)
            return self._failure("error", started)
        except Exception:
            logger.exception("Jev call failed outside the SDK")
            return self._failure("error", started)
        return JevResult(
            status="ok",
            answers=_plain_answers(response),
            latency_ms=_elapsed_ms(started),
            input_tokens=response.usage.input_tokens or 0,
            model=response.model,
        )

    def close(self) -> None:
        with self._lock:
            self._closed = True
            clients, self._idle_clients = self._idle_clients, []
        for client in clients:
            client.close()

    @contextmanager
    def _checked_out_client(self) -> Iterator[TypeSafeClient]:
        with self._lock:
            client = self._idle_clients.pop() if self._idle_clients else None
        if client is None:
            client = TypeSafeClient(
                model=self._settings.model, timeout=self._settings.jev_timeout_s, retry=_NO_RETRIES
            )
        try:
            yield client
        finally:
            with self._lock:
                is_poolable = not self._closed
                if is_poolable:
                    self._idle_clients.append(client)
            if not is_poolable:
                client.close()

    def _failure(self, status: Status, started: float) -> JevResult:
        return JevResult(
            status=status, answers={}, latency_ms=_elapsed_ms(started), input_tokens=0, model=self._settings.model
        )


def _plain_answers(response: SystemOneResponse) -> dict[str, dict[str, Any]]:
    return {
        name: answer.model_dump(mode="json", include=_ANSWER_FIELDS) for name, answer in response.answers.items()
    }


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
