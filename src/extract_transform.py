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

def build_studies(df):
    """
    Build the studies table from the source dataframe. Fields with no source column
    (brief_summary, eligibility_criteria, enrollment_type) are left null.
    """
    studies = pd.DataFrame()

    # Primary key
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

    return studies