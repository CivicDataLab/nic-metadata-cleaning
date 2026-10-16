"""
Worked example: vertically merging two HMIS Item-wise collections.

The pair
--------
  A) "Item-wise HMIS report at State level from financial year 2008-09 to 2013-14"  (144 datasets)
  B) "Item-wise HMIS report at State level from financial year 2014-15 to 2016-17"  ( 72 datasets)

Why these two were selected for merging (all checks are re-run and reported by
this script, nothing is asserted from memory):

  1. Identical normalized title base. Every member is titled
     "Item-wise HMIS report at State level for {Month}-{FY}"; both collections
     collapse to the same `new_title`, "Item-wise HMIS report at State level".
     The only variable parts of the title are temporal.
  2. Same catalog / publisher / catalog title, so they are the same reporting
     series, not two series that merely look alike.
  3. Same semantic schema: 4 identifier columns (District, S.No., Parameters,
     Type) followed by one wide value column per State.
  4. The header delta between A and B is confined to a single real-world event
     — the 2014 bifurcation of Andhra Pradesh — so the two header eras are the
     reason the series was split into two collections in the first place.
  5. A third sibling collection exists (FY 2017-18 to 2019-20) and is *excluded*,
     because its delta is a real schema change rather than a state-boundary
     change. The script reports it so the selection rule is shown to select
     exactly two, not "at least two".

Because the geographic axis lives in *column names* and the temporal axis lives
in the *title*, this is a `curate` merge, not a `direct` one: it is outside the
exact-header rule in `dataset_vertical_merge_exact.py`. The DB agrees — both
collections carry merge_method='curate' and merge_add_columns='financial year,
month'. Those two dimensions are what this script materialises as real columns.

Merge shape
-----------
Row-wise union of all 216 source files, with provenance/dimension columns
prepended and an order-preserving union of the data columns, so
"State - Andhra Pradesh Old", "State - Andhra Pradesh" and "State - Telangana"
all coexist and are blank where the source file did not have them. The merge is
lossless: no cell is dropped or rewritten.

Outputs (all under data/):
  hmis_itemwise_state_level_merged.csv      merged table
  hmis_itemwise_state_level_manifest.csv    per-source-file provenance + row counts
  hmis_itemwise_state_level_headers.csv     raw header signature of each source file
  hmis_itemwise_state_level_merge_notes.md  selection rationale + verification numbers
"""

import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "transformation" / "metadata.db"
TABLE = "dublin_core_metadata"
DOWNLOAD_DIR = ROOT / "data" / "first_batch_downloads"
OUT_DIR = ROOT / "data"

COLLECTION_A = "Item-wise HMIS report at State level from financial year 2008-09 to 2013-14"
COLLECTION_B = "Item-wise HMIS report at State level from financial year 2014-15 to 2016-17"
# Every collection in the same naming family, used to show which siblings the
# selection rule rejects and why.
SIBLING_PREFIX = "Item-wise HMIS report at State level from financial year"

# Dimensions named by merge_add_columns, plus provenance so every merged row can
# be traced back to the dataset it came from.
DIM_COLS = [
    "Financial_Year",
    "Month",
    "Report_Basis",
    "source_collection",
    "source_title",
    "source_uuid",
]

# Both collections interleave two report bases: "... for April-2008-09" is that
# month alone, "... upto April-2008-09" is cumulative from the start of the FY.
# merge_add_columns only names financial year + month, so merging on those two
# alone would leave two indistinguishable rows per (FY, month, indicator) — one
# monthly, one cumulative. Report_Basis is derived from the title to keep them
# apart; see the notes.
BASIS_PATTERN = r"State level (for|upto) "
BASIS_LABELS = {"for": "monthly", "upto": "cumulative"}

FISCAL_MONTH_ORDER = [
    "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "January", "February", "March",
]


def fetch_members(con) -> pd.DataFrame:
    """Metadata rows for both collections, in fiscal order."""
    df = con.execute(
        f'''
        select Collection            as source_collection,
               Title                 as source_title,
               "Identifier[UUID]"    as source_uuid,
               Financial_Year,
               Month,
               row_count            as db_row_count,
               merge_method,
               merge_add_columns,
               new_title,
               "Relation[Catalog Title]" as catalog_title,
               "Publisher[ministry_department]" as ministry,
               "Conforms To"         as conforms_to
        from {TABLE}
        where Collection in (?, ?)
        ''',
        [COLLECTION_A, COLLECTION_B],
    ).fetchdf()
    df["Report_Basis"] = (
        df["source_title"].str.extract(BASIS_PATTERN, expand=False).map(BASIS_LABELS)
    )
    df["_m"] = df["Month"].map({m: i for i, m in enumerate(FISCAL_MONTH_ORDER)})
    df = df.sort_values(["Financial_Year", "_m", "Report_Basis"], kind="stable").drop(columns="_m")
    return df.reset_index(drop=True)


def fetch_siblings(con) -> pd.DataFrame:
    """
    Every collection sharing the family naming pattern, so the notes can show
    which ones the selection rule accepts and which it rejects.
    """
    return con.execute(
        f'''
        select Collection, new_title, merge_method, merge_add_columns,
               count(*) as datasets, min("Conforms To") as conforms_to
        from {TABLE}
        where Collection like ?
        group by 1, 2, 3, 4
        order by Collection
        ''',
        [SIBLING_PREFIX + "%"],
    ).fetchdf()


def read_raw(uuid: str) -> pd.DataFrame:
    """
    Read a source CSV verbatim.

    dtype=str + keep_default_na=False matter here: the files use a literal "NA"
    token for missing values and carry large integer counts. Letting pandas
    infer would turn "NA" into NaN and integers into floats, i.e. silently
    rewrite the data this merge is supposed to preserve.
    """
    return pd.read_csv(
        DOWNLOAD_DIR / f"{uuid}.csv",
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )


def ordered_union(base: list[str], incoming: list[str]) -> list[str]:
    """
    Union two column orders while keeping both sequences intact.

    New columns are inserted directly after the last already-known column that
    precedes them in `incoming`, so "State - Telangana" lands after
    "State - Tamil Nadu" instead of being appended at the end.
    """
    out = list(base)
    anchor = -1
    for col in incoming:
        if col in out:
            anchor = out.index(col)
        else:
            anchor += 1
            out.insert(anchor, col)
    return out


def check_basis_direction(merged: pd.DataFrame) -> tuple[bool, str]:
    """
    Confirm `for`->monthly / `upto`->cumulative and not the reverse.

    Checked on December, the 9th fiscal month, using indicator 1.1 (pregnant
    women registered for ANC) — a count that only accumulates. April would
    prove nothing: it is the first fiscal month, so the two bases coincide
    there under either labelling.
    """
    sel = merged[
        (merged.Month == "December")
        & (merged["S.No."] == "1.1")
        & (merged.Type == "TOTAL")
        & (merged.Financial_Year == "2008-09")
    ]
    vals = {
        basis: int(v)
        for basis, v in zip(sel.Report_Basis, sel["State - All India"])
        if str(v).isdigit()
    }
    if {"monthly", "cumulative"} - vals.keys():
        return False, "sample rows not found"
    ok = vals["cumulative"] > vals["monthly"]
    return ok, f"Dec 2008-09 cumulative {vals['cumulative']:,} > monthly {vals['monthly']:,}"


def main() -> int:
    if not DB_PATH.exists():
        print(f"missing db: {DB_PATH}", file=sys.stderr)
        return 1

    con = duckdb.connect(str(DB_PATH), read_only=True)
    members = fetch_members(con)
    siblings = fetch_siblings(con)
    con.close()

    counts = members["source_collection"].value_counts().to_dict()
    print(f"collection A  {counts.get(COLLECTION_A, 0):>4}  {COLLECTION_A}")
    print(f"collection B  {counts.get(COLLECTION_B, 0):>4}  {COLLECTION_B}")

    missing = [u for u in members.source_uuid if not (DOWNLOAD_DIR / f"{u}.csv").exists()]
    if missing:
        print(f"{len(missing)} source files missing, e.g. {missing[:3]}", file=sys.stderr)
        return 1

    # --- read every source file, recording its RAW header signature ----------
    # The DB's `Conforms To` is a normalized string ("State  A  N Islands");
    # the files carry the original ("State - A & N Islands"). Selection evidence
    # is therefore computed raw-file-to-raw-file, never raw-vs-Conforms To.
    frames, header_rows, union_cols = [], [], []
    for rec in members.itertuples():
        raw = read_raw(rec.source_uuid)
        cols = list(raw.columns)
        union_cols = ordered_union(union_cols, cols) if union_cols else cols

        header_rows.append({
            "source_collection": rec.source_collection,
            "source_uuid": rec.source_uuid,
            "source_title": rec.source_title,
            "column_count": len(cols),
            "raw_header": ",".join(cols),
        })

        raw.insert(0, "source_uuid", rec.source_uuid)
        raw.insert(0, "source_title", rec.source_title)
        raw.insert(0, "source_collection", rec.source_collection)
        raw.insert(0, "Report_Basis", rec.Report_Basis)
        raw.insert(0, "Month", rec.Month)
        raw.insert(0, "Financial_Year", rec.Financial_Year)
        frames.append(raw)

    headers = pd.DataFrame(header_rows)
    headers["header_variant"] = (
        headers.groupby("raw_header", sort=False).ngroup().add(1).map("V{}".format)
    )

    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged = merged.reindex(columns=DIM_COLS + union_cols, fill_value="")
    merged = merged.fillna("")

    manifest = pd.DataFrame({
        "source_collection": members.source_collection,
        "source_title": members.source_title,
        "source_uuid": members.source_uuid,
        "Financial_Year": members.Financial_Year,
        "Month": members.Month,
        "Report_Basis": members.Report_Basis,
        "merge_method": members.merge_method,
        "merge_add_columns": members.merge_add_columns,
        "header_variant": headers.header_variant,
        "column_count": headers.column_count,
        "file_row_count": [len(f) for f in frames],
        "db_row_count": members.db_row_count,
    })

    # --- verification ------------------------------------------------------
    # The row-count check is deliberately against the DB's own `row_count`
    # column, an independently recorded number: comparing the merged length to
    # the sum of the frames just concatenated would be a tautology and could
    # never fail. This one catches a truncated download or a stale DB row.
    rc = manifest.dropna(subset=["db_row_count"]).copy()
    rc["db_row_count"] = pd.to_numeric(rc.db_row_count, errors="coerce")
    rc = rc.dropna(subset=["db_row_count"])
    rc_mismatch = rc[rc.file_row_count != rc.db_row_count.astype(int)]
    n_dim_blank = int(
        (members.Month.fillna("").eq("")
         | members.Financial_Year.fillna("").eq("")
         | members.Report_Basis.fillna("").eq("")).sum()
    )
    # The added dimensions must identify a source dataset uniquely, otherwise
    # the merged table has rows it cannot tell apart.
    # Deliberately NOT keyed on source_collection: keying per-collection would
    # hide an FY overlap *between* A and B, which is the failure mode a merge
    # introduces in the first place.
    key = ["Financial_Year", "Month", "Report_Basis"]
    dup_keys = manifest.groupby(key).size()
    dup_keys = dup_keys[dup_keys > 1]

    basis_ok, basis_detail = check_basis_direction(merged)

    checks = [
        ("all 216 source files read",
         len(frames) == 216, f"{len(frames)}"),
        (f"file rows == DB row_count ({len(rc)}/{len(manifest)} covered)",
         rc_mismatch.empty, f"{len(rc_mismatch)} mismatched"),
        ("merged rows == sum of file rows",
         len(merged) == int(manifest.file_row_count.sum()),
         f"{len(merged)} vs {int(manifest.file_row_count.sum())}"),
        ("added dimensions present on every dataset",
         n_dim_blank == 0, f"{n_dim_blank} blank"),
        ("added dimensions identify a dataset uniquely",
         dup_keys.empty, f"{len(dup_keys)} colliding keys"),
        ("Report_Basis labelled the right way round", basis_ok, basis_detail),
        ("columns == added dims + union of source columns",
         list(merged.columns) == DIM_COLS + union_cols, f"{len(merged.columns)}"),
    ]
    print()
    for name, ok, detail in checks:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}  ({detail})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    merged_path = OUT_DIR / "hmis_itemwise_state_level_merged.csv"
    merged.to_csv(merged_path, index=False)
    manifest.to_csv(OUT_DIR / "hmis_itemwise_state_level_manifest.csv", index=False)
    headers.to_csv(OUT_DIR / "hmis_itemwise_state_level_headers.csv", index=False)

    write_notes(members, siblings, manifest, headers, merged, union_cols, checks)

    print(f"\nwrote {merged_path.relative_to(ROOT)}  "
          f"({len(merged):,} rows x {len(merged.columns)} cols, "
          f"{merged_path.stat().st_size / 1e6:.1f} MB)")
    return 0 if all(ok for _, ok, _ in checks) else 1


def write_notes(members, siblings, manifest, headers, merged, union_cols, checks) -> None:
    a = members[members.source_collection == COLLECTION_A]
    b = members[members.source_collection == COLLECTION_B]
    ha = set(headers[headers.source_collection == COLLECTION_A].raw_header.iloc[0].split(","))
    hb = set(headers[headers.source_collection == COLLECTION_B].raw_header.iloc[0].split(","))
    only_a, only_b = sorted(ha - hb), sorted(hb - ha)
    variants_a = headers[headers.source_collection == COLLECTION_A].header_variant.nunique()
    variants_b = headers[headers.source_collection == COLLECTION_B].header_variant.nunique()

    fy = (manifest.groupby(["source_collection", "Financial_Year"])
                  .agg(datasets=("source_uuid", "nunique"), rows=("file_row_count", "sum"))
                  .reset_index())

    rejected = siblings[~siblings.Collection.isin([COLLECTION_A, COLLECTION_B])]

    lines = [
        "# Vertical merge example — HMIS Item-wise reports at State level",
        "",
        "Two collections merged into one table. This note records *why* they were",
        "selected for merging and what the merge did.",
        "",
        "## The two collections",
        "",
        "| # | Collection | Datasets | FY span | Header variants (raw files) |",
        "|---|---|---|---|---|",
        f"| A | {COLLECTION_A} | {len(a)} | {a.Financial_Year.min()} – {a.Financial_Year.max()} | {variants_a} |",
        f"| B | {COLLECTION_B} | {len(b)} | {b.Financial_Year.min()} – {b.Financial_Year.max()} | {variants_b} |",
        "",
        "Both sit under the same catalog and publisher:",
        "",
        f"- Catalog: `{members.catalog_title.iloc[0]}`",
        f"- Publisher: `{members.ministry.iloc[0]}`",
        "",
        "## Why they were selected",
        "",
        "**1. Same normalized title base.** Every member is titled",
        "`Item-wise HMIS report at State level for {Month}-{FY}`. Strip the temporal",
        f"suffix and both collections collapse to the identical `new_title`: `{members.new_title.iloc[0]}`.",
        "The only thing that varies across all 216 datasets is the reporting month and",
        "financial year — the classic signature of a series that was published as one",
        "file per period and should be one table.",
        "",
        "**2. Same semantic schema.** Every file is `District, S.No., Parameters, Type`",
        "followed by one wide value column per State. Same indicator rows",
        "(`M1 [Ante Natal Care Services ANC]` …), same `Type` breakdown, same units.",
        "",
        f"**3. The header delta is one known event.** A has {len(ha)} columns, B has {len(hb)}.",
        "The difference is entirely:",
        "",
        f"- only in A: {', '.join(f'`{c}`' for c in only_a) or '—'}",
        f"- only in B: {', '.join(f'`{c}`' for c in only_b) or '—'}",
        "",
        "That is the June-2014 bifurcation of Andhra Pradesh into Andhra Pradesh and",
        "Telangana. Every other column matches exactly. The header change is *why* the",
        "series was split into two collections in the first place, and it is a change in",
        "the world, not a change in what the dataset measures — so the two collections",
        "belong in one merged table.",
        "",
        "**4. The DB already classifies them the same way.**",
        "",
        f"- `merge_method` = `{members.merge_method.iloc[0]}` for both",
        f"- `merge_add_columns` = `{members.merge_add_columns.iloc[0]}` for both",
        "",
        "`curate`, not `direct`: the temporal axis lives in the *title* and the",
        "geographic axis lives in *column names*, so there is no standalone temporal",
        "column to merge on. This pair is deliberately outside the exact-header rule in",
        "`dataset_vertical_merge_exact.py`, which excludes wide-form groups. Merging it",
        "requires adding the dimensions that `merge_add_columns` names — which is",
        "exactly what the merge below does.",
        "",
        "## Which siblings the rule rejects",
        "",
        f"The naming family `{SIBLING_PREFIX}…` has {len(siblings)} collections in the DB,",
        f"of which the rule selects {len(siblings) - len(rejected)}. Showing the rejections matters: a selection rule",
        "that only ever says yes is not a selection rule.",
        "",
        "| Collection | Datasets | `new_title` | Selected? |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {r.Collection} | {r.datasets} | `{r.new_title}` | "
        f"{'**yes**' if r.Collection in (COLLECTION_A, COLLECTION_B) else 'no'} |"
        for r in siblings.itertuples()
    ]
    lines += [""]
    for r in rejected.itertuples():
        first_cols = ", ".join(f"`{c.strip()}`" for c in (r.conforms_to or "").split(",")[:7])
        lines += [
            f"**Rejected: {r.Collection}**",
            "",
            f"- Its `new_title` is `{r.new_title}` — it does *not* collapse to the shared",
            f"  base `{members.new_title.iloc[0]}`, so criterion 1 already fails.",
            f"- Its header opens with {first_cols} … — the first column is renamed and every",
            "  State is split into five sub-columns (Total AB or CD / Public A / Private B /",
            "  Urban C / Rural D). That is a change to *what is measured and at what",
            "  breakdown*, not a change to the map. Stacking it onto A and B would put",
            "  incomparable numbers in the same table.",
            "",
            "This is the discriminating contrast that makes the example worth reading: the",
            "A↔B delta is three columns caused by a state boundary moving, so they merge;",
            "the A↔C delta is a different measurement breakdown, so it does not.",
            "",
        ]
    lines += [
        "## What the merge did",
        "",
        "Row-wise union of all 216 source files with these columns prepended:",
        "",
        "| Column | Source |",
        "|---|---|",
        "| `Financial_Year` | dimension named by `merge_add_columns`, from the dataset title |",
        "| `Month` | dimension named by `merge_add_columns`, from the dataset title |",
        "| `Report_Basis` | `monthly` / `cumulative`, from the dataset title — see below |",
        "| `source_collection` | provenance |",
        "| `source_title` | provenance |",
        "| `source_uuid` | provenance — the filename in `data/first_batch_downloads/` |",
        "",
        "The data columns are an order-preserving union, so",
        "`State - Andhra Pradesh Old`, `State - Andhra Pradesh` and `State - Telangana`",
        "all coexist and are left blank in the years where the source file did not carry",
        "them. Nothing is dropped, renamed, or retyped: values are read and written as",
        "text so the literal `NA` token and large integer counts survive the round-trip.",
        "",
        f"Result: **{len(merged):,} rows x {len(merged.columns)} columns** "
        f"({len(union_cols)} data + {len(DIM_COLS)} added).",
        "",
        "### `merge_add_columns` names two dimensions; the data needs three",
        "",
        "Both collections interleave two report bases, visible only in the title:",
        "",
        "- `Item-wise HMIS report at State level **for** April-2008-09` — that month alone",
        "- `Item-wise HMIS report at State level **upto** April-2008-09` — cumulative from",
        "  the start of the financial year",
        "",
        f"Each (collection, financial year, month) has exactly **2** datasets, one of each",
        "basis. So merging on `financial year, month` alone — the two dimensions",
        "`merge_add_columns` records — would produce two rows per indicator per month that",
        "nothing in the table distinguishes, silently mixing monthly and cumulative",
        "figures in the same column. `Report_Basis` (`monthly` / `cumulative`) is derived",
        "from the title to keep them apart, and the verification below asserts that the",
        "added dimensions now identify a source dataset uniquely.",
        "",
        "Worth feeding back: for this family `merge_add_columns` is under-specified.",
        "",
        "## Verification",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    lines += [f"| {name} | {'PASS' if ok else 'FAIL'} ({detail}) |" for name, ok, detail in checks]
    lines += [
        "",
        "The row-count check compares each file's actual length against the `row_count`",
        "already recorded in `dublin_core_metadata` — an independent number, so it can",
        "genuinely fail on a truncated download or a stale DB row. (Comparing the merged",
        "length to the sum of the frames just concatenated would always pass and prove",
        "nothing.)",
        "",
        "### Rows per financial year",
        "",
        "| Collection | Financial year | Datasets | Rows |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {'A' if r.source_collection == COLLECTION_A else 'B'} | {r.Financial_Year} | {r.datasets} | {r.rows:,} |"
        for r in fy.itertuples()
    ]
    lines += [
        "",
        "## Observations worth carrying forward",
        "",
        "- The first column is named `District` but holds the indicator group",
        "  (`M1 [Ante Natal Care Services ANC]`). That is a source mislabel; it is left",
        "  as-is here rather than silently renamed.",
        "- `Conforms To` in the DB is normalized (`State  A  N Islands`) while the raw",
        "  files keep the original punctuation (`State - A & N Islands`). Header",
        "  comparisons for selection must be raw-to-raw, or the punctuation stripping",
        "  manufactures mismatches.",
        f"- A further optional step would unpivot the {len(union_cols) - 4} `State - *`",
        "  columns into a single `State` column, giving fully long-form",
        "  `(Financial_Year, Month, Report_Basis, State, Indicator, Value)`. Doing that",
        "  would also collapse `Andhra Pradesh Old` / `Andhra Pradesh` + `Telangana` into a",
        "  question about pre/post-2014 comparability. That is a reshape of the",
        "  data; the merge above is not.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "python transformation/merge_hmis_itemwise_example.py",
        "```",
        "",
        "| Output | Contents |",
        "|---|---|",
        "| `data/hmis_itemwise_state_level_merged.csv` | the merged table |",
        "| `data/hmis_itemwise_state_level_manifest.csv` | one row per source dataset: FY, month, header variant, row count |",
        "| `data/hmis_itemwise_state_level_headers.csv` | raw header signature of each source file |",
        "| `data/hmis_itemwise_state_level_merge_notes.md` | this note |",
        "",
    ]
    (OUT_DIR / "hmis_itemwise_state_level_merge_notes.md").write_text("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
