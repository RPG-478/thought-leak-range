"""Run the V4 body with a deterministic policy and synthetic cloud latency.

This is deliberately a manual experiment rather than production code.  It
separates policy correctness from the asynchronous motor pipeline while using
the real ViZDoom PracticeRange and the corrected monster-label path.
"""

from __future__ import annotations

import argparse
import heapq
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass

from thought_leak_range.arena import PracticeRange
from thought_leak_range.motor_token import MotorToken
from thought_leak_range.protocol import Action
from thought_leak_range.runner import _motor_token_rule


@dataclass(order=True, slots=True)
class PendingDecision:
    due_at: float
    obs: int
    captured_at: float
    captured_tick: int
    token: MotorToken


def action_for(token: MotorToken | None) -> Action:
    return Action.WAIT if token is None else token.action


def run_probe(
    *,
    seed: int,
    duration: float,
    mode: str,
    latency_ms: float,
    observation_interval: float = 0.1,
    lanes: int = 3,
    maximum_age_ms: float = 400.0,
    async_player: bool = True,
) -> dict[str, object]:
    pending: list[PendingDecision] = []
    next_observation = 0.0
    next_tick_at = 0.0
    started = 0.0
    observation_seq = 0
    highest_accepted = -1
    active_token: MotorToken | None = None
    remaining_loop_ticks = 0
    active_until_game_tick = -1
    observations = 0
    accepted = 0
    rejected_expired = 0
    rejected_old = 0
    coalesced = 0
    preemptions = 0
    motor_ticks: Counter[str] = Counter()
    target_names: Counter[str] = Counter()
    visible_observations = 0
    ammo_decrements = 0

    with PracticeRange(
        visible=False,
        seed=seed,
        episode_timeout_seconds=duration + 1.0,
        scenario="defend_the_center",
        async_player=async_player,
    ) as arena:
        # Exclude native initialization from both the wall duration and the
        # legacy catch-up scheduler. Otherwise PLAYER spuriously replays all
        # setup time as a burst of game ticks while ASYNC_PLAYER does not.
        started = time.monotonic()
        next_tick_at = started
        first = arena.observe(seq=0)
        initial = asdict(first)
        last = first
        while not arena.finished and time.monotonic() - started < duration:
            now = time.monotonic()
            elapsed = now - started

            if mode == "oracle_live":
                observation_seq += 1
                last = arena.observe(seq=observation_seq)
                token_for_tick = _motor_token_rule(last)
                observations += 1
                accepted += 1
            else:
                completed: list[PendingDecision] = []
                while pending and pending[0].due_at <= now:
                    completed.append(heapq.heappop(pending))

                eligible: list[PendingDecision] = []
                for decision in completed:
                    age_ms = (now - decision.captured_at) * 1000.0
                    if decision.obs <= highest_accepted:
                        rejected_old += 1
                    elif age_ms > maximum_age_ms:
                        rejected_expired += 1
                    else:
                        eligible.append(decision)

                if mode == "pipeline_loop_pulse":
                    commits = eligible
                else:
                    commits = [max(eligible, key=lambda item: item.obs)] if eligible else []

                for decision in commits:
                    if active_token is not None:
                        preemptions += 1
                    highest_accepted = decision.obs
                    active_token = decision.token
                    accepted += 1
                    if mode == "pipeline_loop_pulse":
                        remaining_loop_ticks = decision.token.pulse_ticks
                    else:
                        active_until_game_tick = arena.ticks + decision.token.pulse_ticks

                if elapsed >= next_observation:
                    if len(pending) < lanes:
                        observation_seq += 1
                        last = arena.observe(seq=observation_seq)
                        token = _motor_token_rule(last)
                        heapq.heappush(
                            pending,
                            PendingDecision(
                                due_at=now + latency_ms / 1000.0,
                                obs=observation_seq,
                                captured_at=last.captured_at,
                                captured_tick=arena.ticks,
                                token=token,
                            ),
                        )
                        observations += 1
                    else:
                        coalesced += 1
                    next_observation += observation_interval

                if mode == "pipeline_loop_pulse":
                    token_for_tick = active_token if remaining_loop_ticks > 0 else None
                    if remaining_loop_ticks > 0:
                        remaining_loop_ticks -= 1
                    if remaining_loop_ticks <= 0:
                        active_token = None
                else:
                    token_for_tick = (
                        active_token if arena.ticks < active_until_game_tick else None
                    )
                    if arena.ticks >= active_until_game_tick:
                        active_token = None

            if last.target_visible:
                visible_observations += 1
            if last.target_name:
                target_names[last.target_name] += 1

            before_ammo = last.ammo
            action = action_for(token_for_tick)
            arena.step(action)
            motor_ticks[action.value] += 1
            after = arena.observe(seq=observation_seq)
            if after.ammo < before_ammo:
                ammo_decrements += before_ammo - after.ammo
            last = after

            if async_player:
                next_tick_at = time.monotonic() + 1.0 / 35.0
            else:
                # Match the legacy V4 scheduler: every simulation tick gets a
                # Python arbitration pass, and late slots are caught up.
                next_tick_at += 1.0 / 35.0
            time.sleep(max(0.0, next_tick_at - time.monotonic()))

        final = asdict(last)
        return {
            "seed": seed,
            "mode": mode,
            "clock_backend": (
                "vizdoom-async-player" if async_player else "vizdoom-player"
            ),
            "synthetic_latency_ms": latency_ms,
            "observation_interval_ms": observation_interval * 1000.0,
            "lanes": lanes,
            "wall_seconds": round(time.monotonic() - started, 3),
            "game_ticks": arena.ticks,
            "game_seconds": round(arena.ticks / 35.0, 3),
            "episode_finished": arena.finished,
            "initial": initial,
            "final": final,
            "observations": observations,
            "visible_observations": visible_observations,
            "accepted": accepted,
            "rejected_expired": rejected_expired,
            "rejected_old": rejected_old,
            "coalesced": coalesced,
            "preemptions": preemptions,
            "motor_ticks": dict(motor_ticks),
            "ammo_decrements": ammo_decrements,
            "target_names": dict(target_names),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--latency-ms", type=float, default=218.0)
    parser.add_argument("--observation-interval", type=float, default=0.1)
    parser.add_argument("--lanes", type=int, default=3)
    parser.add_argument(
        "--clock-backend",
        choices=("async-player", "player"),
        default="async-player",
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=("oracle_live", "pipeline_loop_pulse", "pipeline_tick_lease"),
    )
    args = parser.parse_args()
    modes = args.mode or [
        "oracle_live",
        "pipeline_loop_pulse",
        "pipeline_tick_lease",
    ]
    for mode in modes:
        row = run_probe(
            seed=args.seed,
            duration=args.duration,
            mode=mode,
            latency_ms=args.latency_ms,
            observation_interval=args.observation_interval,
            lanes=args.lanes,
            async_player=args.clock_backend == "async-player",
        )
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
