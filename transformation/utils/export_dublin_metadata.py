"""
Export the dublin_core_metadata table to an .xlsx file.

A set of internal / housekeeping columns are dropped from the export (they are
pipeline bookkeeping, not part of the published Dublin Core metadata).

A priority set of columns is moved to the front of the sheet, and their
header cells are highlighted yellow.

The keyword / sponsored keyword / description / abstract columns are replaced
with the LLM-regenerated values from data/keywords/keyword_gen_2_L.xlsx, joined
on nid. The replacement is wholesale: where the override sheet has a blank, the
exported cell is blank too. Rows with no matching nid in the sheet keep their
database values. Pass --no-overrides to export the table as-is.

The worksheet XML is generated in parallel across all CPU cores (an .xlsx is
a zip archive of XML parts), which is far faster than openpyxl for a table
of this size.

--dcat exports the `dcat_metadata` view instead: identical rows, with the columns
renamed to their DCAT v3 terms. Build it first with
transformation/build_dcat_mapping.py. Under --dcat, --where and --sheet-by take
the DCAT column names.

--table exports any other table in the database (lot3_raw, say).
There nothing is dropped by default -- the merge bookkeeping is the point of that
export, and --exclude is the only way to drop columns there --
the merge columns lead the sheet (TABLE_PRIORITY_COLUMNS, or --priority), and the
keyword overrides are off, since they are keyed to dublin_core_metadata's nids.

--table dublin_core_remaining and --table dublin_core_lot3 are exported in
dublin_core_metadata's arrangement instead, so all three lots read the same: the
same yellow PRIORITY_COLUMNS lead, the columns a lot shares with
dublin_core_metadata follow in that sheet's order, and the lot's own columns come
last (LOT_EXTRA_ORDER). The pipeline columns in LOT_EXCLUDE_COLUMNS (the same
set for both lots) stay in the table but are left out of the sheet. The overrides
stay off.

Usage:
  python export_dublin_metadata.py
  python export_dublin_metadata.py --dcat
  python export_dublin_metadata.py --table dublin_core_remaining
  python export_dublin_metadata.py --table dublin_core_lot3
  python export_dublin_metadata.py --output /path/to/dublin_core_metadata.xlsx
  python export_dublin_metadata.py --where "merge_method = 'curate'" \
      --sheet-by merge_add_columns --output curate_split.xlsx

--where filters rows with a raw SQL predicate; --sheet-by writes one worksheet
per distinct value of the given column instead of a single Sheet1.
"""

import argparse
import datetime
import math
import os
import re
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor
from xml.sax.saxutils import escape

import duckdb
import pandas as pd

# Paths resolve from this file (transformation/utils/), so the script runs from
# any checkout of the repo.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(REPO, "transformation", "metadata.db")
TABLE = "dublin_core_metadata"
DEFAULT_OUTPUT = os.path.join(REPO, "dublin_core_metadata.xlsx")

# Regenerated content columns, joined on nid and substituted into the export.
DEFAULT_OVERRIDES = os.path.join(REPO, "data", "keywords", "keyword_gen_2_L.xlsx")
OVERRIDES_SHEET = "Sheet1"
OVERRIDES_KEY = "nid"
# table column -> column in the overrides sheet
OVERRIDE_COLUMNS = {
    "Subject[keyword]": "generated_keywords",
    "Subject[sponsored_keyword]": "sponsored keywords",
    "Description": "Description",
    "Abstract": "Abstract",
}

# --dcat exports the DCAT-renamed view instead. Same rows, same content: only the
# column names differ, so the override and priority sets are restated under the
# DCAT terms. Built by transformation/build_dcat_mapping.py; `nid` is unrenamed
# and still carries the override join.
DCAT_TABLE = "dcat_metadata"
DCAT_DEFAULT_OUTPUT = os.path.join(REPO, "dcat_metadata.xlsx")
DCAT_OVERRIDE_COLUMNS = {
    "dcat:keyword": "generated_keywords",
    "dcat:keyword[sponsored]": "sponsored keywords",
    "dcterms:description": "Description",
    "dcterms:abstract": "Abstract",
}

# Columns to exclude from the export (internal pipeline bookkeeping).
EXCLUDE_COLUMNS = [
    "exact_merge_group_id",
    "exact_merge_group_name",
    "file_present",
    "metadata_enhanced",
    "dataset_merge",
    "needs_review",
    "fiscal_year"
]

# Columns to bring to the front of the sheet (in this order), with yellow headers.
PRIORITY_COLUMNS = [
    "Title",
    "description",
    "Abstract",
    "Subject[keyword]",
    "Subject[sponsored_keyword]",
    "Conforms To",
    "Collection",
    "new_title",
    "new_unmerged_dataset_title",
    "merge_method",
    "merge_add_columns",
]

DCAT_PRIORITY_COLUMNS = [
    "dcterms:title",
    "dcterms:description",
    "dcterms:abstract",
    "dcat:keyword",
    "dcat:keyword[sponsored]",
    "dcterms:conformsTo",
    "Collection",
    "new_title",
    "new_unmerged_dataset_title",
    "merge_method",
    "merge_add_columns",
]

# --table exports any other table (dublin_core_remaining, say) with nothing
# dropped: there the merge bookkeeping IS the point of the export, so the
# merge columns lead, followed by the headers that justify each decision.
TABLE_PRIORITY_COLUMNS = [
    "nid",
    "Title",
    "merge_method",
    "Collection",
    "merge_add_columns",
    "needs_review",
    "exact_merge_group_name",
    "exact_merge_group_id",
    "dataset_merge",
    "headers_cleaned",
    "header_count",
    "Conforms To",
]

# dublin_core_remaining is exported like dublin_core_metadata: the same
# PRIORITY_COLUMNS lead with yellow headers, and these pipeline columns stay in
# the table but are left out of the sheet -- the column set the user settled on
# 2026-09-25.
REMAINING_TABLE = "dublin_core_remaining"
REMAINING_EXCLUDE_COLUMNS = [
    "source_file",
    "data_time_period_from",
    "data_time_period_to",
    "batch",
    "dataset_merge",
    "exact_merge_group_name",
    "needs_review",
    "exact_merge_group_id",
    "archive",
]

# The other Dublin Core lots are exported in dublin_core_metadata's arrangement:
# the same yellow PRIORITY_COLUMNS lead, the columns a lot shares with
# dublin_core_metadata follow in that sheet's order, and the lot's own columns
# come last in LOT_EXTRA_ORDER. Each lot maps to the pipeline columns that stay
# in its table but are left out of its sheet -- lot 3 leaves out the same ones
# as dublin_core_remaining (it has five of them), as the user asked 2026-10-05.
LOT3_TABLE = "dublin_core_lot3"
# dcat_remaining / dcat_lot3 (build_dcat_mapping.py) are the same lots under DCAT
# names: same excluded pipeline columns, DCAT_PRIORITY_COLUMNS lead, and the
# arrangement follows dcat_metadata.
DCAT_LOT_TABLES = ("dcat_remaining", "dcat_lot3")
LOT_EXCLUDE_COLUMNS = {
    REMAINING_TABLE: REMAINING_EXCLUDE_COLUMNS,
    LOT3_TABLE: REMAINING_EXCLUDE_COLUMNS,
    **{t: REMAINING_EXCLUDE_COLUMNS for t in DCAT_LOT_TABLES},
}

# A lot column that is a dublin_core_metadata column under another name takes
# that column's place in the sheet. Names differing only in case (year / Year)
# match without an entry.
LOT_COLUMN_ALIASES = {
    "Remark": "Remark for change in header",
}

# Columns dublin_core_metadata does not have, in the order they follow its
# columns. One missing from this list goes last, in table order.
LOT_EXTRA_ORDER = [
    "Subject[keyword_fullform]",
    "dcat:keyword[fullform]",
    "state",
    "cdo_name",
    "cdo_email",
    "vcard:fn",
    "vcard:hasEmail",
    "dcat:startDate",
    "dcat:endDate",
    "till_date",
    "data_time_period_from",
    "data_time_period_to",
    "temporal_source",
    "temporal_check",
    "spatial_coverage",
    "spatial_states",
    "spatial_districts",
    "spatial_subdistricts",
    "spatial_level",
    "spatial_source",
    "file_present",
    "source_file",
    "needs_review",
    "dataset_merge",
    "exact_merge_group_name",
    "exact_merge_group_id",
]

_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Excel's per-cell character limit. A longer inline string makes Excel/WPS
# report the workbook as damaged, so it is cut to fit with a trailing "...".
# dublin_core_remaining has a handful of "Conforms To" header lists over it.
CELL_LIMIT = 32767

# A nullable-dtype column (Int64, boolean) hands back pandas' own NA singletons
# rather than None or NaN. They are not caught by the None or the float-NaN
# branch below, so without this they get str()'d into a literal "<NA>" cell --
# 171,409 of them in the dublin_core_remaining export. Identity checks against
# the singletons keep the per-cell cost flat.
_PD_NA = pd.NA
_PD_NAT = pd.NaT


# Set in the parent before the worker pool forks; workers read it directly
# from the inherited address space instead of pickling row chunks.
_VALUES = None


def _cell_xml(v):
    if v is None or v is _PD_NA or v is _PD_NAT:
        return "<c/>"
    if isinstance(v, bool):
        return f'<c t="b"><v>{1 if v else 0}</v></c>'
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return "<c/>"
        return f"<c t=\"n\"><v>{v}</v></c>"
    if isinstance(v, (datetime.datetime, datetime.date)):
        v = v.isoformat()
    else:
        v = str(v)
        if v != v:  # NaN that slipped through as object
            return "<c/>"
    v = _ILLEGAL_XML.sub("", v)
    if len(v) > CELL_LIMIT:
        v = v[:CELL_LIMIT - 3] + "..."
    v = escape(v)
    return f'<c t="inlineStr"><is><t xml:space="preserve">{v}</t></is></c>'


def _write_rows_chunk(args):
    start, stop, path = args
    with open(path, "w", encoding="utf-8") as f:
        for i in range(start, stop):
            f.write("<row>" + "".join(_cell_xml(v) for v in _VALUES[i]) + "</row>")
    return path


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# --- minimal xlsx package parts -------------------------------------------

def _content_types(nsheets: int) -> str:
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, nsheets + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f"{overrides}"
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )


_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)


def _workbook(sheet_names) -> str:
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(sheet_names, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets>"
        "</workbook>"
    )


def _workbook_rels(nsheets: int) -> str:
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, nsheets + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{rels}"
        f'<Relationship Id="rId{nsheets + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )


def _sheet_name(raw, used) -> str:
    """Excel-safe worksheet name: <=31 chars, no []:*?/\\ , unique."""
    name = "NULL" if raw is None else str(raw).strip() or "NULL"
    name = re.sub(r"[\[\]:*?/\\]", "-", name)[:31]
    base, i = name, 2
    while name.lower() in used:
        suffix = f"_{i}"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(name.lower())
    return name

# Style index 1 = yellow solid fill (for priority column headers).
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="3">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFFF00"/><bgColor indexed="64"/></patternFill></fill>'
    "</fills>"
    '<borders count="1"><border/></borders>'
    # The xf entries are fully attributed: stricter readers (duckdb's read_xlsx,
    # openpyxl) reject the bare <xf/> shorthand that Excel itself tolerates.
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="0" fillId="2" borderId="0" xfId="0" applyFill="1"/>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def _load_overrides(con, path: str, override_columns: dict = None) -> dict:
    """Read the overrides sheet into temp table `_overrides`.

    Returns the {table column -> overrides column} map restricted to the
    columns actually present in the sheet. nids are stored as text with any
    trailing ".0" from Excel's numeric coercion stripped, so they join against
    the table's VARCHAR nid.
    """
    override_columns = override_columns or OVERRIDE_COLUMNS
    con.execute("INSTALL excel")
    con.execute("LOAD excel")

    reader = (
        f"read_xlsx('{path}', sheet='{OVERRIDES_SHEET}', all_varchar=true)"
    )
    available = {
        row[0].lower() for row in con.execute(f"DESCRIBE SELECT * FROM {reader}").fetchall()
    }
    if OVERRIDES_KEY.lower() not in available:
        raise SystemExit(f"Overrides sheet has no {OVERRIDES_KEY!r} column: {path}")

    mapping = {t: s for t, s in override_columns.items() if s.lower() in available}
    missing = [s for s in override_columns.values() if s.lower() not in available]
    if missing:
        print(f"Warning: overrides sheet is missing column(s), leaving them as-is: {missing}")
    if not mapping:
        raise SystemExit(f"None of the override columns were found in {path}")

    cols = ", ".join(f'"{s}" AS "ovr_{t}"' for t, s in mapping.items())
    con.execute(
        f"""
        CREATE TEMP TABLE _overrides AS
        SELECT regexp_replace("{OVERRIDES_KEY}", '\\.0+$', '') AS nid, {cols}
        FROM {reader}
        """
    )
    n, distinct = con.execute(
        "SELECT count(*), count(DISTINCT nid) FROM _overrides"
    ).fetchone()
    if n != distinct:
        raise SystemExit(
            f"Overrides sheet has duplicate nids ({n} rows, {distinct} distinct) - "
            "the join would multiply rows."
        )
    print(f"Loaded {n} override row(s) from {path} for column(s): {list(mapping)}")
    return mapping


def _lot_arrangement(rest: list, reference: list) -> list:
    """Order a lot's non-priority columns the way dublin_core_metadata's sheet has them."""
    ref_pos = {c.lower(): i for i, c in enumerate(reference)}
    extra_pos = {c.lower(): i for i, c in enumerate(LOT_EXTRA_ORDER)}

    def key(item):
        i, c = item
        name = LOT_COLUMN_ALIASES.get(c, c).lower()
        if name in ref_pos:
            return (0, ref_pos[name])
        return (1, extra_pos[c.lower()]) if c.lower() in extra_pos else (2, i)

    return [c for _, c in sorted(enumerate(rest), key=key)]


def main(
    output: str = None,
    sheet_by: str = None,
    where: str = None,
    overrides: str = DEFAULT_OVERRIDES,
    dcat: bool = False,
    table: str = None,
    priority: str = None,
    exclude_columns: str = None,
) -> None:
    global _VALUES

    custom = table is not None
    if custom and dcat:
        raise SystemExit("--table and --dcat are mutually exclusive.")
    lot = table in LOT_EXCLUDE_COLUMNS
    table = table or (DCAT_TABLE if dcat else TABLE)
    override_columns = DCAT_OVERRIDE_COLUMNS if dcat else OVERRIDE_COLUMNS
    dcat_lot = table in DCAT_LOT_TABLES
    priority_columns = (DCAT_PRIORITY_COLUMNS if dcat_lot else
                        PRIORITY_COLUMNS if lot else
                        TABLE_PRIORITY_COLUMNS if custom else
                        DCAT_PRIORITY_COLUMNS if dcat else PRIORITY_COLUMNS)
    if priority:
        priority_columns = [c.strip() for c in priority.split(",") if c.strip()]
    if output is None:
        output = (os.path.join(os.path.dirname(DEFAULT_OUTPUT), f"{table}.xlsx") if custom
                  else DCAT_DEFAULT_OUTPUT if dcat else DEFAULT_OUTPUT)

    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        if dcat and not con.execute(
            "SELECT count(*) FROM duckdb_views() WHERE view_name = ?", [DCAT_TABLE]
        ).fetchone()[0] and not con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [DCAT_TABLE]
        ).fetchone()[0]:
            raise SystemExit(
                f"{DCAT_TABLE} not found. Build it first: "
                "python transformation/build_dcat_mapping.py"
            )
        if custom and not con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [table]
        ).fetchone()[0] and not con.execute(
            "SELECT count(*) FROM duckdb_views() WHERE view_name = ?", [table]
        ).fetchone()[0]:
            raise SystemExit(f"Table not found: {table}")
        print(f"Exporting {table}")
        all_cols = [row[1] for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()]
        # Under --table nothing is dropped: the bookkeeping columns are the
        # reason for that export. The Dublin Core lots have their own sets.
        exclude = ({c.lower() for c in LOT_EXCLUDE_COLUMNS[table]} if lot else
                   set() if custom else {c.lower() for c in EXCLUDE_COLUMNS})
        # A lot's sheet follows dublin_core_metadata's column order.
        reference = [row[1] for row in con.execute(
            f'PRAGMA table_info("{DCAT_TABLE if dcat_lot else TABLE}")').fetchall()] if lot else None
        # --exclude drops further columns; the only way to drop anything at all
        # under --table.
        if exclude_columns:
            exclude |= {c.strip().lower() for c in exclude_columns.split(",") if c.strip()}
        keep = [c for c in all_cols if c.lower() not in exclude]

        dropped = [c for c in all_cols if c.lower() in exclude]
        print(f"Dropping {len(dropped)} column(s): {dropped}")
        print(f"Keeping {len(keep)} column(s).")

        override_map = {}
        if overrides:
            if not os.path.exists(overrides):
                raise SystemExit(f"Overrides file not found: {overrides}")
            if "nid" not in {c.lower() for c in keep}:
                raise SystemExit("Cannot apply overrides: exported columns have no nid to join on.")
            override_map = _load_overrides(con, overrides, override_columns)

        # A row present in the overrides sheet takes that sheet's values
        # verbatim, blanks included; a row absent from it keeps the table's.
        by_lower = {t.lower(): t for t in override_map}
        select = ", ".join(
            f'CASE WHEN o.nid IS NULL THEN d."{c}" ELSE o."ovr_{by_lower[c.lower()]}" END AS "{c}"'
            if c.lower() in by_lower
            else f'd."{c}"'
            for c in keep
        )
        join = " LEFT JOIN _overrides o ON d.nid = o.nid" if override_map else ""
        # The predicate is applied outside the join so it only ever sees the
        # flat, single-table column set.
        query = f"WITH base AS (SELECT {select} FROM {table} d{join}) SELECT * FROM base"
        if where:
            query += f" WHERE {where}"

        if override_map:
            matched = con.execute(
                f"SELECT count(*) FROM {table} d JOIN _overrides o ON d.nid = o.nid"
            ).fetchone()[0]
            total = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(
                f"Overrides matched {matched}/{total} table row(s); "
                f"{total - matched} row(s) keep their database values."
            )

        df = con.execute(query).fetchdf()
    finally:
        con.close()

    if sheet_by:
        match = {c.lower(): c for c in df.columns}.get(sheet_by.lower())
        if match is None:
            raise SystemExit(f"--sheet-by column {sheet_by!r} not found in export columns.")
        sheet_by = match
        # Stable sort so each sheet's rows form one contiguous block.
        df = df.sort_values(by=sheet_by, na_position="last", kind="stable").reset_index(drop=True)

    # Reorder: priority columns first (only those that actually exist), then the rest.
    keep_lower = {c.lower(): c for c in df.columns}
    front = [keep_lower[c.lower()] for c in priority_columns if c.lower() in keep_lower]
    missing_priority = [c for c in priority_columns if c.lower() not in keep_lower]
    if missing_priority:
        print(f"Warning: priority column(s) not found in table, skipping: {missing_priority}")

    rest = [c for c in df.columns if c not in front]
    if lot:
        rest = _lot_arrangement(rest, reference)
    df = df[front + rest]

    columns = list(df.columns)
    nrows, ncols = df.shape
    too_long = {c: int(n) for c in df.columns if df[c].dtype == object
                and (n := df[c].map(lambda v: isinstance(v, str) and len(v) > CELL_LIMIT).sum())}
    if too_long:
        print(f"Note: cells over Excel's {CELL_LIMIT}-char limit are truncated: {too_long}")
    _VALUES = df.to_numpy(dtype=object)

    # Header row: priority columns get style 1 (yellow fill).
    header_cells = []
    for j, name in enumerate(columns):
        style = ' s="1"' if name in front else ""
        text = escape(_ILLEGAL_XML.sub("", str(name)))
        header_cells.append(
            f'<c{style} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'
        )
    header_row = "<row>" + "".join(header_cells) + "</row>"

    # Sheets as contiguous row ranges: one per distinct sheet_by value, or a
    # single Sheet1 spanning everything.
    if sheet_by:
        import pandas as pd

        col_values = df[sheet_by].tolist()
        groups = []  # (name, start, stop)
        used_names = set()
        start = 0
        for i in range(1, nrows + 1):
            boundary = i == nrows or (
                (col_values[i] != col_values[start])
                and not (pd.isna(col_values[i]) and pd.isna(col_values[start]))
            )
            if boundary:
                raw = col_values[start]
                groups.append((_sheet_name(None if pd.isna(raw) else raw, used_names), start, i))
                start = i
    else:
        groups = [("Sheet1", 0, nrows)]

    # Generate data-row XML in parallel, one temp file per chunk, never
    # crossing a sheet boundary.
    workers = max(1, os.cpu_count() or 1)
    chunk = max(1, -(-nrows // workers))
    with tempfile.TemporaryDirectory() as tmpdir:
        jobs = []
        sheet_chunks = []  # per sheet, ordered list of chunk file paths
        for si, (_, gstart, gstop) in enumerate(groups):
            paths = []
            for start in range(gstart, gstop, chunk):
                path = os.path.join(tmpdir, f"rows_{si}_{start}.xml")
                jobs.append((start, min(start + chunk, gstop), path))
                paths.append(path)
            sheet_chunks.append(paths)

        print(f"Serializing {nrows} rows into {len(groups)} sheet(s) on {workers} core(s)...")
        with ProcessPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_write_rows_chunk, jobs))

        out_dir = os.path.dirname(os.path.abspath(output))
        os.makedirs(out_dir, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            zf.writestr("[Content_Types].xml", _content_types(len(groups)))
            zf.writestr("_rels/.rels", _ROOT_RELS)
            zf.writestr("xl/workbook.xml", _workbook([g[0] for g in groups]))
            zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(groups)))
            zf.writestr("xl/styles.xml", _STYLES)
            for si, (name, gstart, gstop) in enumerate(groups, 1):
                dimension = f"A1:{_col_letter(ncols)}{gstop - gstart + 1}"
                with zf.open(f"xl/worksheets/sheet{si}.xml", "w") as sheet:
                    sheet.write(
                        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    )
                    sheet.write(f'<dimension ref="{dimension}"/><sheetData>'.encode())
                    sheet.write(header_row.encode("utf-8"))
                    for path in sheet_chunks[si - 1]:
                        with open(path, "rb") as f:
                            while True:
                                block = f.read(1 << 22)
                                if not block:
                                    break
                                sheet.write(block)
                    sheet.write(b"</sheetData></worksheet>")

    print(f"Wrote {nrows} rows x {ncols} columns to {output}")
    for name, gstart, gstop in groups:
        print(f"  sheet {name!r}: {gstop - gstart} rows")
    print(f"Highlighted {len(front)} header cell(s) yellow: {front}")
    return columns


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export dublin_core_metadata (or the DCAT-renamed view) to xlsx."
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output .xlsx path. Defaults to dublin_core_metadata.xlsx, or "
             "dcat_metadata.xlsx under --dcat.",
    )
    parser.add_argument(
        "--dcat",
        action="store_true",
        help=f"Export {DCAT_TABLE} (DCAT v3 column names) instead of {TABLE}.",
    )
    parser.add_argument(
        "--table",
        default=None,
        help="Export another table (e.g. lot3_raw) with every column kept and the "
             "merge columns in front; dublin_core_remaining and dublin_core_lot3 get "
             "the dublin_core_metadata arrangement and highlights. Implies --no-overrides.",
    )
    parser.add_argument(
        "--priority",
        default=None,
        help="Comma-separated column names to move to the front (overrides the default set).",
    )
    parser.add_argument(
        "--exclude",
        default=None,
        help="Comma-separated column names to drop from the export, in addition to "
             "the default set (and the only way to drop columns under --table).",
    )
    parser.add_argument(
        "--where",
        default=None,
        help="SQL predicate to filter rows, e.g. \"merge_method = 'curate'\".",
    )
    parser.add_argument(
        "--sheet-by",
        default=None,
        help="Column name: write one worksheet per distinct value instead of a single sheet.",
    )
    parser.add_argument(
        "--overrides",
        default=DEFAULT_OVERRIDES,
        help="xlsx of regenerated keyword/description/abstract values, joined on nid.",
    )
    parser.add_argument(
        "--no-overrides",
        dest="overrides",
        action="store_const",
        const=None,
        help="Export the table as-is, without substituting the regenerated columns.",
    )
    args = parser.parse_args()
    # The overrides sheet is keyed to dublin_core_metadata's nids; it has no
    # meaning for another table, so --table turns it off unless asked for.
    overrides = args.overrides
    if args.table and overrides == DEFAULT_OVERRIDES:
        overrides = None
    main(
        output=args.output,
        sheet_by=args.sheet_by,
        where=args.where,
        overrides=overrides,
        dcat=args.dcat,
        table=args.table,
        priority=args.priority,
        exclude_columns=args.exclude,
    )
