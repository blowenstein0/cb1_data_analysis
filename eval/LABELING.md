# Golden-set labeling policy

Decisions made during golden-set review. These definitions bind both the
golden files and (from schema v1.1) the extraction prompt.

## public_speakers — STRICT (decided 2026-07-14)

`public_speakers` = individuals giving testimony in the **public session or
public hearing** portions of the meeting. Community voice only.

- **Excluded**: elected officials and agency staff addressing the board
  under announcements/reports sections (e.g. "ANNOUNCEMENTS: ELECTED
  OFFICIALS"). These go in `government_announcements`.
- Rationale: the speakers table feeds testimony-sentiment analyses
  (for/against ratios). Government announcements are not testimony and
  would pollute position analytics.
- Origin: cb1-2019-02-12 review — Mr. Pierre (Comptroller's office) spoke
  under announcements, not public session. The pipeline's public-session-only
  extraction was correct by this policy.

## government_announcements

Officials/agency staff addressing the board outside the public session.
Fields: name, affiliation (office/agency), topic, source_snippet. No
position field — announcements are not for/against testimony.

- Present in golden sets from now on (best-effort; NOT scored against the
  v1.0 pipeline, which does not extract them).
- Becomes a scored entity when the extraction prompt adds it (schema v1.1).

## Known follow-ups

- cb1-2016-02-09 golden: verify Stephen T. Levin's speaker record — if he
  spoke under announcements rather than public session, move him to
  government_announcements per this policy.
