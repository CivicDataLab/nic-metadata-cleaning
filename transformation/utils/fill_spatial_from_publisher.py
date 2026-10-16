"""
Fill the spatial coverage that Spatial_script.py leaves NULL, using the two
metadata fields it never reads: the PUBLISHER and the CATALOG TITLE.

Spatial_script.py resolves coverage from a dataset's own contents and from its
own title, and deliberately writes nothing when neither carries a geography:
plain "India" is a positive claim of national scope, and hvd_score.signal_geo
grants 0.5 geo credit for the literal string "India", so an unevidenced fill
would move live scores. This script supplies the missing evidence from fields
that are decisive on this corpus - every row still blank is Jurisdiction =
'Central' with an empty Publisher[state_department], and its publisher string
either names a State/UT or names none at all:

    "Ministry of Housing and Urban Affairs, Smart Cities Mission,
     Maharashtra, Pimpri Chinchwad"      -> Pimpri Chinchwad, Maharashtra, India
    "Rajya Sabha" / "…NCRB" / "NITI Aayog"
                                         -> India

Evidence is taken most-specific-first, and spatial_source records which field
won, so rows filled from a weaker signal stay separable for review or rollback:

  1. publisher names a State with a trailing segment after it
        -> "<that segment>, <State>, India"   level=district  source=publisher
  2. publisher names a State and nothing follows it
        -> "<State>, India"                   level=state     source=publisher
  3. catalog title names exactly one State
        -> "<State>, India"                   level=state     source=catalog_title
     ("Projects funded by MDoNER for Bodo Territorial Council (BTC), Assam")
  4. catalog title says India / All-India outright
        -> "India"                            level=national  source=catalog_title
  5. nothing above, and the publisher is a central body with no State
        -> "India"                            level=national  source=publisher

The publisher outranks the catalog title because it is structured (ministry ->
mission -> State -> city) and therefore more specific; the catalog title only
ever yields a State, never a district. A catalog title naming SEVERAL States is
ignored rather than guessed at - Spatial_script's contract is that the token
before the trailing "India" is the State, so a multi-State list cannot be
written into the coverage string.

Districts are not read out of the catalog title: that needs Spatial_script's
harvested gazetteer to tell a real district from a title fragment, and on this
corpus it yielded none.

The coverage string keeps Spatial_script's contract, so hvd_score.parse_state
keeps working on everything written here.

Both tables are updated: "remaining-raw-datasets" (the pipeline table) and
dublin_core_remaining, where the Dublin Core field "Spatial Coverage" is a
straight copy of spatial_coverage (see metdata_transform_dublin.py).

Usage:
    python fill_spatial_from_publisher.py --dry-run    # classify + preview
    python fill_spatial_from_publisher.py              # write both tables
    python fill_spatial_from_publisher.py --backup     # snapshot cols first
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

sys.path.insert(0, str(ROOT / "transformation" / "temporal"))

from Spatial_script import (  # noqa: E402
    _NATIONAL_TITLE_RE,
    canon_state,
    states_from_title,
)

DB_PATH = str(ROOT / "transformation" / "metadata.db")

RAW_TABLE = "remaining-raw-datasets"
RAW_UUID = "uuid"
RAW_PUBLISHER = "ministry_department"
RAW_CATALOG = "catalog_title"

DUBLIN_TABLE = "dublin_core_remaining"
DUBLIN_UUID = "Identifier[UUID]"

SPATIAL_COLS = [
    "spatial_coverage",
    "spatial_states",
    "spatial_districts",
    "spatial_subdistricts",
    "spatial_level",
    "spatial_source",
]

SOURCE_PUBLISHER = "publisher"
SOURCE_CATALOG = "catalog_title"


# =========================================================
# CLASSIFY ONE PUBLISHER STRING
# =========================================================


def split_publisher(publisher):
    """-> [segment, ...] of a comma-separated publisher string."""
    if not publisher:
        return []
    return [seg.strip() for seg in str(publisher).split(",") if seg.strip()]


def _row(coverage, level, source, state=None, district=None):
    return {
        "spatial_coverage": coverage,
        "spatial_states": state,
        "spatial_districts": district,
        "spatial_subdistricts": None,
        "spatial_level": level,
        "spatial_source": source,
    }


def resolve_publisher(publisher):
    """-> dict of spatial columns implied by a publisher string, or None.

    None means "this publisher names no State"; the caller then falls through to
    the catalog title before settling for plain "India".

    The State is looked for from the RIGHT: these strings run
    ministry -> mission -> State -> city, so the last State-looking segment is
    the geography and anything after it is the place inside that State. Reading
    left-to-right would trip over publishers that carry a State inside their own
    name ("Registrar General and Census Commissioner, India").
    """
    segments = split_publisher(publisher)

    state = None
    state_at = None
    for idx in range(len(segments) - 1, -1, -1):
        hit = canon_state(segments[idx], strict=True)
        if hit:
            state, state_at = hit, idx
            break

    if state is None:
        return None

    tail = segments[state_at + 1:]

    # "Maharashtra, Pimpri Chinchwad" -> the city is the sub-State unit. It is
    # recorded as the district: it occupies the district slot of the coverage
    # string, and a Smart Cities city is the city-level unit this corpus has.
    # A city that repeats its State's name (Delhi, Puducherry) says nothing
    # extra, so it collapses to the State rather than doubling it.
    if tail and tail[-1].casefold() != state.casefold():
        place = tail[-1]
        return _row(f"{place}, {state}, India", "district", SOURCE_PUBLISHER,
                    state=state, district=place)

    return _row(f"{state}, India", "state", SOURCE_PUBLISHER, state=state)


def resolve_catalog_title(catalog_title):
    """-> dict of spatial columns implied by a catalog title, or None.

    Only two shapes are trusted: exactly one State named, or an explicit
    India / All-India. Several States is a list the coverage string cannot
    hold (see the module docstring), so it is left for the caller's fallback.
    """
    text = (catalog_title or "").strip()
    if not text:
        return None

    states = states_from_title(text)
    if len(states) == 1:
        return _row(f"{states[0]}, India", "state", SOURCE_CATALOG,
                    state=states[0])

    if not states and _NATIONAL_TITLE_RE.search(text):
        return _row("India", "national", SOURCE_CATALOG)

    return None


def resolve_row(publisher, catalog_title):
    """Most specific evidence wins; plain 'India' is the last resort."""
    return (
        resolve_publisher(publisher)
        or resolve_catalog_title(catalog_title)
        or _row("India", "national", SOURCE_PUBLISHER)
    )


# =========================================================
# DB
# =========================================================


def backup_columns(con, table, uuid_col):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = table.replace("-", "_")
    dest = str(ROOT / "data" / "backups" / f"spatial_cols_{safe}_{stamp}.csv")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    cols = ", ".join(f'"{c}"' for c in SPATIAL_COLS)
    con.execute(
        f'COPY (SELECT "{uuid_col}", {cols} FROM "{table}") '
        f"TO '{dest}' (HEADER, DELIMITER ',')"
    )
    print(f"  snapshot: {dest}")


def fetch_blanks(con, table, uuid_col, publisher_col, catalog_col):
    """Rows whose spatial_coverage is still empty, with their two evidence
    fields. Both tables key on the same uuid, so one read drives both writes."""
    return con.execute(
        f'''
        SELECT "{uuid_col}" AS uuid,
               "{publisher_col}" AS publisher,
               "{catalog_col}" AS catalog_title
        FROM "{table}"
        WHERE "{uuid_col}" IS NOT NULL
          AND coalesce(spatial_coverage, '') = ''
        '''
    ).fetchall()


def write_updates(con, table, uuid_col, resolved, dublin=False):
    """Push the resolved columns back, 20k rows at a time."""
    import pandas as pd

    frame = pd.DataFrame(resolved)
    if frame.empty:
        print(f"  {table}: nothing to write")
        return 0

    for col in SPATIAL_COLS:
        con.execute(
            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{col}" VARCHAR'
        )

    sets = ", ".join(f'"{c}" = u.{c}' for c in SPATIAL_COLS)
    if dublin:
        # "Spatial Coverage" is the Dublin Core face of spatial_coverage; the
        # two are defined as equal, so they must move together.
        sets += ', "Spatial Coverage" = u.spatial_coverage'

    written = 0
    chunk = 20000
    for start in range(0, len(frame), chunk):
        part = frame.iloc[start:start + chunk]
        con.register("pub_upd", part)
        con.execute(
            f'''
            UPDATE "{table}" AS d
            SET {sets}
            FROM pub_upd AS u
            WHERE d."{uuid_col}" = u.uuid
            '''
        )
        con.unregister("pub_upd")
        written += len(part)
        print(f"  {table}: wrote {written}/{len(frame)}", flush=True)

    return written


# =========================================================
# MAIN
# =========================================================


def preview(resolved, rows):
    from collections import Counter

    levels = Counter(r["spatial_level"] for r in resolved)
    print(f"\nlevels: {dict(levels)}")

    sources = Counter(r["spatial_source"] for r in resolved)
    print(f"sources: {dict(sources)}")

    seen = Counter()
    print("\n-- sample: up to 6 rows per (level, source) --")
    for r, (_, publisher, catalog_title) in zip(resolved, rows):
        key = (r["spatial_level"], r["spatial_source"])
        if seen[key] >= 6:
            continue
        seen[key] += 1
        evidence = publisher if r["spatial_source"] == SOURCE_PUBLISHER else catalog_title
        print(f"  {r['spatial_level']:<9} | {r['spatial_source']:<13} | "
              f"{str(r['spatial_coverage']):<38} | {(evidence or '')[:70]}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--dry-run", action="store_true",
                    help="classify and preview; write nothing")
    ap.add_argument("--backup", action="store_true",
                    help="dump uuid + the spatial columns of both tables to "
                         "data/backups/ before writing")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=args.dry_run)

    rows = fetch_blanks(con, RAW_TABLE, RAW_UUID, RAW_PUBLISHER, RAW_CATALOG)
    print(f'{RAW_TABLE}: {len(rows)} rows with no spatial_coverage')

    # With neither field there is no evidence at all, and the whole point of
    # this script is not to claim "India" without any.
    blind = sum(1 for _, p, c in rows
                if not (p or "").strip() and not (c or "").strip())
    if blind:
        print(f"  ...of which {blind} have neither publisher nor catalog "
              f"title - skipped")

    todo = [(u, p, c) for u, p, c in rows
            if (p or "").strip() or (c or "").strip()]
    resolved = [dict(resolve_row(p, c), uuid=u) for u, p, c in todo]

    preview(resolved, todo)

    if args.dry_run:
        print("\nDRY RUN - nothing written")
        con.close()
        return

    if args.backup:
        backup_columns(con, RAW_TABLE, RAW_UUID)
        backup_columns(con, DUBLIN_TABLE, DUBLIN_UUID)

    print()
    write_updates(con, RAW_TABLE, RAW_UUID, resolved)
    write_updates(con, DUBLIN_TABLE, DUBLIN_UUID, resolved, dublin=True)

    for table, uuid_col in ((RAW_TABLE, RAW_UUID), (DUBLIN_TABLE, DUBLIN_UUID)):
        left = con.execute(
            f'''SELECT count(*) FROM "{table}"
                WHERE coalesce(spatial_coverage, '') = ''
                  AND "{uuid_col}" IS NOT NULL'''
        ).fetchone()[0]
        print(f"{table}: {left} rows still blank")

    con.close()


if __name__ == "__main__":
    main()
