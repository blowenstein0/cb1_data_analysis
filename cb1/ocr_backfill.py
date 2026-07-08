"""Backfill vision OCR for ALL textless pages (the 'dark' attachments).

The main pipeline deliberately skipped attachment scans to keep extraction
cheap. This backfill makes them full-text searchable — resident letters,
written testimony, scanned reports — so archival analyses (letters over
time, mention counts) see the whole record. Cached per page; safe to kill
and rerun. Oldest meetings first (they're the darkest).

Run: uv run python -m cb1.ocr_backfill
"""

import json

from cb1 import config
from cb1.anthropic_client import Client
from cb1.pdf_text import page_texts
from cb1.vision_ocr import ocr_page


def main() -> None:
    client = Client()
    meetings = json.loads((config.DATA_DIR / "meetings.json").read_text())["meetings"]
    todo = []
    for mid, m in sorted(meetings.items(), key=lambda kv: kv[1]["date"]):
        for f in m["files"]:
            path = config.RAW_DIR / f["local"]
            for i, t in enumerate(page_texts(path, f["sha256"])):
                if len(t.strip()) < 20 and not (
                    config.INTERIM_DIR / "ocr" / f"{f['sha256']}-p{i:03d}.txt"
                ).exists():
                    todo.append((mid, path, f["sha256"], i))
    print(f"ocr-backfill: {len(todo)} dark pages to transcribe", flush=True)
    for n, (mid, path, sha, page_no) in enumerate(todo, 1):
        ocr_page(path, sha, page_no, client)
        if n % 50 == 0:
            print(f"  [{n}/{len(todo)}] through {mid} "
                  f"(${client.ledger.total_usd():.2f} total spend)", flush=True)
    print(f"ocr-backfill: done, total spend ${client.ledger.total_usd():.2f}", flush=True)


if __name__ == "__main__":
    main()
