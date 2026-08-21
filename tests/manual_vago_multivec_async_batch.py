"""Run the unpaused VAGO adapter with one OS process per episode.

ViZDoom can wedge while repeatedly creating DoomGame instances in one long
Python process.  The Colab benchmark therefore isolates every seed and merges
the per-seed JSON files.  A wedged seed is killed by a wall-clock watchdog and
is reported, never silently averaged.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any

from manual_vago_multivec_async import EpisodeStats, aggregate


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()


def kill_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()


def write_combined(
    *,
    output: Path,
    base: dict[str, Any],
    episodes: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    timeout_seconds: float,
) -> None:
    stats = [EpisodeStats(**episode) for episode in episodes]
    payload = dict(base)
    payload["episodes"] = episodes
    payload["aggregate"] = aggregate(stats)
    payload["batch"] = {
        "isolation": "one seed per OS process",
        "episode_wall_timeout_seconds": timeout_seconds,
        "errors": errors,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runner",
        type=Path,
        default=Path(__file__).with_name("manual_vago_multivec_async.py"),
    )
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--scenario-path", required=True, type=Path)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(7, 17)))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--observation-tics", type=int, default=4)
    parser.add_argument("--pulse-tics", type=int, default=4)
    parser.add_argument("--maximum-tics", type=int, default=2100)
    parser.add_argument("--tick-hz", type=float, default=35.0)
    parser.add_argument("--minimum-action-latency-ms", type=float, default=0.0)
    parser.add_argument("--episode-wall-timeout", type=float, default=100.0)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    episodes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    base: dict[str, Any] | None = None

    for seed in args.seeds:
        seed_output = args.output.with_name(f"{args.output.stem}-seed{seed}.json")
        command = [
            sys.executable,
            str(args.runner.resolve()),
            "--upstream",
            str(args.upstream.resolve()),
            "--scenario-path",
            str(args.scenario_path.resolve()),
            "--episodes",
            "1",
            "--seeds",
            str(seed),
            "--device",
            args.device,
            "--observation-tics",
            str(args.observation_tics),
            "--pulse-tics",
            str(args.pulse_tics),
            "--maximum-tics",
            str(args.maximum_tics),
            "--tick-hz",
            str(args.tick_hz),
            "--minimum-action-latency-ms",
            str(args.minimum_action_latency_ms),
            "--output",
            str(seed_output.resolve()),
        ]
        if args.model_path:
            command.extend(["--model-path", str(args.model_path.resolve())])

        print(f"seed={seed} start", flush=True)
        popen_options: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "env": {**os.environ, "PYTHONUNBUFFERED": "1"},
        }
        if os.name == "posix":
            popen_options["start_new_session"] = True
        process = subprocess.Popen(command, **popen_options)
        try:
            stdout, _ = process.communicate(timeout=args.episode_wall_timeout)
        except subprocess.TimeoutExpired:
            terminate_process_tree(process)
            try:
                stdout, _ = process.communicate(timeout=5.0)
            except subprocess.TimeoutExpired:
                kill_process_tree(process)
                stdout, _ = process.communicate()
            errors.append(
                {
                    "seed": seed,
                    "error": f"wall_timeout_{args.episode_wall_timeout:g}s",
                    "output_tail": stdout[-1000:],
                }
            )
            print(f"seed={seed} timeout", flush=True)
            if base is not None:
                write_combined(
                    output=args.output,
                    base=base,
                    episodes=episodes,
                    errors=errors,
                    timeout_seconds=args.episode_wall_timeout,
                )
            continue

        print(stdout, end="", flush=True)
        if process.returncode != 0 or not seed_output.is_file():
            errors.append(
                {
                    "seed": seed,
                    "error": f"exit_{process.returncode}",
                    "output_tail": stdout[-1000:],
                }
            )
            continue

        seed_payload = json.loads(seed_output.read_text(encoding="utf-8"))
        if base is None:
            base = {
                key: value
                for key, value in seed_payload.items()
                if key not in {"episodes", "aggregate"}
            }
        episodes.extend(seed_payload["episodes"])
        write_combined(
            output=args.output,
            base=base,
            episodes=episodes,
            errors=errors,
            timeout_seconds=args.episode_wall_timeout,
        )

    if base is None:
        raise SystemExit("no valid episodes completed")
    print(json.dumps(aggregate([EpisodeStats(**item) for item in episodes]), indent=2), flush=True)
    if errors:
        raise SystemExit(f"{len(errors)} episode(s) failed; see batch.errors")


if __name__ == "__main__":
    main()
