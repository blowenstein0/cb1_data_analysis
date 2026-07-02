import json

import pytest
from pydantic import ValidationError

from cb1.extract import (
    SYSTEM_PROMPT,
    build_user_prompt,
    finalize,
    parse_llm_extraction,
    strip_fences,
    system_blocks,
)
from cb1.models import LLMExtraction

MEETING = {
    "meeting_id": "cb1-2023-06-13",
    "date": "2023-06-13",
    "meeting_type": "combined",
    "date_source": "content",
    "date_confidence": 1.0,
    "is_revised": False,
    "files": [{"local": "minutes.pdf", "sha256": "x", "part_no": None, "is_revised": False}],
    "warnings": [],
}

LLM_JSON = {
    "meeting": {
        "meeting_id": "cb1-2023-06-13",
        "date": "2023-06-14",  # wrong on purpose: model drift
        "meeting_type": "combined",
        "attendance_count": 31,
        "chair": "Dealice Fuller",
    },
    "votes": [
        {
            "motion_text": "Approve SLA committee report",
            "topic_category": "liquor",
            "yes": 25, "no": 0, "abstain": 0, "recusal": 0,
            "outcome": "passed",
            "source_snippet": "The vote was 25 Yes, 0 No",
        }
    ],
}


def test_parse_strips_markdown_fences():
    raw = "```json\n" + json.dumps(LLM_JSON) + "\n```"
    ex = parse_llm_extraction(raw)
    assert ex.votes[0].yes == 25


def test_parse_rejects_garbage():
    with pytest.raises(ValidationError):
        parse_llm_extraction('{"meeting": {"date": "not-a-date"}}')


def test_finalize_pins_identity_to_manifest():
    llm = LLMExtraction.model_validate(LLM_JSON)
    ex = finalize(MEETING, llm, {"pages_body": 10, "pages_dropped": 300, "ocr_pages": 0})
    assert ex.meeting.date == "2023-06-13"  # manifest wins over model drift
    assert ex.meeting.source_files == ["minutes.pdf"]
    assert any("pinned to manifest" in w for w in ex.extraction_meta.warnings)
    assert ex.extraction_meta.pages_attachments_dropped == 300
    assert ex.extraction_meta.text_source == "native"


def test_finalize_text_source_vision():
    llm = LLMExtraction.model_validate(LLM_JSON)
    meeting_2016 = {**MEETING, "meeting_id": "cb1-2016-01-12", "date": "2016-01-12"}
    ex = finalize(meeting_2016, llm, {"pages_body": 8, "pages_dropped": 5, "ocr_pages": 8})
    assert ex.extraction_meta.text_source == "vision_ocr"


def test_finalize_text_source_embedded_ocr_era():
    llm = LLMExtraction.model_validate(LLM_JSON)
    meeting_2019 = {**MEETING, "meeting_id": "cb1-2019-02-12", "date": "2019-02-12"}
    ex = finalize(meeting_2019, llm, {"pages_body": 12, "pages_dropped": 20, "ocr_pages": 0})
    assert ex.extraction_meta.text_source == "embedded_ocr"


def test_user_prompt_carries_manifest_identity():
    p = build_user_prompt(MEETING, "BODY")
    assert "cb1-2023-06-13" in p
    assert "2023-06-13" in p


def test_system_prompt_is_cacheable_and_contains_schema():
    blocks = system_blocks()
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "source_snippet" in SYSTEM_PROMPT
    assert "liquor_licenses" in SYSTEM_PROMPT


def test_strip_fences_noop_on_clean_json():
    assert strip_fences('{"a": 1}') == '{"a": 1}'
