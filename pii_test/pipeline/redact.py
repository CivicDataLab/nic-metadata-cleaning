"""Redacted copies of the columns a finished run classified ``present``.

Only the columns the tiers ended up calling present (or --redact-classes) are
redacted, in the local files the run scanned; a column the tiers cleared
reaches the copy intact. run.py's ``redact`` step calls targets() and redact().

Redaction runs the same passes the scan does -- analyzer, PM-Kisan field
labels, regex detectors, then filters.py -- so it removes what the scan called
personal data and nothing else. Presidio on its own reads "प्रधान मंत्री
किसान सम्मान" as a PERSON, and a KCC answer comes back with the scheme it
names replaced by <PERSON>. The filters are where that knowledge lives, so
redaction has to go through them too.

Every row is redacted, not only the rows the scan read. The scan's row cap
belongs to detection, where a sample is enough to judge a file; a redacted
copy cut off at the same row still ships every name below it.

CSV only: an Excel file is reported as an error in redaction_log.csv.
"""

import csv
import logging
import multiprocessing as mp
import os
import shutil
import sys

import pandas as pd
import torch
from presidio_analyzer import RecognizerResult
from presidio_anonymizer import AnonymizerEngine

import scan
from filters import filterdetections, regexmatches

LOG = "redaction_log.csv"

# The models of this process, set by start(): once for a single-process run,
# and in every worker of a pool.
analyzer = None
anonymizer = None
maxrows = None        # None redacts every row


def start(gpu=False, rows=None):
    global analyzer, anonymizer, maxrows
    device = "cuda" if gpu and torch.cuda.is_available() else "cpu"
    analyzer, _ = scan.models(device)
    anonymizer = AnonymizerEngine()
    maxrows = rows
    logging.info(f"Redaction worker {os.getpid()} initialized (device={device})")


def spans(text):
    """Every PII span in one cell as (result, source), overlaps resolved."""
    language = scan.language(text)
    found, seen = [], set()
    try:
        # Devanagari text is read as Hindi and as English; the results of the
        # two passes are deduplicated on (type, start, end).
        for lang in ([language] if language == "en" else [language, "en"]):
            for r in analyzer.analyze(text=text, language=lang):
                if (r.entity_type, r.start, r.end) not in seen:
                    seen.add((r.entity_type, r.start, r.end))
                    found.append(r)
    except Exception:                                           # noqa: BLE001
        found = []
    merged = scan.resolve(list(found) + scan.fieldnames(text))
    return [(r, "presidio") for r in merged if scan.keepresult(r, text)] + [
        (RecognizerResult(entity_type=label, start=start, end=end, score=1.0,
                          analysis_explanation=None), "regex")
        for label, _, start, end in regexmatches(text)]


def redactframe(df, columns, rows=None, label=""):
    """Redact ``columns`` of ``df`` in place. Returns the number of cells changed.

    One column at a time, because the filters' second pass reads a whole
    column -- how often a value repeats, how distinct the column is -- and per
    cell it would reach different answers than the scan did. rows=None
    redacts every row.
    """
    rows = len(df) if rows is None else min(rows, len(df))
    changed = 0
    for col in columns:
        if col not in df.columns:
            continue
        position = df.columns.get_loc(col)
        cells, padding, detections = {}, {}, []
        for i in range(rows):
            value = df.iat[i, position]
            raw = "" if pd.isna(value) else str(value)
            text = raw.strip()
            if not text:
                continue
            cells[i] = text
            # The scan analyses the stripped cell, so the spans are offsets
            # into that; the padding goes back on so a redacted cell differs
            # from the original only where a span was cut out.
            padding[i] = (raw[:len(raw) - len(raw.lstrip())], raw[len(raw.rstrip()):])
            try:
                found = spans(text)
            except Exception as exc:                            # noqa: BLE001
                logging.warning(f"Analysis failed for {label} col={col} row={i}: {exc}")
                continue
            for r, source in found:
                detections.append({
                    "column": col, "row_index": i,
                    "entity_type": r.entity_type,
                    "entity_text": text[r.start:r.end],
                    "score": r.score, "source": source,
                    # start/end are redaction's own: the filters pass unknown
                    # keys through, and the anonymizer needs them back to cut
                    # the span out of the cell.
                    "start": r.start, "end": r.end,
                    "cell_len": len(text),
                    "left_context": text[max(0, r.start - scan.CONTEXTCHARS):r.start],
                })

        detections = filterdetections(detections, {col: scan.cardinality(df[col], rows)})

        byrow = {}
        for d in detections:
            byrow.setdefault(d["row_index"], []).append(d)
        for i, found in byrow.items():
            text = cells[i]
            results = [RecognizerResult(d["entity_type"], d["start"], d["end"], d["score"])
                       for d in found]
            try:
                redacted = anonymizer.anonymize(text=text, analyzer_results=results).text
            except Exception as exc:                            # noqa: BLE001
                logging.warning(f"Redaction failed for {label} col={col} row={i}: {exc}")
                continue
            if redacted != text:
                lead, trail = padding[i]
                df.iat[i, position] = lead + redacted + trail
                changed += 1
    return changed


def redactfile(task):
    """Redact one local CSV into its destination. A pool worker's job."""
    source, dest, columns = task
    result = {"source": source, "dest": dest, "columns": "; ".join(columns),
              "cells_redacted": 0, "error": None}
    if os.path.splitext(source)[1].lower() != ".csv":
        result["error"] = "redaction reads CSV only"
        return result
    try:
        # dtype=str with keep_default_na off leaves every cell the analyzer
        # does not touch byte-identical; pandas' own inference would write 7
        # back as 7.0 and blank out a literal "NA".
        df = pd.read_csv(source, dtype=str, keep_default_na=False, on_bad_lines="skip")
        result["cells_redacted"] = redactframe(df, columns, maxrows, source)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        df.to_csv(dest, index=False)
    except Exception as exc:                                    # noqa: BLE001
        result["error"] = str(exc)
    return result


def targets(rows, classes=("present",), root=None):
    """(source file, relative path, columns) per file with a column in ``classes``.

    ``rows`` are Tier 1's column rows. ``uuid`` is the scanned file's path
    relative to the scanned folder -- which is also where its redacted copy
    goes -- and ``source_file`` is where it sits on disk; where a row lacks
    one, it is rebuilt from ``root`` and the uuid.
    """
    wanted = {}
    for row in rows:
        if row.get("pii_class") not in classes:
            continue
        uuid = str(row["uuid"])
        source = row.get("source_file") or (os.path.join(root, uuid) if root else None)
        if not source:
            raise ValueError(f"{uuid} has no source_file and no scanned folder was given")
        wanted.setdefault((source, uuid), []).append(row["column"])
    return [(source, uuid, columns) for (source, uuid), columns in sorted(wanted.items())]


def redact(files, outdir, gpu=False, workers=1, rows=None, clean=None):
    """Write a redacted copy of each of ``files`` (from targets) under ``outdir``,
    keeping its path.

    Logs every file to redaction_log.csv there. With ``clean`` (the scanned
    folder), also copy the files that needed no redaction, so ``outdir`` holds
    the whole corpus -- but not the scan's own detection CSVs, which quote the
    personal data by design.
    """
    root = os.path.abspath(clean) if clean else None
    if root and os.path.commonpath([os.path.abspath(outdir), root]) == root:
        sys.exit(f"{outdir} is inside the scanned folder {root}; a rescan would read "
                 f"the redacted copies as data")
    os.makedirs(outdir, exist_ok=True)
    tasks = [(source, os.path.join(outdir, uuid.replace("/", os.sep)), columns)
             for source, uuid, columns in files]

    def progress(result):
        mark = result["error"] or f"{result['cells_redacted']} cell(s)"
        print(f"[{len(results)}/{len(tasks)}] {os.path.basename(result['source'])[:50]:<50} "
              f"{mark}", file=sys.stderr, flush=True)

    results = []
    if workers > 1:
        pool = mp.Pool(workers, initializer=start, initargs=(gpu, rows))
        try:
            for result in pool.imap(redactfile, tasks):
                results.append(result)
                progress(result)
        finally:
            pool.close()
            pool.join()
    else:
        start(gpu, rows)
        for task in tasks:
            results.append(redactfile(task))
            progress(results[-1])

    with open(os.path.join(outdir, LOG), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "dest", "columns",
                                                    "cells_redacted", "error"])
        writer.writeheader()
        writer.writerows(results)

    if root:
        done, copied = {uuid for _, uuid, _ in files}, 0
        for dirpath, _, names in sorted(os.walk(root)):
            for name in sorted(names):
                if name == scan.DETECTIONS or name.endswith("_pii_detections.csv"):
                    continue
                source = os.path.join(dirpath, name)
                rel = os.path.relpath(source, root)
                if rel.replace(os.sep, "/") in done:
                    continue
                dest = os.path.join(outdir, rel)
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
                shutil.copy2(source, dest)
                copied += 1
        print(f"copied {copied} file(s) that needed no redaction", file=sys.stderr)

    failed = [r for r in results if r["error"]]
    cells = sum(r["cells_redacted"] for r in results)
    print(f"redacted {len(results) - len(failed)} file(s), {cells} cell(s) -> {outdir}"
          + (f" | {len(failed)} failed, see {LOG}" if failed else ""), file=sys.stderr)
    return results
