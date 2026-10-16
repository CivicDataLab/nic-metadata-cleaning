"""PII test timestamp and flags per dataset, for lots 2 and 3. Writes two files.

pii_test/final_review/pii_test_timestamps_lots_2_3.csv
    One row per checked dataset: nid, lot, pii_test_timestamp, pii_present.
    Datasets that were not checked (no file, not a table, scan error) are left out.

data/pii_test_timestamps_lots_2_3.csv
    One row per dataset in the lot's table, checked or not: nid, uuid, lot, pii_tested,
    pii_detected, pii_test_timestamp. pii_tested means what run_pii_s3.py writes to lot 1's
    table; pii_detected does not (see below). The one lot 3 row with no nid is left out.

    pii_test_timestamp  when the scan read the file (UTC), from the per-file line of
                        the lot's scan log; the latest one where a file was scanned
                        more than once. Blank when not tested.
    pii_tested          True when the scan read the file; False for no file, not a
                        table, or a scan error.
    pii_detected        the same as pii_present (the user's choice, 2026-10-14), so True
                        for the 59 datasets with private individuals' data. Lot 1's
                        pii_detected is the scan's own flag instead (`pii=` on the log
                        line), True for 2,699 datasets in lots 2 and 3. Blank when not
                        tested.
    pii_present         True when the final result is `present`: the pipeline verdict
                        as corrected by the review in pii_test/final_review/
                        (build_final_review.py). `permissible`, `false_positive` and
                        "no detections" are False.

    python pii_test/export_pii_test_timestamps.py
"""

import os
import re

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PII = os.path.join(REPO_ROOT, "pii_test")
OUT = os.path.join(PII, "final_review", "pii_test_timestamps_lots_2_3.csv")
OUT_DATA = os.path.join(REPO_ROOT, "data", "pii_test_timestamps_lots_2_3.csv")

CHECKED = {"no_detections", "false_positive", "permissible", "present"}
# 2026-10-08 06:15:30 [INFO] [s000 1/1200] <uuid>.csv | rows=0 pii=False ...
SCAN_LINE = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d) \[INFO\] \[\w+ \d+/\d+\] "
                       r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.\w+ \| "
                       r"rows=\d+ pii=(True|False) ")


def latest_scans(lot):
    """{file uuid: (timestamp, pii flag) of its latest scan}."""
    latest = {}
    with open(os.path.join(PII, f"lot{lot}", f"lot{lot}_scan.log"), errors="replace") as fh:
        for line in fh:
            m = SCAN_LINE.match(line)
            if m:
                stamp = f"{m.group(1)}T{m.group(2)}"
                if stamp >= latest.get(m.group(3), ("",))[0]:
                    latest[m.group(3)] = (stamp, m.group(4) == "True")
    return latest


def read_result(lot):
    result = pd.read_csv(os.path.join(PII, f"lot{lot}", f"lot{lot}_pii_result.csv"),
                         dtype=str, keep_default_na=False,
                         usecols=["nid", "uuid", "pii_status"])
    # dublin_core_lot3 holds one dataset twice (same nid and uuid).
    return result.drop_duplicates(["nid", "uuid"])


def present_uuids(final, lot):
    return set(final.loc[(final["lot"] == str(lot)) & (final["final_result"] == "present"),
                         "uuid"])


def export_lot(lot, final, scans):
    result = read_result(lot)
    result = result[result["pii_status"].isin(CHECKED)]
    present = present_uuids(final, lot)
    return pd.DataFrame({"nid": result["nid"], "lot": lot,
                         "pii_test_timestamp": result["uuid"].map(lambda u: scans[u][0]),
                         "pii_present": result["uuid"].isin(present)})


def flags_lot(lot, final, scans):
    result = read_result(lot)
    no_nid = result["nid"] == ""
    if no_nid.any():
        print(f"lot {lot}: left out {no_nid.sum()} row(s) with no nid, uuid "
              f"{', '.join(result.loc[no_nid, 'uuid'])}")
    result = result[~no_nid]
    tested = result["pii_status"].isin(CHECKED)
    assert (tested == result["uuid"].isin(scans)).all(), "tested status and scan log disagree"
    present = present_uuids(final, lot)
    return pd.DataFrame({"nid": result["nid"], "uuid": result["uuid"], "lot": lot,
                         "pii_tested": tested,
                         "pii_detected": result["uuid"].isin(present).where(tested, None),
                         "pii_test_timestamp": result["uuid"].map(
                             lambda u: scans[u][0] if u in scans else "")})


def main():
    final = pd.read_csv(os.path.join(PII, "final_review", "final_results.csv"),
                        dtype=str, keep_default_na=False)
    scans = {lot: latest_scans(lot) for lot in (2, 3)}

    out = pd.concat([export_lot(lot, final, scans[lot]) for lot in (2, 3)], ignore_index=True)
    assert not out.duplicated(["lot", "nid"]).any(), "a nid is repeated within a lot"
    assert (out["nid"] != "").all() and (out["pii_test_timestamp"] != "").all()
    out.to_csv(OUT, index=False)

    flags = pd.concat([flags_lot(lot, final, scans[lot]) for lot in (2, 3)], ignore_index=True)
    assert not flags.duplicated(["lot", "nid"]).any(), "a nid is repeated within a lot"
    assert (flags["uuid"] != "").all()
    blank = flags["pii_test_timestamp"] == ""
    assert (blank == ~flags["pii_tested"]).all() and (blank == flags["pii_detected"].isna()).all()
    assert (flags["pii_detected"] == True).sum() == out["pii_present"].sum()
    flags.to_csv(OUT_DATA, index=False)

    for lot, part in out.groupby("lot"):
        print(f"lot {lot}: {len(part)} datasets checked, {part['pii_present'].sum()} with PII "
              f"present, scanned {part['pii_test_timestamp'].min()} to "
              f"{part['pii_test_timestamp'].max()}")
    for lot, part in flags.groupby("lot"):
        print(f"lot {lot}: {len(part)} datasets, {part['pii_tested'].sum()} tested, "
              f"{(part['pii_detected'] == True).sum()} pii_detected")
    print(f"wrote {OUT}")
    print(f"wrote {OUT_DATA}")


if __name__ == "__main__":
    main()
