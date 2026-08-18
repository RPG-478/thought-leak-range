"""Empirically check whether VAGO's public benchmark advances during inference.

This is a manual, API-free probe. It imports the upstream ``benchmark.py`` and
uses its real ``setup_game`` and ``run_benchmark`` functions. The controlled
A/B changes only the seed and episode timeout so a 0 ms vs 650 ms comparison
finishes quickly.

Example:
    .venv\\Scripts\\python.exe tests\\manual_vago_sync_probe.py \
        --vago-root ..\\..\\artifacts\\vago-upstream
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import vizdoom


def _load_upstream(vago_root: Path) -> ModuleType:
    benchmark_path = vago_root / "scripts" / "benchmark.py"
    if not benchmark_path.is_file():
        raise FileNotFoundError(f"VAGO benchmark not found: {benchmark_path}")
    spec = importlib.util.spec_from_file_location("vago_benchmark_probe", benchmark_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load: {benchmark_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _upstream_commit(vago_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(vago_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _ascii_scenario_copy() -> tuple[Path, Path]:
    """Avoid ViZDoom 1.3.0's non-ASCII native-path bug on Windows."""
    source = Path(vizdoom.scenarios_path)
    cache = Path(tempfile.gettempdir()) / "thought-leak-range-vago-probe"
    cache.mkdir(parents=True, exist_ok=True)
    config = cache / "defend_the_center.cfg"
    wad = cache / "defend_the_center.wad"
    shutil.copy2(source / config.name, config)
    shutil.copy2(source / wad.name, wad)
    return config, wad


def _snapshot(game: vizdoom.DoomGame) -> dict[str, Any]:
    state = game.get_state()
    screen = None if state is None else state.screen_buffer
    return {
        "episode_time": int(game.get_episode_time()),
        "state_number": None if state is None else int(state.number),
        "screen_sha256": (
            None
            if screen is None
            else hashlib.sha256(np.asarray(screen).tobytes()).hexdigest()
        ),
        "health": float(game.get_game_variable(vizdoom.GameVariable.HEALTH)),
        "ammo2": float(game.get_game_variable(vizdoom.GameVariable.AMMO2)),
        "killcount": float(game.get_game_variable(vizdoom.GameVariable.KILLCOUNT)),
        "finished": bool(game.is_episode_finished()),
    }


def direct_wait_probe(vago: ModuleType, config: Path) -> dict[str, Any]:
    """Use upstream setup_game and check state across wall-clock waits."""
    game = vago.setup_game(str(config), match_visual=True)
    try:
        game.new_episode()
        game.make_action([0, 0, 0, 0], 70)
        trials: list[dict[str, Any]] = []
        for wait_ms in (250, 650, 2_000):
            before = _snapshot(game)
            started = time.perf_counter()
            time.sleep(wait_ms / 1_000)
            wall_ms = (time.perf_counter() - started) * 1_000
            after = _snapshot(game)
            trials.append(
                {
                    "requested_wait_ms": wait_ms,
                    "actual_wall_ms": round(wall_ms, 3),
                    "episode_time_delta": after["episode_time"]
                    - before["episode_time"],
                    "state_number_delta": after["state_number"]
                    - before["state_number"],
                    "screen_changed": after["screen_sha256"]
                    != before["screen_sha256"],
                    "health_delta": after["health"] - before["health"],
                }
            )

        before_action = _snapshot(game)
        game.make_action([0, 0, 0, 0], 4)
        after_action = _snapshot(game)
        return {
            "mode": str(game.get_mode()),
            "wait_trials": trials,
            "explicit_make_action_4": {
                "episode_time_delta": after_action["episode_time"]
                - before_action["episode_time"],
                "state_number_delta": after_action["state_number"]
                - before_action["state_number"],
                "screen_changed": after_action["screen_sha256"]
                != before_action["screen_sha256"],
            },
        }
    finally:
        game.close()


class _FixedPolicy:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.name = f"fixed-policy-delay-{int(delay_seconds * 1_000)}ms"
        self.screen_hashes: list[str] = []
        self.depth_hashes: list[str] = []

    def get_action(self, screen: np.ndarray, depth: np.ndarray) -> tuple[str, list[int]]:
        self.screen_hashes.append(hashlib.sha256(screen.tobytes()).hexdigest())
        self.depth_hashes.append(hashlib.sha256(depth.tobytes()).hexdigest())
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return "turn_left+shoot", [1, 0, 1, 0]


def controlled_ab_probe(
    vago: ModuleType,
    config: Path,
    wad: Path,
    *,
    delay_ms: int,
) -> dict[str, Any]:
    """Run VAGO's runner with an identical policy at two wall-clock latencies."""

    def controlled_setup(
        scenario: str = "defend_the_center", match_visual: bool = False
    ) -> vizdoom.DoomGame:
        del scenario, match_visual
        game = vizdoom.DoomGame()
        game.load_config(str(config))
        game.set_doom_scenario_path(str(wad))
        game.set_screen_format(vizdoom.ScreenFormat.RGB24)
        game.set_depth_buffer_enabled(True)
        game.set_window_visible(False)
        game.set_mode(vizdoom.Mode.PLAYER)
        game.set_seed(20_260_819)
        game.set_screen_resolution(vizdoom.ScreenResolution.RES_640X480)
        game.set_render_hud(True)
        game.set_episode_timeout(70)
        game.clear_available_buttons()
        for button in (
            vizdoom.Button.ATTACK,
            vizdoom.Button.MOVE_FORWARD,
            vizdoom.Button.TURN_LEFT,
            vizdoom.Button.TURN_RIGHT,
        ):
            game.add_available_button(button)
        for variable in (
            vizdoom.GameVariable.HEALTH,
            vizdoom.GameVariable.AMMO2,
            vizdoom.GameVariable.KILLCOUNT,
        ):
            game.add_available_game_variable(variable)
        game.init()
        return game

    vago.setup_game = controlled_setup

    def run(delay_seconds: float) -> tuple[_FixedPolicy, list[dict[str, Any]], float]:
        agent = _FixedPolicy(delay_seconds)
        started = time.perf_counter()
        result = vago.run_benchmark(
            agent,
            "defend_the_center",
            episodes=1,
            frame_skip=4,
            realtime=True,
        )
        return agent, result, time.perf_counter() - started

    fast_agent, fast_result, fast_wall = run(0.0)
    slow_agent, slow_result, slow_wall = run(delay_ms / 1_000)
    result_keys = ("steps", "kills", "health_remaining", "action_counts")
    return {
        "controlled_changes": [
            "seed fixed to 20260819",
            "episode timeout shortened from 2100 to 70 tics",
        ],
        "unchanged_runner": "VAGO scripts/benchmark.py::run_benchmark",
        "realtime": True,
        "frame_skip": 4,
        "fast_wall_seconds": round(fast_wall, 3),
        "slow_wall_seconds": round(slow_wall, 3),
        "fast_result": fast_result,
        "slow_result": slow_result,
        "screen_trajectory_identical": (
            fast_agent.screen_hashes == slow_agent.screen_hashes
        ),
        "depth_trajectory_identical": (
            fast_agent.depth_hashes == slow_agent.depth_hashes
        ),
        "results_except_latency_identical": {
            key: fast_result[0][key] == slow_result[0][key]
            for key in result_keys
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vago-root", required=True, type=Path)
    parser.add_argument("--slow-ms", type=int, default=650)
    args = parser.parse_args()

    root = args.vago_root.resolve()
    vago = _load_upstream(root)
    config, wad = _ascii_scenario_copy()
    output = {
        "upstream_commit": _upstream_commit(root),
        "direct_wait_probe": direct_wait_probe(vago, config),
        "controlled_ab_probe": controlled_ab_probe(
            vago, config, wad, delay_ms=args.slow_ms
        ),
    }
    print("\n=== VAGO SYNC PROBE RESULT ===")
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
