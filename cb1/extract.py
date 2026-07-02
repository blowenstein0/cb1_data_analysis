"""Per-meeting structured extraction: minutes-body text -> schema JSON.

One call per meeting (chunked only if enormous), low temperature, cached
system prompt. Output validated by pydantic with ONE retry that feeds the
validation error back. Batch API used for the bulk pass (50% off);
validation-failure retries run synchronously afterwards.
"""

import json
import re

from pydantic import ValidationError

from cb1 import config
from cb1.models import (
    ExtractionMeta,
    LLMExtraction,
    MeetingExtraction,
    format_validation_error,
)
from cb1.pdf_text import page_texts
from cb1.segment import segment_file

MAX_BODY_CHARS = 350_000  # ~90k tokens; chunk above this (Haiku ctx is 200k)

SYSTEM_PROMPT = f"""You are a meticulous civic-records extraction engine. You extract structured data from Brooklyn Community Board 1 (Williamsburg/Greenpoint) meeting minutes.

You will receive the minutes body text of ONE meeting (attachments already removed), with page markers. Return ONLY a JSON object conforming to this schema — no prose, no markdown fences:

{json.dumps(LLMExtraction.model_json_schema(), indent=1)}

Field-by-field guidance:
- meeting: use the meeting_id, date, and meeting_type given in the input header verbatim. location_or_platform: street address or remote platform (e.g. "Zoom", "WebEx"). attendance_count: members answering the FIRST roll call. quorum_noted: true only if quorum is explicitly mentioned. chair: who chaired this meeting.
- liquor_licenses: every SLA/liquor item (agenda lists AND narrative). application_type: new|renewal|alteration|corporate_change|transfer|other. Deduplicate: one record per applicant+address per meeting, merging agenda and narrative detail. features: only those explicitly mentioned (e.g. sidewalk_cafe, rooftop, patron_dancing, live_music, third_party_promoters, security_personnel, outdoor_seating, backyard).
- votes: EVERY motion with a recorded tally. yes/no/abstain/recusal as integers (missing category = 0). "unanimous" language with N members present means yes=N if N is stated. outcome: passed|failed. conditions: stipulations attached to the motion. Vote tallies are the analytical core — transcribe the numbers EXACTLY as written; never infer or arithmetic-correct them.
- public_speakers: individuals speaking in the public session/hearing, their affiliation if stated, topic, and position (for|against|neutral|unclear).
- traffic_incidents: any mention of a traffic crash/fatality/injury in the district (victim name if named, location, severity).
- cannabis_licenses: cannabis/dispensary applications (CAURD etc.).
- source_snippet: for EVERY record, a verbatim quote (<=300 chars) from the input text that supports the record. Copy exactly, including OCR errors.

If a section yields nothing, use an empty list. Never invent records."""


def build_meeting_text(meeting: dict) -> tuple[str, dict]:
    """Concatenate body-page text across the meeting's parts, page-tagged."""
    chunks = []
    stats = {"pages_body": 0, "pages_dropped": 0, "ocr_pages": 0}
    for f in meeting["files"]:
        path = config.RAW_DIR / f["local"]
        seg = segment_file(path, f["sha256"])
        texts = page_texts(path, f["sha256"])
        ocr_dir = config.INTERIM_DIR / "ocr"
        for i in seg["body_pages"]:
            text = texts[i]
            ocr_file = ocr_dir / f"{f['sha256']}-p{i:03d}.txt"
            if len(text.strip()) < 20 and ocr_file.exists():
                text = ocr_file.read_text()
                stats["ocr_pages"] += 1
            chunks.append(f"=== {f['local']} page {i + 1} ===\n{text.strip()}")
        stats["pages_body"] += len(seg["body_pages"])
        stats["pages_dropped"] += len(seg["pages"]) - len(seg["body_pages"])
    return "\n\n".join(chunks), stats


def build_user_prompt(meeting: dict, body_text: str) -> str:
    return (
        f"meeting_id: {meeting['meeting_id']}\n"
        f"date: {meeting['date']}\n"
        f"meeting_type: {meeting['meeting_type']}\n\n"
        f"MINUTES BODY TEXT:\n\n{body_text}"
    )


def strip_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(json)?\s*", "", raw)
    return re.sub(r"\s*```$", "", raw)


def parse_llm_extraction(raw: str) -> LLMExtraction:
    return LLMExtraction.model_validate_json(strip_fences(raw))


def system_blocks() -> list[dict]:
    """System prompt as a cacheable block (stable across all 110 meetings)."""
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def extract_meeting_sync(meeting: dict, client) -> MeetingExtraction:
    """Synchronous extract + validate, one retry with error feedback."""
    body_text, stats = build_meeting_text(meeting)
    if len(body_text) > MAX_BODY_CHARS:
        body_text = body_text[:MAX_BODY_CHARS]
        stats["truncated"] = True
    user = build_user_prompt(meeting, body_text)

    raw = client.message(
        stage="extract",
        system=system_blocks(),
        messages=[{"role": "user", "content": user}],
        max_tokens=16000,
        meeting=meeting["meeting_id"],
    )
    try:
        llm = parse_llm_extraction(raw)
    except ValidationError as e:
        retry_msg = format_validation_error(raw, e)
        raw2 = client.message(
            stage="extract_retry",
            system=system_blocks(),
            messages=[
                {"role": "user", "content": user},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": retry_msg},
            ],
            max_tokens=16000,
            meeting=meeting["meeting_id"],
        )
        llm = parse_llm_extraction(raw2)  # second failure raises: surfaced, not hidden

    return finalize(meeting, llm, stats)


def text_source_for(meeting: dict, stats: dict) -> str:
    if stats["ocr_pages"] and stats["ocr_pages"] >= stats["pages_body"]:
        return "vision_ocr"
    if stats["ocr_pages"]:
        return "mixed"
    year = int(meeting["date"][:4])
    return "embedded_ocr" if year < 2022 else "native"


def finalize(meeting: dict, llm: LLMExtraction, stats: dict) -> MeetingExtraction:
    """Attach pipeline-known metadata; pin identity fields to the manifest."""
    warnings = list(meeting.get("warnings", []))
    if llm.meeting.date != meeting["date"]:
        warnings.append(f"model returned date {llm.meeting.date}; pinned to manifest")
    m = llm.meeting.model_copy(
        update={
            "meeting_id": meeting["meeting_id"],
            "date": meeting["date"],
            "meeting_type": meeting["meeting_type"],
            "date_source": meeting.get("date_source", "content"),
            "date_confidence": meeting.get("date_confidence", 1.0),
            "is_revised": meeting.get("is_revised", False),
            "source_files": [f["local"] for f in meeting["files"]],
        }
    )
    if stats.get("truncated"):
        warnings.append("body text truncated to fit context")
    meta = ExtractionMeta(
        model=config.MODEL,
        text_source=text_source_for(meeting, stats),
        pages_minutes_body=stats["pages_body"],
        pages_attachments_dropped=stats["pages_dropped"],
        input_tokens=0,  # filled by the caller from API usage
        output_tokens=0,
        cost_usd=0.0,
        schema_version=config.SCHEMA_VERSION,
        prompt_version=config.PROMPT_VERSION,
        warnings=warnings,
    )
    return MeetingExtraction(
        meeting=m,
        liquor_licenses=llm.liquor_licenses,
        votes=llm.votes,
        public_speakers=llm.public_speakers,
        traffic_incidents=llm.traffic_incidents,
        cannabis_licenses=llm.cannabis_licenses,
        extraction_meta=meta,
    )


def output_path(meeting_id: str):
    return config.EXTRACTED_DIR / f"{meeting_id}.json"


def already_extracted(meeting_id: str) -> bool:
    p = output_path(meeting_id)
    if not p.exists():
        return False
    data = json.loads(p.read_text())
    return data.get("extraction_meta", {}).get("prompt_version") == config.PROMPT_VERSION


def save(extraction: MeetingExtraction, usage: dict | None = None) -> None:
    if usage:
        extraction.extraction_meta.input_tokens += usage.get("input_tokens", 0)
        extraction.extraction_meta.output_tokens += usage.get("output_tokens", 0)
        extraction.extraction_meta.cost_usd = round(
            extraction.extraction_meta.cost_usd + usage.get("cost_usd", 0.0), 6
        )
    config.EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    output_path(extraction.meeting.meeting_id).write_text(
        extraction.model_dump_json(indent=2)
    )


def batch_request(meeting: dict) -> dict:
    body_text, _ = build_meeting_text(meeting)
    return {
        "custom_id": meeting["meeting_id"],
        "params": {
            "model": config.MODEL,
            "max_tokens": 16000,
            "temperature": 0.0,
            "system": system_blocks(),
            "messages": [
                {"role": "user", "content": build_user_prompt(meeting, body_text[:MAX_BODY_CHARS])}
            ],
        },
    }


def run_extract_structured(client, sync: bool = False, only: list[str] | None = None) -> None:
    """Stage runner. Batch by default; --sync for dev/eval single meetings."""
    meetings = json.loads((config.DATA_DIR / "meetings.json").read_text())["meetings"]
    todo = [
        m for mid, m in sorted(meetings.items())
        if not already_extracted(mid) and (only is None or mid in only)
    ]
    print(f"extract-structured: {len(todo)} meetings to extract "
          f"({len(meetings) - len(todo)} cached)")
    if not todo:
        return

    if sync:
        for m in todo:
            ex = extract_meeting_sync(m, client)
            save(ex, client.last_usage)
            print(f"  {m['meeting_id']}: {len(ex.votes)} votes, "
                  f"{len(ex.liquor_licenses)} licenses")
        return

    results = client.batch("extract", [batch_request(m) for m in todo])
    for m in todo:
        mid = m["meeting_id"]
        r = results.get(mid, {"text": None, "error": "missing from batch results"})
        if r["text"] is None:
            print(f"  {mid}: batch error ({r['error']}), retrying sync")
            ex = extract_meeting_sync(m, client)
            save(ex, client.last_usage)
            continue
        _, stats = build_meeting_text(m)  # cached, cheap
        try:
            llm = parse_llm_extraction(r["text"])
        except ValidationError as e:
            print(f"  {mid}: validation failed, sync retry with feedback")
            ex = _sync_retry(m, r["text"], e, client)
            save(ex, {
                k: r["usage"].get(k, 0) + client.last_usage.get(k, 0)
                for k in ("input_tokens", "output_tokens", "cost_usd")
            })
            continue
        save(finalize(m, llm, stats), r["usage"])
    print(f"extract-structured: done, outputs in {config.EXTRACTED_DIR}")


def _sync_retry(meeting: dict, raw: str, error: ValidationError, client) -> MeetingExtraction:
    body_text, stats = build_meeting_text(meeting)
    user = build_user_prompt(meeting, body_text[:MAX_BODY_CHARS])
    raw2 = client.message(
        stage="extract_retry",
        system=system_blocks(),
        messages=[
            {"role": "user", "content": user},
            {"role": "assistant", "content": raw},
            {"role": "user", "content": format_validation_error(raw, error)},
        ],
        max_tokens=16000,
        meeting=meeting["meeting_id"],
    )
    return finalize(meeting, parse_llm_extraction(raw2), stats)
