"""
Extract and transform COVID-19 clinical trial data into the target relational schema.

Reads the flat source CSV and reshapes it into seven related tables:
studies, interventions, outcomes, conditions, sponsors, locations, study_design.

Transformation is structural only - parsing, splitting, and type conversion.
Data quality issues in the source are preserved so they can be surfaced during profiling and testing.
"""

import pandas as pd
import numpy as np
from pathlib import Path

RAW_PATH = Path("data/raw/COVID clinical trials.csv")

# Source columns:
# 'Rank', 'NCT Number', 'Title', 'Acronym', 'Status', 'Study Results', 'Conditions', 'Interventions', 'Outcome Measures', 
# 'Sponsor/Collaborators', 'Gender', 'Age', 'Phases', 'Enrollment', 'Funded Bys', 'Study Type', 'Study Designs', 'Other IDs', 
# 'Start Date', 'Primary Completion Date', 'Completion Date', 'First Posted', 'Results First Posted', 'Last Update Posted', 
# 'Locations', 'Study Documents', 'URL'

# Column order per sql/01_schema.sql. Each build function reindexes to its
# list, so a missing or misnamed column fails here rather than at load time.
STUDIES_COLUMNS = [
    "study_id", "nct_id", "title", "acronym", "status", "phase", "study_type",
    "start_date", "completion_date", "primary_completion_date",
    "enrollment", "enrollment_type", "brief_summary", "eligibility_criteria",
    "minimum_age", "maximum_age", "gender",
]

CONDITIONS_COLUMNS = ["study_id", "condition_name", "mesh_term"]

INTERVENTIONS_COLUMNS = ["study_id", "intervention_type", "name", "description"]

OUTCOMES_COLUMNS = ["study_id", "outcome_type", "measure", "time_frame", "description"]

SPONSORS_COLUMNS = ["study_id", "agency", "agency_class", "lead_or_collaborator"]

LOCATIONS_COLUMNS = ["study_id", "facility", "city", "state", "country", "continent"]

STUDY_DESIGN_COLUMNS = [
    "study_id", "allocation", "intervention_model", "masking",
    "primary_purpose", "observational_model", "time_perspective",
]


# Helper Functions

def parse_age(value):
    """
    Split an age string into (minimum, maximum).

    Four shapes occur in the source:
        "18 Years and older  (Adult, Older Adult)"  -> ("18 Years", None)
        "18 Years to 80 Years  (Adult)"             -> ("18 Years", "80 Years")
        "up to 1 Year  (Child)"                     -> (None, "1 Year")
        "Child, Adult, Older Adult"                 -> (None, None)

    Units are preserved as written. Unrecognised shapes return (None, None).
    """

    if pd.isna(value):
        return (None, None)

    # Drop the trailing category, e.g. "(Adult, Older Adult)"
    text = value.split("(")[0].strip()
    
    if text.startswith("up to "):
        return (None, text.replace("up to ", "").strip())

    if " to " in text:
        low, high = text.split(" to ", 1)
        return (low.strip(), high.strip())

    if text.endswith("and older"):
        return (text.replace("and older", "").strip(), None)

    # Category-only rows, or anything unexpected
    return (None, None)


def parse_study_design(value):
    """
    Parse a study design string into a dict of its key-value pairs.

    Source format is pipe-delimited "Key: Value" pairs, e.g.
        "Allocation: Randomized|Masking: None (Open Label)"

    Interventional and observational studies use different keys, so any
    given study populates only a subset. Keys are normalised to the schema
    column names; unrecognised keys are ignored.
    """
    if pd.isna(value):
        return {}

    key_map = {
        "Allocation": "allocation",
        "Intervention Model": "intervention_model",
        "Masking": "masking",
        "Primary Purpose": "primary_purpose",
        "Observational Model": "observational_model",
        "Time Perspective": "time_perspective",
    }

    parsed = {}
    for pair in value.split("|"):
        if ":" not in pair:
            continue
        key, val = pair.split(":", 1)
        column = key_map.get(key.strip())
        if column:
            parsed[column] = val.strip()

    return parsed



def parse_location(site):
    """
    Split a single location string into (facility, city, state, country).

    Parts are comma-separated but variable in number, because facility names
    frequently contain commas (department lists, institutional hierarchies).
    Parsing is therefore right-anchored: the trailing fields are reliable,
    the facility absorbs whatever remains.

    Facility values are not cleaned - some contain a full address duplicating
    the structured fields, which is preserved for profiling to surface.
    """
    if pd.isna(site):
        return (None, None, None, None)

    parts = [p.strip() for p in site.split(",")]

    if len(parts) == 1:
        return (parts[0], None, None, None)

    if len(parts) == 2:
        return (parts[0], None, None, parts[1])

    if len(parts) == 3:
        return (parts[0], parts[1], None, parts[2])

    # Four or more: last is country, then state, then city;
    # everything before that is facility
    facility = ", ".join(parts[:-3])
    return (facility, parts[-3], parts[-2], parts[-1])


# Build Table Functions

def build_studies(df):
    """
    Build the studies table from the source dataframe. Fields with no source column
    (brief_summary, eligibility_criteria, enrollment_type) are left null.
    """
    studies = pd.DataFrame()

    # Primary key assigned explicitly in the transformation rather than relying on the SERIAL default,
    # since child tables need the value at build time.
    studies["study_id"] = range(1, len(df) + 1)

    # Direct mappings
    studies["nct_id"] = df["NCT Number"]
    studies["title"] = df["Title"]
    studies["acronym"] = df["Acronym"]
    studies["status"] = df["Status"]
    studies["phase"] = df["Phases"]
    studies["study_type"] = df["Study Type"]
    studies["gender"] = df["Gender"]

    # Dates: source is string, target is DATE.
    # errors="coerce" turns unparseable values into NaT rather than raising.
    studies["start_date"] = pd.to_datetime(df["Start Date"], errors="coerce")
    studies["completion_date"] = pd.to_datetime(df["Completion Date"], errors="coerce")
    studies["primary_completion_date"] = pd.to_datetime(df["Primary Completion Date"], errors="coerce")

    # Enrollment: source is float, target is INTEGER.
    studies["enrollment"] = df["Enrollment"].astype("Int64")

    # Age: source packs range and category into one string,
    # e.g. "18 Years and older  (Adult, Older Adult)".
    # The range maps to two columns; the category has no schema field.
    ages = df["Age"].apply(parse_age)
    studies["minimum_age"] = ages.str[0]
    studies["maximum_age"] = ages.str[1]

    # No source column
    studies["brief_summary"] = None
    studies["eligibility_criteria"] = None
    studies["enrollment_type"] = None

    return studies[STUDIES_COLUMNS]



def build_conditions(df, studies):
    """
    Build the conditions table.

    Source packs conditions into one pipe-delimited field per study.
    Each becomes its own row, linked back by study_id.

    mesh_term has no source column and is left null.
    """

    conditions = pd.DataFrame({
        "study_id": studies["study_id"],
        "condition_name": df["Conditions"],
    })

    # One row per condition
    conditions["condition_name"] = conditions["condition_name"].str.split("|")
    conditions = conditions.explode("condition_name")

    # Drop studies with no conditions listed
    conditions = conditions.dropna(subset=["condition_name"])

    conditions["condition_name"] = conditions["condition_name"].str.strip()
    conditions["mesh_term"] = None

    return conditions[CONDITIONS_COLUMNS].reset_index(drop=True)



def build_interventions(df, studies):
    """
    Build the interventions table.

    Source is pipe-delimited, each entry formatted "Type: Name"
    (e.g. "Drug: normal saline"). Splitting on the first colon separates them.

    Entries without a colon keep the full string as name and leave type null.
    description has no source column.
    """
    interventions = pd.DataFrame({
        "study_id": studies["study_id"],
        "raw": df["Interventions"],
    })

    interventions["raw"] = interventions["raw"].str.split("|")
    interventions = interventions.explode("raw")
    interventions = interventions.dropna(subset=["raw"])
    interventions["raw"] = interventions["raw"].str.strip()

    # Split on the first colon only - names may contain colons
    split = interventions["raw"].str.split(":", n=1, expand=True)
    interventions["intervention_type"] = split[0].str.strip()
    interventions["name"] = split[1].str.strip()

    interventions["description"] = None

    return interventions[INTERVENTIONS_COLUMNS].reset_index(drop=True)



def build_outcomes(df, studies):
    """
    Build the outcomes table.

    Source is a single pipe-delimited field of outcome measures. The source
    does not distinguish primary from secondary outcomes, so outcome_type is
    left null. time_frame and description have no source column.
    """
    outcomes = pd.DataFrame({
        "study_id": studies["study_id"],
        "measure": df["Outcome Measures"],
    })

    outcomes["measure"] = outcomes["measure"].str.split("|")
    outcomes = outcomes.explode("measure")
    outcomes = outcomes.dropna(subset=["measure"])
    outcomes["measure"] = outcomes["measure"].str.strip()

    outcomes["outcome_type"] = None
    outcomes["time_frame"] = None
    outcomes["description"] = None

    return outcomes[OUTCOMES_COLUMNS].reset_index(drop=True) 



def build_sponsors(df, studies):
    """
    Build the sponsors table.

    Source is pipe-delimited, first entry being the lead sponsor and any
    subsequent entries collaborators.

    agency_class has no direct source column. "Funded Bys" carries related
    information but is study-level rather than per-sponsor, and its values
    are order-inconsistent (e.g. "Other|Industry" and "Industry|Other"),
    so it is not mapped here.
    """
    sponsors = pd.DataFrame({
        "study_id": studies["study_id"],
        "agency": df["Sponsor/Collaborators"],
    })

    sponsors["agency"] = sponsors["agency"].str.split("|")
    sponsors = sponsors.explode("agency")
    sponsors = sponsors.dropna(subset=["agency"])
    sponsors["agency"] = sponsors["agency"].str.strip()

    # First entry per study is the lead sponsor
    position = sponsors.groupby("study_id").cumcount()
    sponsors["lead_or_collaborator"] = np.where(position == 0, "lead", "collaborator")

    sponsors["agency_class"] = None

    return sponsors[SPONSORS_COLUMNS].reset_index(drop=True)



def build_locations(df, studies):
    """
    Build the locations table.

    Source is pipe-delimited sites, each comma-separated internally.
    continent has no source column.
    """
    locations = pd.DataFrame({
        "study_id": studies["study_id"],
        "site": df["Locations"],
    })

    locations["site"] = locations["site"].str.split("|")
    locations = locations.explode("site")
    locations = locations.dropna(subset=["site"])
    locations["site"] = locations["site"].str.strip()

    parsed = locations["site"].apply(parse_location)
    locations["facility"] = parsed.str[0]
    locations["city"] = parsed.str[1]
    locations["state"] = parsed.str[2]
    locations["country"] = parsed.str[3]

    locations["continent"] = None

    return locations[LOCATIONS_COLUMNS].reset_index(drop=True)



def build_study_design(df, studies):
    """
    Build the study_design table - one row per study.

    Fields not present for a given study type are left null.
    """
    parsed = df["Study Designs"].apply(parse_study_design)

    design = pd.DataFrame(list(parsed))
    design.insert(0, "study_id", studies["study_id"].values)

    # Ensure every schema column exists, even if no study populated it
    for col in STUDY_DESIGN_COLUMNS:
        if col not in design.columns:
            design[col] = None

    return design[STUDY_DESIGN_COLUMNS].reset_index(drop=True)



def main():
    """
    Run the full transformation and return the seven target tables.
    """
    source = pd.read_csv(RAW_PATH)

    studies = build_studies(source)
    tables = {
        "studies": studies,
        "conditions": build_conditions(source, studies),
        "interventions": build_interventions(source, studies),
        "outcomes": build_outcomes(source, studies),
        "sponsors": build_sponsors(source, studies),
        "locations": build_locations(source, studies),
        "study_design": build_study_design(source, studies),
    }

    return tables


if __name__ == "__main__":
    tables = main()
    print(f"Source rows: {len(pd.read_csv(RAW_PATH)):,}\n")
    for name, table in tables.items():
        print(f"{name:<15} {len(table):>7,} rows")