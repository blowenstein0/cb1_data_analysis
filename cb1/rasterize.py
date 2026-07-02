"""Rasterize PDF pages to PNG for the vision tier. Cached by (sha, page, dpi)."""

import fitz  # pymupdf

from cb1 import config


def page_png(pdf_path, sha256: str, page_no: int, dpi: int = config.RASTER_DPI) -> bytes:
    cache = config.INTERIM_DIR / "img" / f"{sha256}-p{page_no:03d}-{dpi}.png"
    if cache.exists():
        return cache.read_bytes()
    with fitz.open(pdf_path) as doc:
        pix = doc[page_no].get_pixmap(dpi=dpi)
        png = pix.tobytes("png")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(png)
    return png
