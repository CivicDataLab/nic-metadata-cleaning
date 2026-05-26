"""
Group similar catalog titles into collections and write a CSV with links.

Reads the distinct "Relation[Catalog Title]" values from dublin_core_metadata
and clusters titles that describe the *same kind* of catalog into one
collection. Grouping is deterministic: a title is reduced to a stem by
removing the parts that vary across members of the same catalog family —

  * trailing state / UT names        ("... of Bihar", "... at District level of Goa")
  * trailing year / edition          ("- 2015", "- 2019-20", "(DLHS-3)", "(NFHS-5)")
  * frequency words                  ("Annual", "Quarterly", "Monthly")
  * the indicator / sub-report clause after the first " for " or ":"
  * geographic / temporal tails       ("in India", "Across States/UTs", "at facility")
  * "Cumulative" qualifier            (HMIS comparison series)

Titles sharing a stem land in the same collection. Catalogs with no sibling
form a one-member collection named after the catalog itself.

Output CSV columns: collection, catalog_title, catalog_url, collection_size.
Catalog URLs follow the same naive slug convention as collection_catalog_links.py.

Usage:
    python catalog_collections.py
    python catalog_collections.py --db /path/to/metadata.db
    python catalog_collections.py --out /tmp/catalog_collections.csv
"""

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

import duckdb

# Reuse the closed-list state regex from dataset_merge (sibling of utils/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dataset_merge import STATE_ALT  # noqa: E402

DB_PATH = Path(__file__).resolve().parent.parent / "metadata.db"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "catalog_collections.csv"
BASE_URL = "https://data.gov.in/catalog/"

# ── normalization patterns ───────────────────────────────────────────────────
_EDITION = re.compile(r"\s*\((?:DLHS|NFHS|GYTS|NSS)[^)]*\)", re.I)
_PROVISIONAL = re.compile(r"\s*\(provisional\)", re.I)
# frequency words, but never strip the proper name "Annual Health Survey"
_FREQ = re.compile(r"\b(annual|quarterly|monthly)\b(?!\s+health\s+survey)", re.I)
_CUMULATIVE = re.compile(r"\bcumulative\b", re.I)
_GEO_TAIL = re.compile(
    r"\s+(in india(\s*\(across states/uts\))?|across (states(/uts)?|the months)|at facility)\s*$",
    re.I,
)
_STATE_SUFFIX = re.compile(
    rf"\s+(?:of|across sub districts of|at district level of|at sub district level of|in)\s+(?:{STATE_ALT})\s*$",
    re.I,
)
_YEAR = re.compile(r"[\s\-,]+\d{4}(\s*[-–]\s*\d{2,4})?\s*$")
_TRAIL_PUNCT = re.compile(r"[\s\-:,]+$")


def stem(title: str) -> str:
    """Reduce a catalog title to its collection stem (case preserved)."""
    s = title.strip().replace("–", "-").replace("—", "-").replace("&", "and")
    s = re.sub(r"\s+", " ", s)
    s = _EDITION.sub("", s)
    s = _PROVISIONAL.sub("", s)

    # cut the indicator / sub-report clause at the first " for " or ":"
    cut = len(s)
    for_m = re.search(r"\bfor\b", s, re.I)
    if for_m:
        cut = min(cut, for_m.start())
    colon = s.find(":")
    if colon != -1:
        cut = min(cut, colon)
    s = s[:cut]

    s = _FREQ.sub("", s)
    s = _CUMULATIVE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()

    # peel trailing geo / state / year qualifiers (may stack)
    for _ in range(3):
        before = s
        s = _GEO_TAIL.sub("", s)
        s = _STATE_SUFFIX.sub("", s)
        s = _YEAR.sub("", s)
        s = _TRAIL_PUNCT.sub("", s).strip()
        if s == before:
            break
    return s


def catalog_title_to_url(title: str) -> str:
    """Naive catalog slug, matching collection_catalog_links.py."""
    slug = re.sub(r"\s+", "-", title.strip().lower())
    return BASE_URL + slug


def build_collections(titles: list[str]) -> list[tuple[str, str, str, int]]:
    """Return (collection, catalog_title, catalog_url, collection_size) rows."""
    # key -> {members: [...], stems: Counter of case-preserved display stems}
    groups: dict[str, dict] = {}
    for t in titles:
        disp = stem(t)
        key = disp.lower()
        g = groups.setdefault(key, {"members": [], "stems": Counter()})
        g["members"].append(t)
        g["stems"][disp] += 1

    rows: list[tuple[str, str, str, int]] = []
    for g in groups.values():
        size = len(g["members"])
        if size == 1:
            # lone catalog: name the collection after the catalog itself
            collection = g["members"][0]
        else:
            # deterministic display: most common stem, then shortest, then alpha
            collection = sorted(
                g["stems"].items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0])
            )[0][0]
        for title in sorted(g["members"]):
            rows.append((collection, title, catalog_title_to_url(title), size))

    rows.sort(key=lambda r: (-r[3], r[0].lower(), r[1].lower()))
    return rows


def fetch_titles(conn: duckdb.DuckDBPyConnection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT "Relation[Catalog Title]"
            FROM dublin_core_metadata
            WHERE "Relation[Catalog Title]" IS NOT NULL
              AND TRIM("Relation[Catalog Title]") <> ''
            """
        ).fetchall()
    ]


def write_csv(rows: list[tuple[str, str, str, int]], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["collection", "catalog_title", "catalog_url", "collection_size"])
        w.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Group catalog titles into collections.")
    parser.add_argument("--db", default=str(DB_PATH), help="DuckDB database path")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output CSV path")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(args.db, read_only=True)
    try:
        titles = fetch_titles(conn)
    finally:
        conn.close()

    rows = build_collections(titles)

    n_collections = len({r[0] for r in rows})
    multi = sorted(
        {r[0]: r[3] for r in rows if r[3] > 1}.items(), key=lambda kv: -kv[1]
    )
    write_csv(rows, out_path)

    print(f"CSV written: {out_path}")
    print(f"  {len(titles)} catalogs -> {n_collections} collections "
          f"({len(multi)} multi-catalog, {n_collections - len(multi)} singletons)")
    print("\nLargest collections:")
    for name, size in multi[:12]:
        print(f"  [{size:>2}] {name}")


if __name__ == "__main__":
    main()
