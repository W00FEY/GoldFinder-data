"""Gold-shift scoring: where recent rain over alluvial goldfields may have
redistributed gold.

score = 100 * A^0.7 * R * (0.5 + 0.5*W)

A — log-scaled alluvial occurrence density incl. half-weighted neighbors (0-1)
R — min(1, 0.6*min(1, r7/60) + 0.4*min(1, rmax24/30))
W — waterway factor from static/waterways_grid.json; 0.5 neutral when absent

Multiplicative: no rain => no signal. This is a heuristic, not a prediction.
"""
import json
import math
from pathlib import Path

from . import config
from .grid import cell_key, cell_polygon

_STATIC_WATERWAYS = Path(__file__).resolve().parent.parent / "static" / "waterways_grid.json"


def _load_waterways() -> dict[str, float]:
    if _STATIC_WATERWAYS.exists():
        try:
            return json.loads(_STATIC_WATERWAYS.read_text())
        except Exception:
            pass
    return {}


def _cell_density(cell: dict) -> float:
    # OZMIN's deposit-model field is sparse (few explicit alluvial tags), so
    # blend: alluvial occurrences count fully, all other gold occurrences at
    # 0.3 — keeps the signal national while boosting known alluvial country.
    return cell["alluvial"] + 0.3 * (cell["count"] - cell["alluvial"])


def _density(grid: dict[tuple[int, int], dict]) -> dict[tuple[int, int], float]:
    raw: dict[tuple[int, int], float] = {}
    for (cx, cy), cell in grid.items():
        own = _cell_density(cell)
        neigh = sum(
            _cell_density(grid[k])
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            if (dx, dy) != (0, 0) and (k := (cx + dx, cy + dy)) in grid
        )
        raw[(cx, cy)] = own + 0.5 * neigh
    return raw


def rain_factor(r7: float, rmax24: float) -> float:
    return min(
        1.0,
        0.6 * min(1.0, r7 / config.SHIFT_R7_FULL_MM)
        + 0.4 * min(1.0, rmax24 / config.SHIFT_RMAX_FULL_MM),
    )


def compute_goldshift(
    grid: dict[tuple[int, int], dict], rainfall: dict[str, dict]
) -> list[dict]:
    raw = _density(grid)
    a_max = max(raw.values(), default=0.0)
    if a_max <= 0:
        return []
    waterways = _load_waterways()

    features = []
    for (cx, cy), r in raw.items():
        if r <= 0:
            continue
        key = cell_key(cx, cy)
        rain = rainfall.get(key)
        if not rain:
            continue
        a = math.log1p(r) / math.log1p(a_max)
        rf = rain_factor(rain["r7"], rain["rmax24"])
        w = waterways.get(key, 0.5)
        score = 100.0 * (a ** config.SHIFT_ALPHA) * rf * (0.5 + 0.5 * w)
        if score < config.SHIFT_MIN_SCORE:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": cell_polygon(cx, cy),
                "properties": {
                    "cell": key,
                    "score": round(score, 1),
                    "a": round(a, 3),
                    "r": round(rf, 3),
                    "w": round(w, 3),
                    "r7": rain["r7"],
                    "rmax24": rain["rmax24"],
                    "label": grid[(cx, cy)].get("name"),
                },
            }
        )
    features.sort(key=lambda f: -f["properties"]["score"])
    return features


def rainfall_features(
    grid: dict[tuple[int, int], dict], rainfall: dict[str, dict]
) -> list[dict]:
    """Rainfall grid as polygons (only cells with any rain, to keep size down)."""
    out = []
    for (cx, cy) in sorted(grid.keys()):
        key = cell_key(cx, cy)
        rain = rainfall.get(key)
        if not rain or rain["r14"] <= 0.5:
            continue
        out.append(
            {
                "type": "Feature",
                "geometry": cell_polygon(cx, cy),
                "properties": {"cell": key, **rain},
            }
        )
    return out
