"""
Detect, per merge_method='curate' collection, which dimension column(s) must be
added to make its datasets directly mergeable, and whether the collection also
needs a reshape/review beyond that.

Writes two columns on dublin_core_metadata (curate rows only):
  merge_add_columns  VARCHAR  - comma list from {year, state, district} (in that
                                order) that appear as a varying axis in the
                                titles but are NOT present as a column in the
                                headers. NULL when nothing needs adding.
  needs_review       BOOLEAN  - TRUE when the collection has header variation
                                BEYOND the missing dimension/embedded-year
                                (e.g. mixed state/district granularity, differing
                                bucket ranges) so adding the column alone won't
                                align the schemas. FALSE = clean add-column case.

Logic per collection:
  1. Title axes  : parse_title_components() over every title; a dimension
     (state / district / year[=time_period]) is an "axis" if it has >= 2
     distinct non-null values across the collection.
  2. Header dims : split "Conforms To" by comma; per column name detect whether
     a state / district / time column already exists (in the modal signature).
  3. add_columns : axis dimensions that are NOT already present as columns.
  4. needs_review: strip year/month tokens from every column name; if the
     distinct stripped signatures are NOT all identical, the collection varies
     beyond the dimension -> review needed.

Only operates on rows whose merge_method='curate' (set by set_merge_method.py).
Non-curate rows keep NULL in both columns. Idempotent; safe to re-run.

Usage:
  python detect_merge_add_columns.py --dry-run
  python detect_merge_add_columns.py
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))            # title_components
sys.path.insert(0, str(HERE.parent))     # dataset_merge
from title_components import parse_title_components  # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_metadata"

_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
# Genuine year tokens only: 1971 / 2011 / 201112 / 2015-16 — NOT bucket numbers
# like 1000 or 3000 (those are not 19xx/20xx prefixed).
_YEAR_TOK = re.compile(r"\b(?:19|20)\d{2}(?:[-/]\d{2,4})?\b|\b(?:19|20)\d{4}\b")
# Fiscal shorthand attached to a month, e.g. "April 0809", "Upto May 1011".
_MONTH_NUM = re.compile(rf"({_MONTHS}[a-z]*)\s*\d{{2,6}}", re.I)
_STATE_COL = re.compile(r"\bstates?\b|\bstate\s*/\s*ut\b|states/union", re.I)
_DIST_COL = re.compile(r"\bdistrict\b|\bdistt\b|sub[\s\-]?district", re.I)
_TIME_COL = re.compile(
    rf"\b(?:19|20)\d{{2}}\b|\b(?:19|20)\d{{4}}\b|\b\d{{4}}-\d{{2,4}}\b"
    rf"|\byear\b|\bmonth\b|\bquarter\b|financial\s+year|reporting\s+period|{_MONTHS}",
    re.I,
)


def cols_of(sig: str) -> list[str]:
    return [c.strip() for c in sig.split(",") if c.strip()]


def strip_year(name: str) -> str:
    s = _MONTH_NUM.sub(r"\1", name)   # "April 0809" -> "April"
    s = _YEAR_TOK.sub("", s)          # "Pregnancies 201112" -> "Pregnancies "
    return re.sub(r"\s+", " ", s).strip()


def analyse(rows):
    """
    rows: list of (title, conforms_to, period_from, period_to, sp_states,
    sp_districts) for one collection. The trailing four are None on tables
    that do not carry them.

    An axis can come from the title OR from metadata. Batch 2 needs the
    metadata path: data_time_period_from/to is populated on every row, and
    UDISE titles repeat verbatim across years with the year only in metadata,
    so a title-only reading reports no axis at all for those collections.
    """
    states, dists, times = set(), set(), set()
    sig_counts = defaultdict(int)
    for title, sig, p_from, p_to, sp_states, sp_dists in rows:
        comp = parse_title_components(title or "")
        if comp["state"]:
            states.add(comp["state"].lower())
        if comp["district"]:
            dists.add(comp["district"].lower())
        if comp["time_period"]:
            times.add(comp["time_period"].lower())

        if p_from or p_to:
            times.add(f"{p_from}|{p_to}".lower())
        if sp_states and str(sp_states).strip():
            states.add(str(sp_states).strip().lower())
        if sp_dists and str(sp_dists).strip():
            dists.add(str(sp_dists).strip().lower())

        if sig:
            sig_counts[sig] += 1

    axes = set()
    if len(states) >= 2:
        axes.add("state")
    if len(dists) >= 2:
        axes.add("district")
    if len(times) >= 2:
        axes.add("year")

    # column-presence over the modal signature
    modal = max(sig_counts, key=sig_counts.get) if sig_counts else ""
    modal_cols = cols_of(modal)
    has_state = any(_STATE_COL.search(c) for c in modal_cols)
    has_dist = any(_DIST_COL.search(c) for c in modal_cols)
    has_time = any(_TIME_COL.search(c) for c in modal_cols)

    add = []
    if "year" in axes and not has_time:
        add.append("year")
    if "state" in axes and not has_state:
        add.append("state")
    if "district" in axes and not has_dist:
        add.append("district")

    # reshape / fixability over distinct signatures
    sigs = list(sig_counts)
    raw_set = {tuple(cols_of(s)) for s in sigs}
    stripped_set = {tuple(sorted(strip_year(c) for c in cols_of(s))) for s in sigs}
    fixable = len(stripped_set) == 1
    reshape = fixable and len(raw_set) > 1  # uniform only after year strip

    # No detected axis means the merge axis is either absent or outside this
    # script's closed vocabulary {year, state, district} — real collections vary
    # by entity too ("… of Air Asia" vs "… of Air Costa"), and header-less
    # collections give no evidence at all. Either way a human has to name the
    # axis, so route them to review rather than reporting "nothing to add".
    rows_with_sig = sum(sig_counts.values())
    if not add:
        fixable = False

    return {
        "axes": sorted(axes), "has_state": has_state, "has_dist": has_dist,
        "has_time": has_time, "add": add, "reshape": reshape, "fixable": fixable,
        "n_sig": len(sigs), "modal": modal, "rows_with_sig": rows_with_sig,
    }


def build_map(con):
    """Return {collection: (merge_add_columns|None, needs_review)} for curate collections."""
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [TABLE],
    ).fetchall()}

    def opt(name: str) -> str:
        """Select the column when the table has it, else a NULL placeholder."""
        return f'"{name}"' if name in cols else "NULL"

    # One scan grouped in Python. The previous form issued a separate query per
    # collection — ~12k round trips on batch 2.
    rows = con.execute(f"""
        SELECT "Collection", "Title", "Conforms To",
               {opt('data_time_period_from')}, {opt('data_time_period_to')},
               {opt('spatial_states')}, {opt('spatial_districts')}
        FROM {TABLE}
        WHERE merge_method='curate' AND "Collection" IS NOT NULL
    """).fetchall()

    by_coll = defaultdict(list)
    for coll, *rest in rows:
        by_coll[coll].append(tuple(rest))

    result = {}
    for coll, members in by_coll.items():
        r = analyse(members)
        add_val = ",".join(r["add"]) if r["add"] else None
        result[coll] = (add_val, not r["fixable"])
    return result


def main(dry_run: bool, db: str = DB_PATH, table: str = TABLE) -> None:
    global TABLE
    TABLE = table
    con = duckdb.connect(db, read_only=dry_run)
    try:
        cmap = build_map(con)

        add_colls, add_rows = defaultdict(int), defaultdict(int)
        review_colls = review_rows = 0
        sizes = dict(con.execute(f"""
            SELECT "Collection", COUNT(*) FROM {TABLE}
            WHERE merge_method='curate' AND "Collection" IS NOT NULL GROUP BY 1
        """).fetchall())
        for coll, (add_val, review) in cmap.items():
            n = sizes.get(coll, 0)
            key = add_val or "(none)"
            add_colls[key] += 1
            add_rows[key] += n
            if review:
                review_colls += 1
                review_rows += n

        print(f"curate collections: {len(cmap)}\n")
        print("=== merge_add_columns distribution ===")
        print(f"  {'add_columns':<22} {'#collections':>12} {'#rows':>10}")
        for key, c in sorted(add_colls.items(), key=lambda x: -x[1]):
            print(f"  {key:<22} {c:>12} {add_rows[key]:>10}")
        print(f"\nneeds_review=TRUE collections: {review_colls}  ({review_rows} rows)")

        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        # Add columns if missing.
        existing = {r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_name='{TABLE}'"
        ).fetchall()}
        if "merge_add_columns" not in existing:
            con.execute(f"ALTER TABLE {TABLE} ADD COLUMN merge_add_columns VARCHAR")
            print("\nAdded column: merge_add_columns")
        if "needs_review" not in existing:
            con.execute(f"ALTER TABLE {TABLE} ADD COLUMN needs_review BOOLEAN")
            print("Added column: needs_review")

        # Reset (idempotent): clear any prior values, then write fresh from the map.
        con.execute(f"UPDATE {TABLE} SET merge_add_columns = NULL, needs_review = NULL")
        con.execute("DROP TABLE IF EXISTS _tmp_addmap")
        con.execute("CREATE TEMP TABLE _tmp_addmap(collection VARCHAR, add_cols VARCHAR, review BOOLEAN)")
        con.executemany(
            "INSERT INTO _tmp_addmap VALUES (?,?,?)",
            [(c, v[0], v[1]) for c, v in cmap.items()],
        )
        con.execute(f"""
            UPDATE {TABLE} AS d
            SET merge_add_columns = m.add_cols, needs_review = m.review
            FROM _tmp_addmap m
            WHERE d.merge_method = 'curate' AND d."Collection" = m.collection
        """)
        con.execute("DROP TABLE IF EXISTS _tmp_addmap")

        # Verify.
        print("\nWritten. Verification (curate rows):")
        for val, n in con.execute(f"""
            SELECT COALESCE(merge_add_columns,'(null)'), COUNT(*)
            FROM {TABLE} WHERE merge_method='curate' GROUP BY 1 ORDER BY COUNT(*) DESC
        """).fetchall():
            print(f"  merge_add_columns={val:<18} : {n:>8}")
        nr = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE merge_method='curate' AND needs_review"
        ).fetchone()[0]
        leaked = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE merge_method IS DISTINCT FROM 'curate' "
            f"AND (merge_add_columns IS NOT NULL OR needs_review IS NOT NULL)"
        ).fetchone()[0]
        print(f"  needs_review=TRUE (curate)        : {nr}")
        print(f"  non-curate rows touched (must be 0): {leaked}")
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Detect dimension columns to add per curate collection."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    parser.add_argument("--db", default=DB_PATH, help="DuckDB file.")
    parser.add_argument("--table", default=TABLE, help="Target table.")
    args = parser.parse_args()
    main(dry_run=args.dry_run, db=args.db, table=args.table)
