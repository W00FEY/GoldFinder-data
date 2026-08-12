from goldpipe.fetch_prices import to_aud


def test_conversion_divides_by_fx():
    usd = {"2026-08-10": 2400.0}
    fx = {"2026-08-10": 0.66}
    out = to_aud(usd, fx)
    assert out == [["2026-08-10", round(2400.0 / 0.66, 2)]]


def test_fx_forward_fills_across_holidays():
    usd = {"2026-08-10": 100.0, "2026-08-11": 110.0}
    fx = {"2026-08-10": 0.5}  # FX market closed on the 11th
    out = to_aud(usd, fx)
    assert out == [["2026-08-10", 200.0], ["2026-08-11", 220.0]]


def test_days_before_first_fx_quote_are_dropped():
    usd = {"2026-08-09": 100.0, "2026-08-10": 100.0}
    fx = {"2026-08-10": 0.5}
    out = to_aud(usd, fx)
    assert [d for d, _ in out] == ["2026-08-10"]


def test_sorted_by_date():
    usd = {"2026-08-11": 1.0, "2026-08-09": 1.0, "2026-08-10": 1.0}
    fx = {"2026-08-09": 1.0}
    out = to_aud(usd, fx)
    assert [d for d, _ in out] == ["2026-08-09", "2026-08-10", "2026-08-11"]
