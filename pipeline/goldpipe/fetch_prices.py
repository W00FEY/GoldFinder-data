"""Daily gold / silver / oil prices in AUD.

Yahoo Finance's keyless chart API supplies USD futures closes (COMEX gold
and silver, NYMEX WTI crude) plus the AUD/USD rate; we forward-fill the FX
series across trading-calendar gaps and convert each close to AUD. Fail-soft
like every other section — on any error the previous prices.json stays in
place marked stale.
"""
from datetime import datetime, timezone

from . import config
from .http import get_json

SYMBOLS = {
    "gold": "GC=F",
    "silver": "SI=F",
    "oil": "CL=F",
}
FX_SYMBOL = "AUDUSD=X"
UNITS = {
    "gold_aud": "AUD/oz",
    "silver_aud": "AUD/oz",
    "oil_aud": "AUD/barrel",
}


def _closes(symbol: str) -> dict[str, float]:
    """date (YYYY-MM-DD, UTC) -> daily close for one Yahoo symbol."""
    data = get_json(
        config.YAHOO_CHART.format(symbol=symbol),
        params={"range": config.PRICES_RANGE, "interval": "1d"},
    )
    result = data["chart"]["result"][0]
    stamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    out: dict[str, float] = {}
    for ts, close in zip(stamps, closes):
        if close is None:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        out[day] = float(close)
    return out


def to_aud(usd: dict[str, float], fx: dict[str, float]) -> list[list]:
    """[[date, AUD value], ...] sorted by date; FX forward-filled across
    mismatched trading holidays. Days before the first FX quote are dropped."""
    out: list[list] = []
    rate = None
    for day in sorted(set(usd) | set(fx)):
        rate = fx.get(day, rate)
        if rate and day in usd:
            out.append([day, round(usd[day] / rate, 2)])
    return out


def fetch_prices() -> dict | None:
    """The prices.json payload, or None if Yahoo is unreachable."""
    try:
        fx = _closes(FX_SYMBOL)
        if not fx:
            return None
        series: dict[str, list[list]] = {}
        latest: dict[str, float] = {}
        for name, symbol in SYMBOLS.items():
            usd = _closes(symbol)
            aud = to_aud(usd, fx)
            if not aud:
                return None
            series[f"{name}_aud"] = aud
            latest[f"{name}_usd"] = round(usd[max(usd)], 2)
            latest[f"{name}_aud"] = aud[-1][1]
        latest["aud_usd"] = round(fx[max(fx)], 4)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {
            "schema_version": config.SCHEMA_VERSION,
            "updated_at": now.isoformat().replace("+00:00", "Z"),
            "units": UNITS,
            "latest": latest,
            "series": series,
        }
    except Exception as e:  # noqa: BLE001
        print(f"[prices] FAILED: {e}")
        return None
