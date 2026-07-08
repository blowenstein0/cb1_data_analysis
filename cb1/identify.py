"""Derive each file's canonical meeting date + type from page-1 CONTENT.

Filename dates are unreliable (10 formats, undated fragments), so content
is the source of truth. Tiering: free regex on the text layer first;
Haiku vision only for files whose page 1 is a scan (2016-2018 era).

Output: per-file cache in data/interim/identify/, plus data/meetings.json
mapping meeting_id -> ordered source files (the canonical grouping every
later stage consumes) and data/unresolved.json for anything unplaceable.
"""

import json
import re
from datetime import date

from cb1 import config
from cb1.download import load_manifest
from cb1.grouping import MONTHS, FileRef, parse_href
from cb1.pdf_text import is_low_density, page_texts
from cb1.rasterize import page_jpeg

MONTH_ALT = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december"
)
# "TUESDAY, SEPTEMBER 12, 2023" / "June 8 2021" — first date in the header
# (?!\d) rejects five-digit typo years: "JANUARY 11, 20211" (real, in the
# Jan 2022 minutes) must not parse as 2021 — the filename date is right there.
CONTENT_DATE_RE = re.compile(
    rf"({MONTH_ALT})\s+(\d{{1,2}})\s*,?\s*(\d{{4}})(?!\d)", re.IGNORECASE
)
NUMERIC_CONTENT_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")

VISION_IDENTIFY_PROMPT = """This image is page 1 of a NYC community board meeting minutes document.

Return ONLY a JSON object, no other text:
{"date": "YYYY-MM-DD or null if no meeting date is visible",
 "meeting_type": "combined|public_hearing|special|committee|other"}

meeting_type guide: "combined" = combined public hearing and board meeting;
"public_hearing" = standalone public hearing; "special" = special meeting;
"committee" = a single committee's meeting/hearing; otherwise "other".
The meeting date is usually in the header/title area."""


TITLE_ANCHOR_RE = re.compile(
    r"combined public hearing|board meeting|public hearing|minutes of", re.IGNORECASE
)


def identify_from_text(page1: str) -> tuple[date | None, str | None]:
    """(meeting_date, meeting_type) from page-1 text. Free, no API.

    Letterheads carry a transmittal date BEFORE the document title (seen in
    the wild: "October 28, 2024 COMBINED PUBLIC HEARING ... OCTOBER 8, 2024").
    So when a title phrase is present, prefer the first date at or after it;
    only fall back to the first date anywhere.
    """
    head = " ".join(page1.split())[:2000]  # collapse OCR line breaks
    anchor = TITLE_ANCHOR_RE.search(head)
    start = anchor.start() if anchor else 0

    d = _first_date(head, start) or _first_date(head, 0)

    low = head[:1200].lower()
    mtype = _meeting_type(low)
    return d, mtype


def _first_date(text: str, start: int) -> date | None:
    m = CONTENT_DATE_RE.search(text, start)
    if m:
        try:
            return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            pass
    m = NUMERIC_CONTENT_DATE_RE.search(text, start)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    return None


def _meeting_type(low: str) -> str | None:
    mtype = None
    if "special" in low:
        mtype = "special"
    elif "committee" in low:
        mtype = "committee"
    elif "combined" in low:
        mtype = "combined"
    elif "public hearing" in low:
        mtype = "public_hearing"
    elif "board meeting" in low:
        mtype = "other"
    return mtype


def identify_file(path, sha256: str, client=None) -> dict:
    """Identify one file; cached by sha. Vision fallback needs a Client."""
    cache = config.INTERIM_DIR / "identify" / f"{sha256}.json"
    if cache.exists():
        cached = json.loads(cache.read_text())
        # A dateless text-only attempt is retried once vision is available.
        if cached.get("date") or cached.get("method") == "vision" or client is None:
            return cached

    texts = page_texts(path, sha256)
    page1 = texts[0] if texts else ""
    d, mtype = identify_from_text(page1)
    result: dict = {
        "date": d.isoformat() if d else None,
        "meeting_type": mtype,
        "method": "text",
        "page1_low_density": is_low_density(page1),
    }

    if d is None and client is not None:
        raw = client.message(
            stage="identify",
            messages=[
                {
                    "role": "user",
                    "content": [
                        _image(path, sha256),
                        {"type": "text", "text": VISION_IDENTIFY_PROMPT},
                    ],
                }
            ],
            max_tokens=200,
        )
        try:
            parsed = json.loads(_strip_fences(raw))
            result["date"] = parsed.get("date")
            result["meeting_type"] = parsed.get("meeting_type") or mtype
            result["method"] = "vision"
        except (json.JSONDecodeError, AttributeError):
            result["warnings"] = [f"vision identify returned unparseable: {raw[:200]}"]

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result))
    return result


def _image(path, sha256: str) -> dict:
    from cb1.anthropic_client import image_block

    return image_block(page_jpeg(path, sha256, 0))


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(json)?\s*", "", raw)
    return re.sub(r"\s*```$", "", raw)


def resolve_file(ref: FileRef, content: dict) -> dict:
    """Reconcile content-derived and filename-derived date/type for one file."""
    content_date = content.get("date")
    fname_date = ref.date_guess.isoformat() if ref.date_guess else None
    warnings: list[str] = []

    if content_date and fname_date and content_date != fname_date:
        warnings.append(
            f"date mismatch: content={content_date} filename={fname_date}; using content"
        )
    final_date = content_date or fname_date
    date_source = "content" if content_date else "filename"
    if final_date is None and ref.year_month_guess:
        warnings.append("only year-month known from filename; day unresolved")

    if ref.doc_type_hint != "unknown":
        mtype = ref.doc_type_hint  # filename hints are precise where present
    else:
        mtype = content.get("meeting_type") or "combined"

    confidence = 1.0 if (content_date and fname_date and content_date == fname_date) else (
        0.9 if content_date and content["method"] == "text" else
        0.8 if content_date else
        0.5 if fname_date else 0.0
    )
    return {
        "date": final_date,
        "date_source": date_source,
        "date_confidence": confidence,
        "meeting_type": mtype,
        "warnings": warnings,
    }


def run_identify(client=None) -> dict:
    """Identify every downloaded file and write the canonical meetings manifest."""
    config.ensure_dirs()
    manifest = load_manifest()
    if not manifest:
        raise SystemExit("no downloads found — run the download stage first")

    overrides = {}
    if (config.DATA_DIR / "overrides.json").exists():
        overrides = json.loads((config.DATA_DIR / "overrides.json").read_text())

    meetings: dict[str, dict] = {}
    unresolved: list[dict] = []
    for href, entry in sorted(manifest.items()):
        ref = parse_href(href)
        path = config.RAW_DIR / entry["local"]
        if entry["local"] in overrides:
            ov = overrides[entry["local"]]
            resolved = {
                "date": ov["date"],
                "date_source": "override",
                "date_confidence": 1.0,
                "meeting_type": ref.doc_type_hint if ref.doc_type_hint != "unknown" else "combined",
                "warnings": [f"date overridden: {ov['reason'][:120]}"],
            }
        elif ref.part_no is not None and ref.part_no >= 2 and ref.date_guess:
            # Parts >= 2 start mid-document (no header); the filename date
            # groups them with their part 1, whose content anchors the group.
            resolved = {
                "date": ref.date_guess.isoformat(),
                "date_source": "filename",
                "date_confidence": 0.9,
                "meeting_type": ref.doc_type_hint if ref.doc_type_hint != "unknown" else "combined",
                "warnings": [],
            }
        elif ref.part_no is not None and ref.part_no >= 2:
            # Undated part >= 2 fragment: its page 1 is mid-document content,
            # so any date found there (text OR vision) is a letter/attachment
            # date, not the meeting date. Sibling-stem inheritance below is
            # the only trustworthy placement.
            unresolved.append({
                "href": href, "local": entry["local"], "sha256": entry["sha256"],
                "part_no": ref.part_no, "is_revised": ref.is_revised,
                "reason": "undated fragment; awaiting sibling-stem inheritance",
            })
            continue
        else:
            content = identify_file(path, entry["sha256"], client=client)
            resolved = resolve_file(ref, content)
        file_info = {
            "href": href,
            "local": entry["local"],
            "sha256": entry["sha256"],
            "part_no": ref.part_no,
            "is_revised": ref.is_revised,
        }
        if resolved["date"] is None:
            unresolved.append({**file_info, "reason": "no date from content or filename"})
            continue
        mid = f"cb1-{resolved['date']}"
        m = meetings.setdefault(
            mid,
            {
                "meeting_id": mid,
                "date": resolved["date"],
                "date_source": resolved["date_source"],
                "date_confidence": resolved["date_confidence"],
                "meeting_type": resolved["meeting_type"],
                "is_revised": False,
                "files": [],
                "warnings": [],
            },
        )
        m["files"].append(file_info)
        m["is_revised"] = m["is_revised"] or ref.is_revised
        m["warnings"].extend(resolved["warnings"])
        if resolved["meeting_type"] != m["meeting_type"] and resolved["meeting_type"] != "combined":
            m["meeting_type"] = resolved["meeting_type"]

    # Undated fragments inherit the date of a resolved sibling that shares
    # their filename stem (e.g. Pages-from-Minutes-2..5 follow -1's content
    # date): uploaded-together parts stay together.
    still_unresolved = []
    for u in unresolved:
        stem = re.sub(r"[-_]\d{1,2}\.pdf$", "", u["local"], flags=re.IGNORECASE)
        home = next(
            (
                m for m in meetings.values()
                if any(
                    f["local"].lower().startswith(stem.lower()) and f["part_no"] is not None
                    for f in m["files"]
                )
            ),
            None,
        )
        if home is not None and stem:
            u.pop("reason", None)
            home["files"].append(u)
            home["warnings"].append(
                f"{u['local']}: date inherited from sibling with same stem"
            )
        else:
            still_unresolved.append(u)
    unresolved = still_unresolved

    for m in meetings.values():
        # revised-over-plain per part, then stitch order
        by_part: dict[int | None, dict] = {}
        for f in m["files"]:
            cur = by_part.get(f["part_no"])
            if cur is None or (f["is_revised"] and not cur["is_revised"]):
                by_part[f["part_no"]] = f
            elif not f["is_revised"] and cur["is_revised"]:
                pass
            elif f is not cur:
                # A same-date, same-part collision usually means content
                # identify misread one file. NEVER drop silently: surface it.
                m["warnings"].append(f"duplicate part={f['part_no']}: {f['local']}")
                print(
                    f"WARNING: {f['local']} collides with {cur['local']} at "
                    f"{m['date']} and was DROPPED — check date, consider an override"
                )
        m["files"] = sorted(
            by_part.values(), key=lambda f: (f["part_no"] is None, f["part_no"] or 0)
        )

    out = {"meetings": dict(sorted(meetings.items())), "unresolved": unresolved}
    (config.DATA_DIR / "meetings.json").write_text(json.dumps(out, indent=2))
    if unresolved:
        config.UNRESOLVED_PATH.write_text(json.dumps(unresolved, indent=2))
    print(
        f"identify: {len(meetings)} meetings, {len(unresolved)} unresolved, "
        f"{sum(1 for m in meetings.values() if len(m['files']) > 1)} multi-part"
    )
    return out
