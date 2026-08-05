"""Detect NEW records between pipeline runs.

State file (state/occurrence_index.json):
{
  "ids": {"<id>": {"hash": "<attr-hash>", "first_seen": "YYYY-MM-DD"}},
  "community": {"<url>": "YYYY-MM-DD"}
}

The first run ever seeds the index without flagging everything as new.
"""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from . import config


def _attr_hash(props: dict) -> str:
    core = {k: props.get(k) for k in ("name", "occ_type", "commodity", "deposit_model")}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


def load_state(state_dir: Path) -> dict:
    p = state_dir / "occurrence_index.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"ids": {}, "community": {}}


def save_state(state_dir: Path, state: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "occurrence_index.json").write_text(
        json.dumps(state, sort_keys=True, indent=1)
    )


def diff_occurrences(
    features: list[dict], state: dict, today: date
) -> tuple[list[dict], dict]:
    """Return (new_report_features, updated_state)."""
    ids = state.get("ids", {})
    first_run = not ids
    cutoff = today - timedelta(days=config.NEW_REPORT_MAX_AGE_DAYS)
    new_reports: list[dict] = []

    for f in features:
        props = f["properties"]
        oid = props["id"]
        h = _attr_hash(props)
        entry = ids.get(oid)
        if entry is None:
            # Records present on the first run ever are baseline, not "new".
            ids[oid] = {"hash": h, "first_seen": today.isoformat(), "seeded": first_run}
            if not first_run:
                new_reports.append(_to_report(f, today.isoformat()))
        else:
            entry["hash"] = h
            fs = date.fromisoformat(entry["first_seen"])
            if not entry.get("seeded") and cutoff < fs < today:
                # Still within the 90-day "new" window from an earlier run.
                new_reports.append(_to_report(f, entry["first_seen"]))

    state["ids"] = ids
    return new_reports, state


def diff_community(reports: list[dict], state: dict, today: date) -> tuple[list[dict], dict]:
    """Community reports keyed by URL; all within-window items are 'new'."""
    seen = state.get("community", {})
    cutoff = today - timedelta(days=config.NEW_REPORT_MAX_AGE_DAYS)
    out: list[dict] = []
    for r in reports:
        url = r["url"]
        first_seen = seen.get(url) or today.isoformat()
        seen[url] = first_seen
        if date.fromisoformat(first_seen) > cutoff:
            out.append({**r, "first_seen": first_seen})
    # Trim expired URLs so the state file doesn't grow forever.
    state["community"] = {
        u: d for u, d in seen.items() if date.fromisoformat(d) > cutoff
    }
    return out, state


def _to_report(feature: dict, first_seen: str) -> dict:
    props = feature["properties"]
    return {
        "type": "Feature",
        "geometry": feature["geometry"],
        "properties": {
            "id": props["id"],
            "source": "ozmin",
            "title": props["name"],
            "detail": props.get("commodity"),
            "first_seen": first_seen,
            "url": props.get("url"),
        },
    }
