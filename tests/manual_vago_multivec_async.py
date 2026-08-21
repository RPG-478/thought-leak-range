r"""Run VAGO MultiVec 1.3M while ViZDoom keeps advancing at 35 Hz.

The upstream benchmark uses ``vizdoom.Mode.PLAYER`` and calls inference before
``make_action``.  This manual benchmark keeps all ViZDoom access on a dedicated
PLAYER clock thread.  The model sees a snapshot every four native tics; the
previous action expires after four tics even if the next inference is late.

The upstream repository and trained checkpoint are external inputs::

    python tests/manual_vago_multivec_async.py \
      --upstream C:/path/to/SauerkrautLM-Doom-MultiVec \
      --scenario-path C:/ascii-path/defend_the_center.cfg \
      --episodes 10 --seeds 7 8 9 10 11 12 13 14 15 16 \
      --output runs/vago-multivec-async.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing
import queue
import statistics
import sys
import threading
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FrameObservation:
    episode_seed: int
    seq: int
    game_tick: int
    captured_at: float
    screen: Any
    depth: Any


@dataclass(frozen=True, slots=True)
class ModelAction:
    episode_seed: int
    name: str
    buttons: tuple[int, int, int, int]
    obs_seq: int
    obs_game_tick: int
    inference_ms: float
    decision_latency_ms: float
    arrived_at: float


class LatestFrame:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._frame: FrameObservation | None = None
        self._closed = False

    def publish(self, frame: FrameObservation) -> None:
        with self._condition:
            self._frame = frame
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def latest(self) -> FrameObservation | None:
        with self._condition:
            return self._frame

    def wait_newer(
        self,
        seq: int,
        *,
        timeout: float = 1.0,
    ) -> FrameObservation | None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._closed and (
                self._frame is None or self._frame.seq <= seq
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if self._frame is not None and self._frame.seq > seq:
                return self._frame
            return None


class ActionQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: deque[ModelAction] = deque()

    def submit(self, action: ModelAction) -> None:
        with self._lock:
            self._items.append(action)

    def drain(self) -> list[ModelAction]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return items


@dataclass(slots=True)
class EpisodeStats:
    seed: int
    kills: int = 0
    health: float = 100.0
    native_tics: int = 0
    active_wall_seconds: float = 0.0
    effective_hz: float = 0.0
    clock_valid: bool = False
    episode_finished: bool = False
    inference_count: int = 0
    inference_mean_ms: float = 0.0
    inference_p50_ms: float = 0.0
    inference_p95_ms: float = 0.0
    decision_latency_mean_ms: float = 0.0
    decision_latency_p50_ms: float = 0.0
    decision_latency_p95_ms: float = 0.0
    action_age_mean_tics: float = 0.0
    action_age_p95_tics: float = 0.0
    observation_replacements: int = 0
    submitted_actions: int = 0
    applied_actions: int = 0
    superseded_actions: int = 0
    neutral_tics: int = 0
    action_tics: dict[str, int] = field(default_factory=dict)
    selected_actions: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile_value / 100.0
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def delay_until_latency_floor(
    captured_at: float,
    minimum_latency_ms: float,
) -> None:
    """Delay delivery until an observation is at least this old."""
    if minimum_latency_ms <= 0:
        return
    remaining = captured_at + minimum_latency_ms / 1000.0 - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def load_upstream_agent(upstream: Path, model_path: Path, *, device: str) -> Any:
    source_root = upstream / "src"
    benchmark_path = upstream / "scripts" / "benchmark.py"
    if not benchmark_path.is_file():
        raise FileNotFoundError(f"missing upstream benchmark: {benchmark_path}")
    if not model_path.is_dir():
        raise FileNotFoundError(f"missing upstream checkpoint: {model_path}")
    sys.path.insert(0, str(source_root))
    spec = importlib.util.spec_from_file_location(
        "vago_upstream_benchmark",
        benchmark_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import upstream benchmark: {benchmark_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    agent = module.MultiVecAgent(str(model_path))
    if device == "cpu":
        return agent

    import torch

    target = torch.device(device)

    def move_tensors(value: Any, device: torch.device) -> Any:
        if isinstance(value, torch.Tensor):
            return value.to(device)
        if isinstance(value, dict):
            return {
                key: move_tensors(item, device)
                for key, item in value.items()
            }
        if isinstance(value, tuple):
            return tuple(move_tensors(item, device) for item in value)
        if isinstance(value, list):
            return [move_tensors(item, device) for item in value]
        return value

    class DeviceRoundTripModel(torch.nn.Module):
        """Move model inputs to CUDA and outputs back for the upstream policy."""

        def __init__(self, wrapped: torch.nn.Module) -> None:
            super().__init__()
            self.wrapped = wrapped.to(target)

        def forward(self, *args: Any, **kwargs: Any) -> Any:
            device_args = move_tensors(args, target)
            device_kwargs = move_tensors(kwargs, target)
            result = self.wrapped(*device_args, **device_kwargs)
            return move_tensors(result, torch.device("cpu"))

    # Keep the external repository's get_action implementation authoritative.
    # This project only supplies device transport and never republishes its
    # action-fusion policy.
    agent.model = DeviceRoundTripModel(agent.model).eval()
    agent.name = f"{agent.name}-{target.type}"
    return agent


def inference_process_main(
    upstream: str,
    model_path: str,
    device: str,
    torch_threads: int | None,
    minimum_action_latency_ms: float,
    requests: Any,
    results: Any,
    ready: Any,
    busy: Any,
    errors: Any,
) -> None:
    try:
        if torch_threads is not None:
            import torch

            torch.set_num_threads(torch_threads)
        agent = load_upstream_agent(
            Path(upstream),
            Path(model_path),
            device=device,
        )
        ready.set()
        while True:
            frame = requests.get()
            if frame is None:
                return
            busy.set()
            try:
                started = time.perf_counter()
                name, buttons = agent.get_action(frame.screen, frame.depth)
                inference_ms = (time.perf_counter() - started) * 1000.0
                delay_until_latency_floor(
                    frame.captured_at,
                    minimum_action_latency_ms,
                )
                arrived_at = time.monotonic()
                results.put(
                    ModelAction(
                        episode_seed=frame.episode_seed,
                        name=name,
                        buttons=tuple(int(value) for value in buttons),
                        obs_seq=frame.seq,
                        obs_game_tick=frame.game_tick,
                        inference_ms=inference_ms,
                        decision_latency_ms=(
                            arrived_at - frame.captured_at
                        ) * 1000.0,
                        arrived_at=arrived_at,
                    )
                )
            finally:
                busy.clear()
    except BaseException as error:
        errors.put(f"{type(error).__name__}: {error}")
        ready.set()


class InferenceProcess:
    def __init__(
        self,
        *,
        upstream: Path,
        model_path: Path,
        device: str,
        torch_threads: int | None,
        minimum_action_latency_ms: float,
    ) -> None:
        context = multiprocessing.get_context("spawn")
        self._requests = context.Queue(maxsize=1)
        self._results = context.Queue()
        self._errors = context.Queue()
        self._ready = context.Event()
        self._busy = context.Event()
        self._process = context.Process(
            target=inference_process_main,
            args=(
                str(upstream),
                str(model_path),
                device,
                torch_threads,
                minimum_action_latency_ms,
                self._requests,
                self._results,
                self._ready,
                self._busy,
                self._errors,
            ),
            name="vago-multivec-inference",
            daemon=True,
        )

    def start(self, timeout: float = 180.0) -> None:
        self._process.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("VAGO inference process did not become ready")
        self.raise_if_failed()

    def raise_if_failed(self) -> None:
        try:
            error = self._errors.get_nowait()
        except queue.Empty:
            error = None
        if error is not None:
            raise RuntimeError(f"VAGO inference process failed: {error}")
        if not self._process.is_alive() and self._process.exitcode not in (None, 0):
            raise RuntimeError(
                f"VAGO inference process exited with {self._process.exitcode}"
            )

    def submit_latest(self, frame: FrameObservation) -> bool:
        replaced = False
        try:
            self._requests.put_nowait(frame)
            return replaced
        except queue.Full:
            pass
        try:
            self._requests.get_nowait()
            replaced = True
        except queue.Empty:
            pass
        try:
            self._requests.put(frame, timeout=0.05)
        except queue.Full:
            # The multiprocessing feeder may not have released its semaphore
            # yet. Dropping this snapshot is safer than blocking the clock-side
            # coordinator; the next four-tic observation will replace it.
            replaced = True
        return replaced

    def drain(self) -> list[ModelAction]:
        items: list[ModelAction] = []
        while True:
            try:
                items.append(self._results.get_nowait())
            except queue.Empty:
                return items

    def wait_idle(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while self._busy.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.raise_if_failed()

    def close(self) -> None:
        self.wait_idle()
        try:
            self._requests.put_nowait(None)
        except queue.Full:
            try:
                self._requests.get_nowait()
            except queue.Empty:
                pass
            self._requests.put_nowait(None)
        self._process.join(30.0)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(5.0)


class PlayerClockEpisode:
    def __init__(
        self,
        *,
        scenario_path: Path,
        seed: int,
        observation_tics: int,
        pulse_tics: int,
        maximum_tics: int,
        tick_hz: float,
    ) -> None:
        self.scenario_path = scenario_path
        self.seed = seed
        self.observation_tics = observation_tics
        self.pulse_tics = pulse_tics
        self.maximum_tics = maximum_tics
        self.tick_hz = tick_hz
        self.frames = LatestFrame()
        self.actions = ActionQueue()
        self.finished = threading.Event()
        self.stats = EpisodeStats(seed=seed)
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"vago-async-clock-seed-{seed}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def join(self) -> None:
        self._thread.join()
        if self._error is not None:
            raise RuntimeError("VAGO async clock failed") from self._error

    def _run(self) -> None:
        import numpy as np
        import vizdoom

        selected = Counter()
        action_tics = Counter()
        action_ages: list[float] = []
        current_name = "neutral"
        current_buttons = [0, 0, 0, 0]
        action_expires_at = 0
        last_health = 100.0
        game = vizdoom.DoomGame()
        try:
            game.load_config(str(self.scenario_path))
            game.set_seed(self.seed)
            game.set_mode(vizdoom.Mode.PLAYER)
            game.set_screen_format(vizdoom.ScreenFormat.RGB24)
            game.set_screen_resolution(vizdoom.ScreenResolution.RES_640X480)
            game.set_depth_buffer_enabled(True)
            game.set_render_hud(True)
            game.set_window_visible(False)
            game.set_episode_timeout(self.maximum_tics)
            game.clear_available_buttons()
            game.add_available_button(vizdoom.Button.ATTACK)
            game.add_available_button(vizdoom.Button.MOVE_FORWARD)
            game.add_available_button(vizdoom.Button.TURN_LEFT)
            game.add_available_button(vizdoom.Button.TURN_RIGHT)
            game.add_available_game_variable(vizdoom.GameVariable.HEALTH)
            game.add_available_game_variable(vizdoom.GameVariable.AMMO2)
            game.add_available_game_variable(vizdoom.GameVariable.KILLCOUNT)
            game.init()
            game.new_episode()

            started = time.monotonic()
            next_tick_at = started
            tick_period = 1.0 / self.tick_hz
            observation_seq = 0

            def publish_frame(game_tick: int) -> None:
                nonlocal observation_seq
                state = game.get_state()
                if state is None:
                    return
                observation_seq += 1
                screen = np.array(state.screen_buffer, copy=True)
                depth = (
                    np.array(state.depth_buffer, copy=True)
                    if state.depth_buffer is not None
                    else None
                )
                self.frames.publish(
                    FrameObservation(
                        episode_seed=self.seed,
                        seq=observation_seq,
                        game_tick=game_tick,
                        captured_at=time.monotonic(),
                        screen=screen,
                        depth=depth,
                    )
                )

            publish_frame(0)
            native_tics = 0
            while (
                native_tics < self.maximum_tics
                and not game.is_episode_finished()
            ):
                now = time.monotonic()
                remaining = next_tick_at - now
                if remaining > 0:
                    time.sleep(min(remaining, 0.01))
                    continue

                pending = self.actions.drain()
                if pending:
                    newest = pending[-1]
                    self.stats.superseded_actions += max(0, len(pending) - 1)
                    current_name = newest.name
                    current_buttons = list(newest.buttons)
                    action_expires_at = native_tics + self.pulse_tics
                    action_ages.append(float(native_tics - newest.obs_game_tick))
                    selected[current_name] += 1
                    self.stats.applied_actions += 1

                if native_tics >= action_expires_at:
                    current_name = "neutral"
                    current_buttons = [0, 0, 0, 0]

                action_tics[current_name] += 1
                if current_name == "neutral":
                    self.stats.neutral_tics += 1
                game.make_action(current_buttons, 1)
                native_tics += 1

                if not game.is_episode_finished():
                    last_health = float(
                        game.get_game_variable(vizdoom.GameVariable.HEALTH)
                    )
                    if native_tics % self.observation_tics == 0:
                        publish_frame(native_tics)

                after_step = time.monotonic()
                next_tick_at += tick_period
                if next_tick_at < after_step - tick_period:
                    next_tick_at = after_step + tick_period

            active_wall = time.monotonic() - started
            self.stats.kills = int(
                game.get_game_variable(vizdoom.GameVariable.KILLCOUNT)
            )
            self.stats.health = max(0.0, last_health)
            self.stats.native_tics = native_tics
            self.stats.active_wall_seconds = active_wall
            self.stats.effective_hz = native_tics / active_wall if active_wall else 0.0
            self.stats.clock_valid = self.stats.effective_hz >= self.tick_hz * 0.95
            self.stats.episode_finished = game.is_episode_finished()
            self.stats.action_age_mean_tics = (
                statistics.fmean(action_ages) if action_ages else 0.0
            )
            self.stats.action_age_p95_tics = percentile(action_ages, 95)
            self.stats.action_tics = dict(action_tics)
            self.stats.selected_actions = dict(selected)
        except BaseException as error:
            self._error = error
            self.stats.error = f"{type(error).__name__}: {error}"
        finally:
            try:
                game.close()
            finally:
                self.frames.close()
                self.finished.set()


def run_episode(
    inference: InferenceProcess,
    *,
    scenario_path: Path,
    seed: int,
    observation_tics: int,
    pulse_tics: int,
    maximum_tics: int,
    tick_hz: float,
) -> EpisodeStats:
    episode = PlayerClockEpisode(
        scenario_path=scenario_path,
        seed=seed,
        observation_tics=observation_tics,
        pulse_tics=pulse_tics,
        maximum_tics=maximum_tics,
        tick_hz=tick_hz,
    )
    episode.start()
    last_seq = 0
    latencies: list[float] = []
    decision_latencies: list[float] = []
    observation_replacements = 0
    submitted = 0
    try:
        while not episode.finished.is_set():
            frame = episode.frames.latest()
            if frame is not None and frame.seq > last_seq:
                if last_seq:
                    observation_replacements += max(0, frame.seq - last_seq - 1)
                last_seq = frame.seq
                if inference.submit_latest(frame):
                    observation_replacements += 1
                submitted += 1
            for action in inference.drain():
                if action.episode_seed != seed:
                    continue
                latencies.append(action.inference_ms)
                decision_latencies.append(action.decision_latency_ms)
                episode.actions.submit(action)
            inference.raise_if_failed()
            time.sleep(0.002)
    finally:
        episode.join()
        inference.wait_idle()
        for action in inference.drain():
            if action.episode_seed == seed:
                latencies.append(action.inference_ms)
                decision_latencies.append(action.decision_latency_ms)

    stats = episode.stats
    stats.inference_count = len(latencies)
    stats.inference_mean_ms = statistics.fmean(latencies) if latencies else 0.0
    stats.inference_p50_ms = percentile(latencies, 50)
    stats.inference_p95_ms = percentile(latencies, 95)
    stats.decision_latency_mean_ms = (
        statistics.fmean(decision_latencies) if decision_latencies else 0.0
    )
    stats.decision_latency_p50_ms = percentile(decision_latencies, 50)
    stats.decision_latency_p95_ms = percentile(decision_latencies, 95)
    stats.observation_replacements = observation_replacements
    stats.submitted_actions = submitted
    return stats


def aggregate(episodes: list[EpisodeStats]) -> dict[str, Any]:
    return {
        "episodes": len(episodes),
        "total_kills": sum(item.kills for item in episodes),
        "mean_kills": statistics.fmean(item.kills for item in episodes),
        "mean_survival_seconds": statistics.fmean(
            item.native_tics / 35.0 for item in episodes
        ),
        "mean_effective_hz": statistics.fmean(
            item.effective_hz for item in episodes
        ),
        "valid_clock_episodes": sum(item.clock_valid for item in episodes),
        "mean_inference_ms": statistics.fmean(
            item.inference_mean_ms for item in episodes
        ),
        "mean_decision_latency_ms": statistics.fmean(
            item.decision_latency_mean_ms for item in episodes
        ),
        "mean_action_age_tics": statistics.fmean(
            item.action_age_mean_tics for item in episodes
        ),
        "total_neutral_tics": sum(item.neutral_tics for item in episodes),
        "total_observation_replacements": sum(
            item.observation_replacements for item in episodes
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--scenario-path", required=True, type=Path)
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(7, 17)))
    parser.add_argument("--observation-tics", type=int, default=4)
    parser.add_argument("--pulse-tics", type=int, default=4)
    parser.add_argument("--maximum-tics", type=int, default=2100)
    parser.add_argument("--tick-hz", type=float, default=35.0)
    parser.add_argument("--torch-threads", type=int)
    parser.add_argument(
        "--minimum-action-latency-ms",
        type=float,
        default=0.0,
        help="Floor observation-to-action delivery latency without stopping Doom",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    upstream = args.upstream.resolve()
    model_path = (
        args.model_path.resolve()
        if args.model_path
        else upstream / "models" / "doom-multivec-trained"
    )
    scenario_path = args.scenario_path.resolve()
    if not scenario_path.is_file():
        parser.error(f"scenario does not exist: {scenario_path}")
    if args.episodes <= 0:
        parser.error("--episodes must be positive")
    seeds = args.seeds[: args.episodes]
    if len(seeds) != args.episodes:
        parser.error("provide at least --episodes seeds")

    import torch

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        parser.error("--device cuda requested but torch.cuda.is_available() is false")
    inference = InferenceProcess(
        upstream=upstream,
        model_path=model_path,
        device=device,
        torch_threads=args.torch_threads,
        minimum_action_latency_ms=args.minimum_action_latency_ms,
    )
    inference.start()
    results: list[EpisodeStats] = []
    try:
        for index, seed in enumerate(seeds, start=1):
            stats = run_episode(
                inference,
                scenario_path=scenario_path,
                seed=seed,
                observation_tics=args.observation_tics,
                pulse_tics=args.pulse_tics,
                maximum_tics=args.maximum_tics,
                tick_hz=args.tick_hz,
            )
            results.append(stats)
            print(
                f"episode={index}/{len(seeds)} seed={seed} kills={stats.kills} "
                f"tics={stats.native_tics} hz={stats.effective_hz:.2f} "
                f"compute={stats.inference_mean_ms:.1f}ms "
                f"delivery={stats.decision_latency_mean_ms:.1f}ms "
                f"valid={stats.clock_valid} "
                f"age={stats.action_age_mean_tics:.2f}t neutral={stats.neutral_tics}",
                flush=True,
            )
            payload = {
                "runner": "vago-multivec-v4-independent-player-clock",
                "upstream": str(upstream),
                "model_path": str(model_path),
                "device": device,
                "scenario_path": str(scenario_path),
                "clock": {
                    "mode": "PLAYER owned by dedicated 35 Hz thread",
                    "tick_hz": args.tick_hz,
                    "observation_tics": args.observation_tics,
                    "pulse_tics": args.pulse_tics,
                    "maximum_tics": args.maximum_tics,
                    "inference_advances_world": True,
                    "minimum_action_latency_ms": args.minimum_action_latency_ms,
                    "late_action_behavior": "previous action expires, then neutral",
                    "observation_queue": "latest-only",
                },
                "episodes": [asdict(item) for item in results],
                "aggregate": aggregate(results),
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    finally:
        inference.close()

    print(json.dumps(payload["aggregate"], indent=2), flush=True)


if __name__ == "__main__":
    main()
