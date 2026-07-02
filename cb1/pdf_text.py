"""Per-page text extraction + density scoring, cached in data/interim/text.

Cache key is sha256 of the file, so re-runs are free and a re-uploaded
(changed) PDF re-extracts automatically.
"""

import json

import fitz  # pymupdf

from cb1 import config


def page_texts(pdf_path, sha256: str) -> list[str]:
    """Text of every page (text layer only — no OCR). Cached."""
    cache = config.INTERIM_DIR / "text" / f"{sha256}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    with fitz.open(pdf_path) as doc:
        texts = [page.get_text() for page in doc]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(texts))
    return texts


def is_low_density(text: str) -> bool:
    """Pages under the char threshold get flagged for vision OCR."""
    return len(text.strip()) < config.MIN_TEXT_DENSITY_CHARS


def page_count(pdf_path) -> int:
    with fitz.open(pdf_path) as doc:
        return len(doc)
