#!/usr/bin/env python3
"""
Export dublin_core_remaining from metadata.db to xlsx (and optionally csv).

The export is export_dublin_metadata.py --table dublin_core_remaining, the same
writer used for dublin_core_metadata: the same priority columns
(PRIORITY_COLUMNS) lead the sheet with yellow headers, and the
pipeline columns in REMAINING_EXCLUDE_COLUMNS stay in the table but are left out
of the sheet. Change the column set there, not here.

If the target file is open in WPS/LibreOffice/Excel the export does not
overwrite it -- the office suite would write its own buffer back over ours on
its next save. It falls back to a timestamped name in the same directory and
says so.

Usage:
  python3 export_dublin_core_remaining.py
  python3 export_dublin_core_remaining.py --out /path/to/file.xlsx
  python3 export_dublin_core_remaining.py --csv          # csv beside the xlsx
  python3 export_dublin_core_remaining.py --where "merge_method='curate'"
"""

import argparse
import datetime as dt
import re
import subprocess
from pathlib import Path

import duckdb

import export_dublin_metadata as edm

HERE = Path(__file__).resolve().parent
TABLE = edm.REMAINING_TABLE
DEFAULT_OUT = HERE.parent.parent / "dublin_core_remaining.xlsx"


def file_is_open(path: Path) -> str | None:
    """Name of an office process holding this file, if any."""
    if not path.exists():
        return None
    lock = path.with_name(f".~{path.name}")          # WPS / LibreOffice lock file
    try:
        ps = subprocess.run(["ps", "-eo", "comm,args"], capture_output=True,
                            text=True, timeout=10).stdout
    except Exception:
        return None
    for line in ps.splitlines():
        # Match on the command name only: a script named *sheet.py with the
        # path in its own arguments is not an office suite.
        comm = line.split(None, 1)[0] if line.strip() else ""
        if str(path) in line and re.search(r"wps|office|excel|et\b|soffice",
                                           comm, re.I):
            return comm
    if lock.exists() and re.search(r"wps|soffice|\bet\b", ps, re.I):
        return "an office suite (lock file present)"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=edm.DB_PATH)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--where", default=None, help="SQL predicate, without WHERE")
    ap.add_argument("--csv", action="store_true", help="also write a csv beside it")
    ap.add_argument("--force", action="store_true",
                    help="overwrite even if the file looks open in an office suite")
    args = ap.parse_args()

    out = Path(args.out)
    holder = file_is_open(out)
    if holder and not args.force:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = out.with_name(f"{out.stem}_{ts}{out.suffix}")
        print(f"! {Path(args.out).name} is open in {holder} - not overwriting it.")
        print(f"  Writing to {out.name} instead (pass --force to override).\n")

    edm.DB_PATH = args.db
    cols = edm.main(output=str(out), where=args.where, overrides=None, table=TABLE)
    print(f"Wrote {out}  ({out.stat().st_size / 1024 / 1024:.1f} MB)")

    if args.csv:
        cpath = out.with_suffix(".csv")
        quoted = ", ".join(f'"{c}"' for c in cols)
        where = f" WHERE {args.where}" if args.where else ""
        con = duckdb.connect(args.db, read_only=True)
        try:
            con.execute(f"""COPY (SELECT {quoted} FROM {TABLE}{where})
                            TO '{cpath}' (HEADER, DELIMITER ',')""")
        finally:
            con.close()
        print(f"Wrote {cpath}  ({cpath.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
