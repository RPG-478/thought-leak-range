from thought_leak_range.council import (
    MotorCouncilArbiter,
    SpecialistBitParser,
)
from thought_leak_range.protocol import Action


RUN_ID = "council123"


def _vote(*, action: Action, bit: str, obs: int = 1, now: float = 1.1):
    parser = SpecialistBitParser(
        expected_run_id=RUN_ID,
        expected_obs=obs,
        specialist=action,
    )
    return parser.feed(bit, now=now)[0]


def test_specialist_parser_uses_only_first_non_whitespace_character():
    parser = SpecialistBitParser(
        expected_run_id=RUN_ID,
        expected_obs=4,
        specialist=Action.LEFT,
    )

    assert parser.feed("  \n1 and then prose", now=2.0)[0].claimed is True
    assert parser.feed("0", now=2.1) == []


def test_malformed_first_character_fails_closed_permanently():
    parser = SpecialistBitParser(
        expected_run_id=RUN_ID,
        expected_obs=4,
        specialist=Action.FIRE,
    )

    assert parser.feed("b1", now=2.0) == []
    assert parser.feed("1", now=2.1) == []


def test_first_fresh_claim_selects_movement_lease():
    arbiter = MotorCouncilArbiter(run_id=RUN_ID, movement_ttl_ms=600)
    arbiter.note_observation(1, captured_at=1.0)

    decline = arbiter.offer(_vote(action=Action.WAIT, bit="0"), now=1.1)
    selected = arbiter.offer(_vote(action=Action.LEFT, bit="1"), now=1.1)

    assert decline.accepted and decline.reason == "declined"
    assert selected.accepted and selected.reason == "selected"
    assert arbiter.take_action(now=1.2) is Action.LEFT
    assert arbiter.take_action(now=1.59) is Action.LEFT
    assert arbiter.take_action(now=1.6) is Action.WAIT


def test_fire_is_consumed_exactly_once():
    arbiter = MotorCouncilArbiter(run_id=RUN_ID, fire_max_age_ms=300)
    arbiter.note_observation(1, captured_at=1.0)
    selected = arbiter.offer(
        _vote(action=Action.FIRE, bit="1", now=1.2), now=1.2
    )

    assert selected.accepted
    assert arbiter.take_action(now=1.21) is Action.FIRE
    assert arbiter.take_action(now=1.22) is Action.WAIT


def test_fresh_fire_gets_one_tick_execution_grace():
    arbiter = MotorCouncilArbiter(run_id=RUN_ID, fire_max_age_ms=300)
    arbiter.note_observation(1, captured_at=1.0)
    selected = arbiter.offer(
        _vote(action=Action.FIRE, bit="1", now=1.299), now=1.299
    )

    assert selected.accepted
    assert arbiter.take_action(now=1.33) is Action.FIRE


def test_late_old_vote_cannot_replace_active_movement():
    arbiter = MotorCouncilArbiter(run_id=RUN_ID)
    arbiter.note_observation(1, captured_at=1.0)
    arbiter.offer(_vote(action=Action.RIGHT, bit="1"), now=1.1)
    arbiter.note_observation(2, captured_at=1.2)

    late = arbiter.offer(
        _vote(action=Action.FIRE, bit="1", obs=1, now=1.21), now=1.21
    )

    assert not late.accepted
    assert late.reason == "not_latest_observation"
    assert arbiter.take_action(now=1.3) is Action.RIGHT


def test_second_positive_vote_is_logged_as_conflict():
    arbiter = MotorCouncilArbiter(run_id=RUN_ID)
    arbiter.note_observation(1, captured_at=1.0)
    arbiter.offer(_vote(action=Action.LEFT, bit="1"), now=1.1)

    conflict = arbiter.offer(
        _vote(action=Action.RIGHT, bit="1", now=1.11), now=1.11
    )

    assert not conflict.accepted
    assert conflict.reason == "conflicting_claim"
    assert conflict.selected_action is Action.LEFT


def test_late_fire_preempts_same_observation_movement_once():
    arbiter = MotorCouncilArbiter(run_id=RUN_ID)
    arbiter.note_observation(1, captured_at=1.0)
    arbiter.offer(_vote(action=Action.LEFT, bit="1"), now=1.1)

    fire = arbiter.offer(
        _vote(action=Action.FIRE, bit="1", now=1.12), now=1.12
    )

    assert fire.accepted
    assert fire.reason == "fire_preempted"
    assert arbiter.take_action(now=1.13) is Action.FIRE
    assert arbiter.take_action(now=1.14) is Action.WAIT
