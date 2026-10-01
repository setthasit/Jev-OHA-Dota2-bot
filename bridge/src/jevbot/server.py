import json
import logging
import threading
from collections.abc import Callable
from contextlib import suppress
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, NoReturn
from urllib.parse import urlsplit

from jevbot.budget import SpendGovernor, estimate_tokens
from jevbot.config import Settings
from jevbot.gamelog import GameLogs
from jevbot.jev import Asker
from jevbot.questions import lookup

_TEAMS = (2, 3)
_GAME_END = "game_end"
_TICK_INTERVAL_S = 1.0
_DRAIN_GRACE_JEV_TIMEOUTS = 2
_HANDLER_TIMEOUT_S = 5.0
_MAX_CONNECTIONS = 64

logger = logging.getLogger(__name__)


class _Rejected(Exception):
    def __init__(self, status: HTTPStatus, allow: str | None = None) -> None:
        super().__init__(status.phrase)
        self.status = status
        self.allow = allow


class _InFlightDecides:
    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._count = 0

    def __enter__(self) -> None:
        with self._changed:
            self._count += 1

    def __exit__(self, *_exc: object) -> None:
        with self._changed:
            self._count -= 1
            self._changed.notify_all()

    def wait_until_idle(self, timeout_s: float) -> None:
        with self._changed:
            self._changed.wait_for(lambda: self._count == 0, timeout_s)


class _BridgeServer(ThreadingHTTPServer):
    block_on_close = False

    def __init__(self, settings: Settings, asker: Asker, governor: SpendGovernor, logs: GameLogs) -> None:
        self.settings = settings
        self.asker = asker
        self.governor = governor
        self.logs = logs
        self.in_flight = _InFlightDecides()
        self.ending_game = threading.Lock()
        self.drain_grace_s = settings.jev_timeout_s * _DRAIN_GRACE_JEV_TIMEOUTS
        self._connection_slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)
        self._stop_ticking = threading.Event()
        self._ticker = threading.Thread(target=self._tick_logs, name="jevbot-log-ticker", daemon=True)
        super().__init__((settings.host, settings.port), _Handler)
        self.local_host = f"{settings.host}:{self.server_address[1]}"
        self._ticker.start()

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._connection_slots.acquire(blocking=False):
            _send_busy(request)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()

    def server_close(self) -> None:
        self._stop_ticking.set()
        if self._ticker.is_alive():
            self._ticker.join()
        super().server_close()
        self.in_flight.wait_until_idle(self.drain_grace_s)

    def _tick_logs(self) -> None:
        while not self._stop_ticking.wait(_TICK_INTERVAL_S):
            try:
                self.logs.tick()
            except Exception:
                logger.exception("Game log tick failed")


def make_server(settings: Settings, asker: Asker, governor: SpendGovernor, logs: GameLogs) -> ThreadingHTTPServer:
    return _BridgeServer(settings, asker, governor, logs)


_Response = tuple[HTTPStatus, dict[str, Any] | None]


class _Handler(BaseHTTPRequestHandler):
    server: _BridgeServer
    timeout = _HANDLER_TIMEOUT_S

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("%r", format % args)

    def _dispatch(self, method: str) -> None:
        path = urlsplit(self.path).path
        allow = None
        try:
            self._require_local_caller()
            status, body = _route(path, method)(self)
        except _Rejected as rejection:
            status, body, allow = rejection.status, _error_body(rejection.status), rejection.allow
        except Exception:
            logger.exception("%s %s failed", method, path)
            status, body = HTTPStatus.INTERNAL_SERVER_ERROR, _error_body(HTTPStatus.INTERNAL_SERVER_ERROR)
        self._send(status, body, allow)

    def _require_local_caller(self) -> None:
        if "Origin" in self.headers or self.headers.get_all("Host") != [self.server.local_host]:
            raise _Rejected(HTTPStatus.FORBIDDEN)

    def _send(self, status: HTTPStatus, body: dict[str, Any] | None, allow: str | None) -> None:
        payload = None if body is None else _encode(body)
        self.send_response(status)
        if allow is not None:
            self.send_header("Allow", allow)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload is not None:
            self.wfile.write(payload)

    def _read_body(self) -> bytes:
        if self.headers.get_content_type() != "application/json":
            raise _Rejected(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        declared = self.headers.get("Content-Length")
        if declared is None:
            raise _Rejected(HTTPStatus.LENGTH_REQUIRED)
        if not (declared.isascii() and declared.isdigit()):
            raise _Rejected(HTTPStatus.BAD_REQUEST)
        length = int(declared)
        if length > self.server.settings.max_body_bytes:
            raise _Rejected(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            return self.rfile.read(length)
        except TimeoutError as error:
            raise _Rejected(HTTPStatus.REQUEST_TIMEOUT) from error

    def _health(self) -> _Response:
        return HTTPStatus.OK, {"status": "ok", "game_open": self.server.logs.is_open}

    def _decide(self) -> _Response:
        body = self._read_body()
        request = _parse_decide(body)
        with self.server.in_flight:
            self.server.logs.observe(request["game_time"])
            outcome = self._decide_outcome(request, body)
            self.server.logs.write(
                {
                    "type": "call",
                    "game_time": request["game_time"],
                    "team": request["team"],
                    "player": request["player"],
                    "kind": request["kind"],
                    "id": request["id"],
                    **outcome,
                }
            )
        return HTTPStatus.OK, {"id": request["id"], **outcome}

    def _decide_outcome(self, request: dict[str, Any], body: bytes) -> dict[str, Any]:
        spec = lookup(request["kind"])
        if spec is None:
            return _fallback_outcome("unknown_kind")
        state = request["state"]
        questions = spec.build(state)
        estimate = estimate_tokens(body)
        if not self.server.governor.try_acquire(estimate):
            return _fallback_outcome("budget")
        result = self.server.asker.ask(state, questions)
        billed = estimate if result.status == "timeout" else result.input_tokens
        self.server.governor.record(estimate, billed)
        return {
            "status": result.status,
            "answers": result.answers,
            "latency_ms": result.latency_ms,
            "input_tokens": billed,
        }

    def _events(self) -> _Response:
        batch = _parse_events(self._read_body())
        for event in batch["events"]:
            if event["type"] == _GAME_END:
                self._end_game(batch["team"], event)
                break
            self._log_event(batch["team"], event)
        return HTTPStatus.NO_CONTENT, None

    def _end_game(self, team: int, event: dict[str, Any]) -> None:
        with self.server.ending_game:
            if not self.server.logs.is_open:
                return
            self._log_event(team, event)
            self.server.in_flight.wait_until_idle(self.server.drain_grace_s)
            self.server.logs.close(_GAME_END)

    def _log_event(self, team: int, event: dict[str, Any]) -> None:
        self.server.logs.observe(event["t"])
        self.server.logs.write({"type": "event", "team": team, "event": event})


_ROUTES: dict[str, tuple[str, Callable[[_Handler], _Response]]] = {
    "/v1/decide": ("POST", _Handler._decide),
    "/v1/events": ("POST", _Handler._events),
    "/health": ("GET", _Handler._health),
}


def _route(path: str, method: str) -> Callable[[_Handler], _Response]:
    route = _ROUTES.get(path)
    if route is None:
        raise _Rejected(HTTPStatus.NOT_FOUND)
    allowed_method, handle = route
    if method != allowed_method:
        raise _Rejected(HTTPStatus.METHOD_NOT_ALLOWED, allow=allowed_method)
    return handle


def _send_busy(request: Any) -> None:
    payload = _encode(_error_body(HTTPStatus.SERVICE_UNAVAILABLE))
    head = f"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n"
    with suppress(OSError):
        request.setblocking(False)
        request.send(head.encode() + payload)


def _parse_decide(body: bytes) -> dict[str, Any]:
    request = _load_object(body)
    is_valid = (
        isinstance(request.get("id"), str)
        and isinstance(request.get("kind"), str)
        and _is_team(request.get("team"))
        and _is_int(request.get("player"))
        and _is_number(request.get("game_time"))
        and isinstance(request.get("state"), dict)
    )
    if not is_valid:
        raise _Rejected(HTTPStatus.BAD_REQUEST)
    return request


def _parse_events(body: bytes) -> dict[str, Any]:
    batch = _load_object(body)
    events = batch.get("events")
    is_valid = (
        _is_team(batch.get("team"))
        and isinstance(events, list)
        and all(_is_event(event) for event in events)
    )
    if not is_valid:
        raise _Rejected(HTTPStatus.BAD_REQUEST)
    return batch


def _is_event(event: object) -> bool:
    return isinstance(event, dict) and isinstance(event.get("type"), str) and _is_number(event.get("t"))


def _load_object(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body, parse_constant=_reject_non_finite, parse_float=_finite_float)
    except (ValueError, RecursionError) as error:
        raise _Rejected(HTTPStatus.BAD_REQUEST) from error
    if not isinstance(value, dict):
        raise _Rejected(HTTPStatus.BAD_REQUEST)
    return value


def _reject_non_finite(literal: str) -> NoReturn:
    raise ValueError(f"non-finite number {literal}")


def _finite_float(literal: str) -> float:
    value = float(literal)
    if value in (float("inf"), float("-inf")):
        raise ValueError("number out of range")
    return value


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return _is_int(value) or isinstance(value, float)


def _is_team(value: object) -> bool:
    return _is_int(value) and value in _TEAMS


def _fallback_outcome(status: str) -> dict[str, Any]:
    return {"status": status, "answers": {}, "latency_ms": 0, "input_tokens": 0}


def _error_body(status: HTTPStatus) -> dict[str, Any]:
    return {"error": status.phrase}


def _encode(body: dict[str, Any]) -> bytes:
    return json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
