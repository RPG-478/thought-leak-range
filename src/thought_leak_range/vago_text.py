from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import numpy as np


VAGO_TEXT_WIDTH = 40
VAGO_TEXT_HEIGHT = 25
VAGO_BRIGHTNESS_CHARS = " .:-=+*#%@"
VAGO_ACTION_NAMES = ("shoot", "move_forward", "turn_left", "turn_right")
VAGO_ACTION_BUTTONS = {
    "shoot": (1, 0, 0, 0),
    "move_forward": (0, 1, 0, 0),
    "turn_left": (0, 0, 1, 0),
    "turn_right": (0, 0, 0, 1),
}


def extract_upstream_llm_system_prompt(benchmark_path: Path) -> str:
    """Read LLMAgent.SYSTEM_PROMPT without importing the external project.

    Keeping the byte-exact upstream prompt outside this repository avoids
    silently vendoring code from a repository whose README names Apache 2.0
    but whose current tree does not contain the corresponding license text.
    """

    source = benchmark_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(benchmark_path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "LLMAgent":
            continue
        for statement in node.body:
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                continue
            target = statement.targets[0]
            if isinstance(target, ast.Name) and target.id == "SYSTEM_PROMPT":
                value = ast.literal_eval(statement.value)
                if isinstance(value, str) and value.strip():
                    return value
    raise ValueError(f"LLMAgent.SYSTEM_PROMPT was not found in {benchmark_path}")


def build_vago_cloud_user_content(screen: Any, depth: Any | None) -> str:
    """Reproduce VAGO's published Cloud-LLM View + textual-depth payload.

    This intentionally follows ``scripts/benchmark.py`` rather than the 1.3M
    model path: the Cloud baseline receives brightness ASCII plus a second
    0--9 text grid, while the specialist receives aligned 16-bin embeddings.
    """

    frame = np.asarray(screen)
    gray = np.mean(frame, axis=2).astype(np.uint8) if frame.ndim == 3 else frame
    ascii_frame = _ascii_from_gray(gray)
    user_content = f"View:\n```\n{ascii_frame}\n```"
    if depth is not None:
        user_content += (
            "\n\nDepth (0=near, 9=far):\n```\n"
            f"{_depth_text(np.asarray(depth))}\n```"
        )
    return user_content


def parse_vago_cloud_action(text: str) -> tuple[str, tuple[int, int, int, int]]:
    """Match the public VAGO LLMAgent parser, including its forward fallback."""

    action_text = text.strip().lower()
    lines = [line.strip() for line in action_text.split("\n") if line.strip()]
    if lines:
        action_text = lines[-1]

    buttons = [0, 0, 0, 0]
    parsed: list[str] = []
    for action in VAGO_ACTION_NAMES:
        if action not in action_text:
            continue
        action_buttons = VAGO_ACTION_BUTTONS[action]
        buttons = [max(a, b) for a, b in zip(buttons, action_buttons, strict=True)]
        parsed.append(action)
    if parsed:
        return "+".join(parsed), tuple(buttons)
    return "move_forward", VAGO_ACTION_BUTTONS["move_forward"]


def _downscale_like_vago(image: np.ndarray) -> np.ndarray:
    if image.ndim != 2:
        raise ValueError("VAGO text conversion expects a 2-D buffer after grayscale")
    height, width = image.shape
    block_h = height // VAGO_TEXT_HEIGHT
    block_w = width // VAGO_TEXT_WIDTH
    if block_h < 1 or block_w < 1:
        raise ValueError("source buffer is smaller than the 40x25 text grid")
    cropped = image[
        : block_h * VAGO_TEXT_HEIGHT,
        : block_w * VAGO_TEXT_WIDTH,
    ]
    return (
        cropped.reshape(
            VAGO_TEXT_HEIGHT,
            block_h,
            VAGO_TEXT_WIDTH,
            block_w,
        )
        .mean(axis=(1, 3))
        .astype(np.uint8)
    )


def _ascii_from_gray(gray: np.ndarray) -> str:
    resized = _downscale_like_vago(gray)
    rows: list[str] = []
    levels = len(VAGO_BRIGHTNESS_CHARS)
    for row in resized:
        rows.append(
            "".join(
                VAGO_BRIGHTNESS_CHARS[
                    min(int(int(value) / 256 * levels), levels - 1)
                ]
                for value in row
            )
        )
    return "\n".join(rows)


def _depth_text(depth: np.ndarray) -> str:
    source = depth.astype(np.float32) if depth.dtype != np.float32 else depth
    resized = _downscale_like_vago(source)
    low = resized.min()
    high = resized.max()
    if high > low:
        normalized = (resized - low) / (high - low)
    else:
        normalized = np.zeros_like(resized)
    quantized = np.clip((normalized * 10).astype(int), 0, 9)
    return "\n".join("".join(str(int(value)) for value in row) for row in quantized)
