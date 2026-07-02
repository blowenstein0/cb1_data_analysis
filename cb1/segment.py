"""Page-level classification: which pages feed extraction, which are dropped.

Observed document anatomy (from real corpus inspection):
  - The minutes "body" is one or more letterhead-anchored sections (board
    meeting minutes, public hearing section/agenda), NOT a single prefix.
  - Committee reports appear as typed letterhead attachments ("report as
    written") and hold substance missing from the narrative (e.g. cannabis
    recommendations) -> classified body and KEPT.
  - Roll-call vote sheets are scans, but 2022+ ones carry embedded text
    ("YES NO ABS REC X X X") -> own label, excluded from extraction text.
  - Long textless runs in text-era files are scanned attachments; only
    2016-18 pure-scan files need vision OCR before segmentation.

Labels: body | vote_sheet | attachment | blank. Pages the heuristics can't
call confidently inherit their neighborhood (sections are contiguous runs);
anything still ambiguous is flagged for the vision fallback.
"""

import json
import re

from cb1 import config
from cb1.pdf_text import page_texts

BODY_KEYWORDS = (
    "motion", "seconded", "vote was", "adjourn", "roll call", "committee",
    "chairperson", "district manager", "old business", "new business",
    "public session", "minutes", "recommendation", "agenda", "presentation",
    "moment of silence", "quorum",
)
ATTACHMENT_KEYWORDS = (
    "questionnaire", "sincerely", "dear ", "respectfully submitted",
    "www.", "@gmail", "@yahoo", "press release", "article",
)
LETTERHEAD_RE = re.compile(r"435\s+graham\s+avenue", re.IGNORECASE)
TITLE_RE = re.compile(
    r"combined\s+public\s+hearing|minutes\s+of\s+the|board\s+meeting|public\s+hearing",
    re.IGNORECASE,
)
# column-major text extraction turns the sheet header into repeated runs:
# "ROLL ROLL ROLL CALL CALL CALL 1ST 2ND 3RD..."
VOTE_SHEET_RE = re.compile(
    r"yes\s+no\s+abs\s+rec|1st\s+2nd\s+3rd", re.IGNORECASE
)
XRUN_RE = re.compile(r"(?:\bx\s+){5,}", re.IGNORECASE)


def classify_page(text: str) -> tuple[str, float]:
    """(label, confidence) for one page from its text alone."""
    t = " ".join(text.split())
    low = t.lower()

    if len(t) < 20:
        return "blank", 1.0
    if VOTE_SHEET_RE.search(low) or XRUN_RE.search(low):
        return "vote_sheet", 0.95

    head = low[:700]
    if LETTERHEAD_RE.search(head) and TITLE_RE.search(head):
        return "body", 0.95  # letterhead-anchored section start

    body_hits = sum(1 for k in BODY_KEYWORDS if k in low)
    attach_hits = sum(1 for k in ATTACHMENT_KEYWORDS if k in low)
    dense = len(t) >= 800

    if body_hits >= 3 and body_hits > attach_hits:
        return "body", 0.85 if (dense or body_hits >= 5) else 0.7
    if attach_hits > body_hits:
        return "attachment", 0.8
    if not dense and body_hits < 2:
        return "attachment", 0.6  # sparse non-narrative page (slide, flyer)
    if body_hits >= 1 and dense:
        return "body", 0.55
    return "attachment", 0.4


def classify_pages(texts: list[str]) -> list[dict]:
    """Per-page labels with contiguity smoothing.

    Sections are runs, so a low-confidence page sandwiched between two
    same-label pages takes that label; leading/trailing low-confidence
    pages inherit their confident neighbor.
    """
    raw = [classify_page(t) for t in texts]
    labels = [{"label": lab, "confidence": conf} for lab, conf in raw]

    # blank pages act as section separators; low-confidence non-blank pages
    # get smoothed toward their confident neighbors
    for i, entry in enumerate(labels):
        if entry["confidence"] >= 0.8 or entry["label"] == "blank":
            continue
        prev_l = next(
            (labels[j]["label"] for j in range(i - 1, -1, -1) if labels[j]["confidence"] >= 0.8),
            None,
        )
        next_l = next(
            (labels[j]["label"] for j in range(i + 1, len(labels)) if labels[j]["confidence"] >= 0.8),
            None,
        )
        if prev_l is not None and prev_l == next_l and prev_l != "blank":
            entry["label"] = prev_l
            entry["confidence"] = 0.75
            entry["smoothed"] = True

    return labels


def needs_ocr_first(texts: list[str]) -> bool:
    """True when the minutes BODY itself is a textless scan.

    The body always sits at the front of the file, so a textless front
    (first 3 pages) means vision OCR must run before segmentation — even if
    later attachment pages happen to carry an embedded OCR layer (seen in
    land_use_committee_held_ph_6_6_17: scanned body, OCR'd attachments).
    Textless pages in the middle/tail of a texted file stay classified as
    scanned attachments and are never OCR'd.
    """
    front = texts[:3]
    if front and all(len(t.strip()) < 20 for t in front):
        return True
    textless = sum(1 for t in texts if len(t.strip()) < 20)
    return textless / max(len(texts), 1) > 0.8


def segment_file(pdf_path, sha256: str) -> dict:
    """Classify every page of one file. Cached by sha."""
    cache = config.INTERIM_DIR / "segments" / f"{sha256}.json"
    ocr_dir = config.INTERIM_DIR / "ocr"

    texts = page_texts(pdf_path, sha256)
    # overlay vision-OCR transcripts where the text layer was empty
    ocr_pages = 0
    merged = []
    for i, t in enumerate(texts):
        ocr_file = ocr_dir / f"{sha256}-p{i:03d}.txt"
        if len(t.strip()) < 20 and ocr_file.exists():
            merged.append(ocr_file.read_text())
            ocr_pages += 1
        else:
            merged.append(t)

    if cache.exists():
        cached = json.loads(cache.read_text())
        if cached.get("ocr_pages") == ocr_pages:  # re-segment if new OCR landed
            return cached

    result = {
        "needs_ocr_first": needs_ocr_first(texts) and ocr_pages == 0,
        "ocr_pages": ocr_pages,
        "pages": classify_pages(merged),
    }
    result["body_pages"] = [
        i for i, p in enumerate(result["pages"]) if p["label"] == "body"
    ]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result))
    return result
