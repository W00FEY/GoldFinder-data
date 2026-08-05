"""0.25-degree grid helpers shared by rainfall and goldshift."""
import math

from . import config


def cell_of(lon: float, lat: float) -> tuple[int, int]:
    return (math.floor(lon / config.CELL_DEG), math.floor(lat / config.CELL_DEG))


def cell_key(cx: int, cy: int) -> str:
    return f"{cx}_{cy}"


def cell_center(cx: int, cy: int) -> tuple[float, float]:
    return ((cx + 0.5) * config.CELL_DEG, (cy + 0.5) * config.CELL_DEG)


def cell_polygon(cx: int, cy: int) -> dict:
    d = config.CELL_DEG
    x0, y0 = cx * d, cy * d
    x1, y1 = x0 + d, y0 + d
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def gold_grid(features: list[dict]) -> dict[tuple[int, int], dict]:
    """Cells containing >=1 gold occurrence plus a one-cell buffer.

    Returns {(cx, cy): {"count": n, "alluvial": n, "name": str|None, "occupied": bool}}
    """
    cells: dict[tuple[int, int], dict] = {}
    for f in features:
        lon, lat = f["geometry"]["coordinates"][:2]
        key = cell_of(lon, lat)
        c = cells.setdefault(
            key, {"count": 0, "alluvial": 0, "name": None, "occupied": True}
        )
        c["count"] += 1
        c["occupied"] = True
        props = f["properties"]
        if props.get("alluvial"):
            c["alluvial"] += 1
            if props.get("name") and props["name"] != "Unnamed":
                c["name"] = c["name"] or props["name"]
        if c["name"] is None and props.get("name") and props["name"] != "Unnamed":
            c["name"] = props["name"]

    # one-cell buffer ring
    for (cx, cy) in list(cells.keys()):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                k = (cx + dx, cy + dy)
                if k not in cells:
                    cells[k] = {"count": 0, "alluvial": 0, "name": None, "occupied": False}
    return cells
