#!/usr/bin/env python3
"""Copy dataset headers ("Conforms To") onto dublin_core_aikosh from the two
tables that already hold them, joining on nid.

Sources (checked in order, first hit wins -- though they are asserted disjoint):
    dublin_core_remaining
    dublin_core_metadata

This is a *copy only*. Datasets whose headers are not already in the DB are not
extracted from disk; they are written to a log so they can be handled by
transformation/fill_headers_remaining.py or a re-download.

Usage:
    python3 transformation/utils/fill_headers_aikosh.py [--dry-run] [--db PATH]
                                                        [--table T] [--log PATH]

Idempotent: only rows whose "Conforms To" is NULL/blank are updated, so a
re-run after an interruption continues rather than redoing work.
"""

import argparse
import os
import sys

import duckdb

DB_PATH = "transformation/metadata.db"
TARGET_TABLE = "dublin_core_aikosh"
SOURCE_TABLES = ["dublin_core_remaining", "dublin_core_metadata"]
HEADER_COL = "Conforms To"
LOG_PATH = "transformation/utils/aikosh_headers_missing.csv"

# A row is "filled" only if the header string is non-NULL and not whitespace.
# Blank must stay indistinguishable from never-attempted -- writing '' would make
# the resume predicate re-select the row forever.
NONBLANK = 'nullif(trim({alias}"{col}"), \'\') IS NOT NULL'


def source_union_sql(tables, header_col):
    """One relation of (nid, header, source) over every table that has headers."""
    parts = [
        f'SELECT nid, nullif(trim("{header_col}"), \'\') AS hdr, '
        f"'{t}' AS src FROM {t} "
        f"WHERE {NONBLANK.format(alias="", col=header_col)}"
        for t in tables
    ]
    return "\nUNION ALL\n".join(parts)


def assert_join_is_unique(con, tables, target):
    """UPDATE ... FROM picks arbitrarily and silently when a nid matches more than
    one source row. Re-assert 1:1 every run -- the source tables are rebuilt by
    other pipeline steps, so yesterday's check does not carry."""
    for t in tables + [target]:
        dupes = con.execute(
            f"SELECT count(*) FROM (SELECT nid FROM {t} "
            f"GROUP BY nid HAVING count(*) > 1)"
        ).fetchone()[0]
        if dupes:
            sys.exit(f"ABORT: {t} has {dupes} duplicated nid(s); join is not 1:1.")

    for i, a in enumerate(tables):
        for b in tables[i + 1:]:
            both = con.execute(
                f"SELECT count(*) FROM (SELECT nid FROM {a} INTERSECT "
                f"SELECT nid FROM {b})"
            ).fetchone()[0]
            if both:
                sys.exit(
                    f"ABORT: {both} nid(s) appear in both {a} and {b}; "
                    "source precedence is undefined."
                )


def write_missing_log(con, path, target, tables, header_col):
    """Log every dataset that comes out headerless, with *why*.

    Two distinct reasons, kept apart on purpose: 'not_in_db' means the nid is
    absent from both source tables; 'in_db_no_headers' means the row is there but
    its own header cell is blank. Collapsing them would make "never downloaded"
    indistinguishable from "downloaded but unreadable".
    """
    present = "\nUNION ALL\n".join(f"SELECT nid FROM {t}" for t in tables)
    con.execute(
        f"""
        COPY (
            SELECT a.nid,
                   a.Title,
                   a."Identifier[UUID]" AS uuid,
                   CASE WHEN a.nid IN ({present}) THEN 'in_db_no_headers'
                        ELSE 'not_in_db' END AS reason
            FROM {target} a
            WHERE {NONBLANK.format(alias="a.", col=header_col)} IS NOT TRUE
            ORDER BY reason, a.nid
        ) TO '{path}' (HEADER, DELIMITER ',')
        """
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--table", default=TARGET_TABLE)
    ap.add_argument("--sources", nargs="+", default=SOURCE_TABLES)
    ap.add_argument("--log", default=LOG_PATH)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be filled; write nothing")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"no such database: {args.db}")

    con = duckdb.connect(args.db, read_only=args.dry_run)
    con.execute("SET enable_progress_bar=false")

    total = con.execute(f"SELECT count(*) FROM {args.table}").fetchone()[0]
    before = con.execute(
        f"SELECT count(*) FROM {args.table} "
        f"WHERE {NONBLANK.format(alias="", col=HEADER_COL)}"
    ).fetchone()[0]

    assert_join_is_unique(con, args.sources, args.table)

    src = source_union_sql(args.sources, HEADER_COL)

    fillable = con.execute(f"""
        SELECT s.src, count(*) FROM {args.table} a
        JOIN ({src}) s ON s.nid = a.nid
        WHERE nullif(trim(a."{HEADER_COL}"), '') IS NULL
        GROUP BY s.src ORDER BY s.src
    """).fetchall()

    print(f"{args.table}: {total} rows, {before} already have headers")
    for source, n in fillable:
        print(f"  fillable from {source}: {n}")
    print(f"  total fillable: {sum(n for _, n in fillable)}")

    if args.dry_run:
        print("dry run -- no changes written")
        return

    con.execute("BEGIN TRANSACTION")
    con.execute(f"""
        UPDATE {args.table} AS a
        SET "{HEADER_COL}" = s.hdr
        FROM ({src}) s
        WHERE s.nid = a.nid
          AND nullif(trim(a."{HEADER_COL}"), '') IS NULL
    """)
    con.execute("COMMIT")

    after = con.execute(
        f"SELECT count(*) FROM {args.table} "
        f"WHERE {NONBLANK.format(alias="", col=HEADER_COL)}"
    ).fetchone()[0]
    rows_now = con.execute(f"SELECT count(*) FROM {args.table}").fetchone()[0]
    if rows_now != total:
        sys.exit(f"ABORT: row count changed {total} -> {rows_now}")

    print(f"filled {after - before}; {after}/{total} now have headers")

    write_missing_log(con, args.log, args.table, args.sources, HEADER_COL)
    counts = con.execute(
        f"SELECT reason, count(*) FROM read_csv_auto('{args.log}') "
        "GROUP BY reason ORDER BY reason"
    ).fetchall()
    print(f"wrote {args.log}")
    for reason, n in counts:
        print(f"  {reason}: {n}")


if __name__ == "__main__":
    main()
