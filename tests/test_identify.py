from datetime import date

from cb1.grouping import parse_href
from cb1.identify import identify_from_text, resolve_file

CLEAN_HEADER = """
COMMUNITY BOARD NO. 1
MINUTES OF THE COMBINED PUBLIC HEARING AND BOARD MEETING
HELD ON TUESDAY, SEPTEMBER 12, 2023 AT 6:30 PM
"""

# 2019-era embedded OCR: broken words, stray line breaks
DIRTY_OCR_HEADER = """
C OMMUNITY B OARD N O. 1
MINUTES OF THE COMBINED PUBLIC HEARING AND BOARD MEETING
HELD ON TUESDAY, FEBRUARY
12, 2019 AT 6:30 PM
"""

NUMERIC_HEADER = "Board Meeting Minutes 6/24/2020 held via WebEx"

SPECIAL_HEADER = "MINUTES OF THE SPECIAL FULL BOARD MEETING HELD JUNE 12, 2023"


def test_clean_header():
    d, mtype = identify_from_text(CLEAN_HEADER)
    assert d == date(2023, 9, 12)
    assert mtype == "combined"


def test_dirty_ocr_header_date_survives_linebreak():
    d, mtype = identify_from_text(DIRTY_OCR_HEADER)
    assert d == date(2019, 2, 12)
    assert mtype == "combined"


def test_numeric_date_and_bare_board_meeting():
    d, mtype = identify_from_text(NUMERIC_HEADER)
    assert d == date(2020, 6, 24)
    assert mtype == "other"


def test_special_meeting_type():
    d, mtype = identify_from_text(SPECIAL_HEADER)
    assert d == date(2023, 6, 12)
    assert mtype == "special"


LETTERHEAD_TRANSMITTAL = """
PHILIP A. CAPONEGRO MEMBER-AT-LARGE
October 28, 2024
COMBINED PUBLIC HEARING AND BOARD MEETING
211 AINSLIE STREET
OCTOBER 8, 2024
PUBLIC HEARING ROLL CALL
"""


def test_transmittal_date_before_title_is_skipped():
    # real case from Pages-from-Minutes-1.pdf: letterhead carries a
    # transmittal date before the title; the meeting date follows the title
    d, mtype = identify_from_text(LETTERHEAD_TRANSMITTAL)
    assert d == date(2024, 10, 8)
    assert mtype == "combined"


def test_no_date_returns_none():
    d, mtype = identify_from_text("completely scanned page, no text layer")
    assert d is None


def test_resolve_content_wins_over_filename():
    ref = parse_href("/x/Combined-Public-Hearing-Board-Meeting-Minutes-09-10-24.pdf")
    r = resolve_file(ref, {"date": "2024-09-11", "meeting_type": "combined", "method": "text"})
    assert r["date"] == "2024-09-11"
    assert r["date_source"] == "content"
    assert any("mismatch" in w for w in r["warnings"])


def test_resolve_agreement_is_full_confidence():
    ref = parse_href("/x/Combined-Public-Hearing-Board-Meeting-Minutes-09-10-24.pdf")
    r = resolve_file(ref, {"date": "2024-09-10", "meeting_type": "combined", "method": "text"})
    assert r["date_confidence"] == 1.0


def test_resolve_content_fills_ym_only_filename():
    ref = parse_href("/x/minutes-202111.pdf")  # year-month only
    r = resolve_file(ref, {"date": "2021-11-09", "meeting_type": "combined", "method": "text"})
    assert r["date"] == "2021-11-09"
    assert r["date_source"] == "content"


def test_resolve_filename_fallback_when_content_blank():
    ref = parse_href("/x/Combined-Public-Hearing-Board-Meeting-Minutes-10-13-16.pdf")
    r = resolve_file(ref, {"date": None, "meeting_type": None, "method": "text"})
    assert r["date"] == "2016-10-13"
    assert r["date_source"] == "filename"
    assert r["date_confidence"] == 0.5


def test_resolve_filename_hint_beats_content_type():
    # standalone public hearing whose page 1 says "combined" boilerplate
    ref = parse_href("/x/Public-Hearing-Meeting-Minutes-01-20-26.pdf")
    r = resolve_file(ref, {"date": "2026-01-20", "meeting_type": "combined", "method": "text"})
    assert r["meeting_type"] == "public_hearing"
