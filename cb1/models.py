"""Pydantic models mirroring the extraction schema (PLAN.md section 4).

These are the validation gate on LLM output: extraction responses are parsed
with MeetingExtraction.model_validate_json, and on failure the formatted
error is fed back to the model for one retry.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MeetingType = Literal["combined", "public_hearing", "special", "committee", "other"]
ApplicationType = Literal[
    "new", "renewal", "alteration", "corporate_change", "transfer", "other"
]
TopicCategory = Literal[
    "land_use",
    "liquor",
    "transportation",
    "environment",
    "parks",
    "budget",
    "internal",
    "other",
]
Position = Literal["for", "against", "neutral", "unclear"]
Severity = Literal["fatality", "critical_injury", "other"]
TextSource = Literal["native", "embedded_ocr", "vision_ocr", "mixed"]
DateSource = Literal["content", "filename", "override"]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Meeting(BaseModel):
    meeting_id: str  # stable key: cb1-YYYY-MM-DD
    date: str  # YYYY-MM-DD
    meeting_type: MeetingType = "combined"
    location_or_platform: str | None = None
    attendance_count: int | None = None
    quorum_noted: bool = False
    chair: str | None = None
    source_files: list[str] = Field(default_factory=list)
    date_source: DateSource = "content"
    date_confidence: float = 1.0
    is_revised: bool = False

    @field_validator("date")
    @classmethod
    def _date_format(cls, v: str) -> str:
        if not DATE_RE.match(v):
            raise ValueError(f"date must be YYYY-MM-DD, got {v!r}")
        return v


class LiquorLicense(BaseModel):
    applicant_name: str
    dba: str | None = None
    address: str
    application_type: ApplicationType = "other"
    license_class: str | None = None
    features: list[str] = Field(default_factory=list)
    committee_recommendation: str | None = None
    board_action: str | None = None
    source_snippet: str


class Vote(BaseModel):
    motion_text: str
    topic_category: TopicCategory = "other"
    mover: str | None = None
    seconder: str | None = None
    yes: int = Field(ge=0)
    no: int = Field(ge=0)
    abstain: int = Field(ge=0)
    recusal: int = Field(ge=0)
    outcome: Literal["passed", "failed"]
    unanimous: bool = False
    conditions: list[str] = Field(default_factory=list)
    source_snippet: str


class PublicSpeaker(BaseModel):
    name: str | None = None
    affiliation: str | None = None
    topic: str
    position: Position = "unclear"
    source_snippet: str


class GovernmentAnnouncement(BaseModel):
    """Officials/agency staff addressing the board outside the public
    session. Separate from public_speakers (community testimony only).
    Pipeline extracts this from schema v1.1 onward; golden sets carry it
    from v1.0."""

    name: str | None = None
    affiliation: str | None = None
    topic: str
    source_snippet: str


class TrafficIncident(BaseModel):
    victim_name: str | None = None
    incident_date: str | None = None
    location: str
    severity: Severity = "other"
    source_snippet: str


class CannabisLicense(BaseModel):
    applicant_name: str
    address: str
    application_type: str = "other"
    source_snippet: str


class ExtractionMeta(BaseModel):
    model: str
    text_source: TextSource
    pages_minutes_body: int = Field(ge=0)
    pages_attachments_dropped: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    schema_version: str = "1.0"
    prompt_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)


class MeetingExtraction(BaseModel):
    meeting: Meeting
    liquor_licenses: list[LiquorLicense] = Field(default_factory=list)
    votes: list[Vote] = Field(default_factory=list)
    public_speakers: list[PublicSpeaker] = Field(default_factory=list)
    traffic_incidents: list[TrafficIncident] = Field(default_factory=list)
    cannabis_licenses: list[CannabisLicense] = Field(default_factory=list)
    government_announcements: list[GovernmentAnnouncement] = Field(default_factory=list)
    extraction_meta: ExtractionMeta


# What the LLM is asked to produce: everything except extraction_meta
# (meta is assembled by the pipeline, which knows tokens/cost/page counts).
class LLMExtraction(BaseModel):
    meeting: Meeting
    liquor_licenses: list[LiquorLicense] = Field(default_factory=list)
    votes: list[Vote] = Field(default_factory=list)
    public_speakers: list[PublicSpeaker] = Field(default_factory=list)
    traffic_incidents: list[TrafficIncident] = Field(default_factory=list)
    cannabis_licenses: list[CannabisLicense] = Field(default_factory=list)
    government_announcements: list[GovernmentAnnouncement] = Field(default_factory=list)


def format_validation_error(raw: str, error: Exception) -> str:
    """Build the retry-with-feedback user message after a validation failure."""
    return (
        "Your previous response failed schema validation.\n\n"
        f"Validation errors:\n{error}\n\n"
        "Return ONLY corrected JSON conforming to the schema. "
        "Do not change fields that were already valid.\n\n"
        f"Your previous response was:\n{raw}"
    )
