"""Thin wrapper around the Anthropic SDK: budget check before every call,
cost ledger record after, SDK-level retries for rate limits."""

import base64
import time

import anthropic
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from cb1 import config
from cb1.costs import CostLedger

# transient network failures worth retrying; NOT 4xx API errors
TRANSIENT = (
    httpx.ReadTimeout,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
)


class Client:
    def __init__(self, ledger: CostLedger | None = None, backend: str | None = None):
        self.backend = backend or config.BACKEND
        if self.backend == "bedrock":
            self._client = anthropic.AnthropicBedrock(
                aws_region=config.AWS_REGION, max_retries=5
            )
        else:
            self._client = anthropic.Anthropic(max_retries=5)
        self.ledger = ledger or CostLedger()
        self.last_usage: dict = {}

    def _model_id(self, model: str) -> str:
        """Canonical model name -> backend-specific id. Ledger always gets
        the canonical name so pricing lookups stay backend-agnostic."""
        if self.backend == "bedrock":
            return config.BEDROCK_MODEL_IDS[model]
        return model

    @retry(
        retry=retry_if_exception_type(TRANSIENT),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, max=60),
        reraise=True,
    )
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
            model=self._model_id(model),
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
        )
        if system is not None:
            kwargs["system"] = system
        # stream + collect: the SDK refuses non-streaming requests whose
        # worst-case duration exceeds 10 minutes (max_tokens >= ~16k)
        with self._client.messages.stream(**kwargs) as s:
            resp = s.get_final_message()
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

        Bedrock has no Message Batches API (its batch inference is an
        S3/CreateModelInvocationJob flow — not worth the plumbing at this
        corpus size), so on that backend this degrades to sequential
        synchronous calls at list price.
        """
        if self.backend == "bedrock":
            return self._batch_sync_fallback(stage, requests)
        self.ledger.check_budget()
        batch = self._client.messages.batches.create(requests=requests)
        print(f"batch {batch.id}: {len(requests)} requests submitted")
        while batch.processing_status == "in_progress":
            time.sleep(poll_s)
            batch = self._client.messages.batches.retrieve(batch.id)
            c = batch.request_counts
            print(f"  {c.succeeded} ok / {c.errored} err / {c.processing} pending")

        req_models = {r["custom_id"]: r["params"]["model"] for r in requests}
        out: dict = {}
        for r in self._client.messages.batches.results(batch.id):
            if r.result.type == "succeeded":
                msg = r.result.message
                u = msg.usage
                cost = self.ledger.record(
                    stage=stage,
                    model=req_models.get(r.custom_id, config.MODEL),
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

    def _batch_sync_fallback(self, stage: str, requests: list[dict]) -> dict:
        print(f"bedrock backend: running {len(requests)} requests sequentially")
        out: dict = {}
        for i, req in enumerate(requests, 1):
            p = req["params"]
            try:
                text = self.message(
                    stage=stage,
                    messages=p["messages"],
                    system=p.get("system"),
                    max_tokens=p.get("max_tokens", 4096),
                    temperature=p.get("temperature", 0.0),
                    meeting=req["custom_id"],
                    model=p.get("model", config.MODEL),
                )
                out[req["custom_id"]] = {
                    "text": text, "usage": dict(self.last_usage), "error": None,
                }
            except anthropic.APIStatusError as e:
                out[req["custom_id"]] = {"text": None, "usage": {}, "error": str(e)}
            print(f"  [{i}/{len(requests)}] {req['custom_id']}")
        return out


def image_block(jpeg_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(jpeg_bytes).decode(),
        },
    }
