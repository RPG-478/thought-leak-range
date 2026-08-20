from thought_leak_range.motor_token import (
    MotorToken,
    MotorTokenArbiter,
    MotorTokenFrame,
    MotorTokenParser,
)
from thought_leak_range.protocol import Action


RUN_ID = "motortoken1"


def test_parser_can_fail_closed_on_long_tokens_removed_by_v5_lite() -> None:
    parser = MotorTokenParser(
        expected_run_id=RUN_ID,
        expected_obs=1,
        allowed_tokens=frozenset(
            {
                MotorToken.WAIT,
                MotorToken.LEFT_SHORT,
                MotorToken.RIGHT_SHORT,
                MotorToken.FIRE,
            }
        ),
    )
    assert parser.feed("2", now=1.0) == []

    accepted = MotorTokenParser(
        expected_run_id=RUN_ID,
        expected_obs=2,
        allowed_tokens=frozenset({MotorToken.RIGHT_SHORT}),
    ).feed("3", now=1.0)
    assert len(accepted) == 1
    assert accepted[0].token is MotorToken.RIGHT_SHORT


def test_parser_maps_semantic_v5_letters_to_hold_tokens() -> None:
    aliases = {
        "W": MotorToken.WAIT,
        "L": MotorToken.LEFT_HOLD,
        "R": MotorToken.RIGHT_HOLD,
        "F": MotorToken.FIRE,
    }
    parsed = MotorTokenParser(
        expected_run_id=RUN_ID,
        expected_obs=3,
        token_aliases=aliases,
    ).feed("R", now=1.0)
    assert len(parsed) == 1
    assert parsed[0].token is MotorToken.RIGHT_HOLD


def _frame(
    *,
    obs: int,
    token: MotorToken,
    received_at: float,
    game_tick: int | None = None,
):
    return MotorTokenFrame(
        run_id=RUN_ID,
        obs=obs,
        token=token,
        received_at=received_at,
        obs_game_tick=game_tick,
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
    assert decision.frame.captured_at == 1.0
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


def test_game_tick_lease_commits_only_newest_result_once_per_tick():
    arbiter = MotorTokenArbiter(run_id=RUN_ID, game_tick_lease=True)
    assert arbiter.offer(
        _frame(
            obs=1,
            token=MotorToken.RIGHT_LONG,
            received_at=1.10,
            game_tick=0,
        ),
        captured_at=1.0,
        now=1.10,
    ).accepted
    assert arbiter.offer(
        _frame(
            obs=2,
            token=MotorToken.LEFT_SHORT,
            received_at=1.11,
            game_tick=0,
        ),
        captured_at=1.0,
        now=1.11,
    ).accepted

    committed = arbiter.take_tick(game_tick=0, now=1.12)
    assert committed is not None
    assert committed.frame.obs == 2
    assert committed.action is Action.LEFT
    assert committed.committed
    assert committed.superseded_before_commit == 1
    assert committed.expires_at_game_tick == 2

    # A late completion on the same native tick is held for the next boundary;
    # it cannot overwrite the action twice inside one Python loop.
    assert arbiter.offer(
        _frame(
            obs=3,
            token=MotorToken.FIRE,
            received_at=1.13,
            game_tick=0,
        ),
        captured_at=1.0,
        now=1.13,
    ).accepted
    same_tick = arbiter.take_tick(game_tick=0, now=1.14)
    assert same_tick is not None
    assert same_tick.frame.obs == 2
    assert not same_tick.committed

    next_tick = arbiter.take_tick(game_tick=1, now=1.15)
    assert next_tick is not None
    assert next_tick.frame.obs == 3
    assert next_tick.committed
    assert next_tick.superseded_before_commit == 0
    assert next_tick.preempted is not None
    assert next_tick.preempted.obs == 2
    assert next_tick.expires_at_game_tick == 2


def test_game_tick_lease_can_flatten_every_token_to_four_native_ticks():
    arbiter = MotorTokenArbiter(
        run_id=RUN_ID,
        game_tick_lease=True,
        flat_pulse_ticks=4,
    )
    assert arbiter.offer(
        _frame(obs=1, token=MotorToken.FIRE, received_at=1.1, game_tick=0),
        captured_at=1.0,
        now=1.1,
    ).accepted

    ticks = [arbiter.take_tick(game_tick=tick, now=1.11 + tick / 35) for tick in range(5)]
    assert [tick.action for tick in ticks[:4] if tick is not None] == [Action.FIRE] * 4
    assert ticks[0].expires_at_game_tick == 4
    assert ticks[4] is None


def test_hold5_is_preempted_by_newer_fire_at_next_native_tick():
    arbiter = MotorTokenArbiter(run_id=RUN_ID, game_tick_lease=True)
    assert arbiter.offer(
        _frame(
            obs=1,
            token=MotorToken.LEFT_HOLD,
            received_at=1.10,
            game_tick=0,
        ),
        captured_at=1.0,
        now=1.10,
    ).accepted

    first_tick = arbiter.take_tick(game_tick=0, now=1.11)
    assert first_tick is not None
    assert first_tick.action is Action.LEFT
    assert first_tick.expires_at_game_tick == 5

    # A lane completing after this tick cannot mutate the already committed
    # action; it becomes the complete command for the next native boundary.
    assert arbiter.offer(
        _frame(
            obs=2,
            token=MotorToken.FIRE,
            received_at=1.12,
            game_tick=0,
        ),
        captured_at=1.05,
        now=1.12,
    ).accepted
    same_tick = arbiter.take_tick(game_tick=0, now=1.13)
    assert same_tick is not None
    assert same_tick.action is Action.LEFT
    assert not same_tick.committed

    fire_tick = arbiter.take_tick(game_tick=1, now=1.14)
    assert fire_tick is not None
    assert fire_tick.action is Action.FIRE
    assert fire_tick.preempted is not None
    assert fire_tick.preempted.token is MotorToken.LEFT_HOLD
    assert fire_tick.expires_at_game_tick == 2
    assert arbiter.take_tick(game_tick=2, now=1.15) is None


def test_game_tick_lease_requires_both_wall_and_game_age():
    by_game_tick = MotorTokenArbiter(run_id=RUN_ID, game_tick_lease=True)
    assert by_game_tick.offer(
        _frame(
            obs=1,
            token=MotorToken.FIRE,
            received_at=1.10,
            game_tick=0,
        ),
        captured_at=1.0,
        now=1.10,
    ).accepted
    assert by_game_tick.take_tick(game_tick=15, now=1.10) is None

    by_wall_time = MotorTokenArbiter(run_id=RUN_ID, game_tick_lease=True)
    assert by_wall_time.offer(
        _frame(
            obs=1,
            token=MotorToken.FIRE,
            received_at=1.39,
            game_tick=0,
        ),
        captured_at=1.0,
        now=1.39,
    ).accepted
    assert by_wall_time.take_tick(game_tick=0, now=1.50) is None
