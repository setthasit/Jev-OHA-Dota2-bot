import dataclasses
import http.client
import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from jevbot.budget import SpendGovernor
from jevbot.config import Settings
from jevbot.gamelog import GameLogs
from jevbot.jev import JevResult
from jevbot.server import make_server

DECIDE_PATH = "/v1/decide"
EVENTS_PATH = "/v1/events"
WAIT_S = 5.0
SERVE_POLL_INTERVAL_S = 0.01
STATE = {
    "towers": [{"lane": "mid", "team": 3, "standing": True}],
    "allies": [{"hero": "lina", "hp": "high"}],
    "enemies_visible": [],
    "enemies_missing": ["pudge"],
}
OK_ANSWERS = {
    "objective": {"choice": "push_mid", "probabilities": {"push_mid": 0.7, "farm": 0.3}, "confidence": 0.7}
}
OK_RESULT = JevResult(status="ok", answers=OK_ANSWERS, latency_ms=240, input_tokens=1_800, model="jev-1.13.0")
TIMEOUT_RESULT = JevResult(status="timeout", answers={}, latency_ms=1_200, input_tokens=0, model="jev-1.13.0")
GAME_END = {"type": "game_end", "t": 130.0, "winner": 2}


class FakeAsker:
    def __init__(self) -> None:
        self.result = OK_RESULT
        self.asked_states: list[Any] = []
        self.entered = threading.Event()
        self.released = threading.Event()
        self.released.set()

    @property
    def calls(self) -> int:
        return len(self.asked_states)

    def ask(self, state, questions) -> JevResult:
        self.asked_states.append(state)
        self.entered.set()
        self.released.wait(WAIT_S)
        return self.result


class SignallingGameLogs(GameLogs):
    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self.game_end_logged = threading.Event()

    def write(self, record: dict[str, Any]) -> None:
        super().write(record)
        if record.get("event", {}).get("type") == "game_end":
            self.game_end_logged.set()


@dataclasses.dataclass
class Bridge:
    server: Any
    serving: threading.Thread
    logs: SignallingGameLogs
    fake: FakeAsker
    log_dir: Path

    def post(self, path: str, payload: dict, headers: dict[str, str] | None = None) -> tuple[int, dict | None]:
        def send_request(connection: http.client.HTTPConnection) -> None:
            connection.request("POST", path, encode(payload), {"Content-Type": "application/json", **(headers or {})})

        return self._exchange(send_request)

    def post_headers_declaring(self, path: str, content_length: int) -> tuple[int, dict | None]:
        def send_headers_only(connection: http.client.HTTPConnection) -> None:
            connection.putrequest("POST", path)
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(content_length))
            connection.endheaders()

        return self._exchange(send_headers_only)

    def _exchange(self, send: Callable[[http.client.HTTPConnection], None]) -> tuple[int, dict | None]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=WAIT_S)
        try:
            send(connection)
            response = connection.getresponse()
            raw = response.read()
        finally:
            connection.close()
        return response.status, json.loads(raw) if raw else None

    def log_files(self) -> list[Path]:
        return sorted(self.log_dir.glob("game-*.jsonl"))

    def records(self) -> list[dict]:
        (path,) = self.log_files()
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def stop(self) -> None:
        self.fake.released.set()
        self.server.shutdown()
        self.server.server_close()
        self.logs.close("shutdown")
        self.serving.join(WAIT_S)


@pytest.fixture
def bridge(request, tmp_path):
    settings = dataclasses.replace(Settings(), port=0, log_dir=tmp_path, **getattr(request, "param", {}))
    governor = SpendGovernor(settings.max_tokens_per_s, settings.max_requests_per_s)
    logs = SignallingGameLogs(settings, lambda: (governor.calls, governor.input_tokens), lambda: 0.0)
    fake = FakeAsker()
    server = make_server(settings, fake, governor, logs)
    serving = threading.Thread(target=server.serve_forever, args=(SERVE_POLL_INTERVAL_S,))
    serving.start()
    running = Bridge(server, serving, logs, fake, tmp_path)
    try:
        yield running
    finally:
        running.stop()


def encode(payload: dict) -> bytes:
    return json.dumps(payload).encode()


def decide_request(request_id: str = "d1", kind: str = "team_macro", game_time: float = 120.0, state=STATE) -> dict:
    return {"id": request_id, "kind": kind, "team": 2, "player": 1, "game_time": game_time, "state": state}


def outcome(status: str, answers: dict, latency_ms: int, input_tokens: int) -> dict:
    return {"status": status, "answers": answers, "latency_ms": latency_ms, "input_tokens": input_tokens}


def fallback(status: str) -> dict:
    return outcome(status, {}, 0, 0)


def call_record(request: dict, result: dict) -> dict:
    return {
        "type": "call",
        "game_time": request["game_time"],
        "team": request["team"],
        "player": request["player"],
        "kind": request["kind"],
        "id": request["id"],
        **result,
    }


def event_record(team: int, event: dict) -> dict:
    return {"type": "event", "team": team, "event": event}


def spend_summary(calls: int, input_tokens: int, cost_usd: float, reason: str) -> dict:
    return {
        "type": "spend_summary",
        "calls": calls,
        "input_tokens": input_tokens,
        "cost_usd": pytest.approx(cost_usd, rel=1e-12),
        "reason": reason,
    }


def test_ok_decide_returns_answers_and_writes_one_call_record(bridge):
    request = decide_request()
    ok = outcome("ok", OK_ANSWERS, 240, 1_800)

    assert bridge.post(DECIDE_PATH, request) == (200, {"id": "d1", **ok})
    assert bridge.fake.asked_states == [STATE]
    assert bridge.records() == [call_record(request, ok)]


def test_jev_timeout_returns_timeout_and_bills_the_token_estimate(bridge):
    bridge.fake.result = TIMEOUT_RESULT
    request = decide_request()
    timed_out = outcome("timeout", {}, 1_200, 81)

    assert bridge.post(DECIDE_PATH, request) == (200, {"id": "d1", **timed_out})

    bridge.stop()
    assert bridge.records() == [
        call_record(request, timed_out),
        spend_summary(calls=1, input_tokens=81, cost_usd=0.000003402, reason="shutdown"),
    ]


@pytest.mark.parametrize("status", ["error", "rate_limited"])
def test_failed_jev_call_returns_its_status_and_bills_the_reported_tokens(bridge, status):
    bridge.fake.result = JevResult(status=status, answers={}, latency_ms=35, input_tokens=0, model="jev-1.13.0")
    request = decide_request()
    failed = outcome(status, {}, 35, 0)

    assert bridge.post(DECIDE_PATH, request) == (200, {"id": "d1", **failed})
    assert bridge.records() == [call_record(request, failed)]


@pytest.mark.parametrize("bridge", [{"max_tokens_per_s": 1}], indirect=True)
def test_exhausted_governor_returns_budget_without_asking_jev(bridge):
    request = decide_request()

    assert bridge.post(DECIDE_PATH, request) == (200, {"id": "d1", **fallback("budget")})
    assert bridge.fake.calls == 0

    bridge.stop()
    assert bridge.records() == [
        call_record(request, fallback("budget")),
        spend_summary(calls=0, input_tokens=0, cost_usd=0.0, reason="shutdown"),
    ]


def test_unknown_kind_returns_unknown_kind_without_asking_jev(bridge):
    request = decide_request(kind="ward_spot")

    assert bridge.post(DECIDE_PATH, request) == (200, {"id": "d1", **fallback("unknown_kind")})
    assert bridge.fake.calls == 0
    assert bridge.records() == [call_record(request, fallback("unknown_kind"))]


def test_declared_body_over_256_kib_is_rejected_with_413_before_any_log_or_call(bridge):
    assert bridge.post_headers_declaring(DECIDE_PATH, 300_000) == (413, {"error": "Request Entity Too Large"})
    assert bridge.fake.calls == 0
    assert bridge.log_files() == []


@pytest.mark.parametrize(
    ("headers", "status", "error"),
    [
        ({"Origin": "http://127.0.0.1"}, 403, "Forbidden"),
        ({"Host": "localhost"}, 403, "Forbidden"),
        ({"Content-Type": "text/plain"}, 415, "Unsupported Media Type"),
    ],
)
def test_browser_style_requests_are_rejected_before_any_paid_call(bridge, headers, status, error):
    assert bridge.post(DECIDE_PATH, decide_request(), headers) == (status, {"error": error})
    assert bridge.fake.calls == 0
    assert bridge.log_files() == []


def test_events_are_appended_as_event_records_tagged_with_the_team(bridge):
    events = [
        {"type": "kill", "t": 300.0, "killer": 3, "victim": 7},
        {"type": "tower_destroyed", "t": 310.5, "lane": "mid"},
    ]

    assert bridge.post(EVENTS_PATH, {"team": 3, "events": events}) == (204, None)
    assert bridge.records() == [event_record(3, event) for event in events]


def test_game_end_during_an_in_flight_decide_closes_the_game_after_that_call_record(bridge):
    bridge.fake.released.clear()
    request = decide_request()
    ok = outcome("ok", OK_ANSWERS, 240, 1_800)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            decide = pool.submit(bridge.post, DECIDE_PATH, request)
            assert bridge.fake.entered.wait(WAIT_S)
            game_end = pool.submit(bridge.post, EVENTS_PATH, {"team": 2, "events": [GAME_END]})
            assert bridge.logs.game_end_logged.wait(WAIT_S)
            assert bridge.records() == [event_record(2, GAME_END)]

            bridge.fake.released.set()
            assert decide.result(WAIT_S) == (200, {"id": "d1", **ok})
            assert game_end.result(WAIT_S) == (204, None)
    finally:
        bridge.fake.released.set()

    assert bridge.records() == [
        event_record(2, GAME_END),
        call_record(request, ok),
        spend_summary(calls=1, input_tokens=1_800, cost_usd=0.0000756, reason="game_end"),
    ]
    assert bridge.fake.calls == 1


def test_shutdown_writes_spend_summary_last_with_the_game_totals(bridge):
    kill = {"type": "kill", "t": 125.0, "killer": 1, "victim": 6}
    assert bridge.post(DECIDE_PATH, decide_request("d1"))[0] == 200
    assert bridge.post(EVENTS_PATH, {"team": 2, "events": [kill]}) == (204, None)
    assert bridge.post(DECIDE_PATH, decide_request("d2", game_time=130.0))[0] == 200

    bridge.stop()

    records = bridge.records()
    assert [record["type"] for record in records] == ["call", "event", "call", "spend_summary"]
    assert records[-1] == spend_summary(calls=2, input_tokens=3_600, cost_usd=0.0001512, reason="shutdown")
