# Brooklyn CB1 Minutes → Structured Dataset

Ten years (2016–2026) of Brooklyn Community Board 1 (Williamsburg/Greenpoint)
meeting-minutes PDFs, extracted into a queryable DuckDB dataset via a
cost-tiered LLM pipeline, with an eval harness proving extraction accuracy.
See [PLAN.md](PLAN.md) for architecture and design decisions.

## The story

The dataset was built for the blog post **[Two Parks, Two Vacant Lots, and
1,254 Votes](blog/williamsburg-waterfront.html)** (published at
bradlowenstein.com): does showing up to community board meetings actually do
anything? The narrative analysis behind it is
[analysis/does_showing_up_work.ipynb](analysis/does_showing_up_work.ipynb);
the wider notebook set in [analysis/](analysis/) covers the regression
models, the decade-long waterfront saga timeline, waterfront EDA, and an
entity graph of who speaks and writes in.

## Use the data without running anything

The extracted dataset ships in the repo (`data/db/*.parquet`, ~700 KB
total) — no pipeline run or LLM spend needed:

```python
import pandas as pd
votes = pd.read_parquet("data/db/votes.parquet")
```

Everything is extracted from CB1's publicly posted meeting minutes. Names in
the dataset (speakers, license applicants, letter writers) appear in that
public record; every row carries a verbatim `source_snippet` so any value
can be traced to its source page. Manual corrections are documented in
`data/overrides.json` (dates) and `data/vote_overrides.json` (votes missed
by extraction, recovered by hand with quotes).

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
