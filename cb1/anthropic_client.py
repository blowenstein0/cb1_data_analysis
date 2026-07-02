"""Thin wrapper around the Anthropic SDK: budget check before every call,
cost ledger record after, SDK-level retries for rate limits."""

import base64

import anthropic

from cb1 import config
from cb1.costs import CostLedger


class Client:
    def __init__(self, ledger: CostLedger | None = None):
        self._client = anthropic.Anthropic(max_retries=5)
        self.ledger = ledger or CostLedger()

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
        self.ledger.record(
            stage=stage,
            model=model,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            meeting=meeting,
        )
        return "".join(b.text for b in resp.content if b.type == "text")


def image_block(png_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.standard_b64encode(png_bytes).decode(),
        },
    }
