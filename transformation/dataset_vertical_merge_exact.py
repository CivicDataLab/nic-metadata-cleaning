"""
Vertical-merge detection using *exact* header equality plus a title-base check.

Two datasets are mergeable iff:
  1. Their `Conforms To` column lists are identical after splitting on comma
     and trimming whitespace (case, punctuation, order, and serial-number
     columns are all significant).
  2. Their titles, after stripping temporal and geographic variable parts via
     `normalize_title`, match case-insensitively.
  3. The shared header signature contains a standalone temporal column
     (e.g. "Year", "Month", "Period"). Groups whose temporal axis lives only
     in column names (wide form, like "Births 201112") are excluded because
     merging them requires a pivot — i.e. modifying the data.

The title-base check prevents semantically distinct datasets that happen to
share a column schema (e.g. IPD vs OPD attendance reports) from being pooled
into the same group. Unlike `dataset_vertical_merge.py`, this script still
does NOT key on Collection.
"""

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import pandas as pd

# Make sibling import work whether run as script or module
sys.path.insert(0, str(Path(__file__).parent))

from dataset_merge import normalize_title

DB_PATH = Path(__file__).parent / "metadata.db"
TABLE = "dublin_core_metadata"
GROUPS_TABLE = "exact_merge_groups"
MERGE_THRESHOLD = 2
OUT_DIR = Path(__file__).parent

GROUP_ID_COL = "exact_merge_group_id"
GROUP_NAME_COL = "exact_merge_group_name"
GROUPS_TABLE_NAME_COL = "merge_group_name"

# Whole-name (case-insensitive) match. A group is kept only if its header
# signature already contains one of these — meaning the temporal axis is
# data, not encoded in column names (wide-form like "Births 201112" would
# need a pivot to merge, so it's excluded by design).
TEMPORAL_HEADER_NAMES = frozenset({
    "year", "month", "date", "period", "quarter",
    "financial year", "fiscal year",
    "reporting year", "reporting month", "reporting period",
    "time period", "reference period", "mid year",
})


def _has_temporal_column(signature: tuple[str, ...]) -> bool:
    return any(h.strip().lower() in TEMPORAL_HEADER_NAMES for h in signature)


def exact_header_signature(conforms_to: str) -> tuple[str, ...]:
    """
    Split `Conforms To` on commas and strip whitespace from each header.
    Returns the tuple as-is (order preserved, case preserved, nothing
    dropped). Empty input returns ().
    """
    if not conforms_to:
        return ()
    parts = tuple(p.strip() for p in conforms_to.split(","))
    # Drop only fully-empty headers (e.g. trailing comma artefacts);
    # everything else is significant.
    parts = tuple(p for p in parts if p)
    return parts


def _group_id(signature: tuple[str, ...], title_base: str) -> str:
    """Deterministic 12-hex-char ID derived from (header signature, title_base)."""
    key = "|".join(signature) + "::" + title_base
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _pick_group_name(titles: list[str]) -> str:
    """Most-common title; ties broken by shortest length, then lexicographic."""
    counts = Counter(titles)
    max_count = max(counts.values())
    candidates = [t for t, c in counts.items() if c == max_count]
    candidates.sort(key=lambda t: (len(t), t))
    return candidates[0]


def build_groups(conn: duckdb.DuckDBPyConnection, batch: int | None = None) -> dict:
    """
    Returns:
      {
        group_id: {
          "name": str,
          "signature": tuple[str, ...],
          "members": [(uuid, title, collection, conforms), ...]
        }
      }
    """
    columns = {
        r[0]
        for r in conn.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{TABLE}'"
        ).fetchall()
    }

    query = f'''
        SELECT "Identifier[UUID]", "Title", "Collection", "Conforms To"
        FROM {TABLE}
        WHERE "Conforms To" IS NOT NULL AND "Conforms To" != ''
    '''
    if "archive" in columns:
        query += " AND archive IS NOT TRUE"
    if batch is not None:
        query += f" AND batch = {batch}"

    rows = conn.execute(query).fetchall()

    by_key: dict[tuple[tuple[str, ...], str], list[tuple[str, str, str, str]]] = defaultdict(list)
    for uuid, title, collection, conforms in rows:
        sig = exact_header_signature(conforms)
        if not sig:
            continue
        title_base = normalize_title(title or "").lower()
        if not title_base:
            continue
        by_key[(sig, title_base)].append((uuid, title, collection or "", conforms or ""))

    groups: dict = {}
    for (sig, title_base), members in by_key.items():
        if len(members) < MERGE_THRESHOLD:
            continue
        if not _has_temporal_column(sig):
            continue
        gid = _group_id(sig, title_base)
        groups[gid] = {
            "name": _pick_group_name([t for _, t, _, _ in members]),
            "title_base": title_base,
            "signature": sig,
            "members": members,
        }
    return groups


def apply_to_db(conn: duckdb.DuckDBPyConnection, groups: dict) -> None:
    existing = {
        r[0]
        for r in conn.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{TABLE}'"
        ).fetchall()
    }
    for col in (GROUP_ID_COL, GROUP_NAME_COL):
        if col not in existing:
            conn.execute(f'ALTER TABLE {TABLE} ADD COLUMN {col} VARCHAR')

    conn.execute(
        f'UPDATE {TABLE} SET {GROUP_ID_COL} = NULL, {GROUP_NAME_COL} = NULL'
    )

    if not groups:
        return

    rows = []
    for gid, g in groups.items():
        for uuid, _t, _c, _conf in g["members"]:
            rows.append((uuid, gid, g["name"]))

    mapping_df = pd.DataFrame(
        rows, columns=["uuid", "group_id", "group_name"]
    )

    conn.execute("DROP TABLE IF EXISTS _tmp_exact_merge_map")
    conn.execute("CREATE TEMP TABLE _tmp_exact_merge_map AS SELECT * FROM mapping_df")
    conn.execute(f'''
        UPDATE {TABLE} AS d
        SET {GROUP_ID_COL}   = m.group_id,
            {GROUP_NAME_COL} = m.group_name
        FROM _tmp_exact_merge_map m
        WHERE d."Identifier[UUID]" = m.uuid
    ''')
    conn.execute("DROP TABLE IF EXISTS _tmp_exact_merge_map")


def apply_groups_table_to_db(conn: duckdb.DuckDBPyConnection, groups: dict) -> None:
    """
    Persist the groups themselves as a standalone table (one row per group),
    in addition to the per-row mapping on {TABLE}.
    """
    conn.execute(f'DROP TABLE IF EXISTS {GROUPS_TABLE}')
    conn.execute(f'''
        CREATE TABLE {GROUPS_TABLE} (
            {GROUP_ID_COL}          VARCHAR PRIMARY KEY,
            {GROUPS_TABLE_NAME_COL} VARCHAR,
            title_base              VARCHAR,
            headers                 VARCHAR,
            signature_size          INTEGER,
            total_members           INTEGER
        )
    ''')

    if not groups:
        return

    rows = [
        (
            gid,
            g["name"],
            g["title_base"],
            ", ".join(g["signature"]),
            len(g["signature"]),
            len(g["members"]),
        )
        for gid, g in groups.items()
    ]
    groups_df = pd.DataFrame(
        rows,
        columns=[
            GROUP_ID_COL,
            GROUPS_TABLE_NAME_COL,
            "title_base",
            "headers",
            "signature_size",
            "total_members",
        ],
    )
    conn.execute(f'INSERT INTO {GROUPS_TABLE} SELECT * FROM groups_df')


def write_reports(groups: dict, out_dir: Path) -> tuple[Path, Path]:
    json_path = out_dir / "vertical_merge_groups_exact.json"
    csv_path = out_dir / "vertical_merge_groups_exact.csv"

    json_groups = []
    for gid, g in sorted(groups.items(), key=lambda kv: -len(kv[1]["members"])):
        members = g["members"]
        sample_titles = list({t for _, t, _, _ in members})[:5]
        collections = sorted({c for _, _, c, _ in members if c})
        json_groups.append({
            GROUP_ID_COL: gid,
            GROUP_NAME_COL: g["name"],
            "signature_size": len(g["signature"]),
            "headers": list(g["signature"]),
            "total_members": len(members),
            "collections": collections,
            "sample_titles": sample_titles,
        })

    payload = {
        "total_groups": len(groups),
        "total_members": sum(len(g["members"]) for g in groups.values()),
        "groups": json_groups,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            GROUP_ID_COL, GROUP_NAME_COL,
            "Identifier[UUID]", "Title", "Collection", "Conforms To",
        ])
        for gid, g in groups.items():
            for uuid, title, coll, conforms in g["members"]:
                w.writerow([gid, g["name"], uuid, title, coll, conforms])

    return json_path, csv_path


def print_summary(groups: dict) -> None:
    total_members = sum(len(g["members"]) for g in groups.values())
    collections_touched = len({
        c for g in groups.values() for _, _, c, _ in g["members"] if c
    })

    print(f"\n{'=' * 70}")
    print(f"  Exact-header merge groups (>= {MERGE_THRESHOLD} members) : {len(groups):>10}")
    print(f"  Rows in any merge group                       : {total_members:>10}")
    print(f"  Distinct collections touched                  : {collections_touched:>10}")
    print(f"{'=' * 70}")

    print(f"\n  Top 15 groups by size:\n")
    print(f"  {'group_id':<14} {'sig_cols':>8} {'members':>8}  name")
    print(f"  {'-' * 100}")
    for gid, g in sorted(groups.items(), key=lambda kv: -len(kv[1]["members"]))[:15]:
        name = g["name"] if len(g["name"]) <= 70 else g["name"][:67] + "..."
        print(f"  {gid:<14} {len(g['signature']):>8} {len(g['members']):>8}  {name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect vertically-mergeable datasets by exact header equality"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute groups and write reports, but skip DB updates")
    parser.add_argument("--batch", type=int, default=None,
                        help="Process only this batch number")
    parser.add_argument("--db", default=str(DB_PATH), help="DuckDB database path")
    parser.add_argument("--out-dir", default=str(OUT_DIR), help="Reports output directory")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(args.db, read_only=args.dry_run)

    print("Building exact-header merge groups...")
    groups = build_groups(conn, batch=args.batch)

    json_path, csv_path = write_reports(groups, out_dir)
    print(f"JSON written: {json_path}")
    print(f"CSV  written: {csv_path}")

    print_summary(groups)

    if args.dry_run:
        print("\n[DRY RUN] Skipping database writes.")
    else:
        print(f"\nApplying {GROUP_ID_COL} / {GROUP_NAME_COL} to database...")
        apply_to_db(conn, groups)
        print(f"Writing groups table '{GROUPS_TABLE}'...")
        apply_groups_table_to_db(conn, groups)
        print("Done.")

    conn.close()


if __name__ == "__main__":
    main()