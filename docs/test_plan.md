# Data Quality Test Plan

**Dataset:** COVID-19 Clinical Trials (5,783 studies, seven related tables)  
**Database:** PostgreSQL 17  
**Author:** Elene Kikalishvili  
**Date:** 2026-07-24

## Purpose

Validate the loaded dataset against explicit data quality rules before it is 
used for analysis. Rules are drawn from two sources: constraints declared in the 
target schema, and issues identified during profiling (`notebooks/01_profiling.ipynb`).

Each test case maps to a numbered rule. Execution is scripted 
(`src/run_tests.py`) so the suite is repeatable against future data refreshes; 
results are written to `outputs/test_results.csv` and failures documented in 
`docs/defect_log.md`.

## Scope

**In scope**
- Structural integrity of the seven loaded tables: uniqueness and referential integrity
- Validity of values against domain constraints and declared formats
- Internal consistency of date sequences and categorical representation
- Usability of derived geographic fields for analysis

**Out of scope**
- Verification against the source registry. Values are tested for internal consistency and plausibility, not factual accuracy against ClinicalTrials.gov.
- Fields with no source column (`brief_summary`, `mesh_term`, `agency_class`, `continent`, `enrollment_type`, `outcome_type`, `time_frame`, `eligibility_criteria`, and the `description` fields), which are null by construction rather than by defect.
- Free-text fields with no testable format (`title`, `measure`, `facility`).
- Performance and load testing.

## Test selection

Ten test cases were selected on analytical impact - each maps to a field or relationship the business questions depend on. Constraints already enforced by the schema at load time (`NOT NULL`, `UNIQUE`, foreign keys) are included only where the field is analytically central; a violation elsewhere would have caused the load to fail rather than pass silently.

## Severity definitions

| Severity | Meaning |
|---|---|
| High | Produces incorrect analytical results, or breaks referential structure |
| Medium | Produces incomplete or misleading results; analysis remains possible with caveats |
| Low | Limited impact; affects a narrow subset or a secondary field |

## Quality rules

| Rule ID | Dimension | Rule | Source |
|---|---|---|---|
| DQ-01 | Uniqueness | `nct_id` is unique across all studies | Schema (`UNIQUE`) |
| DQ-02 | Referential integrity | Every `conditions.study_id` references an existing study | Schema (FK) |
| DQ-03 | Referential integrity | Every `locations.study_id` references an existing study | Schema (FK) |
| DQ-04 | Date logic | `completion_date` is not earlier than `start_date` | Domain logic |
| DQ-05 | Valid range | `enrollment`, where populated, is greater than zero | Domain logic |
| DQ-06 | Plausibility | Interventional studies record an enrolment below 1,000,000 | Domain logic |
| DQ-07 | Consistency | `phase` holds a single value, not a delimited list | Schema (single-value column) |
| DQ-08 | Consistency | Absence in `allocation` is represented as NULL, not as a literal string | Profiling finding |
| DQ-09 | Validity | `city` contains a place name, not a facility or department name | Profiling finding |
| DQ-10 | Completeness | `state` is populated for locations in countries with state subdivisions | Domain logic |

## Test cases

| Test ID | Rule | Test | Expected |
|---|---|---|---|
| TC-01 | DQ-01 | Count `nct_id` values occurring more than once | 0 |
| TC-02 | DQ-02 | Count conditions whose `study_id` has no matching study | 0 |
| TC-03 | DQ-03 | Count locations whose `study_id` has no matching study | 0 |
| TC-04 | DQ-04 | Count studies where `completion_date < start_date` | 0 |
| TC-05 | DQ-05 | Count studies where `enrollment <= 0` | 0 |
| TC-06 | DQ-06 | Count interventional studies where `enrollment > 1000000` | 0 |
| TC-07 | DQ-07 | Count studies where `phase` contains a pipe delimiter | 0 |
| TC-08 | DQ-08 | Count study_design rows where `allocation = 'N/A'` | 0 |
| TC-09 | DQ-09 | Count locations where `city` contains a facility term (Hospital, Department, Institute, Clinic, University, Center, Centre) | 0 |
| TC-10 | DQ-10 | Count US locations where `state` is null | 0 |

## Severity assignment

| Test ID | Severity | Rationale |
|---|---|---|
| TC-01 | High | Duplicate registry identifiers make study-level analysis unreliable |
| TC-02 | High | Orphaned records break aggregation across tables |
| TC-03 | High | Orphaned records break aggregation across tables |
| TC-04 | High | Invalid ordering produces negative durations in duration analysis |
| TC-05 | Medium | Zero enrolment is either a failed trial or a data entry error; both require investigation before enrolment analysis |
| TC-06 | Medium | An interventional trial cannot administer an intervention at population scale; such values distort enrolment summaries |
| TC-07 | Medium | Multi-valued phase fragments any grouping by phase, excluding affected studies from single-phase counts |
| TC-08 | Medium | Mixed representation of absence causes null checks to return incomplete results |
| TC-09 | Medium | Facility names in the city field make geographic aggregation unreliable. Heuristic test - a genuine place name could contain one of these terms |
| TC-10 | Low | Missing state affects US regional breakdown only; country-level analysis is unaffected |

## Execution

    python src/run_tests.py

Results are written to `outputs/test_results.csv`. Failures are expanded in 
`docs/defect_log.md` with counts, examples, and analytical impact.