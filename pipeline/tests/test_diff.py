from datetime import date, timedelta

from goldpipe.diff import diff_community, diff_occurrences


def _feat(oid, name="Spot"):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [143.0, -36.0]},
        "properties": {
            "id": oid, "name": name, "occ_type": "occurrence",
            "commodity": "Gold", "deposit_model": None, "url": None,
        },
    }


def test_first_run_seeds_without_flagging_new():
    new, state = diff_occurrences([_feat("a"), _feat("b")], {"ids": {}, "community": {}}, date(2026, 8, 5))
    assert new == []
    assert set(state["ids"]) == {"a", "b"}


def test_second_run_flags_only_new_ids():
    today = date(2026, 8, 5)
    _, state = diff_occurrences([_feat("a")], {"ids": {}, "community": {}}, today - timedelta(days=1))
    new, state = diff_occurrences([_feat("a"), _feat("b")], state, today)
    assert [f["properties"]["id"] for f in new] == ["b"]
    assert new[0]["properties"]["first_seen"] == today.isoformat()


def test_recent_new_ids_stay_in_window():
    today = date(2026, 8, 5)
    _, state = diff_occurrences([_feat("a")], {"ids": {}, "community": {}}, today - timedelta(days=30))
    _, state = diff_occurrences([_feat("a"), _feat("b")], state, today - timedelta(days=10))
    new, _ = diff_occurrences([_feat("a"), _feat("b")], state, today)
    assert [f["properties"]["id"] for f in new] == ["b"]
    assert new[0]["properties"]["first_seen"] == (today - timedelta(days=10)).isoformat()


def test_old_ids_expire_from_window():
    today = date(2026, 8, 5)
    _, state = diff_occurrences([_feat("a")], {"ids": {}, "community": {}}, today - timedelta(days=200))
    _, state = diff_occurrences([_feat("a"), _feat("b")], state, today - timedelta(days=120))
    new, _ = diff_occurrences([_feat("a"), _feat("b")], state, today)
    assert new == []


def test_community_diff_preserves_first_seen_and_trims():
    today = date(2026, 8, 5)
    r = {"id": "u1", "url": "u1", "title": "t", "source": "reddit",
         "posted_at": "2026-08-01T00:00:00Z", "lat": None, "lon": None}
    out, state = diff_community([r], {"ids": {}, "community": {}}, today - timedelta(days=5))
    out, state = diff_community([r], state, today)
    assert out[0]["first_seen"] == (today - timedelta(days=5)).isoformat()
    state["community"]["old"] = (today - timedelta(days=120)).isoformat()
    out, state = diff_community([r], state, today)
    assert "old" not in state["community"]
