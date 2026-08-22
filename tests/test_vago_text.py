from pathlib import Path

import numpy as np

from thought_leak_range.vago_text import (
    build_vago_cloud_user_content,
    extract_upstream_llm_system_prompt,
    parse_vago_cloud_action,
)


def test_vago_text_payload_has_exact_public_layout() -> None:
    screen = np.zeros((50, 80, 3), dtype=np.uint8)
    screen[:, 40:, :] = 255
    depth = np.zeros((50, 80), dtype=np.uint8)
    depth[:, 40:] = 255

    payload = build_vago_cloud_user_content(screen, depth)
    view, depth_part = payload.split("\n\nDepth (0=near, 9=far):\n```\n")
    view_rows = view.removeprefix("View:\n```\n").removesuffix("\n```").splitlines()
    depth_rows = depth_part.removesuffix("\n```").splitlines()

    assert len(view_rows) == 25
    assert all(row == " " * 20 + "@" * 20 for row in view_rows)
    assert len(depth_rows) == 25
    assert all(row == "0" * 20 + "9" * 20 for row in depth_rows)


def test_vago_action_parser_matches_substring_order_and_fallback() -> None:
    assert parse_vago_cloud_action("turn_left+shoot") == (
        "shoot+turn_left",
        (1, 0, 1, 0),
    )
    assert parse_vago_cloud_action("analysis\nturn_right") == (
        "turn_right",
        (0, 0, 0, 1),
    )
    assert parse_vago_cloud_action("nonsense") == (
        "move_forward",
        (0, 1, 0, 0),
    )


def test_extracts_prompt_without_importing_external_benchmark(tmp_path: Path) -> None:
    benchmark = tmp_path / "benchmark.py"
    benchmark.write_text(
        "class LLMAgent:\n    SYSTEM_PROMPT = 'upstream prompt'\n",
        encoding="utf-8",
    )
    assert extract_upstream_llm_system_prompt(benchmark) == "upstream prompt"
