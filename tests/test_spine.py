from thought_leak_range.arena import Observation
from thought_leak_range.protocol import Action
from thought_leak_range.runner import (
    _direct_bit_x,
    _direct_nonce,
    _direct_rule_action,
    _motor_messages,
    _spinal_action,
    _tracking_action,
)


def observation(*, visible: bool, dx: float | None, ammo: int = 10) -> Observation:
    return Observation(
        seq=1,
        captured_at=1.0,
        target_visible=visible,
        target_id=42 if visible else None,
        target_name="Demon" if visible else None,
        target_dx=dx,
        target_width=0.1 if visible else None,
        health=100,
        ammo=ammo,
        kills=0,
        hits=0,
        damage=0,
    )


def test_blind_spine_scans_without_firing() -> None:
    assert _spinal_action(
        observation=observation(visible=False, dx=None),
        trigger_armed=True,
    ) is Action.RIGHT


def test_spine_tracks_moving_target_without_llm_steering() -> None:
    assert _spinal_action(
        observation=observation(visible=True, dx=-0.4),
        trigger_armed=False,
    ) is Action.LEFT
    assert _spinal_action(
        observation=observation(visible=True, dx=0.4),
        trigger_armed=False,
    ) is Action.RIGHT


def test_centered_target_fires_only_while_gate_is_armed() -> None:
    centered = observation(visible=True, dx=0.02)
    assert _spinal_action(
        observation=centered,
        trigger_armed=False,
    ) is Action.WAIT
    assert _spinal_action(
        observation=centered,
        trigger_armed=True,
    ) is Action.FIRE


def test_empty_weapon_never_fires() -> None:
    assert _spinal_action(
        observation=observation(visible=True, dx=0.0, ammo=0),
        trigger_armed=True,
    ) is Action.WAIT


def test_direct_rule_chooses_one_immediate_shot_only_in_window() -> None:
    assert _direct_rule_action(observation(visible=True, dx=0.08)) is Action.FIRE
    assert _direct_rule_action(observation(visible=True, dx=0.081)) is Action.WAIT
    assert _direct_rule_action(observation(visible=False, dx=None)) is Action.WAIT


def test_direct_bit_integer_sensor_preserves_fire_boundary() -> None:
    assert _direct_bit_x(observation(visible=True, dx=0.08)) == 80
    assert _direct_bit_x(observation(visible=True, dx=0.0801)) == 81
    assert _direct_bit_x(observation(visible=True, dx=-0.08)) == -80
    assert _direct_bit_x(observation(visible=True, dx=-0.0801)) == -81


def test_tracking_assist_can_never_fire() -> None:
    assert _tracking_action(observation(visible=True, dx=0.0)) is Action.WAIT
    assert _tracking_action(observation(visible=True, dx=-0.4)) is Action.LEFT
    assert _tracking_action(observation(visible=True, dx=0.4)) is Action.RIGHT


def test_direct_prompt_never_contains_an_executable_header() -> None:
    current = observation(visible=True, dx=0.0)
    run_id = "abc123def456"
    nonce = _direct_nonce(run_id=run_id, obs=current.seq)
    messages = _motor_messages(
        observation=current,
        run_id=run_id,
        tap_mode="direct-shot",
    )
    prompt = "\n".join(message["content"] for message in messages)
    assert f"!{nonce}:0!" not in prompt
    assert f"!{nonce}:1!" not in prompt


def test_direct_bit_prompt_has_no_nonce_or_output_template() -> None:
    current = observation(visible=True, dx=0.0)
    run_id = "abc123def456"
    messages = _motor_messages(
        observation=current,
        run_id=run_id,
        tap_mode="direct-bit",
    )
    prompt = "\n".join(message["content"] for message in messages)
    assert len(messages) == 2
    assert run_id not in prompt
    assert _direct_nonce(run_id=run_id, obs=current.seq) not in prompt
    assert "!" not in prompt
