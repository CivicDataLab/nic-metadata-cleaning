"""Export the PII results of lots 1, 2 and 3 to Excel, one row per detection.

The result shown is the final one: the pipeline's verdict, corrected by the
manual review in pii_test/final_review/ (build_final_review.py). The pipeline's
own verdict stays beside it in `pipeline_result`.

Five workbooks go to pii_test/results_excel/:

    PII_results_all_datasets.xlsx   every dataset with its result, and every detection
    PII_all_datasets_list.xlsx      every dataset with its result, without the detections
    PII_present.xlsx                the datasets finally judged `present`
    PII_permissible.xlsx            the same for `permissible`
    PII_false_positive.xlsx         the false detections: the datasets finally judged
                                    `false_positive`, and every detection in them

Each has a "Datasets" sheet (nid, title, result) and a "Detections" sheet (nid,
title, column, row, what was detected and the detected value). In the `present`
and `permissible` workbooks the Detections sheet holds only the detections in
columns that carry the finding; the ones in columns the pipeline rejected are
on a "Removed detections" sheet. The lots are put together; a `lot` column
says where a row came from.

The workbooks hold the detected values themselves -- real names, phone numbers
and addresses. They are for review on this server or the reviewer's own
machine and must not be committed or passed on.

Sources: lot 1 from metadata.db (pii_detections_lot1, pii_column_class) and the
flag snapshot the September re-scan uploaded to S3; lots 2 and 3 from the
per-shard pii_detections.csv files and pii_test/lot{2,3}/. KCC is not here: it
has no nid or title, and its full scan has over a million detections.

    python pii_test/export_results_excel.py --lot1-snapshot PATH/lot1_snapshot.parquet
"""

import argparse
import glob
import os
import re

import duckdb
import pandas as pd
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE, WriteOnlyCell
from openpyxl.styles import Font

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(REPO_ROOT, "transformation", "metadata.db")
OUT_DIR = os.path.join(REPO_ROOT, "pii_test", "results_excel")
UUID_RE = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
VERDICTS = ["present", "permissible", "false_positive"]
SEVERITY = {"present": 0, "permissible": 1, "false_positive": 2}

FINAL_DIR = os.path.join(REPO_ROOT, "pii_test", "final_review")
MEMBER_DIRECTORY = ("judgment call: member directory that also gives relatives' names and "
                    "home addresses")

DATASET_COLUMNS = ["nid", "title", "catalog_title", "publisher", "lot", "final_result",
                   "pipeline_result", "what_it_holds", "review_note", "detections",
                   "detected_types", "flagged_columns", "note", "uuid"]
DETECTION_COLUMNS = ["nid", "title", "catalog_title", "publisher", "lot", "final_result",
                     "column", "column_verdict", "decided_by", "row_index",
                     "detected_as", "detected_value", "source", "what_it_holds", "uuid"]

README = [
    ("What this is", "PII test results for lots 1, 2 and 3 (dublin_core_metadata, "
                     "dublin_core_remaining, dublin_core_lot3), put together, after the "
                     "manual review of 2026-10-12 that removed the false detections."),
    ("Handle with care", "The Detections sheets hold the detected values themselves: real "
                         "names, phone numbers, email addresses and addresses. Do not share or "
                         "commit this file."),
    ("Datasets sheet", "One row per dataset: nid, title, catalogue, publisher, lot, final "
                       "result, the pipeline's result, what the dataset holds, number of "
                       "detections, what was detected, and the flagged columns with their "
                       "verdicts."),
    ("Detections sheet", "One row per detected value: the dataset (nid, title), the column, "
                         "the row, what it was detected as and the value. In the present and "
                         "permissible workbooks, only detections in columns that carry the "
                         "finding."),
    ("Removed detections sheet", "Present and permissible workbooks only: detections in the "
                                 "same datasets that sit in a column the pipeline rejected "
                                 "(place names, codes, numbers). Removed as false."),
    ("final_result", "present = personal data of private individuals; permissible = people "
                     "named in a public, official or professional role, or office and business "
                     "contacts; false_positive = not personal data; no_detections; not_scanned "
                     "(the note says why)."),
    ("pipeline_result", "What the pipeline decided before the review. Where it differs from "
                        "final_result, the review changed it."),
    ("what_it_holds / review_note", "From the review: what kind of data the dataset holds and, "
                                    "where the result was changed or the call is arguable, why. "
                                    "Rows marked 'judgment call' are permissible by the rule "
                                    "used and could be argued the other way; filter on the "
                                    "text to see them as sets."),
    ("column_verdict / decided_by", "The pipeline's verdict for that column of that file, and "
                                    "the rule (R1-R11) or the LLM judge (T3-judge) that gave it."),
    ("row_index", "Position of the row among the rows scanned; 0 is the first data row. The "
                  "scan read the first 250 rows of each file."),
    ("What was reviewed", "Every dataset the pipeline judged present or permissible in lots 2 "
                          "and 3 (852 rows). Datasets the pipeline judged false_positive or "
                          "found nothing in were not reviewed, so a file with personal data "
                          "that the scan missed is not in the present list. Two such files "
                          "were found by chance and added; their note says so."),
    ("Stray false values", "A kept column can still contain single false values (a place "
                           "name inside a column of person names). The review was per dataset "
                           "and column, not per value."),
    ("Not included", "KCC transcripts (no nid or title). Lot 1 files that kept their May 2026 "
                     "result are listed as no_detections with a note."),
]


def clean(value):
    """A cell value openpyxl will take: no control characters, within Excel's limit."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (int, float)):
        return value
    return ILLEGAL_CHARACTERS_RE.sub(" ", str(value))[:32000]


def write_sheet(workbook, name, frame, widths):
    sheet = workbook.create_sheet(name)
    for index, width in enumerate(widths):
        sheet.column_dimensions[chr(ord("A") + index)].width = width
    sheet.freeze_panes = "A2"
    header = []
    for column in frame.columns:
        cell = WriteOnlyCell(sheet, value=column)
        cell.font = Font(bold=True)
        header.append(cell)
    sheet.append(header)
    for row in frame.itertuples(index=False, name=None):
        cells = []
        for value in row:
            value = clean(value)
            if isinstance(value, str) and value[:1] == "=":
                # A detected value is text even when it starts like a formula.
                cell = WriteOnlyCell(sheet, value=value)
                cell.data_type = "s"
                cells.append(cell)
            else:
                cells.append(value)
        sheet.append(cells)


def write_workbook(path, datasets, detections, scope, removed=None, leave_out=()):
    workbook = Workbook(write_only=True)
    readme = pd.DataFrame([("Scope", scope)] + README, columns=["item", "meaning"])
    write_sheet(workbook, "Read me", readme, [28, 130])
    shown = [c for c in DATASET_COLUMNS if c not in leave_out]
    width = dict(zip(DATASET_COLUMNS, [12, 70, 45, 40, 6, 16, 16, 40, 60, 11, 34, 60, 40, 38]))
    write_sheet(workbook, "Datasets", datasets[shown], [width[c] for c in shown])
    widths = [12, 60, 40, 34, 6, 16, 30, 16, 24, 10, 22, 45, 10, 40, 38]
    if detections is not None:
        write_sheet(workbook, "Detections", detections[DETECTION_COLUMNS], widths)
    if removed is not None:
        write_sheet(workbook, "Removed detections", removed[DETECTION_COLUMNS], widths)
    workbook.save(path)
    count = "no detections sheet" if detections is None else f"{len(detections):,} detection(s)"
    if removed is not None:
        count += f", {len(removed):,} removed"
    print(f"{os.path.basename(path)}: {len(datasets):,} dataset(s), {count}, "
          f"{os.path.getsize(path) / 1e6:.1f} MB")


# -- loading -----------------------------------------------------------------

def shard_detections(stage_root):
    """Every pii_detections.csv under a staged folder, keyed like column_class.csv."""
    parts = []
    for path in sorted(glob.glob(os.path.join(stage_root, "*", "pii_detections.csv"))):
        part = pd.read_csv(path, dtype=str, keep_default_na=False)
        part["key"] = os.path.basename(os.path.dirname(path)) + "/" + part["file"]
        parts.append(part)
    found = pd.concat(parts, ignore_index=True)
    found["uuid"] = found["key"].str.extract(UUID_RE)[0]
    return found


def final_review(lot):
    """The review's decisions for a lot, one row per dataset, indexed by uuid."""
    review = pd.read_csv(os.path.join(FINAL_DIR, "final_results.csv"), dtype=str,
                         keep_default_na=False)
    return review[review["lot"] == str(lot)].drop_duplicates("uuid").set_index("uuid")


def kept_columns(lot):
    """{(uuid prefix, column)} the pipeline rejected and the review kept."""
    kept = pd.read_csv(os.path.join(FINAL_DIR, "kept_columns.csv"), dtype=str,
                       keep_default_na=False)
    kept = kept[kept["lot"] == str(lot)]
    return set(zip(kept["uuid_prefix"], kept["column"].str.strip()))


def folder_lot(lot, table, result_path, class_path, stage_root):
    """(datasets, detections) for a lot that was run from staged local files."""
    result = pd.read_csv(result_path, dtype=str, keep_default_na=False)
    result = result.drop_duplicates("uuid")               # lot 3 has one uuid on two rows
    column_class = pd.read_csv(class_path, dtype=str, keep_default_na=False)
    column_class["file_uuid"] = column_class["uuid"].str.extract(UUID_RE)[0]

    detections = shard_detections(stage_root).merge(
        column_class[["uuid", "column", "pii_class", "rule_id"]].rename(
            columns={"uuid": "key", "pii_class": "column_verdict", "rule_id": "decided_by"}),
        on=["key", "column"], how="left")

    flagged = (column_class.assign(item=column_class["column"].str.strip() + " ["
                                   + column_class["pii_class"] + "]")
               .groupby("file_uuid")["item"].agg("; ".join).rename("flagged_columns"))
    review = final_review(lot)

    scanned = result["pii_status"].isin(VERDICTS + ["no_detections"])
    pipeline = result["pii_status"].where(scanned, "not_scanned")
    datasets = pd.DataFrame({
        "nid": result["nid"], "title": result["title"], "catalog_title": result["catalog_title"],
        "publisher": result["publisher"], "lot": lot,
        "final_result": result["uuid"].map(review["final_result"]).fillna(pipeline),
        "pipeline_result": pipeline,
        "what_it_holds": result["uuid"].map(review["holds"]).fillna(""),
        "review_note": result["uuid"].map(review["note"]).fillna(""),
        "detections": pd.to_numeric(result["entity_count"], errors="coerce").fillna(0).astype(int),
        "detected_types": result["pii_types"],
        "flagged_columns": result["uuid"].map(flagged).fillna(""),
        "note": (result["pii_status"].where(~scanned, "") + " " + result["note"]).str.strip(),
        "uuid": result["uuid"],
    })
    info = datasets.set_index("uuid")
    keep = kept_columns(lot)
    rescued = pd.Series([(u[:8], c.strip()) in keep
                         for u, c in zip(detections["uuid"], detections["column"])],
                        index=detections.index)
    detections = pd.DataFrame({
        "nid": detections["uuid"].map(info["nid"]), "title": detections["uuid"].map(info["title"]),
        "catalog_title": detections["uuid"].map(info["catalog_title"]),
        "publisher": detections["uuid"].map(info["publisher"]), "lot": lot,
        "final_result": detections["uuid"].map(info["final_result"]),
        "column": detections["column"], "column_verdict": detections["column_verdict"],
        "decided_by": detections["decided_by"],
        "row_index": pd.to_numeric(detections["row_index"], errors="coerce"),
        "detected_as": detections["entity_type"], "detected_value": detections["entity_text"],
        "source": detections["source"],
        "what_it_holds": detections["uuid"].map(info["what_it_holds"]),
        "uuid": detections["uuid"],
        "in_kept_column": (detections["column_verdict"] != "false_positive") | rescued,
    })
    print(f"lot {lot} ({table}): {len(datasets):,} datasets, {len(detections):,} detections")
    return datasets, detections


def lot1(snapshot_path):
    """(datasets, detections) for lot 1, from metadata.db and the September flag snapshot."""
    con = duckdb.connect(DB_PATH, read_only=True)
    table = con.execute('''
        SELECT nid, "Identifier[UUID]" AS uuid, "Title" AS title,
               "Relation[Catalog Title]" AS catalog_title,
               "Publisher[ministry_department]" AS publisher
        FROM dublin_core_metadata ORDER BY nid''').fetch_df()
    column_class = con.execute('''
        SELECT uuid, "column", pii_class, rule_id FROM pii_column_class WHERE lot = 1''').fetch_df()
    dataset_class = con.execute(
        "SELECT uuid, pii_class, n_detections FROM pii_dataset_class WHERE lot = 1").fetch_df()
    found = con.execute('''
        SELECT uuid, "column", row_index, entity_type, entity_text, source
        FROM pii_detections_lot1''').fetch_df()
    snapshot = con.execute(f'''
        SELECT "Identifier[UUID]" AS uuid, pii_tested, pii_test_timestamp
        FROM read_parquet('{snapshot_path}')''').fetch_df()
    con.close()

    snapshot = snapshot.set_index("uuid")
    tested = table["uuid"].map(snapshot["pii_tested"]).fillna(False).astype(bool)
    stamp = pd.to_datetime(table["uuid"].map(snapshot["pii_test_timestamp"]))
    old = tested & (stamp < pd.Timestamp("2026-09-01"))
    verdict = table["uuid"].map(dataset_class.set_index("uuid")["pii_class"])
    result = verdict.fillna("no_detections").where(tested, "not_scanned")
    note = pd.Series("", index=table.index)
    note[old] = "result from the May 2026 pass; not re-scanned in September"
    note[~tested] = "file could not be read in the September re-scan"

    flagged = (column_class.assign(item=column_class["column"].str.strip() + " ["
                                   + column_class["pii_class"] + "]")
               .groupby("uuid")["item"].agg("; ".join))
    types = found.groupby("uuid")["entity_type"].agg(lambda s: ",".join(sorted(set(s))))
    # Lot 1 was closed as it stands: its verdicts are the pipeline's. The eight
    # permissible files are six member directories and two hospital contact lists.
    flagged_text = table["uuid"].map(flagged).fillna("")
    permissible = result == "permissible"
    directory = permissible & flagged_text.str.contains("Father Name", regex=False)
    holds = pd.Series("", index=table.index)
    holds[permissible] = "office or business contacts"
    holds[directory] = "named people in a public or professional role"
    datasets = pd.DataFrame({
        "nid": table["nid"], "title": table["title"], "catalog_title": table["catalog_title"],
        "publisher": table["publisher"], "lot": 1, "final_result": result,
        "pipeline_result": result, "what_it_holds": holds,
        "review_note": pd.Series("", index=table.index).where(~directory, MEMBER_DIRECTORY),
        "detections": table["uuid"].map(dataset_class.set_index("uuid")["n_detections"]).fillna(0).astype(int),
        "detected_types": table["uuid"].map(types).fillna(""),
        "flagged_columns": flagged_text,
        "note": note, "uuid": table["uuid"],
    })
    info = datasets.set_index("uuid")
    found = found.merge(column_class.rename(columns={"pii_class": "column_verdict",
                                                     "rule_id": "decided_by"}),
                        on=["uuid", "column"], how="left")
    detections = pd.DataFrame({
        "nid": found["uuid"].map(info["nid"]), "title": found["uuid"].map(info["title"]),
        "catalog_title": found["uuid"].map(info["catalog_title"]),
        "publisher": found["uuid"].map(info["publisher"]), "lot": 1,
        "final_result": found["uuid"].map(info["final_result"]),
        "column": found["column"], "column_verdict": found["column_verdict"],
        "decided_by": found["decided_by"], "row_index": found["row_index"],
        "detected_as": found["entity_type"], "detected_value": found["entity_text"],
        "source": found["source"], "what_it_holds": found["uuid"].map(info["what_it_holds"]),
        "uuid": found["uuid"],
        "in_kept_column": found["column_verdict"] != "false_positive",
    })
    print(f"lot 1 (dublin_core_metadata): {len(datasets):,} datasets, {len(detections):,} detections")
    return datasets, detections


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lot1-snapshot", required=True,
                        help="local copy of s3://nic-ogdp-datasets/pii-results/"
                             "dublin_core_metadata_snapshot.parquet")
    args = parser.parse_args()

    pii = os.path.join(REPO_ROOT, "pii_test")
    data = os.path.join(REPO_ROOT, "data")
    lots = [
        lot1(args.lot1_snapshot),
        folder_lot(2, "dublin_core_remaining", os.path.join(pii, "lot2", "lot2_pii_result.csv"),
                   os.path.join(pii, "lot2", "classification", "column_class.csv"),
                   os.path.join(data, "lot2_pii_stage")),
        folder_lot(3, "dublin_core_lot3", os.path.join(pii, "lot3", "lot3_pii_result.csv"),
                   os.path.join(pii, "lot3", "classification", "column_class.csv"),
                   os.path.join(data, "lot3_pii_stage")),
    ]
    datasets = pd.concat([d for d, _ in lots], ignore_index=True)
    detections = pd.concat([d for _, d in lots], ignore_index=True)

    order = datasets["final_result"].map(SEVERITY).fillna(9)
    datasets = datasets.assign(_o=order).sort_values(["_o", "lot", "nid"]).drop(columns="_o")
    detections = (detections.assign(_o=detections["final_result"].map(SEVERITY).fillna(9))
                  .sort_values(["_o", "lot", "nid", "column", "row_index"]).drop(columns="_o"))
    # A detection stands when its dataset holds personal data and its column was not rejected.
    stands = detections["final_result"].isin(["present", "permissible"]) & detections["in_kept_column"]

    print("\nfinal result by lot:")
    print(pd.crosstab(datasets["final_result"], datasets["lot"], margins=True).to_string())
    print("\npipeline result -> final result:")
    print(pd.crosstab(datasets["pipeline_result"], datasets["final_result"]).to_string())
    print("\ndetections that stand, by final result and lot:")
    print(pd.crosstab(detections.loc[stands, "final_result"], detections.loc[stands, "lot"],
                      margins=True).to_string())
    print(f"detections removed as false: {int((~stands).sum()):,} of {len(detections):,}\n")

    os.makedirs(OUT_DIR, exist_ok=True)
    write_workbook(os.path.join(OUT_DIR, "PII_results_all_datasets.xlsx"), datasets, detections,
                   "Every dataset of lots 1, 2 and 3 with its final result, and every detection, "
                   "kept or removed.")
    # The same Datasets sheet on its own: the full workbook is ~50 MB, and the three
    # verdict workbooks below already hold every detection between them. The uuid
    # column is left out to keep it under the 30 MiB a file can be sent at; nid
    # identifies the dataset.
    write_workbook(os.path.join(OUT_DIR, "PII_all_datasets_list.xlsx"), datasets, None,
                   "Every dataset of lots 1, 2 and 3 with its final result. The detections are in "
                   "PII_present.xlsx, PII_permissible.xlsx and PII_false_positive.xlsx. No uuid "
                   "column here (file size); the other workbooks have it.",
                   leave_out=("uuid",))
    for verdict in ("present", "permissible"):
        mine = detections["final_result"] == verdict
        write_workbook(os.path.join(OUT_DIR, f"PII_{verdict}.xlsx"),
                       datasets[datasets["final_result"] == verdict],
                       detections[mine & stands],
                       f"The datasets finally judged `{verdict}`, and the detections in the "
                       "columns that carry the finding.",
                       removed=detections[mine & ~stands])
    write_workbook(os.path.join(OUT_DIR, "PII_false_positive.xlsx"),
                   datasets[datasets["final_result"] == "false_positive"],
                   detections[detections["final_result"] == "false_positive"],
                   "The false detections: datasets finally judged `false_positive` (not personal "
                   "data), and every detection in them.")


if __name__ == "__main__":
    main()
