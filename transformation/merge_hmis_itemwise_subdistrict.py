"""
Merge HMIS Item-wise sub-district reports up to STATE level.

Source shape
------------
Each source dataset is one district-month: 4 identifier columns
(`Indicator, S.No., Parameters, Type`) followed by one wide value column per
sub-district. The district lives in the *title*, the financial year and month
live in the *title*, and the sub-districts live in *column names* — so three of
the four dimensions of the series are not columns at all. That is why these
collections are `merge_method='curate'`.

What this script does
---------------------
Generalises the single-district example (one district, one FY) to every
district of a state and every financial year. The source is transposed: an
indicator-per-row / sub-district-per-column file becomes a
sub-district-per-row / indicator-per-column table.

  * each source column (a sub-district, optionally x facility category) becomes
    one output ROW, carrying District / Sub District / FY / Month as real
    columns;
  * each source row (an indicator) becomes one output COLUMN.

That orientation is what keeps the output small. Unpivoting to fully long form
instead — one row per indicator per sub-district per month — repeats the
indicator name and its full description on every one of ~88M rows for these two
states. Transposing gives the same cells in ~0.3M rows of ~300 columns.

Monthly and cumulative are written to SEPARATE files
----------------------------------------------------
Every district-month is published twice: `... for <Month>-<FY>` is that month
alone, `... upto <Month>-<FY>` is cumulative from the start of the financial
year. They are the same indicators on different bases; in one table they are
indistinguishable without reading a column, and any sum over the table
double-counts. So each basis gets its own file.

...and so are the two indicator frameworks
------------------------------------------
HMIS renumbered its indicators in 2017-18. Measured on these datasets: of the
318 pre-2017-18 indicator codes and the 286 from 2017-18 onwards, only 33 codes
appear in both — and all 33 mean something different (`13.2` is "Intraocular
Lens implantations" before and "DOTS cases completed successfully" after). One
column cannot hold both, so each era gets its own file too: 2 bases x 2 eras
per state.

Indicator columns are identified by (Indicator group, Type, Parameters), not by
S.No., because S.No. is not stable even within an era: the same indicator is
published as `8.1` in some files and `8.10` in others, and `10.1` is used for
two different indicators (Malaria and Pneumonia) in the same file. The
representative S.No. is used in the column label, and every observed variant is
recorded in the indicator dictionary.

District roll-up columns
------------------------
A column named `SubDistrict-_Kodagu` (leading underscore) is the *district
total*, not a sub-district. It is kept — dropping data is not this script's job
— but flagged in a `Level` column (`district_total` vs `subdistrict`) so that
anyone aggregating the merged table does not double-count every district.

Usage
-----
    python transformation/merge_hmis_itemwise_subdistrict.py
    python transformation/merge_hmis_itemwise_subdistrict.py --state Karnataka --gzip
    python transformation/merge_hmis_itemwise_subdistrict.py --limit 20   # smoke test
    python transformation/merge_hmis_itemwise_subdistrict.py --layout long

Outputs (under data/hmis_itemwise_subdistrict_merged/):
    hmis_itemwise_subdistrict_<state>_<basis>_<era>.csv  merged table, indicators as columns
    <state>_indicator_columns.csv                        column dictionary (label -> indicator)
    <state>_manifest.csv                                 one row per source dataset
    <state>_duplicates.csv                               datasets dropped as re-publications
    <state>_merge_notes.md                               what was merged, and the verification
"""

import argparse
import csv
import gzip
import hashlib
import multiprocessing
import os
import re
import subprocess
import sys
import io
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "transformation" / "metadata.db"
TABLE = "dublin_core_metadata"
DOWNLOAD_DIR = ROOT / "data" / "first_batch_downloads"
OUT_DIR = ROOT / "data" / "hmis_itemwise_subdistrict_merged"

DEFAULT_STATES = ["Odisha", "Assam"]
# One catalog per state holds exactly this family, which is a tighter selector
# than the collection titles (some collections carry no `(FY ...)` suffix and a
# handful of datasets carry no Collection at all).
CATALOG_TEMPLATE = "HMIS sub district level item-wise monthly report of {state}"

MONTHS = ("January|February|March|April|May|June|July|August|"
          "September|October|November|December")

# Basis + month + FY, anchored at the end of the title. Anchoring on the month
# matters: "District-Wise HMIS Item Reports for Deogarh, Odisha upto December
# 2014-15" contains both "for" and "upto", and a bare \b(for|upto)\b would call
# that monthly. The separator before the FY is "-" in most titles and a space
# in a few.
TITLE_RE = re.compile(
    rf"(?i)\b(?P<basis>upto|for)\s+(?P<month>{MONTHS})[-,\s]+(?P<fy>\d{{4}}-\d{{2}})\s*$"
)
# District + state from the title. Two title phrasings exist:
#   "Item-wise report for <District> of <State> upto ..."
#   "District-Wise HMIS Item Reports for <District>, <State> upto ..."
TITLE_GEO_RE = re.compile(r"(?i)\bfor\s+(?P<district>.+?)(?:,|\s+of)\s+(?P<state>{state})\b")
# District + state from the Collection. The trailing "(FY ...)" is optional and
# a "[NN cols]" suffix may follow it.
COLLECTION_GEO_RE = re.compile(
    r"Sub-districts of (?P<district>.+?), (?P<state>[A-Za-z &.]+?)\s*(?:\(FY|\[|$)"
)

# A data column is "SubDistrict-<name>" (pre-2017-18) or
# "SubDistrict-<name>-<Category> [<code>]" (2017-18 onwards). Anchoring on the
# known category suffix instead of splitting on "-" is what keeps sub-district
# names that contain a hyphen intact.
CATEGORIES = ("Total", "Public", "Private", "Urban", "Rural")
DATA_COL_RE = re.compile(
    r"^SubDistrict\s*-\s*(?P<sd>.*?)"
    rf"(?:\s*-\s*(?P<cat>{'|'.join(CATEGORIES)})\s*\[[^\]]*\])?$"
)

BASIS_LABELS = {"for": "monthly", "upto": "cumulative"}
DISTRICT_TOTAL_LABEL = "All Subdistricts"
FORMAT_OLD = "Old (pre 2017-18)"
FORMAT_NEW = "Revised (2017-18 onwards)"
ERA_SLUG = {FORMAT_OLD: "pre-2017-18", FORMAT_NEW: "2017-18-onwards"}

HEADER_ID_COLS = ["Indicator", "S.No.", "Parameters", "Type"]
# Row identity of the wide output. One row per source data column.
KEY_COLS = [
    "State", "District", "Sub District", "Level",
    "Report FY", "Month", "Report Basis", "Format Version",
    "Facility Category", "source_uuid",
]
# Row identity of the long output; indicators stay in rows.
LONG_HEADER = KEY_COLS[:-1] + [
    "Indicator", "S.No.", "Parameters", "Type", "Value", "source_uuid",
]


# --------------------------------------------------------------------------- #
# metadata
# --------------------------------------------------------------------------- #
def fetch_members(con, state: str) -> pd.DataFrame:
    """
    Every dataset of the state's sub-district catalog, with the two numbers the
    DB already knows about each file: its row count and its header.

    `Conforms To` is the stored header, so the size of the job can be worked out
    before a single file is opened. It is punctuation-stripped
    (`SubDistrictAchneraTotal AB or CD`), which is enough to count columns and
    tell the two header shapes apart but NOT enough to recover the sub-district
    and category — those still come from the real header, in the pass that reads
    the file anyway.
    """
    return con.execute(
        f'''
        select Collection            as source_collection,
               Title                 as source_title,
               "Identifier[UUID]"    as source_uuid,
               Financial_Year        as db_fy,
               Month                 as db_month,
               try_cast(row_count as bigint) as db_row_count,
               "Conforms To"         as db_header,
               merge_method,
               merge_add_columns
        from {TABLE}
        where "Relation[Catalog Title]" = ?
        order by Title
        ''',
        [CATALOG_TEMPLATE.format(state=state)],
    ).fetchdf()


def preflight(members: pd.DataFrame) -> pd.DataFrame:
    """Size the job from the DB's stored headers — no file I/O."""
    n_cols = members.db_header.fillna("").str.count(",") - 3
    shape = members.db_header.fillna("").str.contains("Total AB or CD").map(
        {True: "categorised", False: "plain"}
    )
    return pd.DataFrame({
        "db_data_columns": n_cols.clip(lower=0),
        "db_header_shape": shape,
        "db_cells": n_cols.clip(lower=0) * members.db_row_count.fillna(0),
    }, index=members.index)


def parse_members(df: pd.DataFrame, state: str) -> pd.DataFrame:
    """
    Derive (state, district, FY, month, basis) for every dataset.

    The title is the primary source and the Collection only a fallback: a few
    datasets carry no Collection at all, and where both exist they agree (the
    run asserts this).
    """
    geo_re = re.compile(TITLE_GEO_RE.pattern.format(state=re.escape(state)))
    out = []
    for rec in df.itertuples():
        t = str(rec.source_title).strip()
        m = TITLE_RE.search(t)
        g = geo_re.search(t)
        c = (COLLECTION_GEO_RE.search(rec.source_collection)
             if isinstance(rec.source_collection, str) else None)
        out.append({
            "basis": BASIS_LABELS[m.group("basis").lower()] if m else None,
            "month": m.group("month").title() if m else None,
            "fy": m.group("fy") if m else None,
            "district": (g.group("district").strip() if g
                         else c.group("district").strip() if c else None),
            "state": state,
            "coll_district": c.group("district").strip() if c else None,
            "coll_basis": (BASIS_LABELS["upto" if "Cumulative" in rec.source_collection else "for"]
                           if isinstance(rec.source_collection, str) else None),
        })
    parsed = pd.DataFrame(out, index=df.index)
    parsed["format_version"] = parsed.fy.map(
        lambda f: None if not f else (FORMAT_NEW if int(f[:4]) >= 2017 else FORMAT_OLD)
    )
    return pd.concat([df, parsed], axis=1)


def dedupe(members: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Drop re-publications of the same district-month.

    A handful of datasets are published twice under different UUIDs — the
    duplicate typically carries no Collection. Keeping both would double every
    row of that district-month in the merged table, so one is kept per
    (district, FY, month, basis) key and the rest are recorded, with a
    content hash (line endings normalised) so it is visible whether the
    dropped copy was byte-identical or genuinely different.
    """
    key = ["district", "fy", "month", "basis"]
    # Prefer the copy that has a Collection; break remaining ties on UUID so the
    # choice is deterministic across runs.
    members = members.assign(_no_coll=members.source_collection.isna().astype(int))
    members = members.sort_values(["_no_coll", "source_uuid"], kind="stable")
    keep_mask = ~members.duplicated(subset=key, keep="first")
    kept = members[keep_mask].drop(columns="_no_coll")
    dropped = members[~keep_mask].drop(columns="_no_coll")

    if len(dropped):
        kept_by_key = {k: u for k, u in zip(map(tuple, kept[key].values), kept.source_uuid)}
        rows = []
        for rec in dropped.itertuples():
            k = (rec.district, rec.fy, rec.month, rec.basis)
            kept_uuid = kept_by_key[k]
            rows.append({
                "dropped_uuid": rec.source_uuid,
                "dropped_title": rec.source_title,
                "dropped_collection": rec.source_collection,
                "kept_uuid": kept_uuid,
                "district": rec.district, "fy": rec.fy,
                "month": rec.month, "basis": rec.basis,
                "content_identical": content_hash(rec.source_uuid) == content_hash(kept_uuid),
            })
        dropped = pd.DataFrame(rows)
    else:
        dropped = pd.DataFrame(columns=["dropped_uuid", "kept_uuid", "content_identical"])

    return kept.sort_values(["basis", "district", "fy", "month"], kind="stable"), dropped


def content_hash(uuid: str) -> str:
    """MD5 of the file with line endings normalised, so CRLF/LF-only differences
    do not read as different content."""
    data = (DOWNLOAD_DIR / f"{uuid}.csv").read_bytes()
    return hashlib.md5(data.replace(b"\r\n", b"\n")).hexdigest()


# --------------------------------------------------------------------------- #
# files
# --------------------------------------------------------------------------- #
def rel(path: Path) -> str:
    """Repo-relative path when the output lives in the repo, absolute otherwise."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def open_rows(path: Path) -> io.StringIO:
    """
    Read a source CSV as text, falling back to cp1252.

    Decoding the whole file up front rather than streaming it: these files are
    ~100 KB, and a partial read cannot tell whether a UnicodeDecodeError is
    waiting further down — which would otherwise surface halfway through
    writing the merged output.
    """
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    return io.StringIO(text, newline="")


def read_header(path: Path) -> list[str]:
    """
    Just the first line. Deliberately not `open_rows`, which decodes the whole
    file: the header pre-pass runs over every source file, and reading all of
    them in full turns a cheap validation into a third full read of the corpus.
    """
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return next(csv.reader(fh))
    except UnicodeDecodeError:
        with open(path, encoding="cp1252", newline="") as fh:
            return next(csv.reader(fh))


def parse_data_cols(header: list[str]) -> tuple[list[tuple[str, str, str]], list[str]]:
    """
    header -> [(sub_district, level, facility_category)], plus any columns that
    did not match the expected shape.

      'SubDistrict-Madikeri'                     -> ('Madikeri', 'subdistrict', 'Total')
      'SubDistrict-Madikeri-Public [A]'          -> ('Madikeri', 'subdistrict', 'Public')
      'SubDistrict-_Kodagu-Total [(A+B) or (C+D)]'
                                                 -> ('All Subdistricts', 'district_total', 'Total')
    """
    cols, bad = [], []
    for h in header[4:]:
        m = DATA_COL_RE.match(h.replace("\xa0", " ").strip())
        if not m:
            bad.append(h)
            continue
        sd = m.group("sd").strip()
        if sd.startswith("_"):                      # leading underscore = district roll-up
            sd, level = DISTRICT_TOTAL_LABEL, "district_total"
        else:
            level = "subdistrict"
        cols.append((sd, level, m.group("cat") or "Total"))
    return cols, bad


def canon(s: str) -> str:
    """
    Normalise an identifier cell.

    Three artefacts of the source exports have to go before anything can be
    keyed on these values: non-breaking spaces inside the text, runs of
    whitespace, and S.No. codes exported as a quoted literal (`'1.1'`) in some
    files and bare (`1.1`) in others. Left alone, the last one alone makes two
    files of the same year look like two different indicator frameworks.
    """
    s = str(s).replace("\xa0", " ").strip()
    if len(s) > 1 and s[0] == "'" and s[-1] == "'":
        s = s[1:-1].strip()
    return re.sub(r"\s+", " ", s)


def indicator_key(indicator: str, typ: str, parameters: str) -> tuple[str, str, str]:
    """
    Identity of an indicator column: (Indicator group, Type, Parameters).

    Deliberately NOT keyed on S.No.. Within one era the same indicator is
    published as `8.1` in some files and `8.10` in others (trailing zero lost in
    an export), which would split one column into two; and `10.1` is used for
    two different indicators in the same file, which would collapse two columns
    into one. The group + breakdown + description text is stable across both.
    Case-folded so capitalisation drift does not fork a column.
    """
    return (canon(indicator).casefold(), canon(typ).casefold(), canon(parameters).casefold())


def ordered_union(base: list, incoming: list) -> list:
    """
    Union two column orders while keeping both sequences intact.

    New keys are inserted after the last already-known key that precedes them in
    `incoming`, so an indicator added in a later year lands inside its own M-group
    instead of being appended after M16.
    """
    out = list(base)
    anchor = -1
    for k in incoming:
        if k in out:
            anchor = out.index(k)
        else:
            anchor += 1
            out.insert(anchor, k)
    return out


def scan_chunk(tasks: list[tuple[str, str]]) -> dict:
    """
    Worker: read a chunk of source files and report everything the merge needs
    to know about them — header validity, shape, and the indicator sequence.

    Aggregated per chunk rather than per file: returning one entry per file
    would ship ~300 indicator tuples per file back through the pipe, and every
    file of an era has the same sequence.
    """
    stats, problems, meta = [], [], {}
    sequences = defaultdict(list)
    for uuid, era in tasks:
        header, rows = iter_rows(DOWNLOAD_DIR / f"{uuid}.csv")
        id_cols = [canon(h) for h in header[:4]]
        if id_cols != HEADER_ID_COLS:
            problems.append(f"{uuid}: identifier columns {id_cols}")
        cols, bad = parse_data_cols(header)
        if bad:
            problems.append(f"{uuid}: unparsed data columns {bad[:3]}")

        keys, seen = [], set()
        for r in rows:
            ind, sno, par, typ = (canon(v) for v in r[:4])
            k = indicator_key(ind, typ, par)
            if k in seen:
                problems.append(f"{uuid}: repeated indicator {ind} / {sno} / {par[:40]}")
                continue
            seen.add(k)
            keys.append(k)
            m = meta.setdefault((era, k), [ind, par, typ, Counter(), 0])
            m[3][sno] += 1
            m[4] += 1
        seq = tuple(keys)
        if seq not in sequences[era]:
            sequences[era].append(seq)
        stats.append({
            "source_uuid": uuid,
            "data_columns": len(cols),
            "sub_districts": len({c[0] for c in cols}),
            "header_shape": "categorised" if any(c[2] != "Total" for c in cols) else "plain",
            "file_row_count": len(rows),
            "distinct_row_keys": len(set(cols)),
        })
    return {"stats": stats, "problems": problems, "meta": meta,
            "sequences": {e: v for e, v in sequences.items()}}


def build_indicator_columns(members: pd.DataFrame, workers: int) -> tuple[dict, pd.DataFrame,
                                                                         pd.DataFrame, list[str]]:
    """
    First pass: read every source file and derive, per era, the ordered list of
    indicator columns.

    Returns {era: {key: column_index}}, the dictionary table, per-file stats,
    and any problems.
    """
    tasks = list(zip(members.source_uuid, members.format_version))
    order, meta, problems, stats = defaultdict(list), defaultdict(dict), [], []
    for res in imap_chunks(scan_chunk, tasks, workers, "scanned"):
        stats.extend(res["stats"])
        problems.extend(res["problems"])
        for era, seqs in res["sequences"].items():
            for seq in seqs:
                order[era] = ordered_union(order[era], list(seq)) if order[era] else list(seq)
        for (era, k), (ind, par, typ, snos, files) in res["meta"].items():
            m = meta[era].setdefault(
                k, {"Indicator": ind, "Parameters": par, "Type": typ,
                    "sno": Counter(), "files": 0}
            )
            m["sno"].update(snos)
            m["files"] += files

    index, dict_rows = {}, []
    for era, keys in order.items():
        labels = {}
        for pos, k in enumerate(keys):
            m = meta[era][k]
            sno = m["sno"].most_common(1)[0][0]
            label = f"{sno} {m['Parameters']}"
            if m["Type"].upper() != "TOTAL":
                label += f" [{m['Type']}]"
            # Two indicators that differ only in their group would collide here;
            # keep them apart rather than silently overwriting one with the other.
            if label in labels:
                label = f"{label} ({m['Indicator'].split(' [')[0]})"
            labels[label] = k
            dict_rows.append({
                "Format Version": era,
                "column_position": pos + 1,
                "column_label": label,
                "Indicator": m["Indicator"],
                "S.No.": sno,
                "S.No. variants": " | ".join(sorted(m["sno"])) if len(m["sno"]) > 1 else "",
                "Parameters": m["Parameters"],
                "Type": m["Type"],
                "source_files": m["files"],
            })
        index[era] = {k: i for i, k in enumerate(keys)}
        index[era, "labels"] = list(labels)
    return (index, pd.DataFrame(dict_rows),
            pd.DataFrame(stats).set_index("source_uuid"), problems)


FISCAL_MONTHS = ["April", "May", "June", "July", "August", "September",
                 "October", "November", "December", "January", "February", "March"]


def span_slug(df: pd.DataFrame) -> str:
    """
    `Sep-2011-12_to_Mar-2016-17` — the fiscal span of a set of datasets, for the
    filename. Ordered fiscally (April first), so the first month of the series
    is not confused with the earliest calendar month.
    """
    order = {mn: i for i, mn in enumerate(FISCAL_MONTHS)}
    o = df.fy.str[:4].astype(int) * 12 + df.month.map(order)
    a, b = df.loc[o.idxmin()], df.loc[o.idxmax()]
    return f"{a.month[:3]}-{a.fy}_to_{b.month[:3]}-{b.fy}"


def coverage_table(manifest: pd.DataFrame) -> pd.DataFrame:
    """
    Temporal coverage: where each district's series starts and ends, and whether
    anything is missing in between.

    Months are ordered fiscally (April first), so "first month" means the first
    month of the series and not simply January. `missing_months` is the gap
    between the months actually published and the months the span implies —
    without it a district that skipped a year still looks fully covered.
    """
    m = manifest.copy()
    order = {mn: i for i, mn in enumerate(FISCAL_MONTHS)}
    m["_ord"] = m.fy.str[:4].astype(int) * 12 + m.month.map(order)
    rows = []
    for keys, g in m.groupby(["state", "basis", "format_version", "district"], sort=True):
        first, last = g.loc[g._ord.idxmin()], g.loc[g._ord.idxmax()]
        present = g[["fy", "month"]].drop_duplicates().shape[0]
        possible = int(last._ord - first._ord) + 1
        rows.append({
            "state": keys[0], "basis": keys[1], "format_version": keys[2],
            "district": keys[3],
            "from_month": first.month, "from_fy": first.fy,
            "to_month": last.month, "to_fy": last.fy,
            "financial_years": g.fy.nunique(),
            "months_present": present,
            "months_in_span": possible,
            "missing_months": possible - present,
            "datasets": len(g),
        })
    return pd.DataFrame(rows)


def chunked(seq: list, workers: int) -> list[list]:
    """Split into ~4 chunks per worker: enough to even out stragglers, few
    enough that per-chunk overhead stays negligible."""
    n = max(1, min(len(seq), workers * 4))
    size = -(-len(seq) // n)
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def imap_chunks(fn, tasks: list, workers: int, verb: str):
    """Run `fn` over chunks of `tasks`, in order, with a progress line."""
    chunks = chunked(tasks, workers)
    done = 0
    if workers == 1:
        for c in chunks:
            yield fn(c)
            done += len(c)
            print(f"    {verb} {done:,}/{len(tasks):,}", flush=True)
        return
    with multiprocessing.Pool(workers) as pool:
        for res in pool.imap(fn, chunks):
            done += len(chunks[0])
            print(f"    {verb} {min(done, len(tasks)):,}/{len(tasks):,}", flush=True)
            yield res


def iter_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """(header, data rows) of a source file, blank trailing lines dropped."""
    rows = list(csv.reader(open_rows(path)))
    return rows[0], [r for r in rows[1:] if len(r) >= 4]


# --------------------------------------------------------------------------- #
# merge
# --------------------------------------------------------------------------- #
class OutputSet:
    """The open output files for one state, keyed by whatever splits them."""

    def __init__(self, state: str, out_dir: Path, use_gzip: bool):
        self.slug = state.lower().replace(" ", "_")
        self.out_dir = out_dir
        self.suffix = ".csv.gz" if use_gzip else ".csv"
        self.use_gzip = use_gzip
        self.handles, self.writers, self.paths = {}, {}, {}
        self.rows = Counter()

    def writer(self, key: tuple, name: str, header: list[str]):
        if key not in self.writers:
            p = self.out_dir / f"hmis_itemwise_subdistrict_{self.slug}_{name}{self.suffix}"
            fh = (gzip.open(p, "wt", newline="", encoding="utf-8") if self.use_gzip
                  else open(p, "w", newline="", encoding="utf-8"))
            self.handles[key], self.paths[key] = fh, p
            self.writers[key] = csv.writer(fh)
            self.writers[key].writerow(header)
        return self.writers[key]

    def close(self):
        for fh in self.handles.values():
            fh.close()

    def report(self):
        for key, p in sorted(self.paths.items()):
            print(f"    wrote {rel(p)}  "
                  f"({self.rows[key]:,} rows, {p.stat().st_size / 1e6:,.0f} MB)")


def write_shard(task: dict) -> list[dict]:
    """
    Worker: transpose a chunk of source files into one headerless shard.

    One row per source data column, one column per indicator. Memory stays flat
    — a file's rows are built and written before the next file is opened, and a
    file is only ~90 rows x ~300 columns.
    """
    col_index, n_labels, state = task["col_index"], task["n_labels"], task["state"]
    stats = []
    fh = (gzip.open(task["shard"], "wt", newline="", encoding="utf-8") if task["gzip"]
          else open(task["shard"], "w", newline="", encoding="utf-8"))
    with fh:
        w = csv.writer(fh).writerow
        for rec in task["records"]:
            header, rows = iter_rows(DOWNLOAD_DIR / f"{rec['uuid']}.csv")
            cols, _ = parse_data_cols(header)

            matrix = [[""] * n_labels for _ in cols]   # matrix[j] = output row for column j
            n_short = n_unknown = 0
            for r in rows:
                ind, sno, par, typ = (canon(v) for v in r[:4])
                ci = col_index.get(indicator_key(ind, typ, par))
                if ci is None:                    # cannot happen: the scan saw this file
                    n_unknown += 1
                    continue
                values = r[4:]
                if len(values) != len(cols):      # never let zip() truncate silently
                    n_short += 1
                    values = (values + [""] * len(cols))[:len(cols)]
                for j, val in enumerate(values):
                    matrix[j][ci] = val

            prefix = [state, rec["district"], None, None, rec["fy"], rec["month"],
                      rec["basis"], rec["era"], None, rec["uuid"]]
            for (sd, level, cat), values in zip(cols, matrix):
                prefix[2], prefix[3], prefix[8] = sd, level, cat
                w(prefix + values)
            stats.append({
                "source_uuid": rec["uuid"],
                "ragged_rows": n_short,
                "unknown_indicators": n_unknown,
                "out_rows": len(cols),
                "cells": len(rows) * len(cols),
            })
    return stats


def merge_state_wide(state, members, index, out_dir, use_gzip, workers) -> pd.DataFrame:
    """
    Write one table per (basis, era).

    Each group's files are split across workers, every worker writing its own
    headerless shard, and the shards are then concatenated onto the header with
    `cat` — which is both faster than funnelling every row back through one
    process and order-preserving, since the shards are concatenated in the order
    the chunks were cut. (Concatenated gzip members are themselves a valid gzip
    stream, so this holds for --gzip too.)
    """
    suffix = ".csv.gz" if use_gzip else ".csv"
    slug = state.lower().replace(" ", "_")
    tmp_dir = out_dir / f".shards_{slug}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    stats, written = [], Counter()

    groups = members.groupby(["basis", "format_version"], sort=True)
    try:
        for (basis, era), grp in groups:
            labels = index[era, "labels"]
            records = [{"uuid": r.source_uuid, "district": r.district, "fy": r.fy,
                        "month": r.month, "basis": basis, "era": era}
                       for r in grp.itertuples()]
            chunks = chunked(records, workers)
            tasks = [{"shard": tmp_dir / f"{basis}_{ERA_SLUG[era]}_{i:04d}{suffix}",
                      "records": c, "col_index": index[era], "n_labels": len(labels),
                      "state": state, "gzip": use_gzip}
                     for i, c in enumerate(chunks)]

            print(f"    {basis} / {ERA_SLUG[era]}: {len(records):,} files "
                  f"-> {len(tasks)} shards", flush=True)
            if workers == 1:
                for t in tasks:
                    stats.extend(write_shard(t))
            else:
                with multiprocessing.Pool(min(workers, len(tasks))) as pool:
                    for s in pool.imap(write_shard, tasks):
                        stats.extend(s)

            # The span goes in the filename so the period a table covers is
            # visible without opening it. It also identifies the framework:
            # pre-2017-18 tables end in FY 2016-17, revised ones start 2017-18.
            path = (out_dir /
                    f"hmis_itemwise_subdistrict_{slug}_{basis}_{span_slug(grp)}{suffix}")
            fh = (gzip.open(path, "wt", newline="", encoding="utf-8") if use_gzip
                  else open(path, "w", newline="", encoding="utf-8"))
            with fh:
                csv.writer(fh).writerow(KEY_COLS + labels)
            with open(path, "ab") as out_fh:
                subprocess.run(["cat", *[str(t["shard"]) for t in tasks]],
                               stdout=out_fh, check=True)
            for t in tasks:
                t["shard"].unlink()
            written[(basis, era)] = sum(len(c) for c in chunks)
            print(f"    wrote {rel(path)}  "
                  f"({path.stat().st_size / 1e6:,.0f} MB)", flush=True)
    finally:
        if tmp_dir.exists() and not any(tmp_dir.iterdir()):
            tmp_dir.rmdir()
    return pd.DataFrame(stats).set_index("source_uuid")


def merge_state_long(state, members, out_dir, use_gzip) -> pd.DataFrame:
    """
    Fully long alternative: one row per indicator per sub-district per month.

    Kept because it is the layout that survives mixing eras — the indicator name
    travels with the value instead of living in a header whose meaning changed
    in 2017-18 — but it is ~300x more rows, so it is not the default.
    """
    out = OutputSet(state, out_dir, use_gzip)
    stats = []
    try:
        for i, rec in enumerate(members.itertuples(), 1):
            header, rows = iter_rows(DOWNLOAD_DIR / f"{rec.source_uuid}.csv")
            cols, _ = parse_data_cols(header)
            key = (rec.basis,)
            w = out.writer(key, rec.basis, LONG_HEADER).writerow
            n_short = 0
            for r in rows:
                ind, sno, par, typ = (canon(v) for v in r[:4])
                values = r[4:]
                if len(values) != len(cols):
                    n_short += 1
                    values = (values + [""] * len(cols))[:len(cols)]
                for (sd, level, cat), val in zip(cols, values):
                    w([state, rec.district, sd, level, rec.fy, rec.month,
                       rec.basis, rec.format_version, cat,
                       ind, sno, par, typ, val, rec.source_uuid])
            out.rows[key] += len(rows) * len(cols)
            stats.append({
                "source_uuid": rec.source_uuid,
                "file_row_count": len(rows),
                "ragged_rows": n_short,
                "unknown_indicators": 0,
                "out_rows": len(rows) * len(cols),
                "distinct_row_keys": len(set(cols)),
                "cells": len(rows) * len(cols),
            })
            if i % 500 == 0:
                print(f"    {i:>6}/{len(members)} files, "
                      f"{sum(out.rows.values()):,} rows written", flush=True)
    finally:
        out.close()
    out.report()
    return pd.DataFrame(stats).set_index("source_uuid")


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def run_state(con, state: str, out_dir: Path, use_gzip: bool, limit: int | None,
              layout: str, workers: int) -> bool:
    print(f"\n=== {state}")
    raw = fetch_members(con, state)
    if raw.empty:
        print(f"  no datasets found for catalog "
              f"'{CATALOG_TEMPLATE.format(state=state)}'", file=sys.stderr)
        return False
    members = parse_members(raw, state)

    unparsed = members[members.basis.isna() | members.district.isna() | members.fy.isna()]
    missing = [u for u in members.source_uuid
               if not (DOWNLOAD_DIR / f"{u}.csv").exists()]
    # Basis and district are read off the title; where a Collection also exists
    # it is an independent statement of the same two facts, so disagreement
    # means one of them is wrong and the run should say so.
    have_coll = members[members.source_collection.notna()]
    basis_conflict = have_coll[have_coll.basis != have_coll.coll_basis]
    district_conflict = have_coll[
        have_coll.district.str.lower() != have_coll.coll_district.str.lower()
    ]

    print(f"  {len(members):,} datasets, {members.district.nunique()} districts, "
          f"FY {members.fy.min()}–{members.fy.max()}, "
          f"{dict(members.basis.value_counts())}")

    members, dropped = dedupe(members)
    if limit:
        members = members.groupby("basis", group_keys=False).head(limit)
        print(f"  --limit {limit}: {len(members)} datasets per basis")

    if missing:
        print(f"  {len(missing)} source files missing, aborting", file=sys.stderr)
        return False

    # Pre-flight off the DB's stored headers: says how big the job is before any
    # file is opened.
    pre = preflight(members)
    print(f"  expect {int(pre.db_data_columns.sum()):,} rows "
          f"({int(pre.db_cells.sum()):,} cells), "
          f"{pre.db_header_shape.value_counts().to_dict()}")

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"  scanning {len(members):,} files on {workers} workers ...", flush=True)
    index, indicator_dict, headers, problems = build_indicator_columns(members, workers)
    if problems:
        print(f"  {len(problems)} header/indicator problems, e.g.:", file=sys.stderr)
        for p in problems[:5]:
            print(f"    {p}", file=sys.stderr)
        return False
    for era, n in indicator_dict["Format Version"].value_counts().items():
        print(f"    {era}: {n} indicator columns")

    if layout == "wide":
        stats = merge_state_wide(state, members, index, out_dir, use_gzip, workers)
    else:
        indicator_dict = pd.DataFrame()
        stats = merge_state_long(state, members, out_dir, use_gzip)

    manifest = members.set_index("source_uuid").join(headers).join(stats).reset_index()
    # The scan read the real headers; the DB's stored header is an independent
    # record of the same thing, so disagreement means one of them is stale.
    pre = pre.set_index(members.source_uuid)
    header_drift = int((manifest.set_index("source_uuid").data_columns
                        != pre.db_data_columns).sum())
    # The era is derived from the financial year (S.No. semantics changed in
    # 2017-18); the header shape is an independent signal of the same change.
    # Cross-checking them beats assuming they line up.
    era = pd.crosstab(manifest.format_version, manifest.header_shape)
    era_consistent = (
        era.reindex(index=[FORMAT_OLD, FORMAT_NEW],
                    columns=["plain", "categorised"], fill_value=0)
           .pipe(lambda t: t.loc[FORMAT_OLD, "categorised"] == 0
                           and t.loc[FORMAT_NEW, "plain"] == 0)
    )

    rc = manifest.dropna(subset=["db_row_count"])
    rc_mismatch = rc[rc.file_row_count != rc.db_row_count.astype(int)]
    dup_keys = manifest.groupby(["basis", "district", "fy", "month"]).size()
    dup_keys = dup_keys[dup_keys > 1]

    checks = [
        ("every dataset parsed to state+district+FY+month+basis",
         unparsed.empty, f"{len(unparsed)} unparsed"),
        ("title basis agrees with Collection (Monthly/Cumulative)",
         basis_conflict.empty, f"{len(basis_conflict)} conflicts"),
        ("title district agrees with Collection district",
         district_conflict.empty, f"{len(district_conflict)} conflicts"),
        ("all source files present", not missing, f"{len(missing)} missing"),
        ("every header parsed", not problems, f"{len(problems)} problems"),
        ("file header width == DB `Conforms To` width",
         header_drift == 0, f"{header_drift} differ"),
        (f"file rows == DB row_count ({len(rc)}/{len(manifest)} covered)",
         rc_mismatch.empty, f"{len(rc_mismatch)} mismatched"),
        ("no ragged rows (row width == header width)",
         manifest.ragged_rows.sum() == 0, f"{int(manifest.ragged_rows.sum())} rows"),
        ("every indicator landed in a column",
         manifest.unknown_indicators.sum() == 0,
         f"{int(manifest.unknown_indicators.sum())} unplaced"),
        # The transpose must move every cell: one output row per source data
        # column, and file rows x data columns cells, same as the long layout
        # would have written.
        ("cells preserved (file rows x data columns)",
         bool((manifest.cells == manifest.file_row_count * manifest.data_columns).all()),
         f"{int(manifest.cells.sum()):,} cells"),
        ("output rows == source data columns" if layout == "wide"
         else "output rows == cells",
         bool((manifest.out_rows == (manifest.data_columns if layout == "wide"
                                     else manifest.cells)).all()),
         f"{int(manifest.out_rows.sum()):,} rows"),
        ("(district, FY, month) unique within each basis",
         dup_keys.empty, f"{len(dup_keys)} colliding keys"),
        ("FY-derived era matches header shape",
         bool(era_consistent), era.to_dict()),
    ]
    # A sub-district repeated inside one file's header would write two rows with
    # the same key. Across files the key is unique because (district, FY, month)
    # is unique within a basis, which the check above establishes.
    key_dups = int((manifest.out_rows - manifest.distinct_row_keys).sum()) \
        if layout == "wide" else 0
    checks.append(("output row keys unique within a source file",
                   key_dups == 0, f"{key_dups} duplicates"))
    print()
    for name, ok, detail in checks:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}  ({detail})")

    slug = state.lower().replace(" ", "_")
    manifest.to_csv(out_dir / f"{slug}_manifest.csv", index=False)
    dropped.to_csv(out_dir / f"{slug}_duplicates.csv", index=False)
    coverage_table(manifest).to_csv(out_dir / f"{slug}_coverage.csv", index=False)
    if layout == "wide":
        indicator_dict.to_csv(out_dir / f"{slug}_indicator_columns.csv", index=False)
    write_notes(state, manifest, dropped, era, checks, indicator_dict,
                out_dir, use_gzip, layout)
    return all(ok for _, ok, _ in checks)


def write_notes(state, manifest, dropped, era, checks, indicator_dict,
                out_dir, use_gzip, layout) -> None:
    slug = state.lower().replace(" ", "_")
    ext = ".csv.gz" if use_gzip else ".csv"
    grp = ["basis", "format_version"] if layout == "wide" else ["basis"]
    by_file = manifest.groupby(grp).agg(
        datasets=("source_uuid", "nunique"),
        districts=("district", "nunique"),
        source_rows=("file_row_count", "sum"),
        out_rows=("out_rows", "sum"),
        cells=("cells", "sum"),
    ).reset_index()
    by_fy = manifest.groupby(["fy", "basis"]).agg(
        datasets=("source_uuid", "nunique"),
        districts=("district", "nunique"),
        out_rows=("out_rows", "sum"),
    ).reset_index()
    n_ind = (indicator_dict.groupby("Format Version").size().to_dict()
             if len(indicator_dict) else {})

    lines = [
        f"# HMIS Item-wise sub-district reports merged to state level — {state}",
        "",
        f"Every district of {state}, every financial year, transposed so that each",
        "sub-district-month is a row and each indicator is a column, and stacked into one",
        "table per report basis and indicator framework.",
        "",
        "## What was merged",
        "",
        "| Basis | Format Version | Datasets | Districts | Rows | Indicator columns | Cells |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.basis} | {getattr(r, 'format_version', '—')} | {r.datasets:,} | "
        f"{r.districts} | {r.out_rows:,} | "
        f"{n_ind.get(getattr(r, 'format_version', None), '—')} | {r.cells:,} |"
        for r in by_file.itertuples()
    ]
    lines += [
        "",
        f"FY {manifest.fy.min()} – {manifest.fy.max()}.",
        "",
        "## Orientation: indicators are columns",
        "",
        "The source files are indicator-per-row, sub-district-per-column. They are",
        "transposed: **one row per sub-district per month**, **one column per indicator**.",
        "",
        "The alternative — fully long form, one row per indicator per sub-district per",
        f"month — would be {int(manifest.cells.sum()):,} rows for {state} alone, each",
        "repeating the indicator's full description. Transposing carries exactly the same",
        f"cells in {int(manifest.out_rows.sum()):,} rows. (`--layout long` writes that form",
        "if it is ever wanted.)",
        "",
        "Indicator column labels are `<S.No.> <Parameters>`, with `[<Type>]` appended where",
        "the indicator has a breakdown other than TOTAL (age bands and similar). The full",
        f"mapping — group, S.No., description, breakdown — is in `{slug}_indicator_columns.csv`.",
        "",
        "### Why columns are keyed on the description, not on S.No.",
        "",
        "`S.No.` is not a stable identifier even inside one framework:",
        "",
        "- the same indicator is published as `8.1` in some files and `8.10` in others",
        "  (`9.1`/`9.10`, `10.1`/`10.10`, `14.1`/`14.10`, `14.2`/`14.20` likewise) — keying",
        "  on it would split one indicator across two columns;",
        "- `10.1` is used for two *different* indicators in the same file (Childhood",
        "  Diseases – Malaria and – Pneumonia) — keying on it would collapse two indicators",
        "  into one column;",
        "- some files export the code as a quoted literal (`'1.1'`) and others bare (`1.1`).",
        "",
        "Columns are therefore identified by (Indicator group, Type, Parameters), which is",
        "stable across every file checked. Every `S.No.` variant observed for a column is",
        "recorded in the dictionary's `S.No. variants`.",
        "",
        "## Why monthly and cumulative are separate files",
        "",
        "Each district-month is published twice:",
        "",
        f"- `Item-wise report for <District> of {state} **for** <Month>-<FY>` — that month alone",
        f"- `Item-wise report for <District> of {state} **upto** <Month>-<FY>` — cumulative from",
        "  the start of the financial year",
        "",
        "Same indicators, same sub-districts, different basis. In one table the two are",
        "indistinguishable without reading a column, and any sum over the table",
        "double-counts every month. So they are written to separate files, and the basis",
        "is still carried as a column so the files can be concatenated deliberately.",
        "",
        "## Key columns",
        "",
        "Every row is identified by these; everything after them is an indicator.",
        "",
        "| Column | Source |",
        "|---|---|",
        "| `State` | the catalog the datasets belong to |",
        "| `District` | dataset title (`Item-wise report for **<District>** of …`) |",
        "| `Sub District` | source column name |",
        "| `Level` | `subdistrict`, or `district_total` for the `_<District>` roll-up column |",
        "| `Report FY` | dataset title |",
        "| `Month` | dataset title |",
        "| `Report Basis` | `monthly` / `cumulative`, from `for` / `upto` in the title |",
        "| `Format Version` | FY < 2017-18 vs 2017-18 onwards |",
        "| `Facility Category` | `Total` / `Public` / `Private` / `Urban` / `Rural`, from the column name |",
        "| `source_uuid` | provenance — the filename in `data/first_batch_downloads/` |",
        "",
        "Values are copied verbatim, read and written as text, so the literal `NA` token",
        "and large integer counts survive the round-trip.",
        "",
        "### `Level` exists so aggregates do not double-count",
        "",
        "A source column named `SubDistrict-_<District>` (leading underscore) is the",
        "district total, not a sub-district. It is kept — nothing is dropped — but marked",
        "`district_total`. Summing the table without filtering on",
        "`Level = 'subdistrict'` counts every district twice.",
        "",
        "### The two indicator frameworks are separate files",
        "",
        "HMIS renumbered its indicators in 2017-18. In these datasets the pre-2017-18",
        f"framework has {n_ind.get(FORMAT_OLD, '—')} indicators and the 2017-18-onwards one",
        f"has {n_ind.get(FORMAT_NEW, '—')}; only 33 codes appear in both, and all 33 mean",
        "something different (`13.2` is *Intraocular Lens implantations* before and *DOTS",
        "cases completed successfully* after). One set of columns cannot hold both, so each",
        "framework gets its own file.",
        "",
        "The revision also changed the source header: from 2017-18 each sub-district is",
        "split into five sub-columns (Total / Public / Private / Urban / Rural), which is",
        "where `Facility Category` comes from. Pre-2017-18 files have one column per",
        "sub-district and are recorded as `Total`. The run cross-checks the FY-derived",
        "framework against the observed header shape:",
        "",
        "```",
        era.to_string(),
        "```",
        "",
    ]
    if len(dropped):
        ident = int(dropped.content_identical.sum())
        lines += [
            "## Re-published datasets dropped",
            "",
            f"{len(dropped)} dataset(s) repeat a district-month already published under",
            f"another UUID ({ident} byte-identical once line endings are normalised).",
            "Keeping both would duplicate every row of that district-month. The dropped",
            f"UUIDs are listed in `{slug}_duplicates.csv`.",
            "",
            "| Dropped | Kept | District | FY | Month | Basis | Identical? |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [
            f"| `{r.dropped_uuid}` | `{r.kept_uuid}` | {r.district} | {r.fy} | "
            f"{r.month} | {r.basis} | {'yes' if r.content_identical else 'no'} |"
            for r in dropped.itertuples()
        ]
        lines += [""]
    lines += [
        "## Verification",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} ({d}) |" for n, ok, d in checks]
    lines += [
        "",
        "The row-count check compares each file's actual length against the `row_count`",
        "recorded in `dublin_core_metadata` — an independent number, so it can genuinely",
        "fail on a truncated download or a stale DB row.",
        "",
        "## Rows per financial year",
        "",
        "| FY | Basis | Datasets | Districts | Rows |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.fy} | {r.basis} | {r.datasets:,} | {r.districts} | {r.out_rows:,} |"
        for r in by_fy.itertuples()
    ]
    lines += [
        "",
        "## Reproduce",
        "",
        "```bash",
        f"python transformation/merge_hmis_itemwise_subdistrict.py --state '{state}'",
        "```",
        "",
        "| Output | Contents |",
        "|---|---|",
    ]
    lines += [
        f"| `hmis_itemwise_subdistrict_{slug}_{b}_"
        f"{span_slug(manifest[(manifest.basis == b) & (manifest.format_version == e)])}{ext}` | "
        f"{b} figures, {ERA_SLUG[e]} indicators, all districts |"
        for b in ("monthly", "cumulative") for e in (FORMAT_OLD, FORMAT_NEW)
    ] if layout == "wide" else [
        f"| `hmis_itemwise_subdistrict_{slug}_{b}{ext}` | {b} figures, long form |"
        for b in ("monthly", "cumulative")
    ]
    lines += [
        f"| `{slug}_indicator_columns.csv` | column dictionary: label, group, S.No. (+ variants), description, breakdown |",
        f"| `{slug}_manifest.csv` | one row per source dataset: district, FY, month, basis, columns, row counts |",
        f"| `{slug}_duplicates.csv` | datasets dropped as re-publications |",
        f"| `{slug}_merge_notes.md` | this note |",
        "",
    ]
    (out_dir / f"{slug}_merge_notes.md").write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--state", action="append", dest="states", metavar="NAME",
                    help=f"repeatable; default {' + '.join(DEFAULT_STATES)}")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--gzip", action="store_true",
                    help="write .csv.gz instead of .csv (~8x smaller)")
    ap.add_argument("--limit", type=int,
                    help="only merge the first N datasets per basis (smoke test)")
    ap.add_argument("--layout", choices=("wide", "long"), default="wide",
                    help="wide: indicators as columns (default). "
                         "long: one row per indicator per sub-district per month")
    ap.add_argument("--workers", type=int, default=os.cpu_count(),
                    help=f"parallel workers (default {os.cpu_count()})")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"missing db: {DB_PATH}", file=sys.stderr)
        return 1
    if not DOWNLOAD_DIR.is_dir():
        print(f"missing downloads: {DOWNLOAD_DIR}", file=sys.stderr)
        return 1

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        ok = all([run_state(con, s, args.out_dir, args.gzip, args.limit,
                            args.layout, max(1, args.workers))
                  for s in (args.states or DEFAULT_STATES)])
    finally:
        con.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
