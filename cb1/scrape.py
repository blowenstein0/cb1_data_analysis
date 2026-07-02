"""Fetch the CB1 minutes index page and pull PDF hrefs.

nyc.gov returns 403 to non-browser user agents, so we send a real one.
Some hrefs contain literal spaces and must be quoted before download.
"""

import re
from urllib.parse import quote

import httpx

from cb1 import config

HREF_RE = re.compile(r'href="([^"]*\.pdf)"', re.IGNORECASE)


def fetch_index(url: str = config.INDEX_URL) -> str:
    resp = httpx.get(
        url,
        headers={"User-Agent": config.USER_AGENT},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def extract_pdf_hrefs(html: str) -> list[str]:
    """All .pdf hrefs, deduplicated, original order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for href in HREF_RE.findall(html):
        if href not in seen:
            seen.add(href)
            out.append(href)
    return out


def absolute_url(href: str) -> str:
    """Absolutize against nyc.gov and percent-quote spaces etc."""
    if href.startswith("http"):
        return href
    return config.BASE_URL + quote(href, safe="/:%")
