"""Mobile phone tower sites from the ACMA Register of Radiocommunications
Licences (nightly bulk zip). Towers are a practical proxy for reception:
within a few km line-of-sight of a site you'll usually have signal.

Streams the big CSVs (device_details is ~380 MB) row-by-row to stay inside
CI memory. Fail-soft like every fetcher.
"""
import csv
import io
import os
import tempfile
import zipfile
from pathlib import Path

from .http import SESSION

RRL_ZIP = "https://cdn.acma.gov.au/rrl/spectra_rrl.zip"

_CARRIERS = {
    "TELSTRA": "Telstra",
    "OPTUS": "Optus",
    "VODAFONE": "Vodafone/TPG",
    "TPG": "Vodafone/TPG",
}


def _carrier_of(name: str) -> str | None:
    up = (name or "").upper()
    for key, label in _CARRIERS.items():
        if key in up:
            return label
    return None


def _build_features(zf: zipfile.ZipFile) -> list[dict]:
    def rows(name: str):
        with zf.open(name) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))

    # client_no -> carrier label (mobile carriers only)
    carrier_by_client: dict[str, str] = {}
    for r in rows("client.csv"):
        carrier = _carrier_of(r.get("LICENCEE", "")) or _carrier_of(r.get("TRADING_NAME", ""))
        if carrier:
            carrier_by_client[r["CLIENT_NO"]] = carrier

    # licence_no -> carrier, for mobile-service licences held by carriers
    carrier_by_licence: dict[str, str] = {}
    for r in rows("licence.csv"):
        carrier = carrier_by_client.get(r.get("CLIENT_NO", ""))
        if not carrier:
            continue
        cat = (r.get("LICENCE_CATEGORY_NAME") or "").upper()
        typ = (r.get("LICENCE_TYPE_NAME") or "").upper()
        if cat.startswith("PMTS") or typ == "SPECTRUM":
            carrier_by_licence[r["LICENCE_NO"]] = carrier

    # site_id -> set of carriers transmitting there
    carriers_by_site: dict[str, set[str]] = {}
    for r in rows("device_details.csv"):
        if r.get("DEVICE_TYPE") != "T":
            continue
        carrier = carrier_by_licence.get(r.get("LICENCE_NO", ""))
        if carrier:
            carriers_by_site.setdefault(r.get("SITE_ID", ""), set()).add(carrier)

    features = []
    for r in rows("site.csv"):
        site_id = r.get("SITE_ID", "")
        carriers = carriers_by_site.get(site_id)
        if not carriers:
            continue
        try:
            lat = float(r["LATITUDE"])
            lon = float(r["LONGITUDE"])
        except (KeyError, TypeError, ValueError):
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                "properties": {
                    "id": site_id,
                    "name": (r.get("NAME") or "Tower site")[:120],
                    "carriers": ", ".join(sorted(carriers)),
                },
            }
        )
    features.sort(key=lambda f: f["properties"]["id"])
    return features


def fetch_tower_sites() -> list[dict] | None:
    """Download the RRL zip (or use TOWERS_LOCAL_ZIP for tests) and extract
    mobile carrier transmitter sites."""
    local = os.environ.get("TOWERS_LOCAL_ZIP")
    try:
        if local and Path(local).exists():
            with zipfile.ZipFile(local) as zf:
                return _build_features(zf)
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            with SESSION.get(RRL_ZIP, stream=True, timeout=600) as r:
                r.raise_for_status()
                for chunk in r.iter_content(1 << 20):
                    tmp.write(chunk)
            tmp.flush()
            with zipfile.ZipFile(tmp.name) as zf:
                return _build_features(zf)
    except Exception as e:  # noqa: BLE001 — fail-soft by design
        print(f"[towers] failed: {e}")
        return None
