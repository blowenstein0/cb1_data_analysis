import json

import duckdb

from cb1.db import load_db

EXTRACTION = {
    "meeting": {
        "meeting_id": "cb1-2023-06-13", "date": "2023-06-13",
        "meeting_type": "combined", "location_or_platform": "211 Ainslie Street",
        "attendance_count": 31, "quorum_noted": True, "chair": "Dealice Fuller",
        "source_files": ["a.pdf"], "date_source": "content",
        "date_confidence": 1.0, "is_revised": False,
    },
    "liquor_licenses": [{
        "applicant_name": "Example LLC", "dba": None, "address": "123 Bedford Ave",
        "application_type": "new", "license_class": "OP",
        "features": ["sidewalk_cafe"], "committee_recommendation": "approve",
        "board_action": "approved", "source_snippet": "snippet",
    }],
    "votes": [
        {"motion_text": "approve report", "topic_category": "liquor",
         "mover": None, "seconder": None, "yes": 25, "no": 2, "abstain": 1,
         "recusal": 0, "outcome": "passed", "unanimous": False,
         "conditions": [], "source_snippet": "s"},
        {"motion_text": "adopt budget", "topic_category": "budget",
         "mover": None, "seconder": None, "yes": 28, "no": 0, "abstain": 0,
         "recusal": 0, "outcome": "passed", "unanimous": True,
         "conditions": [], "source_snippet": "s"},
    ],
    "public_speakers": [],
    "traffic_incidents": [],
    "cannabis_licenses": [],
    "extraction_meta": {
        "model": "claude-haiku-4-5", "text_source": "native",
        "pages_minutes_body": 12, "pages_attachments_dropped": 300,
        "input_tokens": 20000, "output_tokens": 2500, "cost_usd": 0.03,
        "schema_version": "1.0", "prompt_version": "1.0", "warnings": [],
    },
}


def test_load_db_and_contested_votes_query(tmp_path):
    (tmp_path / "cb1-2023-06-13.json").write_text(json.dumps(EXTRACTION))
    db_path = tmp_path / "cb1.duckdb"
    counts = load_db(extracted_dir=tmp_path, db_path=db_path)
    assert counts == {
        "meetings": 1, "licenses": 1, "votes": 2, "speakers": 0,
        "incidents": 0, "cannabis": 0,
    }

    con = duckdb.connect(str(db_path))
    # success criterion #4: contested votes by topic in one query
    rows = con.execute("""
        SELECT m.date, v.topic_category, v.no
        FROM votes v JOIN meetings m USING (meeting_id)
        WHERE v.no > 0 ORDER BY m.date
    """).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "liquor"

    assert (tmp_path / "votes.parquet").exists()
    assert (tmp_path / "meetings.parquet").exists()
