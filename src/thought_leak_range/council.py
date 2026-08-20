from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .protocol import Action


SPECIALISTS = (Action.WAIT, Action.LEFT, Action.RIGHT, Action.FIRE)
LAUNCH_ORDER = (Action.FIRE, Action.WAIT, Action.LEFT, Action.RIGHT)


@dataclass(frozen=True, slots=True)
class SpecialistVote:
    run_id: str
    obs: int
    specialist: Action
    claimed: bool
    received_at: float


@dataclass(frozen=True, slots=True)
class VoteDecision:
    accepted: bool
    reason: str
    vote: SpecialistVote
    selected_action: Action | None = None


@dataclass(slots=True)
class CouncilRound:
    obs: int
    captured_at: float
    votes: dict[Action, bool] = field(default_factory=dict)
    selected_action: Action | None = None
    selected_at: float | None = None


@dataclass(frozen=True, slots=True)
class ActiveCouncilAction:
    action: Action
    obs: int
    selected_at: float
    expires_at: float


class SpecialistBitParser:
    """Interpret only the first non-whitespace character from one specialist.

    The request callback binds the bit to an observation and a specialist. A
    malformed first character permanently fails closed for that response.
    """

    def __init__(
        self, *, expected_run_id: str, expected_obs: int, specialist: Action
    ) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", expected_run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if expected_obs < 0:
            raise ValueError("expected observation must be nonnegative")
        if specialist not in SPECIALISTS:
            raise ValueError("unknown motor specialist")
        self.expected_run_id = expected_run_id
        self.expected_obs = expected_obs
        self.specialist = specialist
        self._finished = False

    def feed(
        self, chunk: str, *, now: float | None = None
    ) -> list[SpecialistVote]:
        if self._finished or not chunk:
            return []
        candidate = chunk.lstrip()
        if not candidate:
            return []
        self._finished = True
        if candidate[0] not in {"0", "1"}:
            return []
        return [
            SpecialistVote(
                run_id=self.expected_run_id,
                obs=self.expected_obs,
                specialist=self.specialist,
                claimed=candidate[0] == "1",
                received_at=time.monotonic() if now is None else now,
            )
        ]


class MotorCouncilArbiter:
    """Race four request-bound claims while the Doom world keeps moving.

    The first fresh positive claim selects the round. Movement/WAIT becomes a
    short lease; FIRE is consumed exactly once. New observations may be in flight
    while the previous movement lease finishes, but late votes from an older
    observation can never replace it.
    """

    FIRE_EXECUTION_GRACE_MS = 50

    def __init__(
        self,
        *,
        run_id: str,
        movement_ttl_ms: int = 600,
        fire_max_age_ms: int = 300,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9]{6,32}", run_id):
            raise ValueError("run id must be 6-32 lowercase ASCII letters/digits")
        if not 100 <= movement_ttl_ms <= 2000:
            raise ValueError("council movement TTL must be 100-2000 ms")
        if not 50 <= fire_max_age_ms <= 1000:
            raise ValueError("council FIRE age must be 50-1000 ms")
        self.run_id = run_id
        self.movement_ttl_ms = movement_ttl_ms
        self.fire_max_age_ms = fire_max_age_ms
        self.latest_observation = -1
        self.rounds: dict[int, CouncilRound] = {}
        self._active: ActiveCouncilAction | None = None
        self._pending_fire: ActiveCouncilAction | None = None
        self._last_selected_action = Action.WAIT

    def note_observation(self, obs: int, *, captured_at: float) -> None:
        if obs <= self.latest_observation:
            raise ValueError("observation sequence must increase")
        self.latest_observation = obs
        self.rounds[obs] = CouncilRound(obs=obs, captured_at=captured_at)
        for old_obs in tuple(self.rounds):
            if old_obs < obs - 2:
                del self.rounds[old_obs]

    def offer(
        self, vote: SpecialistVote, *, now: float | None = None
    ) -> VoteDecision:
        offered_at = time.monotonic() if now is None else now
        if vote.run_id != self.run_id:
            return VoteDecision(False, "wrong_run", vote)
        if vote.obs != self.latest_observation:
            return VoteDecision(False, "not_latest_observation", vote)
        round_state = self.rounds.get(vote.obs)
        if round_state is None:
            return VoteDecision(False, "unknown_observation", vote)
        if vote.specialist in round_state.votes:
            return VoteDecision(False, "duplicate_specialist", vote)
        if vote.received_at > offered_at + 0.001:
            return VoteDecision(False, "timestamp_from_future", vote)

        age_ms = (offered_at - round_state.captured_at) * 1000.0
        maximum_age = (
            self.fire_max_age_ms
            if vote.specialist is Action.FIRE
            else self.movement_ttl_ms
        )
        if age_ms > maximum_age:
            return VoteDecision(False, "observation_expired", vote)

        round_state.votes[vote.specialist] = vote.claimed
        if not vote.claimed:
            return VoteDecision(True, "declined", vote)
        if round_state.selected_action is not None:
            if (
                vote.specialist is Action.FIRE
                and round_state.selected_action is not Action.FIRE
            ):
                round_state.selected_action = Action.FIRE
                round_state.selected_at = offered_at
                selected = ActiveCouncilAction(
                    action=Action.FIRE,
                    obs=vote.obs,
                    selected_at=offered_at,
                    expires_at=(
                        offered_at + self.FIRE_EXECUTION_GRACE_MS / 1000.0
                    ),
                )
                self._pending_fire = selected
                self._active = None
                self._last_selected_action = Action.FIRE
                return VoteDecision(
                    True,
                    "fire_preempted",
                    vote,
                    selected_action=Action.FIRE,
                )
            return VoteDecision(
                False,
                "conflicting_claim",
                vote,
                selected_action=round_state.selected_action,
            )

        round_state.selected_action = vote.specialist
        round_state.selected_at = offered_at
        expires_at = (
            offered_at + self.FIRE_EXECUTION_GRACE_MS / 1000.0
            if vote.specialist is Action.FIRE
            else round_state.captured_at + maximum_age / 1000.0
        )
        selected = ActiveCouncilAction(
            action=vote.specialist,
            obs=vote.obs,
            selected_at=offered_at,
            expires_at=expires_at,
        )
        if vote.specialist is Action.FIRE:
            self._pending_fire = selected
            self._active = None
        else:
            self._active = selected
            self._pending_fire = None
        self._last_selected_action = vote.specialist
        return VoteDecision(True, "selected", vote, selected_action=vote.specialist)

    def take_action(self, *, now: float | None = None) -> Action:
        checked_at = time.monotonic() if now is None else now
        if self._pending_fire is not None:
            pending = self._pending_fire
            self._pending_fire = None
            if checked_at <= pending.expires_at:
                return Action.FIRE
        if self._active is not None:
            if checked_at < self._active.expires_at:
                return self._active.action
            self._active = None
        return Action.WAIT

    def blackboard(self) -> str:
        previous = self.rounds.get(self.latest_observation)
        if previous is None:
            return "o=-1 p=0000 e=W"
        votes = "".join(
            str(int(previous.votes[action])) if action in previous.votes else "?"
            for action in SPECIALISTS
        )
        selected = previous.selected_action or self._last_selected_action
        initials = {
            Action.WAIT: "W",
            Action.LEFT: "L",
            Action.RIGHT: "R",
            Action.FIRE: "F",
        }
        return f"o={previous.obs} p={votes} e={initials[selected]}"

    def panic_release(self) -> None:
        self._active = None
        self._pending_fire = None
