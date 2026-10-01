import pytest

from jevbot.budget import SpendGovernor
from jevbot.config import Settings

SETTINGS = Settings()
TOKENS_PER_S = SETTINGS.max_tokens_per_s
REQUESTS_PER_S = SETTINGS.max_requests_per_s
MAX_TRIES_PER_INSTANT = REQUESTS_PER_S + 1
GAME_HOUR_S = 3600
CEILING_TOKENS = 357_142_857


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_governor(clock: FakeClock) -> SpendGovernor:
    return SpendGovernor(TOKENS_PER_S, REQUESTS_PER_S, clock=clock)


def acquire_until_refused(governor: SpendGovernor, estimated_tokens: int) -> int:
    for granted in range(MAX_TRIES_PER_INSTANT):
        if not governor.try_acquire(estimated_tokens):
            return granted
    return MAX_TRIES_PER_INSTANT


def test_request_limit_refuses_the_36th_acquire_at_one_frozen_instant():
    governor = make_governor(FakeClock())

    results = [governor.try_acquire(1) for _ in range(REQUESTS_PER_S + 1)]

    assert results == [True] * REQUESTS_PER_S + [False]
    assert governor.calls == REQUESTS_PER_S


def test_request_over_the_per_second_token_limit_fails_on_a_fresh_bucket():
    governor = make_governor(FakeClock())

    assert governor.try_acquire(90_000) is False
    assert governor.calls == 0
    assert governor.try_acquire(TOKENS_PER_S) is True


def test_capacity_returns_after_one_second_of_fake_time():
    clock = FakeClock()
    governor = make_governor(clock)
    assert governor.try_acquire(TOKENS_PER_S) is True
    assert acquire_until_refused(governor, 0) == REQUESTS_PER_S - 1

    clock.now = 0.5
    assert governor.try_acquire(TOKENS_PER_S) is False

    clock.now = 1.0
    assert governor.try_acquire(TOKENS_PER_S) is True
    assert acquire_until_refused(governor, 0) == REQUESTS_PER_S - 1


def test_idle_time_beyond_one_second_banks_no_extra_capacity():
    clock = FakeClock()
    governor = make_governor(clock)
    assert governor.try_acquire(TOKENS_PER_S) is True
    assert acquire_until_refused(governor, 0) == REQUESTS_PER_S - 1

    clock.now = 3.0
    assert governor.try_acquire(TOKENS_PER_S + 1) is False
    assert governor.try_acquire(TOKENS_PER_S) is True
    assert acquire_until_refused(governor, 0) == REQUESTS_PER_S - 1


def test_overrun_is_charged_as_debt_against_later_acquires():
    clock = FakeClock()
    governor = make_governor(clock)
    assert governor.try_acquire(1_000) is True

    governor.record(estimated_tokens=1_000, actual_tokens=TOKENS_PER_S + 1_000)

    assert governor.try_acquire(1) is False
    clock.now = 1.0
    assert governor.try_acquire(TOKENS_PER_S) is False
    clock.now = 2.0
    assert governor.try_acquire(TOKENS_PER_S) is True
    assert governor.input_tokens == TOKENS_PER_S + 1_000


def test_underrun_is_not_refunded_above_the_bucket_capacity():
    clock = FakeClock()
    governor = make_governor(clock)
    assert governor.try_acquire(TOKENS_PER_S) is True
    clock.now = 1.0

    governor.record(estimated_tokens=TOKENS_PER_S, actual_tokens=0)

    assert governor.try_acquire(TOKENS_PER_S + 1) is False
    assert governor.input_tokens == 0


def test_one_hour_at_maximum_rate_with_overruns_stays_within_the_ceiling():
    estimated_tokens = 2_000
    actual_tokens = 3_000
    clock = FakeClock()
    governor = make_governor(clock)

    for second in range(GAME_HOUR_S):
        clock.now = float(second)
        for _ in range(MAX_TRIES_PER_INSTANT):
            if not governor.try_acquire(estimated_tokens):
                break
            governor.record(estimated_tokens, actual_tokens)

    assert governor.input_tokens == governor.calls * actual_tokens
    assert governor.input_tokens <= CEILING_TOKENS
    assert governor.input_tokens >= (TOKENS_PER_S - estimated_tokens) * GAME_HOUR_S


def test_negative_estimate_on_acquire_raises_and_leaves_capacity_untouched():
    governor = make_governor(FakeClock())

    with pytest.raises(ValueError):
        governor.try_acquire(-1)

    assert governor.calls == 0
    assert governor.try_acquire(TOKENS_PER_S) is True


@pytest.mark.parametrize(("estimated_tokens", "actual_tokens"), [(-1, 0), (0, -1)])
def test_negative_token_count_on_record_raises_and_charges_nothing(
    estimated_tokens, actual_tokens
):
    governor = make_governor(FakeClock())

    with pytest.raises(ValueError):
        governor.record(estimated_tokens, actual_tokens)

    assert governor.input_tokens == 0
    assert governor.try_acquire(TOKENS_PER_S) is True


def test_clock_stepping_backwards_grants_no_extra_capacity():
    clock = FakeClock(now=10.0)
    governor = make_governor(clock)
    assert acquire_until_refused(governor, 0) == REQUESTS_PER_S

    clock.now = 5.0
    assert governor.try_acquire(0) is False

    clock.now = 10.0
    assert governor.try_acquire(0) is False

    clock.now = 11.0
    assert acquire_until_refused(governor, 0) == REQUESTS_PER_S
