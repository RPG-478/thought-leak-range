from thought_leak_range.arena import Observation
from thought_leak_range.runner import RunMetrics, _track_observed_ammo


def _observation(ammo: int) -> Observation:
    return Observation(
        seq=0,
        captured_at=0.0,
        target_visible=False,
        target_id=None,
        target_name=None,
        target_dx=None,
        target_width=None,
        health=100,
        ammo=ammo,
        kills=0,
        hits=0,
        damage=0,
    )


def test_observed_ammo_catches_a_held_fire_drop_between_control_events() -> None:
    metrics = RunMetrics()

    _track_observed_ammo(metrics, _observation(52))
    _track_observed_ammo(metrics, _observation(52))
    _track_observed_ammo(metrics, _observation(50))

    assert metrics.observed_ammo_decrements == 2
    assert metrics.observed_ammo_increases == 0
