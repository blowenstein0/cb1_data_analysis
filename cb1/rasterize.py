"""Rasterize PDF pages for the vision tier. Cached by (sha, page, dpi).

Grayscale JPEG, stepping DPI down if needed: the API rejects images over
5 MB, and some scanned pages rasterize past that as color PNG.
"""

import fitz  # pymupdf

from cb1 import config

MAX_IMAGE_BYTES = 3_600_000  # 5 MB API limit applies to BASE64 bytes (4/3 inflation)
JPEG_QUALITY = 80
FALLBACK_DPIS = (110, 80, 60)


def page_jpeg(pdf_path, sha256: str, page_no: int, dpi: int = config.RASTER_DPI) -> bytes:
    cache = config.INTERIM_DIR / "img" / f"{sha256}-p{page_no:03d}-{dpi}.jpg"
    if cache.exists():
        return cache.read_bytes()
    with fitz.open(pdf_path) as doc:
        # API also caps dimensions at 8000px/side; poster-scale pages
        # (plans, drawings) must be rendered at whatever DPI fits
        rect = doc[page_no].rect
        max_side_in = max(rect.width, rect.height) / 72
        dim_cap = int(7500 / max_side_in) if max_side_in > 0 else dpi
        for try_dpi in (min(dpi, dim_cap), *(min(d, dim_cap) for d in FALLBACK_DPIS)):
            pix = doc[page_no].get_pixmap(dpi=try_dpi, colorspace=fitz.csGRAY)
            img = pix.tobytes("jpg", jpg_quality=JPEG_QUALITY)
            if len(img) <= MAX_IMAGE_BYTES:
                break
        else:
            # poster-scale pages can exceed the cap even at minimum DPI:
            # degrade quality until they fit (guaranteed exit)
            for q in (60, 45, 30, 20, 10):
                img = pix.tobytes("jpg", jpg_quality=q)
                if len(img) <= MAX_IMAGE_BYTES:
                    break
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(img)
    return img
