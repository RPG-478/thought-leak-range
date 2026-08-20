from __future__ import annotations

import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from .arena import Observation, PracticeRange
from .motor_token import MotorToken, MotorTokenArbiter, MotorTokenFrame
from .protocol import Action


@dataclass(frozen=True, slots=True)
class ClockDecision:
    """A parsed cloud decision waiting for the game thread to inspect it."""

    frame: MotorTokenFrame
    captured_at: float
    arrived_at: float


class DecisionMailbox:
    """Thread-safe FIFO for decisions; it never exposes ViZDoom to asyncio."""

    def __init__(self, *, run_id: str) -> None:
        self.run_id = run_id
        self._lock = threading.Lock()
        self._items: deque[ClockDecision] = deque()

    def submit(self, decision: ClockDecision) -> None:
        with self._lock:
            self._items.append(decision)

    def drain(self) -> list[ClockDecision]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return items


class LatestObservationMailbox:
    """Publish only the newest observation so a slow cloud side coalesces."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Observation | None = None

    def publish(self, observation: Observation) -> None:
        with self._lock:
            self._latest = observation

    def latest(self) -> Observation | None:
        with self._lock:
            return self._latest


@dataclass(slots=True)
class PlayerClockStats:
    queued_decisions: int = 0
    queued_fire_decisions: int = 0
    committed_decisions: int = 0
    committed_fire_decisions: int = 0
    superseded_before_commit: int = 0
    preemptions: int = 0
    selected: Counter[str] = field(default_factory=Counter)
    token_ticks: Counter[str] = field(default_factory=Counter)
    game_ticks: set[int] = field(default_factory=set)
    fire_game_ticks: set[int] = field(default_factory=set)
    actions: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True, slots=True)
class ClockEvent:
    kind: str
    clock_t_ms: float
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PlayerClockResult:
    initial_observation: Observation
    final_observation: Observation | None
    observations: tuple[Observation, ...]
    frame_samples: tuple[tuple[int, object, Action, int], ...]
    ticks: int
    episode_finished: bool
    total_reward: float
    initialization_ms: float
    active_wall_ms: float
    stats: PlayerClockStats
    events: tuple[ClockEvent, ...]


class PlayerClockThread:
    """Own a PLAYER ViZDoom instance and advance exactly one native tick.

    The cloud loop is deliberately absent from this class. It can submit parsed
    decisions to ``decision_mailbox`` and read the latest snapshot, but only
    this thread constructs, observes, and steps ViZDoom. A missing or late
    decision therefore becomes WAIT on the next native tick instead of leaving
    an ASYNC_PLAYER FIRE command held in the engine.
    """

    def __init__(
        self,
        *,
        decision_mailbox: DecisionMailbox,
        observation_mailbox: LatestObservationMailbox,
        duration_seconds: float,
        observation_interval: float,
        visible: bool,
        seed: int,
        scenario: str,
        motor_token_max_age_ms: int,
        tick_hz: float = 35.0,
        capture_frames: bool = False,
    ) -> None:
        if duration_seconds <= 0:
            raise ValueError("clock-thread duration must be positive")
        if observation_interval <= 0:
            raise ValueError("clock-thread observation interval must be positive")
        if tick_hz <= 0:
            raise ValueError("clock-thread tick rate must be positive")
        self.decision_mailbox = decision_mailbox
        self.observation_mailbox = observation_mailbox
        self.duration_seconds = duration_seconds
        self.observation_interval = observation_interval
        self.visible = visible
        self.seed = seed
        self.scenario = scenario
        self.motor_token_max_age_ms = motor_token_max_age_ms
        self.tick_hz = tick_hz
        # Reading a second native screen buffer for a GIF is not part of the
        # formal clock.  It can consume enough time to turn a 35 Hz body into
        # a slow-motion benchmark, so recording must be an explicit opt-in.
        self.capture_frames = capture_frames
        self._stop = threading.Event()
        self._finished = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="thought-leak-vizdoom-clock",
            daemon=True,
        )
        self._result: PlayerClockResult | None = None
        self._error: BaseException | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)
        if self._thread.is_alive():
            return
        if self._error is not None:
            raise RuntimeError("PLAYER clock thread failed") from self._error

    @property
    def result(self) -> PlayerClockResult:
        if not self._finished.is_set():
            raise RuntimeError("PLAYER clock thread has not finished")
        if self._error is not None:
            raise RuntimeError("PLAYER clock thread failed") from self._error
        if self._result is None:
            raise RuntimeError("PLAYER clock thread produced no result")
        return self._result

    def _run(self) -> None:
        initialization_started = time.monotonic()
        observations: list[Observation] = []
        frame_samples: list[tuple[int, object, Action, int]] = []
        events: list[ClockEvent] = []
        stats = PlayerClockStats()
        arbiter: MotorTokenArbiter | None = None
        initial: Observation | None = None
        final: Observation | None = None
        gameplay_started: float | None = None

        def emit(kind: str, **data: Any) -> None:
            origin = gameplay_started or initialization_started
            events.append(
                ClockEvent(
                    kind=kind,
                    clock_t_ms=(time.monotonic() - origin) * 1000.0,
                    data=data,
                )
            )

        try:
            with PracticeRange(
                visible=self.visible,
                seed=self.seed,
                episode_timeout_seconds=max(30.0, self.duration_seconds + 1.0),
                scenario=self.scenario,
                async_player=False,
            ) as arena:
                arbiter = MotorTokenArbiter(
                    run_id=self.decision_mailbox.run_id,
                    maximum_age_ms=self.motor_token_max_age_ms,
                    game_tick_lease=True,
                )
                initial = arena.observe(seq=0)
                observations.append(initial)
                self.observation_mailbox.publish(initial)
                gameplay_started = time.monotonic()
                initialization_ms = (
                    gameplay_started - initialization_started
                ) * 1000.0
                emit(
                    "gameplay_started",
                    obs=initial.seq,
                    game_tick=initial.game_tick,
                    initialization_ms=initialization_ms,
                )

                next_observation_at = gameplay_started
                next_tick_at = gameplay_started
                observation_seq = 0
                tick_period = 1.0 / self.tick_hz

                while (
                    not self._stop.is_set()
                    and not arena.finished
                    and time.monotonic() - gameplay_started < self.duration_seconds
                ):
                    now = time.monotonic()
                    wait_for_tick = next_tick_at - now
                    if wait_for_tick > 0:
                        self._stop.wait(min(wait_for_tick, 0.05))
                        continue

                    # Only this thread calls offer/take_tick. The cloud side
                    # can never mutate the arbiter while a native tick runs.
                    for pending in self.decision_mailbox.drain():
                        decision = arbiter.offer(
                            pending.frame,
                            captured_at=pending.captured_at,
                            now=now,
                            captured_game_tick=pending.frame.obs_game_tick,
                        )
                        if decision.accepted:
                            stats.queued_decisions += 1
                            if pending.frame.token is MotorToken.FIRE:
                                stats.queued_fire_decisions += 1
                            emit(
                                "motor_token_queued",
                                obs=pending.frame.obs,
                                token=pending.frame.token.name,
                                reason=decision.reason,
                                obs_game_tick=pending.frame.obs_game_tick,
                            )
                        else:
                            emit(
                                "motor_token_rejected",
                                obs=pending.frame.obs,
                                token=pending.frame.token.name,
                                reason=decision.reason,
                            )

                    execute_game_tick = arena.ticks
                    motor_tick = arbiter.take_tick(
                        now=now,
                        game_tick=execute_game_tick,
                    )
                    action = (
                        motor_tick.action if motor_tick is not None else Action.WAIT
                    )
                    stats.actions[action.value] += 1
                    if motor_tick is not None:
                        token = motor_tick.frame.token
                        stats.token_ticks[token.name] += 1
                        stats.game_ticks.add(execute_game_tick)
                        if action is Action.FIRE:
                            stats.fire_game_ticks.add(execute_game_tick)
                        if motor_tick.committed:
                            stats.committed_decisions += 1
                            stats.superseded_before_commit += (
                                motor_tick.superseded_before_commit
                            )
                            stats.selected[token.name] += 1
                            if token is MotorToken.FIRE:
                                stats.committed_fire_decisions += 1
                            emit(
                                "motor_token_committed",
                                obs=motor_tick.frame.obs,
                                token=token.name,
                                execute_game_tick=execute_game_tick,
                                superseded_before_commit=(
                                    motor_tick.superseded_before_commit
                                ),
                            )
                        if motor_tick.preempted is not None:
                            stats.preemptions += 1

                    arena.step(action)
                    if self.capture_frames and arena.ticks % 4 == 0:
                        frame = arena.frame()
                        if frame is not None:
                            frame_samples.append(
                                (arena.ticks, frame, action, observation_seq)
                            )

                    after_step = time.monotonic()
                    if (
                        after_step >= next_observation_at
                        or arena.finished
                    ):
                        observation_seq += 1
                        observation = arena.observe(seq=observation_seq)
                        observations.append(observation)
                        self.observation_mailbox.publish(observation)
                        next_observation_at = after_step + self.observation_interval

                    next_tick_at += tick_period
                    if next_tick_at < after_step - tick_period:
                        # Do not burst several PLAYER calls after scheduler
                        # jitter; each call still means one real game tick.
                        next_tick_at = after_step + tick_period

                try:
                    observation_seq += 1
                    final = arena.observe(seq=observation_seq)
                    observations.append(final)
                    self.observation_mailbox.publish(final)
                except Exception as error:
                    emit("final_observation_error", error_type=type(error).__name__)
                active_wall_ms = (time.monotonic() - gameplay_started) * 1000.0
                self._result = PlayerClockResult(
                    initial_observation=initial,
                    final_observation=final,
                    observations=tuple(observations),
                    frame_samples=tuple(frame_samples),
                    ticks=arena.ticks,
                    episode_finished=arena.finished,
                    total_reward=arena.total_reward,
                    initialization_ms=initialization_ms,
                    active_wall_ms=active_wall_ms,
                    stats=stats,
                    events=tuple(events),
                )
        except BaseException as error:
            self._error = error
        finally:
            self._finished.set()
