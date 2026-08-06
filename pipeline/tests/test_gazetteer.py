from goldpipe.gazetteer import locate


def test_matches_wa_goldfields():
    hit = locate("Z13 is Mint | GPZ 8000 | WA GOLDFIELDS")
    assert hit is not None
    lon, lat, place = hit
    assert place == "Wa Goldfields"
    assert abs(lon - 121.47) < 0.1 and abs(lat + 30.75) < 0.1


def test_matches_town():
    hit = locate("Found a 2 gram nugget near Dunolly today")
    assert hit is not None
    assert hit[2] == "Dunolly"


def test_longest_match_wins():
    # "golden triangle" must not be swallowed by any shorter entry.
    hit = locate("Detecting the Golden Triangle again")
    assert hit is not None
    assert hit[2] == "Golden Triangle"


def test_word_boundaries():
    # "cue"/"young"-style substrings were removed; ensure no match inside words.
    assert locate("Rescued a kangaroo today, no gold sorry") is None


def test_no_match_returns_none():
    assert locate("My favourite detector settings explained") is None
