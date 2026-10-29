"""Final PII results of lots 2 and 3: the review, the test timestamps, the Excel workbooks.

Replaces build_final_review.py, export_pii_test_timestamps.py and export_results_excel.py.

    python pii_test/pipeline/report.py review
    python pii_test/pipeline/report.py stamps
    python pii_test/pipeline/report.py excel --lot1-snapshot PATH/lot1_snapshot.parquet

Everything is read from the real folders (pii_test/lot2, lot3, final_review, the staged
shards in data/) and written under --out, in the same places relative to it:

    OUT/pii_test/final_review/final_results.csv, kept_columns.csv      review
    OUT/pii_test/final_review/pii_test_timestamps_lots_2_3.csv         stamps
    OUT/data/pii_test_timestamps_lots_2_3.csv                          stamps
    OUT/pii_test/results_excel/*.xlsx                                  excel

--out defaults to pii_test/pipeline/out, so a test run touches nothing real. Pass the
repo root to write over the real files. `review` holds the manual review of 2026-10-12;
`stamps` and `excel` read its result from --final (default: the real final_review).

review   The pipeline's `present` and `permissible` verdicts over-call. On 2026-10-12
         every dataset the pipeline judged `present` (231 in lot 2, 237 rows in lot 3)
         or `permissible` (256 and 128) was read again: title, headers, the flagged
         columns and their detected values, and the cells where that was not enough.
         This holds what that review decided. It changes no pipeline output, and a
         pipeline re-run does not carry these decisions forward. The three final
         classes are the pipeline's own:

             present         personal data of private individuals: beneficiaries,
                             patients, victims, accused, owners or next of kin, or a
                             register that gives relatives' names, date of birth or
                             community
             permissible     people named in a public, official or professional role,
                             and the contact details of offices, institutions and
                             businesses
             false_positive  not personal data: place, scheme, institution and disease
                             names read as people, ordinary numbers read as phone or
                             Aadhaar numbers

         Starting point for a `present` dataset is the first reading in
         lot{2,3}_present_groups.csv; CORRECTIONS are where the second reading
         disagreed. A `permissible` dataset keeps its verdict unless it is in
         PERMISSIBLE_FALSE. ADDED are files the scan could not read at all.

stamps   One row per dataset with the time its file was scanned (UTC, from the lot's
         scan log; the latest one where a file was scanned more than once).
         final_review file: checked datasets only, nid, lot, pii_test_timestamp,
         pii_present. data file: every dataset of the lot's table, nid, uuid, lot,
         pii_tested, pii_detected, pii_test_timestamp. pii_detected is the same as
         pii_present (the user's choice, 2026-10-14), blank when not tested. Lot 1's
         pii_detected is the scan's own flag instead.

excel    Five workbooks with one row per detection, the final result beside the
         pipeline's own. The Detections sheets hold the detected values themselves
         (real names, phone numbers and addresses): review on this server only, never
         commit or pass on. Lot 1 comes from metadata.db and the flag snapshot the
         September re-scan uploaded to S3; lots 2 and 3 from the per-shard
         pii_detections.csv files. KCC is not here: it has no nid or title.
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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PII = os.path.join(ROOT, "pii_test")
DB = os.path.join(ROOT, "transformation", "metadata.db")
UUID = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
KW = dict(dtype=str, keep_default_na=False)
VERDICTS = ["present", "permissible", "false_positive"]
SEVERITY = {"present": 0, "permissible": 1, "false_positive": 2}
CHECKED = {"no_detections", "false_positive", "permissible", "present"}
# 2026-10-08 06:15:30 [INFO] [s000 1/1200] <uuid>.csv | rows=0 pii=False ...
SCAN = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d) \[INFO\] \[\w+ \d+/\d+\] " + UUID
                  + r"\.\w+ \| rows=\d+ pii=(True|False) ")

PRIVATE = "private individuals"
ROLE = "named people in a public or professional role"
OFFICE = "office or business contacts"
NOTPII = "not personal data"

# First reading (group letter in lot*_present_groups.csv) -> (final result, what it holds).
FIRST = {
    2: {"A": ("present", PRIVATE), "B": ("permissible", ROLE),
        "C": ("permissible", OFFICE), "D": ("false_positive", NOTPII)},
    3: {"A": ("present", PRIVATE), "B": ("permissible", ROLE), "C": ("permissible", ROLE),
        "D": ("permissible", OFFICE), "E": ("false_positive", NOTPII)},
}

# Where the second reading disagreed with the first: uuid prefix -> (final, holds, why).
CORRECTIONS = {
    2: {
        "f8397904": ("present", PRIVATE,
                     "missing-children cases: girls aged 15-17 named with father's name, home "
                     "address, mobile number and caste"),
        "6dfdd7da": ("present", PRIVATE,
                     "traffic-accident victims named with address, mobile number, caste and "
                     "occupation"),
        "8d7d991e": ("present", PRIVATE,
                     "merchant registration survey: proprietors' PAN numbers, names, mobile "
                     "numbers and IP addresses"),
        "f9419172": ("permissible", ROLE, "named doctors and service-centre operators with locality"),
        "4da4dbd2": ("permissible", ROLE, "named service-centre operators with business address"),
        "8a6e8694": ("permissible", ROLE, "free text naming a college founder and an acting principal"),
    },
    3: {
        "2bf5e7f0": ("false_positive", NOTPII, "the beneficiary is a workers' union, not a person"),
        "7fff4e1c": ("false_positive", NOTPII, "constituency names"),
        # Advocate rolls that go beyond name and address.
        "a1d912ee": ("present", PRIVATE, "advocate roll with father's name, address and phone"),
        "c0cc1127": ("present", PRIVATE, "advocate roll with father's name, address and phone"),
        "10205f8f": ("present", PRIVATE, "advocate roll with date of birth and community"),
        "492f1bd5": ("present", PRIVATE,
                     "advocate roll with date of birth, father's and husband's name, community"),
        "ba059a7f": ("present", PRIVATE, "advocate roll with father's name and date of birth"),
        "bc30d4fe": ("permissible", OFFICE, "one office address and landline among statistics"),
        "dd18336f": ("permissible", OFFICE, "one office address and landline among statistics"),
        "bdbde33c": ("permissible", OFFICE, "service-centre landlines"),
        "5cbeb76f": ("permissible", ROLE, "one contractor named"),
    },
}

# Pipeline `permissible` datasets that are false detections. A catalogue entry takes
# every permissible dataset of that catalogue whose flagged columns are all in the set.
PERMISSIBLEFALSE = {
    2: {
        "03b0094f": "college names", "31e16f75": "college names",
        "d6eab018": "student/faculty ratios read as phone numbers",
        "7da55270": "city names", "07df5cfe": "hospital addresses", "51833678": "a locality name",
        "f6b5a8d8": "school names", "27ecd279": "school names",
        "e6860bae": "project numbers read as phone numbers",
        "c54acf87": "a volume read as a phone number", "bdafc6e5": "a volume read as a phone number",
        "f9ff3de2": "project names", "19ed7dc5": "institute addresses",
        "459bd56a": "amounts read as phone and Aadhaar numbers",
        "cf9bc4a4": "an amount read as a phone number", "99f16a41": "a system name",
    },
    3: {
        "b9113f69": "political party names", "6772a536": "political party names",
        "9e5e965d": "political party names", "3729002f": "political party names",
        "d8cd3611": "an abbreviation", "65632b8b": "department names",
    },
}
PERMISSIBLECATALOGUES = {
    2: [("Mission Antyodaya Survey Data", {"GP NAME"}, "gram panchayat names")],
    3: [],
}

# Files the scan read nothing from (base64-encoded JSON saved as .csv), found by
# looking at the neighbours of confirmed findings.
ADDED = {
    2: {
        "45035150": ("present", PRIVATE,
                     "added by review: 100 COVID patients with name, address, age, mobile number "
                     "and comorbidity, base64-encoded so the scan read nothing"),
        "008aeb86": ("permissible", ROLE,
                     "added by review: hospital in-charge names and contact numbers, "
                     "base64-encoded so the scan read nothing"),
    },
    3: {},
}

# Columns the pipeline rejected that do hold personal data (dataset stays `present`).
KEPT = [
    (2, "f26b2921", "enumerator_name", "field staff names"),
    (2, "bd9bdf79", "individual_owner_name", "scheme owners' names"),
    (2, "b7803577", "Name Beneficiary", "beneficiaries' names (single-word names)"),
    (2, "a54c9ed9", "Allegation in Brief", "people named in the allegation text"),
    (2, "8d7d991e", "Unnamed: 25", "PAN numbers"),
    (3, "492f1bd5", "ADDRESS", "a person named in the address"),
]

# Arguable calls, marked so they can be filtered and flipped as a set.
DIRECTORY = ("judgment call: member directory that also gives relatives' names and "
             "home addresses")
REGISTER = ("judgment call: professional register of advocates or notaries (name and address, "
            "sometimes a phone number)")
STUDENTS = "judgment call: students, trainees or research fellows named"
OPERATORS = "judgment call: service-centre operators listed with their mobile numbers"
OTHERCALLS = {
    2: {
        "d800da24": STUDENTS, "3b13f438": STUDENTS, "c718b2f4": STUDENTS, "d81281ed": STUDENTS,
        "a2c7ce89": STUDENTS,
        "8ac38867": "judgment call: volunteer animal rescuers named with mobile numbers",
        "a8116d49": "judgment call: child day-care workers named",
        "ab76eef4": "judgment call: self-help group contact numbers and addresses",
        "fd945b55": "judgment call: leaders of insurgent groups named",
        "daae37e8": OPERATORS, "94d19335": OPERATORS,
    },
    3: {"7774dbc6": OPERATORS, "6d8723cc": OPERATORS, "c21a7382": OPERATORS,
        "f58b58ae": OPERATORS},
}
REGISTERS = ("All India Advocate List",
             "State-wise List of Notaries Appointed by the Central Government")

DATASETCOLS = ["nid", "title", "catalog_title", "publisher", "lot", "final_result",
               "pipeline_result", "what_it_holds", "review_note", "detections",
               "detected_types", "flagged_columns", "note", "uuid"]
DETECTIONCOLS = ["nid", "title", "catalog_title", "publisher", "lot", "final_result",
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


def review(out):
    """Write final_results.csv and kept_columns.csv."""
    rows = []
    for lot in (2, 3):
        result = pd.read_csv(os.path.join(PII, f"lot{lot}", f"lot{lot}_pii_result.csv"), **KW)
        groups = (pd.read_csv(os.path.join(PII, f"lot{lot}", f"lot{lot}_present_groups.csv"), **KW)
                  .drop_duplicates("uuid").set_index("uuid")["group"])
        cc = pd.read_csv(os.path.join(PII, f"lot{lot}", "classification", "column_class.csv"),
                         usecols=["uuid", "column", "pii_class"], **KW)
        cc = cc[cc["pii_class"] != "false_positive"]
        cc["file"] = cc["uuid"].str.extract(UUID)[0]
        columns = cc.groupby("file")["column"].agg(lambda s: {c.strip() for c in s}).to_dict()

        for row in result.itertuples(index=False):
            pipeline = row.pii_status
            note = ""
            if pipeline == "present":
                final_class, holds = FIRST[lot][groups[row.uuid][0]]
                fixed = CORRECTIONS[lot].get(row.uuid[:8])
                if fixed:
                    final_class, holds, note = fixed
            elif pipeline == "permissible":
                final_class, holds = "permissible", "public role or office contact (pipeline verdict kept)"
                why = PERMISSIBLEFALSE[lot].get(row.uuid[:8])
                for catalogue, only, reason in PERMISSIBLECATALOGUES[lot]:
                    if row.catalog_title.strip() == catalogue and columns.get(row.uuid, set()) <= only:
                        why = reason
                if why:
                    final_class, holds, note = "false_positive", NOTPII, why
            elif ADDED[lot].get(row.uuid[:8]):
                final_class, holds, note = ADDED[lot][row.uuid[:8]]
            else:
                continue

            if final_class == "permissible" and not note:
                if "Father Name" in columns.get(row.uuid, set()):
                    note = DIRECTORY
                elif row.catalog_title.strip().startswith(REGISTERS):
                    note = REGISTER
                else:
                    note = OTHERCALLS[lot].get(row.uuid[:8]) or ""
            rows.append({"lot": lot, "nid": row.nid, "uuid": row.uuid, "title": row.title,
                         "catalog_title": row.catalog_title, "publisher": row.publisher,
                         "pipeline_result": pipeline, "final_result": final_class,
                         "holds": holds, "changed": "yes" if final_class != pipeline else "no",
                         "note": note})
    reviewed = pd.DataFrame(rows)

    folder = os.path.join(out, "pii_test", "final_review")
    os.makedirs(folder, exist_ok=True)
    reviewed.to_csv(os.path.join(folder, "final_results.csv"), index=False)
    pd.DataFrame(KEPT, columns=["lot", "uuid_prefix", "column", "holds"]).to_csv(
        os.path.join(folder, "kept_columns.csv"), index=False)

    for lot, part in reviewed.groupby("lot"):
        print(f"\nlot {lot}: {len(part)} rows reviewed "
              f"({part['uuid'].nunique()} distinct datasets)")
        print(pd.crosstab(part["pipeline_result"], part["final_result"], margins=True).to_string())
    calls = reviewed[reviewed["note"].str.startswith("judgment call")]
    print("\njudgment calls:")
    print(calls.groupby(["lot", "note"]).size().to_string())
    print(f"\nwrote {folder}/final_results.csv and kept_columns.csv")


def stamps(out, final):
    """Write the two timestamp files."""
    decided = pd.read_csv(os.path.join(final, "final_results.csv"), **KW)
    checked, flags = [], []
    for lot in (2, 3):
        latest = {}
        with open(os.path.join(PII, f"lot{lot}", f"lot{lot}_scan.log"), errors="replace") as fh:
            for line in fh:
                m = SCAN.match(line)
                if m:
                    stamp = f"{m.group(1)}T{m.group(2)}"
                    if stamp >= latest.get(m.group(3), ("",))[0]:
                        latest[m.group(3)] = (stamp, m.group(4) == "True")
        # dublin_core_lot3 holds one dataset twice (same nid and uuid).
        result = pd.read_csv(os.path.join(PII, f"lot{lot}", f"lot{lot}_pii_result.csv"),
                             usecols=["nid", "uuid", "pii_status"], **KW).drop_duplicates(["nid", "uuid"])
        present = set(decided.loc[(decided["lot"] == str(lot)) & (decided["final_result"] == "present"),
                                  "uuid"])

        done = result[result["pii_status"].isin(CHECKED)]
        checked.append(pd.DataFrame({
            "nid": done["nid"], "lot": lot,
            "pii_test_timestamp": done["uuid"].map(lambda u: latest[u][0]),
            "pii_present": done["uuid"].isin(present)}))

        nonid = result["nid"] == ""
        if nonid.any():
            print(f"lot {lot}: left out {nonid.sum()} row(s) with no nid, uuid "
                  f"{', '.join(result.loc[nonid, 'uuid'])}")
        result = result[~nonid]
        tested = result["pii_status"].isin(CHECKED)
        assert (tested == result["uuid"].isin(latest)).all(), "tested status and scan log disagree"
        flags.append(pd.DataFrame({
            "nid": result["nid"], "uuid": result["uuid"], "lot": lot, "pii_tested": tested,
            "pii_detected": result["uuid"].isin(present).where(tested, None),
            "pii_test_timestamp": result["uuid"].map(lambda u: latest[u][0] if u in latest else "")}))

    checked = pd.concat(checked, ignore_index=True)
    assert not checked.duplicated(["lot", "nid"]).any(), "a nid is repeated within a lot"
    assert (checked["nid"] != "").all() and (checked["pii_test_timestamp"] != "").all()
    flags = pd.concat(flags, ignore_index=True)
    assert not flags.duplicated(["lot", "nid"]).any(), "a nid is repeated within a lot"
    assert (flags["uuid"] != "").all()
    blank = flags["pii_test_timestamp"] == ""
    assert (blank == ~flags["pii_tested"]).all() and (blank == flags["pii_detected"].isna()).all()
    assert (flags["pii_detected"] == True).sum() == checked["pii_present"].sum()

    first = os.path.join(out, "pii_test", "final_review", "pii_test_timestamps_lots_2_3.csv")
    second = os.path.join(out, "data", "pii_test_timestamps_lots_2_3.csv")
    os.makedirs(os.path.dirname(first), exist_ok=True)
    os.makedirs(os.path.dirname(second), exist_ok=True)
    checked.to_csv(first, index=False)
    flags.to_csv(second, index=False)
    for lot, part in checked.groupby("lot"):
        print(f"lot {lot}: {len(part)} datasets checked, {part['pii_present'].sum()} with PII "
              f"present, scanned {part['pii_test_timestamp'].min()} to "
              f"{part['pii_test_timestamp'].max()}")
    for lot, part in flags.groupby("lot"):
        print(f"lot {lot}: {len(part)} datasets, {part['pii_tested'].sum()} tested, "
              f"{(part['pii_detected'] == True).sum()} pii_detected")
    print(f"wrote {first}\nwrote {second}")


def lotframes(lot, final):
    """(datasets, detections) for lot 2 or 3, from the result file and the staged shards."""
    folder = os.path.join(PII, f"lot{lot}")
    result = pd.read_csv(os.path.join(folder, f"lot{lot}_pii_result.csv"), **KW)
    result = result.drop_duplicates("uuid")               # lot 3 has one uuid on two rows
    cc = pd.read_csv(os.path.join(folder, "classification", "column_class.csv"), **KW)
    cc["file"] = cc["uuid"].str.extract(UUID)[0]

    parts = []
    for path in sorted(glob.glob(os.path.join(ROOT, "data", f"lot{lot}_pii_stage", "*",
                                              "pii_detections.csv"))):
        part = pd.read_csv(path, **KW)
        part["key"] = os.path.basename(os.path.dirname(path)) + "/" + part["file"]
        parts.append(part)
    found = pd.concat(parts, ignore_index=True)
    found["uuid"] = found["key"].str.extract(UUID)[0]
    detections = found.merge(
        cc[["uuid", "column", "pii_class", "rule_id"]].rename(
            columns={"uuid": "key", "pii_class": "column_verdict", "rule_id": "decided_by"}),
        on=["key", "column"], how="left")

    flagged = (cc.assign(item=cc["column"].str.strip() + " [" + cc["pii_class"] + "]")
               .groupby("file")["item"].agg("; ".join).rename("flagged_columns"))
    decided = pd.read_csv(os.path.join(final, "final_results.csv"), **KW)
    decided = decided[decided["lot"] == str(lot)].drop_duplicates("uuid").set_index("uuid")

    scanned = result["pii_status"].isin(VERDICTS + ["no_detections"])
    pipeline = result["pii_status"].where(scanned, "not_scanned")
    datasets = pd.DataFrame({
        "nid": result["nid"], "title": result["title"], "catalog_title": result["catalog_title"],
        "publisher": result["publisher"], "lot": lot,
        "final_result": result["uuid"].map(decided["final_result"]).fillna(pipeline),
        "pipeline_result": pipeline,
        "what_it_holds": result["uuid"].map(decided["holds"]).fillna(""),
        "review_note": result["uuid"].map(decided["note"]).fillna(""),
        "detections": pd.to_numeric(result["entity_count"], errors="coerce").fillna(0).astype(int),
        "detected_types": result["pii_types"],
        "flagged_columns": result["uuid"].map(flagged).fillna(""),
        "note": (result["pii_status"].where(~scanned, "") + " " + result["note"]).str.strip(),
        "uuid": result["uuid"],
    })
    info = datasets.set_index("uuid")
    kept = pd.read_csv(os.path.join(final, "kept_columns.csv"), **KW)
    kept = kept[kept["lot"] == str(lot)]
    keep = set(zip(kept["uuid_prefix"], kept["column"].str.strip()))
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
    print(f"lot {lot}: {len(datasets):,} datasets, {len(detections):,} detections")
    return datasets, detections


def lotone(snapshot):
    """(datasets, detections) for lot 1, from metadata.db and the September flag snapshot."""
    con = duckdb.connect(DB, read_only=True)
    table = con.execute('''
        SELECT nid, "Identifier[UUID]" AS uuid, "Title" AS title,
               "Relation[Catalog Title]" AS catalog_title,
               "Publisher[ministry_department]" AS publisher
        FROM dublin_core_metadata ORDER BY nid''').fetch_df()
    cc = con.execute('''
        SELECT uuid, "column", pii_class, rule_id FROM pii_column_class WHERE lot = 1''').fetch_df()
    dataset = con.execute(
        "SELECT uuid, pii_class, n_detections FROM pii_dataset_class WHERE lot = 1").fetch_df()
    found = con.execute('''
        SELECT uuid, "column", row_index, entity_type, entity_text, source
        FROM pii_detections_lot1''').fetch_df()
    snap = con.execute(f'''
        SELECT "Identifier[UUID]" AS uuid, pii_tested, pii_test_timestamp
        FROM read_parquet('{snapshot}')''').fetch_df()
    con.close()

    snap = snap.set_index("uuid")
    tested = table["uuid"].map(snap["pii_tested"]).fillna(False).astype(bool)
    stamp = pd.to_datetime(table["uuid"].map(snap["pii_test_timestamp"]))
    old = tested & (stamp < pd.Timestamp("2026-09-01"))
    verdict = table["uuid"].map(dataset.set_index("uuid")["pii_class"])
    result = verdict.fillna("no_detections").where(tested, "not_scanned")
    note = pd.Series("", index=table.index)
    note[old] = "result from the May 2026 pass; not re-scanned in September"
    note[~tested] = "file could not be read in the September re-scan"

    flagged = (cc.assign(item=cc["column"].str.strip() + " [" + cc["pii_class"] + "]")
               .groupby("uuid")["item"].agg("; ".join))
    types = found.groupby("uuid")["entity_type"].agg(lambda s: ",".join(sorted(set(s))))
    # Lot 1 was closed as it stands: its verdicts are the pipeline's. The eight
    # permissible files are six member directories and two hospital contact lists.
    flaggedtext = table["uuid"].map(flagged).fillna("")
    permissible = result == "permissible"
    directory = permissible & flaggedtext.str.contains("Father Name", regex=False)
    holds = pd.Series("", index=table.index)
    holds[permissible] = "office or business contacts"
    holds[directory] = "named people in a public or professional role"
    datasets = pd.DataFrame({
        "nid": table["nid"], "title": table["title"], "catalog_title": table["catalog_title"],
        "publisher": table["publisher"], "lot": 1, "final_result": result,
        "pipeline_result": result, "what_it_holds": holds,
        "review_note": pd.Series("", index=table.index).where(~directory, DIRECTORY),
        "detections": table["uuid"].map(dataset.set_index("uuid")["n_detections"]).fillna(0).astype(int),
        "detected_types": table["uuid"].map(types).fillna(""),
        "flagged_columns": flaggedtext,
        "note": note, "uuid": table["uuid"],
    })
    info = datasets.set_index("uuid")
    found = found.merge(cc.rename(columns={"pii_class": "column_verdict", "rule_id": "decided_by"}),
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
    print(f"lot 1: {len(datasets):,} datasets, {len(detections):,} detections")
    return datasets, detections


def workbook(path, datasets, detections, scope, removed=None, leaveout=()):
    """Write one workbook: Read me, Datasets, and the Detections sheets that are given."""
    book = Workbook(write_only=True)
    shown = [c for c in DATASETCOLS if c not in leaveout]
    width = dict(zip(DATASETCOLS, [12, 70, 45, 40, 6, 16, 16, 40, 60, 11, 34, 60, 40, 38]))
    widths = [12, 60, 40, 34, 6, 16, 30, 16, 24, 10, 22, 45, 10, 40, 38]
    sheets = [("Read me", pd.DataFrame([("Scope", scope)] + README, columns=["item", "meaning"]),
               [28, 130]),
              ("Datasets", datasets[shown], [width[c] for c in shown])]
    if detections is not None:
        sheets.append(("Detections", detections[DETECTIONCOLS], widths))
    if removed is not None:
        sheets.append(("Removed detections", removed[DETECTIONCOLS], widths))
    for name, frame, sizes in sheets:
        sheet = book.create_sheet(name)
        for index, size in enumerate(sizes):
            sheet.column_dimensions[chr(ord("A") + index)].width = size
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
                # A value openpyxl will take: no control characters, within Excel's limit.
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    value = ""
                elif not isinstance(value, (int, float)):
                    value = ILLEGAL_CHARACTERS_RE.sub(" ", str(value))[:32000]
                if isinstance(value, str) and value[:1] == "=":
                    # A detected value is text even when it starts like a formula.
                    cell = WriteOnlyCell(sheet, value=value)
                    cell.data_type = "s"
                    cells.append(cell)
                else:
                    cells.append(value)
            sheet.append(cells)
    book.save(path)
    count = "no detections sheet" if detections is None else f"{len(detections):,} detection(s)"
    if removed is not None:
        count += f", {len(removed):,} removed"
    print(f"{os.path.basename(path)}: {len(datasets):,} dataset(s), {count}, "
          f"{os.path.getsize(path) / 1e6:.1f} MB")


def excel(out, final, snapshot):
    """Write the five workbooks."""
    lots = [lotone(snapshot), lotframes(2, final), lotframes(3, final)]
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

    folder = os.path.join(out, "pii_test", "results_excel")
    os.makedirs(folder, exist_ok=True)
    workbook(os.path.join(folder, "PII_results_all_datasets.xlsx"), datasets, detections,
             "Every dataset of lots 1, 2 and 3 with its final result, and every detection, "
             "kept or removed.")
    # The same Datasets sheet on its own: the full workbook is ~50 MB, and the three
    # verdict workbooks below already hold every detection between them. The uuid
    # column is left out to keep it under the 30 MiB a file can be sent at; nid
    # identifies the dataset.
    workbook(os.path.join(folder, "PII_all_datasets_list.xlsx"), datasets, None,
             "Every dataset of lots 1, 2 and 3 with its final result. The detections are in "
             "PII_present.xlsx, PII_permissible.xlsx and PII_false_positive.xlsx. No uuid "
             "column here (file size); the other workbooks have it.",
             leaveout=("uuid",))
    for verdict in ("present", "permissible"):
        mine = detections["final_result"] == verdict
        workbook(os.path.join(folder, f"PII_{verdict}.xlsx"),
                 datasets[datasets["final_result"] == verdict], detections[mine & stands],
                 f"The datasets finally judged `{verdict}`, and the detections in the "
                 "columns that carry the finding.",
                 removed=detections[mine & ~stands])
    workbook(os.path.join(folder, "PII_false_positive.xlsx"),
             datasets[datasets["final_result"] == "false_positive"],
             detections[detections["final_result"] == "false_positive"],
             "The false detections: datasets finally judged `false_positive` (not personal "
             "data), and every detection in them.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["review", "stamps", "excel"])
    parser.add_argument("--out", default=os.path.join(PII, "pipeline", "out"),
                        help="write under this root, laid out like the repo (default: "
                             "pii_test/pipeline/out; pass the repo root to overwrite the real files)")
    parser.add_argument("--final", default=os.path.join(PII, "final_review"),
                        help="folder holding final_results.csv and kept_columns.csv")
    parser.add_argument("--lot1-snapshot",
                        help="excel only: local copy of s3://nic-ogdp-datasets/pii-results/"
                             "dublin_core_metadata_snapshot.parquet")
    args = parser.parse_args()
    if args.step == "review":
        review(args.out)
    elif args.step == "stamps":
        stamps(args.out, args.final)
    else:
        if not args.lot1_snapshot:
            parser.error("excel needs --lot1-snapshot")
        excel(args.out, args.final, args.lot1_snapshot)
