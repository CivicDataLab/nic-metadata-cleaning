"""
Detect SPATIAL coverage (States / districts / sub-districts) for every dataset
downloaded into data/final_batch_downloads and write it onto the
`remaining-raw-datasets` table.

Content-based sibling of utils/extract_coverage_from_title.py (which reads the
title only). This script uses BOTH signals:

  * the dataset FILE   - columns whose header names a geography ("State/UT",
                         "District", "Tehsil"/"Block"/"Mandal"...) contribute
                         their distinct values; a wide file with one column per
                         State contributes its headers.
  * the dataset TITLE  - the closed State/UT list from dataset_merge.py plus the
                         "<District> of <State>" shapes from utils/title_components.py.

Two phases, so the expensive pass over 23 GB happens once:

  PHASE 1  --extract   Parallel (ProcessPoolExecutor) scan of every local file.
                       Per file we record the raw geo values found, plus every
                       (sub-district -> district -> State) row triple observed.
                       Appended to a JSONL cache; re-runs skip cached uuids.

  PHASE 2  --resolve   Builds a HIERARCHY GAZETTEER out of the harvested triples
                       (district -> State, sub-district -> district), then
                       resolves each dataset and writes the DB columns.

The gazetteer is what makes the user-visible rule work: when a file only names a
sub-district ("Tehsil: Sardhana"), its parent district and State are looked up
from the thousands of files that DO carry all three columns, so the coverage
string still reads "Sardhana, Meerut, Uttar Pradesh, India". The same lookup
fills the State for a district-only file, and it doubles as the validator that
throws out the junk the title parser produces ("Cotton Yarn" is not a district).

Columns written to "remaining-raw-datasets":

  spatial_coverage      canonical string, always ending in "India" so that
                        hvd_score.parse_state (which reads the token before the
                        trailing "India") keeps working:
                            "India"                                  national / many States
                            "Bihar, India"                           one State
                            "Nalanda, Bihar, India"                  one district
                            "Rajgir, Nalanda, Bihar, India"          one sub-district
                        A multi-State list is deliberately NEVER written here -
                        parse_state would read the last one as "the" State.
  spatial_states        every State/UT detected, "; "-joined (the full list)
  spatial_districts     every district detected, "; "-joined
  spatial_subdistricts  every sub-district detected, "; "-joined
  spatial_level         national | multi_state | state | district | sub_district
  spatial_source        title | content | both  (where the evidence came from)

Usage:
    python Spatial_script.py --extract --limit 500     # try the scan on 500 files
    python Spatial_script.py --dry-run                 # resolve + preview, no write
    python Spatial_script.py --extract                 # full parallel scan (slow)
    python Spatial_script.py --resolve                 # gazetteer + write to DB
    python Spatial_script.py                           # extract, then resolve
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
import warnings

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from io import BytesIO
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))            # dataset_merge.py
sys.path.insert(0, str(HERE.parent / "utils"))  # title_components.py

from dataset_merge import state_ut                        # noqa: E402
from title_components import parse_title_components       # noqa: E402

# =========================================================
# CONFIG
# =========================================================

# Paths are derived from this file's location (transformation/temporal/), so the
# script follows the repo instead of one developer's home directory.
ROOT = HERE.parent.parent

LOCAL_DIR = str(ROOT / "data" / "final_batch_downloads")

DB_PATH = str(ROOT / "transformation" / "metadata.db")

# NOTE: hyphenated table name -> MUST be double-quoted in every SQL string
TABLE_NAME = "remaining-raw-datasets"
UUID_COL = "uuid"

CACHE_PATH = str(ROOT / "data" / "spatial_extract_cache.jsonl")

VALID_EXT = (".csv", ".xls", ".xlsx", ".xlsm", ".xlsb")

MAX_WORKERS = 6            # 8 cores / 7 GB RAM - leave headroom
MAX_ROWS = 5000            # rows sampled per file (matches Temporal_script)
MAX_DISTINCT = 400         # distinct values kept per geo column, per file
MAX_PAIRS = 800            # distinct hierarchy pairs kept per file
CSV_READ_BYTES = 4 * 1024 * 1024     # only the head of a CSV is parsed
EXCEL_MAX_BYTES = 60 * 1024 * 1024   # bigger workbooks are skipped (recorded)
FLUSH_EVERY = 500          # cache flush cadence (files)
NAME_CAP = 200             # names per detail column, so no cell explodes

# A district -> State inference is only trusted when one State dominates the
# observed rows: "Aurangabad" appears in both Maharashtra and Bihar, and a
# 55/45 split must NOT silently pick a side.
DOMINANCE = 0.60
MIN_PAIR_COUNT = 3         # a hierarchy edge needs this much support

# =========================================================
# STATE / UT VOCABULARY
# =========================================================

# dataset_merge.state_ut is a closed list of the 36 States/UTs PLUS four values
# that are not geographies at all - they must not enter the State set or every
# multi-State count would be off by one.
NON_STATES = {"all india", "india", "m/o defence", "m/o railways"}

# Spellings that really occur in this corpus (old names, abbreviations, the
# many ways "&" gets written). Keys are normalised by _norm() below.
STATE_ALIASES = {
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "pondichery": "Puducherry",
    "uttaranchal": "Uttarakhand",
    "chattisgarh": "Chhattisgarh",
    "chhatisgarh": "Chhattisgarh",
    "tamilnadu": "Tamil Nadu",
    "tamil nad": "Tamil Nadu",
    "nct of delhi": "Delhi",
    "delhi nct": "Delhi",
    "nct delhi": "Delhi",
    "new delhi": "Delhi",
    "jammu and kashmir ut": "Jammu and Kashmir",
    "j and k": "Jammu and Kashmir",
    "jk": "Jammu and Kashmir",
    "jammu kashmir": "Jammu and Kashmir",
    "a and n islands": "Andaman and Nicobar Islands",
    "a and n island": "Andaman and Nicobar Islands",
    "andaman and nicobar": "Andaman and Nicobar Islands",
    "andaman nicobar islands": "Andaman and Nicobar Islands",
    "andamans": "Andaman and Nicobar Islands",
    "d and n haveli": "Dadra and Nagar Haveli",
    "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli",
    "dnh and dd": "Dadra and Nagar Haveli",
    "daman and diu": "Daman and Diu",
    "himachal": "Himachal Pradesh",
    "andhra": "Andhra Pradesh",
    "arunachal": "Arunachal Pradesh",
    "up": "Uttar Pradesh",
    "mp": "Madhya Pradesh",
    "ap": "Andhra Pradesh",
    "wb": "West Bengal",
    "tn": "Tamil Nadu",
    "uttar pradesh up": "Uttar Pradesh",
    "madhya pradesh mp": "Madhya Pradesh",
    "lakshdweep": "Lakshadweep",
    "laccadive": "Lakshadweep",
    "telengana": "Telangana",
    "karnatka": "Karnataka",
    "maharastra": "Maharashtra",
    "westbengal": "West Bengal",
    "bengal": "West Bengal",
    "ladakh ut": "Ladakh",
}


def _norm(text):
    """Lower-case, "&"->"and", punctuation -> space, whitespace collapsed.

    Used for every vocabulary lookup so "A & N Islands", "a and n islands" and
    "A.&.N. Islands" all land on the same key.
    """
    s = str(text).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


CANON_STATES = {
    s for s in state_ut if s.strip().lower() not in NON_STATES
}

# normalised form -> canonical spelling
STATE_LOOKUP = {_norm(s): s for s in CANON_STATES}
for _alias, _canon in STATE_ALIASES.items():
    STATE_LOOKUP[_norm(_alias)] = _canon

# Strict variant for scanning HEADERS (and titles), where a two-letter alias is
# usually not a State: this corpus is full of parliamentary-question tables
# whose "MP" column means Member of Parliament, not Madhya Pradesh. Canonical
# names are always kept - "Goa" is short but unambiguous.
STRICT_STATE_LOOKUP = {_norm(s): s for s in CANON_STATES}
for _alias, _canon in STATE_ALIASES.items():
    if len(_norm(_alias)) >= 4:
        STRICT_STATE_LOOKUP[_norm(_alias)] = _canon

# Regex over the closed list, for scanning free text (titles). Longest first so
# "Andhra Pradesh" wins over a bare "Andhra".
_TITLE_STATE_RE = re.compile(
    r"\b(" + "|".join(
        re.escape(s) for s in sorted(
            list(CANON_STATES) + list(STATE_ALIASES.keys()),
            key=len, reverse=True
        )
    ) + r")\b",
    re.I,
)

# Values that are aggregates / placeholders, never a place name.
JUNK_VALUES = {
    "", "-", "--", "na", "n a", "n/a", "nil", "none", "null", "nan", "no",
    "total", "totals", "grand total", "sub total", "subtotal", "all",
    "all india", "india", "others", "other", "unknown", "not known",
    "not reported", "not available", "not applicable", "average", "sum",
    "state", "district", "sub district", "subdistrict", "tehsil", "taluk",
    "taluka", "mandal", "block", "region", "zone", "country", "overall",
    "unspecified", "rural", "urban", "total rural", "total urban", "combined",
    "male", "female", "yes", "no data", "0", "nk", "na na",
    # Header text leaking into the value set: many of these files carry a title
    # or blank row above the real header, so row 1 parses as the header and the
    # actual column names show up as data.
    "sr no", "s no", "sl no", "serial no", "serial number", "srno", "slno",
    "district name", "state name", "block name", "sub district name",
    "districtname", "statename", "blockname", "udisecode", "udise code",
    "name", "value", "header", "column", "particulars", "description",
}

# ...and the code columns that leak in the same way ("UdiseCode", "LGD_Code").
_CODEY_VALUE_RE = re.compile(r"^[a-z_ ]*code$|^[a-z_ ]*_cd$", re.I)


def canon_state(value, strict=False):
    """Canonical State/UT for a raw cell value, else None.

    Composite cells really occur in this corpus ("Haryana and Delhi",
    "Assam and Northeast"). A substring match would collapse those to one
    State, so they are split and each part resolved on its own; parts that are
    not States (that "Northeast") are simply dropped.
    """
    if value is None:
        return None

    lookup = STRICT_STATE_LOOKUP if strict else STATE_LOOKUP
    key = _norm(value)

    if not key or key in JUNK_VALUES:
        return None

    hit = lookup.get(key)
    if hit:
        return hit

    # trailing footnote junk: "Bihar 1", "Kerala p"
    trimmed = re.sub(r"\s+[a-z0-9]{1,2}$", "", key).strip()
    if trimmed and trimmed != key:
        hit = lookup.get(trimmed)
        if hit:
            return hit

    return None


def canon_states_multi(value, strict=False):
    """Every State a (possibly composite) cell resolves to."""
    single = canon_state(value, strict=strict)
    if single:
        return [single]

    lookup = STRICT_STATE_LOOKUP if strict else STATE_LOOKUP
    key = _norm(value)
    if not key or len(key) > 80:
        return []

    parts = [p for p in re.split(r"\band\b|/|,|\+", key) if p.strip()]
    if len(parts) < 2:
        return []

    found = []
    for part in parts:
        hit = lookup.get(part.strip())
        if hit and hit not in found:
            found.append(hit)

    return found

# =========================================================
# GEO COLUMN HEADERS
# =========================================================

# Checked most specific first: "Sub District" contains "District", and
# "District" columns must not be read as State columns.
_SUBDIST_HDR = re.compile(
    r"sub\s*dist|subdist|sub\s*div|tehsil|tahsil|taluk|taluq|mandal|"
    r"\bblock\b|\bcircle\b|\bpanchayat\s*samiti\b|\bteh\b",
    re.I,
)
_DIST_HDR = re.compile(
    r"\bdistrict|\bdistt|\bdist\b|\bzila\b|\bzilla\b|\bjila\b|\bjilla\b",
    re.I,
)
_STATE_HDR = re.compile(
    r"\bstate\b|\bstates\b|\bstate\s*/\s*ut\b|\bstate_ut\b|\but\s*/\s*state\b|"
    r"\brajya\b",
    re.I,
)
# Headers that merely mention a geography as a qualifier, not as the place
# itself - these would flood the value sets with non-places.
_HDR_EXCLUDE = re.compile(
    # "block_cd" is a block CODE column; "CD Block" is a Community Development
    # block and a real place column, so "cd" only disqualifies a header when it
    # is not the CD-block sense.
    r"\bcode\b|\bcd\b(?!\s*block)|\bid\b|\bno\b|\bnos\b|\bnumber\b|\bcount\b|"
    r"\brank\b|\bshare\b|"
    r"\bpercent\w*\b|\bdensity\b|\bpopulation\b|\barea\b|\bamount\b|"
    r"\bexpenditure\b|\bgovern\w*\b|\bscheme\b|\bcapital\b|\bheadquarter\w*\b|"
    r"\bcoal block\b|\bmining block\b|\btime block\b|"
    # qualifier columns that name a *different* place than the row's own:
    # "District Head Quarter (Name)", "Within the State/UT (Name)",
    # "Outside the State/UT ... (Distance in km)", "State Highway (Status ...)"
    r"\bhead quarter\w*\b|\bhq\b|\bdistance\b|\bstatus\b|\bwithin\b|"
    r"\boutside\b|\bnearest\b|\broad\b|\bhighway\b|\bkm\b|\bdist from\b",
    re.I,
)

# Real headers in this corpus are written every which way: "StateName",
# "State_Name", "Udise_Block_Name", "Country/State/UT Name". Word-boundary
# regexes miss the first two entirely (an underscore is a word character, and
# camelCase has no boundary at all), so split those apart before classifying.
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def normalize_header(header):
    h = str(header)
    h = _CAMEL_RE.sub(" ", h)
    h = re.sub(r"[^A-Za-z0-9%]+", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def classify_header(header):
    """'state' | 'district' | 'subdistrict' | None for one column header."""
    h = normalize_header(header)

    if not h or _HDR_EXCLUDE.search(h):
        return None

    if _SUBDIST_HDR.search(h):
        return "subdistrict"

    if _DIST_HDR.search(h):
        return "district"

    if _STATE_HDR.search(h):
        return "state"

    return None


def clean_place(value):
    """Tidy a raw cell into a place name, or None if it is not one."""
    if value is None:
        return None

    s = str(value).strip()

    if not s or len(s) > 60:
        return None

    # strip leading serial numbers ("1. Nalanda", "12 Nalanda") and footnotes
    s = re.sub(r"^\s*\d+\s*[.)\-]\s*", "", s)
    s = re.sub(r"[*#@]+\s*$", "", s)
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;:-")

    if not s or _norm(s) in JUNK_VALUES or _CODEY_VALUE_RE.match(s.strip()):
        return None

    # a place name must be mostly letters
    letters = sum(ch.isalpha() for ch in s)
    if letters < 3 or letters / len(s) < 0.6:
        return None

    return s.title() if s.isupper() or s.islower() else s

# =========================================================
# FILE READING
# =========================================================


def read_sample(path):
    """Read the head of a dataset file into a polars DataFrame (all Utf8)."""
    size = os.path.getsize(path)
    ext = path.lower().rsplit(".", 1)[-1]

    if ext in ("xls", "xlsx", "xlsm", "xlsb"):

        if size > EXCEL_MAX_BYTES:
            raise ValueError(f"excel too large ({size} bytes)")

        with open(path, "rb") as fh:
            blob = fh.read()

        for engine in ("openpyxl", "xlrd", "pyxlsb", None):
            try:
                df = pd.read_excel(
                    BytesIO(blob),
                    engine=engine,
                    dtype=str,
                    nrows=MAX_ROWS,
                )
                return pl.from_pandas(df.astype(str))
            except Exception:
                continue

        # html tables served with an .xls name are common on data.gov.in
        try:
            tables = pd.read_html(BytesIO(blob))
            if tables:
                return pl.from_pandas(tables[0].astype(str))
        except Exception:
            pass

        raise ValueError("unreadable excel")

    # ---- CSV / text: only the head is needed ----
    with open(path, "rb") as fh:
        blob = fh.read(CSV_READ_BYTES)

    if size > CSV_READ_BYTES:
        # a byte cap can cut mid-row; drop the partial tail
        cut = blob.rfind(b"\n")
        if cut > 0:
            blob = blob[:cut]

    # polars only speaks utf8 / utf8-lossy; anything else falls through to the
    # pandas reader below, which handles latin1.
    for enc in ("utf8", "utf8-lossy"):
        try:
            return pl.read_csv(
                BytesIO(blob),
                encoding=enc,
                n_rows=MAX_ROWS,
                infer_schema_length=0,
                ignore_errors=True,
                truncate_ragged_lines=True,
                has_header=True,
            )
        except Exception:
            continue

    try:
        df = pd.read_csv(
            BytesIO(blob),
            dtype=str,
            engine="python",
            encoding="latin1",
            nrows=MAX_ROWS,
            on_bad_lines="skip",
        )
        return pl.from_pandas(df.astype(str))
    except Exception as exc:
        raise ValueError(f"unreadable csv: {exc}")

# =========================================================
# PHASE 1: EXTRACT FROM ONE FILE
# =========================================================


def extract_from_df(df):
    """Pull geo values + hierarchy pairs out of a sampled DataFrame."""
    states, districts, subdistricts = [], [], []
    d2s = Counter()   # (district, State)
    s2d = Counter()   # (sub-district, district)

    matched = {"state": [], "district": [], "subdistrict": []}

    for col in df.columns:
        kind = classify_header(col)
        if kind:
            matched[kind].append(col)

    # A file can match several columns for one kind ("District Name" alongside
    # "Major District Road"); the purest place column is the one whose header is
    # almost nothing but the geo word, so rank by normalised length and read only
    # the winner. Reading them all pollutes the value set with headquarters and
    # neighbouring-district names.
    cols = {
        kind: [min(hits, key=lambda c: (len(normalize_header(c)), str(c)))]
        for kind, hits in matched.items() if hits
    }
    for kind in ("state", "district", "subdistrict"):
        cols.setdefault(kind, [])

    # ---- wide layout: one column PER State, e.g. "... , Bihar, Kerala, ..."
    # strict=True: a bare "MP"/"AP" header is a Member of Parliament or an
    # abbreviation far more often than it is a State.
    for col in df.columns:
        for st in canon_states_multi(col, strict=True):
            states.append(st)

    # ---- long layout: values inside a geo column
    national = False
    for col in cols["state"]:
        for val in df[col].drop_nulls().to_list()[:MAX_ROWS]:
            # "India" / "All India" is filtered out of the State set (it is not
            # a State), but it is real evidence of national scope - keep it as
            # its own flag rather than losing the signal entirely.
            if _norm(val) in ("india", "all india"):
                national = True
            states.extend(canon_states_multi(val))

    for col in cols["district"]:
        for val in df[col].drop_nulls().to_list()[:MAX_ROWS]:
            # a "District" column sometimes actually holds State names
            if canon_state(val):
                states.append(canon_state(val))
                continue
            place = clean_place(val)
            if place:
                districts.append(place)

    for col in cols["subdistrict"]:
        for val in df[col].drop_nulls().to_list()[:MAX_ROWS]:
            place = clean_place(val)
            if place:
                subdistricts.append(place)

    # ---- hierarchy: read the columns together, row by row
    if cols["district"] and cols["state"]:
        dcol, scol = cols["district"][0], cols["state"][0]
        for dval, sval in zip(
            df[dcol].to_list()[:MAX_ROWS], df[scol].to_list()[:MAX_ROWS]
        ):
            place, st = clean_place(dval), canon_state(sval)
            if place and st and len(d2s) < MAX_PAIRS:
                d2s[(place, st)] += 1

    if cols["subdistrict"] and cols["district"]:
        sdcol, dcol = cols["subdistrict"][0], cols["district"][0]
        for sdval, dval in zip(
            df[sdcol].to_list()[:MAX_ROWS], df[dcol].to_list()[:MAX_ROWS]
        ):
            sub, place = clean_place(sdval), clean_place(dval)
            if sub and place and len(s2d) < MAX_PAIRS:
                s2d[(sub, place)] += 1

    def top(seq):
        return [v for v, _ in Counter(seq).most_common(MAX_DISTINCT)]

    return {
        "states": top(states),
        "districts": top(districts),
        "subdistricts": top(subdistricts),
        "national": national,
        "d2s": [[d, s, c] for (d, s), c in d2s.most_common(MAX_PAIRS)],
        "s2d": [[a, b, c] for (a, b), c in s2d.most_common(MAX_PAIRS)],
        # the column actually read, plus how many candidates it beat (audit trail)
        "geo_cols": {k: [str(c) for c in v] for k, v in cols.items() if v},
        "geo_cols_all": {
            k: len(v) for k, v in matched.items() if len(v) > 1
        },
    }


def process_file(path):
    """Worker entry point: one local file -> one cache record."""
    uuid = os.path.splitext(os.path.basename(path))[0]

    try:
        df = read_sample(path)

        if df is None or df.is_empty():
            return {"uuid": uuid, "error": "empty"}

        rec = extract_from_df(df)
        rec["uuid"] = uuid
        return rec

    except Exception as exc:
        return {"uuid": uuid, "error": str(exc)[:200]}

# =========================================================
# PHASE 1: DRIVER
# =========================================================


def list_local_files(directory):
    files = []
    with os.scandir(directory) as it:
        for entry in it:
            if entry.name.lower().endswith(VALID_EXT):
                files.append(entry.path)
    return files


def load_cache(path):
    """uuid -> record, from the JSONL cache (last line for a uuid wins)."""
    records = {}

    if not os.path.exists(path):
        return records

    with open(path, "r", encoding="utf8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("uuid"):
                records[rec["uuid"]] = rec

    return records


def load_uuid_filter(path):
    """uuids to scan, one per line (blank lines and '#' comments ignored)."""
    wanted = set()
    with open(path, "r", encoding="utf8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                wanted.add(line)
    return wanted


def run_extract(args):
    files = list_local_files(LOCAL_DIR)
    print(f"local files (valid types): {len(files)}")

    # --only-uuids narrows the 23 GB scan to the datasets that still need one
    # (typically the rows whose spatial_coverage is NULL / level 'unknown').
    # The gazetteer in phase 2 is still built from the WHOLE cache, so records
    # left over from earlier, wider scans keep contributing their hierarchy
    # edges even when this pass only touches a subset.
    if args.only_uuids:
        wanted = load_uuid_filter(args.only_uuids)
        print(f"uuid filter: {len(wanted)} uuids from {args.only_uuids}")
        files = [
            p for p in files
            if os.path.splitext(os.path.basename(p))[0] in wanted
        ]
        print(f"  files matching the filter: {len(files)}")

    done = set() if args.refresh else set(load_cache(CACHE_PATH))
    if done:
        print(f"already in cache: {len(done)}")

    todo = [
        p for p in files
        if os.path.splitext(os.path.basename(p))[0] not in done
    ]

    if args.limit:
        todo = todo[: args.limit]

    print(f"to scan: {len(todo)} (workers={args.workers})")

    if not todo:
        return

    mode = "w" if args.refresh else "a"
    started = time.time()
    ok = err = 0

    with open(CACHE_PATH, mode, encoding="utf8") as out, \
            ProcessPoolExecutor(max_workers=args.workers) as pool:

        futures = [pool.submit(process_file, p) for p in todo]

        for n, fut in enumerate(as_completed(futures), start=1):
            try:
                rec = fut.result()
            except Exception as exc:
                rec = {"uuid": None, "error": f"worker: {exc}"[:200]}

            if rec.get("error"):
                err += 1
            else:
                ok += 1

            out.write(json.dumps(rec, ensure_ascii=False) + "\n")

            if n % FLUSH_EVERY == 0:
                out.flush()
                rate = n / max(time.time() - started, 1e-9)
                left = (len(todo) - n) / max(rate, 1e-9) / 60
                print(
                    f"  scanned {n}/{len(todo)}  ok={ok} err={err}  "
                    f"{rate:.1f} files/s  eta {left:.0f}m",
                    flush=True,
                )

    print(
        f"extract done: {ok} readable, {err} failed, "
        f"{(time.time() - started) / 60:.1f} min -> {CACHE_PATH}"
    )

# =========================================================
# PHASE 2: HIERARCHY GAZETTEER
# =========================================================


def build_gazetteer(records):
    """district -> State and sub-district -> district, from every file's rows.

    An edge is kept only when one parent dominates (DOMINANCE) and has at least
    MIN_PAIR_COUNT support, so genuinely ambiguous names (Aurangabad, Bilaspur,
    Hamirpur) resolve to nothing rather than to a coin flip.
    """
    d2s = defaultdict(Counter)
    s2d = defaultdict(Counter)
    district_names = Counter()

    for rec in records.values():
        for d, s, c in rec.get("d2s", []):
            d2s[_norm(d)][s] += c
        for a, b, c in rec.get("s2d", []):
            s2d[_norm(a)][b] += c
        for d in rec.get("districts", []):
            district_names[_norm(d)] += 1

    def resolve(mapping):
        out = {}
        ambiguous = 0
        for key, counter in mapping.items():
            total = sum(counter.values())
            parent, count = counter.most_common(1)[0]
            if count >= MIN_PAIR_COUNT and count / total >= DOMINANCE:
                out[key] = parent
            else:
                ambiguous += 1
        return out, ambiguous

    dist_to_state, amb_d = resolve(d2s)
    sub_to_dist, amb_s = resolve(s2d)

    print(
        f"gazetteer: {len(dist_to_state)} district->State edges "
        f"({amb_d} ambiguous dropped), {len(sub_to_dist)} sub-district->district "
        f"edges ({amb_s} ambiguous dropped), "
        f"{len(district_names)} distinct district names seen"
    )

    return {
        "dist_to_state": dist_to_state,
        "sub_to_dist": sub_to_dist,
        "district_names": set(district_names),
    }

# =========================================================
# PHASE 2: RESOLVE ONE DATASET
# =========================================================


# "... in India", "All India ..." - national scope stated in the title itself.
_NATIONAL_TITLE_RE = re.compile(r"\b(?:all[\s-]india|india)\b", re.I)


def states_from_title(title):
    out = []
    for m in _TITLE_STATE_RE.finditer(title or ""):
        st = canon_state(m.group(1))
        if st and st not in out:
            out.append(st)
    return out


def districts_from_title(title, gaz):
    """Title district, kept only if the corpus has ever seen that district.

    title_components was tuned for merge-group classification and happily
    returns fragments like "Cotton Yarn"; the gazetteer check is what makes it
    usable here.
    """
    comp = parse_title_components(title or "")
    raw = comp.get("district")

    if not raw:
        return []

    place = clean_place(raw)
    if not place:
        return []

    key = _norm(place)
    if key in gaz["district_names"] or key in gaz["dist_to_state"]:
        return [place]

    return []


def dedupe(names):
    """Case/spacing-insensitive dedupe that keeps first-seen spelling."""
    seen, out = set(), []
    for n in names:
        k = _norm(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def resolve_one(uuid, title, rec, gaz):
    """-> dict of the six spatial columns for one dataset."""
    content_states = list(rec.get("states", [])) if rec else []

    # Re-run clean_place over the cached names: it is idempotent, so tightening
    # the junk rules takes effect on an existing cache without a 47-minute
    # re-scan of 23 GB.
    districts = [p for p in (clean_place(d) for d in (rec.get("districts", []) if rec else [])) if p]
    subdistricts = [p for p in (clean_place(s) for s in (rec.get("subdistricts", []) if rec else [])) if p]

    # sub-district values are noisy ("Block A", "Zone 3"); keep only names the
    # corpus recognises as a real sub-district
    subdistricts = [
        s for s in subdistricts if _norm(s) in gaz["sub_to_dist"]
    ]

    title_states = states_from_title(title)
    title_districts = districts_from_title(title, gaz)
    title_national = bool(_NATIONAL_TITLE_RE.search(title or ""))
    is_national = bool(rec and rec.get("national")) or title_national

    # Attribute the evidence BEFORE climbing the hierarchy - afterwards an
    # inferred parent State would look like something the file said.
    has_content = bool(content_states or districts or subdistricts
                       or (rec and rec.get("national")))
    has_title = bool(title_states or title_districts or title_national)

    states = dedupe(content_states + title_states)
    districts = dedupe(districts + title_districts)
    subdistricts = dedupe(subdistricts)

    # ---- climb the hierarchy: sub-district -> district -> State ----
    if subdistricts and not districts:
        parents = dedupe([
            gaz["sub_to_dist"][_norm(s)]
            for s in subdistricts
            if _norm(s) in gaz["sub_to_dist"]
        ])
        districts = parents

    if districts and not states:
        parents = dedupe([
            gaz["dist_to_state"][_norm(d)]
            for d in districts
            if _norm(d) in gaz["dist_to_state"]
        ])
        states = parents

    if has_content and has_title:
        source = "both"
    elif has_content:
        source = "content"
    elif has_title:
        source = "title"
    else:
        source = "none"

    # ---- canonical coverage string ----
    # Never a multi-State list: hvd_score.parse_state reads the token before the
    # trailing "India" and would treat the last of 36 States as "the" State.
    if len(states) == 1:
        state = states[0]
        if len(districts) == 1 and len(subdistricts) == 1:
            # A sub-district often shares its district's name (and a small UT
            # shares all three): "Baloda Bazar, Baloda Bazar, Chhattisgarh"
            # says nothing extra, so collapse the repeats.
            #
            # The canonical `state` is appended LAST rather than deduped in
            # sequence: dropping it as "same as the previous token" would leave
            # the DISTRICT's spelling in the State slot ("Dadra And Nagar
            # Haveli" vs "Dadra and Nagar Haveli"), and hvd_score.parse_state
            # counts distinct States by exact string.
            parts = []
            for p in (subdistricts[0], districts[0]):
                if _norm(p) == _norm(state):
                    continue
                if parts and _norm(p) == _norm(parts[-1]):
                    continue
                parts.append(p)
            coverage = ", ".join(parts + [state]) + ", India"
            level = "sub_district"
        elif len(districts) == 1:
            if _norm(districts[0]) == _norm(state):
                coverage = f"{state}, India"      # e.g. Delhi district of Delhi
            else:
                coverage = f"{districts[0]}, {state}, India"
            level = "district"
        else:
            # 0 districts, or a district-wise file covering the whole State
            coverage = f"{state}, India"
            level = "state"
    elif len(states) > 1:
        coverage = "India"
        level = "multi_state"
    elif districts or subdistricts:
        # a place WAS found, but no State could be attached to it - typically an
        # ambiguous district name (Aurangabad is in both Maharashtra and Bihar).
        # Writing "<District>, India" would break the "token before India is the
        # State" contract, so the string is left NULL and the names are kept in
        # the detail columns for review.
        coverage = None
        level = "unresolved"
    elif is_national:
        # the file or title says India / All India outright
        coverage = "India"
        level = "national"
    elif source == "none":
        # Nothing in the file and nothing in the title. "India" would be a
        # positive claim of national scope - and hvd_score.signal_geo treats
        # the literal string "India" as national (0.5 geo credit), so writing
        # it here would move a live score on evidence we never had.
        coverage = None
        level = "unknown"
    else:
        coverage = None
        level = "unknown"

    def join(names):
        head = names[:NAME_CAP]
        extra = len(names) - len(head)
        text = "; ".join(head)
        return text + (f"; (+{extra} more)" if extra else "") or None

    return {
        "uuid": uuid,
        "spatial_coverage": coverage,
        "spatial_states": join(states),
        "spatial_districts": join(districts),
        "spatial_subdistricts": join(subdistricts),
        "spatial_level": level,
        "spatial_source": source,
    }

# =========================================================
# PHASE 2: DRIVER
# =========================================================

SPATIAL_COLS = [
    "spatial_coverage",
    "spatial_states",
    "spatial_districts",
    "spatial_subdistricts",
    "spatial_level",
    "spatial_source",
]


def backup_db(db_path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = f"{db_path}.spatial_backup_{stamp}"
    shutil.copy2(db_path, dest)

    # a backup nobody can open is not a backup
    con = duckdb.connect(dest, read_only=True)
    con.execute(f'SELECT count(*) FROM "{TABLE_NAME}"').fetchone()
    con.close()

    print(f"DB backed up + verified: {dest}")
    return dest


def backup_columns(db_path):
    """Snapshot just the columns this script overwrites, as CSV.

    The full-DB copy above is several GB; on a near-full disk that is both slow
    and the thing most likely to fail. Everything this script can damage lives
    in the six SPATIAL_COLS, so uuid + those columns is a complete undo set at a
    fraction of the size.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = str(Path(db_path).parent.parent / "data" / "backups" /
               f"spatial_cols_{TABLE_NAME}_{stamp}.csv")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    cols = ", ".join(f'"{c}"' for c in SPATIAL_COLS)
    con = duckdb.connect(db_path, read_only=True)
    con.execute(
        f'COPY (SELECT "{UUID_COL}", {cols} FROM "{TABLE_NAME}") '
        f"TO '{dest}' (HEADER, DELIMITER ',')"
    )
    rows = con.execute(f'SELECT count(*) FROM "{TABLE_NAME}"').fetchone()[0]
    con.close()

    print(f"spatial columns snapshotted ({rows} rows): {dest}")
    return dest


def run_resolve(args):
    records = load_cache(CACHE_PATH)
    print(f"cache records: {len(records)}")

    if not records:
        print("nothing in the cache - run with --extract first")
        return

    readable = {u: r for u, r in records.items() if not r.get("error")}
    print(f"  readable: {len(readable)}, failed to read: {len(records) - len(readable)}")

    # The gazetteer always reads the WHOLE cache, even when this pass only
    # rewrites a subset of the table: hierarchy edges harvested from datasets we
    # are not touching are exactly what resolves a district-only file here.
    gaz = build_gazetteer(readable)

    con = duckdb.connect(DB_PATH, read_only=True)
    rows = con.execute(
        f'SELECT "{UUID_COL}", title FROM "{TABLE_NAME}" WHERE "{UUID_COL}" IS NOT NULL'
    ).fetchall()
    con.close()
    print(f"DB rows with a uuid: {len(rows)}")

    # A partial cache must not be written back over the whole table. Five of the
    # six columns are overwritten outright, so a row whose file is absent from
    # this cache would have its details from an earlier, wider run blanked out.
    # --only-uuids therefore scopes the WRITE as well as the scan.
    if args.only_uuids:
        wanted = load_uuid_filter(args.only_uuids)
        rows = [r for r in rows if str(r[0]) in wanted]
        print(f"  --only-uuids: rewriting {len(rows)} of them")

    resolved = []
    for uuid, title in rows:
        resolved.append(resolve_one(uuid, title, readable.get(str(uuid)), gaz))

    # ---- corpus / table reconciliation ----
    db_uuids = {str(u) for u, _ in rows}
    no_file = len(db_uuids - set(records))
    no_row = len(set(records) - db_uuids)

    levels = Counter(r["spatial_level"] for r in resolved)
    sources = Counter(r["spatial_source"] for r in resolved)

    print(f"\nlevels : {dict(levels)}")
    print(f"sources: {dict(sources)}")
    print(
        f"reconciliation: {no_file} DB rows have no scanned file, "
        f"{no_row} scanned files have no DB row"
    )

    if args.dry_run:
        # a spread across levels, not the first 25 rows of one kind
        per_level = 5
        seen = Counter()
        print(f"\n-- sample: up to {per_level} rows per level --")
        for r, (_, title) in zip(resolved, rows):
            lvl = r["spatial_level"]
            if seen[lvl] >= per_level:
                continue
            seen[lvl] += 1
            print(
                f"  {lvl:<12} | {str(r['spatial_coverage']):<45} | "
                f"{r['spatial_source']:<7} | {(title or '')[:58]}"
            )
            if r["spatial_states"] and lvl == "multi_state":
                print(f"       states   : {r['spatial_states'][:110]}")
            if r["spatial_districts"]:
                print(f"       districts: {r['spatial_districts'][:110]}")
            if r["spatial_subdistricts"]:
                print(f"       sub-dist : {r['spatial_subdistricts'][:110]}")

        print("\nDRY RUN - nothing written")
        return

    if args.backup == "columns":
        backup_columns(DB_PATH)
    elif args.backup == "db":
        backup_db(DB_PATH)
    else:
        print("WARNING: --backup none - nothing was saved before the write")

    con = duckdb.connect(DB_PATH)
    for col in SPATIAL_COLS:
        con.execute(
            f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN IF NOT EXISTS "{col}" VARCHAR'
        )

    frame = pd.DataFrame(resolved)
    written = 0
    chunk = 20000

    for start in range(0, len(frame), chunk):
        part = frame.iloc[start:start + chunk]
        con.register("spatial_upd", part)
        # spatial_coverage is COALESCEd: extract_coverage_from_title.py already
        # wrote a value on some rows, and a detection of "unknown" here (NULL)
        # is not a reason to delete what another pass concluded. Every other
        # column is ours alone and is overwritten outright.
        sets = ", ".join(
            'spatial_coverage = COALESCE(u.spatial_coverage, d.spatial_coverage)'
            if c == "spatial_coverage" else f'"{c}" = u.{c}'
            for c in SPATIAL_COLS
        )
        con.execute(
            f'''
            UPDATE "{TABLE_NAME}" AS d
            SET {sets}
            FROM spatial_upd AS u
            WHERE d."{UUID_COL}" = u.uuid
            '''
        )
        con.unregister("spatial_upd")
        written += len(part)
        print(f"  wrote {written}/{len(frame)}", flush=True)

    check = con.execute(
        f'''
        SELECT count(*) FROM "{TABLE_NAME}"
        WHERE spatial_coverage IS NOT NULL AND spatial_coverage <> 'India'
        '''
    ).fetchone()[0]
    con.close()

    print(
        f"\nDONE - wrote {written} rows into {TABLE_NAME}; "
        f"{check} rows carry a State-or-finer coverage"
    )

# =========================================================
# MAIN
# =========================================================


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--extract", action="store_true",
                    help="phase 1 only: parallel scan of local files")
    ap.add_argument("--resolve", action="store_true",
                    help="phase 2 only: gazetteer + write to DB")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve and print a preview; write nothing")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--limit", type=int, default=0,
                    help="scan at most N files (phase 1 testing)")
    ap.add_argument("--backup", choices=("db", "columns", "none"), default="db",
                    help="what to save before writing: 'db' copies the whole "
                         "database (default, several GB), 'columns' dumps only "
                         "uuid + the six spatial columns to data/backups/*.csv, "
                         "'none' skips it")
    ap.add_argument("--only-uuids", default=None, metavar="FILE",
                    help="phase 1: scan only the uuids listed in FILE (one per "
                         "line) instead of every local file")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore + overwrite the extract cache. REQUIRED after "
                         "any change to classify_header / clean_place / "
                         "extract_from_df, otherwise the cache silently mixes "
                         "records produced by two different code versions.")
    args = ap.parse_args()

    do_extract = args.extract or not (args.extract or args.resolve or args.dry_run)
    do_resolve = args.resolve or args.dry_run or not (args.extract or args.resolve)

    if do_extract:
        run_extract(args)

    if do_resolve:
        run_resolve(args)


if __name__ == "__main__":
    main()
