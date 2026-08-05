# GoldFinder-data

Daily-updated map data feed for the [GoldFinder](https://github.com/W00FEY/GoldFinder)
Android app — an interactive gold prospecting map of Australia.

A GitHub Actions cron runs the pipeline in `pipeline/` every day and publishes
the results to the **`data`** branch of this repo. The app fetches:

```
https://raw.githubusercontent.com/W00FEY/GoldFinder-data/data/v1/manifest.json
```

## What's in the feed

| File | Content |
|---|---|
| `manifest.json` | generated-at stamp, per-section status, new-report count |
| `gold_occurrences.geojson` | all gold occurrences from Geoscience Australia's OZMIN database |
| `new_reports.geojson` | official + community gold reports first seen in the last 90 days |
| `rainfall_grid.geojson` | 7/14-day rainfall over the goldfields (0.25° grid) |
| `goldshift.geojson` | heuristic "gold shift" hotspots (recent heavy rain over alluvial goldfields) |
| `community_reports.json` | best-effort community find reports |
| `tenement_sources.json` | live per-state tenement/claim service registry + daily health check |

The full JSON contract lives in the app repo:
[`data-contract/SCHEMA.md`](https://github.com/W00FEY/GoldFinder/blob/claude/australia-gold-map-interactive-vugsvu/data-contract/SCHEMA.md).

## Running the pipeline locally

```bash
cd pipeline
pip install -r requirements.txt
python -m goldpipe.cli all --out out/v1 --state state
pytest
```

## Data sources & credits

Geoscience Australia OZMIN (CC BY 4.0) · Open-Meteo (CC BY 4.0) with NASA
POWER fallback · state government tenement services (WA DMIRS, QLD, NSW, VIC,
SA, NT, TAS) · public Reddit prospecting communities.

Data is provided as-is from public sources with no warranty. Gold shift is a
heuristic, not a prediction. Always verify claim status and land access before
prospecting.
