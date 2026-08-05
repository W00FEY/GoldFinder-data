"""Assemble the out/v1 tree + manifest.json.

Fail-soft: each section writer is handed the result (or None on failure) and
falls back to the previous run's file with status="stale".
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

from . import config


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def geojson(features: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "goldfinder": {"schema_version": config.SCHEMA_VERSION},
        "features": features,
    }


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


class Publisher:
    def __init__(self, out_dir: Path):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.sections: dict[str, dict] = {}

    def section(self, name: str, filename: str, features_or_obj, count: int | None):
        """Write a section. Pass None to keep the previous file as stale."""
        path = self.out / filename
        if features_or_obj is not None:
            write_json(path, features_or_obj)
            self.sections[name] = {
                "file": filename,
                "status": "ok" if count else "empty",
                "updated_at": _now_iso(),
                "count": count or 0,
            }
        elif path.exists():
            prev = self._prev_manifest_section(name)
            self.sections[name] = {
                "file": filename,
                "status": "stale",
                "updated_at": prev.get("updated_at", _now_iso()),
                "count": prev.get("count", 0),
            }
        else:
            self.sections[name] = {
                "file": filename,
                "status": "stale",
                "updated_at": _now_iso(),
                "count": 0,
            }

    def _prev_manifest_section(self, name: str) -> dict:
        p = self.out / "manifest.json"
        if p.exists():
            try:
                return json.loads(p.read_text())["sections"].get(name, {})
            except Exception:
                pass
        return {}

    def finish(self, new_reports: list[dict], today: date) -> dict:
        recent = 0
        for f in new_reports:
            fs = f["properties"].get("first_seen", "")
            try:
                d = date.fromisoformat(fs)
                if (today - d).days <= config.NEW_REPORT_NOTIFY_DAYS:
                    recent += 1
            except ValueError:
                pass
        manifest = {
            "schema_version": config.SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "new_report_count": recent,
            "sections": self.sections,
        }
        write_json(self.out / "manifest.json", manifest)
        return manifest
