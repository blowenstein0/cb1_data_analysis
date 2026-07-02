"""Per-entity precision/recall, per-field accuracy, vote-tally exact match.

CI gate thresholds (fail loudly):
  - vote tally exact-match must be 100% (tallies are the analytical core)
  - record recall must be >= 90% for every entity type present in golden
"""

from rapidfuzz import fuzz

from cb1.eval.matching import match_records, normalize, tallies_exact

ENTITY_TYPES = (
    "liquor_licenses", "votes", "public_speakers", "traffic_incidents",
    "cannabis_licenses",
)

# fields scored per entity (source_snippet excluded: traceability, not truth)
COMPARED_FIELDS = {
    "liquor_licenses": ("applicant_name", "dba", "address", "application_type",
                        "license_class", "committee_recommendation", "board_action"),
    "votes": ("topic_category", "outcome", "yes", "no", "abstain", "recusal"),
    "public_speakers": ("name", "affiliation", "position"),
    "traffic_incidents": ("victim_name", "location", "severity"),
    "cannabis_licenses": ("applicant_name", "address", "application_type"),
}

RECALL_THRESHOLD = 0.90
FUZZY_FIELD_THRESHOLD = 85


def field_correct(g, e) -> bool:
    if g is None and e is None:
        return True
    if isinstance(g, (int, bool)) or isinstance(e, (int, bool)):
        return g == e
    if isinstance(g, str) and isinstance(e, str):
        return fuzz.token_sort_ratio(normalize(g), normalize(e)) >= FUZZY_FIELD_THRESHOLD
    return g == e


def score_meeting(golden: dict, extracted: dict) -> dict:
    """Compare one golden meeting against one extraction."""
    out: dict = {"entities": {}, "tally_total": 0, "tally_exact": 0}
    for entity in ENTITY_TYPES:
        g_list = golden.get(entity, [])
        e_list = extracted.get(entity, [])
        if not g_list and not e_list:
            continue
        matches, un_g, un_e = match_records(g_list, e_list, entity)

        fields_total = fields_correct = 0
        field_errors = []
        for gi, ei, _score in matches:
            for f in COMPARED_FIELDS[entity]:
                fields_total += 1
                if field_correct(g_list[gi].get(f), e_list[ei].get(f)):
                    fields_correct += 1
                else:
                    field_errors.append(
                        f"{entity}[{gi}].{f}: golden={g_list[gi].get(f)!r} "
                        f"extracted={e_list[ei].get(f)!r}"
                    )
        if entity == "votes":
            for gi, ei, _score in matches:
                out["tally_total"] += 1
                out["tally_exact"] += tallies_exact(g_list[gi], e_list[ei])

        out["entities"][entity] = {
            "golden": len(g_list),
            "extracted": len(e_list),
            "matched": len(matches),
            "precision": len(matches) / len(e_list) if e_list else 1.0,
            "recall": len(matches) / len(g_list) if g_list else 1.0,
            "field_accuracy": fields_correct / fields_total if fields_total else 1.0,
            "missed": [_summary(g_list[i]) for i in un_g],
            "spurious": [_summary(e_list[i]) for i in un_e],
            "field_errors": field_errors,
        }
    return out


def _summary(record: dict) -> str:
    for k in ("applicant_name", "motion_text", "name", "victim_name", "location"):
        if record.get(k):
            return str(record[k])[:80]
    return str(record)[:80]


def aggregate(per_meeting: dict[str, dict]) -> dict:
    """Roll per-meeting scores into the corpus scorecard + pass/fail gate."""
    agg: dict = {"entities": {}, "tally_total": 0, "tally_exact": 0}
    for score in per_meeting.values():
        agg["tally_total"] += score["tally_total"]
        agg["tally_exact"] += score["tally_exact"]
        for entity, s in score["entities"].items():
            a = agg["entities"].setdefault(
                entity, {"golden": 0, "extracted": 0, "matched": 0,
                         "fields_correct": 0.0, "fields_total": 0}
            )
            a["golden"] += s["golden"]
            a["extracted"] += s["extracted"]
            a["matched"] += s["matched"]
            # weight field accuracy by matched records
            a["fields_correct"] += s["field_accuracy"] * s["matched"]
            a["fields_total"] += s["matched"]

    failures = []
    for entity, a in agg["entities"].items():
        a["precision"] = a["matched"] / a["extracted"] if a["extracted"] else 1.0
        a["recall"] = a["matched"] / a["golden"] if a["golden"] else 1.0
        a["field_accuracy"] = (
            a["fields_correct"] / a["fields_total"] if a["fields_total"] else 1.0
        )
        if a["golden"] and a["recall"] < RECALL_THRESHOLD:
            failures.append(
                f"{entity} recall {a['recall']:.0%} < {RECALL_THRESHOLD:.0%}"
            )
    tally_rate = (
        agg["tally_exact"] / agg["tally_total"] if agg["tally_total"] else 1.0
    )
    if tally_rate < 1.0:
        failures.append(
            f"vote tally exact-match {tally_rate:.0%} < 100% "
            f"({agg['tally_exact']}/{agg['tally_total']})"
        )
    agg["tally_exact_rate"] = tally_rate
    agg["failures"] = failures
    agg["passed"] = not failures
    return agg


def render(agg: dict, per_meeting: dict[str, dict]) -> str:
    lines = ["", "=" * 74, "EVAL SCORECARD", "=" * 74]
    lines.append(
        f"{'entity':<20} {'gold':>5} {'extr':>5} {'match':>5} "
        f"{'prec':>7} {'recall':>7} {'fields':>7}"
    )
    for entity, a in sorted(agg["entities"].items()):
        lines.append(
            f"{entity:<20} {a['golden']:>5} {a['extracted']:>5} {a['matched']:>5} "
            f"{a['precision']:>6.0%} {a['recall']:>6.0%} {a['field_accuracy']:>6.0%}"
        )
    lines.append(
        f"\nvote tallies exact: {agg['tally_exact']}/{agg['tally_total']} "
        f"({agg['tally_exact_rate']:.0%})"
    )
    for mid, s in per_meeting.items():
        misses = [
            f"    MISSED {entity}: {m}"
            for entity, es in s["entities"].items()
            for m in es["missed"]
        ]
        errors = [
            f"    {e}"
            for es in s["entities"].values()
            for e in es["field_errors"][:5]
        ]
        if misses or errors:
            lines.append(f"\n  {mid}:")
            lines.extend(misses + errors)
    lines.append("")
    if agg["passed"]:
        lines.append("PASS: all gates met")
    else:
        lines.append("FAIL:")
        lines.extend(f"  - {f}" for f in agg["failures"])
    lines.append("=" * 74)
    return "\n".join(lines)
