# PLAN — Brooklyn CB1 Minutes → Structured Dataset Pipeline

**Status:** awaiting approval. No pipeline code will be written until this plan is approved.

Goal: turn ~110 Brooklyn Community Board 1 meeting-minutes PDFs (Jan 2016 – Apr 2026) into a clean, queryable structured dataset via a cost-tiered LLM pipeline, with a first-class eval harness proving extraction accuracy. Doubles as a portfolio piece for agentic-BI eval consulting, so the eval layer is a deliverable, not an afterthought.

---

## 0. Reconnaissance (already done — grounds the plan)

I scraped the live index (`https://www.nyc.gov/site/brooklyncb1/meetings/minutes.page`) and pulled the raw hrefs. Findings that shaped this plan:

- **138 raw PDF links → ~110 logical meetings.** The gap is multi-part splits and revised re-uploads.
- **The index requires a browser `User-Agent`.** The default fetcher gets `403`; `Mozilla/5.0…` gets `200`. The scraper must set a real UA.
- **Multi-part stitching is the hard problem.** Real cases in the corpus:
  - `Combined-...-05-13-25-Part-1.pdf` (plain) + `REVISED-...-05-13-25-Part-2.pdf` — one meeting, two parts, mixed revised/plain.
  - `10-21-25`: `REVISED-...-Part-1` + plain `Part-2/3/4`.
  - `05-12-26`: `REVISED-...-Part-1/2` + plain `Part-3/4/5`.
  - `04-14-26`: plain `Part-1/2` + plain `Part-3/4` (clean).
  - `Pages-from-Minutes-1..5.pdf` (2024): **no date in filename at all** — only page content can place them.
- **~10 filename date formats:** `jan2016`, `minutes-20221109`, `minutes-202111` (year-month only), `10-13-16`, `combined_..._2_15_17`, `..._292021_...` (MDYYYY no separators), `December-19-2023`, `September-12-2023`, `april_10_2018`, etc.
- **Non-combined docs mixed in:** special meetings (`Special-Full-Board-Minutes-6-12-23`, `Special-Meeting-Select-New-District-Manager-...`), standalone/limited public hearings (`Public-Hearing-Meeting-Minutes-01-20-26`, `Limited-Public-Hearing-Minutes-8-09-16`), and a committee hearing (`land_use_committee_held_ph_6_6_17_minutes`).
- **Directory is not a stable key.** 2026 meetings appear under both `/pdf/2026/` and `/pdf/meeting-minutes/`.

**Design consequence (the load-bearing decision):** filename-based dates and grouping are too unreliable to be authoritative. The pipeline derives each meeting's **canonical date from page-1 content** (cheap identify pass) and uses that as the grouping key; the filename date is only a hint and a cross-check. The 138-link scrape is saved as a test fixture (`tests/fixtures/index_hrefs.txt`) so the parsing/stitching logic is tested against the real mess.

---

## 1. Architecture overview

Six idempotent, resumable stages, each a CLI entrypoint. ~95% of tokens go through the cheap model (Haiku 4.5); the frontier model is **not** part of this build (synthesis is a later phase and only ever sees the distilled dataset).

```
download → identify → segment → extract-text → extract-structured → load-db
                                     │                    │
                                   (vision tier)      (eval harness runs against golden meetings)
```

- **download** — scrape index, resolve multi-part groups, download PDFs (content-hash manifest, never re-download).
- **identify** — cheap per-file page-1 read (text, or Haiku vision if page-1 is a scan) → canonical meeting date + meeting_type. This is what makes multi-part stitching reliable.
- **segment** — page-level classification: minutes body vs appended attachment. Heuristics first, Haiku vision fallback for ambiguous pages.
- **extract-text** — per-page text via pymupdf/pdfplumber; empty/low-density pages flagged for the vision tier (Haiku transcription at ~150 DPI).
- **extract-structured** — one structured-extraction call per meeting over the minutes-body text → schema-conforming JSON, validated by pydantic with one retry-with-error-feedback.
- **load-db** — load extracted JSON into DuckDB + parquet exports.

### Model / API decisions (grounded in the Anthropic API reference)

- **Model:** `claude-haiku-4-5` ($1/1M input, $5/1M output, 200K ctx, vision) for **all three** LLM tiers (identify, vision OCR, extraction), per the spec. No frontier model in this build.
- **Per-page rasterization, not native-PDF blocks.** We rasterize only *flagged* pages at ~150 DPI and send page images, rather than shipping whole PDFs as `document` blocks. Justification: (a) some files exceed 20 MB and the 100-page/32 MB request limits; (b) whole-PDF blocks would feed appended attachments straight into the model, which is exactly the pollution we're segmenting out; (c) per-page control lets us cache and cost-track at page granularity and reuse the same images for the segment classifier.
- **Batch API for the two bulk passes (vision OCR + extraction).** 50% cheaper, latency-tolerant, keyed by `custom_id`. Trade-off: results are async and unordered, and the validation-retry loop is awkward inside a batch. Resolution: run the bulk pass through Batch, then do **synchronous** retry-with-error-feedback only for the handful of pydantic-validation failures. `make all` submits the batch and polls; a `--sync` flag forces synchronous calls for a single meeting during development/eval.
- **Prompt caching** on the extraction system prompt + schema instructions (stable prefix), so 110 extraction calls reuse the cached instruction block. Volatile per-meeting text goes after the cache breakpoint.
- **Structured outputs** via pydantic (`messages.parse` in `--sync` mode; `output_config.format` json_schema in batch mode) so the model returns schema-valid JSON.

---

## 2. Module breakdown

```
cb1/
  __init__.py
  config.py            # env, paths, budget cap, model id, DPI, thresholds
  models.py            # pydantic models mirroring the schema (§4)
  costs.py             # append-only cost ledger (JSONL) + budget guardrail
  anthropic_client.py  # thin wrapper: retries/backoff, token+cost logging, cache, batch helpers
  scrape.py            # fetch index (real UA), extract hrefs
  grouping.py          # filename date/part parsing + multi-part → meeting grouping (PURE, tested)
  download.py          # sequential polite download, content-hash manifest
  identify.py          # page-1 → canonical date + meeting_type (text or vision)
  pdf_text.py          # per-page text extraction + density scoring (pymupdf/pdfplumber)
  rasterize.py         # page → 150 DPI PNG (pymupdf)
  segment.py           # page classification: minutes-body vs attachment (heuristics + vision)
  vision_ocr.py        # Haiku transcription of flagged page images
  extract.py           # per-meeting structured extraction + validate/retry
  db.py                # DuckDB load + parquet exports
  eval/
    matching.py        # fuzzy record matching + tally comparison (PURE, tested)
    scorecard.py       # precision/recall/field-accuracy/tally-exact metrics
    run.py             # runs golden meetings, prints scorecard, CI gate exit code
  cli.py               # subcommands: download identify segment extract-text
                       #              extract-structured eval load-db cost-report
tests/
  fixtures/index_hrefs.txt   # the real 138 hrefs (regression fixture)
  test_grouping.py           # date parsing + multi-part stitching against real names
  test_segment_heuristics.py
  test_models.py             # schema validation, retry-feedback formatting
  test_matching.py           # eval fuzzy matching + tally comparison
data/
  raw/           interim/     extracted/     db/
eval/
  golden/        # hand-labeled ground truth (3 meetings)
  cache/         # cached raw model outputs, keyed by (meeting, prompt_ver, model)
Makefile
pyproject.toml   # uv-managed, typed
PLAN.md  README.md  .env.example
```

**Stack:** Python 3.12, `uv` for env; `anthropic`, `pymupdf`, `pdfplumber`, `pydantic`, `duckdb`, `rapidfuzz`, `httpx`, `tenacity`, `pytest`.

---

## 3. Idempotency, cost control, resumability

- **Downloads:** `data/raw/manifest.json` maps `sha256 → {url, local_path, group_id}`. Present hash ⇒ skip. Re-running `download` twice costs $0.
- **Interim caches keyed by `filehash:page`:** extracted text (`data/interim/text/`), rasterized images (`data/interim/img/`), segment labels (`data/interim/segments/`). Present ⇒ skip.
- **Extraction outputs:** one JSON per meeting in `data/extracted/`. Present + matching `prompt_version` ⇒ skip.
- **Cost ledger:** every API call appends `{ts, stage, meeting, model, input_tokens, output_tokens, cached_tokens, cost_usd}` to `data/costs.jsonl`. `make cost-report` summarizes by stage.
- **Budget guardrail:** before every API call, sum the ledger; if cumulative ≥ cap (default **$75**, env-configurable) raise `BudgetExceeded` and hard-stop. Target full-run spend **< $50**.
- **Rate limits:** SDK auto-retries 429/5xx with backoff; we add `tenacity` around batch submit/poll and a small inter-request delay for the scraper (sequential, ~1 s, real UA).

---

## 4. Schema (refinements to the spec)

Keeping `source_snippet` traceability and `extraction_meta` cost tracking **non-negotiable**. Proposed additions (all backward-compatible with the spec):

**`meeting`** — add:
- `meeting_id: str` — stable key `cb1-YYYY-MM-DD` (from canonical content date).
- `meeting_type: "combined" | "public_hearing" | "special" | "committee" | "other"` — the corpus has all of these.
- `date_source: "content" | "filename"` and `date_confidence: float` — provenance for the canonical date.
- `is_revised: bool` — whether any source part was a REVISED upload.

**`votes[]`** — add `unanimous: bool` (convenience), keep exact tallies (`yes/no/abstain/recusal`) as the analytical core.

**`extraction_meta`** — add `schema_version`, `prompt_version`, `warnings: [str]` (e.g. "date mismatch: filename vs content", "attachment/body boundary ambiguous"). Keep `text_source`, page counts, tokens, `cost_usd`.

**Cross-entity:** every record keeps `source_snippet`; optionally add `page_ref: int` (page in minutes body) to speed eval triage. All other fields exactly as specified (liquor_licenses, public_speakers, traffic_incidents, cannabis_licenses).

Pydantic models mirror this 1:1 and are the validation gate on LLM output (one retry with the validation error fed back into the prompt).

---

## 5. Multi-part stitching algorithm (the crux)

1. Scrape 138 hrefs; parse each into `{raw_date_guess, part_no, is_revised, dir}` via `grouping.py` (pure, tested against the real fixture).
2. Download all; run **identify** (page-1 content date) on each file.
3. Group files by **canonical content date** (not filename). Within a group:
   - Order by `part_no` (missing part ⇒ treated as single-part).
   - When plain and REVISED exist for the **same `(date, part_no)`**, keep REVISED, drop plain. When they cover **different** part numbers (e.g. plain Part-1 + REVISED Part-2), **keep both** — this is the `05-13-25` case.
   - Set `is_revised = any(part.is_revised)`.
4. Files whose content date can't be resolved (e.g. `Pages-from-Minutes-1..5.pdf`) are grouped by content date once identify reads them; if still ambiguous, flagged in a `data/unresolved.json` report for manual mapping rather than silently guessed.
5. Concatenate parts (logical page order) into one meeting before segmentation.

---

## 6. Eval harness (first-class)

- **Golden set:** 3 meetings, one per era — a 2016 pure scan, a 2019 dirty-OCR, a 2023+ clean digital. Workflow: `make draft-golden MEETING=<id>` runs the pipeline to produce a draft extraction → I hand-correct the JSON in `eval/golden/<id>.json` → corrected file becomes ground truth.
- **Matching (`eval/matching.py`, pure/tested):**
  - Records matched by **fuzzy key** via `rapidfuzz` bipartite assignment: licenses on normalized `applicant_name + address`; speakers on `name + topic`; incidents on `location + victim`; votes on normalized `motion_text` (fallback: topic + order).
  - **Vote tallies compared exact** — `yes/no/abstain/recusal` must match to the integer.
- **Metrics (`scorecard.py`):** per-entity-type precision/recall (record-level), per-field accuracy on matched records, and vote-tally exact-match rate.
- **CI gate:** `make eval` runs extraction on the 3 golden meetings (reusing `eval/cache/` raw outputs when the prompt is unchanged) and prints a scorecard. **Exit non-zero if vote-tally exact-match < 100% or any entity recall < 90%.**
- **Regression:** raw model outputs cached under `eval/cache/<meeting>_<prompt_ver>_<model>.json` so re-running eval after a prompt tweak is cheap and diffable.

---

## 7. Storage & query layer

- `data/raw/` PDFs (+ manifest), `data/interim/` caches, `data/extracted/` JSON, `data/db/cb1.duckdb` + `data/db/*.parquet`.
- DuckDB tables: `meetings`, `licenses`, `votes`, `speakers`, `incidents`, `cannabis`, plus a `costs` view over the ledger.
- Success criterion #4 query works out of the box, e.g.:
  ```sql
  SELECT m.date, v.topic_category, v.motion_text, v.yes, v.no, v.abstain
  FROM votes v JOIN meetings m USING (meeting_id)
  WHERE v.no > 0 ORDER BY m.date;
  ```

---

## 8. Cost estimate (why this stays cheap)

Dominant cost is vision OCR on the 2016–2021 scans; extraction is small.

| Pass | Volume (est.) | Tokens | Haiku list price | With Batch −50% |
|---|---|---|---|---|
| identify (page-1) | ~120 files, many text | ~0.2M in / 0.05M out | ~$0.45 | ~$0.23 |
| segment (vision fallback) | ~150 ambiguous pages | ~0.3M in / 0.05M out | ~$0.55 | ~$0.28 |
| vision OCR | ~55 meetings × ~15 pages ≈ 825 imgs | ~1.7M in / 0.4M out | ~$3.7 | ~$1.9 |
| extraction | 110 meetings, cached prompt | ~1.1M in / 0.33M out | ~$2.75 | ~$1.4 |
| **Total** | | | **~$7.5** | **~$3.8** |

Comfortably under the **$50** target and the **$75** hard cap. Real numbers get logged to the ledger; `make cost-report` is the source of truth.

---

## 9. Build phases (each ends with a passing commit)

1. **Scaffold + models + cost ledger + config** — pydantic schema, budget guardrail, `.env.example`, Makefile skeleton. Tests: schema validation.
2. **Scrape + grouping** — index fetch, `grouping.py`, multi-part stitching. Tests: date parsing + stitching against the 138-href fixture. (No API cost.)
3. **Download + identify** — polite downloads, manifest, page-1 date/type. First API spend (tiny).
4. **Text + rasterize + segment** — per-page text/density, 150 DPI raster, page classifier. Tests: heuristics.
5. **Vision OCR + extraction** — Batch passes, validate/retry, prompt caching. Produces `data/extracted/`.
6. **Eval harness** — golden scaffolding, matching, scorecard, `make eval` CI gate. Tests: matching.
7. **load-db + `make all`** — DuckDB/parquet, end-to-end wiring, README with the sample queries.

---

## 10. Open questions (need your call before/around implementation)

1. **Non-combined docs** — ✅ RESOLVED: include them, tagged with `meeting_type` (`special` / `public_hearing` / `committee`) so they're filterable in SQL.
2. **Undated 2024 fragments** (`Pages-from-Minutes-1..5.pdf`): confirm the approach — resolve their meeting by **page-1 content date**, and if still unresolvable, park them in `data/unresolved.json` for a manual mapping rather than guessing. OK?
3. **Golden meeting picks:** any specific dates you want as the three era representatives, or should I choose (e.g. `jan2016` scan, a 2019 dirty-OCR combined, a clean 2023 combined)?
4. **Batch vs sync default:** default `make all` to the Batch API (cheaper, async up to ~1 h) with a `--sync` dev flag — agreed?
5. **Budget:** cap $75 / target <$50 as given — confirm, or set a tighter cap for the first full run?

---

Approve as-is, or tell me what to change, and I'll start with Phase 1.
