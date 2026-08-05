"""Rainfall over the gold grid.

Primary: Open-Meteo forecast API with past_days (includes the most recent
days, unlike the ERA5 archive which lags ~5 days). Fallbacks: Open-Meteo
archive, then NASA POWER (occupied cells only — it is one call per point).
BOM AGCD grids and SILO are documented manual fallbacks (need NetCDF deps /
an API key) — see README.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from . import config
from .grid import cell_center, cell_key
from .http import get_json


def _summarize(daily_mm: list[float]) -> dict:
    vals = [v if isinstance(v, (int, float)) else 0.0 for v in daily_mm]
    last7 = vals[-7:]
    return {
        "r7": round(sum(last7), 1),
        "r14": round(sum(vals[-14:]), 1),
        "rmax24": round(max(last7) if last7 else 0.0, 1),
    }


def _openmeteo(url: str, cells: list[tuple[int, int]], extra: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(cells), config.RAIN_BATCH):
        if i:
            time.sleep(config.RAIN_BATCH_PAUSE_S)
        batch = cells[i : i + config.RAIN_BATCH]
        centers = [cell_center(cx, cy) for cx, cy in batch]
        params = {
            "latitude": ",".join(f"{lat:.3f}" for _, lat in centers),
            "longitude": ",".join(f"{lon:.3f}" for lon, _ in centers),
            "daily": "precipitation_sum",
            "timezone": "UTC",
            **extra,
        }
        data = get_json(url, params=params, timeout=120)
        results = data if isinstance(data, list) else [data]
        if len(results) != len(batch):
            raise ValueError(f"expected {len(batch)} results, got {len(results)}")
        for (cx, cy), res in zip(batch, results):
            out[cell_key(cx, cy)] = _summarize(res["daily"]["precipitation_sum"])
    return out


def _openmeteo_forecast(cells):
    return _openmeteo(
        config.OPEN_METEO_FORECAST,
        cells,
        {"past_days": config.RAIN_DAYS, "forecast_days": 1},
    )


def _openmeteo_archive(cells):
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=config.RAIN_DAYS - 1)
    return _openmeteo(
        config.OPEN_METEO_ARCHIVE,
        cells,
        {"start_date": start.isoformat(), "end_date": end.isoformat()},
    )


def _nasa_power_one(args):
    (cx, cy), start, end = args
    lon, lat = cell_center(cx, cy)
    data = get_json(
        config.NASA_POWER,
        params={
            "parameters": "PRECTOTCORR",
            "community": "AG",
            "latitude": f"{lat:.3f}",
            "longitude": f"{lon:.3f}",
            "start": start,
            "end": end,
            "format": "JSON",
        },
        timeout=60,
    )
    series = data["properties"]["parameter"]["PRECTOTCORR"]
    daily = [v for _, v in sorted(series.items()) if v is not None and v >= 0]
    return cell_key(cx, cy), _summarize(daily)


def _nasa_power(cells, occupied: set[tuple[int, int]]):
    end_d = date.today() - timedelta(days=3)
    start_d = end_d - timedelta(days=config.RAIN_DAYS - 1)
    start, end = start_d.strftime("%Y%m%d"), end_d.strftime("%Y%m%d")
    targets = [c for c in cells if c in occupied]
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for key, summary in ex.map(
            _nasa_power_one, [(c, start, end) for c in targets]
        ):
            out[key] = summary
    return out


def fetch_rainfall(
    grid: dict[tuple[int, int], dict]
) -> tuple[dict[str, dict] | None, str]:
    """Returns ({cell_key: {r7, r14, rmax24}} or None, source_name)."""
    cells = sorted(grid.keys())
    occupied = {c for c, v in grid.items() if v["occupied"]}
    for name, fn in (
        ("open-meteo", lambda: _openmeteo_forecast(cells)),
        ("open-meteo-archive", lambda: _openmeteo_archive(cells)),
        ("nasa-power", lambda: _nasa_power(cells, occupied)),
    ):
        try:
            return fn(), name
        except Exception as e:  # noqa: BLE001 — fail-soft by design
            print(f"[rainfall] {name} failed: {e}")
    return None, "none"
