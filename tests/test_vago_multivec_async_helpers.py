from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import threading
import time

import pytest

from manual_vago_multivec_async import (
    delay_until_latency_floor,
    EpisodeStats,
    FrameObservation,
    LatestFrame,
    percentile,
)
from manual_vago_multivec_async_batch import write_combined


def test_percentile_interpolates() -> None:
    assert percentile([], 95) == 0.0
    assert percentile([10.0], 95) == 10.0
    assert percentile([0.0, 10.0], 50) == 5.0


def test_latency_floor_waits_only_for_remaining_budget(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(time, "monotonic", lambda: 10.150)
    monkeypatch.setattr(time, "sleep", sleeps.append)

    delay_until_latency_floor(10.0, 200.0)
    assert sleeps == [pytest.approx(0.05)]

    sleeps.clear()
    delay_until_latency_floor(10.0, 100.0)
    assert sleeps == []


def test_latest_frame_coalesces_slow_consumer() -> None:
    mailbox = LatestFrame()
    first = FrameObservation(7, 1, 4, 1.0, object(), object())
    newest = FrameObservation(7, 3, 12, 3.0, object(), object())
    mailbox.publish(first)
    mailbox.publish(newest)
    assert mailbox.wait_newer(0) is newest


def test_latest_frame_unblocks_when_new_frame_arrives() -> None:
    mailbox = LatestFrame()
    expected = FrameObservation(7, 2, 8, 2.0, object(), object())

    def publish() -> None:
        time.sleep(0.01)
        mailbox.publish(expected)

    thread = threading.Thread(target=publish)
    thread.start()
    assert mailbox.wait_newer(1, timeout=0.5) is expected
    thread.join()


def test_batch_output_keeps_failures_visible(tmp_path: Path) -> None:
    output = tmp_path / "combined.json"
    episode = EpisodeStats(seed=7, kills=17, effective_hz=35.0)
    write_combined(
        output=output,
        base={"runner": "test"},
        episodes=[asdict(episode)],
        errors=[{"seed": 9, "error": "wall_timeout_100s"}],
        timeout_seconds=100.0,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["aggregate"]["mean_kills"] == 17
    assert payload["batch"]["errors"] == [
        {"seed": 9, "error": "wall_timeout_100s"}
    ]
