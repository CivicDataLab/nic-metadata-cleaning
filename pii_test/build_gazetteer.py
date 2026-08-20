"""
Build the rejection gazetteers used by pii_filters. One file per vocabulary,
so a rejection names the list it came from and any list can be dropped
wholesale if it turns out to over-reject.

Two sources:

**Place names** (``place_names.txt``) come from the catalogue, which already
knows every place the corpus covers: remain_raw_metadata carries
semicolon-separated spatial_states / spatial_districts / spatial_subdistricts
per dataset. Indian administrative place names were the single largest source
of PERSON false positives in the LOT 2 scan (RAJGARH, THOUBAL, JAISALMER).

**Value families** (``crime_heads.txt``, ``languages.txt``,
``commodities.txt``, ``occupations.txt``, ``species.txt``) are harvested from
the corpus itself rather than hand-typed: for each family, find the datasets
whose detections came from a column whose header matches the family, download
those CSVs, and take the distinct values of the matching columns. NCRB crime
heads and census mother tongues are closed lists of a few dozen values and
converge after a handful of files; commodities are a longer tail, which is why
--max-datasets is per family.

Between them these covered ~47% of the residual LOT 2 detections. Harvesting
beats typing because it captures the corpus's own spellings ("MAKKI",
"ATTA CHAKKI", "C.H. Not Amounting to Murder").

Usage:
    python pii_test/build_gazetteer.py                  # place names only
    python pii_test/build_gazetteer.py --stats          # + coverage vs current detections
    python pii_test/build_gazetteer.py --family crime_heads
    python pii_test/build_gazetteer.py --all-families   # every family, downloads from S3
"""

import argparse
import collections
import logging
import os
import re
from datetime import date

import boto3
import duckdb
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

DB_PATH = "transformation/metadata.db"
SOURCE_TABLE = "remain_raw_metadata"
DETECTIONS_TABLE = "pii_detections_lot2"
DETECTIONS_BASELINE = "pii_detections_lot2_baseline"
SPATIAL_COLUMNS = ("spatial_states", "spatial_districts", "spatial_subdistricts")
GAZETTEER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gazetteer")
OUTPUT_PATH = os.path.join(GAZETTEER_DIR, "place_names.txt")

S3_BUCKET = "nic-ogdp-datasets"
S3_ROOT_PREFIX = "downloaded-datasets/"

# Place names shorter than this are dropped: two- and three-letter fragments
# collide with real name particles and initials.
MIN_PLACE_LENGTH = 4

# --- Value families ---
#
# ``patterns``    SQL LIKE patterns matched against lower(detections.column).
#                 Deliberately narrow: "Particulars" also carries crime heads
#                 but carries free text too, and harvesting free text into a
#                 rejection list is how a real name ends up in one.
# ``max_datasets`` How many CSVs to download. Closed lists converge in a few
#                 files; commodities and occupations have a longer tail.
# ``min_datasets`` How many of those datasets a value must appear in to be
#                 kept. This is the guard against poisoning the list with a
#                 real name: the commodity columns of the village directories
#                 are free text, and someone typing "Ashok Kumar" into one of
#                 them would otherwise put that name beyond detection forever.
#                 A genuine commodity recurs across districts; a stray name
#                 does not. Raise it for the free-text families.
FAMILIES = {
    "crime_heads": {
        "patterns": ("%crime head%", "%heads of crime%", "%crime heads%"),
        "max_datasets": 40,
        "min_datasets": 2,
    },
    "languages": {
        "patterns": ("%mother tongue%", "%language name%"),
        "max_datasets": 20,
        "min_datasets": 2,
    },
    "commodities": {
        "patterns": ("%commodit%", "%handicraft%"),
        "max_datasets": 60,
        "min_datasets": 3,
    },
    "occupations": {
        "patterns": ("%nco name%", "%occupation%"),
        "max_datasets": 40,
        "min_datasets": 2,
    },
    "species": {
        "patterns": ("species", "%species name%"),
        "max_datasets": 20,
        "min_datasets": 2,
    },
}

# Harvested values outside this length band are dropped. The floor matches
# MIN_PLACE_LENGTH; the ceiling drops free-text cells that slipped into an
# otherwise categorical column.
MIN_VALUE_LENGTH = 4
MAX_VALUE_LENGTH = 60


def place_name_query():
    """SQL producing one normalised place name per row from the spatial columns."""
    unions = "\n  UNION ALL\n".join(
        f"  SELECT unnest(str_split({col}, ';')) AS part FROM {SOURCE_TABLE} "
        f"WHERE {col} IS NOT NULL"
        for col in SPATIAL_COLUMNS
    )
    return f"""
WITH parts AS (
{unions}
),
cleaned AS (
    SELECT lower(trim(part)) AS name FROM parts
)
SELECT DISTINCT name
FROM cleaned
WHERE name <> '' AND length(name) >= {MIN_PLACE_LENGTH}
ORDER BY name
"""


def family_columns(conn, patterns, limit):
    """Datasets and column headers matching a family, most-productive first.

    Sourced from the detection tables because those are exactly the columns
    that produced false positives; the baseline is included because it covers
    six times as many datasets.
    """
    tables = {t[0] for t in conn.execute("SHOW TABLES").fetchall()}
    sources = [t for t in (DETECTIONS_TABLE, DETECTIONS_BASELINE) if t in tables]
    if not sources:
        raise SystemExit("No detection tables to harvest column names from")

    where = " OR ".join('lower("column") LIKE ?' for _ in patterns)
    union = "\n  UNION ALL\n".join(
        f'  SELECT uuid, ministry, "column", 1 AS n FROM {t}\n'
        f"  WHERE entity_type = 'PERSON' AND ({where})"
        for t in sources
    )
    rows = conn.execute(f"""
        WITH hits AS (
{union}
        )
        SELECT uuid, ministry, list(DISTINCT "column") AS columns, COUNT(*) AS n
        FROM hits
        WHERE ministry IS NOT NULL
        GROUP BY uuid, ministry
        ORDER BY n DESC
        LIMIT {int(limit)}
    """, list(patterns) * len(sources)).fetchall()
    return [(uuid, ministry, columns) for uuid, ministry, columns, _n in rows]


def harvest_values(s3, uuid, ministry, columns):
    """Distinct values of the named columns of one dataset."""
    key = f"{S3_ROOT_PREFIX}{ministry}/{uuid}.csv"
    body = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    import io
    try:
        df = pd.read_csv(io.BytesIO(body), low_memory=False)
    except UnicodeDecodeError:
        df = pd.read_csv(io.BytesIO(body), low_memory=False,
                         encoding="cp1252", encoding_errors="replace")

    wanted = {str(c).strip().lower() for c in columns}
    values = set()
    for col in df.columns:
        if str(col).strip().lower() not in wanted:
            continue
        series = df[col].dropna().astype(str).str.strip()
        values.update(series[series != ""].unique())
    return values


# Categorical columns in this corpus number their rows inside the value
# itself -- "1. Cattle", "10.Yaks", "1 . Murder (Sec 302 IPC)", and the same
# list re-numbered per state. The NER span never includes the number, so an
# un-stripped entry can never match a detection.
_ENUMERATOR_RE = re.compile(r"^[\s\-.)]*\d+[\s.):,\-]+")
# The closing bracket is optional: these CSVs are full of values truncated
# mid-parenthesis ("Ascidiacea (Sea Squirts", "1 - Murder (Section 302 IPC").
_TRAILING_PAREN_RE = re.compile(r"\s*\([^()]*\)?\s*$")
_TRAILING_YEAR_RE = re.compile(r"[,\s]+(?:19|20)\d{2}\s*$")
_EDGE_PUNCT_RE = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)


def clean_values(values):
    """Normalise harvested values, and emit the sub-forms NER actually spans.

    A detection is the name of the thing, not the catalogue entry it sits in:
    the table holds "Murder", not "1 . Murder (Sec 302 IPC)". So each value
    contributes its stripped form plus the shorter forms left after removing a
    trailing statute reference or year -- all of them exact strings, since
    pii_filters matches these lists whole rather than as substrings.
    """
    out = set()
    for value in values:
        text = " ".join(str(value).split()).lower()
        # Repeatedly: section numbering nests ("11.1 - Grievous Hurt").
        while True:
            stripped = _ENUMERATOR_RE.sub("", text)
            if stripped == text:
                break
            text = stripped
        variants = {text}
        for pattern in (_TRAILING_PAREN_RE, _TRAILING_YEAR_RE):
            variants |= {pattern.sub("", v) for v in list(variants)}
        for variant in variants:
            variant = _EDGE_PUNCT_RE.sub("", variant).strip()
            if not (MIN_VALUE_LENGTH <= len(variant) <= MAX_VALUE_LENGTH):
                continue
            if not any(ch.isalpha() for ch in variant):
                continue
            out.add(variant)
    return out


def build_family(conn, s3, family, out_dir, max_datasets=None):
    spec = FAMILIES[family]
    limit = max_datasets or spec["max_datasets"]
    targets = family_columns(conn, spec["patterns"], limit)
    if not targets:
        logging.warning(f"{family}: no matching columns in the detection tables")
        return 0

    min_datasets = spec["min_datasets"]
    counts, headers, scanned, failed = collections.Counter(), set(), 0, 0
    for uuid, ministry, columns in targets:
        try:
            raw = harvest_values(s3, uuid, ministry, columns)
        except Exception as exc:
            failed += 1
            logging.debug(f"{family}: {uuid} failed ({exc})")
            continue
        # Counted once per dataset, not once per row, so one district file
        # cannot carry a value over the recurrence floor by itself.
        counts.update(clean_values(raw))
        headers.update(columns)
        scanned += 1
        if scanned % 10 == 0:
            logging.info(f"  {family}: {scanned}/{len(targets)} datasets, "
                         f"{len(counts):,} candidate values")

    kept = sorted(value for value, n in counts.items() if n >= min_datasets)
    dropped = len(counts) - len(kept)
    path = os.path.join(out_dir, f"{family}.txt")
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Generated by pii_test/build_gazetteer.py -- do not edit by hand.\n")
        fh.write(f"# Family: {family}   Snapshot: {date.today().isoformat()}\n")
        fh.write(f"# Harvested from the distinct values of {len(headers)} column "
                 f"header(s) across {scanned} dataset(s)"
                 f"{f' ({failed} unreadable)' if failed else ''}.\n")
        fh.write(f"# Kept values appearing in >= {min_datasets} of those datasets; "
                 f"{dropped:,} one-off value(s) dropped as possible stray names.\n")
        for header in sorted(headers)[:12]:
            fh.write(f"#   column: {header}\n")
        for value in kept:
            fh.write(value + "\n")
    logging.info(f"Wrote {len(kept):,} {family} values to {path} "
                 f"(from {scanned} dataset(s); dropped {dropped:,} below the "
                 f"recurrence floor of {min_datasets})")
    return len(kept)


def build_place_names(conn, out_path):
    names = [r[0] for r in conn.execute(place_name_query()).fetchall()]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("# Generated by pii_test/build_gazetteer.py -- do not edit by hand.\n")
        fh.write(f"# Source: {SOURCE_TABLE}.{{{', '.join(SPATIAL_COLUMNS)}}}\n")
        for name in names:
            fh.write(name + "\n")
    logging.info(f"Wrote {len(names)} place names to {out_path}")
    return names


def main():
    parser = argparse.ArgumentParser(description="Build the rejection gazetteers.")
    parser.add_argument("--out", default=OUTPUT_PATH, help="Output path for the place-name gazetteer")
    parser.add_argument("--stats", action="store_true",
                        help="Report how much of the current detection set the gazetteer covers")
    parser.add_argument("--family", action="append", choices=sorted(FAMILIES),
                        help="Build this value family instead of the place names "
                             "(repeatable). Downloads the source CSVs from S3.")
    parser.add_argument("--all-families", action="store_true",
                        help="Build every value family")
    parser.add_argument("--max-datasets", type=int, default=None,
                        help="Override the per-family download cap")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        raise SystemExit(f"Database not found: {DB_PATH} (run from the repo root)")

    families = sorted(FAMILIES) if args.all_families else (args.family or [])

    conn = duckdb.connect(DB_PATH, read_only=True)
    if families:
        s3 = boto3.client("s3")
        for family in families:
            build_family(conn, s3, family, GAZETTEER_DIR, args.max_datasets)
        conn.close()
        return

    names = build_place_names(conn, args.out)

    if args.stats:
        tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
        if DETECTIONS_TABLE not in tables:
            logging.warning(f"{DETECTIONS_TABLE} not present; skipping coverage stats")
        else:
            conn.execute("CREATE TEMP TABLE gaz (name VARCHAR)")
            conn.executemany("INSERT INTO gaz VALUES (?)", [(n,) for n in names])
            covered, total = conn.execute(f"""
                SELECT
                    SUM(CASE WHEN g.name IS NOT NULL THEN 1 ELSE 0 END),
                    COUNT(*)
                FROM {DETECTIONS_TABLE} d
                LEFT JOIN gaz g ON lower(trim(d.entity_text)) = g.name
                WHERE d.entity_type = 'PERSON'
            """).fetchone()
            logging.info(
                f"Gazetteer matches {covered:,} of {total:,} PERSON detections "
                f"({100 * covered / total:.1f}%)"
            )

    conn.close()


if __name__ == "__main__":
    main()
