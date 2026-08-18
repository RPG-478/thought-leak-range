from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import StrEnum

from .protocol import Action


class MotorToken(StrEnum):
    WAIT = "0"
    LEFT_SHORT = "1"
    LEFT_LONG = "2"
    RIGHT_SHORT = "3"
    RIGHT_LONG = "4"
    FIRE = "5"

    @property
    def action(self) -> Action:
        return {
            MotorToken.WAIT: Action.WAIT,
            MotorToken.LEFT_SHORT: Action.LEFT,
            MotorToken.LEFT_LONG: Action.LEFT,
            MotorToken.RIGHT_SHORT: Action.RIGHT,
            MotorToken.RIGHT_LONG: Action.RIGHT,
            MotorToken.FIRE: Action.FIRE,
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
        }[self]


@dataclass(frozen=True, slots=True)
class MotorTokenFrame:
    run_id: str
    obs: int
    token: MotorToken
    received_at: float


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


@dataclass(frozen=True, slots=True)
class MotorTick:
    action: Action
    frame: MotorTokenFrame


class MotorTokenParser:
    """Parse one request-bound motor token from the first visible character."""

    def __init__(self, *, expected_run_id: str, expected_obs: int) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", expected_run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if expected_obs < 0:
            raise ValueError("expected observation must be nonnegative")
        self.expected_run_id = expected_run_id
        self.expected_obs = expected_obs
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
        try:
            token = MotorToken(candidate[0])
        except ValueError:
            return []
        return [
            MotorTokenFrame(
                run_id=self.expected_run_id,
                obs=self.expected_obs,
                token=token,
                received_at=time.monotonic() if now is None else now,
            )
        ]


class MotorTokenArbiter:
    """Execute fresh monotonic motor tokens without requiring latest-capture status.

    Capturing a newer observation does not retroactively cancel a still-fresh
    response. Whichever accepted response has the highest observation number
    preempts the active pulse; out-of-order older responses fail closed.
    """

    def __init__(
        self,
        *,
        run_id: str,
        maximum_age_ms: int = 400,
        ticks_per_second: int = 35,
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
        self.highest_accepted_obs = -1
        self._active: ActivePulse | None = None

    def offer(
        self,
        frame: MotorTokenFrame,
        *,
        captured_at: float,
        now: float | None = None,
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

        preempted = self._active.frame if self._active is not None else None
        self.highest_accepted_obs = frame.obs
        pulse_seconds = (frame.token.pulse_ticks + 1) / self.ticks_per_second
        self._active = ActivePulse(
            frame=frame,
            remaining_ticks=frame.token.pulse_ticks,
            expires_at=offered_at + pulse_seconds,
        )
        return MotorTokenDecision(True, "fresh_monotonic", frame, preempted)

    def take_tick(self, *, now: float | None = None) -> MotorTick | None:
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

    def panic_release(self) -> None:
        self._active = None
