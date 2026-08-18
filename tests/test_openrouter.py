from pathlib import Path

import pytest

from thought_leak_range.openrouter import (
    BudgetExceeded,
    CostBudget,
    _safe_error_detail,
    load_api_key,
)


def test_env_loader_reads_only_requested_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "UNRELATED=visible\nOPENROUTER_API_KEY='secret-for-test'\n",
        encoding="utf-8",
    )
    assert load_api_key(env_file=env_file) == "secret-for-test"


def test_process_environment_wins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "process-secret")
    assert load_api_key(env_file=tmp_path / "missing") == "process-secret"


def test_request_guard_is_hard() -> None:
    budget = CostBudget(maximum_usd=1.0, maximum_requests=1)
    messages = [{"role": "user", "content": "tiny"}]
    budget.reserve(messages, max_tokens=16)
    with pytest.raises(BudgetExceeded, match="request guard"):
        budget.reserve(messages, max_tokens=16)


def test_cost_guard_fails_before_request() -> None:
    budget = CostBudget(maximum_usd=0.000001, maximum_requests=10)
    with pytest.raises(BudgetExceeded, match="cost guard"):
        budget.reserve(
            [{"role": "user", "content": "x" * 20_000}],
            max_tokens=512,
        )


def test_error_detail_drops_account_and_upstream_raw_fields() -> None:
    body = (
        '{"error":{"message":"Provider returned error","code":429,'
        '"metadata":{"provider_name":"FastGPU","limit_source":"pool",'
        '"raw":"secret upstream detail","user_id":"user_private",'
        '"previous_errors":[{"provider_name":"OtherGPU",'
        '"raw":"another secret"}]}},"user_id":"outer_private"}'
    )
    detail = _safe_error_detail(body)
    assert "code=429" in detail
    assert "FastGPU" in detail
    assert "OtherGPU" in detail
    assert "user_private" not in detail
    assert "secret" not in detail
