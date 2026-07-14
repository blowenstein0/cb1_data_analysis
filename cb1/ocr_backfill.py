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


if __name__ == "__main__" and __import__("sys").argv[-1] == "haiku":
    main()


# ---------------------------------------------------------------------------
# Free tier: tesseract. Validated against 59 Haiku transcripts of the same
# pages: median word recall 98%, 85%+ on 50/59. Adequate for searchability
# (mentions, letters); pages where tesseract fails land in an escalation
# list for an optional paid vision pass.

import subprocess
from concurrent.futures import ProcessPoolExecutor

from cb1.rasterize import page_jpeg

PROVENANCE = config.INTERIM_DIR / "ocr" / "_provenance.jsonl"
ESCALATE = config.INTERIM_DIR / "ocr" / "_escalate.jsonl"


def _tesseract_one(args):
    local, sha, page_no = args
    img = page_jpeg(config.RAW_DIR / local, sha, page_no)
    img_path = config.INTERIM_DIR / "img" / f"{sha}-p{page_no:03d}-{config.RASTER_DPI}.jpg"
    out = subprocess.run(
        ["tesseract", str(img_path), "stdout", "--psm", "3"],
        capture_output=True, text=True, timeout=120,
    )
    text = out.stdout.strip()
    (config.INTERIM_DIR / "ocr" / f"{sha}-p{page_no:03d}.txt").write_text(text)
    img_path.unlink(missing_ok=True)  # keep disk flat; jpg is regenerable
    return sha, page_no, len(text.split())


def main_tesseract(workers: int = 6) -> None:
    import json as _json

    meetings = _json.loads((config.DATA_DIR / "meetings.json").read_text())["meetings"]
    todo = []
    for mid, m in sorted(meetings.items(), key=lambda kv: kv[1]["date"]):
        for f in m["files"]:
            path = config.RAW_DIR / f["local"]
            for i, t in enumerate(page_texts(path, f["sha256"])):
                if len(t.strip()) < 20 and not (
                    config.INTERIM_DIR / "ocr" / f"{f['sha256']}-p{i:03d}.txt"
                ).exists():
                    todo.append((f["local"], f["sha256"], i))
    print(f"tesseract-backfill: {len(todo)} pages, {workers} workers", flush=True)
    done = 0
    with PROVENANCE.open("a") as prov, ESCALATE.open("a") as esc,          ProcessPoolExecutor(max_workers=workers) as ex:
        for sha, page_no, nwords in ex.map(_tesseract_one, todo, chunksize=8):
            key = f"{sha}-p{page_no:03d}"
            prov.write(_json.dumps({"key": key, "engine": "tesseract"}) + "\n")
            if nwords < 10:
                esc.write(_json.dumps({"key": key, "words": nwords}) + "\n")
            done += 1
            if done % 250 == 0:
                print(f"  [{done}/{len(todo)}]", flush=True)
    print(f"tesseract-backfill: done ({done} pages, $0)", flush=True)


if __name__ == "__main__" and __import__("sys").argv[-1] == "tesseract":
    main_tesseract()
