"""Central configuration: endpoints, grid parameters, thresholds."""

USER_AGENT = "GoldFinder/1.0 (github.com/W00FEY/GoldFinder; hobby prospecting map)"

SCHEMA_VERSION = 1

# Australian mainland + Tasmania bounding box (OZMIN contains a few overseas
# records that must be filtered out).
AUS_BBOX = (112.0, -44.0, 154.5, -9.0)  # lon_min, lat_min, lon_max, lat_max

# --- Prices (Yahoo Finance keyless chart API) ---
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
PRICES_RANGE = "5y"

# --- OZMIN (Geoscience Australia) ---
OZMIN_WFS = "https://services.ga.gov.au/gis/earthresource/wfs"
OZMIN_TYPENAME = "erl:MineralOccurrenceView"
OZMIN_PAGE_SIZE = 2000

ALLUVIAL_RE = r"placer|alluvi|deep lead|eluvial"

# occ_type -> heatmap weight
OCC_WEIGHTS = {
    "mine": 1.0,
    "deposit": 1.0,
    "occurrence": 0.6,
    "prospect": 0.3,
    "project": 0.3,
}
DEFAULT_OCC_WEIGHT = 0.5

# --- Rainfall grid ---
CELL_DEG = 0.25          # grid cell size in degrees
RAIN_DAYS = 14           # history window
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
NASA_POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"
RAIN_BATCH = 100         # coordinates per Open-Meteo request
RAIN_BATCH_PAUSE_S = 10  # Open-Meteo counts each location as one call
                         # (~600/min free limit) — pace the batches

# --- Gold shift ---
SHIFT_R7_FULL_MM = 60.0     # 7-day rain that saturates the rain factor
SHIFT_RMAX_FULL_MM = 30.0   # 1-day rain that saturates the flash factor
SHIFT_MIN_SCORE = 15.0
SHIFT_ALPHA = 0.7           # density exponent

# --- New-report tracking ---
NEW_REPORT_MAX_AGE_DAYS = 90
NEW_REPORT_NOTIFY_DAYS = 14

# --- YouTube: active Australian prospecting channels (feeds verified 2026-08) ---
YOUTUBE_CHANNELS: dict[str, str] = {
    "GoldenGully": "UC9t2RlHUshAARQNGe3tfk0A",
    "Goldfields Goose": "UCI8fiJvIppySeXfrhskEyWQ",
    "Vo-Gus Prospecting": "UCxOWMu3gx_EJO7J5Vm0ecPw",
    "Prospector Nic": "UCZVigrxLbuXmTB1NL6YA0xQ",
    "PioneerPauly": "UCeU8II9pvOcHXl7EGeXi8yQ",
    "Tassie Boys Prospecting": "UCaFzHYMrIhVahBCfmc1AjNw",
    "Australian Gold Detecting": "UCqAnfx9LJIBy7zfVXn-P8_A",
    "Gold Rat Prospecting": "UCie0tDHPLPSRkD528DPkgwQ",
    "NQE Overland": "UCN470oZHVqf3BYmqK-FzbqQ",
}

# Each channel's usual stomping grounds: fallback approximate location when a
# video title doesn't name a place. (lon, lat, region label)
YOUTUBE_CHANNEL_HOMES: dict[str, tuple[float, float, str]] = {
    "GoldenGully": (143.80, -36.70, "Golden Triangle VIC"),
    "Goldfields Goose": (121.47, -30.75, "WA Goldfields"),
    "Vo-Gus Prospecting": (144.28, -36.76, "Central VIC"),
    "Prospector Nic": (143.85, -37.56, "Ballarat VIC"),
    "PioneerPauly": (144.22, -37.06, "Central VIC"),
    "Tassie Boys Prospecting": (146.80, -41.50, "Tasmania"),
    "Australian Gold Detecting": (143.80, -36.70, "Golden Triangle VIC"),
    "Gold Rat Prospecting": (152.67, -26.19, "SE Queensland"),
    "NQE Overland": (146.26, -20.08, "North QLD"),
}

# --- Community ---
REDDIT_URL = (
    "https://www.reddit.com/r/Goldpanning+GoldProspecting+metaldetecting/new.json?limit=100"
)
COMMUNITY_KEYWORDS = r"found|nugget|detect|specimen|colour|color|pan|crevic|sluic"
COMMUNITY_AU_HINTS = (
    r"australia|victoria|ballarat|bendigo|golden triangle|wedderburn|dunolly|"
    r"kalgoorlie|goldfields|\bwa\b|\bnsw\b|\bvic\b|\bqld\b|queensland|tasmania|"
    r"\bnt\b|pilbara|clermont|gympie|hill end|ophir|araluen|leonora|laverton"
)
