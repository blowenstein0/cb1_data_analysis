"""Load extracted meeting JSON into DuckDB + parquet exports."""

import json
from pathlib import Path

import duckdb

from cb1 import config

DDL = """
CREATE OR REPLACE TABLE meetings (
    meeting_id VARCHAR PRIMARY KEY, date DATE, meeting_type VARCHAR,
    location_or_platform VARCHAR, attendance_count INT, quorum_noted BOOLEAN,
    chair VARCHAR, is_revised BOOLEAN, date_source VARCHAR,
    date_confidence DOUBLE, source_files VARCHAR[],
    text_source VARCHAR, pages_minutes_body INT, pages_attachments_dropped INT,
    input_tokens INT, output_tokens INT, cost_usd DOUBLE, warnings VARCHAR[]
);
CREATE OR REPLACE TABLE licenses (
    meeting_id VARCHAR, applicant_name VARCHAR, dba VARCHAR, address VARCHAR,
    application_type VARCHAR, license_class VARCHAR, features VARCHAR[],
    committee_recommendation VARCHAR, board_action VARCHAR, source_snippet VARCHAR
);
CREATE OR REPLACE TABLE votes (
    meeting_id VARCHAR, motion_text VARCHAR, topic_category VARCHAR,
    mover VARCHAR, seconder VARCHAR, yes INT, no INT, abstain INT, recusal INT,
    outcome VARCHAR, unanimous BOOLEAN, conditions VARCHAR[], source_snippet VARCHAR
);
CREATE OR REPLACE TABLE speakers (
    meeting_id VARCHAR, name VARCHAR, affiliation VARCHAR, topic VARCHAR,
    position VARCHAR, source_snippet VARCHAR
);
CREATE OR REPLACE TABLE incidents (
    meeting_id VARCHAR, victim_name VARCHAR, incident_date VARCHAR,
    location VARCHAR, severity VARCHAR, source_snippet VARCHAR
);
CREATE OR REPLACE TABLE cannabis (
    meeting_id VARCHAR, applicant_name VARCHAR, address VARCHAR,
    application_type VARCHAR, source_snippet VARCHAR
);
"""

TABLES = ("meetings", "licenses", "votes", "speakers", "incidents", "cannabis")


def load_db(extracted_dir: Path | None = None, db_path: Path | None = None) -> dict:
    extracted_dir = extracted_dir or config.EXTRACTED_DIR
    db_path = db_path or (config.DB_DIR / "cb1.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(extracted_dir.glob("cb1-*.json"))
    con = duckdb.connect(str(db_path))
    con.execute(DDL)

    for f in files:
        d = json.loads(f.read_text())
        m, meta = d["meeting"], d["extraction_meta"]
        mid = m["meeting_id"]
        con.execute(
            "INSERT INTO meetings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                mid, m["date"], m["meeting_type"], m.get("location_or_platform"),
                m.get("attendance_count"), m.get("quorum_noted"), m.get("chair"),
                m.get("is_revised"), m.get("date_source"), m.get("date_confidence"),
                m.get("source_files", []),
                meta["text_source"], meta["pages_minutes_body"],
                meta["pages_attachments_dropped"], meta["input_tokens"],
                meta["output_tokens"], meta["cost_usd"], meta.get("warnings", []),
            ],
        )
        for r in d.get("liquor_licenses", []):
            con.execute(
                "INSERT INTO licenses VALUES (?,?,?,?,?,?,?,?,?,?)",
                [mid, r["applicant_name"], r.get("dba"), r["address"],
                 r["application_type"], r.get("license_class"), r.get("features", []),
                 r.get("committee_recommendation"), r.get("board_action"),
                 r["source_snippet"]],
            )
        for r in d.get("votes", []):
            con.execute(
                "INSERT INTO votes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [mid, r["motion_text"], r["topic_category"], r.get("mover"),
                 r.get("seconder"), r["yes"], r["no"], r["abstain"], r["recusal"],
                 r["outcome"], r.get("unanimous", False), r.get("conditions", []),
                 r["source_snippet"]],
            )
        for r in d.get("public_speakers", []):
            con.execute(
                "INSERT INTO speakers VALUES (?,?,?,?,?,?)",
                [mid, r.get("name"), r.get("affiliation"), r["topic"],
                 r["position"], r["source_snippet"]],
            )
        for r in d.get("traffic_incidents", []):
            con.execute(
                "INSERT INTO incidents VALUES (?,?,?,?,?,?)",
                [mid, r.get("victim_name"), r.get("incident_date"), r["location"],
                 r["severity"], r["source_snippet"]],
            )
        for r in d.get("cannabis_licenses", []):
            con.execute(
                "INSERT INTO cannabis VALUES (?,?,?,?,?)",
                [mid, r["applicant_name"], r["address"], r["application_type"],
                 r["source_snippet"]],
            )

    counts = {}
    for t in TABLES:
        counts[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        con.execute(
            f"COPY {t} TO '{db_path.parent / (t + '.parquet')}' (FORMAT PARQUET)"
        )
    con.close()
    print(f"load-db: {counts} -> {db_path} (+ parquet)")
    return counts
