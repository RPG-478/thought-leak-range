from __future__ import annotations

import time
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import vizdoom as vzd

from .protocol import Action


@dataclass(frozen=True, slots=True)
class Observation:
    seq: int
    captured_at: float
    target_visible: bool
    target_id: int | None
    target_name: str | None
    target_dx: float | None
    target_width: float | None
    health: int
    ammo: int
    kills: int
    hits: int
    damage: int
    game_tick: int = 0

    def prompt_text(self) -> str:
        dx = "unknown" if self.target_dx is None else f"{self.target_dx:+.3f}"
        width = (
            "unknown" if self.target_width is None else f"{self.target_width:.3f}"
        )
        name = self.target_name or "none"
        return (
            f"obs={self.seq}\n"
            f"target_visible={str(self.target_visible).lower()}\n"
            f"target_id={self.target_id if self.target_id is not None else 'none'}\n"
            f"target_name={name}\n"
            f"target_dx={dx}  # -1 is far left, 0 is crosshair, +1 is far right\n"
            f"target_screen_width={width}\n"
            f"health={self.health}\n"
            f"ammo={self.ammo}\n"
            f"kills={self.kills}\n"
            f"hits={self.hits}\n"
            f"damage={self.damage}"
        )


class PracticeRange:
    """A process-local ViZDoom body; it never emits native keyboard input."""

    def __init__(
        self,
        *,
        visible: bool = False,
        seed: int = 7,
        episode_timeout_seconds: float = 30.0,
        scenario: str = "basic",
        async_player: bool = False,
    ) -> None:
        self.game = vzd.DoomGame()
        config_path, wad_path = _ascii_scenario_paths(scenario)
        self.game.load_config(str(config_path))
        # ViZDoom 1.3.0 on Windows decodes native paths as UTF-8. The project
        # deliberately has a Japanese name, so both paths must stay ASCII here.
        self.game.set_doom_scenario_path(str(wad_path))
        self.game.set_window_visible(visible)
        self.async_player = async_player
        self.game.set_mode(
            vzd.Mode.ASYNC_PLAYER if async_player else vzd.Mode.PLAYER
        )
        self.game.set_seed(seed)
        # It is a laboratory, not an esports qualifier. Monsters still move on
        # skill 1, but the cloud brain gets time to wake up before being eaten.
        self.game.set_doom_skill(1)
        self.game.set_episode_timeout(
            max(300, int(episode_timeout_seconds * 35) + 14)
        )
        self.game.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
        self.game.set_screen_format(vzd.ScreenFormat.RGB24)
        self.game.set_labels_buffer_enabled(True)

        available_variables = set(self.game.get_available_game_variables())
        for variable in (
            vzd.GameVariable.HEALTH,
            vzd.GameVariable.AMMO2,
            vzd.GameVariable.KILLCOUNT,
            vzd.GameVariable.HITCOUNT,
            vzd.GameVariable.DAMAGECOUNT,
        ):
            if variable not in available_variables:
                self.game.add_available_game_variable(variable)

        self.game.init()
        self.game.new_episode()
        self.scenario = scenario
        self._buttons = list(self.game.get_available_buttons())
        self._button_index = {
            button: index for index, button in enumerate(self._buttons)
        }
        self.total_reward = 0.0
        self.ticks = 0
        self._episode_time_origin = int(self.game.get_episode_time())
        self._target_lock_id: int | None = None

    def close(self) -> None:
        try:
            self.game.close()
        except vzd.ViZDoomError:
            pass

    def __enter__(self) -> PracticeRange:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def finished(self) -> bool:
        return self.game.is_episode_finished()

    def observe(self, *, seq: int) -> Observation:
        state = self.game.get_state()
        game_tick = self._refresh_game_tick()
        health = int(self.game.get_game_variable(vzd.GameVariable.HEALTH))
        ammo = int(self.game.get_game_variable(vzd.GameVariable.AMMO2))
        kills = int(self.game.get_game_variable(vzd.GameVariable.KILLCOUNT))
        hits = int(self.game.get_game_variable(vzd.GameVariable.HITCOUNT))
        damage = int(self.game.get_game_variable(vzd.GameVariable.DAMAGECOUNT))
        if state is None:
            self._target_lock_id = None
            return Observation(
                seq=seq,
                captured_at=time.monotonic(),
                target_visible=False,
                target_id=None,
                target_name=None,
                target_dx=None,
                target_width=None,
                health=health,
                ammo=ammo,
                kills=kills,
                hits=hits,
                damage=damage,
                game_tick=game_tick,
            )

        frame = state.screen_buffer
        height, width = int(frame.shape[0]), int(frame.shape[1])
        candidates = [
            label
            for label in state.labels
            if _is_probable_monster(
                str(label.object_name),
                getattr(label, "object_category", None),
            )
        ]
        if not candidates:
            self._target_lock_id = None
            return Observation(
                seq=seq,
                captured_at=time.monotonic(),
                target_visible=False,
                target_id=None,
                target_name=None,
                target_dx=None,
                target_width=None,
                health=health,
                ammo=ammo,
                kills=kills,
                hits=hits,
                damage=damage,
                game_tick=game_tick,
            )

        target, self._target_lock_id = _select_locked_target(
            candidates,
            locked_target_id=self._target_lock_id,
        )
        assert target is not None
        center_x = float(target.x) + float(target.width) / 2.0
        dx = (center_x - width / 2.0) / (width / 2.0)
        return Observation(
            seq=seq,
            captured_at=time.monotonic(),
            target_visible=True,
            target_id=int(target.object_id),
            target_name=str(target.object_name),
            target_dx=max(-1.0, min(1.0, dx)),
            target_width=max(0.0, min(1.0, float(target.width) / width)),
            health=health,
            ammo=ammo,
            kills=kills,
            hits=hits,
            damage=damage,
            game_tick=game_tick,
        )

    def frame(self):
        state = self.game.get_state()
        return None if state is None else state.screen_buffer.copy()

    def step(self, action: Action, *, ticks: int = 1) -> float:
        if ticks < 1:
            raise ValueError("step ticks must be positive")
        if self.async_player and ticks != 1:
            raise ValueError("ASYNC_PLAYER step ticks must remain one")
        vector = [False] * len(self._buttons)
        button = None
        if action is Action.LEFT:
            button = _first_available(
                self._button_index,
                vzd.Button.MOVE_LEFT,
                vzd.Button.TURN_LEFT,
            )
        elif action is Action.RIGHT:
            button = _first_available(
                self._button_index,
                vzd.Button.MOVE_RIGHT,
                vzd.Button.TURN_RIGHT,
            )
        elif action is Action.FIRE:
            button = vzd.Button.ATTACK
        if button is not None and button in self._button_index:
            vector[self._button_index[button]] = True
        if self.async_player:
            # ASYNC_PLAYER keeps the native game clock moving while Python is
            # waiting on the Cloud request.  set_action changes the held body
            # command; advance_action refreshes the latest native state and
            # catches up all tics elapsed since the previous refresh.
            self.game.set_action(vector)
            before_total = float(self.game.get_total_reward())
            self.game.advance_action()
            after_total = float(self.game.get_total_reward())
            self.total_reward = after_total
            self._refresh_game_tick()
            return after_total - before_total

        reward = float(self.game.make_action(vector, ticks))
        self.total_reward += reward
        self._refresh_game_tick()
        return reward

    def _refresh_game_tick(self) -> int:
        current = max(
            0,
            int(self.game.get_episode_time()) - self._episode_time_origin,
        )
        self.ticks = max(self.ticks, current)
        return self.ticks


_MONSTER_TERMS = (
    "zombie",
    "shotgunguy",
    "marinechainsawvzd",
    "chaingunguy",
    "imp",
    "demon",
    "spectre",
    "cacodemon",
    "baron",
    "hellknight",
    "lostsoul",
    "pain",
    "revenant",
    "mancubus",
    "arachnotron",
    "archvile",
    "cyberdemon",
    "spider",
)


def _is_probable_monster(name: str, category: object | None = None) -> bool:
    category_folded = str(category or "").casefold().replace("_", "")
    if category_folded.endswith("monster"):
        return True
    folded = name.casefold().replace("_", "")
    return any(term in folded for term in _MONSTER_TERMS)


def _select_locked_target(
    candidates: list[object],
    *,
    locked_target_id: int | None,
) -> tuple[object | None, int | None]:
    """Choose one near-looking enemy without swapping targets every frame.

    Projected label area is the only distance proxy available on the normal
    observation path. Keep the current identity for as long as it remains
    visible; choose a new nearest-looking enemy only after it disappears.
    This stabilizes perception; it does not choose LEFT/RIGHT/FIRE for the model.
    """

    if not candidates:
        return None, None

    challenger = max(
        candidates,
        key=lambda label: float(getattr(label, "width"))
        * float(getattr(label, "height")),
    )
    if locked_target_id is None:
        return challenger, int(getattr(challenger, "object_id"))

    locked = next(
        (
            label
            for label in candidates
            if int(getattr(label, "object_id")) == locked_target_id
        ),
        None,
    )
    if locked is None:
        return challenger, int(getattr(challenger, "object_id"))

    return locked, locked_target_id


def _ascii_scenario_paths(scenario: str) -> tuple[Path, Path]:
    if scenario not in {"basic", "defend_the_center"}:
        raise ValueError(f"unsupported practice scenario: {scenario}")
    source = Path(vzd.scenarios_path)
    source_config = source / f"{scenario}.cfg"
    source_wad = source / f"{scenario}.wad"
    if not source_config.is_file() or not source_wad.is_file():
        raise RuntimeError(f"ViZDoom basic scenario is missing below: {source}")

    # tempfile.gettempdir() is ASCII on the Windows account used for this lab.
    # If it is not, fail explicitly instead of passing a corrupt native path.
    cache = Path(tempfile.gettempdir()) / "thought-leak-range-vizdoom"
    try:
        str(cache).encode("ascii")
    except UnicodeEncodeError as error:
        raise RuntimeError(
            "ViZDoom on Windows needs an ASCII temporary path for this project"
        ) from error
    cache.mkdir(parents=True, exist_ok=True)
    cached_config = cache / f"{scenario}.cfg"
    cached_wad = cache / f"{scenario}.wad"
    shutil.copy2(source_config, cached_config)
    shutil.copy2(source_wad, cached_wad)
    return cached_config, cached_wad


def _first_available(buttons: dict, *candidates):
    return next((button for button in candidates if button in buttons), None)
