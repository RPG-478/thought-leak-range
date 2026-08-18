from thought_leak_range.motor_token import (
    MotorToken,
    MotorTokenArbiter,
    MotorTokenFrame,
    MotorTokenParser,
)
from thought_leak_range.protocol import Action


RUN_ID = "motortoken1"


def _frame(*, obs: int, token: MotorToken, received_at: float):
    return MotorTokenFrame(
        run_id=RUN_ID,
        obs=obs,
        token=token,
        received_at=received_at,
    )


def test_parser_accepts_each_motor_token():
    for obs, token in enumerate(MotorToken):
        parser = MotorTokenParser(expected_run_id=RUN_ID, expected_obs=obs)
        parsed = parser.feed(f" \n{token.value}ignored", now=1.0)
        assert parsed[0].token is token


def test_parser_fails_closed_after_invalid_first_character():
    parser = MotorTokenParser(expected_run_id=RUN_ID, expected_obs=1)

    assert parser.feed("L2", now=1.0) == []
    assert parser.feed("2", now=1.1) == []


def test_fresh_response_survives_newer_observation_being_in_flight():
    arbiter = MotorTokenArbiter(run_id=RUN_ID, maximum_age_ms=400)
    decision = arbiter.offer(
        _frame(obs=3, token=MotorToken.RIGHT_SHORT, received_at=1.3),
        captured_at=1.0,
        now=1.3,
    )

    assert decision.accepted
    assert arbiter.take_tick(now=1.31).action is Action.RIGHT


def test_newer_accepted_token_preempts_active_pulse():
    arbiter = MotorTokenArbiter(run_id=RUN_ID)
    arbiter.offer(
        _frame(obs=1, token=MotorToken.RIGHT_LONG, received_at=1.1),
        captured_at=1.0,
        now=1.1,
    )
    newer = arbiter.offer(
        _frame(obs=2, token=MotorToken.LEFT_SHORT, received_at=1.2),
        captured_at=1.1,
        now=1.2,
    )

    assert newer.accepted
    assert newer.preempted.token is MotorToken.RIGHT_LONG
    assert arbiter.take_tick(now=1.21).action is Action.LEFT


def test_out_of_order_response_cannot_replace_newer_token():
    arbiter = MotorTokenArbiter(run_id=RUN_ID)
    arbiter.offer(
        _frame(obs=5, token=MotorToken.FIRE, received_at=1.2),
        captured_at=1.0,
        now=1.2,
    )
    old = arbiter.offer(
        _frame(obs=4, token=MotorToken.WAIT, received_at=1.21),
        captured_at=1.05,
        now=1.21,
    )

    assert not old.accepted
    assert old.reason == "stale_or_out_of_order"
    assert arbiter.take_tick(now=1.22).action is Action.FIRE


def test_long_and_short_pulses_have_model_selected_lengths():
    arbiter = MotorTokenArbiter(run_id=RUN_ID)
    arbiter.offer(
        _frame(obs=1, token=MotorToken.LEFT_LONG, received_at=1.1),
        captured_at=1.0,
        now=1.1,
    )
    assert [arbiter.take_tick(now=1.11 + i * 0.02).action for i in range(5)] == [
        Action.LEFT
    ] * 5
    assert arbiter.take_tick(now=1.22) is None

    arbiter.offer(
        _frame(obs=2, token=MotorToken.RIGHT_SHORT, received_at=1.3),
        captured_at=1.2,
        now=1.3,
    )
    assert arbiter.take_tick(now=1.31).action is Action.RIGHT
    assert arbiter.take_tick(now=1.33).action is Action.RIGHT
    assert arbiter.take_tick(now=1.35) is None


def test_expired_observation_fails_closed():
    arbiter = MotorTokenArbiter(run_id=RUN_ID, maximum_age_ms=400)
    decision = arbiter.offer(
        _frame(obs=1, token=MotorToken.FIRE, received_at=1.401),
        captured_at=1.0,
        now=1.401,
    )

    assert not decision.accepted
    assert decision.reason == "observation_expired"
