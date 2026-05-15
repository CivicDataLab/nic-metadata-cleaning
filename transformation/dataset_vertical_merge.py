
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import pandas as pd

# Make sibling imports work whether run as script or module
sys.path.insert(0, str(Path(__file__).parent))

from dataset_merge import normalize_title
from utils.dataset_headers import header_signature

DB_PATH = Path(__file__).parent / "metadata.db"
TABLE = "dublin_core_metadata"
MERGE_THRESHOLD = 2
OUT_DIR = Path(__file__).parent


def _group_id(collection: str, title_base: str, signature: tuple[str, ...]) -> str:
    """Deterministic 12-hex-char ID derived from (Collection, title_base, signature)."""
    key = collection + "::" + title_base + "::" + "|".join(signature)
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return h[:12]


def _pick_canonical_title(titles: list[str]) -> str:
    """Most-common title, ties broken by shortest length, then lexicographic."""
    counts = Counter(titles)
    max_count = max(counts.values())
    candidates = [t for t, c in counts.items() if c == max_count]
    candidates.sort(key=lambda t: (len(t), t))
    return candidates[0]


def _group_name(titles: list[str]) -> str:
    canonical = _pick_canonical_title(titles)
    normalised = normalize_title(canonical)
    if len(normalised) < 8 or len(normalised.split()) < 2:
        return canonical
    return normalised


def _disambiguate_names(groups: dict) -> None:
    """
    Mutate `groups` in place so every merge_group_name is unique.

    When the same (Collection, normalize_title) produces multiple groups
    (because the column schema varies), each group gets the same name. Append
    a "#N" suffix to disambiguate, ordered largest-first then by group_id so
    the assignment is deterministic across runs.
    """
    by_name: dict[str, list[str]] = defaultdict(list)
    for gid, g in groups.items():
        by_name[g["name"]].append(gid)

    for name, gids in by_name.items():
        if len(gids) < 2:
            continue
        gids.sort(key=lambda gid: (-len(groups[gid]["members"]), gid))
        for i, gid in enumerate(gids, start=1):
            groups[gid]["name"] = f"{name} #{i}"


def build_groups(conn: duckdb.DuckDBPyConnection, batch: int | None = None) -> dict:
    """
    Returns:
      {
        group_id: {
          "name": str,
          "signature": tuple[str, ...],
          "members": [(uuid, title, collection), ...]
        }
      }
    """
    query = f'''
        SELECT "Identifier[UUID]", "Title", "Collection", "Conforms To"
        FROM {TABLE}
        WHERE "Conforms To" IS NOT NULL AND "Conforms To" != ''
    '''
    if batch is not None:
        query += f" AND batch = {batch}"

    rows = conn.execute(query).fetchall()

    # Group by (Collection, title_base, signature). Collection alone is not
    # discriminating enough — dataset_merge.py's fuzzy-merge step can fold
    # semantically distinct titles (e.g. IPD vs OPD Attendance) into the
    # same Collection. Adding normalize_title() as a secondary key recovers
    # the pre-fuzzy distinction. Rows with NULL Collection are skipped.
    by_key: dict[tuple[str, str, tuple[str, ...]], list[tuple[str, str, str]]] = defaultdict(list)
    for uuid, title, collection, conforms in rows:
        if not collection:
            continue
        sig = header_signature(conforms)
        if not sig:
            continue
        title_base = normalize_title(title).lower()
        by_key[(collection, title_base, sig)].append((uuid, title, collection))

    groups: dict = {}
    for (collection, title_base, sig), members in by_key.items():
        if len(members) < MERGE_THRESHOLD:
            continue
        gid = _group_id(collection, title_base, sig)
        titles = [t for _, t, _ in members]
        groups[gid] = {
            "name": _group_name(titles),
            "collection": collection,
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
    for col in ("merge_group_id", "merge_group_name"):
        if col not in existing:
            conn.execute(f'ALTER TABLE {TABLE} ADD COLUMN {col} VARCHAR')

    # Clear previous values so removed members don't keep a stale id
    conn.execute(
        f'UPDATE {TABLE} SET merge_group_id = NULL, merge_group_name = NULL'
    )

    if not groups:
        return

    rows = []
    for gid, g in groups.items():
        for uuid, _title, _coll in g["members"]:
            rows.append((uuid, gid, g["name"]))

    mapping_df = pd.DataFrame(rows, columns=["uuid", "merge_group_id", "merge_group_name"])

    conn.execute("DROP TABLE IF EXISTS _tmp_merge_map")
    conn.execute("CREATE TEMP TABLE _tmp_merge_map AS SELECT * FROM mapping_df")
    conn.execute(f'''
        UPDATE {TABLE} AS d
        SET merge_group_id   = m.merge_group_id,
            merge_group_name = m.merge_group_name
        FROM _tmp_merge_map m
        WHERE d."Identifier[UUID]" = m.uuid
    ''')
    conn.execute("DROP TABLE IF EXISTS _tmp_merge_map")


def mark_duplicates_for_archive(conn: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    """
    Within each merge_group_id, rows whose Title matches (case-insensitive,
    trimmed) another row are duplicates. Keep the row with the latest
    `Date Modified` (UUID tie-break) and flag the rest with archive=TRUE.

    Returns (buckets_with_dupes, rows_flagged).
    """
    existing = {
        r[0]
        for r in conn.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{TABLE}'"
        ).fetchall()
    }
    if "archive" not in existing:
        conn.execute(f'ALTER TABLE {TABLE} ADD COLUMN archive BOOLEAN DEFAULT FALSE')

    # Reset so removed duplicates don't keep stale flags
    conn.execute(f'UPDATE {TABLE} SET archive = FALSE')

    conn.execute(f'''
        UPDATE {TABLE} SET archive = TRUE
        WHERE "Identifier[UUID]" IN (
            WITH ranked AS (
                SELECT "Identifier[UUID]",
                       ROW_NUMBER() OVER (
                           PARTITION BY merge_group_id, LOWER(TRIM("Title"))
                           ORDER BY "Date Modified" DESC NULLS LAST,
                                    "Identifier[UUID]" ASC
                       ) AS rn,
                       COUNT(*) OVER (
                           PARTITION BY merge_group_id, LOWER(TRIM("Title"))
                       ) AS bucket_size
                FROM {TABLE}
                WHERE merge_group_id IS NOT NULL
            )
            SELECT "Identifier[UUID]" FROM ranked
            WHERE rn > 1 AND bucket_size >= 2
        )
    ''')

    rows_flagged = conn.execute(
        f'SELECT COUNT(*) FROM {TABLE} WHERE archive = TRUE'
    ).fetchone()[0]
    buckets = conn.execute(f'''
        SELECT COUNT(*) FROM (
            SELECT merge_group_id, LOWER(TRIM("Title"))
            FROM {TABLE}
            WHERE merge_group_id IS NOT NULL
            GROUP BY merge_group_id, LOWER(TRIM("Title"))
            HAVING COUNT(*) >= 2
        )
    ''').fetchone()[0]

    return buckets, rows_flagged


def write_reports(groups: dict, out_dir: Path) -> tuple[Path, Path]:
    json_path = out_dir / "vertical_merge_groups.json"
    csv_path = out_dir / "vertical_merge_groups.csv"

    json_groups = []
    for gid, g in sorted(groups.items(), key=lambda kv: -len(kv[1]["members"])):
        members = g["members"]
        sample_titles = list({t for _, t, _ in members})[:5]
        json_groups.append({
            "merge_group_id": gid,
            "merge_group_name": g["name"],
            "collection": g["collection"],
            "signature_size": len(g["signature"]),
            "total_members": len(members),
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
        w.writerow(["merge_group_id", "merge_group_name", "Identifier[UUID]", "Title", "Collection"])
        for gid, g in groups.items():
            for uuid, title, coll in g["members"]:
                w.writerow([gid, g["name"], uuid, title, coll or ""])

    return json_path, csv_path


def print_summary(conn: duckdb.DuckDBPyConnection, groups: dict) -> None:
    total_mergeable = sum(len(g["members"]) for g in groups.values())
    collections_with_groups = len({g["collection"] for g in groups.values()})

    print(f"\n{'=' * 70}")
    print(f"  Merge groups (>= {MERGE_THRESHOLD} members) : {len(groups):>10}")
    print(f"  Rows in any merge group              : {total_mergeable:>10}")
    print(f"  Collections with >=1 merge group     : {collections_with_groups:>10}")
    print(f"{'=' * 70}")

    print(f"\n  Top 15 groups by size:\n")
    print(f"  {'group_id':<14} {'sig_cols':>8} {'members':>8}  collection / name")
    print(f"  {'-' * 100}")
    for gid, g in sorted(groups.items(), key=lambda kv: -len(kv[1]["members"]))[:15]:
        coll = g["collection"] if len(g["collection"]) <= 50 else g["collection"][:47] + "..."
        name = g["name"] if len(g["name"]) <= 40 else g["name"][:37] + "..."
        print(f"  {gid:<14} {len(g['signature']):>8} {len(g['members']):>8}  [{coll}] {name}")

    # IPD Attendance Collection sanity-check: dataset_merge.py over-broadly
    # grouped both IPD and OPD titles into this Collection. After adding
    # title_base to the grouping key, every resulting group must be
    # exclusively IPD or exclusively OPD (no mixed-title groups). Total
    # member rows must still equal the input row count for the Collection.
    target = "Range-wise Performance of Public Facilities for IPD Attendance"
    ipd_only = opd_only = mixed = 0
    ipd_members = 0
    for g in groups.values():
        in_coll = [m for m in g["members"] if m[2] == target]
        if not in_coll:
            continue
        ipd_members += len(in_coll)
        has_ipd = any("IPD" in t for _, t, _ in in_coll)
        has_opd = any("OPD" in t for _, t, _ in in_coll)
        if has_ipd and has_opd:
            mixed += 1
        elif has_ipd:
            ipd_only += 1
        elif has_opd:
            opd_only += 1
    expected_total = conn.execute(
        f'SELECT COUNT(*) FROM {TABLE} '
        f'WHERE "Collection" = ? AND "Conforms To" IS NOT NULL AND "Conforms To" != \'\'',
        [target],
    ).fetchone()[0]
    print(f"\n  Falsifiable check — '{target}':")
    print(f"    rows with non-null Conforms To  : {expected_total}")
    print(f"    rows assigned to a merge group  : {ipd_members}")
    print(f"    IPD-only groups   : {ipd_only}")
    print(f"    OPD-only groups   : {opd_only}")
    print(f"    Mixed groups      : {mixed}  (must be 0)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect vertically-mergeable datasets")
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

    print("Building merge groups...")
    groups = build_groups(conn, batch=args.batch)
    _disambiguate_names(groups)

    json_path, csv_path = write_reports(groups, out_dir)
    print(f"JSON written: {json_path}")
    print(f"CSV  written: {csv_path}")

    print_summary(conn, groups)

    if args.dry_run:
        print("\n[DRY RUN] Skipping database writes.")
    else:
        print("\nApplying merge_group_id / merge_group_name to database...")
        apply_to_db(conn, groups)
        print("Marking duplicate-Title rows for archive...")
        buckets, flagged = mark_duplicates_for_archive(conn)
        print(f"  Duplicate-title buckets : {buckets}")
        print(f"  Rows flagged archive=TRUE: {flagged}")
        print("Done.")

    conn.close()


if __name__ == "__main__":
    main()
