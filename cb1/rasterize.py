"""Rasterize PDF pages for the vision tier. Cached by (sha, page, dpi).

Grayscale JPEG, stepping DPI down if needed: the API rejects images over
5 MB, and some scanned pages rasterize past that as color PNG.
"""

import fitz  # pymupdf

from cb1 import config

MAX_IMAGE_BYTES = 4_500_000  # headroom under the 5 MB API limit
JPEG_QUALITY = 80
FALLBACK_DPIS = (110, 80, 60)


def page_jpeg(pdf_path, sha256: str, page_no: int, dpi: int = config.RASTER_DPI) -> bytes:
    cache = config.INTERIM_DIR / "img" / f"{sha256}-p{page_no:03d}-{dpi}.jpg"
    if cache.exists():
        return cache.read_bytes()
    with fitz.open(pdf_path) as doc:
        for try_dpi in (dpi, *FALLBACK_DPIS):
            pix = doc[page_no].get_pixmap(dpi=try_dpi, colorspace=fitz.csGRAY)
            img = pix.tobytes("jpg", jpg_quality=JPEG_QUALITY)
            if len(img) <= MAX_IMAGE_BYTES:
                break
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(img)
    return img
