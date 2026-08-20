from thought_leak_range.arena import Observation
from thought_leak_range.motor_token import MotorToken
from thought_leak_range.runner import _stale_direction_reason


def _observation(*, seq: int, target_id: int | None, dx: float | None) -> Observation:
    return Observation(
        seq=seq,
        captured_at=float(seq),
        target_visible=target_id is not None,
        target_id=target_id,
        target_name="MarineChainsawVzd" if target_id is not None else None,
        target_dx=dx,
        target_width=0.03 if target_id is not None else None,
        health=100,
        ammo=50,
        kills=0,
        hits=0,
        damage=0,
    )


def test_stale_right_is_rejected_after_same_target_enters_fire_window() -> None:
    source = _observation(seq=1, target_id=7, dx=0.15)
    current = _observation(seq=2, target_id=7, dx=0.04)

    assert (
        _stale_direction_reason(MotorToken.RIGHT_SHORT, source, current)
        == "entered_fire_window"
    )


def test_direction_remains_the_llms_while_target_is_still_on_source_side() -> None:
    source = _observation(seq=1, target_id=7, dx=-0.15)
    current = _observation(seq=2, target_id=7, dx=-0.10)

    assert _stale_direction_reason(MotorToken.LEFT_SHORT, source, current) is None


def test_search_turn_without_target_is_not_locally_cancelled() -> None:
    source = _observation(seq=1, target_id=None, dx=None)
    current = _observation(seq=2, target_id=7, dx=-0.40)

    assert _stale_direction_reason(MotorToken.RIGHT_LONG, source, current) is None
