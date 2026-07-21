"""Render analysis/BLOG.ipynb to blog/williamsburg-waterfront.html via Quarto.

Never writes to the source notebook: stages a copy, injects front matter, drops empty
code cells, silences the setup cell's stdout, renders with stored outputs
(no execution), and moves the self-contained HTML into blog/.

Usage: uv run python scripts/render_blog.py [notebook]  (default: analysis/blog_v2.ipynb)
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import nbformat as nbf

REPO = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "analysis" / "blog_v2.ipynb"
OUT = REPO / "blog" / "williamsburg-waterfront.html"

FRONT_MATTER = """---
title: "{title}"
description: "I scraped ten years of my community board's minutes to find out if showing up works."
author: "Brad Lowenstein"
date: today
format:
  html:
    toc: true
    embed-resources: true
    fig-align: left
execute:
  enabled: false
  echo: false
---"""


def main() -> None:
    nb = nbf.read(SRC, as_version=4)

    title = "Williamsburg Waterfront"
    c0 = nb.cells[0]
    if c0.cell_type == "markdown" and c0.source.startswith("# "):
        first, *rest = c0.source.split("\n", 1)
        title = first.lstrip("# ").strip()
        c0.source = rest[0].lstrip("\n") if rest else ""
        if not c0.source.strip():
            nb.cells.pop(0)

    nb.cells = [
        c for c in nb.cells if not (c.cell_type == "code" and not c.source.strip())
    ]

    # mute all stdout: code is hidden (echo: false), so stray prints would
    # float context-free; figures are display_data and unaffected
    for c in nb.cells:
        if c.cell_type == "code":
            c.outputs = [o for o in c.outputs if o.output_type != "stream"]

    nb.cells.insert(0, nbf.v4.new_raw_cell(FRONT_MATTER.format(title=title)))

    with tempfile.TemporaryDirectory() as td:
        staged = Path(td) / "blog_render.ipynb"
        nbf.write(nb, staged)
        images = REPO / "blog" / "images"
        if images.is_dir():
            shutil.copytree(images, Path(td) / "images")
        subprocess.run(
            ["uv", "run", "--with", "quarto-cli", "quarto", "render",
             str(staged), "--to", "html"],
            check=True, cwd=REPO,
        )
        OUT.parent.mkdir(exist_ok=True)
        (Path(td) / "blog_render.html").rename(OUT)
    print(f"rendered: {OUT} ({OUT.stat().st_size / 1e6:.1f} MB) — title: {title}")


if __name__ == "__main__":
    main()
