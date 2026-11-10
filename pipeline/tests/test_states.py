from goldpipe.fetch_news import dedupe_stories
from goldpipe.fetch_states import aggregate, merge, normalize, site_weight


def _raw(num, lon, lat, name="", commodity="Au", kind="mineral deposit"):
    return {
        "id": f"er.mineraloccurrence.{num}",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": name, "commodity": commodity, "earthResourceType": kind},
    }


def test_normalize_keeps_gold_and_real_names_only():
    r = normalize(_raw("S1", 121.5, -30.7, "Lucky Strike", "Au,Ag"), "gswa")
    assert r["name"] == "Lucky Strike" and r["commodity"] == "Gold, Silver"
    assert normalize(_raw("S2", 121.5, -30.7, "WABMINES AMB1"), "gswa")["name"] == ""
    # '%Au%' matched a non-gold code: dropped.
    assert normalize(_raw("S3", 121.5, -30.7, commodity="Bauxite"), "gswa") is None
    # Outside Australia: dropped.
    assert normalize(_raw("S4", 10.0, 50.0), "gswa") is None
    n = normalize(_raw("101", 147.0, -33.0, "er.mineraloccurrence.101", "copper,gold",
                       "http://x/mineral-occurrence-type/occurrence"), "gsnsw")
    assert n["name"] == "" and n["occ_type"] == "occurrence" and n["commodity"] == "Copper, Gold"


def test_aggregate_folds_a_cluster_into_one_named_site():
    recs = [normalize(_raw(f"S{i:03d}", 121.5001 + i * 1e-5, -30.7001, "WABMINES X"), "gswa")
            for i in range(50)]
    recs.append(normalize(_raw("S900", 121.5002, -30.7002, "Golden Mile"), "gswa"))
    recs.append(normalize(_raw("S950", 122.9, -31.9), "gswa"))
    sites = aggregate(recs, "gswa")
    assert len(sites) == 2
    big = next(s for s in sites if s["properties"].get("sites"))["properties"]
    assert big["id"] == "gswa.S900" and big["name"] == "Golden Mile" and big["sites"] == 51
    assert big["weight"] == site_weight(51) > site_weight(1)
    lone = next(s for s in sites if "sites" not in s["properties"])["properties"]
    assert lone["name"] == "WA gold deposit #S950" and lone["src"] == "gswa"


def test_weight_is_capped():
    assert site_weight(1) == 0.35
    assert site_weight(10**9) == 3.0


def test_merge_drops_sites_already_in_the_national_database():
    national = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [121.5, -30.7]},
                 "properties": {"id": "oz.1"}}]
    sites = aggregate([normalize(_raw("S1", 121.5003, -30.7), "gswa"),
                       normalize(_raw("S2", 121.6, -30.7), "gswa")], "gswa")
    assert [f["properties"]["id"] for f in merge(national, sites)] == ["gswa.S2", "oz.1"]


def test_news_keeps_one_article_per_story_preferring_australian():
    def art(title, au, when):
        return {"title": title, "australian": au, "posted_at": when, "url": title}
    out = dedupe_stories([
        art("Australian man digs up gold nugget worth over $150,000 after spotting yellow dot", False, "2026-10-27T07:00:00Z"),
        art("Prospector digs up $150,000 gold nugget after spotting yellow dot in dirt", True, "2026-10-28T07:00:00Z"),
        art("Fossicking season opens in Bendigo", True, "2026-10-20T07:00:00Z"),
    ])
    assert [r["title"][:10] for r in out] == ["Prospector", "Fossicking"]
