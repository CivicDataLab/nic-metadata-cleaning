"""
Build ``gazetteer/public_office_holders.txt`` -- the allow-list of people who
appear in government data in a public capacity.

Why an allow-list, and why it is the riskiest file here
-------------------------------------------------------
Every other gazetteer under ``gazetteer/`` makes the pipeline *quieter about
things that are not people*. This one makes it quieter about things that
**are** people, on the grounds that their names are already published: DPDP
Act 2023 s.3(c)(ii) puts personal data made public under a legal obligation
outside the Act, and a parliamentary member directory is published under
exactly such an obligation.

That inverts the usual failure mode. A bad entry in ``place_names.txt`` costs
a missed detection in one column; a bad entry here can mark a real private
individual as publishable. "Ram Singh" is both an MP and several hundred
thousand other people. So:

* **No mononyms.** A single token is never enough to identify an office
  holder, and single-token entries are what would match everybody.
* **Collisions are dropped, not resolved.** A name that is also a place name,
  an occupation, a crime head or a species is removed outright.
* **Corpus-common names are dropped.** Anything appearing in more than
  ``CROSS_DATASET_MAX`` datasets is a category or a very common name; either
  way it cannot distinguish an MP from a beneficiary.
* **A single match never decides anything.** The list is consumed at column
  level in ``pii_classify.py``: a share of the column's distinct values has to
  match before the column is called permissible. One hit is noise.

Sources
-------
``--wikidata``  Humans who are citizens of India with occupation politician,
                plus humans holding a position whose country is India. English
                and Hindi labels. ~30k people, and the only source that covers
                state legislatures and municipal office.
``--local``     Member-directory files on disk. The graded corpus ships the
                Lok Sabha former-member directories, which is where the
                permissible class was defined in the first place.
``--corpus``    Datasets whose *column schema* says office-bearer directory
                (``pii_classify.schema_context``), harvested from S3. This is
                the only source that captures the corpus's own spellings, the
                same reason build_gazetteer.py harvests rather than types.

Usage
-----
    python pii_test/build_public_office_gazetteer.py --local
    python pii_test/build_public_office_gazetteer.py --wikidata
    python pii_test/build_public_office_gazetteer.py --all
    python pii_test/build_public_office_gazetteer.py --all --stats
"""

import argparse
import io
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pii_filters import (  # noqa: E402
    CROSS_DATASET_MAX,
    GAZETTEERS,
    cross_dataset_frequency,
    normalize_entity_text,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

GAZETTEER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "gazetteer")
OUTPUT_PATH = os.path.join(GAZETTEER_DIR, "public_office_holders.txt")
SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "pii-test-sample", "pii-permissible")

DB_PATH = "transformation/metadata.db"
S3_BUCKET = "nic-ogdp-datasets"
S3_LOT1_PREFIX = "downloaded-datasets/downloaded-datasets-mohfw"
S3_LOT2_PREFIX = "downloaded-datasets"

# Column headers that hold the office holder's own name in a directory. The
# relatives' columns (Father/Mother/Spouse Name) are deliberately excluded:
# those people hold no office, and their names are permissible only by sitting
# inside the member's published record -- which the dataset-context rule
# already handles. Harvesting them would put ordinary private names on an
# allow-list that travels to every other dataset.
NAME_COLUMN_HINTS = (
    "member name", "name of member", "mp name", "mla name", "name",
    "name of vice-chancellor", "officer name", "name of officer",
    "nodal officer", "cpio", "chairman", "chairperson", "director name",
)

MIN_TOKENS = 2
MIN_LENGTH = 6
MAX_LENGTH = 60

# Honorifics carried by the source directories ("Shri Vizol", "Smt Annapurna
# Devi", "श्री आभा"). They must not count towards MIN_TOKENS: "shri vizol" is
# two tokens but one name, and putting it on an allow-list would make every
# person called Vizol publishable. Both forms are emitted -- the directory
# spells names with the honorific, other datasets usually do not -- but a name
# only qualifies if it has two real tokens once these are removed.
HONORIFICS = {
    "shri", "sri", "shree", "smt", "smt.", "shrimati", "srimati", "km",
    "kum", "kumari", "dr", "doctor", "prof", "professor", "mr", "mrs",
    "ms", "miss", "thiru", "tmt", "sardar", "capt", "col", "gen", "maj",
    "justice", "adv", "advocate", "er", "engg", "late", "hon", "honble",
    "श्री", "श्रीमती", "सुश्री", "डा", "डॉ", "कुमारी", "प्रो", "डाक्टर",
}


def strip_honorifics(normalized):
    """Drop leading honorific tokens from a normalised name."""
    tokens = normalized.split()
    while tokens and tokens[0] in HONORIFICS:
        tokens = tokens[1:]
    return " ".join(tokens)

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_USER_AGENT = "nic-ogdp-pii-gazetteer/1.0 (data.gov.in metadata cleaning)"
WIKIDATA_PAGE = 20000
# The public endpoint rate-limits to one request per minute during an outage.
WIKIDATA_PACE_SECONDS = 65
WIKIDATA_BACKOFF_SECONDS = 90

# Humans who are Indian citizens with occupation politician. Broadest single
# source: covers MPs, MLAs and municipal office holders alike.
WIKIDATA_POLITICIANS = """
SELECT DISTINCT ?name WHERE {
  ?p wdt:P31 wd:Q5 ; wdt:P27 wd:Q668 ; wdt:P106 wd:Q82955 ;
     rdfs:label ?name .
  FILTER(LANG(?name) IN ("en", "hi"))
}
"""

# Humans holding any position whose country is India. Catches office holders
# who are not tagged as politicians -- vice-chancellors, judges, governors.
WIKIDATA_OFFICE_HOLDERS = """
SELECT DISTINCT ?name WHERE {
  ?p wdt:P31 wd:Q5 ; p:P39/ps:P39 ?pos ; rdfs:label ?name .
  ?pos wdt:P17 wd:Q668 .
  FILTER(LANG(?name) IN ("en", "hi"))
}
"""


# --------------------------------------------------------------------------
# Safety filtering
# --------------------------------------------------------------------------

def _collision_lists():
    """Every rejection gazetteer, as one set of normalised values."""
    collisions = set()
    for label, names in GAZETTEERS.items():
        collisions |= set(names)
        logger.debug("collision source %s: %d values", label, len(names))
    return collisions


def acceptable(normalized, collisions):
    """Whether a normalised name may go on the allow-list, and why not.

    Returns ``(bool, reason)``. Every rejection reason is counted and reported
    so the filtering stays auditable -- an allow-list that silently drops most
    of its input is as much a bug as one that keeps too much.
    """
    if not normalized:
        return False, "empty"
    if any(ch.isdigit() for ch in normalized):
        return False, "contains a digit"
    if not (MIN_LENGTH <= len(normalized) <= MAX_LENGTH):
        return False, "length out of range"
    if len(strip_honorifics(normalized).split()) < MIN_TOKENS:
        return False, "mononym once honorifics are removed"
    if normalized in collisions:
        return False, "collides with a rejection gazetteer"
    if cross_dataset_frequency(normalized) > CROSS_DATASET_MAX:
        return False, "appears in too many datasets to identify anyone"
    return True, None


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

def fetch_wikidata(query, label, page=WIKIDATA_PAGE, max_pages=20,
                   pace=WIKIDATA_PACE_SECONDS):
    """Run a paged SPARQL query, returning raw label strings.

    The public endpoint rate-limits hard -- during a WDQS outage it drops to
    one request per minute -- so requests are paced rather than retried
    quickly, and a page is large enough that few are needed. A failure returns
    what has been collected so far instead of raising: a partial allow-list is
    usable, and the header records which sources actually contributed.
    """
    names = []
    for page_index in range(max_pages):
        if page_index or names:
            time.sleep(pace)
        paged = f"{query.strip()} LIMIT {page} OFFSET {page_index * page}"
        url = (WIKIDATA_ENDPOINT + "?" +
               urllib.parse.urlencode({"query": paged, "format": "json"}))
        request = urllib.request.Request(
            url, headers={"User-Agent": WIKIDATA_USER_AGENT,
                          "Accept": "application/sparql-results+json"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    payload = json.load(response)
                break
            except Exception as exc:                      # noqa: BLE001
                if attempt == 2:
                    logger.error("%s page %d failed after 3 tries: %s",
                                 label, page_index, exc)
                    return names
                wait = WIKIDATA_BACKOFF_SECONDS * (attempt + 1)
                logger.warning("%s page %d attempt %d failed (%s); waiting %ds",
                               label, page_index, attempt + 1, exc, wait)
                time.sleep(wait)

        rows = payload["results"]["bindings"]
        names.extend(row["name"]["value"] for row in rows)
        logger.info("%s: page %d returned %d labels (%d total)",
                    label, page_index, len(rows), len(names))
        if len(rows) < page:
            break
    return names


def from_wikidata():
    names = []
    names += fetch_wikidata(WIKIDATA_POLITICIANS, "politicians")
    names += fetch_wikidata(WIKIDATA_OFFICE_HOLDERS, "office holders")
    return names


def _name_columns(columns):
    """Columns of a directory that hold the office holder's own name."""
    wanted = []
    for column in columns:
        lowered = str(column).strip().lower()
        if any(lowered == hint or lowered.startswith(hint)
               for hint in NAME_COLUMN_HINTS):
            wanted.append(column)
    return wanted


def _read_table(path_or_bytes, name_hint=""):
    import pandas as pd
    source = path_or_bytes
    if str(name_hint).lower().endswith((".xls", ".xlsx")):
        try:
            return pd.read_excel(source)
        except Exception as exc:                          # noqa: BLE001
            logger.warning("cannot read %s (%s); install xlrd/openpyxl to "
                           "include it", name_hint, exc)
            return None
    try:
        return pd.read_csv(source, low_memory=False)
    except UnicodeDecodeError:
        if hasattr(source, "seek"):
            source.seek(0)
        return pd.read_csv(source, low_memory=False, encoding="cp1252",
                           encoding_errors="replace")
    except Exception as exc:                              # noqa: BLE001
        logger.warning("cannot read %s: %s", name_hint, exc)
        return None


def from_local(directory=SAMPLE_DIR):
    """Harvest office-holder names from member directories on disk."""
    names = []
    if not os.path.isdir(directory):
        logger.warning("%s does not exist; skipping local source", directory)
        return names
    for filename in sorted(os.listdir(directory)):
        if filename == "pii_detections.csv":
            continue
        path = os.path.join(directory, filename)
        frame = _read_table(path, filename)
        if frame is None:
            continue
        columns = _name_columns(frame.columns)
        if not columns:
            logger.info("%s: no office-holder name column, skipped", filename)
            continue
        for column in columns:
            values = frame[column].dropna().astype(str).str.strip()
            harvested = [v for v in values.unique() if v]
            names.extend(harvested)
            logger.info("%s [%s]: %d distinct values", filename, column,
                        len(harvested))
    return names


def from_corpus(max_datasets=200):
    """Harvest from datasets whose column schema says office-bearer directory.

    The directory datasets are identified the same way ``pii_classify`` does
    it -- by their column schema, not their catalogue title, because in this
    corpus the two can disagree outright.
    """
    import boto3
    import duckdb
    from pii_classify import schema_context

    names = []
    try:
        connection = duckdb.connect(DB_PATH, read_only=True)
    except Exception as exc:                              # noqa: BLE001
        logger.error("cannot open %s: %s", DB_PATH, exc)
        return names

    headers = {}
    for lot, table, key in ((1, "pii_detections_lot1", "batch"),
                            (2, "pii_detections_lot2", "ministry")):
        try:
            rows = connection.execute(
                f'SELECT uuid, {key}, "column" FROM {table}').fetchall()
        except Exception as exc:                          # noqa: BLE001
            logger.warning("cannot read %s: %s", table, exc)
            continue
        for uuid, location, column in rows:
            headers.setdefault((uuid, lot, location), set()).add(column)
    connection.close()

    directories = [(uuid, lot, location, columns)
                   for (uuid, lot, location), columns in headers.items()
                   if schema_context(columns)[0] == "official_directory"]
    logger.info("%d datasets have an office-bearer column schema",
                len(directories))

    s3 = boto3.client("s3")
    for uuid, lot, location, columns in directories[:max_datasets]:
        key = (f"{S3_LOT1_PREFIX}/batch_{location}/{uuid}.csv" if lot == 1
               else f"{S3_LOT2_PREFIX}/{location}/{uuid}.csv")
        try:
            body = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
        except Exception as exc:                          # noqa: BLE001
            logger.warning("cannot fetch %s: %s", key, exc)
            continue
        frame = _read_table(io.BytesIO(body), key)
        if frame is None:
            continue
        for column in _name_columns(frame.columns):
            values = frame[column].dropna().astype(str).str.strip()
            harvested = [v for v in values.unique() if v]
            names.extend(harvested)
            logger.info("%s [%s]: %d distinct values", uuid, column,
                        len(harvested))
    return names


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def build(sources, out_path=OUTPUT_PATH):
    collisions = _collision_lists()
    kept = {}
    rejected = {}
    raw_counts = {}

    for label, names in sources.items():
        raw_counts[label] = len(names)
        for name in names:
            normalized = normalize_entity_text(name)
            ok, reason = acceptable(normalized, collisions)
            if not ok:
                rejected[reason] = rejected.get(reason, 0) + 1
                continue
            kept.setdefault(normalized, label)
            # The honorific-free form too, so a detection elsewhere that
            # writes the name plainly still matches. Re-checked rather than
            # assumed: stripping can push a name below the length floor or
            # onto a rejection gazetteer.
            stripped = strip_honorifics(normalized)
            if stripped != normalized:
                ok, _ = acceptable(stripped, collisions)
                if ok:
                    kept.setdefault(stripped, label)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("# Generated by pii_test/build_public_office_gazetteer.py"
                     " -- do not edit by hand.\n")
        handle.write(f"# Snapshot: {date.today().isoformat()}\n")
        handle.write("# An ALLOW-list: a match is evidence that a name is "
                     "published in a public capacity.\n")
        handle.write("# Consumed at column level by pii_classify.py -- a share "
                     "of a column's distinct\n")
        handle.write("# values must match before the column is called "
                     "permissible. One hit decides nothing.\n")
        handle.write("# Sources: " + ", ".join(
            f"{label} ({count} raw)" for label, count in sorted(raw_counts.items()))
            + "\n")
        handle.write(f"# Kept {len(kept)} names. Dropped: " + ", ".join(
            f"{reason} ({count})" for reason, count in sorted(rejected.items()))
            + "\n")
        handle.write(f"# Filters: >= {MIN_TOKENS} tokens, {MIN_LENGTH}-"
                     f"{MAX_LENGTH} chars, no digits, no collision with a "
                     f"rejection gazetteer,\n")
        handle.write(f"# and cross-dataset frequency <= {CROSS_DATASET_MAX}.\n")
        for name in sorted(kept):
            handle.write(name + "\n")

    return kept, rejected, raw_counts


def report_stats(kept):
    """How the new list would land on the columns already classified."""
    try:
        import duckdb
        from pii_classify import PUBLIC_OFFICE_MATCH_RATE
    except Exception as exc:                              # noqa: BLE001
        logger.warning("cannot compute stats: %s", exc)
        return
    path = "transformation/pii_classification.db"
    if not os.path.exists(path):
        logger.info("no %s yet; skipping stats", path)
        return
    connection = duckdb.connect(path, read_only=True)
    rows = connection.execute(
        'SELECT "column", pii_class, evidence_json FROM pii_column_class'
    ).fetchall()
    connection.close()

    hits = {}
    for column, pii_class, evidence in rows:
        values = json.loads(evidence).get("sample_values") or []
        if not values:
            continue
        matched = sum(1 for v in values
                      if normalize_entity_text(v) in kept)
        if matched / len(values) >= PUBLIC_OFFICE_MATCH_RATE:
            hits.setdefault((column, pii_class), 0)
            hits[(column, pii_class)] += 1

    logger.info("columns whose sampled values match the allow-list at >= %.0f%%:",
                PUBLIC_OFFICE_MATCH_RATE * 100)
    for (column, pii_class), count in sorted(hits.items(),
                                             key=lambda kv: -kv[1])[:25]:
        logger.info("  %4d  %-15s %s", count, pii_class, column)
    if not hits:
        logger.info("  none")


def main():
    parser = argparse.ArgumentParser(description="Build the public "
                                                 "office-holder allow-list.")
    parser.add_argument("--wikidata", action="store_true",
                        help="Indian politicians and office holders from Wikidata")
    parser.add_argument("--local", action="store_true",
                        help=f"member directories under {SAMPLE_DIR}")
    parser.add_argument("--corpus", action="store_true",
                        help="datasets whose column schema says directory (S3)")
    parser.add_argument("--all", action="store_true", help="every source")
    parser.add_argument("--max-datasets", type=int, default=200,
                        help="cap on datasets harvested by --corpus")
    parser.add_argument("--out", default=OUTPUT_PATH)
    parser.add_argument("--stats", action="store_true",
                        help="report how the list lands on pii_column_class")
    args = parser.parse_args()

    if not (args.wikidata or args.local or args.corpus or args.all):
        parser.error("choose at least one source, or --all")

    sources = {}
    if args.local or args.all:
        sources["local"] = from_local()
    if args.wikidata or args.all:
        sources["wikidata"] = from_wikidata()
    if args.corpus or args.all:
        sources["corpus"] = from_corpus(args.max_datasets)

    kept, rejected, raw = build(sources, args.out)
    logger.info("raw values by source: %s", raw)
    logger.info("dropped: %s", rejected)
    logger.info("wrote %d names to %s", len(kept), args.out)

    if args.stats:
        report_stats(set(kept))
    return 0


if __name__ == "__main__":
    sys.exit(main())
