"""
Hand-fix "Conforms To" on dublin_core_remaining for 44 datasets whose headers
fill_headers_remaining.py extracted wrongly (user list, 2026-09-29).

What went wrong, and the fix for each kind:

  * PDFs (5 listed as application/pdf, plus nid 95560 whose Format says
    text/html but whose file is a PDF): the extractor read the file as CSV and
    stored "%PDF1.4". A PDF has no header row, so the headers are cleared
    (NULL Conforms To / header_count, headers_cleaned FALSE, as on every other
    header-less row).
  * Economic Survey 2012-13 appendix tables (.xls): pandas took the table
    title as the header row, giving "<title>,Unnamed 1,...". The real header
    is a block of several rows under the title; it is rebuilt by hand in
    MANUAL. Levels are joined with " - " (the source convention the cleaner
    turns into a double space), and footnote markers ("2011-12a", "P") and
    column-arithmetic notes ("(2 to 6)") are dropped.
  * CSVs whose real header row is not row 0 (Smart Cities template rows,
    title rows, blank leading rows), whose first column is blank or ".", or
    whose group labels are the table title: FROM_FILE takes the header row
    from the file itself; GROUPED holds the ones rebuilt from two rows.
  * nid 602908884 is an .xls saved as .csv: read with read_excel.

Every header then goes through the same character filter as
fill_headers_remaining.extract(), so the result matches the rest of the column.

Usage:
    python fix_malformed_headers.py              # dry run: print old -> new
    python fix_malformed_headers.py --apply      # snapshot, then write
"""

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DB_PATH = HERE.parent / "metadata.db"
DOWNLOADS = ROOT / "data" / "final_batch_downloads"
TABLE = "dublin_core_remaining"

PDF_NIDS = ["95494", "95518", "95558", "95560", "95579", "95750"]

# Economic Survey tables that share one header block.
GDP_BY_INDUSTRY = [
    "Year",
    "Agriculture, forestry & fishing, mining and quarrying",
    "Manufacturing, construction, electricity, gas and water supply",
    "Trade, hotels, transport & communication",
    "Financing, insurance, real estate and business services",
    "Community, social and personal services",
    "Gross domestic product at factor cost",
]
CROP_INDEX = ["S.No.", "Crop"]

MANUAL = {
    "85916": [
        "Year",
        "Gross national income at factor cost - At current prices",
        "Gross national income at factor cost - At 2004-05 prices",
        "Net national income at factor cost - At current prices",
        "Net national income at factor cost - At 2004-05 prices",
        "Per capita net national income - At current prices",
        "Per capita net national income - At 2004-05 prices",
    ],
    "85918": GDP_BY_INDUSTRY,
    "88174": ["Group/Commodity", "1970-71", "1980-81", "1990-91", "2000-01",
              "2007-08", "2008-09", "2009-10", "2010-11", "2011-12"],
    "88192": GDP_BY_INDUSTRY,
    "88194": GDP_BY_INDUSTRY,
    "88196": [
        "Year",
        "Gross domestic savings - Household sector",
        "Gross domestic savings - Private corporate sector",
        "Gross domestic savings - Public sector",
        "Gross domestic savings - Total",
        "Gross fixed capital formation - Public sector",
        "Gross fixed capital formation - Private sector",
        "Gross fixed capital formation - Total",
        "Change in stocks - Public sector",
    ],
    "88437": ["Particulars", "Unit", "1960-61", "1970-71", "1980-81", "1990-91",
              "1999-00", "2004-05", "2005-06", "2007-08", "2008-09", "2009-10",
              "2010-11", "2011-12"],
    "88588": CROP_INDEX + ["Weight", "2007-08", "2008-09", "2009-10", "2010-11",
                           "2011-12"],
    "88590": CROP_INDEX + ["2007-08", "2008-09", "2009-10", "2010-11", "2011-12"],
    "88614": ["Industry Group", "Industry", "Weight", "2006-07", "2007-08",
              "2008-09", "2009-10", "2010-11", "2011-12"],
    "89178": [
        "Year",
        "Population (million)",
        "Cereals - Net production (million tonnes)",
        "Cereals - Net imports (million tonnes)",
        "Cereals - Change in Government stocks (million tonnes)",
        "Cereals - Net availability (million tonnes)",
        "Pulses - Net availability (million tonnes)",
        "Per capita net availability per day (grams) - Cereals",
        "Per capita net availability per day (grams) - Pulses",
        "Per capita net availability per day (grams) - Total",
    ],
    "89180": [
        "Year",
        "Net production of foodgrains",
        "Net imports",
        "Net availability of foodgrains",
        "Procurement",
        "Public distribution",
        # "Col. 3 as per cent of Col. 4" etc., with the column names filled in
        "Net imports as per cent of net availability",
        "Procurement as per cent of net production",
        "Public distribution as per cent of net availability",
    ],
    "89665": ["Particulars", "1950-51", "1960-61", "1970-71", "1980-81",
              "1990-91", "2000-01", "2007-08", "2008-09", "2009-10", "2010-11",
              "2011-12"],
    "89667": ["Particulars", "Unit", "1950-51", "1960-61", "1970-71", "1980-81",
              "1990-91", "2000-01", "2008-09", "2009-10", "2010-11", "2011-12"],
    "89752": ["Year", "Domestic", "Commercial", "Industry", "Traction",
              "Agriculture", "Others"],
    "89860": [
        "Year",
        "Edible oil (Kg.)",
        "Vanaspati (Kg.)",
        "Sugar (Nov.-Oct.) (Kg.)",
        "Cloth - Cotton (metres)",
        "Cloth - Man-made (metres)",
        "Cloth - Total (metres)",
        "Tea (Gram.)",
        "Coffee (Gram.)",
        "Electricity (Domestic) (KWH)",
    ],
    "90357": ["Sector", "2004-05", "2005-06", "2006-07", "2007-08", "2008-09",
              "2009-10", "2010-11", "2011-12"],
    "90359": [
        "S.No.",
        "Crops/Groups of Crops",
        "States",
        "Production (Million Tonnes)",
        "Per cent Share of Production to All India",
        "Cumulative Per cent Share of Production",
    ],
    "90387": ["Industry", "Unit", "1950-51", "1960-61", "1970-71", "1980-81",
              "1990-91", "2000-01", "2005-06", "2006-07", "2007-08", "2008-09",
              "2009-10", "2010-11", "2011-12"],
    "90783": ["Commodity", "1950-51", "1960-61", "1970-71", "1980-81", "1990-91",
              "2000-01", "2007-08", "2008-09", "2009-10", "2010-11", "2011-12"],
    "91740": [
        "S.No",
        "Name of Utility",
        "Tariff effective from",
        "Domestic 4KW (400 KWh/Month)",
        "Large Industry 1000KW 60% L.F. (438000 KWh/Month)",
    ],
    # Smart City project cards: a vertical key/value sheet with no header row
    "602917169": ["S.No.", "Particulars", "Details"],
    "602917184": ["S.No.", "Particulars", "Details"],
}

# Headers built from two header rows (group label over sub-headers).
VEHICLE_GROUPS = ["Buses", "Light Motor Vehicles", "Goods Carrier Vehicles",
                  "Two-Wheeler Vehicles", "Four-Wheeler Vehicles", "Miscellaneous"]
VEHICLE_YEARS = ["2019-20", "2018-19", "2017-18", "2016-17", "2015-16"]
GROUPED = {
    # Blank template rows 0-4; group row 6 sits one cell right of each
    # 5-year block in row 7. Column 1 and the last 4 columns are empty.
    "602911036": ["City Name"] + [f"No. of Registrations - {g} - {y}"
                                  for g in VEHICLE_GROUPS for y in VEHICLE_YEARS],
    # Header row 6 under a group row that puts the last five columns under
    # "Collection Vehicle details" - the prefix every other city's copy of
    # this template carries.
    "602916740": ["City Name", "Zone Name", "Ward name", "Ward No.",
                  "Waste Quantity (TPD)"] + [
        f"Collection Vehicle details - {h}" for h in [
            "Type of Waste collection vehicle", "Capacity (in cubic meters)",
            "Year of purchase", "Nos of Vehicle",
            "Frequency of trips (Daily, Biweekly, Fortnightly, Monthly)"]],
}
# Domestic + foreign monument tables, whose group label was the whole table
# title ("10 Most popular ... for Domestic Visitors in 2018-19 - Rank").
for _nid in ["6819441", "6879879", "7061493", "7280694"]:
    GROUPED[_nid] = [f"{g} Visitors - {h}" for g in ["Domestic", "Foreign"]
                     for h in ["Rank", "Name of Monument", f"No. of {g} visitors",
                               "Percentage share"]]

# Header taken from the file: `row` is the 0-based header row; `set` replaces
# cells; empty columns are dropped.
FROM_FILE = {
    "3960081": {"row": 0, "set": {0: "DESCRIPTION"}},    # as its 4 siblings
    "657161": {"row": 0, "set": {0: "State / Union Territory"}},  # as siblings
    "91567": {"row": 0},                  # blank, empty first column
    "602908884": {"row": 0},              # .xls saved as .csv
    "602909395": {"row": 6},              # Smart Cities template rows above
    "602915015": {"row": 5},
    "602920866": {"row": 1},              # title row ",Shimla City,"
    "602921130": {"row": 1},              # title row ",,,EV CHARGER ,,,"
    "604783910": {"row": 2},              # two blank rows above
}


def clean(h):
    """fill_headers_remaining.extract()'s filter, plus a strip."""
    return re.sub(r"[^a-zA-Z0-9_%. /]", "", str(h)).strip()


def read_rows(path):
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic == b"\xd0\xcf\x11\xe0":  # OLE2: an Excel file whatever its suffix
        df = pd.read_excel(path, header=None, dtype=str)
        return df.fillna("").values.tolist()
    with open(path, newline="", encoding="latin-1") as f:
        return list(csv.reader(f))


def headers_from_file(path, row, set_=None):
    rows = read_rows(path)
    width = max(len(r) for r in rows)
    header = list(rows[row]) + [""] * (width - len(rows[row]))
    for j, v in (set_ or {}).items():
        header[j] = v
    # Drop columns empty in the header and every row below it.
    keep = [j for j in range(width)
            if str(header[j]).strip()
            or any(j < len(r) and str(r[j]).strip() for r in rows[row + 1:])]
    missing = [j for j in keep if not str(header[j]).strip()]
    if missing:
        raise ValueError(f"{path.name}: data columns {missing} have no header")
    return [header[j] for j in keep]


def build(con):
    nids = PDF_NIDS + list(MANUAL) + list(GROUPED) + list(FROM_FILE)
    assert len(nids) == len(set(nids)) == 44, len(nids)
    rows = con.execute(
        f'SELECT nid, "Identifier[UUID]", "Conforms To", header_count, '
        f'headers_cleaned FROM {TABLE} WHERE nid IN (SELECT unnest(?))',
        [nids]).fetchall()
    current = {r[0]: r[1:] for r in rows}
    missing = set(nids) - set(current)
    if missing:
        raise SystemExit(f"nids not in {TABLE}: {sorted(missing)}")

    out = []
    for nid in nids:
        uuid = current[nid][0]
        if nid in PDF_NIDS:
            out.append((nid, None, None, False))
            continue
        if nid in MANUAL:
            raw = MANUAL[nid]
        elif nid in GROUPED:
            raw = GROUPED[nid]
        else:
            spec = FROM_FILE[nid]
            path = next(DOWNLOADS.glob(f"{uuid}.*"))
            raw = headers_from_file(path, spec["row"], spec.get("set"))
        cleaned = [clean(h) for h in raw]
        changed = any(c != str(h) for c, h in zip(cleaned, raw))
        count = sum(1 for c in cleaned if c)
        out.append((nid, ",".join(cleaned), count, changed))
    return current, out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--apply", action="store_true",
                    help="snapshot the four columns, then write (default: dry run)")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=not args.apply)
    current, out = build(con)
    for nid, hdrs, count, changed in out:
        old = current[nid][1]
        print(f"{nid}  count {current[nid][2]} -> {count}")
        print(f"   old: {old!r}"[:220])
        print(f"   new: {hdrs!r}")

    if not args.apply:
        print(f"\nDRY RUN - {len(out)} rows would change; rerun with --apply")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / "data" / "backups" / f"{TABLE}_malformed_headers_{stamp}.csv"
    con.execute("CREATE TEMP TABLE _fix(nid VARCHAR, hdrs VARCHAR, "
                "cnt INTEGER, cleaned BOOLEAN)")
    con.executemany("INSERT INTO _fix VALUES (?, ?, ?, ?)", out)
    con.execute(
        f'COPY (SELECT d.nid, d."Conforms To", d.header_count, d.headers_cleaned '
        f'FROM {TABLE} d JOIN _fix USING (nid) ORDER BY d.nid) '
        f"TO '{backup}' (HEADER)")
    print(f"\nsnapshot -> {backup}")
    con.execute(f'''
        UPDATE {TABLE} AS d
        SET "Conforms To" = t.hdrs, header_count = t.cnt,
            headers_cleaned = t.cleaned
        FROM _fix AS t
        WHERE d.nid = t.nid
    ''')
    n = con.execute(f'SELECT count(*) FROM {TABLE} d JOIN _fix t USING (nid) '
                    f'WHERE d."Conforms To" IS NOT DISTINCT FROM t.hdrs').fetchone()[0]
    print(f"written: {n}/{len(out)} rows now match")
    con.close()


if __name__ == "__main__":
    main()
