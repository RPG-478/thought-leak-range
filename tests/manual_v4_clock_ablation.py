r"""Run the paired V4 unpaused versus stopped-world Cloud experiment.

This is intentionally a manual paid experiment, not a pytest.  Odd seeds run
unpaused first and even seeds run vago-sync first so provider drift is not
assigned to only one clock. Unpaused uses ViZDoom ASYNC_PLAYER; vago-sync uses
ViZDoom PLAYER. A manifest is rewritten after every completed run.

Example:
    .venv\Scripts\python.exe tests\manual_v4_clock_ablation.py \
        --env-file C:\\path\\outside\\repo\\.env
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]


def _clock_order(seed: int) -> tuple[str, str]:
    if seed % 2:
        return "unpaused", "vago-sync"
    return "vago-sync", "unpaused"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _summary_for(parent: Path) -> tuple[Path, dict[str, Any]] | None:
    candidates = sorted(parent.glob("*/summary.json"))
    if len(candidates) != 1:
        return None
    path = candidates[0]
    return path, json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--batch-dir", type=Path)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(7, 17)))
    parser.add_argument(
        "--clocks",
        choices=("unpaused", "vago-sync"),
        nargs="+",
        help="override the paired per-seed order, primarily for a failed-run retry",
    )
    parser.add_argument("--model", default="meta-llama/llama-3.1-8b-instruct")
    parser.add_argument("--provider", default="Groq")
    parser.add_argument("--max-requests", type=int, default=300)
    parser.add_argument("--max-usd-per-run", type=float, default=0.04)
    parser.add_argument("--maximum-reported-cost-usd", type=float, default=0.05)
    args = parser.parse_args()

    env_file = args.env_file.resolve()
    if not env_file.is_file():
        parser.error(f"env file does not exist: {env_file}")
    if args.maximum_reported_cost_usd <= 0:
        parser.error("--maximum-reported-cost-usd must be positive")
    if not 7 <= args.max_requests <= 400:
        parser.error("--max-requests must be between 7 and 400")
    if args.max_usd_per_run <= 0:
        parser.error("--max-usd-per-run must be positive")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    batch_dir = (
        args.batch_dir.resolve()
        if args.batch_dir
        else PROJECT_DIR / "runs" / f"v4-clock-10x-{stamp}"
    )
    batch_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = batch_dir / "manifest.json"
    manifest: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_head": _git_head(),
        "model": args.model,
        "provider": args.provider,
        "provider_fallback": False,
        "provider_sort": "latency",
        "scenario": "defend_the_center",
        "skill": 1,
        "duration_simulation_seconds": 15,
        "seeds": args.seeds,
        "order_rule": (
            "explicit " + ",".join(args.clocks)
            if args.clocks
            else "odd unpaused-first; even vago-sync-first"
        ),
        "motor_token_max_age_ms": 400,
        "clock_backends": {
            "unpaused": "vizdoom-async-player",
            "vago-sync": "vizdoom-player",
        },
        "max_requests_per_run": args.max_requests,
        "max_usd_per_run": args.max_usd_per_run,
        "maximum_reported_cost_usd": args.maximum_reported_cost_usd,
        "runs": [],
    }
    _write_json(manifest_path, manifest)

    for seed in args.seeds:
        for world_clock in tuple(args.clocks or _clock_order(seed)):
            label = f"seed-{seed:02d}-{world_clock}"
            artifact_parent = batch_dir / label
            artifact_parent.mkdir()
            log_path = batch_dir / f"{label}.log"
            command = [
                sys.executable,
                "-m",
                "thought_leak_range",
                "live",
                "--env-file",
                str(env_file),
                "--model",
                args.model,
                "--provider",
                args.provider,
                "--no-provider-fallback",
                "--provider-sort",
                "latency",
                "--tap-mode",
                "direct-motor",
                "--world-clock",
                world_clock,
                "--lanes",
                "3",
                "--scenario",
                "defend_the_center",
                "--duration",
                "15",
                "--seed",
                str(seed),
                "--motor-token-max-age-ms",
                "400",
                "--max-tokens",
                "16",
                "--max-requests",
                str(args.max_requests),
                "--max-usd",
                str(args.max_usd_per_run),
                "--save-thoughts",
                "--artifact-dir",
                str(artifact_parent),
            ]
            if world_clock == "unpaused":
                command.extend(["--observation-interval", "0.10"])

            print(f"START {label}", flush=True)
            started = time.perf_counter()
            with log_path.open("w", encoding="utf-8") as log:
                completed = subprocess.run(
                    command,
                    cwd=PROJECT_DIR,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            wall_seconds = time.perf_counter() - started
            loaded_summary = _summary_for(artifact_parent)
            if loaded_summary is None:
                failure_entry = {
                    "seed": seed,
                    "world_clock": world_clock,
                    "returncode": completed.returncode,
                    "wall_seconds_including_probe": round(wall_seconds, 3),
                    "log_path": str(log_path.relative_to(batch_dir)),
                    "status": "missing_summary",
                    "valid_terminal": False,
                }
                manifest["runs"].append(failure_entry)
                _write_json(manifest_path, manifest)
                raise RuntimeError(
                    f"run produced no summary: {label} rc={completed.returncode}; "
                    f"inspect {log_path}"
                )
            summary_path, summary = loaded_summary
            budget = summary.get("budget") or {}
            reported_cost = float(budget.get("reported_cost_usd") or 0.0)
            range_summary = summary.get("range") or {}
            target_ticks = math.ceil(15 * 35)
            episode_finished = bool(range_summary.get("episode_finished"))
            if world_clock == "vago-sync":
                valid_terminal = episode_finished or int(
                    range_summary.get("ticks") or 0
                ) >= target_ticks
            else:
                # ASYNC_PLAYER is wall-clock paced by ViZDoom itself. Allow 5%
                # startup/scheduler jitter, but reject a surviving run that
                # failed to reach the requested simulation horizon.
                valid_terminal = episode_finished or int(
                    range_summary.get("ticks") or 0
                ) >= math.floor(target_ticks * 0.95)
            entry = {
                "seed": seed,
                "world_clock": world_clock,
                "clock_backend": range_summary.get("clock_backend"),
                "order_within_seed": len(
                    [run for run in manifest["runs"] if run["seed"] == seed]
                )
                + 1,
                "returncode": completed.returncode,
                "wall_seconds_including_probe": round(wall_seconds, 3),
                "summary_path": str(summary_path.relative_to(batch_dir)),
                "log_path": str(log_path.relative_to(batch_dir)),
                "reported_cost_usd": reported_cost,
                "status": summary.get("status"),
                "provider": summary.get("provider"),
                "kills": (range_summary.get("final_observation") or {}).get("kills"),
                "hits": (range_summary.get("final_observation") or {}).get("hits"),
                "game_ticks": range_summary.get("ticks"),
                "game_duration_ms": range_summary.get("simulation_duration_ms"),
                "episode_finished": episode_finished,
                "valid_terminal": valid_terminal,
            }
            manifest["runs"].append(entry)
            manifest["reported_cost_usd"] = sum(
                run["reported_cost_usd"] for run in manifest["runs"]
            )
            _write_json(manifest_path, manifest)
            print(
                f"DONE  {label} rc={completed.returncode} "
                f"kills={entry['kills']} cost=${reported_cost:.8f}",
                flush=True,
            )

            if completed.returncode != 0 or summary.get("status") != "completed":
                raise RuntimeError(f"run failed closed: {label}; inspect {log_path}")
            if not valid_terminal:
                raise RuntimeError(
                    f"time-model QC failed: {label} ended at "
                    f"{range_summary.get('ticks')} / {target_ticks} tics without death"
                )
            if manifest["reported_cost_usd"] > args.maximum_reported_cost_usd:
                raise RuntimeError(
                    "reported-cost guard exceeded after "
                    f"{label}: ${manifest['reported_cost_usd']:.8f}"
                )

    manifest["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_json(manifest_path, manifest)
    print(
        f"COMPLETE runs={len(manifest['runs'])} "
        f"cost=${manifest['reported_cost_usd']:.8f} batch={batch_dir}",
        flush=True,
    )


if __name__ == "__main__":
    main()
