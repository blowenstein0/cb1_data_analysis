import pytest
from pydantic import ValidationError

from cb1.models import (
    LLMExtraction,
    MeetingExtraction,
    Vote,
    format_validation_error,
)

VALID = {
    "meeting": {
        "meeting_id": "cb1-2023-06-13",
        "date": "2023-06-13",
        "meeting_type": "combined",
        "location_or_platform": "211 Ainslie Street",
        "attendance_count": 32,
        "quorum_noted": True,
        "chair": "Dealice Fuller",
        "source_files": ["Combined-Public-Hearing-Board-Meeting-Minutes-06-13-2023.pdf"],
    },
    "liquor_licenses": [
        {
            "applicant_name": "Example LLC",
            "dba": "The Spot",
            "address": "123 Bedford Ave",
            "application_type": "new",
            "license_class": "OP",
            "features": ["sidewalk_cafe"],
            "committee_recommendation": "approve with stipulations",
            "board_action": "approved",
            "source_snippet": "Example LLC dba The Spot, 123 Bedford Ave...",
        }
    ],
    "votes": [
        {
            "motion_text": "Motion to approve the SLA committee report",
            "topic_category": "liquor",
            "mover": "P. Smith",
            "yes": 30,
            "no": 2,
            "abstain": 1,
            "recusal": 0,
            "outcome": "passed",
            "source_snippet": "30 in favor, 2 opposed, 1 abstention",
        }
    ],
    "public_speakers": [],
    "traffic_incidents": [],
    "cannabis_licenses": [],
}


def test_llm_extraction_valid_payload():
    ex = LLMExtraction.model_validate(VALID)
    assert ex.meeting.date == "2023-06-13"
    assert ex.votes[0].yes == 30
    assert ex.liquor_licenses[0].application_type == "new"


def test_meeting_extraction_requires_meta():
    with pytest.raises(ValidationError):
        MeetingExtraction.model_validate(VALID)
    full = {
        **VALID,
        "extraction_meta": {
            "model": "claude-haiku-4-5",
            "text_source": "native",
            "pages_minutes_body": 12,
            "pages_attachments_dropped": 30,
            "input_tokens": 20000,
            "output_tokens": 3000,
            "cost_usd": 0.035,
        },
    }
    ex = MeetingExtraction.model_validate(full)
    assert ex.extraction_meta.text_source == "native"


def test_bad_date_rejected():
    bad = {**VALID, "meeting": {**VALID["meeting"], "date": "6/13/23"}}
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        LLMExtraction.model_validate(bad)


def test_negative_tally_rejected():
    with pytest.raises(ValidationError):
        Vote(
            motion_text="m",
            yes=-1,
            no=0,
            abstain=0,
            recusal=0,
            outcome="passed",
            source_snippet="s",
        )


def test_unknown_enum_rejected():
    bad = {**VALID, "votes": [{**VALID["votes"][0], "topic_category": "zoning"}]}
    with pytest.raises(ValidationError):
        LLMExtraction.model_validate(bad)


def test_defaults_fill_optional_sections():
    minimal = {"meeting": {"meeting_id": "cb1-2016-01-12", "date": "2016-01-12"}}
    ex = LLMExtraction.model_validate(minimal)
    assert ex.votes == []
    assert ex.meeting.meeting_type == "combined"


def test_format_validation_error_includes_raw_and_errors():
    try:
        LLMExtraction.model_validate({"meeting": {"date": "nope"}})
    except ValidationError as e:
        msg = format_validation_error('{"meeting": {"date": "nope"}}', e)
    assert "failed schema validation" in msg
    assert "nope" in msg
    assert "meeting_id" in msg  # missing-field error is surfaced
