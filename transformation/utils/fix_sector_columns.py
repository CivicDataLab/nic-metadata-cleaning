"""
Put the sector columns of the lot 2 / lot 3 dataset tables into the SECTOR_VOCAB
format of llm_batch_classifier.py ("Sector; Sub-sector" pairs joined by ", ",
a bare Sector when no sub-sector fits).

  Subject[sector_resource]  the dataset's own sector. It takes the per-dataset
      generated_theme that the fill scripts had written to Subject[sector],
      repaired where it broke the vocabulary, and replaces the raw portal value
      ('All', 'Statistics', "Census, Census and Surveys, ..."). The raw value
      stays in remaining-raw-datasets / lot3_raw.
  Subject[sector]           the catalog's sector, one value per
      new_catalog_title, read from dublin_catalog_lot2n3. A catalog with no row
      there gets the commonest Subject[sector_resource] of its datasets.
  Catalog side              remaining_catalog.generated_sector and
      dublin_catalog_lot2n3."Subject[sector]" first take the corrections in
      catalog_sector_changes.csv; the same rows are appended to the classifier's
      results CSV so a later `llm_catalog_classifier_remaining.py --sync` keeps them.

Repair of a malformed theme:
  - rules: the sector is repeated for every sub-sector ("Education; Elementary,
    Secondary"), a bare sub-sector goes to the one sector that lists it,
    "Census and Surveys; Population Enumerator" becomes "Census; Population
    Enumerator" (that is where the vocabulary lists it), and the two terms the
    vocabulary misspells are written its way ("Corportae governance",
    "District Adminstration");
  - sector_units.csv: every other fragment ("Economy; Revenue", "Fisheries;
    Fishery", ...) -> its vocabulary value, classified by two Haiku agents from
    the dataset titles (2026-10-13);
  - dataset_sector_overrides.csv: datasets that get their own value - the two
    whose theme was still 'All', and the rows of "Energy; Renewable" /
    "Energy; Non Renewable" that are not LPG.

Order matters and step 1 runs once: after it Subject[sector] no longer holds the
per-dataset theme. The script detects that from the raw markers ('All',
'Statistics', 'Others') being gone from Subject[sector_resource] and then only
re-applies the catalog steps. No snapshot is written; everything is one
transaction and every value is checked against the vocabulary before the commit.

Usage:
  python fix_sector_columns.py --dry-run     # counts only, rolled back
  python fix_sector_columns.py
"""
import argparse
import csv
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
WORK = HERE.parent.parent / "data" / "sector_work"
UNITS_CSV = WORK / "sector_units.csv"
OVERRIDES_CSV = WORK / "dataset_sector_overrides.csv"
CATALOG_CSV = WORK / "catalog_sector_changes.csv"
RESULTS_CSV = HERE.parent / "text_generation" / "remaining_catalog_llm_results.csv"

DATASET_TABLES = ["dublin_core_remaining", "dublin_core_lot3"]
CATALOG_SOURCE = "remaining_catalog"
CATALOG_TABLE = "dublin_catalog_lot2n3"
RAW_MARKERS = ("All", "Statistics", "Others")

_prompt = (HERE.parent / "llm_batch_classifier.py").read_text(encoding="utf-8")
VOCAB = {line.split(":", 1)[0].strip(): [s.strip() for s in line.split(":", 1)[1].split(",")]
         for line in _prompt.split("SECTOR_VOCAB:\n", 1)[1].split("\n\n", 1)[0].splitlines()}
SUB_HOME: dict[str, list[str]] = {}
for _sector, _subs in VOCAB.items():
    for _sub in _subs:
        SUB_HOME.setdefault(_sub, []).append(_sector)
# The vocabulary's own spelling wins, so one value never has two spellings.
TYPO = {("Industries", "Corporate governance"): "Corportae governance",
        ("Governance and Administration", "District Administration"): "District Adminstration"}


def valid_pair(pair: str) -> bool:
    bits = pair.split("; ")
    return (len(bits) == 1 and bits[0] in VOCAB) or \
           (len(bits) == 2 and bits[0] in VOCAB and bits[1] in VOCAB[bits[0]])


def is_valid(value) -> bool:
    if value is None or not str(value).strip():
        return False
    pairs = str(value).split(", ")
    return all(valid_pair(p) for p in pairs) and len(set(pairs)) == len(pairs)


def repair(value: str, units: dict[str, str]) -> str:
    """Rebuild a malformed theme pair by pair; `units` places what the rules cannot."""
    out, prev = [], None
    for part in str(value).split(","):
        part = " ".join(part.split())
        if not part:
            continue
        bits = [b.strip() for b in part.split(";")]
        if len(bits) == 1:
            term = bits[0]
            if prev and term in VOCAB[prev]:
                out.append(f"{prev}; {term}")
            elif term in VOCAB:
                out.append(term)
                prev = term
            elif len(SUB_HOME.get(term, [])) == 1:
                out.append(f"{SUB_HOME[term][0]}; {term}")
            else:
                out += units[f"{prev} >> {term}" if prev else term].split(", ")
            continue
        sector, sub = bits[0], bits[1]
        if len(bits) == 2 and sector in VOCAB and sub in VOCAB[sector]:
            out.append(f"{sector}; {sub}")
        elif len(bits) == 2 and sector == "Census and Surveys" and sub in VOCAB["Census"]:
            out.append(f"Census; {sub}")
        elif len(bits) == 2 and (sector, sub) in TYPO:
            out.append(f"{sector}; {TYPO[(sector, sub)]}")
        else:
            out += units[part].split(", ")
        if sector in VOCAB:
            prev = sector
    # A bare Sector adds nothing once the same sector carries a sub-sector.
    with_sub = {p.split(";")[0] for p in out if ";" in p}
    return ", ".join(p for p in dict.fromkeys(out) if ";" in p or p not in with_sub)


def both(select: str) -> str:
    return " UNION ALL ".join(select.format(t=t) for t in DATASET_TABLES)


def move_dataset_theme(con: duckdb.DuckDBPyConnection, units: dict[str, str],
                       overrides: pd.DataFrame) -> None:
    """Step 1: Subject[sector_resource] = the repaired per-dataset theme."""
    themes = [r[0] for r in con.execute(
        "SELECT DISTINCT s FROM (" + both('SELECT "Subject[sector]" s FROM "{t}"') + ")").fetchall()]
    mapping = pd.DataFrame(
        [(t, t if is_valid(t) else repair(t, units)) for t in themes if t != "All"], columns=["old", "new"])
    bad = mapping[~mapping["new"].map(is_valid)]
    assert bad.empty, f"repair left invalid values: {bad.head().to_dict('records')}"
    con.register("theme_map_df", mapping)
    con.register("override_df", overrides)
    for t in DATASET_TABLES:
        con.execute(f'''UPDATE "{t}" SET "Subject[sector_resource]" = m.new
                        FROM theme_map_df m WHERE "{t}"."Subject[sector]" = m.old''')
        # nid is not unique across the two tables, so the override names its table and old theme.
        con.execute(f'''UPDATE "{t}" SET "Subject[sector_resource]" = o.new_value
                        FROM override_df o WHERE o."table" = '{t}' AND CAST("{t}".nid AS VARCHAR) = o.nid
                          AND "{t}"."Subject[sector]" = o.old_theme''')
        repaired = con.execute(f'''SELECT count(*) FROM "{t}"
                                   WHERE "Subject[sector_resource]" <> "Subject[sector]"''').fetchone()[0]
        print(f"  {t}: Subject[sector_resource] rewritten on every row; {repaired} themes repaired")


def fix_catalog_sectors(con: duckdb.DuckDBPyConnection, changes: pd.DataFrame) -> None:
    """Step 2: corrected catalog sectors, in the source table and the Dublin table."""
    con.register("cat_changes_df", changes[["new_catalog_title", "new_sector"]])
    for table, col in ((CATALOG_SOURCE, "generated_sector"), (CATALOG_TABLE, '"Subject[sector]"')):
        n = con.execute(f'''SELECT count(*) FROM {table} t JOIN cat_changes_df c
                            ON trim(t.new_catalog_title) = c.new_catalog_title
                            WHERE t.{col} IS DISTINCT FROM c.new_sector''').fetchone()[0]
        con.execute(f'''UPDATE {table} SET {col} = c.new_sector FROM cat_changes_df c
                        WHERE trim({table}.new_catalog_title) = c.new_catalog_title''')
        print(f"  {table}: {n} rows changed ({len(changes)} catalogs in {CATALOG_CSV.name})")


def append_to_results_csv(changes: pd.DataFrame) -> None:
    """Keep the classifier's results CSV in step, or its --sync would undo step 2."""
    if not RESULTS_CSV.exists():
        return
    # Read by position: the 50 --unnamed rows carry an extra field, which pandas rejects.
    csv.field_size_limit(sys.maxsize)
    with open(RESULTS_CSV, encoding="utf-8", newline="") as f:
        header, *rows = list(csv.reader(f))
    title, sector = header.index("new_catalog_title"), header.index("generated_sector")
    last = {r[title]: r for r in rows if len(r) == len(header)}
    wanted = dict(zip(changes["new_catalog_title"], changes["new_sector"]))
    add = [[*r[:sector], wanted[t], *r[sector + 1:]] for t, r in last.items()
           if t in wanted and r[sector] != wanted[t]]
    with open(RESULTS_CSV, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(add)
    print(f"  {RESULTS_CSV.name}: {len(add)} rows appended")


def spread_catalog_sector(con: duckdb.DuckDBPyConnection) -> None:
    """Step 3: Subject[sector] = the catalog's sector, on every dataset of the catalog."""
    con.execute(f'''CREATE OR REPLACE TEMP TABLE cat_sector AS
        SELECT trim(new_catalog_title) cat, min("Subject[sector]") sector,
               count(DISTINCT "Subject[sector]") k
        FROM {CATALOG_TABLE} GROUP BY 1''')
    assert con.execute("SELECT count(*) FROM cat_sector WHERE k > 1").fetchone()[0] == 0, \
        f"{CATALOG_TABLE} has more than one sector for a new_catalog_title"
    con.execute("INSERT INTO cat_sector SELECT cat, sr, 1 FROM (SELECT cat, sr, row_number() OVER "
                "(PARTITION BY cat ORDER BY count(*) DESC, sr) rn FROM ("
                + both('SELECT trim(new_catalog_title) cat, "Subject[sector_resource]" sr FROM "{t}"')
                + ") GROUP BY cat, sr) WHERE rn = 1 AND cat NOT IN (SELECT cat FROM cat_sector)")
    for t in DATASET_TABLES:
        n, fallback = con.execute(f'''
            SELECT count(*) FILTER (WHERE d."Subject[sector]" IS DISTINCT FROM c.sector),
                   count(*) FILTER (WHERE trim(d.new_catalog_title) NOT IN
                                    (SELECT trim(new_catalog_title) FROM {CATALOG_TABLE}))
            FROM "{t}" d JOIN cat_sector c ON trim(d.new_catalog_title) = c.cat''').fetchone()
        con.execute(f'''UPDATE "{t}" SET "Subject[sector]" = c.sector FROM cat_sector c
                        WHERE trim("{t}".new_catalog_title) = c.cat''')
        print(f"  {t}: Subject[sector] changed on {n} rows "
              f"({fallback} rows sit in a catalog that has no row in {CATALOG_TABLE})")


def verify(con: duckdb.DuckDBPyConnection, counts: dict[str, int]) -> None:
    for t, col in [(t, c) for t in DATASET_TABLES for c in ("Subject[sector]", "Subject[sector_resource]")] \
            + [(CATALOG_TABLE, "Subject[sector]"), (CATALOG_SOURCE, "generated_sector")]:
        values = [r[0] for r in con.execute(f'SELECT DISTINCT "{col}" FROM "{t}"').fetchall()]
        bad = [v for v in values if not is_valid(v)]
        assert not bad, f"{t}.{col}: {len(bad)} values outside the vocabulary, e.g. {bad[:3]}"
    for t, n in counts.items():
        assert con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] == n, f"{t}: row count changed"
    mixed = con.execute("SELECT count(*) FROM (SELECT cat FROM ("
                        + both('SELECT trim(new_catalog_title) cat, "Subject[sector]" s FROM "{t}"')
                        + ") GROUP BY cat HAVING count(DISTINCT s) > 1)").fetchone()[0]
    assert mixed == 0, f"{mixed} catalogs still carry more than one Subject[sector]"
    print("  checked: every value is in the vocabulary, one Subject[sector] per new_catalog_title, "
          "row counts unchanged")


def main(dry_run: bool) -> None:
    units = dict(pd.read_csv(UNITS_CSV, dtype=str).fillna("")[["unit", "new_value"]].values)
    overrides = pd.read_csv(OVERRIDES_CSV, dtype=str).fillna("")
    changes = pd.read_csv(CATALOG_CSV, dtype=str).fillna("")
    bad = [v for v in [*units.values(), *overrides["new_value"], *changes["new_sector"]] if not is_valid(v)]
    assert not bad, f"values outside the vocabulary in the CSVs: {bad[:5]}"

    con = duckdb.connect(DB_PATH)
    tables = [*DATASET_TABLES, CATALOG_TABLE, CATALOG_SOURCE]
    counts = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
    markers = ", ".join(f"'{m}'" for m in RAW_MARKERS)
    raw_left = con.execute("SELECT count(*) FROM (" + both(
        f'SELECT 1 FROM "{{t}}" WHERE "Subject[sector_resource]" IN ({markers})') + ")").fetchone()[0]
    con.execute("BEGIN")
    try:
        if raw_left:
            print("Step 1 - dataset sector into Subject[sector_resource]")
            move_dataset_theme(con, units, overrides)
        else:
            print("Step 1 - skipped, Subject[sector_resource] already holds the dataset sector")
        print("Step 2 - catalog sector corrections")
        fix_catalog_sectors(con, changes)
        print("Step 3 - catalog sector into Subject[sector]")
        spread_catalog_sector(con)
        verify(con, counts)
        con.execute("ROLLBACK" if dry_run else "COMMIT")
        print("[dry-run] rolled back." if dry_run else "Committed.")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    if not dry_run:
        append_to_results_csv(changes)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    main(p.parse_args().dry_run)
