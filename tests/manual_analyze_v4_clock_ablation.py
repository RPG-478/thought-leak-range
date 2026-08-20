"""Aggregate a completed manual V4 clock-ablation batch."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(values, percentile)), 3)


def _load_events(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sum_counter(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: Counter[str] = Counter()
    for record in records:
        result.update(record["range"].get(key) or {})
    return dict(result)


def _mode_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    ranges = [record["range"] for record in records]
    motors = [
        event
        for record in records
        for event in record["events"]
        if event.get("kind") == "motor_token"
    ]
    accepted = [event for event in motors if event.get("accepted")]
    fire_events = [
        event
        for record in records
        for event in record["events"]
        if event.get("kind") == "motor_token_fire_executed"
    ]
    sync_waits = [
        event
        for record in records
        for event in record["events"]
        if event.get("kind") == "sync_world_wait_finished"
    ]
    kills = [int((value.get("final_observation") or {}).get("kills") or 0) for value in ranges]
    hits = [int((value.get("final_observation") or {}).get("hits") or 0) for value in ranges]
    ticks = [int(value.get("ticks") or 0) for value in ranges]
    costs = [float(record["summary"]["budget"]["reported_cost_usd"]) for record in records]
    all_latency = [float(event["latency_ms"]) for event in motors]
    accepted_latency = [float(event["latency_ms"]) for event in accepted]
    decisions = sum(int(value.get("motor_token_decisions") or 0) for value in ranges)
    correct = sum(int(value.get("motor_token_correct") or 0) for value in ranges)
    physical_shots = sum(
        max(0, int(event["ammo_before"]) - int(event["ammo_after"]))
        for event in fire_events
    )
    game_seconds = sum(ticks) / 35.0
    return {
        "runs": len(records),
        "kills": {
            "total": sum(kills),
            "mean": round(statistics.mean(kills), 3),
            "median": round(statistics.median(kills), 3),
            "minimum": min(kills),
            "maximum": max(kills),
        },
        "hits_total": sum(hits),
        "damage_total": sum(
            int((value.get("final_observation") or {}).get("damage") or 0)
            for value in ranges
        ),
        "game_ticks_total": sum(ticks),
        "game_seconds_total": round(game_seconds, 3),
        "game_seconds_mean": round(statistics.mean(ticks) / 35.0, 3),
        "runs_reaching_duration": sum(int(value.get("ticks") or 0) >= 525 for value in ranges),
        "stop_reasons": dict(
            Counter(
                value.get("stop_reason")
                or ("episode_finished" if value.get("episode_finished") else "duration_loop")
                for value in ranges
            )
        ),
        "kills_per_game_second": round(sum(kills) / game_seconds, 4),
        "wall_seconds_range_total": round(
            sum(float(value.get("duration_ms") or 0) for value in ranges) / 1000.0,
            3,
        ),
        "wall_seconds_including_probe_total": round(
            sum(float(record["manifest"]["wall_seconds_including_probe"]) for record in records),
            3,
        ),
        "requests": {
            "launched": sum(int(value.get("requests_launched") or 0) for value in ranges),
            "completed": sum(int(value.get("requests_completed") or 0) for value in ranges),
            "errors": sum(int(value.get("request_errors") or 0) for value in ranges),
            "per_game_second": round(
                sum(int(value.get("requests_launched") or 0) for value in ranges)
                / game_seconds,
                3,
            ),
        },
        "tokens": {
            "decisions": decisions,
            "accepted": len(accepted),
            "rejected": len(motors) - len(accepted),
            "correct": correct,
            "incorrect": decisions - correct,
            "semantic_accuracy": round(correct / decisions, 4) if decisions else None,
            "all_latency_ms": {
                "mean": round(statistics.mean(all_latency), 3),
                "p50": _percentile(all_latency, 50),
                "p95": _percentile(all_latency, 95),
                "maximum": round(max(all_latency), 3),
            },
            "accepted_latency_ms": {
                "mean": round(statistics.mean(accepted_latency), 3),
                "p50": _percentile(accepted_latency, 50),
                "p95": _percentile(accepted_latency, 95),
                "maximum": round(max(accepted_latency), 3),
            },
        },
        "actions_by_tick": _sum_counter(records, "actions_by_tick"),
        "motor_tokens_selected": _sum_counter(records, "motor_token_selected"),
        "motor_token_preemptions": sum(
            int(value.get("motor_token_preemptions") or 0) for value in ranges
        ),
        "coalesced_observations": sum(
            int(value.get("coalesced_observations") or 0) for value in ranges
        ),
        "fire_motor_ticks": len(fire_events),
        "observed_ammo_decrement_shots": physical_shots,
        "fire_ticks_without_ammo_decrement": len(fire_events) - physical_shots,
        "sync_waits": {
            "count": len(sync_waits),
            "nonzero_game_tick_delta": sum(
                int(event.get("game_tick_delta") or 0) != 0 for event in sync_waits
            ),
            "maximum_game_tick_delta": max(
                (int(event.get("game_tick_delta") or 0) for event in sync_waits),
                default=None,
            ),
            "fail_closed_wait_ticks": sum(
                int(value.get("sync_fail_closed_wait_ticks") or 0) for value in ranges
            ),
        },
        "budget": {
            "reported_cost_usd": round(sum(costs), 8),
            "prompt_tokens": sum(
                int(record["summary"]["budget"].get("prompt_tokens") or 0)
                for record in records
            ),
            "completion_tokens": sum(
                int(record["summary"]["budget"].get("completion_tokens") or 0)
                for record in records
            ),
        },
        "startup_probes_passed": sum(
            bool(record["summary"].get("probe", {}).get("passed")) for record in records
        ),
    }


def _sign_test_two_sided(wins: int, losses: int) -> float | None:
    trials = wins + losses
    if not trials:
        return None
    tail = min(wins, losses)
    probability = 2 * sum(math.comb(trials, k) for k in range(tail + 1)) / 2**trials
    return min(1.0, probability)


def _batch_records(batch_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for manifest_entry in manifest["runs"]:
        summary_path = batch_dir / manifest_entry["summary_path"]
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        events = _load_events(summary_path.with_name("events.jsonl"))
        records.append(
            {
                "manifest": manifest_entry,
                "summary": summary,
                "range": summary["range"],
                "events": events,
                "source_batch": str(batch_dir),
            }
        )
    return manifest, records


def analyze(batch_dir: Path, replacement_batches: list[Path] | None = None) -> dict[str, Any]:
    manifest, records = _batch_records(batch_dir)
    replacements: list[dict[str, Any]] = []
    for replacement_batch in replacement_batches or []:
        _, replacement_records = _batch_records(replacement_batch)
        replacements.extend(replacement_records)
    if replacements:
        keyed = {
            (record["manifest"]["seed"], record["manifest"]["world_clock"]): record
            for record in records
        }
        for record in replacements:
            keyed[(record["manifest"]["seed"], record["manifest"]["world_clock"])] = record
        records = list(keyed.values())

    by_clock = {
        clock: [record for record in records if record["manifest"]["world_clock"] == clock]
        for clock in ("unpaused", "vago-sync")
    }
    paired: list[dict[str, Any]] = []
    for seed in manifest["seeds"]:
        pair = {
            record["manifest"]["world_clock"]: record
            for record in records
            if record["manifest"]["seed"] == seed
        }
        unpaused = pair["unpaused"]["range"]
        stopped = pair["vago-sync"]["range"]
        unpaused_kills = int((unpaused["final_observation"] or {}).get("kills") or 0)
        stopped_kills = int((stopped["final_observation"] or {}).get("kills") or 0)
        paired.append(
            {
                "seed": seed,
                "first_clock": min(
                    (
                        record["manifest"]
                        for record in pair.values()
                    ),
                    key=lambda record: record["order_within_seed"],
                )["world_clock"],
                "unpaused_kills": unpaused_kills,
                "stopped_kills": stopped_kills,
                "kill_difference_stopped_minus_unpaused": stopped_kills - unpaused_kills,
                "unpaused_ticks": int(unpaused["ticks"]),
                "stopped_ticks": int(stopped["ticks"]),
                "tick_difference_stopped_minus_unpaused": int(stopped["ticks"])
                - int(unpaused["ticks"]),
            }
        )

    differences = [row["kill_difference_stopped_minus_unpaused"] for row in paired]
    wins = sum(value > 0 for value in differences)
    losses = sum(value < 0 for value in differences)
    ties = sum(value == 0 for value in differences)
    tick_differences = [row["tick_difference_stopped_minus_unpaused"] for row in paired]
    return {
        "batch_dir": str(batch_dir),
        "replacement_batches": [str(path) for path in replacement_batches or []],
        "git_head": manifest["git_head"],
        "conditions": {
            key: manifest[key]
            for key in (
                "model",
                "provider",
                "provider_fallback",
                "provider_sort",
                "scenario",
                "skill",
                "duration_simulation_seconds",
                "seeds",
                "order_rule",
                "motor_token_max_age_ms",
                "clock_backends",
            )
        },
        "completed_runs": len(records),
        "mode": {clock: _mode_summary(mode_records) for clock, mode_records in by_clock.items()},
        "paired": {
            "rows": paired,
            "stopped_wins": wins,
            "ties": ties,
            "stopped_losses": losses,
            "kill_difference_mean": round(statistics.mean(differences), 3),
            "kill_difference_median": round(statistics.median(differences), 3),
            "kill_difference_minimum": min(differences),
            "kill_difference_maximum": max(differences),
            "survival_tick_difference_mean": round(statistics.mean(tick_differences), 3),
            "sign_test_two_sided_p": _sign_test_two_sided(wins, losses),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("--replacement-batch", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(
        args.batch_dir.resolve(),
        [path.resolve() for path in args.replacement_batch],
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
