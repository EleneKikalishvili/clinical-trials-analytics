"""
Load the transformed tables into PostgreSQL.

Expects the schema to already exist (sql/01_schema.sql) and the database to be
running. Tables are loaded parent-first so foreign key references resolve.
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from extract_transform import main as transform

load_dotenv()

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://ctuser:ctpass@localhost:5433/clinical_trials",
)

# Parent first - children reference studies.study_id
LOAD_ORDER = [
    "studies",
    "conditions",
    "interventions",
    "outcomes",
    "sponsors",
    "locations",
    "study_design",
]


def load(tables, engine):
    """Insert each table, in dependency order."""
    for name in LOAD_ORDER:
        table = tables[name]
        table.to_sql(name, engine, if_exists="append", index=False)
        print(f"{name:<15} {len(table):>7,} rows loaded")


if __name__ == "__main__":
    engine = create_engine(DB_URL)
    tables = transform()
    load(tables, engine)