# Brooklyn CB1 Minutes → Structured Dataset

Ten years (2016–2026) of Brooklyn Community Board 1 (Williamsburg/Greenpoint)
meeting-minutes PDFs, extracted into a queryable DuckDB dataset via a
cost-tiered LLM pipeline, with an eval harness proving extraction accuracy.
See [PLAN.md](PLAN.md) for architecture and design decisions.

## Setup

```bash
uv sync
cp .env.example .env
```

LLM calls run on **Amazon Bedrock by default** (uses your AWS credentials;
cross-region Haiku 4.5 inference profile in `us-east-1`). Set
`ANTHROPIC_API_KEY` to use the Anthropic API directly instead — that also
re-enables the Message Batches API (50% off the extraction pass; Bedrock
falls back to sequential synchronous calls).

## Run

```bash
make all          # empty repo -> populated DuckDB (idempotent; re-runs cost ~$0)
make eval         # scorecard on golden meetings; fails if tallies imperfect or recall < 90%
make cost-report  # spend by pipeline stage
```

Stages individually: `make download identify extract-text segment
extract-structured load-db`. Extraction supports `--sync` (no Batch API) and
`--only <meeting_id>` via `uv run python -m cb1.cli`.

## The tiers (cost asymmetry by design)

1. **Text (free):** pymupdf text layer; page-1 regex resolves most meeting dates.
2. **Vision (Haiku):** transcription of scanned pages only where the *body* is
   scanned — progressive front OCR stops when the body ends, so 40-page
   attachment runs are never transcribed.
3. **Extraction (Haiku, Batch API):** one structured call per meeting over the
   segmented minutes body; pydantic-validated with one retry-with-feedback.
4. **Synthesis (frontier):** not in this repo — only ever sees the final dataset.

## Query it

```sql
-- every contested vote since 2016 by topic
SELECT m.date, v.topic_category, v.motion_text, v.yes, v.no, v.abstain
FROM votes v JOIN meetings m USING (meeting_id)
WHERE v.no > 0 ORDER BY m.date;
```

Tables: `meetings`, `licenses`, `votes`, `speakers`, `incidents`, `cannabis`
(+ parquet exports next to `data/db/cb1.duckdb`).

Vote-data conventions:
- **Voice votes** ("unanimously carried", no numeric tally in the minutes)
  are stored as `yes=0, no=0`; filter tally analyses with `yes + no > 0`.
- A vote can be `failed` with `yes > no`: board recommendations require a
  majority of the appointed board, not of members voting.

## Golden labeling workflow

```bash
uv run python -m cb1.cli eval --draft cb1-2016-01-12   # pipeline draft
# hand-correct eval/golden/cb1-2016-01-12.draft.json, then rename to .json
make eval
```

Raw model outputs cache to `eval/cache/` keyed by prompt version — re-running
eval after a prompt change re-extracts only what changed; unchanged prompts
are free and diffable.
