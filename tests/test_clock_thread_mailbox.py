import asyncio
import time

from thought_leak_range.arena import Observation
from thought_leak_range.clock_thread import (
    ClockDecision,
    DecisionMailbox,
    LatestObservationMailbox,
)
from thought_leak_range.motor_token import MotorToken, MotorTokenFrame
from thought_leak_range.clock_thread import PlayerClockThread
from thought_leak_range.protocol import Action
from thought_leak_range.runner import MockReasoningPilot, RunArtifacts, run_practice_range


def _observation(seq: int) -> Observation:
    return Observation(
        seq=seq,
        captured_at=float(seq),
        target_visible=True,
        target_id=1,
        target_name="MarineChainsawVzd",
        target_dx=0.0,
        target_width=0.2,
        health=100,
        ammo=52,
        kills=0,
        hits=0,
        damage=0,
        game_tick=seq,
    )


def test_decision_mailbox_drains_fifo_without_exposing_the_game() -> None:
    mailbox = DecisionMailbox(run_id="abc123")
    first = MotorTokenFrame(
        run_id="abc123",
        obs=0,
        token=MotorToken.WAIT,
        received_at=1.0,
        obs_game_tick=0,
    )
    second = MotorTokenFrame(
        run_id="abc123",
        obs=1,
        token=MotorToken.FIRE,
        received_at=2.0,
        obs_game_tick=1,
    )
    mailbox.submit(ClockDecision(first, captured_at=0.5, arrived_at=1.0))
    mailbox.submit(ClockDecision(second, captured_at=1.5, arrived_at=2.0))

    drained = mailbox.drain()

    assert [item.frame.obs for item in drained] == [0, 1]
    assert mailbox.drain() == []


def test_observation_mailbox_coalesces_to_the_newest_snapshot() -> None:
    mailbox = LatestObservationMailbox()
    mailbox.publish(_observation(3))
    mailbox.publish(_observation(4))

    latest = mailbox.latest()

    assert latest is not None
    assert latest.seq == 4


def test_player_clock_releases_fire_on_the_next_native_tick(monkeypatch) -> None:
    class FakePracticeRange:
        def __init__(self, **kwargs) -> None:
            assert kwargs["async_player"] is False
            self.ticks = 0
            self.total_reward = 0.0
            self.actions: list[Action] = []

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        @property
        def finished(self) -> bool:
            return self.ticks >= 4

        def observe(self, *, seq: int) -> Observation:
            return _observation(seq)

        def frame(self):
            raise AssertionError("formal clock must not read an extra GIF frame")

        def step(self, action: Action) -> float:
            self.actions.append(action)
            self.ticks += 1
            return 0.0

    monkeypatch.setattr(
        "thought_leak_range.clock_thread.PracticeRange", FakePracticeRange
    )
    decisions = DecisionMailbox(run_id="abc123")
    observations = LatestObservationMailbox()
    captured_at = time.monotonic()
    decisions.submit(
        ClockDecision(
            MotorTokenFrame(
                run_id="abc123",
                obs=0,
                token=MotorToken.FIRE,
                received_at=captured_at,
                obs_game_tick=0,
            ),
            captured_at=captured_at,
            arrived_at=captured_at,
        )
    )
    clock = PlayerClockThread(
        decision_mailbox=decisions,
        observation_mailbox=observations,
        duration_seconds=1.0,
        observation_interval=0.03,
        visible=False,
        seed=7,
        scenario="basic",
        motor_token_max_age_ms=400,
    )

    clock.start()
    clock.join(timeout=2.0)
    result = clock.result

    assert result.stats.committed_decisions == 1
    assert result.stats.fire_game_ticks == {0}
    assert result.stats.actions[Action.FIRE.value] == 1
    assert result.stats.actions[Action.WAIT.value] >= 3


def test_player_clock_preempts_hold5_with_newer_lane_fire(monkeypatch) -> None:
    decisions = DecisionMailbox(run_id="abc123")
    actions: list[Action] = []

    class FakePracticeRange:
        def __init__(self, **kwargs) -> None:
            assert kwargs["async_player"] is False
            self.ticks = 0
            self.total_reward = 0.0

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        @property
        def finished(self) -> bool:
            return self.ticks >= 6

        def observe(self, *, seq: int) -> Observation:
            return _observation(seq)

        def frame(self):
            raise AssertionError("formal clock must not read an extra GIF frame")

        def step(self, action: Action) -> float:
            actions.append(action)
            if self.ticks == 0:
                arrived_at = time.monotonic()
                decisions.submit(
                    ClockDecision(
                        MotorTokenFrame(
                            run_id="abc123",
                            obs=1,
                            token=MotorToken.FIRE,
                            received_at=arrived_at,
                            obs_game_tick=1,
                        ),
                        captured_at=arrived_at,
                        arrived_at=arrived_at,
                    )
                )
            self.ticks += 1
            return 0.0

    monkeypatch.setattr(
        "thought_leak_range.clock_thread.PracticeRange", FakePracticeRange
    )
    captured_at = time.monotonic()
    decisions.submit(
        ClockDecision(
            MotorTokenFrame(
                run_id="abc123",
                obs=0,
                token=MotorToken.LEFT_HOLD,
                received_at=captured_at,
                obs_game_tick=0,
            ),
            captured_at=captured_at,
            arrived_at=captured_at,
        )
    )
    clock = PlayerClockThread(
        decision_mailbox=decisions,
        observation_mailbox=LatestObservationMailbox(),
        duration_seconds=1.0,
        observation_interval=0.03,
        visible=False,
        seed=7,
        scenario="basic",
        motor_token_max_age_ms=400,
    )

    clock.start()
    clock.join(timeout=2.0)
    result = clock.result

    assert actions[:3] == [Action.LEFT, Action.FIRE, Action.WAIT]
    assert result.stats.committed_decisions == 2
    assert result.stats.preemptions == 1
    assert result.stats.actions[Action.LEFT.value] == 1
    assert result.stats.actions[Action.FIRE.value] == 1


def test_player_clock_does_not_charge_native_init_against_active_duration(monkeypatch) -> None:
    class SlowInitPracticeRange:
        def __init__(self, **kwargs) -> None:
            time.sleep(0.15)
            self.ticks = 0
            self.total_reward = 0.0

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        @property
        def finished(self) -> bool:
            return False

        def observe(self, *, seq: int) -> Observation:
            return _observation(seq)

        def frame(self):
            raise AssertionError("formal clock must not read an extra GIF frame")

        def step(self, action: Action) -> float:
            self.ticks += 1
            return 0.0

    monkeypatch.setattr(
        "thought_leak_range.clock_thread.PracticeRange",
        SlowInitPracticeRange,
    )
    clock = PlayerClockThread(
        decision_mailbox=DecisionMailbox(run_id="abc123"),
        observation_mailbox=LatestObservationMailbox(),
        duration_seconds=0.25,
        observation_interval=0.03,
        visible=False,
        seed=7,
        scenario="basic",
        motor_token_max_age_ms=400,
    )

    clock.start()
    clock.join(timeout=2.0)
    result = clock.result

    assert result.initialization_ms >= 130.0
    assert result.active_wall_ms >= 220.0
    assert result.ticks >= 6


def test_player_clock_benchmark_skips_slow_replay_frame_reads(monkeypatch) -> None:
    class SlowFramePracticeRange:
        def __init__(self, **kwargs) -> None:
            self.ticks = 0
            self.total_reward = 0.0
            self.frame_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        @property
        def finished(self) -> bool:
            return False

        def observe(self, *, seq: int) -> Observation:
            return _observation(seq)

        def frame(self):
            self.frame_calls += 1
            time.sleep(0.03)
            return object()

        def step(self, action: Action) -> float:
            self.ticks += 1
            return 0.0

    monkeypatch.setattr(
        "thought_leak_range.clock_thread.PracticeRange",
        SlowFramePracticeRange,
    )
    clock = PlayerClockThread(
        decision_mailbox=DecisionMailbox(run_id="abc123"),
        observation_mailbox=LatestObservationMailbox(),
        duration_seconds=0.20,
        observation_interval=0.03,
        visible=False,
        seed=7,
        scenario="basic",
        motor_token_max_age_ms=400,
    )

    clock.start()
    clock.join(timeout=2.0)
    result = clock.result

    # The fake frame is deliberately slow; the formal benchmark must not call
    # it on the native tick path. Replay capture is an explicit separate mode.
    assert result.frame_samples == ()
    assert result.ticks >= 5


def test_formal_d_runner_keeps_cloud_side_out_of_the_game_thread(monkeypatch, tmp_path) -> None:
    class FakePracticeRange:
        def __init__(self, **kwargs) -> None:
            assert kwargs["async_player"] is False
            self.ticks = 0
            self.total_reward = 0.0

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        @property
        def finished(self) -> bool:
            return self.ticks >= 5

        def observe(self, *, seq: int) -> Observation:
            return _observation(seq)

        def frame(self):
            return None

        def step(self, action: Action) -> float:
            self.ticks += 1
            return 0.0

    monkeypatch.setattr(
        "thought_leak_range.clock_thread.PracticeRange", FakePracticeRange
    )
    artifacts = RunArtifacts(
        base_dir=tmp_path,
        run_id="abc123def456",
        save_thoughts=False,
    )
    try:
        summary = asyncio.run(
            run_practice_range(
                pilot=MockReasoningPilot(tap_mode="direct-motor"),
                run_id="abc123def456",
                artifacts=artifacts,
                duration_seconds=1.0,
                observation_interval=0.03,
                lanes=2,
                request_limit=3,
                visible=False,
                seed=7,
                show_thoughts=False,
                tap_mode="direct-motor",
                scenario="defend_the_center",
                world_clock="clock-thread",
                motor_body="clock-thread",
                motor_token_max_age_ms=400,
                motor_flat_pulse_ticks=4,
            )
        )
    finally:
        artifacts.close()

    assert summary["formal_condition"] == "D"
    assert summary["motor_flat_pulse_ticks"] == 4
    assert summary["clock_backend"] == "vizdoom-player-clock-thread"
    assert summary["native_action_expiry_model"] == "PLAYER_make_action_one_tick"
    assert summary["initialization_excluded_from_episode_clock"] is True
    assert summary["active_wall_ms"] >= summary["initialization_ms"]
    assert summary["simulation_duration_ms"] == round(
        summary["ticks"] / 35.0 * 1000.0, 3
    )
    assert summary["effective_tick_hz"] > 0
    assert summary["clock_rate_complete"] is True
    assert summary["frame_capture_enabled"] is False
    assert summary["comparison_valid"] is True
