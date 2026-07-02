"""Thin wrapper around the Anthropic SDK: budget check before every call,
cost ledger record after, SDK-level retries for rate limits."""

import base64
import time

import anthropic

from cb1 import config
from cb1.costs import CostLedger


class Client:
    def __init__(self, ledger: CostLedger | None = None):
        self._client = anthropic.Anthropic(max_retries=5)
        self.ledger = ledger or CostLedger()
        self.last_usage: dict = {}

    def message(
        self,
        stage: str,
        messages: list[dict],
        system: str | list | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        meeting: str | None = None,
        model: str = config.MODEL,
    ) -> str:
        """Synchronous call. Returns response text; logs tokens + cost."""
        self.ledger.check_budget()
        kwargs: dict = dict(
            model=model, max_tokens=max_tokens, temperature=temperature, messages=messages
        )
        if system is not None:
            kwargs["system"] = system
        resp = self._client.messages.create(**kwargs)
        u = resp.usage
        cost = self.ledger.record(
            stage=stage,
            model=model,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            meeting=meeting,
        )
        self.last_usage = {
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "cost_usd": cost,
        }
        return "".join(b.text for b in resp.content if b.type == "text")

    def batch(self, stage: str, requests: list[dict], poll_s: int = 30) -> dict:
        """Submit a Message Batch (50% off), poll to completion, log costs.

        `requests`: [{"custom_id": ..., "params": {...messages.create kwargs}}]
        Returns {custom_id: {"text": str|None, "usage": dict, "error": str|None}}.
        """
        self.ledger.check_budget()
        batch = self._client.messages.batches.create(requests=requests)
        print(f"batch {batch.id}: {len(requests)} requests submitted")
        while batch.processing_status == "in_progress":
            time.sleep(poll_s)
            batch = self._client.messages.batches.retrieve(batch.id)
            c = batch.request_counts
            print(f"  {c.succeeded} ok / {c.errored} err / {c.processing} pending")

        out: dict = {}
        for r in self._client.messages.batches.results(batch.id):
            if r.result.type == "succeeded":
                msg = r.result.message
                u = msg.usage
                cost = self.ledger.record(
                    stage=stage,
                    model=msg.model,
                    input_tokens=u.input_tokens,
                    output_tokens=u.output_tokens,
                    cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                    cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                    batch=True,
                    meeting=r.custom_id,
                )
                out[r.custom_id] = {
                    "text": "".join(b.text for b in msg.content if b.type == "text"),
                    "usage": {
                        "input_tokens": u.input_tokens,
                        "output_tokens": u.output_tokens,
                        "cost_usd": cost,
                    },
                    "error": None,
                }
            else:
                out[r.custom_id] = {"text": None, "usage": {}, "error": r.result.type}
        return out


def image_block(png_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.standard_b64encode(png_bytes).decode(),
        },
    }
