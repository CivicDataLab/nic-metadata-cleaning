"""Assign controlled keywords to every dataset in ``dublin_core_metadata``.

Deterministic, rule-based pass over the whole corpus using the controlled
vocabulary in ``controlled_vocabulary.yaml``. Writes the results back into the
existing Dublin Core columns the search facet reads:

    Subject[keyword]            <- generic / layman keywords  (comma-separated)
    Subject[sponsored_keyword]  <- specific keywords          (comma-separated)

It also emits ``controlled_keyword_assignments.csv`` for human spot-checking.

The script is idempotent (overwrites only those two columns) and re-runnable.
It backs up the DB first, following the repo's ``metadata.db.*.bak`` convention.

Run:
    python assign_controlled_keywords.py            # full run, writes to DB
    python assign_controlled_keywords.py --limit 50 # preview, CSV only, no DB write
    python assign_controlled_keywords.py --dry-run  # full pass, CSV only, no DB write
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import time

import duckdb
import pandas as pd

from controlled_vocabulary import TEXT_FIELDS, assign_keywords, load_vocab

logging.basicConfig(
    format="%(asctime)s : %(levelname)s - %(message)s", level=logging.INFO
)

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
SOURCE_TABLE = "dublin_core_metadata"
GENERIC_COL = "Subject[keyword]"
SPONSORED_COL = "Subject[sponsored_keyword]"
OUTPUT_DIR = os.path.dirname(__file__)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "controlled_keyword_assignments.csv")

# Columns we read. nid is the join key; the rest feed the matcher.
SOURCE_FIELDS = ["nid"] + TEXT_FIELDS


def _resolve_columns(con) -> dict[str, str]:
    """Map our desired field names to the table's actual (case-exact) names."""
    available = [
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{SOURCE_TABLE}'"
        ).fetchall()
    ]
    by_lower = {c.lower(): c for c in available}
    return {f: by_lower[f.lower()] for f in SOURCE_FIELDS if f.lower() in by_lower}


def load_rows(con, limit: int | None) -> pd.DataFrame:
    resolved = _resolve_columns(con)
    select = ", ".join(f'"{resolved[f]}" AS "{f}"' for f in resolved)
    query = f"SELECT {select} FROM {SOURCE_TABLE} WHERE nid IS NOT NULL"
    if limit is not None:
        query += f" LIMIT {limit}"
    df = con.execute(query).fetchdf()
    logging.info(f"Loaded {len(df)} rows from {SOURCE_TABLE}")
    return df


def assign_all(df: pd.DataFrame) -> pd.DataFrame:
    vocab = load_vocab()
    generic_out, sponsored_out = [], []
    for row in df.to_dict("records"):
        g, s = assign_keywords(row, vocab)
        generic_out.append(", ".join(g))
        sponsored_out.append(", ".join(s))
    out = pd.DataFrame(
        {
            "nid": df["nid"].astype("int64"),
            "title": df.get("Title", ""),
            GENERIC_COL: generic_out,
            SPONSORED_COL: sponsored_out,
        }
    )
    return out


def write_back(con, assignments: pd.DataFrame) -> None:
    """Bulk-update the two Subject columns via a staging table + UPDATE ... FROM."""
    staging = assignments[["nid", GENERIC_COL, SPONSORED_COL]].rename(
        columns={GENERIC_COL: "g", SPONSORED_COL: "s"}
    )
    con.register("staging_kw", staging)
    con.execute(
        f'UPDATE {SOURCE_TABLE} AS t '
        f'SET "{GENERIC_COL}" = st.g, "{SPONSORED_COL}" = st.s '
        f'FROM staging_kw AS st WHERE t.nid = st.nid'
    )
    con.unregister("staging_kw")
    logging.info(f"Updated {len(staging)} rows in {SOURCE_TABLE}")


def backup_db() -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = f"{DB_PATH}.pre_keywords_{ts}.bak"
    shutil.copy2(DB_PATH, dst)
    logging.info(f"Backed up DB -> {dst}")
    return dst


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign controlled keywords to datasets")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only N rows (implies --dry-run preview)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute + write CSV but do not modify the database")
    args = parser.parse_args()
    dry_run = args.dry_run or args.limit is not None

    con = duckdb.connect(DB_PATH, read_only=dry_run)
    df = load_rows(con, args.limit)
    assignments = assign_all(df)

    assignments.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    logging.info(f"Wrote review CSV -> {OUTPUT_CSV} ({len(assignments)} rows)")

    if dry_run:
        logging.info("Dry run — database not modified.")
        con.close()
        return

    con.close()
    backup_db()
    con = duckdb.connect(DB_PATH)
    write_back(con, assignments)

    # Coverage summary.
    total, with_g, with_s, distinct_g = con.execute(
        f'SELECT COUNT(*), '
        f'COUNT(*) FILTER (WHERE "{GENERIC_COL}" <> \'\'), '
        f'COUNT(*) FILTER (WHERE "{SPONSORED_COL}" <> \'\'), '
        f'COUNT(DISTINCT "{GENERIC_COL}") '
        f'FROM {SOURCE_TABLE}'
    ).fetchone()
    con.close()
    logging.info(
        f"Coverage: {with_g}/{total} have generic keywords "
        f"({100*with_g/total:.1f}%), {with_s}/{total} have sponsored "
        f"({100*with_s/total:.1f}%); {distinct_g} distinct generic combinations."
    )


if __name__ == "__main__":
    main()
