from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import StrEnum


class Action(StrEnum):
    WAIT = "WAIT"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FIRE = "FIRE"


@dataclass(frozen=True, slots=True)
class ActionFrame:
    run_id: str
    obs: int
    ttl_ms: int
    action: Action
    received_at: float


@dataclass(frozen=True, slots=True)
class LeaseDecision:
    accepted: bool
    reason: str
    frame: ActionFrame


@dataclass(frozen=True, slots=True)
class ActiveLease:
    frame: ActionFrame
    expires_at: float


class MotorFrameParser:
    """Parse only complete, request-bound motor markers from arbitrary chunks."""

    _MARKER = re.compile(
        r"\[\[ACT run=(?P<run>[a-z0-9]{6,32}) "
        r"obs=(?P<obs>\d{1,9}) ttl=(?P<ttl>\d{1,4}) "
        r"action=(?P<action>WAIT|LEFT|RIGHT|FIRE)\]\]"
    )

    def __init__(
        self,
        *,
        expected_run_id: str,
        expected_obs: int,
        min_ttl_ms: int = 40,
        max_ttl_ms: int = 500,
        max_buffer_chars: int = 4096,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", expected_run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if expected_obs < 0:
            raise ValueError("expected observation must be nonnegative")
        if not 0 < min_ttl_ms <= max_ttl_ms:
            raise ValueError("invalid TTL bounds")
        self.expected_run_id = expected_run_id
        self.expected_obs = expected_obs
        self.min_ttl_ms = min_ttl_ms
        self.max_ttl_ms = max_ttl_ms
        self.max_buffer_chars = max_buffer_chars
        self._buffer = ""
        self._emitted = False

    def feed(self, chunk: str, *, now: float | None = None) -> list[ActionFrame]:
        if self._emitted or not chunk:
            return []
        self._buffer += chunk
        received_at = time.monotonic() if now is None else now

        for match in self._MARKER.finditer(self._buffer):
            run_id = match.group("run")
            obs = int(match.group("obs"))
            ttl_ms = int(match.group("ttl"))
            if run_id != self.expected_run_id or obs != self.expected_obs:
                continue
            if not self.min_ttl_ms <= ttl_ms <= self.max_ttl_ms:
                continue
            self._emitted = True
            self._buffer = ""
            return [
                ActionFrame(
                    run_id=run_id,
                    obs=obs,
                    ttl_ms=ttl_ms,
                    action=Action(match.group("action")),
                    received_at=received_at,
                )
            ]

        if len(self._buffer) > self.max_buffer_chars:
            self._buffer = self._buffer[-self.max_buffer_chars :]
        return []


class ThoughtCommitParser:
    """Experimental V0 tap: turn a narrow natural-language commitment into action.

    Unlike ``MotorFrameParser`` this is deliberately not a general safety boundary.
    It exists only to test the original "thinking words are muscles" idea inside the
    offline practice room.
    """

    _COMMIT = re.compile(
        r"(?:So|Therefore),? action is (?P<action>WAIT|LEFT|RIGHT|FIRE)\b"
    )

    def __init__(
        self,
        *,
        expected_run_id: str,
        expected_obs: int,
        ttl_ms: int = 400,
        max_buffer_chars: int = 4096,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", expected_run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if expected_obs < 0:
            raise ValueError("expected observation must be nonnegative")
        if not 40 <= ttl_ms <= 500:
            raise ValueError("thought phrase TTL must be between 40 and 500 ms")
        self.expected_run_id = expected_run_id
        self.expected_obs = expected_obs
        self.ttl_ms = ttl_ms
        self.max_buffer_chars = max_buffer_chars
        self._buffer = ""
        self._emitted = False

    def feed(self, chunk: str, *, now: float | None = None) -> list[ActionFrame]:
        if self._emitted or not chunk:
            return []
        self._buffer += chunk
        match = self._COMMIT.search(self._buffer)
        if match is not None:
            self._emitted = True
            received_at = time.monotonic() if now is None else now
            self._buffer = ""
            return [
                ActionFrame(
                    run_id=self.expected_run_id,
                    obs=self.expected_obs,
                    ttl_ms=self.ttl_ms,
                    action=Action(match.group("action")),
                    received_at=received_at,
                )
            ]
        if len(self._buffer) > self.max_buffer_chars:
            self._buffer = self._buffer[-self.max_buffer_chars :]
        return []


class FireGateParser:
    """Turn a raw-reasoning ARMED/SAFE decision into a short fire lease."""

    _COMMIT = re.compile(
        r"(?:So|Therefore),? trigger is (?P<decision>ARMED|SAFE)\b"
    )

    def __init__(
        self,
        *,
        expected_run_id: str,
        expected_obs: int,
        armed_ttl_ms: int = 3000,
        safe_ttl_ms: int = 1000,
        max_buffer_chars: int = 4096,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", expected_run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if expected_obs < 0:
            raise ValueError("expected observation must be nonnegative")
        if not 100 <= armed_ttl_ms <= 5000:
            raise ValueError("armed TTL must be between 100 and 5000 ms")
        if not 100 <= safe_ttl_ms <= 5000:
            raise ValueError("safe TTL must be between 100 and 5000 ms")
        self.expected_run_id = expected_run_id
        self.expected_obs = expected_obs
        self.armed_ttl_ms = armed_ttl_ms
        self.safe_ttl_ms = safe_ttl_ms
        self.max_buffer_chars = max_buffer_chars
        self._buffer = ""
        self._emitted = False

    def feed(self, chunk: str, *, now: float | None = None) -> list[ActionFrame]:
        if self._emitted or not chunk:
            return []
        self._buffer += chunk
        match = self._COMMIT.search(self._buffer)
        if match is not None:
            self._emitted = True
            received_at = time.monotonic() if now is None else now
            armed = match.group("decision") == "ARMED"
            self._buffer = ""
            return [
                ActionFrame(
                    run_id=self.expected_run_id,
                    obs=self.expected_obs,
                    ttl_ms=self.armed_ttl_ms if armed else self.safe_ttl_ms,
                    action=Action.FIRE if armed else Action.WAIT,
                    received_at=received_at,
                )
            ]
        if len(self._buffer) > self.max_buffer_chars:
            self._buffer = self._buffer[-self.max_buffer_chars :]
        return []


class DirectShotParser:
    """Parse a self-delimited request-bound decision header from reasoning.

    The exact executable header is deliberately absent from the prompt: the model
    receives the nonce and construction rules separately. The header must occupy
    a line by itself; quoted or inline protocol restatements cannot become actions.
    """

    def __init__(
        self,
        *,
        expected_run_id: str,
        expected_obs: int,
        expected_nonce: str,
        max_buffer_chars: int = 128,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", expected_run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if expected_obs < 0:
            raise ValueError("expected observation must be nonnegative")
        if not re.fullmatch(r"[a-f0-9]{8}", expected_nonce):
            raise ValueError("direct-shot nonce must be eight lowercase hex digits")
        self.expected_run_id = expected_run_id
        self.expected_obs = expected_obs
        self.expected_nonce = expected_nonce
        self.max_buffer_chars = max_buffer_chars
        self._buffer = ""
        self._finished = False

    def feed(self, chunk: str, *, now: float | None = None) -> list[ActionFrame]:
        if self._finished or not chunk:
            return []
        self._buffer += chunk
        headers = {
            f"!{self.expected_nonce}:0!": Action.WAIT,
            f"!{self.expected_nonce}:1!": Action.FIRE,
        }
        lines = self._buffer.splitlines()
        if self._buffer.endswith(("\n", "\r")):
            lines.append("")
        for line in lines:
            candidate = line.strip(" \t")
            action = headers.get(candidate)
            if action is None:
                continue
            self._finished = True
            self._buffer = ""
            received_at = time.monotonic() if now is None else now
            return [
                ActionFrame(
                    run_id=self.expected_run_id,
                    obs=self.expected_obs,
                    ttl_ms=0,
                    action=action,
                    received_at=received_at,
                )
            ]

        if len(self._buffer) > self.max_buffer_chars:
            self._buffer = self._buffer[-self.max_buffer_chars :]
        return []


class DirectBitParser:
    """Use the first non-whitespace visible character as a request-scoped bit.

    The HTTP stream and callback already bind the output to one observation, so
    this low-latency baseline deliberately has no textual nonce or template.
    Only an exact ``1`` fires. ``0`` waits. Any other first character permanently
    fails closed for that response instead of searching later prose for a digit.
    """

    def __init__(self, *, expected_run_id: str, expected_obs: int) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", expected_run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if expected_obs < 0:
            raise ValueError("expected observation must be nonnegative")
        self.expected_run_id = expected_run_id
        self.expected_obs = expected_obs
        self._finished = False

    def feed(self, chunk: str, *, now: float | None = None) -> list[ActionFrame]:
        if self._finished or not chunk:
            return []
        candidate = chunk.lstrip()
        if not candidate:
            return []

        self._finished = True
        first = candidate[0]
        if first not in {"0", "1"}:
            return []
        return [
            ActionFrame(
                run_id=self.expected_run_id,
                obs=self.expected_obs,
                ttl_ms=0,
                action=Action.FIRE if first == "1" else Action.WAIT,
                received_at=time.monotonic() if now is None else now,
            )
        ]


@dataclass(frozen=True, slots=True)
class PendingShot:
    frame: ActionFrame
    captured_at: float
    expires_at: float


class DirectShotArbiter:
    """Accept only a fresh decision for the latest captured observation.

    FIRE is consumed exactly once. It is never held as a lease and no current
    target/centering check is performed here; hit or miss belongs to the model's
    direct decision. WAIT is still an accepted decision but queues no action.
    """

    def __init__(self, *, run_id: str, maximum_age_ms: int = 300) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if not 50 <= maximum_age_ms <= 2000:
            raise ValueError("direct-shot maximum age must be 50-2000 ms")
        self.run_id = run_id
        self.maximum_age_ms = maximum_age_ms
        self.latest_observation = -1
        self.highest_decision = -1
        self._pending: PendingShot | None = None

    def note_observation(self, obs: int) -> ActionFrame | None:
        if obs <= self.latest_observation:
            raise ValueError("observation sequence must increase")
        self.latest_observation = obs
        cancelled = None
        if self._pending is not None and self._pending.frame.obs < obs:
            cancelled = self._pending.frame
            self._pending = None
        return cancelled

    def offer(
        self,
        frame: ActionFrame,
        *,
        captured_at: float,
        now: float | None = None,
    ) -> LeaseDecision:
        offered_at = time.monotonic() if now is None else now
        if frame.run_id != self.run_id:
            return LeaseDecision(False, "wrong_run", frame)
        if frame.obs != self.latest_observation:
            return LeaseDecision(False, "not_latest_observation", frame)
        if frame.obs <= self.highest_decision:
            return LeaseDecision(False, "stale_or_duplicate_obs", frame)
        if frame.received_at > offered_at + 0.001 or captured_at > offered_at + 0.001:
            return LeaseDecision(False, "timestamp_from_future", frame)
        age_ms = (offered_at - captured_at) * 1000.0
        if age_ms > self.maximum_age_ms:
            return LeaseDecision(False, "observation_expired", frame)

        self.highest_decision = frame.obs
        self._pending = (
            PendingShot(
                frame=frame,
                captured_at=captured_at,
                expires_at=captured_at + self.maximum_age_ms / 1000.0,
            )
            if frame.action is Action.FIRE
            else None
        )
        return LeaseDecision(True, "latest_fresh_observation", frame)

    def take_fire(self, *, now: float | None = None) -> ActionFrame | None:
        checked_at = time.monotonic() if now is None else now
        pending = self._pending
        self._pending = None
        if pending is None or checked_at > pending.expires_at:
            return None
        return pending.frame

    def panic_release(self) -> None:
        self._pending = None


class LeaseArbiter:
    """Newest observation wins; silence releases every button."""

    def __init__(self, *, run_id: str) -> None:
        self.run_id = run_id
        self._highest_obs = -1
        self._lease: ActiveLease | None = None

    @property
    def highest_obs(self) -> int:
        return self._highest_obs

    def offer(self, frame: ActionFrame, *, now: float | None = None) -> LeaseDecision:
        offered_at = time.monotonic() if now is None else now
        if frame.run_id != self.run_id:
            return LeaseDecision(False, "wrong_run", frame)
        if frame.obs <= self._highest_obs:
            return LeaseDecision(False, "stale_or_duplicate_obs", frame)
        if frame.received_at > offered_at + 0.001:
            return LeaseDecision(False, "timestamp_from_future", frame)

        self._highest_obs = frame.obs
        self._lease = ActiveLease(
            frame=frame,
            expires_at=offered_at + frame.ttl_ms / 1000.0,
        )
        return LeaseDecision(True, "newest_obs", frame)

    def current_action(self, *, now: float | None = None) -> Action:
        checked_at = time.monotonic() if now is None else now
        if self._lease is None or checked_at >= self._lease.expires_at:
            self._lease = None
            return Action.WAIT
        return self._lease.frame.action

    def panic_release(self) -> None:
        self._lease = None
