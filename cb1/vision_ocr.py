"""Haiku vision transcription of scanned pages, cached per (sha, page).

Progressive front OCR: scan-era files (and part-N fragments that open on
scans) are OCR'd from page 1 forward, re-classifying as we go, and stop
after 3 consecutive non-body pages — so we never pay to transcribe a
40-page attachment run just to learn it's an attachment run.
"""

from cb1 import config
from cb1.anthropic_client import image_block
from cb1.pdf_text import page_texts
from cb1.rasterize import page_jpeg
from cb1.segment import classify_page

OCR_PROMPT = """Transcribe this scanned page of a NYC community board meeting minutes document.

Rules:
- Output ONLY the transcribed text, no commentary.
- Preserve the reading order and paragraph breaks.
- For roll-call vote sheets or tables, transcribe row by row (name then marks/values).
- Transcribe handwritten text as best you can; mark illegible words as [illegible].
- If the page is blank or contains no text, output exactly: [no text]"""

STOP_AFTER_NON_BODY = 3
FRONT_OCR_PAGE_CAP = 40


def run_extract_text(client) -> None:
    """Stage runner: progressive front OCR for every scan-front file."""
    import json

    from cb1.download import load_manifest
    from cb1.segment import needs_ocr_first, segment_file

    manifest = load_manifest()
    meetings = json.loads((config.DATA_DIR / "meetings.json").read_text())["meetings"]
    in_meetings = {
        f["sha256"] for m in meetings.values() for f in m["files"]
    }
    flagged = []
    for href, e in sorted(manifest.items()):
        if e["sha256"] not in in_meetings:
            continue  # unresolved files wait for manual mapping
        texts = page_texts(config.RAW_DIR / e["local"], e["sha256"])
        if needs_ocr_first(texts):
            flagged.append(e)
    print(f"extract-text: {len(flagged)} scan-front files to OCR")
    for e in flagged:
        n = progressive_front_ocr(config.RAW_DIR / e["local"], e["sha256"], client)
        seg = segment_file(config.RAW_DIR / e["local"], e["sha256"])
        print(f"  {e['local']}: {n} pages OCR'd, {len(seg['body_pages'])} body pages")


def ocr_page(pdf_path, sha256: str, page_no: int, client) -> str:
    cache = config.INTERIM_DIR / "ocr" / f"{sha256}-p{page_no:03d}.txt"
    if cache.exists():
        return cache.read_text()
    text = client.message(
        stage="vision_ocr",
        messages=[
            {
                "role": "user",
                "content": [
                    image_block(page_jpeg(pdf_path, sha256, page_no)),
                    {"type": "text", "text": OCR_PROMPT},
                ],
            }
        ],
        max_tokens=3000,
    )
    if text.strip() == "[no text]":
        text = ""
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text)
    return text


def progressive_front_ocr(pdf_path, sha256: str, client) -> int:
    """OCR textless pages from the front until the body has clearly ended.

    Returns the number of pages OCR'd. Transcripts land in the interim OCR
    cache, which segment_file automatically overlays.
    """
    texts = page_texts(pdf_path, sha256)
    ocrd = 0
    consecutive_non_body = 0
    for i, t in enumerate(texts):
        if i >= FRONT_OCR_PAGE_CAP or consecutive_non_body >= STOP_AFTER_NON_BODY:
            break
        page_text = t
        if len(t.strip()) < 20:
            page_text = ocr_page(pdf_path, sha256, i, client)
            ocrd += 1
        label, _ = classify_page(page_text)
        if label in ("body", "vote_sheet"):
            consecutive_non_body = 0
        else:
            consecutive_non_body += 1
    return ocrd
