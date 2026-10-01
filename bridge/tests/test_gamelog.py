import dataclasses
import json
from pathlib import Path

import pytest

from jevbot.config import Settings
from jevbot.gamelog import GameLogs


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeGovernorTotals:
    def __init__(self) -> None:
        self.calls = 0
        self.input_tokens = 0

    def __call__(self) -> tuple[int, int]:
        return self.calls, self.input_tokens

    def charge(self, input_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens


def make_logs(tmp_path: Path, clock: FakeClock, totals: FakeGovernorTotals) -> GameLogs:
    return GameLogs(dataclasses.replace(Settings(), log_dir=tmp_path), totals, clock)


def log_files(log_dir: Path) -> list[Path]:
    return sorted(log_dir.glob("game-*.jsonl"))


def read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def call_record(game_time: float, question: str) -> dict:
    return {"type": "call", "game_time": game_time, "question": question, "acted_on": True}


def spend_summary(calls: int, input_tokens: int, cost_usd: float, reason: str) -> dict:
    return {
        "type": "spend_summary",
        "calls": calls,
        "input_tokens": input_tokens,
        "cost_usd": pytest.approx(cost_usd, rel=1e-12),
        "reason": reason,
    }


def test_write_before_first_observe_is_dropped_and_first_observe_opens_one_empty_file(tmp_path):
    logs = make_logs(tmp_path, FakeClock(), FakeGovernorTotals())
    logs.write(call_record(0.0, "before_any_game"))

    assert log_files(tmp_path) == []
    assert logs.is_open is False

    logs.observe(5.0)

    files = log_files(tmp_path)
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == ""
    assert logs.is_open is True


def test_game_time_drop_of_61_s_closes_first_log_with_reset_summary_and_opens_second(tmp_path):
    clock = FakeClock()
    totals = FakeGovernorTotals()
    totals.charge(5_000)
    logs = make_logs(tmp_path, clock, totals)

    logs.observe(100.0)
    logs.write(call_record(100.0, "push_lane"))
    totals.charge(1_000)
    totals.charge(2_000)
    logs.observe(161.0)

    clock.now = 1.0
    logs.observe(100.0)
    logs.write(call_record(100.0, "retreat"))
    totals.charge(4_000)
    logs.close("victory")

    files = log_files(tmp_path)
    assert len(files) == 2
    records_by_first_question = {
        records[0]["question"]: records for records in map(read_records, files)
    }
    assert records_by_first_question == {
        "push_lane": [
            call_record(100.0, "push_lane"),
            spend_summary(calls=2, input_tokens=3_000, cost_usd=0.000126, reason="reset"),
        ],
        "retreat": [
            call_record(100.0, "retreat"),
            spend_summary(calls=1, input_tokens=4_000, cost_usd=0.000168, reason="victory"),
        ],
    }


@pytest.mark.parametrize("drop_s", [30.0, 60.0])
def test_game_time_drop_of_at_most_60_s_keeps_writing_to_one_file(tmp_path, drop_s):
    totals = FakeGovernorTotals()
    logs = make_logs(tmp_path, FakeClock(), totals)
    dropped_game_time = 200.0 - drop_s

    logs.observe(200.0)
    logs.write(call_record(200.0, "push_lane"))
    totals.charge(1_000)
    logs.observe(dropped_game_time)
    logs.write(call_record(dropped_game_time, "retreat"))
    totals.charge(1_000)
    logs.close("defeat")

    files = log_files(tmp_path)
    assert len(files) == 1
    assert read_records(files[0]) == [
        call_record(200.0, "push_lane"),
        call_record(dropped_game_time, "retreat"),
        spend_summary(calls=2, input_tokens=2_000, cost_usd=0.000084, reason="defeat"),
    ]


def test_tick_after_119_s_without_observe_keeps_the_game_open(tmp_path):
    clock = FakeClock()
    logs = make_logs(tmp_path, clock, FakeGovernorTotals())
    logs.observe(10.0)
    logs.write(call_record(10.0, "push_lane"))

    clock.now = 119.0
    logs.tick()

    assert logs.is_open is True
    assert read_records(log_files(tmp_path)[0]) == [call_record(10.0, "push_lane")]


def test_tick_after_121_s_without_observe_closes_with_idle_summary(tmp_path):
    clock = FakeClock()
    totals = FakeGovernorTotals()
    logs = make_logs(tmp_path, clock, totals)
    logs.observe(10.0)
    logs.write(call_record(10.0, "push_lane"))
    totals.charge(1_000)

    clock.now = 121.0
    logs.tick()
    logs.write(call_record(11.0, "after_close"))

    assert logs.is_open is False
    files = log_files(tmp_path)
    assert len(files) == 1
    assert read_records(files[0]) == [
        call_record(10.0, "push_lane"),
        spend_summary(calls=1, input_tokens=1_000, cost_usd=0.000042, reason="idle"),
    ]


def test_summary_cost_is_input_tokens_at_0_042_usd_per_million(tmp_path):
    totals = FakeGovernorTotals()
    logs = make_logs(tmp_path, FakeClock(), totals)
    logs.observe(0.0)
    totals.charge(1_500_000)
    totals.charge(2_500_000)
    logs.close("lobby_closed")

    assert read_records(log_files(tmp_path)[0]) == [
        spend_summary(calls=2, input_tokens=4_000_000, cost_usd=0.168, reason="lobby_closed"),
    ]
