import asyncio
import json

import pytest

from thought_leak_range.cli import build_parser, main
from thought_leak_range.runner import (
    MockReasoningPilot,
    RunArtifacts,
    run_practice_range,
)


def test_cli_exposes_vago_sync_world_clock() -> None:
    args = build_parser().parse_args(
        [
            "mock",
            "--tap-mode",
            "direct-motor",
            "--world-clock",
            "vago-sync",
        ]
    )
    assert args.world_clock == "vago-sync"


def test_cli_rejects_vago_sync_before_running_a_non_v4_mode() -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "mock",
                "--tap-mode",
                "direct-bit",
                "--world-clock",
                "vago-sync",
            ]
        )
    assert error.value.code == 2


def test_vago_sync_rejects_non_v4_protocol() -> None:
    with pytest.raises(ValueError, match="requires direct-motor V4"):
        asyncio.run(
            run_practice_range(
                pilot=None,
                run_id="abc123def456",
                artifacts=None,
                duration_seconds=0.1,
                observation_interval=0.1,
                lanes=1,
                request_limit=1,
                visible=False,
                seed=7,
                show_thoughts=False,
                tap_mode="direct-bit",
                scenario="basic",
                world_clock="vago-sync",
            )
        )


def test_vago_sync_mock_freezes_during_request_and_runs_serially(tmp_path) -> None:
    artifacts = RunArtifacts(
        base_dir=tmp_path,
        run_id="abc123def456",
        save_thoughts=False,
    )
    try:
        summary = asyncio.run(
            run_practice_range(
                pilot=MockReasoningPilot(tap_mode="direct-motor"),
                run_id="abc123def456",
                artifacts=artifacts,
                duration_seconds=0.1,
                observation_interval=0.01,
                lanes=3,
                request_limit=4,
                visible=False,
                seed=7,
                show_thoughts=False,
                tap_mode="direct-motor",
                scenario="defend_the_center",
                world_clock="vago-sync",
                motor_token_max_age_ms=400,
            )
        )
    finally:
        artifacts.close()

    events = [
        json.loads(line)
        for line in artifacts.events_path.read_text(encoding="utf-8").splitlines()
    ]
    waits = [event for event in events if event["kind"] == "sync_world_wait_finished"]

    assert summary["world_clock"] == "vago-sync"
    assert summary["duration_basis"] == "simulation_time"
    assert summary["target_ticks"] == 4
    assert summary["ticks"] == 4
    assert summary["configured_lanes"] == 3
    assert summary["effective_lanes"] == 1
    assert summary["requests_launched"] == 1
    assert summary["requests_completed"] == 1
    assert summary["motor_token_preemptions"] == 0
    assert summary["sync_fail_closed_wait_ticks"] == 0
    assert waits and all(event["game_tick_delta"] == 0 for event in waits)
