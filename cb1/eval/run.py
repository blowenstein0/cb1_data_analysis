"""Eval runner: extract the golden meetings, compare, gate.

Golden files: eval/golden/<meeting_id>.json (hand-corrected extractions).
Raw model outputs cache to eval/cache/<meeting_id>__<prompt_version>.json
so prompt-unchanged re-runs are free and diffs are inspectable.

Workflow to create a golden meeting:
    python -m cb1.cli eval --draft cb1-2016-01-12
    # hand-correct eval/golden/cb1-2016-01-12.draft.json
    # rename to eval/golden/cb1-2016-01-12.json
"""

import json
import sys

from pydantic import ValidationError

from cb1 import config
from cb1.eval.scorecard import aggregate, render, score_meeting
from cb1.extract import (
    build_meeting_text,
    extract_meeting_sync,
    finalize,
    parse_llm_extraction,
)


def _load_meetings() -> dict:
    return json.loads((config.DATA_DIR / "meetings.json").read_text())["meetings"]


def _cache_path(meeting_id: str):
    return config.EVAL_CACHE_DIR / f"{meeting_id}__{config.PROMPT_VERSION}.json"


def extract_for_eval(meeting: dict, client) -> dict:
    """Extraction for eval runs, cached on raw output keyed by prompt version."""
    cache = _cache_path(meeting["meeting_id"])
    if cache.exists():
        raw = json.loads(cache.read_text())["raw"]
        _, stats = build_meeting_text(meeting)
        try:
            return finalize(meeting, parse_llm_extraction(raw), stats).model_dump()
        except ValidationError:
            pass  # stale/invalid cache: fall through to a live call
    if client is None:
        raise SystemExit(
            f"no cached extraction for {meeting['meeting_id']} and no API client "
            "(set ANTHROPIC_API_KEY)"
        )
    ex = extract_meeting_sync(meeting, client)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"raw": ex.model_dump_json()}))
    return ex.model_dump()


def run_eval(client=None) -> int:
    goldens = sorted(config.GOLDEN_DIR.glob("cb1-*.json"))
    goldens = [g for g in goldens if not g.name.endswith(".draft.json")]
    if not goldens:
        print(
            "no golden meetings in eval/golden/ — create drafts with:\n"
            "  python -m cb1.cli eval --draft <meeting_id>"
        )
        return 1

    meetings = _load_meetings()
    per_meeting = {}
    for gpath in goldens:
        golden = json.loads(gpath.read_text())
        mid = golden["meeting"]["meeting_id"]
        extracted = extract_for_eval(meetings[mid], client)
        per_meeting[mid] = score_meeting(golden, extracted)

    agg = aggregate(per_meeting)
    print(render(agg, per_meeting))
    return 0 if agg["passed"] else 2


def draft_golden(meeting_id: str, client) -> None:
    """Produce a draft extraction for hand-correction into golden truth."""
    meetings = _load_meetings()
    if meeting_id not in meetings:
        raise SystemExit(f"unknown meeting id {meeting_id}")
    extracted = extract_for_eval(meetings[meeting_id], client)
    out = config.GOLDEN_DIR / f"{meeting_id}.draft.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(extracted, indent=2))
    print(f"draft written to {out}\nhand-correct it, then rename to {meeting_id}.json")


if __name__ == "__main__":
    sys.exit(run_eval())
