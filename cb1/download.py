"""Polite, idempotent PDF downloads.

Sequential with a delay and a browser UA. data/raw/manifest.json maps
href -> {url, local, sha256, size}; a file already in the manifest whose
local copy exists is never re-downloaded.
"""

import hashlib
import json
import re
import time

import httpx

from cb1 import config
from cb1.scrape import absolute_url


def load_manifest() -> dict:
    if config.RAW_DIR.joinpath("manifest.json").exists():
        return json.loads((config.RAW_DIR / "manifest.json").read_text())
    return {}


def save_manifest(manifest: dict) -> None:
    (config.RAW_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))


def safe_filename(href: str, taken: set[str]) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", href.rsplit("/", 1)[-1])
    if name.lower() in taken:  # macOS FS is case-insensitive
        digest = hashlib.sha256(href.encode()).hexdigest()[:8]
        name = f"{digest}-{name}"
    return name


def download_all(hrefs: list[str], delay_s: float = config.DOWNLOAD_DELAY_S) -> dict:
    """Download every href not already in the manifest. Returns the manifest."""
    config.ensure_dirs()
    manifest = load_manifest()
    taken = {v["local"].lower() for v in manifest.values()}

    todo = [h for h in hrefs if not (
        h in manifest and (config.RAW_DIR / manifest[h]["local"]).exists()
    )]
    if not todo:
        print(f"download: all {len(hrefs)} files present, nothing to do")
        return manifest

    print(f"download: {len(todo)} of {len(hrefs)} files to fetch")
    with httpx.Client(
        headers={"User-Agent": config.USER_AGENT}, follow_redirects=True, timeout=120
    ) as client:
        for i, href in enumerate(todo, 1):
            url = absolute_url(href)
            local = safe_filename(href, taken)
            resp = client.get(url)
            resp.raise_for_status()
            path = config.RAW_DIR / local
            path.write_bytes(resp.content)
            taken.add(local.lower())
            manifest[href] = {
                "url": url,
                "local": local,
                "sha256": hashlib.sha256(resp.content).hexdigest(),
                "size": len(resp.content),
            }
            save_manifest(manifest)  # crash-safe: resume where we left off
            print(f"  [{i}/{len(todo)}] {local} ({len(resp.content) // 1024} KB)")
            time.sleep(delay_s)
    return manifest
