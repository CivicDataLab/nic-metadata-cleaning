"""Set raw_metadata (the lot 1 raw table) to the department's resource list.

Source: ResourceList_Department-of-Health-and-Family-Welfare.xlsx, inside
ResourceList_DoFHW(1).zip - 206,972 rows, the same nids as raw_metadata, and
every column of it but batch. Each of those columns is written from the sheet,
matched on nid; batch is not touched and no row is added or removed.

raw_metadata came from this sheet, but its frequency had been turned into
purl.org URIs (or lost: blank on 141,285 rows) and its granularity into
xsd:duration values. The sheet has the OGD labels (Monthly, Annual, Quarterly,
Others, One-time), and those are what the table holds after this.

The sheet went through a find-and-replace of the file-format code: every "31"
became "text/csv", in uuids, titles, notes and URLs too ("as on text/csvst
March", "dataurl0text/csv02019"). It is put back here in every column but
file_format. The table already had the titles and uuids right; it still
carried the damage in datafile, note and Reference Url, and had lost the 31 of
one uuid (nid 114790).

Afterwards re-run export_all_lots.py (both, --no-table will do) for the
raw_lot1 sheets and export_all_lots_old_new.py (both) for the old side.

Usage: python update_raw_metadata_from_resource_list.py [--source ZIP_OR_XLSX] [--dry-run]
"""
import sys
import tempfile
import zipfile
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
SOURCE = Path.home() / "Downloads" / "ResourceList_DoFHW(1).zip"
TABLE = "raw_metadata"
DAMAGE, CODE = "text/csv", "31"
UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
DRY = "--dry-run" in sys.argv
if "--source" in sys.argv:
    SOURCE = Path(sys.argv[sys.argv.index("--source") + 1])

q = lambda name: '"' + name.replace('"', '""') + '"'


def value(col: str, typ: str) -> str:
    """The sheet's text cell as the table's type."""
    c = q(col)
    if typ.startswith("TIMESTAMP"):      # Excel day serials
        return f"CAST(TIMESTAMP '1899-12-30' + to_days(CAST(CAST({c} AS DOUBLE) AS INTEGER)) AS {typ})"
    if typ in ("BIGINT", "INTEGER"):
        return f"CAST(CAST({c} AS DOUBLE) AS {typ})"
    if typ == "DOUBLE":
        return f"CAST({c} AS DOUBLE)"
    text = f"replace({c}, '_x000D_', chr(13))"          # Excel's escape for a carriage return
    return text if col == "file_format" else f"replace({text}, '{DAMAGE}', '{CODE}')"


with tempfile.TemporaryDirectory() as tmp:
    sheet = SOURCE
    if SOURCE.suffix.lower() == ".zip":
        with zipfile.ZipFile(SOURCE) as z:
            members = [m for m in z.namelist() if m.lower().endswith(".xlsx")]
            assert len(members) == 1, members
            sheet = Path(tmp) / "resource_list.xlsx"
            sheet.write_bytes(z.read(members[0]))
    con = duckdb.connect(DB_PATH, read_only=DRY)
    con.execute("INSTALL excel; LOAD excel")
    con.execute("""CREATE TEMP TABLE sheet AS
                   SELECT * FROM read_xlsx(?, all_varchar = true, header = true, stop_at_empty = false)""",
                [str(sheet)])

types = dict(con.execute(
    "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?", [TABLE]).fetchall())
have = [n for n, *_ in con.execute("DESCRIBE sheet").fetchall()]
COLUMNS = [c for c in types if c != "nid" and c in have]
print(f"{SOURCE.name}: {len(COLUMNS)} of {TABLE}'s columns; not in the sheet: "
      f"{[c for c in types if c not in have]}")

con.execute(f"""CREATE TEMP TABLE src AS
                SELECT CAST(CAST(nid AS DOUBLE) AS BIGINT) AS nid,
                       {', '.join(f'{value(c, types[c])} AS {q(c)}' for c in COLUMNS)} FROM sheet""")
text_columns = [c for c in COLUMNS if types[c] == "VARCHAR"]
rows, nids, bad_uuid, left, escapes = con.execute(f"""
    SELECT count(*), count(DISTINCT nid),
           count(*) FILTER (WHERE NOT regexp_full_match(coalesce(uuid, ''), '{UUID}')),
           count(*) FILTER (WHERE {' OR '.join(f"{q(c)} LIKE '%{DAMAGE}%'" for c in text_columns if c != 'file_format')}),
           count(*) FILTER (WHERE {' OR '.join(f"regexp_matches({q(c)}, '_x[0-9A-Fa-f]{{4}}_')" for c in text_columns)})
    FROM src""").fetchone()
assert rows == nids and not (bad_uuid or left or escapes), (rows, nids, bad_uuid, left, escapes)
total, both = con.execute(f"""
    SELECT (SELECT count(*) FROM {TABLE}), count(*) FROM {TABLE} r JOIN src s ON s.nid = r.nid""").fetchone()
assert total == both == rows, f"{TABLE} has {total} rows, the sheet {rows}, {both} nids in both"
print(f"{rows} rows, the same nids as {TABLE}")

differs = lambda c: f"r.{q(c)} IS DISTINCT FROM s.{q(c)}"
counts = f"""
    SELECT count(*) FILTER (WHERE {' OR '.join(differs(c) for c in COLUMNS)}),
           {', '.join(f'count(*) FILTER (WHERE {differs(c)})' for c in COLUMNS)}
    FROM {TABLE} r JOIN src s ON s.nid = r.nid"""
todo, *per_column = con.execute(counts).fetchone()
for c, n in zip(COLUMNS, per_column):
    if n:
        print(f"  {c:26} {n:7d} to write")
print(f"{todo} rows to write")

if not DRY and todo:
    others = [c for c in types if c not in COLUMNS]
    untouched = f"SELECT count(*), {', '.join(f'bit_xor(hash(nid, {q(c)}))' for c in others)} FROM {TABLE}"
    before = con.execute(untouched).fetchone()
    con.execute("BEGIN")
    try:
        n = con.execute(f"""
            UPDATE {TABLE} AS r SET {', '.join(f'{q(c)} = s.{q(c)}' for c in COLUMNS)} FROM src s
            WHERE r.nid = s.nid AND ({' OR '.join(differs(c) for c in COLUMNS)}) RETURNING 1""").fetchall()
        assert len(n) == todo, (len(n), todo)
        assert con.execute(counts).fetchone()[0] == 0, "rows still differ from the sheet"
        assert con.execute(untouched).fetchone() == before, "a column outside the sheet changed"
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("CHECKPOINT")
    print(f"  {len(n)} rows updated")
con.close()
