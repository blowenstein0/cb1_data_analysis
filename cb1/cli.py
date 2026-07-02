"""CLI entrypoints, one subcommand per pipeline stage.

Stages land phase by phase; unimplemented ones exit with a message.
"""

import argparse
import sys

from cb1.costs import CostLedger

STAGES = [
    "download",
    "identify",
    "segment",
    "extract-text",
    "extract-structured",
    "eval",
    "load-db",
    "cost-report",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cb1", description="CB1 minutes pipeline")
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--sync", action="store_true",
                        help="extract-structured: synchronous calls instead of Batch API")
    parser.add_argument("--only", nargs="*", default=None, metavar="MEETING_ID",
                        help="extract-structured: limit to specific meeting ids")
    parser.add_argument("--draft", metavar="MEETING_ID",
                        help="eval: write a draft golden extraction for hand-correction")
    args = parser.parse_args(argv)

    if args.stage == "cost-report":
        print(CostLedger().report())
        return 0

    if args.stage == "download":
        from cb1.download import download_all
        from cb1.scrape import extract_pdf_hrefs, fetch_index

        download_all(extract_pdf_hrefs(fetch_index()))
        return 0

    if args.stage == "identify":
        from cb1.anthropic_client import Client
        from cb1.identify import run_identify

        run_identify(client=Client())
        return 0

    if args.stage == "extract-text":
        from cb1.anthropic_client import Client
        from cb1.vision_ocr import run_extract_text

        run_extract_text(Client())
        return 0

    if args.stage == "segment":
        import json as _json

        from cb1 import config
        from cb1.download import load_manifest
        from cb1.segment import segment_file

        manifest = load_manifest()
        n_body = n_flagged = 0
        for href, e in sorted(manifest.items()):
            seg = segment_file(config.RAW_DIR / e["local"], e["sha256"])
            n_body += len(seg["body_pages"])
            n_flagged += seg["needs_ocr_first"]
        print(f"segment: {n_body} body pages; {n_flagged} files still need OCR first")
        return 0

    if args.stage == "extract-structured":
        from cb1.anthropic_client import Client
        from cb1.extract import run_extract_structured

        run_extract_structured(Client(), sync=args.sync, only=args.only)
        return 0

    if args.stage == "eval":
        import os

        from cb1.eval.run import draft_golden, run_eval

        client = None
        if os.environ.get("ANTHROPIC_API_KEY"):
            from cb1.anthropic_client import Client

            client = Client()
        if args.draft:
            draft_golden(args.draft, client)
            return 0
        return run_eval(client)

    if args.stage == "load-db":
        from cb1.db import load_db

        load_db()
        return 0

    print(f"stage {args.stage!r} not implemented yet (see PLAN.md build phases)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
