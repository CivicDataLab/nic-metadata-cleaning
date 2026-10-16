"""
Unit tests for api_pipeline: no GPU, no judge server, no S3.

The scan and the judge are stubbed; Tier 1 and the Tier 3 plumbing are the
real modules. Run from the repo root:

    .venv/bin/python -m unittest discover -s pii_test/pii_service/tests -v
"""

import csv
import json
import os
import sys
import tempfile
import unittest

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_DIR)

import api_pipeline as P  # noqa: E402
import pii_filters  # noqa: E402
import pii_tier3 as tier3  # noqa: E402

BENEFICIARIES = {"title": "List of beneficiaries under PM-KISAN"}

NAMES = ["Ramesh Kumar Sharma", "Sunita Devi", "Mohammed Irfan Khan",
         "Lakshmi Narayanan", "Priya Rajendran", "Anil Baburao Patil"]


def make_upload(folder, name="upload.csv"):
    path = os.path.join(folder, "input", name)
    os.makedirs(os.path.dirname(path))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Name", "Village", "Amount"])
        for n in NAMES:
            writer.writerow([n, "Rampur", "6000"])
    return path


def make_json_upload(folder, name="upload.json", wrap=None):
    """The same table as make_upload, as the platform's JSON: a list of records."""
    path = os.path.join(folder, "input", name)
    os.makedirs(os.path.dirname(path))
    records = [{"Name": n, "Village": "Rampur", "Amount": 6000} for n in NAMES]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({wrap: records} if wrap else records, fh)
    return path


def make_workbook(folder, name="upload.xlsx", extra_sheets=("Contacts", "Notes")):
    import pandas as pd
    path = os.path.join(folder, "input", name)
    os.makedirs(os.path.dirname(path))
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"Name": NAMES, "Village": "Rampur", "Amount": 6000}).to_excel(
            writer, sheet_name="People", index=False)
        for sheet in extra_sheets:
            pd.DataFrame({"Officer": ["A. Sharma"]}).to_excel(
                writer, sheet_name=sheet, index=False)
    return path


def stub_scan(error=None, detections=None):
    if detections is None:
        detections = [{"uuid": "upload", "column": "Name", "row_index": i,
                       "entity_type": "PERSON", "entity_text": n, "score": 0.85,
                       "source": "presidio"} for i, n in enumerate(NAMES)]

    def scan(path, max_rows):
        return {"error": error, "detections": [] if error else detections,
                "rows_scanned": len(NAMES), "columns_scanned": ["Name", "Village"],
                "entity_count": len(detections), "degraded": False}
    return scan


class StubJudge:
    def __init__(self, verdict):
        self.verdict, self.prompts = verdict, []

    def __call__(self, message):
        self.prompts.append(message)
        return f"CLASS: {self.verdict}"


def run(tmp, meta=None, path=None, **kw):
    path = path or make_upload(tmp)
    kw.setdefault("scan", stub_scan())
    kw.setdefault("judge_check", lambda: None)
    kw.setdefault("find_values", lambda texts: [[] for _ in texts])
    kw.setdefault("max_rows", 100)
    return P.run(path, tmp, meta or {}, run_id="r1", **kw)


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class RequestMetadata(unittest.TestCase):
    def test_title_sets_tier1_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, {"title": "List of beneficiaries under PM-KISAN"},
                         llm=False)
            rows = read_rows(os.path.join(tmp, "detail", "tier1_column_class.csv"))
        self.assertEqual(rows[0]["dataset_context"], "individual_records")
        self.assertEqual(result["final_class"], "present")
        self.assertEqual(result["metadata_source"], "request")
        self.assertEqual(result["tier3"], "not_needed")

    def test_no_metadata_leaves_column_for_the_judge(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, llm=False)
        self.assertEqual(result["final_class"], "undecided")
        self.assertEqual(result["tier3"], "skipped")
        self.assertEqual(result["metadata_source"], "filename")
        self.assertTrue(any("No title" in w for w in result["warnings"]))

    def test_catalog_title_and_description_reach_the_prompt(self):
        meta = {"title": "Kisan data", "catalog_title": "Agri Catalog X",
                "description": "Farmers who received seed kits"}
        with tempfile.TemporaryDirectory() as tmp:
            path = make_upload(tmp)
            dataset = P.dataset_metadata(path, meta)
            rows = [{"uuid": "upload.csv", "lot": P.API_LOT, "column": "Name",
                     "pii_class": "undecided", "entity_types": "PERSON",
                     "evidence_json": json.dumps({"sample_values": NAMES[:2]})}]
            prompt = tier3.build_prompt(P.build_pairs(rows, dataset)[0])
        self.assertIn("Catalog title: Agri Catalog X", prompt)
        self.assertIn("Description: Farmers who received seed kits", prompt)
        self.assertIn("File header row: Village, Amount", prompt)

    def test_file_name_fallback_reads_underscores_as_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_upload(tmp, "List_of_beneficiaries.csv")
            title = P.dataset_metadata(path, {})["title"]
        self.assertEqual(title, "List of beneficiaries")
        self.assertEqual(P.tier1.dataset_context(title)[0], "individual_records")

    def test_uuid_file_name_is_not_a_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_upload(tmp, "3b1f6a2e-0c4d-4e5f-8a9b-1c2d3e4f5a6b.csv")
            self.assertIsNone(P.dataset_metadata(path, {})["title"])


class Tier3(unittest.TestCase):
    def test_judge_decides_the_undecided_column(self):
        judge = StubJudge("permissible")
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, judge_client=judge)
            verdicts = os.path.exists(os.path.join(tmp, "detail", "tier3_verdicts.csv"))
        self.assertEqual(len(judge.prompts), 1)
        self.assertTrue(verdicts)
        self.assertEqual(result["tier3"], "ran")
        self.assertEqual(result["final_class"], "permissible")
        self.assertEqual(result["columns"][0]["decided_by"], "tier3")

    def test_tier3_stage_is_reported_before_the_first_verdict(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp, judge_client=StubJudge("present"),
                progress=lambda stage, done, total: calls.append((stage, done, total)))
        tier3_calls = [c for c in calls if c[0] == "tier3"]
        self.assertEqual(tier3_calls, [("tier3", 0, 1), ("tier3", 1, 1)])

    def test_judge_down_keeps_tier1_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, judge_check=lambda: "no LLM judge at x")
        self.assertEqual(result["tier3"], "unavailable")
        self.assertEqual(result["final_class"], "undecided")
        self.assertTrue(any("did not run" in w for w in result["warnings"]))

    def test_dead_judge_aborts_without_losing_tier1(self):
        def dead(message):
            raise ConnectionRefusedError("refused")
        many = [{"uuid": "upload", "column": f"Name {c}", "row_index": i,
                 "entity_type": "PERSON", "entity_text": n, "score": 0.85,
                 "source": "presidio"}
                for c in "ABCD" for i, n in enumerate(NAMES)]
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, scan=stub_scan(detections=many), judge_client=dead)
        self.assertEqual(result["tier3"], "aborted")
        self.assertEqual(result["final_class"], "undecided")


class Results(unittest.TestCase):
    def test_judged_column_carries_both_tiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp, judge_client=StubJudge("permissible"))
            rows = read_rows(os.path.join(tmp, "results.csv"))
        self.assertEqual([r["entity_text"] for r in rows], NAMES)
        for r in rows:
            self.assertEqual(r["tier1_class"], "undecided")
            self.assertTrue(r["llm_reasoning"])
            self.assertEqual(r["llm_verdict"], "permissible")
            self.assertEqual((r["final_class"], r["decided_by"]),
                             ("permissible", "tier3"))

    def test_rule_decided_column_never_went_to_the_judge(self):
        judge = StubJudge("permissible")
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp, {"title": "List of beneficiaries under PM-KISAN"},
                judge_client=judge)
            rows = read_rows(os.path.join(tmp, "results.csv"))
        self.assertEqual(judge.prompts, [])
        self.assertEqual(len(rows), len(NAMES))
        for r in rows:
            self.assertEqual((r["tier1_class"], r["final_class"], r["decided_by"]),
                             ("present", "present", "tier1"))
            self.assertEqual((r["llm_verdict"], r["llm_reasoning"]), ("", ""))

    def test_reasoning_is_only_on_the_values_in_the_prompt(self):
        names = [f"Person Number{chr(65 + i)} Kumar" for i in range(20)]
        detections = [{"uuid": "upload", "column": "Name", "row_index": i,
                       "entity_type": "PERSON", "entity_text": n, "score": 0.85,
                       "source": "presidio"} for i, n in enumerate(names)]
        judge = StubJudge("present")
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp, scan=stub_scan(detections=detections), judge_client=judge)
            rows = read_rows(os.path.join(tmp, "results.csv"))
        shown = [r["entity_text"] for r in rows if r["llm_reasoning"]]
        self.assertEqual(shown, names[:tier3.MAX_SAMPLE_VALUES])
        for name in shown:
            self.assertIn(name, judge.prompts[0])
        self.assertNotIn(names[-1], judge.prompts[0])
        self.assertTrue(all(r["llm_verdict"] == "present" for r in rows))
        self.assertNotIn("sent_to_llm", rows[0])
        self.assertNotIn("shown_to_llm", rows[0])

    def test_judge_down_leaves_the_llm_columns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp, judge_check=lambda: "no LLM judge at x")
            rows = read_rows(os.path.join(tmp, "results.csv"))
        for r in rows:
            self.assertEqual((r["llm_verdict"], r["llm_reasoning"], r["final_class"]),
                             ("", "", "undecided"))

    def test_no_detections_writes_a_header_only_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp, scan=stub_scan(detections=[]))
            with open(os.path.join(tmp, "results.csv"), encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        self.assertEqual(lines, [",".join(P.RESULT_FIELDS)])


class Outcomes(unittest.TestCase):
    def test_no_detections(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, scan=stub_scan(detections=[]))
            self.assertTrue(os.path.exists(os.path.join(tmp, "columns.csv")))
        self.assertEqual(result["final_class"], "no_pii_found")
        self.assertEqual(result["columns"], [])
        self.assertEqual(result["message"], "No personal data detected.")

    def test_nothing_scanned_is_not_a_clean_bill(self):
        def scan(path, max_rows):
            return {"error": None, "detections": [], "rows_scanned": 0,
                    "columns_scanned": [], "columns_skipped": [("Amount", "numeric")],
                    "entity_count": 0, "degraded": False}
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, scan=scan)
        self.assertEqual(result["final_class"], "no_pii_found")
        self.assertTrue(result["warnings"][0].startswith("Nothing was scanned"))

    def test_scan_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, scan=stub_scan(error="bad CSV"))
            with open(os.path.join(tmp, "result.json"), encoding="utf-8") as fh:
                on_disk = json.load(fh)
        self.assertEqual(result["status"], "error")
        self.assertEqual(on_disk["error"], "bad CSV")

    def test_undecided_column_outranks_permissible(self):
        rows = [{"pii_class": "permissible"}, {"pii_class": "undecided"},
                {"pii_class": "false_positive"}]
        self.assertEqual(P.final_class(rows), "undecided")
        self.assertEqual(P.final_class(rows + [{"pii_class": "present"}]), "present")

    def test_every_class_has_a_message(self):
        cols = [{"column": "A", "class": "present"},
                {"column": "B", "class": "undecided"}]
        for cls in ("present", "undecided", "permissible", "false_positive",
                    "no_pii_found"):
            self.assertTrue(P.message(cls, cols))
        self.assertIn("1 column(s): A.", P.message("present", cols))
        self.assertIn("1 column(s) could not be decided automatically (B)",
                      P.message("undecided", cols))


class Formats(unittest.TestCase):
    """JSON and Excel uploads reach the same pipeline as a CSV."""

    def test_json_is_scanned_as_its_converted_table(self):
        seen = []

        def scan(path, max_rows):
            seen.append(path)
            return stub_scan()(path, max_rows)

        judge = StubJudge("present")
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, path=make_json_upload(tmp), scan=scan, judge_client=judge)
            converted = read_rows(os.path.join(tmp, "converted", "upload.csv"))
        self.assertEqual(seen, [os.path.join(tmp, "converted", "upload.csv")])
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["file"], "upload.json")
        self.assertEqual([r["Name"] for r in converted], NAMES)
        # The tiers' header row is the table's, not the first line of the JSON.
        self.assertIn("File header row: Village, Amount", judge.prompts[0])

    def test_json_and_csv_get_the_same_answer(self):
        answers = []
        for make in (make_upload, make_json_upload,
                     lambda tmp: make_json_upload(tmp, wrap="data")):
            with tempfile.TemporaryDirectory() as tmp:
                result = run(tmp, BENEFICIARIES, path=make(tmp), llm=False)
            answers.append((result["final_class"], result["message"], result["columns"]))
        self.assertEqual(answers[0][0], "present")
        self.assertEqual(answers[1], answers[0])
        self.assertEqual(answers[2], answers[0])

    def test_json_file_name_still_stands_in_for_a_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, path=make_json_upload(tmp, "List_of_beneficiaries.json"),
                         llm=False)
        self.assertEqual(result["final_class"], "present")
        self.assertEqual(result["metadata_source"], "filename")

    def test_json_that_is_not_a_table_ends_the_run(self):
        def never(path, max_rows):
            raise AssertionError("scanned a file that could not be converted")

        for body, error in (('[{"Name": "Ramesh Kum', "Not valid JSON:"),
                            ('{"status": "FAIL"}', "No table found in the JSON")):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "input", "upload.json")
                os.makedirs(os.path.dirname(path))
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(body)
                result = run(tmp, path=path, scan=never)
                with open(os.path.join(tmp, "result.json"), encoding="utf-8") as fh:
                    on_disk = json.load(fh)
                self.assertEqual(result["status"], "error")
                self.assertTrue(on_disk["error"].startswith(error))
                self.assertEqual(on_disk["file"], "upload.json")
                self.assertNotIn("Ramesh", on_disk["error"])

    def test_workbook_goes_to_the_scan_as_it_is(self):
        seen = []

        def scan(path, max_rows):
            seen.append(path)
            return stub_scan()(path, max_rows)

        with tempfile.TemporaryDirectory() as tmp:
            path = make_workbook(tmp)
            result = run(tmp, BENEFICIARIES, path=path, scan=scan, llm=False)
            self.assertFalse(os.path.exists(os.path.join(tmp, "converted")))
        self.assertEqual(seen, [path])
        self.assertEqual(result["final_class"], "present")
        self.assertEqual(result["warnings"][0],
                         "Only the first sheet (People) was checked; 2 other "
                         "sheet(s) were not: Contacts, Notes.")

    def test_single_sheet_workbook_has_no_sheet_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, BENEFICIARIES, path=make_workbook(tmp, extra_sheets=()),
                         llm=False)
        self.assertFalse(any("sheet" in w for w in result["warnings"]))

    def test_text_file_named_xls_is_read_as_csv(self):
        seen = []

        def scan(path, max_rows):
            seen.append(path)
            return stub_scan()(path, max_rows)

        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, BENEFICIARIES, path=make_upload(tmp, "upload.xls"),
                         scan=scan, llm=False)
        self.assertEqual(seen, [os.path.join(tmp, "converted", "upload.csv")])
        self.assertEqual(result["final_class"], "present")
        self.assertTrue(result["warnings"][0].startswith("The file is named as an Excel"))

    def test_convert_stage_is_reported_first(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp, BENEFICIARIES, llm=False, redact=True,
                progress=lambda stage, done, total: calls.append(stage))
        self.assertEqual(calls, ["converting", "scanning", "tier1", "redacting"])


class Redaction(unittest.TestCase):
    def redacted(self, tmp):
        return read_rows(os.path.join(tmp, P.DOWNLOADS["redacted.csv"]))

    def test_not_asked_for_means_no_copy_and_no_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, BENEFICIARIES, llm=False)
            self.assertFalse(os.path.exists(os.path.join(tmp, "redacted.csv")))
        self.assertNotIn("redaction", result)

    def test_present_column_is_redacted(self):
        # The scan caught four of the six names; the copy must hold none.
        some = stub_scan(detections=stub_scan()(None, 0)["detections"][:4])
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, BENEFICIARIES, scan=some, llm=False, redact=True)
            copy = self.redacted(tmp)
            with open(os.path.join(tmp, "result.json"), encoding="utf-8") as fh:
                on_disk = json.load(fh)
        self.assertEqual([r["Name"] for r in copy], ["<PERSON>"] * 6)
        self.assertEqual([r["Village"] for r in copy], ["Rampur"] * 6)
        self.assertEqual([r["Amount"] for r in copy], ["6000"] * 6)
        self.assertEqual(result["redaction"], {
            "status": "done", "message": "1 column(s) redacted in 6 row(s).", "rows": 6,
            "columns": [{"column": "Name", "method": "whole_column",
                         "cells_redacted": 6}]})
        self.assertEqual(on_disk["redaction"], result["redaction"])
        self.assertEqual(result["final_class"], "present")

    def test_json_upload_is_redacted_into_a_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, BENEFICIARIES, path=make_json_upload(tmp), llm=False,
                         redact=True)
            copy = self.redacted(tmp)
        self.assertEqual(result["redaction"]["status"], "done")
        self.assertEqual([r["Name"] for r in copy], ["<PERSON>"] * 6)
        self.assertEqual([r["Amount"] for r in copy], ["6000"] * 6)

    def test_workbook_copy_says_it_is_the_first_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, BENEFICIARIES, path=make_workbook(tmp), llm=False,
                         redact=True)
            copy = self.redacted(tmp)
        self.assertEqual([r["Name"] for r in copy], ["<PERSON>"] * 6)
        self.assertIn("The redacted copy holds the first sheet only.", result["warnings"])

    def test_nothing_present_means_nothing_to_redact(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, judge_client=StubJudge("permissible"), redact=True)
            self.assertFalse(os.path.exists(os.path.join(tmp, "redacted.csv")))
        self.assertEqual(result["redaction"]["status"], "not_needed")
        self.assertNotIn("columns", result["redaction"])

    def test_undecided_columns_are_left_and_named(self):
        two = [dict(d, column=c) for c in ("Name", "Nominee")
               for d in stub_scan()(None, 0)["detections"]]

        def verdict(message):
            return "CLASS: present" if "Flagged column: Name" in message else "no answer"

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "input", "upload.csv")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Name", "Nominee"])
                writer.writerows([n, n] for n in NAMES)
            result = run(tmp, path=path, scan=stub_scan(detections=two),
                         judge_client=verdict, redact=True)
            copy = self.redacted(tmp)
        classes = {c["column"]: c["class"] for c in result["columns"]}
        self.assertEqual(classes, {"Name": "present", "Nominee": "undecided"})
        self.assertEqual([r["Name"] for r in copy], ["<PERSON>"] * 6)
        self.assertEqual([r["Nominee"] for r in copy], NAMES)
        self.assertIn("The redacted copy still holds 1 undecided column(s): Nominee. "
                      "Review them before publishing.", result["warnings"])

    def test_failed_redaction_does_not_fail_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "input", "upload.csv")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as fh:        # rows longer than the header
                fh.write("Name,Village\n" + "".join(f"{n},Rampur,\n" for n in NAMES))
            result = run(tmp, BENEFICIARIES, path=path, llm=False, redact=True)
            self.assertFalse(os.path.exists(os.path.join(tmp, "redacted.csv")))
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["final_class"], "present")
        self.assertEqual(result["redaction"]["status"], "failed")
        self.assertTrue(result["redaction"]["message"].startswith("Redaction failed: the data rows"))

    def test_unexpected_error_is_reported_without_its_message(self):
        saved = P.redactor.redact_file

        def boom(*args, **kwargs):
            raise ValueError(f"could not convert {NAMES[0]!r}")     # as pandas might

        P.redactor.redact_file = boom
        self.addCleanup(setattr, P.redactor, "redact_file", saved)
        with tempfile.TemporaryDirectory() as tmp, self.assertLogs("pii_api", "ERROR") as logs:
            result = run(tmp, BENEFICIARIES, llm=False, redact=True)
        self.assertEqual(result["redaction"],
                         {"status": "failed", "message": "Redaction failed: ValueError."})
        self.assertFalse(any("Ramesh" in line for line in logs.output))

    def test_free_text_is_searched_past_what_the_scan_reported(self):
        remarks = ["Called on behalf of %s about the delayed installment and the "
                   "pending bank verification at the block office" % n for n in NAMES]
        # The scan read two rows and, as it does for a name no cue introduces,
        # kept only the one that happens to follow "Shri".
        remarks[0] = "Shri " + NAMES[0] + remarks[0][len("Called on behalf of " + NAMES[0]):]
        scanned = [{"uuid": "upload", "column": "Remarks", "row_index": 0,
                    "entity_type": "PERSON", "entity_text": NAMES[0], "score": 0.85,
                    "source": "presidio"}]

        def scan(path, max_rows):
            return {"error": None, "detections": scanned, "rows_scanned": 2,
                    "columns_scanned": ["Remarks"], "entity_count": 1, "degraded": False}

        def find_values(texts):
            return [[(n, "PERSON") for n in NAMES if n in text] for text in texts]

        steps = []
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "input", "upload.csv")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Remarks"])
                writer.writerows([r] for r in remarks)
            result = run(tmp, path=path, scan=scan, judge_client=StubJudge("present"),
                         redact=True, find_values=find_values,
                         progress=lambda *step: steps.append(step))
            copy = self.redacted(tmp)
        self.assertEqual(result["redaction"]["columns"],
                         [{"column": "Remarks", "method": "found_values",
                           "cells_redacted": 6}])
        self.assertEqual([n for n in NAMES for r in copy if n in r["Remarks"]], [])
        self.assertTrue(copy[5]["Remarks"].startswith("Called on behalf of <PERSON> about"))
        self.assertEqual(steps[-2:], [("redacting", 0, 0), ("redacting", 6, 6)])
        self.assertTrue(any("a name they missed may remain: Remarks" in w
                            for w in result["warnings"]))


class Pdf(unittest.TestCase):
    """A PDF is checked as lines of text and answered in pages."""

    LINES = [(1, "List of Beneficiaries, Block Rampur"),
             (1, "1 Ramesh Kumar Sharma Rampur 9876543210"),
             (1, "2 Sunita Devi Sonpur 9123456780"),
             (2, "Totals for the block: 2000 4000 6000"),
             (3, "3 Mohammed Irfan Khan Rampur 9812345678")]

    def setUp(self):
        self.addCleanup(setattr, P.convert.pdf_text, "extract", P.convert.pdf_text.extract)

    def run_pdf(self, tmp, lines=None, summary=None, failure=None, **kw):
        lines = self.LINES if lines is None else lines
        read = {"pages": 3, "pages_read": 3, "pages_text": 3, "pages_ocr": 0,
                "pages_empty": [], "lines": len(lines), "ocr_confidence": None}
        read.update(summary or {})

        def extract(pdf_path, out_csv, progress=None):
            if failure:
                raise P.convert.pdf_text.PdfError(failure)
            os.makedirs(os.path.dirname(out_csv))
            with open(out_csv, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["page", "line", "text"])
                seen = {}
                for page, text in lines:
                    seen[page] = seen.get(page, 0) + 1
                    writer.writerow([page, seen[page], text])
            if progress:
                progress(read["pages_read"], read["pages_read"])
            return read

        def scan_text(path, max_rows):
            rows = read_rows(path)
            found = [{"uuid": "upload", "column": "text", "row_index": i,
                      "entity_type": "PERSON", "entity_text": n, "score": 0.85,
                      "source": "presidio"}
                     for i, row in enumerate(rows) for n in NAMES if n in row["text"]]
            return {"error": None, "detections": found, "rows_scanned": len(rows),
                    "columns_scanned": ["text"], "entity_count": len(found),
                    "degraded": False}

        def table_scan(path, max_rows):
            raise AssertionError("a PDF went through the table scan")

        P.convert.pdf_text.extract = extract
        path = os.path.join(tmp, "input", "upload.pdf")
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as fh:
            fh.write(b"%PDF-1.4\n%made up\n")
        kw.setdefault("scan_text", scan_text)
        return run(tmp, kw.pop("meta", BENEFICIARIES), path=path, scan=table_scan, **kw)

    def test_findings_are_reported_by_page(self):
        judge = StubJudge("present")
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_pdf(tmp, judge_client=judge)
            results = read_rows(os.path.join(tmp, "results.csv"))
            with open(os.path.join(tmp, "results.csv"), encoding="utf-8") as fh:
                header = fh.readline().strip()
        self.assertEqual(result["final_class"], "present")
        self.assertEqual(result["message"], "Personal data found on 2 page(s): 1, 3. "
                                            "Redact before publishing.")
        self.assertEqual(result["pdf"], {"pages": 3, "pages_checked": 3, "pages_ocr": 0,
                                         "pages_with_findings": [1, 3]})
        self.assertEqual(result["file"], "upload.pdf")
        self.assertEqual(header, ",".join(P.PDF_RESULT_FIELDS))
        self.assertEqual([(r["page"], r["line"], r["entity_text"]) for r in results],
                         [("1", "2", NAMES[0]), ("1", "3", NAMES[1]), ("3", "1", NAMES[2])])
        self.assertEqual({r["final_class"] for r in results}, {"present"})

    def test_our_own_header_row_never_reaches_the_tiers(self):
        judge = StubJudge("permissible")
        with tempfile.TemporaryDirectory() as tmp:
            self.run_pdf(tmp, judge_client=judge)
        self.assertIn("Flagged column: text", judge.prompts[0])
        self.assertNotIn("File header row", judge.prompts[0])
        self.assertNotIn("page", judge.prompts[0].lower().replace("pm-kisan", ""))

    def test_undecided_findings_name_their_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_pdf(tmp, llm=False)
        self.assertEqual(result["message"],
                         "What was found on 2 page(s) (1, 3) could not be decided "
                         "automatically; needs manual review.")

    def test_redaction_is_not_offered_for_a_pdf(self):
        def never(texts):
            raise AssertionError("searched a PDF for redaction")

        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_pdf(tmp, judge_client=StubJudge("present"), redact=True,
                                  find_values=never)
            self.assertFalse(os.path.exists(os.path.join(tmp, "redacted.csv")))
        self.assertEqual(result["final_class"], "present")
        self.assertEqual(result["redaction"]["status"], "not_supported")

    def test_pdf_that_cannot_be_read_ends_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_pdf(tmp, failure="The PDF is password-protected; remove "
                                              "the password and upload it again")
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["error"].startswith("The PDF is password-protected"))

    def test_what_was_not_read_is_said(self):
        summary = {"pages": 250, "pages_read": 200, "pages_text": 195, "pages_ocr": 5,
                   "pages_empty": [4, 5], "ocr_confidence": 61}
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_pdf(tmp, summary=summary, meta={}, llm=False)
        self.assertEqual(result["warnings"], [
            "Only the first 200 of 250 pages were checked.",
            "No text could be read from 2 page(s): 4-5.",
            "5 page(s) were read by OCR; a misread letter or digit can hide a name "
            "or a number.",
            "The OCR was unsure of what it read (average confidence 61%); treat a "
            "clean result with caution.",
            "No title or description was sent; the rules only had the file name to "
            "go on."])
        self.assertEqual(result["pdf"]["pages_checked"], 200)

    def test_pdf_with_no_readable_text_is_not_a_clean_bill(self):
        summary = {"pages": 2, "pages_read": 2, "pages_text": 0, "pages_ocr": 2,
                   "pages_empty": [1, 2]}
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_pdf(tmp, lines=[], summary=summary)
        self.assertEqual(result["final_class"], "no_pii_found")
        self.assertEqual(result["warnings"],
                         ["Nothing was checked: no text could be read from this PDF."])
        self.assertEqual(result["pdf"]["pages_with_findings"], [])

    def test_row_limit_does_not_cut_a_pdf_short(self):
        # "Rows to scan" set to 2 on a five-line document: the page cap is the
        # PDF's limit, and the answer says every page was checked.
        asked = []

        def scan_text(path, max_rows):
            asked.append(max_rows)
            rows = read_rows(path)
            found = [{"uuid": "upload", "column": "text", "row_index": i,
                      "entity_type": "PERSON", "entity_text": n, "score": 0.85,
                      "source": "presidio"}
                     for i, row in enumerate(rows) for n in NAMES if n in row["text"]]
            return {"error": None, "detections": found, "rows_scanned": len(rows),
                    "columns_scanned": ["text"], "entity_count": len(found),
                    "degraded": False}

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "input", "upload.pdf")
            result = self.run_pdf(tmp, judge_client=StubJudge("present"),
                                  scan_text=scan_text, max_rows=2)
        self.assertEqual(asked, [None])
        self.assertEqual(result["pdf"]["pages_with_findings"], [1, 3])
        self.assertEqual((result["rows_scanned"], result["rows_limit"]), (5, None))

    def test_pages_are_counted_while_converting(self):
        steps = []
        with tempfile.TemporaryDirectory() as tmp:
            self.run_pdf(tmp, llm=False, progress=lambda *step: steps.append(step))
        self.assertEqual(steps[:3], [("converting", 0, 0), ("converting", 3, 3),
                                     ("scanning", 0, 0)])

    def test_page_numbers_read_the_way_a_person_writes_them(self):
        self.assertEqual(P.page_list([9, 1, 2, 3, 5, 10, 3]), "1-3, 5, 9-10")
        self.assertEqual(P.page_list(range(1, 60, 2), limit=3), "1, 3, 5, ...")
        self.assertEqual(P.page_list([]), "")


class Blocklist(unittest.TestCase):
    def test_disable_clears_corpus_counts(self):
        saved = dict(pii_filters.CROSS_DATASET_COUNTS)
        try:
            pii_filters.CROSS_DATASET_COUNTS["someone common"] = 50
            P.disable_corpus_blocklist()
            self.assertEqual(pii_filters.CROSS_DATASET_COUNTS, {})
        finally:
            pii_filters.CROSS_DATASET_COUNTS.clear()
            pii_filters.CROSS_DATASET_COUNTS.update(saved)


if __name__ == "__main__":
    unittest.main()
