from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from math import ceil, inf

from .protocol import Action


class MotorToken(StrEnum):
    WAIT = "0"
    LEFT_SHORT = "1"
    LEFT_LONG = "2"
    RIGHT_SHORT = "3"
    RIGHT_LONG = "4"
    FIRE = "5"
    LEFT_HOLD = "l"
    RIGHT_HOLD = "r"

    @property
    def action(self) -> Action:
        return {
            MotorToken.WAIT: Action.WAIT,
            MotorToken.LEFT_SHORT: Action.LEFT,
            MotorToken.LEFT_LONG: Action.LEFT,
            MotorToken.RIGHT_SHORT: Action.RIGHT,
            MotorToken.RIGHT_LONG: Action.RIGHT,
            MotorToken.FIRE: Action.FIRE,
            MotorToken.LEFT_HOLD: Action.LEFT,
            MotorToken.RIGHT_HOLD: Action.RIGHT,
        }[self]

    @property
    def pulse_ticks(self) -> int:
        return {
            MotorToken.WAIT: 1,
            MotorToken.LEFT_SHORT: 2,
            MotorToken.LEFT_LONG: 5,
            MotorToken.RIGHT_SHORT: 2,
            MotorToken.RIGHT_LONG: 5,
            MotorToken.FIRE: 1,
            MotorToken.LEFT_HOLD: 5,
            MotorToken.RIGHT_HOLD: 5,
        }[self]


@dataclass(frozen=True, slots=True)
class MotorTokenFrame:
    run_id: str
    obs: int
    token: MotorToken
    received_at: float
    obs_game_tick: int | None = None
    captured_at: float | None = None


@dataclass(frozen=True, slots=True)
class MotorTokenDecision:
    accepted: bool
    reason: str
    frame: MotorTokenFrame
    preempted: MotorTokenFrame | None = None


@dataclass(slots=True)
class ActivePulse:
    frame: MotorTokenFrame
    remaining_ticks: int
    expires_at: float
    expires_at_game_tick: int | None = None


@dataclass(frozen=True, slots=True)
class MotorTick:
    action: Action
    frame: MotorTokenFrame
    preempted: MotorTokenFrame | None = None
    committed: bool = False
    superseded_before_commit: int = 0
    expires_at_game_tick: int | None = None


class MotorTokenParser:
    """Parse one request-bound motor token from the first visible character."""

    def __init__(
        self,
        *,
        expected_run_id: str,
        expected_obs: int,
        expected_game_tick: int | None = None,
        allowed_tokens: frozenset[MotorToken] | None = None,
        token_aliases: Mapping[str, MotorToken] | None = None,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", expected_run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if expected_obs < 0:
            raise ValueError("expected observation must be nonnegative")
        if expected_game_tick is not None and expected_game_tick < 0:
            raise ValueError("expected game tick must be nonnegative")
        self.expected_run_id = expected_run_id
        self.expected_obs = expected_obs
        self.expected_game_tick = expected_game_tick
        self.allowed_tokens = allowed_tokens
        self.token_aliases = token_aliases
        self._finished = False

    def feed(
        self, chunk: str, *, now: float | None = None
    ) -> list[MotorTokenFrame]:
        if self._finished or not chunk:
            return []
        candidate = chunk.lstrip()
        if not candidate:
            return []
        self._finished = True
        if self.token_aliases is not None:
            token = self.token_aliases.get(candidate[0])
            if token is None:
                return []
        else:
            try:
                token = MotorToken(candidate[0])
            except ValueError:
                return []
        if self.allowed_tokens is not None and token not in self.allowed_tokens:
            return []
        return [
            MotorTokenFrame(
                run_id=self.expected_run_id,
                obs=self.expected_obs,
                token=token,
                received_at=time.monotonic() if now is None else now,
                obs_game_tick=self.expected_game_tick,
            )
        ]


class MotorTokenArbiter:
    """Execute fresh monotonic motor tokens.

    The default mode retains the original wall-clock behavior for compatibility.
    ``game_tick_lease`` is the ASYNC_PLAYER path: responses are queued when
    they arrive, one newest eligible response is committed at most once per
    game tick, and a pulse expires from the ViZDoom clock rather than Python
    loop count.
    """

    def __init__(
        self,
        *,
        run_id: str,
        maximum_age_ms: int = 400,
        ticks_per_second: int = 35,
        game_tick_lease: bool = False,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if not 50 <= maximum_age_ms <= 1000:
            raise ValueError("motor-token maximum age must be 50-1000 ms")
        if not 1 <= ticks_per_second <= 1000:
            raise ValueError("ticks per second must be positive")
        self.run_id = run_id
        self.maximum_age_ms = maximum_age_ms
        self.ticks_per_second = ticks_per_second
        self.game_tick_lease = game_tick_lease
        self.maximum_age_ticks = max(
            1, ceil(maximum_age_ms * ticks_per_second / 1000.0)
        )
        self.highest_accepted_obs = -1
        self._active: ActivePulse | None = None
        self._pending: list[MotorTokenFrame] = []
        self._last_committed_obs = -1
        self._last_taken_game_tick: int | None = None

    def offer(
        self,
        frame: MotorTokenFrame,
        *,
        captured_at: float,
        now: float | None = None,
        captured_game_tick: int | None = None,
    ) -> MotorTokenDecision:
        offered_at = time.monotonic() if now is None else now
        if frame.run_id != self.run_id:
            return MotorTokenDecision(False, "wrong_run", frame)
        if frame.obs <= self.highest_accepted_obs:
            return MotorTokenDecision(False, "stale_or_out_of_order", frame)
        if frame.received_at > offered_at + 0.001 or captured_at > offered_at + 0.001:
            return MotorTokenDecision(False, "timestamp_from_future", frame)
        if (offered_at - captured_at) * 1000.0 > self.maximum_age_ms:
            return MotorTokenDecision(False, "observation_expired", frame)

        # Keep capture metadata on the accepted frame in both compatibility
        # modes. The legacy wall-clock path still emits age diagnostics when a
        # FIRE pulse is executed, so leaving this field unset would make the
        # measurement path fail only on the real-shot branch.
        if frame.captured_at != captured_at:
            frame = replace(frame, captured_at=captured_at)

        if self.game_tick_lease:
            game_tick = (
                frame.obs_game_tick
                if frame.obs_game_tick is not None
                else captured_game_tick
            )
            if game_tick is None:
                return MotorTokenDecision(False, "missing_obs_game_tick", frame)
            if game_tick < 0:
                return MotorTokenDecision(False, "invalid_obs_game_tick", frame)
            if frame.obs_game_tick != game_tick or frame.captured_at != captured_at:
                frame = replace(
                    frame,
                    obs_game_tick=game_tick,
                    captured_at=captured_at,
                )
            self.highest_accepted_obs = frame.obs
            self._pending.append(frame)
            return MotorTokenDecision(True, "queued_for_game_tick", frame)

        preempted = self._active.frame if self._active is not None else None
        self.highest_accepted_obs = frame.obs
        pulse_seconds = (frame.token.pulse_ticks + 1) / self.ticks_per_second
        self._active = ActivePulse(
            frame=frame,
            remaining_ticks=frame.token.pulse_ticks,
            expires_at=offered_at + pulse_seconds,
        )
        return MotorTokenDecision(True, "fresh_monotonic", frame, preempted)

    def take_tick(
        self,
        *,
        now: float | None = None,
        game_tick: int | None = None,
    ) -> MotorTick | None:
        if self.game_tick_lease:
            if game_tick is None:
                raise ValueError("game_tick is required for game-tick lease")
            return self._take_game_tick(game_tick=game_tick, now=now)

        checked_at = time.monotonic() if now is None else now
        active = self._active
        if active is None:
            return None
        if checked_at > active.expires_at or active.remaining_ticks <= 0:
            self._active = None
            return None
        active.remaining_ticks -= 1
        tick = MotorTick(action=active.frame.token.action, frame=active.frame)
        if active.remaining_ticks <= 0:
            self._active = None
        return tick

    def _take_game_tick(
        self, *, game_tick: int, now: float | None
    ) -> MotorTick | None:
        if game_tick < 0:
            raise ValueError("game_tick must be nonnegative")
        checked_at = time.monotonic() if now is None else now

        # The Python loop may revisit one native tick. It may keep the held
        # action, but it cannot commit a second response at that same tick.
        if self._last_taken_game_tick == game_tick:
            return self._active_for_game_tick(game_tick)
        self._last_taken_game_tick = game_tick

        active = self._active
        if (
            active is not None
            and active.expires_at_game_tick is not None
            and game_tick >= active.expires_at_game_tick
        ):
            self._active = None
            active = None

        eligible: list[MotorTokenFrame] = []
        future: list[MotorTokenFrame] = []
        for frame in self._pending:
            if frame.obs <= self._last_committed_obs:
                continue
            if frame.obs_game_tick is None or frame.captured_at is None:
                continue
            tick_age = game_tick - frame.obs_game_tick
            if tick_age < 0:
                future.append(frame)
                continue
            if tick_age > self.maximum_age_ticks:
                continue
            if (checked_at - frame.captured_at) * 1000.0 > self.maximum_age_ms:
                continue
            eligible.append(frame)
        self._pending = future

        if eligible:
            selected = max(eligible, key=lambda item: item.obs)
            preempted = active.frame if active is not None else None
            self._last_committed_obs = selected.obs
            self._active = ActivePulse(
                frame=selected,
                remaining_ticks=selected.token.pulse_ticks,
                expires_at=inf,
                expires_at_game_tick=game_tick + selected.token.pulse_ticks,
            )
            return MotorTick(
                action=selected.token.action,
                frame=selected,
                preempted=preempted,
                committed=True,
                superseded_before_commit=len(eligible) - 1,
                expires_at_game_tick=game_tick + selected.token.pulse_ticks,
            )

        return self._active_for_game_tick(game_tick)

    def _active_for_game_tick(self, game_tick: int) -> MotorTick | None:
        active = self._active
        if active is None:
            return None
        if (
            active.expires_at_game_tick is not None
            and game_tick >= active.expires_at_game_tick
        ):
            self._active = None
            return None
        return MotorTick(
            action=active.frame.token.action,
            frame=active.frame,
            expires_at_game_tick=active.expires_at_game_tick,
        )

    def panic_release(self) -> None:
        self._active = None
        self._pending.clear()
