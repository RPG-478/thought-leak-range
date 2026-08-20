import asyncio

from thought_leak_range.runner import MockReasoningPilot, RunArtifacts, run_practice_range


def test_unpaused_mock_uses_async_player_clock(tmp_path) -> None:
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
                # ASYNC_PLAYER startup can consume well over 500 ms on a busy
                # Windows host. This test is about native-clock progress, not
                # startup latency, so leave a stable two-second observation.
                duration_seconds=2.0,
                observation_interval=0.05,
                lanes=3,
                request_limit=4,
                visible=False,
                seed=7,
                show_thoughts=False,
                tap_mode="direct-motor",
                scenario="defend_the_center",
                world_clock="unpaused",
                motor_token_max_age_ms=400,
            )
        )
    finally:
        artifacts.close()

    assert summary["world_clock"] == "unpaused"
    assert summary["clock_backend"] == "vizdoom-async-player"
    assert summary["ticks"] >= 4
