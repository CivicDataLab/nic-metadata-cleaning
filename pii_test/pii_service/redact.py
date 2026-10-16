"""
Write a redacted copy of an upload: the columns the tiers called `present`.

This is the API's own redaction. generate_redacted.py is not used, for two
reasons. It builds a second copy of the models, which does not fit beside the
scan and the judge on this GPU. And it replaces the spans the detector finds
and nothing else -- right for a sentence, wrong for a column of names: the
tiers rule on a *column*, from however many of its values the detector
caught, and on LOT 3's real name columns that was 48-73% of the filled
cells. A copy redacted span by span still publishes the rest.

So the method depends on what the column holds:

    whole_column   short values (names, numbers, IDs: a median filled cell of
                   SHORT_VALUE_MAX_CHARS or fewer). Every filled cell is
                   replaced, found or not.
    found_values   free text. The values the detectors flag are cut out of
                   the cell and the sentence around them stays.

For free text the scan's own detections are not enough either. They have
been through the scan's column pass, which drops any name in a sentence that
no "Shri" or "Name:" introduces -- right for deciding whether a column of
advisory text is personal data, and most of the names in a remarks column.
So every row of a free-text column goes back through the detectors without
that pass (the caller's ``find_values``), and what comes back is cut out
together with what the scan reported. That also covers the rows the scan
never read: a copy cut off at the scan limit would ship every name below it.

When in doubt, more is replaced. Without ``find_values``, when it fails, or
when a run has more free text than MAX_SEARCH_CELLS, a free-text column is
replaced whole. A value the scan reported that cannot
be located in its cell means the table and the detections do not line up,
and the whole column goes. The written file is read back and checked before
it is offered; a copy that fails the check is deleted.

Nothing here logs or raises a cell value.
"""

import collections
import logging
import os
import re

import pandas as pd

log = logging.getLogger("pii_api")

# LOT 3's 313 `present` columns split cleanly here: 303 have a median filled
# cell of 40 characters or fewer (297 of them 30 or fewer), 10 are longer.
SHORT_VALUE_MAX_CHARS = 40
FIND_BATCH = 5_000                            # cells per find_values call
# The search runs at about 150 cells of sentences a second on the T4 (60,000
# in 393 s), and nothing else bounds it: the scan stops at 50,000 rows, this
# has to cover every row. Past this many cells in one run a column is replaced
# whole instead, which keeps the worker to about 20 minutes of searching.
MAX_SEARCH_CELLS = 200_000
EXCEL_EXTENSIONS = (".xls", ".xlsx")          # run_pii_s3.read_tabular
WHOLE, FOUND = "whole_column", "found_values"
FALLBACK_TYPE = "REDACTED"


class RedactionError(Exception):
    """No redacted copy can be offered. str(exc) is shown to the user."""


def placeholder(entity_type):
    return f"<{entity_type}>"


# --------------------------------------------------------------------------
# Reading the table back
# --------------------------------------------------------------------------

def _read_csv_text(path, rows_read, text):
    """run_pii_s3.read_csv_robust's choice of encoding, for the whole file.

    The scan decoded only the rows it read. If those were UTF-8, that is the
    text the detections quote, so a stray byte further down is replaced
    rather than re-reading the whole file as cp1252 and turning every
    non-ASCII name above it into something the detections no longer match.
    """
    try:
        return pd.read_csv(path, **text)
    except UnicodeDecodeError:
        pass
    try:
        pd.read_csv(path, nrows=rows_read, **text)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp1252", encoding_errors="replace", **text)
    return pd.read_csv(path, encoding_errors="replace", **text)


def read_text_table(path, rows_read=None):
    """The table the scan read, with every cell as the text in the file.

    Same parser and same rows as run_pii_s3.read_tabular, so a detection's
    row_index points at the same row here. dtype=str with NA handling off is
    what leaves an untouched cell as it was: pandas' own inference would
    write 7 back as 7.0 and blank a literal "NA".
    """
    text = {"dtype": str, "keep_default_na": False}
    if os.path.splitext(path)[1].lower() in EXCEL_EXTENSIONS:
        table = pd.read_excel(path, **text)
    else:
        table = _read_csv_text(path, rows_read, text)
    if not isinstance(table.index, pd.RangeIndex):
        # pandas reads the extra leading field as row labels. The scan does
        # the same, so that column was never looked at and cannot go out in
        # a copy called redacted.
        raise RedactionError(
            "the data rows have more fields than the header row, so the first "
            "column was never checked; fix the header and upload again")
    return table.fillna("") if table.isna().values.any() else table


# --------------------------------------------------------------------------
# One cell, one column
# --------------------------------------------------------------------------

def is_short_valued(cells):
    """True when a column holds values rather than sentences."""
    lengths = cells.str.strip().str.len()
    filled = lengths[lengths > 0]
    return filled.empty or filled.median() <= SHORT_VALUE_MAX_CHARS


def cut(text, found):
    """`text` with every occurrence of each found value replaced.

    ``found`` is [(value, entity type)]. Returns None when a value is not in
    the text at all -- the caller's sign that this is not the cell the scan
    saw. Overlapping finds (a name the NER and a field-label pattern both
    caught, with different edges) become one placeholder.
    """
    spans = []
    for value, entity_type in found:
        start = text.find(value) if value else -1
        if start < 0:
            return None
        while start >= 0:
            spans.append((start, start + len(value), entity_type))
            start = text.find(value, start + 1)
    spans.sort(key=lambda span: (span[0], span[0] - span[1]))
    merged = []
    for start, end, entity_type in spans:
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end, entity_type])
    out, cursor = [], 0
    for start, end, entity_type in merged:
        out += [text[cursor:start], placeholder(entity_type)]
        cursor = end
    return "".join(out) + text[cursor:]


def replace_filled(table, label, mark):
    """Replace every filled cell of a column. Returns how many."""
    position = table.columns.get_loc(label)
    cells = table.iloc[:, position]
    rows = cells.index[cells.str.strip() != ""]     # RangeIndex: labels are positions
    table.iloc[rows, position] = mark
    return len(rows)


def find_in_column(cells, find_values, progress=None):
    """{row: [(value, entity type)]} for every filled cell of a column.

    Each cell goes to the detectors stripped, as the scan sends it; a value
    found there is in the cell itself too.
    """
    texts = cells.str.strip()
    rows = list(texts.index[texts != ""])           # RangeIndex: labels are positions
    found = {}
    for start in range(0, len(rows), FIND_BATCH):
        batch = rows[start:start + FIND_BATCH]
        for row, values in zip(batch, find_values([texts.iat[row] for row in batch])):
            if values:
                found[row] = list(values)
        if progress:
            progress(min(start + FIND_BATCH, len(rows)), len(rows))
    return found


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------

def redact_table(table, present, detections, *, find_values=None, progress=None):
    """Redact the `present` columns of `table` in place.

    Returns (one summary per column, what verify() checks the written file
    against, notes for the user).
    """
    labels = {str(label): label for label in table.columns}
    present = [str(column) for column in present]
    missing = [column for column in present if column not in labels]
    if len(labels) != len(table.columns) or missing:
        raise RedactionError(
            f"{len(missing) or 'some'} flagged column(s) could not be matched "
            f"to the table as it was read back")

    found = {column: collections.defaultdict(list) for column in present}
    types = {column: collections.Counter() for column in present}
    for d in detections:
        column = str(d["column"])
        if column in found:
            found[column][int(d["row_index"])].append(
                (str(d["entity_text"]), d["entity_type"]))
            types[column][d["entity_type"]] += 1

    free_text = [column for column in present
                 if not is_short_valued(table[labels[column]])]
    methods = {column: FOUND if column in free_text else WHOLE for column in present}
    unsearched, too_long, budget = [], [], MAX_SEARCH_CELLS
    for i, column in enumerate(free_text):
        filled = int((table[labels[column]].str.strip() != "").sum())
        if filled > budget:
            methods[column] = WHOLE
            too_long.append(column)
            continue
        budget -= filled
        try:
            if find_values is None:
                raise LookupError("no detectors to search the text with")
            extra = find_in_column(
                table[labels[column]], find_values,
                progress and (lambda done, total, i=i: progress(i, len(free_text), done, total)))
        except Exception as exc:                        # noqa: BLE001
            # The names in these sentences were not looked for, so there is
            # nothing to cut them by.
            log.error(f"redact: free-text search failed ({type(exc).__name__})")
            methods[column] = WHOLE
            unsearched.append(column)
            continue
        for row, values in extra.items():
            found[column][row] += values

    summaries, checks, misaligned = [], {}, []
    for column in present:
        label = labels[column]
        position = table.columns.get_loc(label)
        common = types[column].most_common(1)
        mark = placeholder(common[0][0] if common else FALLBACK_TYPE)
        cuts = {}
        if methods[column] == FOUND:
            for row, values in found[column].items():
                redacted = cut(table.iat[row, position], values) if row < len(table) else None
                if redacted is None:
                    methods[column] = WHOLE
                    misaligned.append(column)
                    break
                cuts[row] = redacted
        if methods[column] == WHOLE:
            changed = replace_filled(table, label, mark)
            checks[column] = {"method": WHOLE, "mark": mark}
        else:
            for row, redacted in cuts.items():
                table.iat[row, position] = redacted
            changed = len(cuts)
            checks[column] = {"method": FOUND,
                              "found": {row: [value for value, _ in values]
                                        for row, values in found[column].items()}}
        summaries.append({"column": column, "method": methods[column],
                          "cells_redacted": int(changed)})

    notes = []
    kept_text = [s["column"] for s in summaries if s["method"] == FOUND]
    if kept_text:
        notes.append(f"In {len(kept_text)} free-text column(s) only the values the "
                     f"detectors flagged were replaced; a name they missed may "
                     f"remain: {', '.join(kept_text)}.")
    whole = unsearched + misaligned
    if whole:
        notes.append(f"{len(whole)} free-text column(s) could not be redacted "
                     f"value by value, so every filled cell was replaced: "
                     f"{', '.join(whole)}.")
    if too_long:
        notes.append(f"{len(too_long)} free-text column(s) were too long to search "
                     f"(more than {MAX_SEARCH_CELLS:,} cells of text in one run), so "
                     f"every filled cell was replaced: {', '.join(too_long)}.")
    marks = {placeholder(entity_type) for column in present
             for values in found[column].values() for _, entity_type in values}
    return summaries, {"columns": checks, "marks": marks | {placeholder(FALLBACK_TYPE)},
                       "labels": labels}, notes


def verify(path, table, checks):
    """Read the written copy back and check it is what redact_table meant.

    Independent of how the cells were rewritten: it looks at the file a
    person would publish. Raises RedactionError on the first thing wrong.
    """
    order = sorted((table.columns.get_loc(checks["labels"][column]), column)
                   for column in checks["columns"])
    copy = pd.read_csv(path, dtype=str, keep_default_na=False,
                       usecols=[position for position, _ in order])
    if len(copy) != len(table):
        raise RedactionError("the redacted copy does not have the same number "
                             "of rows as the file")
    marks = re.compile("|".join(re.escape(m) for m in sorted(checks["marks"])))

    def all_replaced(cells, mark):
        text = cells.str.strip()
        return bool(((text == "") | (cells == mark)).all())

    for i, (_, column) in enumerate(order):
        cells, check = copy.iloc[:, i], checks["columns"][column]
        if check["method"] == WHOLE:
            ok = all_replaced(cells, check["mark"])
        else:
            ok = not any(value in piece
                         for row, values in check["found"].items()
                         for piece in marks.split(cells.iat[row])
                         for value in values)
        if not ok:
            raise RedactionError("the redacted copy failed its own check; "
                                 "no file was produced")


def redact_file(source_path, out_path, present, detections, *, rows_read=None,
                find_values=None, progress=None):
    """Write the redacted copy of `source_path` to `out_path` as CSV.

    ``source_path`` is the table the scan read (a CSV or a workbook),
    ``present`` the columns to redact and ``detections`` the scan's own.
    ``find_values(texts)`` returns [(value, entity type)] per text -- the
    detectors without the scan's column pass (scanner.find_values);
    ``progress(column, columns, done, total)`` follows it through the
    free-text columns. Returns {"rows", "columns", "notes"}. Raises
    RedactionError when no copy can be offered; out_path then does not exist.
    """
    table = read_text_table(source_path, rows_read)
    summaries, checks, notes = redact_table(
        table, present, detections, find_values=find_values, progress=progress)
    part = out_path + ".part"
    try:
        table.to_csv(part, index=False)
        verify(part, table, checks)
        os.replace(part, out_path)
    finally:
        if os.path.exists(part):
            os.remove(part)
    log.info(f"redact: {len(table):,} row(s); "
             + ", ".join(f"{s['method']} {s['cells_redacted']:,}" for s in summaries))
    return {"rows": len(table), "columns": summaries, "notes": notes}
