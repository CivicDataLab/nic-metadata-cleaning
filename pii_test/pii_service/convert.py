"""
Decide what an upload is and hand the scan a table it can read.

The scan reads a CSV or a workbook from a path (run_pii_s3.read_tabular) and
nothing else, and that file is not the API's to change. So the API accepts
more by putting this step in front of it:

    .csv          passed through untouched
    .json         written out as converted/<name>.csv -- every record, since a
                  redacted copy is cut from that table and must cover them all
    .xlsx, .xls   passed through, after two checks: that it is a workbook at
                  all, and that it does not unpack to more than the service
                  can hold. Only the first sheet is read downstream; the
                  sheet names are returned so the caller can say so.
    .pdf          its text, written out as converted/<name>.csv with one row
                  per line (page, line, text) -- see pdf_text.py, which reads
                  a page's own text and OCRs the pages that have none

LOT 3 settled the JSON layouts: of 4,778 JSON files 4,756 are a plain list of
flat records, two wrap that list in an object, and the rest are failed
downloads. It also has 207 ".xls" files that are CSV text, which is why a
workbook name is checked against the file's first bytes rather than trusted.

A ConversionError's message goes to the user as the run's error. It never
quotes the file's contents.
"""

import csv
import json
import os
import shutil
import zipfile

import pandas as pd

import pdf_text

ACCEPTED_EXTENSIONS = (".csv", ".json", ".xlsx", ".xls", ".pdf")
EXCEL_EXTENSIONS = (".xlsx", ".xls")
MAX_UNPACKED_BYTES = 500 * 2**20          # an .xlsx is a zip; cap what it unpacks to
PREFERRED_TABLE_KEYS = ("rows", "records", "data")

NOT_ACCEPTED = "Only .csv, .json, .xlsx, .xls and .pdf files are accepted"
NO_TABLE = ("No table found in the JSON: expected a list of records, "
            "or an object holding one")
NO_RECORDS = "The JSON holds no records"
NOT_A_WORKBOOK = "Not a valid Excel workbook"
NOT_A_PDF = "Not a valid PDF file"


class ConversionError(Exception):
    """The upload cannot be turned into a table. str(exc) is shown to the user."""


def accepted(filename):
    """True if the name ends in one of ACCEPTED_EXTENSIONS, whatever its case."""
    return filename.lower().endswith(ACCEPTED_EXTENSIONS)


# --------------------------------------------------------------------------
# Workbooks
# --------------------------------------------------------------------------

def sniff(path):
    """What the file's first bytes say it is: zip, ole, pdf, html, text or binary."""
    with open(path, "rb") as handle:
        head = handle.read(8192)
    if b"%PDF-" in head[:1024]:                       # the spec allows leading junk
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"                                  # .xlsx
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"                                  # .xls
    if b"\x00" in head:
        return "binary"
    if head.removeprefix(b"\xef\xbb\xbf").lstrip().startswith(b"<"):
        return "html"
    return "text"


def unpacked_size(path):
    """What a zip file's members add up to once unpacked."""
    with zipfile.ZipFile(path) as archive:
        return sum(info.file_size for info in archive.infolist())


def sheet_names(path):
    """A workbook's sheet names, in workbook order."""
    try:
        with pd.ExcelFile(path) as book:
            return list(book.sheet_names)
    except Exception as exc:                            # noqa: BLE001
        raise ConversionError(
            f"The workbook could not be opened ({type(exc).__name__})") from None


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------

def _is_records(value):
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, dict) for item in value)


def find_records(document):
    """The list of record dicts inside a parsed JSON document."""
    if isinstance(document, list):
        if not document:
            raise ConversionError(NO_RECORDS)
        if not _is_records(document):
            raise ConversionError(NO_TABLE)
        return document
    if not isinstance(document, dict):
        raise ConversionError(NO_TABLE)
    keys = [key for key, value in document.items() if _is_records(value)]
    if len(keys) == 1:
        return document[keys[0]]
    if not keys:
        raise ConversionError(NO_TABLE)
    by_lower = {key.lower(): key for key in keys}
    for preferred in PREFERRED_TABLE_KEYS:
        if preferred in by_lower:
            return document[by_lower[preferred]]
    raise ConversionError(f"The JSON holds more than one list of records "
                          f"({', '.join(keys)}); name the table rows, records or data")


def flatten(record):
    """One record as a flat dict of column -> cell value.

    A nested object becomes dotted columns. A list stays one cell, as JSON
    text, so whatever it holds is still in front of the scan.
    """
    flat = {}

    def walk(value, name):
        if isinstance(value, dict):
            for key, inner in value.items():
                walk(inner, f"{name}.{key}" if name else key)
        elif isinstance(value, list):
            flat[name] = json.dumps(value, ensure_ascii=False)
        elif value is None:
            flat[name] = ""
        elif isinstance(value, bool):
            flat[name] = "true" if value else "false"
        else:
            flat[name] = value

    for key, value in record.items():
        walk(value, key)
    return flat


def json_to_csv(input_path, out_path):
    """Write a JSON file's records as a CSV. Returns how many there were."""
    with open(input_path, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ConversionError("The file is not UTF-8 text") from None
    del raw
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConversionError(f"Not valid JSON: {exc.msg} (line {exc.lineno}, "
                              f"column {exc.colno})") from None
    del text
    records = find_records(document)

    # Two passes rather than a list of flattened copies: an upload can be
    # 100 MB, and the parsed document alone is four times that in memory.
    columns = {}
    for record in records:
        columns.update(dict.fromkeys(flatten(record)))
    if not columns:
        raise ConversionError(NO_RECORDS)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), restval="")
        writer.writeheader()
        for record in records:
            writer.writerow(flatten(record))
    return len(records)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def prepare(input_path, run_dir, progress=None):
    """The table the scan should read for this upload, and what it came from.

    Returns {"path", "kind": csv | json | excel | pdf, "converted": whether
    path is a file written here, "records": JSON record count, "sheets":
    every sheet name of a workbook, "disguised": a workbook name on a text
    file, "pdf": pdf_text's summary of a PDF}. ``progress(done, total)``
    follows a PDF through its pages, the one conversion that takes time.
    """
    stem, extension = os.path.splitext(os.path.basename(input_path))
    extension = extension.lower()
    table = {"path": input_path, "kind": "csv", "converted": False,
             "records": None, "sheets": [], "disguised": False, "pdf": None}
    converted = os.path.join(run_dir, "converted", stem + ".csv")

    if extension == ".csv":
        return table
    if extension == ".pdf":
        if sniff(input_path) != "pdf":
            raise ConversionError(NOT_A_PDF)
        try:
            summary = pdf_text.extract(input_path, converted, progress=progress)
        except pdf_text.PdfError as exc:
            raise ConversionError(str(exc)) from None
        return dict(table, path=converted, kind="pdf", converted=True, pdf=summary)
    if extension == ".json":
        records = json_to_csv(input_path, converted)
        return dict(table, path=converted, kind="json", converted=True, records=records)
    if extension not in EXCEL_EXTENSIONS:
        raise ConversionError(NOT_ACCEPTED)

    content = sniff(input_path)
    if content == "zip":
        try:
            size = unpacked_size(input_path)
        except zipfile.BadZipFile:
            raise ConversionError(NOT_A_WORKBOOK) from None
        if size > MAX_UNPACKED_BYTES:
            raise ConversionError(
                f"The workbook unpacks to {size // 2**20} MB, over the "
                f"{MAX_UNPACKED_BYTES // 2**20} MB limit; save the sheet as CSV")
    if content in ("zip", "ole"):
        # pandas picks the engine from the content too, so a workbook under
        # the other Excel extension still reads.
        return dict(table, kind="excel", sheets=sheet_names(input_path))
    if content == "text":
        os.makedirs(os.path.dirname(converted), exist_ok=True)
        shutil.copyfile(input_path, converted)
        return dict(table, path=converted, converted=True, disguised=True)
    if content == "html":
        raise ConversionError(f"The file is named {extension} but holds HTML or XML, "
                              f"not a workbook; save it as CSV")
    raise ConversionError(NOT_A_WORKBOOK)
