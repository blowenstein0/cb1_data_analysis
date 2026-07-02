"""Fuzzy record matching between golden and extracted entities.

Records are matched greedily on a per-entity fuzzy key (best score first),
so OCR noise and paraphrase don't break the pairing; FIELD comparison
happens after pairing, in scorecard.py.
"""

import re

from rapidfuzz import fuzz

MATCH_THRESHOLD = 75


def normalize(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


KEY_FNS = {
    "liquor_licenses": lambda r: normalize(f"{r.get('applicant_name')} {r.get('address')}"),
    "cannabis_licenses": lambda r: normalize(f"{r.get('applicant_name')} {r.get('address')}"),
    "votes": lambda r: normalize(r.get("motion_text")),
    "public_speakers": lambda r: normalize(f"{r.get('name')} {r.get('topic')}"),
    "traffic_incidents": lambda r: normalize(f"{r.get('victim_name')} {r.get('location')}"),
}


def match_records(
    golden: list[dict], extracted: list[dict], entity: str, threshold: int = MATCH_THRESHOLD
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """Greedy best-score bipartite matching on the entity's fuzzy key.

    Returns (matches as (golden_idx, extracted_idx, score),
             unmatched golden indices, unmatched extracted indices).
    """
    key = KEY_FNS[entity]
    gkeys = [key(r) for r in golden]
    ekeys = [key(r) for r in extracted]

    # token_set_ratio: paraphrase tolerance ("approve SLA report" matches
    # "approve the SLA committee report"); greedy best-first keeps near
    # duplicates from cross-matching
    scored = [
        (fuzz.token_set_ratio(gk, ek), gi, ei)
        for gi, gk in enumerate(gkeys)
        for ei, ek in enumerate(ekeys)
        if gk and ek
    ]
    scored.sort(reverse=True)

    used_g: set[int] = set()
    used_e: set[int] = set()
    matches = []
    for score, gi, ei in scored:
        if score < threshold:
            break
        if gi in used_g or ei in used_e:
            continue
        matches.append((gi, ei, score))
        used_g.add(gi)
        used_e.add(ei)

    unmatched_g = [i for i in range(len(golden)) if i not in used_g]
    unmatched_e = [i for i in range(len(extracted)) if i not in used_e]
    return matches, unmatched_g, unmatched_e


def tallies_exact(golden_vote: dict, extracted_vote: dict) -> bool:
    return all(
        int(golden_vote.get(k, 0)) == int(extracted_vote.get(k, 0))
        for k in ("yes", "no", "abstain", "recusal")
    )
