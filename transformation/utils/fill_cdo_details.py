"""
Copy the CDO details fetched by fetch_cdo_details.py (table cdo_details) onto
the three Dublin Core lot tables, matched on the row's trimmed cdo_email:

  cdo_details.designation -> cdo_designation   (DCAT vcard:title)
  cdo_details.phone       -> cdo_phone         (DCAT vcard:hasTelephone)
  cdo_details.address     -> cdo_address       (DCAT vcard:hasAddress)

The columns are added as VARCHAR if missing. cdo_name / cdo_email are left as
they are. A row whose email the API does not know, or that has no email, gets
NULL. Re-running overwrites with the same values.

Usage:
  python fill_cdo_details.py
"""
import argparse
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
TABLES = ["dublin_core_metadata", "dublin_core_remaining", "dublin_core_lot3"]
COLUMNS = {"cdo_designation": "designation", "cdo_phone": "phone", "cdo_address": "address"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    con = duckdb.connect(args.db)
    for table in TABLES:
        have = {r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'").fetchall()}
        for col in COLUMNS:
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} VARCHAR")
        sets = ", ".join(f"{col} = d.{src}" for col, src in COLUMNS.items())
        nulls = ", ".join(f"{col} = NULL" for col in COLUMNS)
        con.execute(f"UPDATE {table} SET {nulls}")
        con.execute(f"""UPDATE {table} t SET {sets} FROM cdo_details d
                        WHERE d.cdo_email = trim(t.cdo_email) AND d.name IS NOT NULL""")
        counts = con.execute(f"SELECT count(*), {', '.join(f'count({c})' for c in COLUMNS)} FROM {table}").fetchone()
        print(f"{table}: {counts[0]} rows; " + ", ".join(f"{c} {n}" for c, n in zip(COLUMNS, counts[1:])))
    con.execute("CHECKPOINT")
    con.close()


if __name__ == "__main__":
    main()
