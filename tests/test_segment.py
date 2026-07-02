"""Heuristics tested on page-text patterns lifted from the real corpus."""

from cb1.segment import classify_page, classify_pages, needs_ocr_first

LETTERHEAD_BODY = """COMMUNITY BOARD No. 1
435 GRAHAM AVENUE - BROOKLYN, NY 11211-8813
PHONE: (718) 389-0009
COMBINED PUBLIC HEARING AND BOARD MEETING
211 AINSLIE STREET OCTOBER 8, 2024
PUBLIC HEARING ROLL CALL The meeting was called to order at 6:08 PM by Chairperson Fuller.
"""

NARRATIVE_BODY = (
    "6 Mr. Chesler requested a motion to recommend the board submit a comment as "
    "written to NYC OER. The motion was seconded by Ms. Teague. The vote was 25 "
    "Yes, 0 No, 0 Abstentions, 0 Recusals. Motion carried. LAND USE, ULURP AND "
    "LANDMARKS COMMITTEE - Ms. Del Teague, Committee Chair, report as written. "
    "SLA REVIEW COMMITTEE - Mr. Arthur Askins, Committee Chair. OLD BUSINESS was "
    "discussed at length by the chairperson and the district manager regarding "
    "the agenda for next month including a presentation from the Department of "
    "Sanitation about residential containerization and composting programs. "
    "NEW BUSINESS included a discussion of the upcoming budget priorities and "
    "several members raised concerns about traffic safety on Metropolitan Avenue."
)

VOTE_SHEET = (
    "DATE: YES NO ABS REC YES NO ABS REC X X X X X X X X X X X X X X X X X X "
    "X X X X X X X TIME: 25 25 YES 0 NO 0 ABS"
)

ROLL_CALL_SHEET = "ROLL ROLL ROLL CALL CALL CALL 1ST 2ND 3RD GINA ARGENTO BOGDAN X X"

QUESTIONNAIRE = (
    "Brooklyn Community Board #1 Liquor License Application Questionnaire "
    "APPLICANT DOING BUSINESS AS (DBA) Corp to be formed"
)

RESIDENT_LETTER = (
    "Dear Chairperson Fuller, I am writing to express my strong opposition to "
    "the proposed liquor license at 123 Bedford Avenue. The noise from this "
    "establishment has been unbearable. Sincerely, A. Resident"
)

SLIDE_PAGE = "IBZ Tree Advocacy Project SEPTEMBER 2024 WILLIS ELKINS ADDRESS: 520 Kingsland Ave"


def test_letterhead_section_start_is_body():
    label, conf = classify_page(LETTERHEAD_BODY)
    assert label == "body"
    assert conf >= 0.9


def test_dense_narrative_is_body():
    label, _ = classify_page(NARRATIVE_BODY)
    assert label == "body"


def test_vote_sheet_by_tally_header():
    assert classify_page(VOTE_SHEET)[0] == "vote_sheet"


def test_vote_sheet_by_roll_call_columns():
    assert classify_page(ROLL_CALL_SHEET)[0] == "vote_sheet"


def test_questionnaire_is_attachment():
    assert classify_page(QUESTIONNAIRE)[0] == "attachment"


def test_resident_letter_is_attachment():
    assert classify_page(RESIDENT_LETTER)[0] == "attachment"


def test_sparse_slide_is_attachment():
    assert classify_page(SLIDE_PAGE)[0] == "attachment"


def test_blank_page():
    assert classify_page("  \n ")[0] == "blank"


def test_smoothing_fills_sandwiched_ambiguous_page():
    ambiguous = "General discussion continued regarding the project timeline."
    labels = classify_pages([LETTERHEAD_BODY, ambiguous, NARRATIVE_BODY])
    assert [p["label"] for p in labels] == ["body", "body", "body"]
    assert labels[1].get("smoothed")


def test_no_smoothing_across_different_neighbors():
    ambiguous = "General discussion continued regarding the project timeline."
    labels = classify_pages([LETTERHEAD_BODY, ambiguous, QUESTIONNAIRE, VOTE_SHEET])
    assert labels[1]["label"] != "body" or not labels[1].get("smoothed")


def test_needs_ocr_first_on_pure_scan():
    assert needs_ocr_first(["", "", "", ""])
    assert not needs_ocr_first([NARRATIVE_BODY] * 3 + [""])
