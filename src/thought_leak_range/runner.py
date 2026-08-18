from __future__ import annotations

import asyncio
import hashlib
import json
import math
import secrets
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TextIO

from PIL import Image, ImageDraw
import vizdoom as vzd

from .arena import Observation, PracticeRange
from .openrouter import BudgetExceeded, OpenRouterReasoningClient, StreamResult
from .protocol import (
    Action,
    DirectBitParser,
    DirectShotArbiter,
    DirectShotParser,
    FireGateParser,
    LeaseArbiter,
    MotorFrameParser,
    ThoughtCommitParser,
)


@dataclass(slots=True)
class RunMetrics:
    accepted_markers: int = 0
    rejected_markers: Counter[str] = field(default_factory=Counter)
    marker_latency_ms: list[float] = field(default_factory=list)
    actions: Counter[str] = field(default_factory=Counter)
    request_errors: int = 0
    completed_requests: int = 0
    coalesced_observations: int = 0
    gate_armed_ticks: int = 0
    direct_fire_decisions: int = 0
    direct_wait_decisions: int = 0
    direct_correct_decisions: int = 0
    direct_incorrect_decisions: int = 0
    direct_shots_executed: int = 0
    direct_hits: int = 0
    direct_damage: int = 0
    budget_guard_stopped: bool = False


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    passed: bool
    marker_action: str | None
    expected_action: str
    semantically_correct: bool
    marker_latency_ms: float | None
    stream: StreamResult


class RunArtifacts:
    def __init__(self, *, base_dir: Path, run_id: str, save_thoughts: bool) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.directory = base_dir.resolve() / f"{stamp}-{run_id[:8]}"
        self.directory.mkdir(parents=True, exist_ok=False)
        self.started_at = time.monotonic()
        self.events_path = self.directory / "events.jsonl"
        self.summary_path = self.directory / "summary.json"
        self.gif_path = self.directory / "episode.gif"
        self.thoughts_path = self.directory / "thoughts.jsonl"
        self._events = self.events_path.open("w", encoding="utf-8", newline="\n")
        self._thoughts: TextIO | None = (
            self.thoughts_path.open("w", encoding="utf-8", newline="\n")
            if save_thoughts
            else None
        )

    def event(self, kind: str, **data: object) -> None:
        row = {
            "t_ms": round((time.monotonic() - self.started_at) * 1000.0, 3),
            "kind": kind,
            **data,
        }
        self._events.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self._events.flush()

    def thought(self, *, obs: int, text: str, source: str = "reasoning.text") -> None:
        if self._thoughts is None:
            return
        row = {
            "t_ms": round((time.monotonic() - self.started_at) * 1000.0, 3),
            "obs": obs,
            "source": source,
            "text": text,
        }
        self._thoughts.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._thoughts.flush()

    def write_summary(self, summary: dict[str, object]) -> None:
        self.summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def close(self) -> None:
        self._events.close()
        if self._thoughts is not None:
            self._thoughts.close()


class ReplayRecorder:
    def __init__(self, *, every_ticks: int = 4) -> None:
        self.every_ticks = every_ticks
        self.frames: list[Image.Image] = []

    def maybe_add(self, *, tick: int, frame, action: Action, obs: int) -> None:
        if frame is None or tick % self.every_ticks != 0:
            return
        if len(frame.shape) == 3 and frame.shape[0] == 3:
            frame = frame.transpose(1, 2, 0)
        image = Image.fromarray(frame).convert("RGB")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, image.width, 18), fill=(0, 0, 0))
        draw.text((4, 4), f"OBS {obs:03d}  MOTOR {action.value}", fill=(0, 255, 120))
        self.frames.append(image)

    def save(self, path: Path) -> bool:
        if not self.frames:
            return False
        self.frames[0].save(
            path,
            save_all=True,
            append_images=self.frames[1:],
            duration=114,
            loop=0,
            optimize=False,
        )
        return True


class MockReasoningPilot:
    def __init__(self, *, tap_mode: str = "marker") -> None:
        self.tap_mode = tap_mode

    async def think(
        self,
        *,
        observation: Observation,
        run_id: str,
        on_reasoning,
        on_visible,
    ) -> StreamResult:
        started = time.monotonic()
        action = _rule_action(observation)
        if self.tap_mode in {"direct-shot", "direct-bit"}:
            nonce = _direct_nonce(run_id=run_id, obs=observation.seq)
            bit = "1" if _direct_rule_action(observation) is Action.FIRE else "0"
            if self.tap_mode == "direct-bit":
                await asyncio.sleep(0.025)
                arrived = time.monotonic()
                on_visible(bit, arrived)
                finished = time.monotonic()
                return StreamResult(
                    response_id=f"mock-{observation.seq}",
                    reported_model="mock/visible-bit-stream",
                    provider="local",
                    reasoning_types=(),
                    raw_reasoning_chars=0,
                    visible_chars=1,
                    first_byte_ms=(arrived - started) * 1000.0,
                    first_reasoning_ms=None,
                    first_visible_ms=(arrived - started) * 1000.0,
                    total_ms=(finished - started) * 1000.0,
                    usage={},
                )
            header = f"!{nonce}:{bit}!"
            first_at: float | None = None
            for chunk in (header[:5], header[5:]):
                await asyncio.sleep(0.025)
                arrived = time.monotonic()
                first_at = first_at or arrived
                on_reasoning(chunk, arrived)
            on_visible(".", time.monotonic())
            finished = time.monotonic()
            return StreamResult(
                response_id=f"mock-{observation.seq}",
                reported_model="mock/reasoning-stream",
                provider="local",
                reasoning_types=("reasoning.text",),
                raw_reasoning_chars=len(header),
                visible_chars=1,
                first_byte_ms=(first_at - started) * 1000.0 if first_at else None,
                first_reasoning_ms=(first_at - started) * 1000.0 if first_at else None,
                first_visible_ms=(finished - started) * 1000.0,
                total_ms=(finished - started) * 1000.0,
                usage={},
            )
        marker = (
            f"[[ACT run={run_id} obs={observation.seq} "
            f"ttl=220 action={action.value}]]"
        )
        chunks = [
            "Maybe FIRE, but the word FIRE is not a commitment. ",
            "The sentence says do not FIRE yet. Committing now: ",
            (
                "So trigger is ARMED. "
                if observation.target_visible and observation.ammo > 0
                else "So trigger is SAFE. "
            ),
            f"So action is {action.value}. ",
            marker[:17],
            marker[17:-2],
            marker[-2:],
        ]
        first_at: float | None = None
        for chunk in chunks:
            await asyncio.sleep(0.025)
            arrived = time.monotonic()
            first_at = first_at or arrived
            on_reasoning(chunk, arrived)
        on_visible(".", time.monotonic())
        finished = time.monotonic()
        return StreamResult(
            response_id=f"mock-{observation.seq}",
            reported_model="mock/reasoning-stream",
            provider="local",
            reasoning_types=("reasoning.text",),
            raw_reasoning_chars=sum(len(chunk) for chunk in chunks),
            visible_chars=1,
            first_byte_ms=(first_at - started) * 1000.0 if first_at else None,
            first_reasoning_ms=(first_at - started) * 1000.0 if first_at else None,
            first_visible_ms=(finished - started) * 1000.0,
            total_ms=(finished - started) * 1000.0,
            usage={},
        )


class OpenRouterPilot:
    def __init__(
        self,
        client: OpenRouterReasoningClient,
        *,
        tap_mode: str = "marker",
        direct_bit_reasoning: bool = False,
    ) -> None:
        self.client = client
        self.tap_mode = tap_mode
        self.direct_bit_reasoning = direct_bit_reasoning

    async def think(
        self,
        *,
        observation: Observation,
        run_id: str,
        on_reasoning,
        on_visible,
    ) -> StreamResult:
        return await self.client.stream(
            messages=_motor_messages(
                observation=observation,
                run_id=run_id,
                tap_mode=self.tap_mode,
            ),
            on_reasoning=on_reasoning,
            on_visible=on_visible,
            # The direct protocol allows a decision on a later standalone line.
            # Stopping at the first newline made compliant model output impossible
            # whenever even one line of reasoning preceded the decision.
            # Some providers begin visible output with a newline. The parser can
            # ignore whitespace, while an API newline stop would erase the bit.
            stop=None,
            temperature=(
                0.0 if self.tap_mode in {"direct-shot", "direct-bit"} else None
            ),
            reasoning_enabled=(
                self.tap_mode != "direct-bit" or self.direct_bit_reasoning
            ),
        )


async def probe_raw_reasoning(
    *,
    pilot,
    run_id: str,
    artifacts: RunArtifacts,
    show_thoughts: bool,
    tap_mode: str,
    probe_case: str = "fire",
) -> ProbeOutcome:
    cases = {
        "fire": (True, 0.0, 10),
        "left": (True, -0.25, 10),
        "right": (True, 0.25, 10),
        "edge-fire-left": (True, -0.08, 10),
        "edge-wait-left": (True, -0.081, 10),
        "edge-fire-right": (True, 0.08, 10),
        "edge-wait-right": (True, 0.081, 10),
        "no-target": (False, None, 10),
        "no-ammo": (True, 0.0, 0),
    }
    if probe_case not in cases:
        raise ValueError(f"unknown probe case: {probe_case}")
    visible, dx, ammo = cases[probe_case]
    observation = Observation(
        seq=0,
        captured_at=time.monotonic(),
        target_visible=visible,
        target_id=0 if visible else None,
        target_name="ProbeDummy" if visible else None,
        target_dx=dx,
        target_width=0.2 if visible else None,
        health=100,
        ammo=ammo,
        kills=0,
        hits=0,
        damage=0,
    )
    parser = _make_parser(run_id=run_id, obs=0, tap_mode=tap_mode)
    frames = []

    def on_reasoning(text: str, arrived_at: float) -> None:
        artifacts.thought(obs=0, text=text)
        if show_thoughts:
            print(f"[probe thought] {text}", end="", flush=True)
        if tap_mode != "direct-bit":
            frames.extend(parser.feed(text, now=arrived_at))

    def on_visible(text: str, arrived_at: float) -> None:
        artifacts.thought(obs=0, text=text, source="visible")
        if tap_mode == "direct-bit":
            frames.extend(parser.feed(text, now=arrived_at))

    artifacts.event(
        "probe_started",
        model=getattr(pilot, "client", None) and pilot.client.model,
        tap_mode=tap_mode,
    )
    stream = await pilot.think(
        observation=observation,
        run_id=run_id,
        on_reasoning=on_reasoning,
        on_visible=on_visible,
    )
    if show_thoughts:
        print()
    expected_action = _direct_rule_action(observation)
    semantically_correct = bool(frames) and frames[0].action is expected_action
    passed = bool(frames) and (
        stream.visible_chars > 0 if tap_mode == "direct-bit" else stream.has_raw_reasoning
    ) and (semantically_correct if tap_mode in {"direct-shot", "direct-bit"} else True)
    latency = (
        (frames[0].received_at - observation.captured_at) * 1000.0
        if frames
        else None
    )
    artifacts.event(
        "probe_finished",
        passed=passed,
        marker_action=frames[0].action.value if frames else None,
        expected_action=expected_action.value,
        semantically_correct=semantically_correct,
        probe_case=probe_case,
        marker_latency_ms=latency,
        **_stream_log(stream),
    )
    return ProbeOutcome(
        passed=passed,
        marker_action=frames[0].action.value if frames else None,
        expected_action=expected_action.value,
        semantically_correct=semantically_correct,
        marker_latency_ms=latency,
        stream=stream,
    )


async def run_practice_range(
    *,
    pilot,
    run_id: str,
    artifacts: RunArtifacts,
    duration_seconds: float,
    observation_interval: float,
    lanes: int,
    request_limit: int,
    visible: bool,
    seed: int,
    show_thoughts: bool,
    tap_mode: str,
    scenario: str,
    direct_max_age_ms: int = 300,
    direct_aim_assist: bool = False,
) -> dict[str, object]:
    if duration_seconds <= 0 or observation_interval <= 0:
        raise ValueError("duration and observation interval must be positive")
    if not 1 <= lanes <= 3:
        raise ValueError("lanes must be between one and three")
    if request_limit < 0:
        raise ValueError("request limit cannot be negative")

    metrics = RunMetrics()
    direct_mode = tap_mode in {"direct-shot", "direct-bit"}
    arbiter = (
        DirectShotArbiter(run_id=run_id, maximum_age_ms=direct_max_age_ms)
        if direct_mode
        else LeaseArbiter(run_id=run_id)
    )
    recorder = ReplayRecorder()
    tasks: dict[asyncio.Task[StreamResult], int] = {}
    observations: dict[int, Observation] = {}
    launched = 0
    latest_obs = 0
    previous_action = Action.WAIT
    previous_gate: bool | None = None
    previous_target_visible: bool | None = None
    last_observation: Observation | None = None
    initialization_started = time.monotonic()
    launch_stopped = False

    artifacts.event(
        "range_started",
        duration_seconds=duration_seconds,
        observation_interval=observation_interval,
        lanes=lanes,
        request_limit=request_limit,
        visible=visible,
        tap_mode=tap_mode,
        scenario=scenario,
        direct_max_age_ms=direct_max_age_ms if direct_mode else None,
        direct_aim_assist=direct_aim_assist if direct_mode else None,
    )

    with PracticeRange(
        visible=visible,
        seed=seed,
        episode_timeout_seconds=duration_seconds + 1.0,
        scenario=scenario,
    ) as arena:
        started = time.monotonic()
        initial_combat = arena.observe(seq=0)
        next_observation_at = started
        next_tick_at = started
        artifacts.event(
            "arena_initialized",
            initialization_ms=(started - initialization_started) * 1000.0,
        )
        try:
            while not arena.finished and time.monotonic() - started < duration_seconds:
                now = time.monotonic()
                launch_stopped = _harvest_finished(
                    tasks=tasks,
                    artifacts=artifacts,
                    metrics=metrics,
                ) or launch_stopped

                live_state = (
                    arena.observe(seq=latest_obs)
                    if tap_mode in {"fire-gate", "direct-shot", "direct-bit"}
                    else None
                )
                target_edge = False
                if live_state is not None:
                    last_observation = live_state
                    if previous_target_visible is None:
                        previous_target_visible = live_state.target_visible
                        artifacts.event(
                            "target_visibility",
                            visible=live_state.target_visible,
                            target_name=live_state.target_name,
                        )
                    elif live_state.target_visible != previous_target_visible:
                        previous_target_visible = live_state.target_visible
                        target_edge = True
                        next_observation_at = now
                        artifacts.event(
                            "target_visibility",
                            visible=live_state.target_visible,
                            target_name=live_state.target_name,
                            target_dx=live_state.target_dx,
                        )

                # Consume a fresh one-shot command at this tick boundary before
                # capturing a newer cloud observation. The old ordering captured
                # first and retroactively cancelled a decision that had already
                # arrived in time for this physical tick.
                executed_direct_frame = None
                if direct_mode:
                    assert isinstance(arbiter, DirectShotArbiter)
                    executed_direct_frame = arbiter.take_fire(now=now)

                if (
                    now >= next_observation_at
                    and launched < request_limit
                    and not launch_stopped
                ):
                    waiting_without_target = (
                        tap_mode in {"fire-gate", "direct-shot", "direct-bit"}
                        and live_state is not None
                        and not live_state.target_visible
                        and not target_edge
                    )
                    if waiting_without_target:
                        # One local visibility edge can wake the cloud brain. Do
                        # not spend every request saying SAFE to an empty room.
                        next_observation_at = now + observation_interval
                    elif len(tasks) < lanes:
                        latest_obs += 1
                        observation = arena.observe(seq=latest_obs)
                        last_observation = observation
                        observations[latest_obs] = observation
                        if direct_mode:
                            assert isinstance(arbiter, DirectShotArbiter)
                            cancelled = arbiter.note_observation(latest_obs)
                            if cancelled is not None:
                                artifacts.event(
                                    "direct_shot_cancelled",
                                    obs=cancelled.obs,
                                    reason="newer_observation_captured",
                                )
                        artifacts.event("observation", **asdict(observation))
                        task = asyncio.create_task(
                            _run_thought_request(
                                pilot=pilot,
                                observation=observation,
                                run_id=run_id,
                                arbiter=arbiter,
                                artifacts=artifacts,
                                metrics=metrics,
                                show_thoughts=show_thoughts,
                                tap_mode=tap_mode,
                            )
                        )
                        tasks[task] = latest_obs
                        launched += 1
                    else:
                        metrics.coalesced_observations += 1
                        artifacts.event("observation_coalesced", reason="all_lanes_busy")
                    # Set this after capture/task creation. Native screen reads can
                    # take hundreds of ms on their first call.
                    next_observation_at = time.monotonic() + observation_interval

                if direct_mode:
                    assert isinstance(arbiter, DirectShotArbiter)
                    if executed_direct_frame is not None and live_state is not None:
                        action = Action.FIRE if live_state.ammo > 0 else Action.WAIT
                        if action is Action.WAIT:
                            artifacts.event(
                                "direct_shot_blocked",
                                obs=executed_direct_frame.obs,
                                reason="no_ammo",
                            )
                            executed_direct_frame = None
                    elif direct_aim_assist:
                        assert live_state is not None
                        action = _tracking_action(live_state)
                    else:
                        action = Action.WAIT
                elif tap_mode == "fire-gate":
                    assert isinstance(arbiter, LeaseArbiter)
                    lease_action = arbiter.current_action(now=now)
                    gate_armed = lease_action is Action.FIRE
                    if gate_armed != previous_gate:
                        artifacts.event("trigger_gate", armed=gate_armed)
                        previous_gate = gate_armed
                    if gate_armed:
                        metrics.gate_armed_ticks += 1
                    assert live_state is not None
                    action = _spinal_action(
                        observation=live_state,
                        trigger_armed=gate_armed,
                    )
                else:
                    assert isinstance(arbiter, LeaseArbiter)
                    lease_action = arbiter.current_action(now=now)
                    action = lease_action
                metrics.actions[action.value] += 1
                if action is not previous_action:
                    artifacts.event("action_changed", action=action.value)
                    previous_action = action
                recorder.maybe_add(
                    tick=arena.ticks,
                    frame=arena.frame(),
                    action=action,
                    obs=latest_obs,
                )
                step_started_at = time.monotonic()
                reward = arena.step(action)
                if executed_direct_frame is not None:
                    before = live_state
                    after = arena.observe(seq=latest_obs)
                    last_observation = after
                    source = observations[executed_direct_frame.obs]
                    hit_delta = max(0, after.hits - before.hits)
                    damage_delta = max(0, after.damage - before.damage)
                    metrics.direct_shots_executed += 1
                    artifacts.event(
                        "direct_shot_executed",
                        source_obs=executed_direct_frame.obs,
                        source_target_id=source.target_id,
                        source_target_dx=source.target_dx,
                        source_age_ms=(step_started_at - source.captured_at) * 1000.0,
                        marker_to_fire_ms=(
                            step_started_at - executed_direct_frame.received_at
                        )
                        * 1000.0,
                        current_target_visible=before.target_visible,
                        current_target_id=before.target_id,
                        current_target_dx=before.target_dx,
                        ammo_before=before.ammo,
                        ammo_after=after.ammo,
                        hits_before=before.hits,
                        hits_after=after.hits,
                        hit_delta=hit_delta,
                        damage_before=before.damage,
                        damage_after=after.damage,
                        damage_delta=damage_delta,
                        kills_before=before.kills,
                        kills_after=after.kills,
                        reward=reward,
                    )
                # basic.cfg has living_reward=-1 on every tick. Keep the JSONL
                # useful by recording only rewards beyond that heartbeat.
                if reward not in {0.0, -1.0}:
                    artifacts.event(
                        "non_living_reward",
                        value=reward,
                        total=arena.total_reward,
                    )

                next_tick_at += 1.0 / 35.0
                await asyncio.sleep(max(0.0, next_tick_at - time.monotonic()))
        finally:
            arbiter.panic_release()
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            episode_finished = arena.finished
            try:
                final_observation = arena.observe(seq=latest_obs + 1)
            except vzd.ViZDoomError:
                final_observation = last_observation
            total_reward = arena.total_reward
            ticks = arena.ticks

    if direct_mode and final_observation is not None:
        metrics.direct_hits = max(0, final_observation.hits - initial_combat.hits)
        metrics.direct_damage = max(
            0, final_observation.damage - initial_combat.damage
        )

    gif_written = recorder.save(artifacts.gif_path)
    marker_latency = metrics.marker_latency_ms
    summary: dict[str, object] = {
        "run_id": run_id,
        "tap_mode": tap_mode,
        "scenario": scenario,
        "duration_ms": round((time.monotonic() - started) * 1000.0, 3),
        "ticks": ticks,
        "episode_finished": episode_finished,
        "requests_launched": launched,
        "requests_completed": metrics.completed_requests,
        "request_errors": metrics.request_errors,
        "accepted_markers": metrics.accepted_markers,
        "rejected_markers": dict(metrics.rejected_markers),
        "marker_latency_ms": marker_latency,
        "mean_marker_latency_ms": (
            sum(marker_latency) / len(marker_latency) if marker_latency else None
        ),
        "actions_by_tick": dict(metrics.actions),
        "coalesced_observations": metrics.coalesced_observations,
        "gate_armed_ticks": metrics.gate_armed_ticks,
        "direct_fire_decisions": metrics.direct_fire_decisions,
        "direct_wait_decisions": metrics.direct_wait_decisions,
        "direct_correct_decisions": metrics.direct_correct_decisions,
        "direct_incorrect_decisions": metrics.direct_incorrect_decisions,
        "direct_shots_executed": metrics.direct_shots_executed,
        "direct_hits": metrics.direct_hits,
        "direct_damage": metrics.direct_damage,
        "budget_guard_stopped": metrics.budget_guard_stopped,
        "total_reward": total_reward,
        "final_observation": asdict(final_observation) if final_observation else None,
        "episode_gif": str(artifacts.gif_path) if gif_written else None,
    }
    artifacts.event("range_finished", **summary)
    return summary


async def _run_thought_request(
    *,
    pilot,
    observation: Observation,
    run_id: str,
    arbiter: LeaseArbiter | DirectShotArbiter,
    artifacts: RunArtifacts,
    metrics: RunMetrics,
    show_thoughts: bool,
    tap_mode: str,
) -> StreamResult:
    parser = _make_parser(
        run_id=run_id,
        obs=observation.seq,
        tap_mode=tap_mode,
    )
    direct_mode = tap_mode in {"direct-shot", "direct-bit"}

    def process_motor_text(
        text: str, arrived_at: float, *, source_channel: str
    ) -> None:
        for frame in parser.feed(text, now=arrived_at):
            expected_action = (
                _direct_rule_action(observation) if direct_mode else None
            )
            if direct_mode:
                assert isinstance(arbiter, DirectShotArbiter)
                decision = arbiter.offer(
                    frame,
                    captured_at=observation.captured_at,
                    now=arrived_at,
                )
            else:
                assert isinstance(arbiter, LeaseArbiter)
                decision = arbiter.offer(frame, now=arrived_at)
            latency = (arrived_at - observation.captured_at) * 1000.0
            if decision.accepted:
                metrics.accepted_markers += 1
                metrics.marker_latency_ms.append(latency)
                if direct_mode:
                    if frame.action is Action.FIRE:
                        metrics.direct_fire_decisions += 1
                    else:
                        metrics.direct_wait_decisions += 1
                    if frame.action is expected_action:
                        metrics.direct_correct_decisions += 1
                    else:
                        metrics.direct_incorrect_decisions += 1
                print(
                    f"\n[MOTOR] obs={frame.obs} {frame.action.value} "
                    + (
                        f"one-shot latency={latency:.1f}ms"
                        if direct_mode
                        else f"ttl={frame.ttl_ms}ms latency={latency:.1f}ms"
                    ),
                    flush=True,
                )
            else:
                metrics.rejected_markers[decision.reason] += 1
            artifacts.event(
                "motor_marker",
                obs=frame.obs,
                action=frame.action.value,
                ttl_ms=frame.ttl_ms,
                latency_ms=latency,
                accepted=decision.accepted,
                reason=decision.reason,
                source_channel=source_channel,
                one_shot=direct_mode,
                expected_action=(
                    expected_action.value if expected_action is not None else None
                ),
                semantically_correct=(
                    frame.action is expected_action
                    if expected_action is not None
                    else None
                ),
            )

    def on_reasoning(text: str, arrived_at: float) -> None:
        artifacts.thought(obs=observation.seq, text=text)
        if show_thoughts:
            print(f"[obs {observation.seq:02d}] {text}", end="", flush=True)
        if tap_mode != "direct-bit":
            process_motor_text(text, arrived_at, source_channel="reasoning.text")

    def on_visible(text: str, arrived_at: float) -> None:
        artifacts.thought(obs=observation.seq, text=text, source="visible")
        if show_thoughts and tap_mode == "direct-bit":
            print(f"[obs {observation.seq:02d} visible] {text}", end="", flush=True)
        if tap_mode == "direct-bit":
            process_motor_text(text, arrived_at, source_channel="visible")

    artifacts.event("request_started", obs=observation.seq)
    result = await pilot.think(
        observation=observation,
        run_id=run_id,
        on_reasoning=on_reasoning,
        on_visible=on_visible,
    )
    if show_thoughts:
        print()
    artifacts.event("request_finished", obs=observation.seq, **_stream_log(result))
    return result


def _harvest_finished(
    *,
    tasks: dict[asyncio.Task[StreamResult], int],
    artifacts: RunArtifacts,
    metrics: RunMetrics,
) -> bool:
    stop_launching = False
    for task, obs in list(tasks.items()):
        if not task.done():
            continue
        tasks.pop(task)
        try:
            task.result()
            metrics.completed_requests += 1
        except asyncio.CancelledError:
            artifacts.event("request_cancelled", obs=obs)
        except BudgetExceeded as error:
            metrics.budget_guard_stopped = True
            stop_launching = True
            artifacts.event(
                "request_guard_stopped",
                obs=obs,
                reason="cost_or_request_budget",
                message=str(error)[:1200],
            )
            print(f"[request guard stopped] {error}", file=sys.stderr, flush=True)
        except Exception as error:  # The body keeps all buttons safely released on failure.
            metrics.request_errors += 1
            artifacts.event(
                "request_error",
                obs=obs,
                error_type=type(error).__name__,
                message=str(error)[:1200],
            )
            print(f"[request {obs} failed] {error}", file=sys.stderr, flush=True)
    return stop_launching


def _stream_log(stream: StreamResult) -> dict[str, object]:
    return {
        "response_id": stream.response_id,
        "reported_model": stream.reported_model,
        "provider": stream.provider,
        "reasoning_types": stream.reasoning_types,
        "raw_reasoning_chars": stream.raw_reasoning_chars,
        "visible_chars": stream.visible_chars,
        "first_byte_ms": stream.first_byte_ms,
        "first_reasoning_ms": stream.first_reasoning_ms,
        "first_visible_ms": stream.first_visible_ms,
        "total_ms": stream.total_ms,
        "usage": stream.usage,
    }


def _motor_messages(
    *,
    observation: Observation,
    run_id: str,
    tap_mode: str,
) -> list[dict[str, str]]:
    if tap_mode == "direct-shot":
        nonce = _direct_nonce(run_id=run_id, obs=observation.seq)
        system = (
            "One offline FPS trigger choice. Set b=1 iff v=1, a>0, and "
            "-0.08<=x<=0.08; else b=0. In raw reasoning emit one standalone "
            "line made by concatenating !, code, :, b, ! with no spaces. Put no "
            "other text on that line. Emit it as early as possible, then stop. "
            "Final answer: ."
        )
        dx = "9" if observation.target_dx is None else f"{observation.target_dx:+.3f}"
        user = (
            f"code={nonce} v={int(observation.target_visible)} "
            f"x={dx} a={observation.ammo}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    if tap_mode == "direct-bit":
        system = (
            "Reply with exactly one ASCII digit and nothing else. Reply 1 only "
            "when v=1, a>0, and -80<=x<=80; otherwise reply 0. /no_think"
        )
        # Preserve the existing 0.001 observation precision, but avoid asking a
        # tiny model to compare signed decimal strings at the fire boundary.
        dx = _direct_bit_x(observation)
        user = (
            f"v={int(observation.target_visible)} x={dx} a={observation.ammo}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    if tap_mode == "fire-gate":
        system = """You control only the trigger authorization in an offline ViZDoom
practice room. A deterministic local spine continuously tracks the nearest moving enemy and
will fire only while your short lease is armed and the enemy is centered. You do not steer or
time individual bullets. Think briefly. If a target is visible and ammo is above zero, decide
ARMED; otherwise decide SAFE. The instant you decide, make the first complete sentence of raw
reasoning exactly "So trigger is ARMED." or "So trigger is SAFE." That sentence is the only
motor authorization. Stop immediately afterward. Final answer: one period."""
        user = "Current game observation:\n" + observation.prompt_text()
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    if tap_mode == "thought-phrase":
        system = """You control only an offline ViZDoom practice room. Your private raw
reasoning is streamed directly into a motor sniffer; the final answer does not control the
game. Think as briefly as possible and do not restate the observation or rules. Apply exactly
these rules: no target or no ammo -> WAIT; target_dx < -0.10 -> LEFT; target_dx > +0.10 ->
RIGHT; otherwise -> FIRE. The instant you decide, make the first complete sentence of your
reasoning exactly "So action is ACTION." with ACTION replaced by WAIT, LEFT, RIGHT, or FIRE.
That sentence is the physical commitment. Stop immediately afterward. Final answer: one period."""
        user = "Current game observation:\n" + observation.prompt_text()
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    system = f"""You are a motor cortex controlling only an offline ViZDoom practice room.
Your raw private reasoning is streamed to a deterministic motor parser. The parser does not
wait for your final answer. At the very beginning of reasoning, commit exactly one action by
writing one complete marker with this exact ASCII grammar:

[[ACT run={run_id} obs={observation.seq} ttl=220 action=ACTION]]

Replace ACTION with exactly one of WAIT, LEFT, RIGHT, FIRE. Do not quote, discuss, or emit an
example marker before the commitment. Never emit a second marker. Rules: if no target or no
ammo, WAIT; if target_dx < -0.10, LEFT; if target_dx > +0.10, RIGHT; otherwise FIRE. Natural
language is never executable in safe mode. Do not restate the observation or rules. If prose
appears in reasoning before the marker, its first conclusion must be the exact sentence
"So action is ACTION." Put the marker in reasoning, not only in the final answer. After the
marker, stop reasoning quickly and make the final answer a single period."""
    user = "Newest game observation:\n" + observation.prompt_text()
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _rule_action(observation: Observation) -> Action:
    if (
        not observation.target_visible
        or observation.target_dx is None
        or observation.ammo <= 0
    ):
        return Action.WAIT
    if observation.target_dx < -0.10:
        return Action.LEFT
    if observation.target_dx > 0.10:
        return Action.RIGHT
    return Action.FIRE


def _direct_rule_action(
    observation: Observation, *, fire_window: float = 0.08
) -> Action:
    if (
        observation.target_visible
        and observation.target_dx is not None
        and observation.ammo > 0
        and abs(observation.target_dx) <= fire_window
    ):
        return Action.FIRE
    return Action.WAIT


def _direct_bit_x(observation: Observation) -> int:
    """Encode dx as signed thousandths without rounding an outside point inward."""

    if observation.target_dx is None:
        return 9999
    dx = observation.target_dx
    magnitude = math.ceil(abs(dx) * 1000.0 - 1e-9)
    return -magnitude if dx < 0 else magnitude


def _direct_nonce(*, run_id: str, obs: int) -> str:
    material = f"{run_id}:{obs}:direct-shot".encode("ascii")
    return hashlib.blake2s(material, digest_size=4).hexdigest()


def make_run_id() -> str:
    return secrets.token_hex(8)


def _make_parser(*, run_id: str, obs: int, tap_mode: str):
    if tap_mode == "marker":
        return MotorFrameParser(expected_run_id=run_id, expected_obs=obs)
    if tap_mode == "thought-phrase":
        return ThoughtCommitParser(expected_run_id=run_id, expected_obs=obs)
    if tap_mode == "fire-gate":
        return FireGateParser(expected_run_id=run_id, expected_obs=obs)
    if tap_mode == "direct-shot":
        return DirectShotParser(
            expected_run_id=run_id,
            expected_obs=obs,
            expected_nonce=_direct_nonce(run_id=run_id, obs=obs),
        )
    if tap_mode == "direct-bit":
        return DirectBitParser(expected_run_id=run_id, expected_obs=obs)
    raise ValueError(f"unknown tap mode: {tap_mode}")


def _tracking_action(
    observation: Observation, *, aim_deadzone: float = 0.08
) -> Action:
    """Aim-assist movement only; this function can never pull the trigger."""

    if not observation.target_visible or observation.target_dx is None:
        return Action.RIGHT
    if observation.target_dx < -aim_deadzone:
        return Action.LEFT
    if observation.target_dx > aim_deadzone:
        return Action.RIGHT
    return Action.WAIT


def _spinal_action(
    *,
    observation: Observation,
    trigger_armed: bool,
    aim_deadzone: float = 0.08,
) -> Action:
    if not observation.target_visible or observation.target_dx is None:
        # In defend_the_center enemies may approach from behind. A blind body
        # slowly scans instead of waiting to be bitten; the LLM still owns only
        # the trigger authorization.
        return Action.RIGHT
    if observation.target_dx < -aim_deadzone:
        return Action.LEFT
    if observation.target_dx > aim_deadzone:
        return Action.RIGHT
    return Action.FIRE if trigger_armed and observation.ammo > 0 else Action.WAIT
