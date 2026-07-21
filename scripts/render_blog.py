"""Render analysis/blog_v2.ipynb to HTML via Quarto.

Never writes to the source notebook: stages a copy, injects front matter, drops empty
code cells, silences the setup cell's stdout, renders with stored outputs
(no execution).

Default: self-contained preview at blog/williamsburg-waterfront.html.
--publish: renders with external assets (S3/CloudFront caches them individually)
and copies <slug>.html + <slug>_files/ + images/ into the bradlowenstein.com
site repo's blog/ dir, with SEO head (canonical, OG, JSON-LD) injected.
Does NOT commit or deploy the site repo.

Usage: uv run python scripts/render_blog.py [--publish] [notebook]
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import nbformat as nbf

REPO = Path(__file__).resolve().parent.parent
PUBLISH = "--publish" in sys.argv
args = [a for a in sys.argv[1:] if a != "--publish"]
SRC = Path(args[0]) if args else REPO / "analysis" / "blog_v2.ipynb"
OUT = REPO / "blog" / "williamsburg-waterfront.html"

SLUG = "does-showing-up-work"
SITE_BLOG = Path.home() / "Workspace" / "BradLowensteinPersonalSite" / "blog"
POST_URL = f"https://bradlowenstein.com/blog/{SLUG}"
DESCRIPTION = (
    "I scraped ten years of my community board's minutes "
    "to find out if showing up works."
)
OG_IMAGE = "https://bradlowenstein.com/blog/images/bip_and_lots.jpg"

FRONT_MATTER = """---
title: "{title}"
description: "{description}"
author: "Brad Lowenstein"
date: today
format:
  html:
    toc: true
    embed-resources: {embed}
    fig-align: left
    grid:
      body-width: 900px
    css: site.css
    include-before-body: nav.html
    include-after-body: footer.html{header}
execute:
  enabled: false
  echo: false
---"""

SEO_HEAD = """<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{og_image}">
<meta property="article:author" content="Brad Lowenstein">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="{og_image}">
<script type="application/ld+json">
{json_ld}
</script>"""


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

    fm = FRONT_MATTER.format(
        title=title,
        description=DESCRIPTION,
        embed="false" if PUBLISH else "true",
        header="\n    include-in-header: seo_head.html" if PUBLISH else "",
    )
    nb.cells.insert(0, nbf.v4.new_raw_cell(fm))

    stem = SLUG if PUBLISH else "blog_render"
    with tempfile.TemporaryDirectory() as td:
        staged = Path(td) / f"{stem}.ipynb"
        nbf.write(nb, staged)
        images = REPO / "blog" / "images"
        if images.is_dir():
            shutil.copytree(images, Path(td) / "images")
        for f in (REPO / "blog" / "site_theme").iterdir():
            shutil.copy2(f, Path(td) / f.name)
        if PUBLISH:
            json_ld = json.dumps({
                "@context": "https://schema.org",
                "@type": "BlogPosting",
                "headline": title,
                "description": DESCRIPTION,
                "author": {"@type": "Person", "name": "Brad Lowenstein",
                           "url": "https://bradlowenstein.com"},
                "image": OG_IMAGE,
                "url": POST_URL,
            }, indent=2)
            (Path(td) / "seo_head.html").write_text(SEO_HEAD.format(
                url=POST_URL, title=title, description=DESCRIPTION,
                og_image=OG_IMAGE, json_ld=json_ld,
            ))
        subprocess.run(
            ["uv", "run", "--with", "quarto-cli", "quarto", "render",
             str(staged), "--to", "html"],
            check=True, cwd=REPO,
        )
        rendered = Path(td) / f"{stem}.html"
        # drop Quarto's unused jQuery/RequireJS CDN tags (nothing on the
        # page needs them; keeps the post free of external dependencies)
        rendered.write_text(re.sub(
            r'<script src="https://cdn\.jsdelivr\.net[^"]*"[^>]*></script>',
            "", rendered.read_text(),
        ))
        if PUBLISH:
            SITE_BLOG.mkdir(exist_ok=True)
            html = SITE_BLOG / f"{SLUG}.html"
            shutil.copy2(Path(td) / f"{stem}.html", html)
            # quarto links css: files relatively but leaves them out of _files/
            shutil.copy2(REPO / "blog" / "site_theme" / "site.css", SITE_BLOG / "site.css")
            files_dir = SITE_BLOG / f"{SLUG}_files"
            if files_dir.exists():
                shutil.rmtree(files_dir)
            shutil.copytree(Path(td) / f"{stem}_files", files_dir)
            # only ship photos the post references, not everything on disk
            used = {
                Path(m).name
                for m in html.read_text().split('src="images/')[1:]
                for m in [m.split('"', 1)[0]]
            }
            (SITE_BLOG / "images").mkdir(exist_ok=True)
            for name in sorted(used):
                shutil.copy2(images / name, SITE_BLOG / "images" / name)
            n_assets = sum(1 for p in files_dir.rglob("*") if p.is_file())
            print(f"published: {html} ({html.stat().st_size / 1e3:.0f} KB) "
                  f"+ {n_assets} assets in {files_dir.name}/ + images/ — not deployed")
        else:
            OUT.parent.mkdir(exist_ok=True)
            (Path(td) / f"{stem}.html").rename(OUT)
            print(f"rendered: {OUT} ({OUT.stat().st_size / 1e6:.1f} MB) — title: {title}")


if __name__ == "__main__":
    main()
