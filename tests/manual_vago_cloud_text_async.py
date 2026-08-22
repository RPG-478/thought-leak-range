r"""Run VAGO's exact Cloud-LLM text input on an independent 35 Hz clock.

The byte-exact system prompt is read from an external VAGO checkout at run time;
this repository independently reproduces only the documented 40x25 View/depth
transformation and parser. Two backends are supported:

    # Three physical Colab T4 lanes
    python tests/manual_vago_cloud_text_async.py --backend remote \
      --upstream C:/path/to/SauerkrautLM-Doom-MultiVec \
      --scenario-path C:/ascii-path/defend_the_center.cfg \
      --episodes 10 --lanes 3 --output runs/vago-text-3t4.json

    # Three in-flight OpenRouter lanes
    python tests/manual_vago_cloud_text_async.py --backend openrouter \
      --upstream C:/path/to/SauerkrautLM-Doom-MultiVec \
      --scenario-path C:/ascii-path/defend_the_center.cfg \
      --episodes 10 --lanes 3 --output runs/vago-text-openrouter.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from manual_vago_multivec_async import (
    EpisodeStats,
    FrameObservation,
    ModelAction,
    PlayerClockEpisode,
    aggregate,
    percentile,
)
from thought_leak_range.openrouter import (
    CostBudget,
    OpenRouterReasoningClient,
    load_api_key,
)
from thought_leak_range.remote_lanes import (
    DEFAULT_LANE_ENV,
    RemoteLanePoolClient,
    load_remote_lane_configs,
)
from thought_leak_range.vago_text import (
    build_vago_cloud_user_content,
    extract_upstream_llm_system_prompt,
    parse_vago_cloud_action,
)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    action: str
    buttons: tuple[int, int, int, int]
    completion: str
    arrived_at: float
    inference_ms: float
    wire_ms: float
    lane: str
    provider: str | None
    prompt_tokens: int | None
    completion_tokens: int | None


class VagoTextPolicy(Protocol):
    lane_count: int

    async def warmup(self) -> Any: ...

    async def decide(
        self,
        *,
        frame: FrameObservation,
        system_prompt: str,
        user_content: str,
        run_id: str,
    ) -> PolicyDecision: ...

    async def aclose(self) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...


class RemoteVagoTextPolicy:
    def __init__(
        self,
        client: RemoteLanePoolClient,
        *,
        max_new_tokens: int,
        temperature: float,
    ) -> None:
        self.client = client
        self.lane_count = client.lane_count
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature

    async def warmup(self) -> Any:
        return await self.client.warmup()

    async def decide(
        self,
        *,
        frame: FrameObservation,
        system_prompt: str,
        user_content: str,
        run_id: str,
    ) -> PolicyDecision:
        decision = await self.client.decide_vago_text(
            system_prompt=system_prompt,
            user_content=user_content,
            run_id=run_id,
            observation_seq=frame.seq,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
        )
        return PolicyDecision(
            action=decision.action,
            buttons=decision.buttons,
            completion=decision.completion,
            arrived_at=decision.arrived_at,
            inference_ms=decision.server_compute_ms or decision.wire_ms,
            wire_ms=decision.wire_ms,
            lane=decision.lane,
            provider=f"remote-colab/{decision.lane}",
            prompt_tokens=decision.prompt_tokens,
            completion_tokens=decision.completion_tokens,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    def snapshot(self) -> dict[str, Any]:
        return self.client.snapshot()


class OpenRouterVagoTextPolicy:
    def __init__(
        self,
        client: OpenRouterReasoningClient,
        *,
        lanes: int,
        temperature: float,
    ) -> None:
        self.client = client
        self.lane_count = lanes
        self.temperature = temperature
        self._available: asyncio.Queue[int] = asyncio.Queue()
        for lane in range(lanes):
            self._available.put_nowait(lane)

    async def warmup(self) -> Any:
        return {"tls_warmup_ms": await self.client.warmup()}

    async def decide(
        self,
        *,
        frame: FrameObservation,
        system_prompt: str,
        user_content: str,
        run_id: str,
    ) -> PolicyDecision:
        lane = await self._available.get()
        try:
            chunks: list[str] = []
            stream = await self.client.stream(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                on_reasoning=lambda _text, _arrived: None,
                on_visible=lambda text, _arrived: chunks.append(text),
                temperature=self.temperature,
                reasoning_enabled=False,
            )
            arrived_at = time.monotonic()
            completion = "".join(chunks)
            action, buttons = parse_vago_cloud_action(completion)
            usage = stream.usage
            return PolicyDecision(
                action=action,
                buttons=buttons,
                completion=completion[:1_000],
                arrived_at=arrived_at,
                inference_ms=stream.total_ms,
                wire_ms=stream.total_ms,
                lane=f"openrouter-{lane}",
                provider=stream.provider,
                prompt_tokens=_optional_int(
                    usage.get("prompt_tokens", usage.get("input_tokens"))
                ),
                completion_tokens=_optional_int(
                    usage.get("completion_tokens", usage.get("output_tokens"))
                ),
            )
        finally:
            self._available.put_nowait(lane)

    async def aclose(self) -> None:
        await self.client.aclose()

    def snapshot(self) -> dict[str, Any]:
        return {"budget": self.client.budget.snapshot()}


@dataclass(frozen=True, slots=True)
class DecisionLog:
    obs_seq: int
    obs_game_tick: int
    action: str
    buttons: tuple[int, int, int, int]
    completion: str
    inference_ms: float
    decision_latency_ms: float
    wire_ms: float
    lane: str
    provider: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    input_characters: int


async def run_episode(
    policy: VagoTextPolicy,
    *,
    system_prompt: str,
    scenario_path: Path,
    seed: int,
    observation_tics: int,
    pulse_tics: int,
    maximum_tics: int,
    tick_hz: float,
    run_id: str,
) -> tuple[EpisodeStats, list[DecisionLog]]:
    episode = PlayerClockEpisode(
        scenario_path=scenario_path,
        seed=seed,
        observation_tics=observation_tics,
        pulse_tics=pulse_tics,
        maximum_tics=maximum_tics,
        tick_hz=tick_hz,
    )
    episode.start()
    tasks: dict[asyncio.Task[PolicyDecision], tuple[FrameObservation, int]] = {}
    last_seq = 0
    skipped_observations = 0
    submitted = 0
    logs: list[DecisionLog] = []
    inference_latencies: list[float] = []
    decision_latencies: list[float] = []

    def harvest() -> None:
        nonlocal tasks
        for task in [candidate for candidate in tasks if candidate.done()]:
            frame, input_characters = tasks.pop(task)
            decision = task.result()
            latency_ms = (decision.arrived_at - frame.captured_at) * 1_000.0
            inference_latencies.append(decision.inference_ms)
            decision_latencies.append(latency_ms)
            logs.append(
                DecisionLog(
                    obs_seq=frame.seq,
                    obs_game_tick=frame.game_tick,
                    action=decision.action,
                    buttons=decision.buttons,
                    completion=decision.completion,
                    inference_ms=decision.inference_ms,
                    decision_latency_ms=latency_ms,
                    wire_ms=decision.wire_ms,
                    lane=decision.lane,
                    provider=decision.provider,
                    prompt_tokens=decision.prompt_tokens,
                    completion_tokens=decision.completion_tokens,
                    input_characters=input_characters,
                )
            )
            episode.actions.submit(
                ModelAction(
                    episode_seed=seed,
                    name=decision.action,
                    buttons=decision.buttons,
                    obs_seq=frame.seq,
                    obs_game_tick=frame.game_tick,
                    inference_ms=decision.inference_ms,
                    decision_latency_ms=latency_ms,
                    arrived_at=decision.arrived_at,
                )
            )

    try:
        while not episode.finished.is_set():
            harvest()
            frame = episode.frames.latest()
            if frame is not None and frame.seq > last_seq:
                skipped_observations += max(0, frame.seq - last_seq - 1)
                last_seq = frame.seq
                if len(tasks) < policy.lane_count:
                    user_content = build_vago_cloud_user_content(
                        frame.screen,
                        frame.depth,
                    )
                    task = asyncio.create_task(
                        policy.decide(
                            frame=frame,
                            system_prompt=system_prompt,
                            user_content=user_content,
                            run_id=run_id,
                        )
                    )
                    tasks[task] = (frame, len(user_content))
                    submitted += 1
                else:
                    skipped_observations += 1
            await asyncio.sleep(0.002)
    finally:
        episode.join()
        if tasks:
            await asyncio.gather(*tasks)
            harvest()

    stats = episode.stats
    stats.inference_count = len(inference_latencies)
    stats.inference_mean_ms = (
        statistics.fmean(inference_latencies) if inference_latencies else 0.0
    )
    stats.inference_p50_ms = percentile(inference_latencies, 50)
    stats.inference_p95_ms = percentile(inference_latencies, 95)
    stats.decision_latency_mean_ms = (
        statistics.fmean(decision_latencies) if decision_latencies else 0.0
    )
    stats.decision_latency_p50_ms = percentile(decision_latencies, 50)
    stats.decision_latency_p95_ms = percentile(decision_latencies, 95)
    stats.observation_replacements = skipped_observations
    stats.submitted_actions = submitted
    return stats, logs


async def run(args: argparse.Namespace) -> dict[str, Any]:
    upstream = args.upstream.resolve()
    benchmark_path = upstream / "scripts" / "benchmark.py"
    system_prompt = extract_upstream_llm_system_prompt(benchmark_path)
    scenario_path = args.scenario_path.resolve()
    run_id = f"vago-text-{uuid.uuid4().hex[:12]}"

    if args.backend == "remote":
        configs = load_remote_lane_configs(
            config_file=args.lane_config,
            env_name=args.lane_env,
        )
        if len(configs) != args.lanes:
            raise ValueError(
                f"--lanes={args.lanes}, but {len(configs)} remote endpoints were configured"
            )
        policy: VagoTextPolicy = RemoteVagoTextPolicy(
            RemoteLanePoolClient(configs, timeout_seconds=args.timeout),
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
        )
    else:
        budget = CostBudget(
            maximum_usd=args.max_usd,
            maximum_requests=args.max_requests,
        )
        client = OpenRouterReasoningClient(
            api_key=load_api_key(env_file=args.env_file),
            budget=budget,
            model=args.model,
            reasoning_effort="none",
            max_tokens=max(16, args.max_new_tokens),
            timeout_seconds=args.timeout,
            provider_sort="latency",
            provider_order=tuple(args.provider),
            provider_allow_fallbacks=args.provider_allow_fallbacks,
            preferred_max_latency_seconds=args.preferred_max_latency,
            session_id=f"latency-kills-vago-text-{args.model}",
        )
        policy = OpenRouterVagoTextPolicy(
            client,
            lanes=args.lanes,
            temperature=args.temperature,
        )

    warmup_started = time.monotonic()
    warmup = await policy.warmup()
    warmup_ms = (time.monotonic() - warmup_started) * 1_000.0
    episodes: list[EpisodeStats] = []
    decision_logs: list[list[DecisionLog]] = []
    try:
        for index, seed in enumerate(args.seeds[: args.episodes], start=1):
            stats, logs = await run_episode(
                policy,
                system_prompt=system_prompt,
                scenario_path=scenario_path,
                seed=seed,
                observation_tics=args.observation_tics,
                pulse_tics=args.pulse_tics,
                maximum_tics=args.maximum_tics,
                tick_hz=args.tick_hz,
                run_id=run_id,
            )
            episodes.append(stats)
            decision_logs.append(logs)
            print(
                f"episode={index}/{args.episodes} seed={seed} kills={stats.kills} "
                f"hz={stats.effective_hz:.2f} compute={stats.inference_mean_ms:.1f}ms "
                f"delivery={stats.decision_latency_mean_ms:.1f}ms "
                f"age={stats.action_age_mean_tics:.2f}t valid={stats.clock_valid}",
                flush=True,
            )
            payload = _payload(
                args=args,
                upstream=upstream,
                scenario_path=scenario_path,
                run_id=run_id,
                warmup=warmup,
                warmup_ms=warmup_ms,
                policy=policy,
                episodes=episodes,
                decision_logs=decision_logs,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    finally:
        await policy.aclose()
    return payload


def _payload(
    *,
    args: argparse.Namespace,
    upstream: Path,
    scenario_path: Path,
    run_id: str,
    warmup: Any,
    warmup_ms: float,
    policy: VagoTextPolicy,
    episodes: list[EpisodeStats],
    decision_logs: list[list[DecisionLog]],
) -> dict[str, Any]:
    return {
        "runner": "vago-cloud-text-v4-independent-player-clock",
        "run_id": run_id,
        "backend": args.backend,
        "model": args.model if args.backend == "openrouter" else "Llama-3.1-8B-Instruct",
        "upstream": str(upstream),
        "upstream_commit": _git_commit(upstream),
        "prompt_source": "byte-exact LLMAgent.SYSTEM_PROMPT extracted at runtime",
        "input_contract": "VAGO Cloud LLMAgent 40x25 brightness ASCII + textual depth 0-9",
        "scenario_path": str(scenario_path),
        "lanes": args.lanes,
        "warmup_ms": warmup_ms,
        "warmup": warmup,
        "clock": {
            "mode": "PLAYER owned by dedicated 35 Hz thread",
            "tick_hz": args.tick_hz,
            "observation_tics": args.observation_tics,
            "pulse_tics": args.pulse_tics,
            "maximum_tics": args.maximum_tics,
            "inference_advances_world": True,
            "late_action_behavior": "previous action expires, then neutral",
            "observation_queue": "drop when every physical/in-flight lane is busy",
        },
        "decode": {
            "contract": "VAGO last-line substring parser with move_forward fallback",
            "temperature": args.temperature,
            "max_new_tokens": args.max_new_tokens,
            "early_action_execution": False,
        },
        "episodes": [
            {
                "stats": asdict(stats),
                "decisions": [asdict(item) for item in logs],
            }
            for stats, logs in zip(episodes, decision_logs, strict=True)
        ],
        "aggregate": aggregate(episodes),
        "policy": policy.snapshot(),
    }


def _git_commit(directory: Path) -> str | None:
    head = directory / ".git" / "HEAD"
    if not head.is_file():
        return None
    value = head.read_text(encoding="utf-8").strip()
    if not value.startswith("ref: "):
        return value or None
    ref = directory / ".git" / value[5:]
    return ref.read_text(encoding="utf-8").strip() if ref.is_file() else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("remote", "openrouter"), required=True)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--scenario-path", required=True, type=Path)
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(7, 17)))
    parser.add_argument("--lanes", type=int, default=3)
    parser.add_argument("--observation-tics", type=int, default=4)
    parser.add_argument("--pulse-tics", type=int, default=4)
    parser.add_argument("--maximum-tics", type=int, default=2100)
    parser.add_argument("--tick-hz", type=float, default=35.0)
    parser.add_argument("--max-new-tokens", type=int, default=200)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--lane-config", type=Path)
    parser.add_argument("--lane-env", default=DEFAULT_LANE_ENV)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model", default="meta-llama/llama-3.1-8b-instruct")
    parser.add_argument("--provider", action="append", default=[])
    parser.add_argument(
        "--no-provider-fallback",
        action="store_false",
        dest="provider_allow_fallbacks",
        default=True,
    )
    parser.add_argument("--preferred-max-latency", type=float, default=0.2)
    parser.add_argument("--max-usd", type=float, default=2.0)
    parser.add_argument("--max-requests", type=int, default=2_000)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.episodes <= 0 or len(args.seeds) < args.episodes:
        parser.error("provide at least one seed per positive episode")
    if not 1 <= args.lanes <= 16:
        parser.error("--lanes must be between 1 and 16")
    if not args.scenario_path.is_file():
        parser.error(f"scenario does not exist: {args.scenario_path}")
    if not (args.upstream / "scripts" / "benchmark.py").is_file():
        parser.error("--upstream does not contain scripts/benchmark.py")
    if not 1 <= args.max_new_tokens <= 200:
        parser.error("--max-new-tokens must be between 1 and 200")
    if not 0.0 <= args.temperature <= 2.0:
        parser.error("--temperature must be between 0 and 2")
    payload = asyncio.run(run(args))
    print(json.dumps(payload["aggregate"], indent=2), flush=True)


if __name__ == "__main__":
    main()
