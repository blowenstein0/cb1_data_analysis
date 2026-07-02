"""Grouping logic tested against the REAL 138 hrefs scraped from nyc.gov."""

from datetime import date
from pathlib import Path

import pytest

from cb1.grouping import group_files, parse_href

FIXTURE = Path(__file__).parent / "fixtures" / "index_hrefs.txt"


@pytest.fixture(scope="module")
def refs():
    hrefs = [line.strip() for line in FIXTURE.read_text().splitlines() if line.strip()]
    assert len(hrefs) == 138
    return [parse_href(h) for h in hrefs]


@pytest.fixture(scope="module")
def grouped(refs):
    return group_files(refs)


# ---- date parsing: one case per real-world format ----

@pytest.mark.parametrize(
    "filename,expected_date,expected_ym",
    [
        ("jan2016.pdf", None, (2016, 1)),  # month-abbrev + year, no day
        ("minutes-202111.pdf", None, (2021, 11)),  # YYYYMM, no day
        ("minutes-20221109.pdf", date(2022, 11, 9), None),  # YYYYMMDD
        ("Combined-Public-Hearing-Board-Meeting-Minutes-10-13-16.pdf", date(2016, 10, 13), None),
        ("combined_ph_and__bd_minutes_2_15_17.pdf", date(2017, 2, 15), None),
        ("combined ph and bd mtg minutes 9_18_17.pdf", date(2017, 9, 18), None),
        (  # MDYYYY concatenated
            "combined_public_hearing_and_bd_meeting_minutes_292021_with_signatures_attachments_and_agenda.pdf",
            date(2021, 2, 9),
            None,
        ),
        (
            "Combined-Public-Hearing-Board-Meeting-Minutes-December-19-2023-full.pdf",
            date(2023, 12, 19),
            None,
        ),
        ("board_meeting_minutes_june_24_2020_with_attachments.pdf", date(2020, 6, 24), None),
        ("combined_public_hearing_and_board_meeting_minutes_9-8-2020_with_attachments.pdf", date(2020, 9, 8), None),
        ("03-12-24-Public-Hearing-Minutes.pdf", date(2024, 3, 12), None),
        ("Pages-from-Minutes-3.pdf", None, None),  # undated fragment
    ],
)
def test_date_parsing(filename, expected_date, expected_ym):
    ref = parse_href(f"/assets/brooklyncb1/downloads/pdf/{filename}")
    assert ref.date_guess == expected_date
    assert ref.year_month_guess == expected_ym


# ---- part + revised parsing ----

def test_explicit_part_numbers():
    r = parse_href("/x/Combined-Public-Hearing-Board-Meeting-Minutes-05-13-25-Part-1.pdf")
    assert (r.date_guess, r.part_no, r.is_revised) == (date(2025, 5, 13), 1, False)


def test_bare_trailing_part_number_after_date():
    r = parse_href(
        "/x/Pages-from-Combined-Public-Hearing-and-Board-Meeting-Minutes-12-10-24-2.pdf"
    )
    assert (r.date_guess, r.part_no) == (date(2024, 12, 10), 2)


def test_trailing_year_digit_is_not_a_part():
    r = parse_href("/x/Combined-Public-Hearing-Board-Meeting-Minutes-06-13-2023.pdf")
    assert r.part_no is None


def test_undated_fragment_keeps_part_number():
    r = parse_href("/x/Pages-from-Minutes-4.pdf")
    assert (r.date_guess, r.year_month_guess, r.part_no) == (None, None, 4)


@pytest.mark.parametrize(
    "filename",
    [
        "REVISED-Combined-Public-Hearing-Board-Meeting-Minutes-03-11-25.pdf",
        "combined_public_hearing_board_mtg_minutes_6_13_17_revised.pdf",
        "Combined-Public-Hearing-and-Board-Meeting-Minutes-6-7-22-rev.pdf",
        "Combined-Public-Hearing-Board-Meeting-Minutes-12-06-16-REVISED.pdf",
    ],
)
def test_revised_detection(filename):
    assert parse_href(f"/x/{filename}").is_revised


# ---- doc type hints ----

@pytest.mark.parametrize(
    "filename,hint",
    [
        ("Special-Meeting-Select-New-District-Manager-CB1-March-21-2023-Minutes.pdf", "special"),
        ("Special-Full-Board-Minutes-6-12-23.pdf", "special"),
        ("land_use_committee_held_ph_6_6_17_minutes.pdf", "committee"),
        ("Public-Hearing-Meeting-Minutes-01-20-26.pdf", "public_hearing"),
        ("Limited-Public-Hearing-Minutes-8-09-16.pdf", "public_hearing"),
        ("Combined-Public-Hearing-Board-Meeting-Minutes-02-10-26.pdf", "combined"),
        ("Combine_Public_Hearing_and_Board_Meeting_Minutes_2-8-22.pdf", "combined"),
        ("minutes-20221206.pdf", "unknown"),
    ],
)
def test_doc_type_hint(filename, hint):
    assert parse_href(f"/x/{filename}").doc_type_hint == hint


# ---- full-corpus grouping invariants ----

def test_only_the_five_pages_from_fragments_are_unresolved(grouped):
    _, unresolved = grouped
    names = sorted(r.filename for r in unresolved)
    assert names == [f"Pages-from-Minutes-{i}.pdf" for i in range(1, 6)]


def test_every_dated_file_lands_in_a_group(grouped, refs):
    groups, unresolved = grouped
    assert sum(len(g.parts) for g in groups) + len(unresolved) == len(refs)


def test_multipart_stitch_cases(grouped):
    groups, _ = grouped
    by_id = {g.group_id: g for g in groups}

    # plain Part-1 + REVISED Part-2 -> both kept, group marked revised
    g = by_id["cb1-2025-05-13"]
    assert [p.part_no for p in g.parts] == [1, 2]
    assert [p.is_revised for p in g.parts] == [False, True]
    assert g.is_revised

    # REVISED Part-1 + plain Parts 2-4
    g = by_id["cb1-2025-10-21"]
    assert [p.part_no for p in g.parts] == [1, 2, 3, 4]
    assert [p.is_revised for p in g.parts] == [True, False, False, False]

    # REVISED Parts 1-2 + plain Parts 3-5
    g = by_id["cb1-2026-05-12"]
    assert [p.part_no for p in g.parts] == [1, 2, 3, 4, 5]

    # bare trailing part numbers, mixed dirs and casing
    g = by_id["cb1-2024-12-10"]
    assert [p.part_no for p in g.parts] == [1, 2, 3]

    # 5 explicit parts
    g = by_id["cb1-2026-06-09"]
    assert [p.part_no for p in g.parts] == [1, 2, 3, 4, 5]


def test_single_part_meetings_group_alone(grouped):
    groups, _ = grouped
    by_id = {g.group_id: g for g in groups}
    g = by_id["cb1-2023-06-13"]
    assert len(g.parts) == 1
    assert g.parts[0].part_no is None


def test_year_month_only_groups_exist(grouped):
    groups, _ = grouped
    by_id = {g.group_id: g for g in groups}
    assert len(by_id["cb1-2016-01"].parts) == 1  # jan2016.pdf
    assert len(by_id["cb1-2021-11"].parts) == 1  # minutes-202111.pdf


def test_group_count_in_expected_range(grouped):
    groups, _ = grouped
    # ~110 logical meetings from 138 files
    assert 100 <= len(groups) <= 120
