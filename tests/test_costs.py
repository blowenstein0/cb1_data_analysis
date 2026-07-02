import pytest

from cb1.costs import BudgetExceeded, CostLedger, compute_cost_usd


def test_compute_cost_haiku_list_price():
    # 1M in + 1M out at list: $1 + $5
    assert compute_cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000) == 6.0


def test_compute_cost_batch_discount():
    assert compute_cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000, batch=True) == 3.0


def test_compute_cost_cache_tokens():
    # cache read is $0.10/MTok
    assert compute_cost_usd("claude-haiku-4-5", 0, 0, cache_read_tokens=1_000_000) == 0.1


def test_ledger_records_and_aggregates(tmp_path):
    ledger = CostLedger(path=tmp_path / "costs.jsonl", cap_usd=75)
    ledger.record("identify", "claude-haiku-4-5", 1000, 200, meeting="cb1-2016-01-12")
    ledger.record("identify", "claude-haiku-4-5", 1500, 300)
    ledger.record("extract", "claude-haiku-4-5", 50_000, 5000, batch=True)
    stages = ledger.by_stage()
    assert stages["identify"]["calls"] == 2
    assert stages["identify"]["input_tokens"] == 2500
    assert ledger.total_usd() == pytest.approx(
        compute_cost_usd("claude-haiku-4-5", 1000, 200)
        + compute_cost_usd("claude-haiku-4-5", 1500, 300)
        + compute_cost_usd("claude-haiku-4-5", 50_000, 5000, batch=True)
    )


def test_budget_guardrail(tmp_path):
    ledger = CostLedger(path=tmp_path / "costs.jsonl", cap_usd=0.001)
    ledger.check_budget()  # empty ledger is fine
    ledger.record("extract", "claude-haiku-4-5", 1_000_000, 0)  # $1
    with pytest.raises(BudgetExceeded, match="cap"):
        ledger.check_budget()


def test_empty_ledger_total_zero(tmp_path):
    ledger = CostLedger(path=tmp_path / "missing.jsonl")
    assert ledger.total_usd() == 0
    assert ledger.by_stage() == {}
