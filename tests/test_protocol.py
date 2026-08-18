from thought_leak_range.protocol import (
    Action,
    ActionFrame,
    DirectBitParser,
    DirectShotArbiter,
    DirectShotParser,
    FireGateParser,
    LeaseArbiter,
    MotorFrameParser,
    ThoughtCommitParser,
)


RUN_ID = "abc123def456"


def test_fragmented_marker_is_emitted_only_after_closing_brackets() -> None:
    parser = MotorFrameParser(expected_run_id=RUN_ID, expected_obs=7)
    assert parser.feed("考え中 [[ACT run=abc123", now=1.0) == []
    assert parser.feed("def456 obs=7 ttl=180 action=FI", now=1.1) == []
    frames = parser.feed("RE]] 反省", now=1.2)
    assert len(frames) == 1
    assert frames[0].action is Action.FIRE
    assert frames[0].received_at == 1.2


def test_natural_language_and_malformed_markers_never_execute() -> None:
    parser = MotorFrameParser(expected_run_id=RUN_ID, expected_obs=7)
    text = (
        "FIREすべきか、まだFIREするな。左ではなく右。 "
        "[[ACT run=abc123def456 obs=7 ttl=180 action=fire]] "
        "[[ACT run=abc123def456 obs=7 ttl=9999 action=FIRE]]"
    )
    assert parser.feed(text, now=1.0) == []


def test_wrong_request_nonce_and_observation_are_ignored() -> None:
    parser = MotorFrameParser(expected_run_id=RUN_ID, expected_obs=7)
    assert parser.feed(
        "[[ACT run=xxxxxx obs=7 ttl=180 action=FIRE]]", now=1.0
    ) == []
    assert parser.feed(
        "[[ACT run=abc123def456 obs=6 ttl=180 action=FIRE]]", now=1.1
    ) == []


def test_arbiter_rejects_old_brains_and_deadman_releases() -> None:
    arbiter = LeaseArbiter(run_id=RUN_ID)
    fresh = ActionFrame(RUN_ID, 9, 100, Action.RIGHT, 2.0)
    assert arbiter.offer(fresh, now=2.0).accepted
    assert arbiter.current_action(now=2.05) is Action.RIGHT
    assert arbiter.current_action(now=2.101) is Action.WAIT

    stale = ActionFrame(RUN_ID, 8, 100, Action.FIRE, 2.2)
    decision = arbiter.offer(stale, now=2.2)
    assert not decision.accepted
    assert decision.reason == "stale_or_duplicate_obs"
    assert arbiter.current_action(now=2.21) is Action.WAIT


def test_thought_commit_phrase_can_cross_chunks() -> None:
    parser = ThoughtCommitParser(expected_run_id=RUN_ID, expected_obs=11)
    assert parser.feed("We should inspect. So act", now=1.0) == []
    frames = parser.feed("ion is RIGHT. Done.", now=1.1)
    assert len(frames) == 1
    assert frames[0].action is Action.RIGHT
    assert frames[0].obs == 11
    assert frames[0].ttl_ms == 400


def test_thought_commit_does_not_accept_negation_or_hypothesis() -> None:
    parser = ThoughtCommitParser(expected_run_id=RUN_ID, expected_obs=11)
    assert parser.feed(
        "The action is not FIRE. If action is FIRE later, reconsider.", now=1.0
    ) == []


def test_fire_gate_arms_from_fragmented_reasoning() -> None:
    parser = FireGateParser(expected_run_id=RUN_ID, expected_obs=12)
    assert parser.feed("Target is valid. So trig", now=1.0) == []
    frames = parser.feed("ger is ARMED.", now=1.1)
    assert len(frames) == 1
    assert frames[0].action is Action.FIRE
    assert frames[0].ttl_ms == 3000


def test_fire_gate_safe_decision_revokes_permission() -> None:
    parser = FireGateParser(expected_run_id=RUN_ID, expected_obs=13)
    frames = parser.feed("Therefore, trigger is SAFE.", now=1.0)
    assert len(frames) == 1
    assert frames[0].action is Action.WAIT
    assert frames[0].ttl_ms == 1000


def test_direct_shot_header_can_cross_chunks_and_is_one_shot() -> None:
    parser = DirectShotParser(
        expected_run_id=RUN_ID,
        expected_obs=21,
        expected_nonce="a1b2c3d4",
    )
    assert parser.feed("!a1b", now=1.0) == []
    frames = parser.feed("2c3d4:1!", now=1.1)
    assert len(frames) == 1
    assert frames[0].action is Action.FIRE
    assert frames[0].obs == 21
    assert frames[0].ttl_ms == 0
    assert parser.feed("!a1b2c3d4:1!", now=1.2) == []


def test_direct_shot_never_executes_quoted_or_inline_header() -> None:
    parser = DirectShotParser(
        expected_run_id=RUN_ID,
        expected_obs=21,
        expected_nonce="a1b2c3d4",
    )
    assert parser.feed('The required text is "!a1b2c3d4:1!".\n', now=1.0) == []
    assert parser.feed("Inline !a1b2c3d4:1! is not executable.\n", now=1.1) == []
    frames = parser.feed("!a1b2c3d4:1!", now=1.2)
    assert len(frames) == 1
    assert frames[0].action is Action.FIRE


def test_direct_shot_rejects_wrong_nonce() -> None:
    parser = DirectShotParser(
        expected_run_id=RUN_ID,
        expected_obs=21,
        expected_nonce="a1b2c3d4",
    )
    assert parser.feed("!deadbeef:1!", now=1.0) == []


def test_direct_bit_uses_only_first_non_whitespace_visible_character() -> None:
    fire = DirectBitParser(expected_run_id=RUN_ID, expected_obs=22)
    assert fire.feed("  \r\n", now=1.0) == []
    frames = fire.feed("1 explanation that must not matter", now=1.1)
    assert len(frames) == 1
    assert frames[0].action is Action.FIRE
    assert frames[0].obs == 22

    wait = DirectBitParser(expected_run_id=RUN_ID, expected_obs=23)
    frames = wait.feed("0", now=1.2)
    assert len(frames) == 1
    assert frames[0].action is Action.WAIT


def test_direct_bit_never_treats_b_or_later_digits_as_fire() -> None:
    parser = DirectBitParser(expected_run_id=RUN_ID, expected_obs=24)
    assert parser.feed("b=1", now=1.0) == []
    assert parser.feed("1", now=1.1) == []

    prose = DirectBitParser(expected_run_id=RUN_ID, expected_obs=25)
    assert prose.feed("We choose 1", now=1.0) == []


def test_direct_arbiter_requires_latest_fresh_observation() -> None:
    arbiter = DirectShotArbiter(run_id=RUN_ID, maximum_age_ms=300)
    arbiter.note_observation(1)
    old = ActionFrame(RUN_ID, 1, 0, Action.FIRE, 1.20)
    arbiter.note_observation(2)
    decision = arbiter.offer(old, captured_at=1.0, now=1.20)
    assert not decision.accepted
    assert decision.reason == "not_latest_observation"

    expired = ActionFrame(RUN_ID, 2, 0, Action.FIRE, 2.31)
    decision = arbiter.offer(expired, captured_at=2.0, now=2.31)
    assert not decision.accepted
    assert decision.reason == "observation_expired"


def test_direct_fire_is_consumed_exactly_once_and_wait_never_queues() -> None:
    arbiter = DirectShotArbiter(run_id=RUN_ID, maximum_age_ms=300)
    arbiter.note_observation(1)
    fire = ActionFrame(RUN_ID, 1, 0, Action.FIRE, 1.10)
    assert arbiter.offer(fire, captured_at=1.0, now=1.10).accepted
    assert arbiter.take_fire(now=1.11) is fire
    assert arbiter.take_fire(now=1.12) is None

    arbiter.note_observation(2)
    wait = ActionFrame(RUN_ID, 2, 0, Action.WAIT, 2.10)
    assert arbiter.offer(wait, captured_at=2.0, now=2.10).accepted
    assert arbiter.take_fire(now=2.11) is None
