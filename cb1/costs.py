"""Append-only cost ledger + budget guardrail.

Every API call appends one JSONL record to data/costs.jsonl. Before every
call, check_budget() sums the ledger and hard-stops if the configured cap
is exceeded.
"""

import json
import time
from collections import defaultdict
from pathlib import Path

from cb1 import config


class BudgetExceeded(RuntimeError):
    pass


def compute_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
    batch: bool = False,
) -> float:
    prices = config.PRICE_PER_MTOK[model]
    discount = config.BATCH_DISCOUNT if batch else 1.0
    cost = (
        input_tokens * prices["input"] * discount
        + output_tokens * prices["output"] * discount
        + cache_write_tokens * prices["cache_write"] * discount
        + cache_read_tokens * prices["cache_read"] * discount
    ) / 1_000_000
    return round(cost, 6)


class CostLedger:
    def __init__(self, path: Path | None = None, cap_usd: float | None = None):
        self.path = path or config.COSTS_PATH
        self.cap_usd = cap_usd if cap_usd is not None else config.BUDGET_CAP_USD

    def record(
        self,
        stage: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
        batch: bool = False,
        meeting: str | None = None,
    ) -> float:
        cost = compute_cost_usd(
            model, input_tokens, output_tokens, cache_write_tokens, cache_read_tokens, batch
        )
        entry = {
            "ts": time.time(),
            "stage": stage,
            "meeting": meeting,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_write_tokens": cache_write_tokens,
            "cache_read_tokens": cache_read_tokens,
            "batch": batch,
            "cost_usd": cost,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return cost

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open() as f:
            return [json.loads(line) for line in f if line.strip()]

    def total_usd(self) -> float:
        return round(sum(e["cost_usd"] for e in self.entries()), 6)

    def by_stage(self) -> dict[str, dict]:
        agg: dict[str, dict] = defaultdict(
            lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        )
        for e in self.entries():
            s = agg[e["stage"]]
            s["calls"] += 1
            s["input_tokens"] += e["input_tokens"]
            s["output_tokens"] += e["output_tokens"]
            s["cost_usd"] = round(s["cost_usd"] + e["cost_usd"], 6)
        return dict(agg)

    def check_budget(self) -> None:
        """Call before every API request. Raises once the cap is hit."""
        total = self.total_usd()
        if total >= self.cap_usd:
            raise BudgetExceeded(
                f"cumulative spend ${total:.2f} >= cap ${self.cap_usd:.2f} "
                f"(raise CB1_BUDGET_CAP_USD to continue)"
            )

    def report(self) -> str:
        lines = [f"{'stage':<20} {'calls':>6} {'in_tok':>10} {'out_tok':>10} {'cost_usd':>10}"]
        for stage, s in sorted(self.by_stage().items()):
            lines.append(
                f"{stage:<20} {s['calls']:>6} {s['input_tokens']:>10} "
                f"{s['output_tokens']:>10} {s['cost_usd']:>10.4f}"
            )
        lines.append(f"{'TOTAL':<20} {'':>6} {'':>10} {'':>10} {self.total_usd():>10.4f}")
        lines.append(f"budget cap: ${self.cap_usd:.2f}")
        return "\n".join(lines)
