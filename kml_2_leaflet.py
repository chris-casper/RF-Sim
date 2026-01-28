#!/usr/bin/env python3
"""
Batch-process all .kml files in a folder.

For each KML:
- Extract site name (CloudRF "nam" preferred)
- Extract site lat/lon
- Extract GroundOverlay image + bounds
- Download overlay PNG(s) (handles 404s + other HTTP errors gracefully)
- Emit Leaflet-friendly manifest.json
- ALSO emit a top-level index.json listing manifest paths

Output structure (example):
out/
  index.json
  <site_slug>/
    manifest.json
    overlays/
      *.png   (only the successfully downloaded ones)

If an overlay image fails to download (404, timeout, etc), the manifest will still
include the overlay with:
  - "image": null
  - "download_ok": false
  - "http_status": <status or null>
  - "error": "<message>"
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

import xml.etree.ElementTree as ET

import requests
from requests.exceptions import RequestException, Timeout


KML_NS = {"kml": "http://earth.google.com/kml/2.2"}

# Target base folder for manifests/images in generated JSON paths
# (Matches your example: "potential/<SiteName>/manifest.json")
POTENTIAL_BASE = "potential"


def slugify(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s.strip()) or "site"


def extract_cloudrf_json(desc: str) -> Optional[Dict[str, Any]]:
    """
    CloudRF embeds a JSON object inside <textarea> ... </textarea> in the HTML CDATA.
    We pull that out and parse it. Returns None if not found/parseable.
    """
    if not desc:
        return None
    m = re.search(r"<textarea[^>]*>(\{.*?\})</textarea>", desc, re.S | re.I)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def safe_filename_from_url(url: str, fallback: str) -> str:
    p = urlparse(url).path
    name = Path(p).name
    return name if name else fallback


@dataclass
class DownloadResult:
    ok: bool
    http_status: Optional[int]
    error: Optional[str]


def download(url: str, dest: Path, timeout_s: int = 120) -> DownloadResult:
    """
    Download url -> dest. Returns DownloadResult.
    Gracefully handles HTTP errors (including 404) and network errors.

    NOTE: we do not raise on errors; we return status so the caller can continue.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        with requests.get(url, stream=True, timeout=timeout_s) as r:
            status = r.status_code

            # Explicit handling for 404 (and any other non-2xx)
            if status == 404:
                return DownloadResult(ok=False, http_status=404, error="404 Not Found")
            if status < 200 or status >= 300:
                return DownloadResult(ok=False, http_status=status, error=f"HTTP {status}")

            # Stream to disk
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 128):
                    if chunk:
                        f.write(chunk)

            return DownloadResult(ok=True, http_status=status, error=None)

    except Timeout:
        return DownloadResult(ok=False, http_status=None, error=f"Timeout after {timeout_s}s")
    except RequestException as e:
        return DownloadResult(ok=False, http_status=None, error=str(e))
    except OSError as e:
        return DownloadResult(ok=False, http_status=None, error=f"Filesystem error: {e}")


def parse_kml(path: Path) -> Dict[str, Any]:
    """
    Parse a CloudRF-style KML and return:
      site_name, lat, lon, overlays[]
    overlays contains: name, href, bounds[[s,w],[n,e]]
    """
    root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))

    folder_name = None
    folder = root.find(".//kml:Folder", KML_NS)
    if folder is not None:
        folder_name = folder.findtext("kml:name", default="", namespaces=KML_NS).strip() or None

    placemark = root.find(".//kml:Placemark", KML_NS)
    if placemark is None:
        raise RuntimeError("No <Placemark> found")

    placemark_name = placemark.findtext("kml:name", default="", namespaces=KML_NS).strip() or None
    desc = placemark.findtext("kml:description", default="", namespaces=KML_NS) or ""

    cloudrf = extract_cloudrf_json(desc) or {}
    site_name = (cloudrf.get("nam") or placemark_name or folder_name or path.stem).strip()

    coord = placemark.findtext(".//kml:Point/kml:coordinates", namespaces=KML_NS)
    if not coord:
        raise RuntimeError("No <Point><coordinates> found for site lat/lon")

    lon, lat = map(float, coord.split(",")[:2])

    overlays: List[Dict[str, Any]] = []
    for go in root.findall(".//kml:GroundOverlay", KML_NS):
        href = go.findtext("kml:Icon/kml:href", namespaces=KML_NS)
        box = go.find("kml:LatLonBox", KML_NS)
        if not href or box is None:
            continue

        def f(tag: str) -> float:
            t = box.findtext(f"kml:{tag}", namespaces=KML_NS)
            if t is None:
                raise RuntimeError(f"Missing <LatLonBox><{tag}>")
            return float(t)

        overlays.append({
            "name": go.findtext("kml:name", default="Coverage", namespaces=KML_NS),
            "href": href.strip(),
            "bounds": [
                [f("south"), f("west")],
                [f("north"), f("east")]
            ],
            "rotation": (lambda x: float(x) if x is not None else None)(
                box.findtext("kml:rotation", namespaces=KML_NS)
            )
        })

    return {
        "site_name": site_name,
        "lat": lat,
        "lon": lon,
        "folder_name": folder_name,
        "placemark_name": placemark_name,
        "overlays": overlays
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default=".", help="Folder containing KML files (default: .)")
    ap.add_argument("-o", "--out", default="out", help="Output folder (default: out)")
    ap.add_argument("--timeout", type=int, default=120, help="Download timeout seconds (default: 120)")
    ap.add_argument("--skip-downloads", action="store_true", help="Do not download PNGs; still writes manifests")
    args = ap.parse_args()

    in_dir = Path(args.input)
    out_dir = Path(args.out)

    kml_files = sorted(in_dir.glob("*.kml"))
    if not kml_files:
        print(f"No KML files found in {in_dir.resolve()}")
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    # Collect relative manifest paths for index.json
    index_manifests: List[str] = []

    for kml in kml_files:
        print(f"\nProcessing: {kml.name}")

        try:
            info = parse_kml(kml)
        except Exception as e:
            print(f"  ❌ Failed to parse KML: {e}")
            continue

        site_name = info["site_name"]
        site_slug = slugify(site_name)

        site_dir = out_dir / site_slug
        overlays_dir = site_dir / "overlays"
        site_dir.mkdir(parents=True, exist_ok=True)

        manifest_overlays: List[Dict[str, Any]] = []

        for idx, ov in enumerate(info["overlays"], start=1):
            href = ov.get("href")
            bounds = ov.get("bounds")

            # CHANGE: overlays.name should be the site.name
            ov_name = site_name

            entry: Dict[str, Any] = {
                "name": ov_name,
                "source_url": href,
                "bounds": bounds,
                "rotation": ov.get("rotation"),
                "image": None,
                "download_ok": False,
                "http_status": None,
                "error": None
            }

            if not href:
                entry["error"] = "No href in GroundOverlay"
                manifest_overlays.append(entry)
                continue

            fname = safe_filename_from_url(href, f"overlay_{idx}.png")
            dest = overlays_dir / fname

            # CHANGE: overlays.image should have "potential/{site.name}/" prepended
            # Keep the rest of the path the same as before ("overlays/<fname>").
            image_rel = f"/{POTENTIAL_BASE}/{site_name}/overlays/{fname}"

            if args.skip_downloads:
                entry["image"] = image_rel
                entry["download_ok"] = False
                entry["error"] = "Downloads skipped by --skip-downloads"
                manifest_overlays.append(entry)
                continue

            res = download(href, dest, timeout_s=args.timeout)

            entry["http_status"] = res.http_status
            entry["download_ok"] = res.ok
            entry["error"] = res.error

            if res.ok:
                entry["image"] = image_rel
                print(f"  ✅ PNG: {fname}")
            else:
                print(f"  ⚠️  PNG failed: {href} -> {res.error} (status={res.http_status})")

            manifest_overlays.append(entry)

        # CHANGE: Add antenna_agl_m and antenna_agl_note after lat/lon with defaults
        manifest = {
            "site": {
                "name": site_name,
                "lat": info["lat"],
                "lon": info["lon"],
                "antenna_agl_m": 10.0,
                "antenna_agl_note": "",
                "folder_name": info["folder_name"],
                "placemark_name": info["placemark_name"],
                "source_kml": kml.name
            },
            "overlays": manifest_overlays
        }

        manifest_path = site_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"  ✔ Wrote: {manifest_path}")

        # CHANGE: Output manifest.json relative path to index.json
        # Example: "potential/BERA/manifest.json"
        index_manifests.append(f"{POTENTIAL_BASE}/{site_name}/manifest.json")

    # Write index.json at output root
    index_path = out_dir / "index.json"
    index = {"manifests": index_manifests}
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"\n✔ Wrote: {index_path}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
