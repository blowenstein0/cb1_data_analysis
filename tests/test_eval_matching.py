from cb1.eval.matching import match_records, normalize, tallies_exact
from cb1.eval.scorecard import aggregate, score_meeting


def lic(name, addr, **kw):
    return {"applicant_name": name, "address": addr, **kw}


def vote(motion, y, n, a=0, r=0, **kw):
    return {
        "motion_text": motion, "yes": y, "no": n, "abstain": a, "recusal": r,
        "outcome": "passed" if y > n else "failed", **kw,
    }


def test_normalize_strips_ocr_noise():
    assert normalize("A VENUE  Bedford,  LLC.") == "a venue bedford llc"


def test_fuzzy_match_survives_ocr_typos():
    golden = [lic("Example Hospitality LLC", "123 Bedford Avenue")]
    extracted = [lic("Exampl e Hospitality LLC", "123 Bedford Ave nue")]  # OCR splits
    matches, un_g, un_e = match_records(golden, extracted, "liquor_licenses")
    assert len(matches) == 1
    assert not un_g and not un_e


def test_distinct_records_do_not_cross_match():
    golden = [
        lic("Alpha Bar LLC", "1 Main St"),
        lic("Beta Lounge Inc", "99 Other Ave"),
    ]
    extracted = [lic("Beta Lounge Inc", "99 Other Ave")]
    matches, un_g, un_e = match_records(golden, extracted, "liquor_licenses")
    assert len(matches) == 1
    assert matches[0][0] == 1  # matched the right golden record
    assert un_g == [0]


def test_greedy_matching_prefers_best_pair():
    golden = [lic("Cafe Roma", "10 Grand St"), lic("Cafe Roma II", "12 Grand St")]
    extracted = [lic("Cafe Roma II", "12 Grand St"), lic("Cafe Roma", "10 Grand St")]
    matches, _, _ = match_records(golden, extracted, "liquor_licenses")
    assert sorted((g, e) for g, e, _ in matches) == [(0, 1), (1, 0)]


def test_tallies_exact():
    assert tallies_exact(vote("m", 25, 0), vote("m", 25, 0))
    assert not tallies_exact(vote("m", 25, 0), vote("m", 25, 1))
    assert not tallies_exact(vote("m", 25, 0, a=1), vote("m", 25, 0, a=0))


def test_score_meeting_precision_recall():
    golden = {
        "votes": [vote("approve SLA report", 30, 2), vote("approve land use item", 28, 0)],
        "liquor_licenses": [lic("A", "1 St"), lic("B", "2 St")],
    }
    extracted = {
        "votes": [vote("approve the SLA committee report", 30, 2)],  # 1 of 2, tallies right
        "liquor_licenses": [lic("A", "1 St"), lic("B", "2 St"), lic("C", "3 St")],
    }
    s = score_meeting(golden, extracted)
    assert s["entities"]["votes"]["recall"] == 0.5
    assert s["entities"]["liquor_licenses"]["precision"] == 2 / 3
    assert s["entities"]["liquor_licenses"]["recall"] == 1.0
    assert s["tally_total"] == 1 and s["tally_exact"] == 1
    assert s["entities"]["liquor_licenses"]["spurious"] == ["C"]


def test_gate_fails_on_imperfect_tallies():
    golden = {"votes": [vote("motion one", 25, 0)]}
    extracted = {"votes": [vote("motion one", 24, 0)]}  # off-by-one tally
    agg = aggregate({"m": score_meeting(golden, extracted)})
    assert not agg["passed"]
    assert any("tally" in f for f in agg["failures"])


def test_gate_fails_on_low_recall():
    golden = {"liquor_licenses": [lic(f"A{i}", f"{i} St") for i in range(10)]}
    extracted = {"liquor_licenses": [lic(f"A{i}", f"{i} St") for i in range(8)]}
    agg = aggregate({"m": score_meeting(golden, extracted)})
    assert not agg["passed"]
    assert any("recall" in f for f in agg["failures"])


def test_gate_passes_when_clean():
    golden = {"votes": [vote("motion one", 25, 0)]}
    extracted = {"votes": [vote("motion one", 25, 0)]}
    agg = aggregate({"m": score_meeting(golden, extracted)})
    assert agg["passed"]
    assert agg["tally_exact_rate"] == 1.0
