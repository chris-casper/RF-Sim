#!/usr/bin/env python3
"""
Batch-process all .kml files in a folder.

For each KML:
- Extract site name from Document/n element or filename
- Extract site lat/lon from Placemark
- Extract TX Height from description
- Extract GroundOverlay bounds
- Overlay image shares the same name as the KML with .png extension
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
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

import xml.etree.ElementTree as ET

import requests
from requests.exceptions import RequestException, Timeout


# Support multiple KML namespaces
KML_NAMESPACES = [
    {"kml": "http://www.opengis.net/kml/2.2"},
    {"kml": "http://earth.google.com/kml/2.2"},
]

# Target base folder for manifests/images in generated JSON paths
POTENTIAL_BASE = "potential"


def slugify(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s.strip()) or "site"


def find_element(root: ET.Element, xpath: str) -> Optional[ET.Element]:
    """Try to find element using multiple namespaces, or without namespace."""
    for ns in KML_NAMESPACES:
        elem = root.find(xpath, ns)
        if elem is not None:
            return elem
    # Try without namespace prefix
    no_ns_xpath = xpath.replace("kml:", "")
    elem = root.find(no_ns_xpath)
    return elem


def find_all_elements(root: ET.Element, xpath: str) -> List[ET.Element]:
    """Try to find all elements using multiple namespaces, or without namespace."""
    for ns in KML_NAMESPACES:
        elems = root.findall(xpath, ns)
        if elems:
            return elems
    # Try without namespace prefix
    no_ns_xpath = xpath.replace("kml:", "")
    return root.findall(no_ns_xpath)


def find_text(root: ET.Element, xpath: str, default: str = "") -> str:
    """Try to find text using multiple namespaces."""
    for ns in KML_NAMESPACES:
        text = root.findtext(xpath, namespaces=ns)
        if text:
            return text.strip()
    # Try without namespace prefix
    no_ns_xpath = xpath.replace("kml:", "")
    text = root.findtext(no_ns_xpath)
    return text.strip() if text else default


def extract_tx_height(desc: str) -> Optional[float]:
    """
    Extract TX Height from description text.
    Looks for patterns like "TX Height: 10 m" or "Height: 10 m AGL"
    """
    if not desc:
        return None
    
    # Try "TX Height: X m" pattern
    m = re.search(r"TX Height:\s*([\d.]+)\s*m", desc, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    
    # Try "Height: X m" pattern
    m = re.search(r"Height:\s*([\d.]+)\s*m", desc, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    
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
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        with requests.get(url, stream=True, timeout=timeout_s) as r:
            status = r.status_code

            if status == 404:
                return DownloadResult(ok=False, http_status=404, error="404 Not Found")
            if status < 200 or status >= 300:
                return DownloadResult(ok=False, http_status=status, error=f"HTTP {status}")

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


def get_element_name(elem: ET.Element) -> Optional[str]:
    """
    Get name from element, checking both <name> and <n> tags.
    """
    # Check for <name> tag (with various namespaces)
    name = find_text(elem, "kml:name")
    if name:
        return name
    
    # Check for <n> tag (non-standard but used in some KMLs)
    n_elem = elem.find("n")
    if n_elem is not None and n_elem.text:
        return n_elem.text.strip()
    
    return None


def parse_kml(path: Path) -> Dict[str, Any]:
    """
    Parse a KML and return:
      site_name, lat, lon, antenna_agl_m, overlays[]
    overlays contains: name, href, bounds[[s,w],[n,e]]
    """
    content = path.read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(content)

    # Get site name from Document/n or Document/name, or fallback to filename
    doc = find_element(root, ".//kml:Document")
    if doc is None:
        # Try without namespace
        doc = root.find(".//Document")
    
    site_name = None
    if doc is not None:
        site_name = get_element_name(doc)
    
    # Fallback to filename (without extension)
    if not site_name:
        site_name = path.stem

    # Find Placemark for coordinates
    placemark = find_element(root, ".//kml:Placemark")
    if placemark is None:
        placemark = root.find(".//Placemark")
    
    if placemark is None:
        raise RuntimeError("No <Placemark> found")

    placemark_name = get_element_name(placemark)

    # Get coordinates
    coord = find_text(placemark, ".//kml:Point/kml:coordinates")
    if not coord:
        point = placemark.find(".//Point")
        if point is not None:
            coord_elem = point.find("coordinates")
            if coord_elem is not None and coord_elem.text:
                coord = coord_elem.text.strip()
    
    if not coord:
        raise RuntimeError("No <Point><coordinates> found for site lat/lon")

    lon, lat = map(float, coord.split(",")[:2])

    # Extract TX Height from GroundOverlay description
    antenna_agl_m = 10.0  # default
    
    ground_overlays = find_all_elements(root, ".//kml:GroundOverlay")
    if not ground_overlays:
        ground_overlays = root.findall(".//GroundOverlay")
    
    for go in ground_overlays:
        desc = get_element_name(go)  # Check name first
        desc_elem = go.find("description")
        if desc_elem is not None and desc_elem.text:
            desc = desc_elem.text
        
        height = extract_tx_height(desc if desc else "")
        if height is not None:
            antenna_agl_m = height
            break

    # Parse overlays - image name is KML filename with .png extension
    overlays: List[Dict[str, Any]] = []
    png_filename = path.stem + ".png"
    
    for go in ground_overlays:
        # Get bounds from LatLonBox
        box = go.find("LatLonBox")
        if box is None:
            for ns in KML_NAMESPACES:
                box = go.find("kml:LatLonBox", ns)
                if box is not None:
                    break
        
        if box is None:
            continue

        def get_bound(tag: str) -> float:
            # Try direct child
            elem = box.find(tag)
            if elem is not None and elem.text:
                return float(elem.text.strip())
            # Try with namespace
            for ns in KML_NAMESPACES:
                text = box.findtext(f"kml:{tag}", namespaces=ns)
                if text:
                    return float(text.strip())
            raise RuntimeError(f"Missing <LatLonBox><{tag}>")

        # Get href from Icon (may be relative path)
        href = None
        icon = go.find("Icon")
        if icon is None:
            for ns in KML_NAMESPACES:
                icon = go.find("kml:Icon", ns)
                if icon is not None:
                    break
        
        if icon is not None:
            href_elem = icon.find("href")
            if href_elem is None:
                for ns in KML_NAMESPACES:
                    href_elem = icon.find("kml:href", ns)
                    if href_elem is not None:
                        break
            if href_elem is not None and href_elem.text:
                href = href_elem.text.strip()

        # Get rotation if present
        rotation = None
        rot_elem = box.find("rotation")
        if rot_elem is None:
            for ns in KML_NAMESPACES:
                rot_elem = box.find("kml:rotation", ns)
                if rot_elem is not None:
                    break
        if rot_elem is not None and rot_elem.text:
            rotation = float(rot_elem.text.strip())

        overlays.append({
            "name": site_name,
            "href": href,
            "bounds": [
                [get_bound("south"), get_bound("west")],
                [get_bound("north"), get_bound("east")]
            ],
            "rotation": rotation,
            "png_filename": png_filename
        })

    return {
        "site_name": site_name,
        "lat": lat,
        "lon": lon,
        "antenna_agl_m": antenna_agl_m,
        "folder_name": site_name,
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
            png_filename = ov.get("png_filename")

            entry: Dict[str, Any] = {
                "name": site_name,
                "source_url": href,
                "bounds": bounds,
                "rotation": ov.get("rotation"),
                "image": None,
                "download_ok": False,
                "http_status": None,
                "error": None
            }

            # Image path uses the PNG filename derived from KML name
            image_rel = f"/{POTENTIAL_BASE}/{site_name}/overlays/{png_filename}"

            if not href:
                # No remote URL - look for local file with same name as KML
                source_png = kml.parent / png_filename
                dest_png = overlays_dir / png_filename
                
                overlays_dir.mkdir(parents=True, exist_ok=True)
                
                if source_png.exists():
                    shutil.copy2(source_png, dest_png)
                    entry["image"] = image_rel
                    entry["download_ok"] = True
                    entry["error"] = None
                    print(f"  ✅ Copied PNG: {png_filename}")
                else:
                    entry["image"] = image_rel
                    entry["download_ok"] = False
                    entry["error"] = f"Local file not found: {source_png}"
                    print(f"  ⚠️  PNG not found: {source_png}")
                manifest_overlays.append(entry)
                continue

            # Check if href is a URL or local file reference
            if href.startswith("http://") or href.startswith("https://"):
                dest = overlays_dir / png_filename

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
                    print(f"  ✅ PNG: {png_filename}")
                else:
                    print(f"  ⚠️  PNG failed: {href} -> {res.error} (status={res.http_status})")
            else:
                # Local file reference - look for PNG in same directory as KML
                source_png = kml.parent / png_filename
                dest_png = overlays_dir / png_filename
                
                overlays_dir.mkdir(parents=True, exist_ok=True)
                
                if source_png.exists():
                    shutil.copy2(source_png, dest_png)
                    entry["image"] = image_rel
                    entry["download_ok"] = True
                    entry["error"] = None
                    print(f"  ✅ Copied PNG: {png_filename}")
                else:
                    entry["image"] = image_rel
                    entry["download_ok"] = False
                    entry["error"] = f"Local file not found: {source_png}"
                    print(f"  ⚠️  PNG not found: {source_png}")

            manifest_overlays.append(entry)

        manifest = {
            "site": {
                "name": site_name,
                "lat": info["lat"],
                "lon": info["lon"],
                "antenna_agl_m": info["antenna_agl_m"],
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
