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

    print(f"stage {args.stage!r} not implemented yet (see PLAN.md build phases)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
