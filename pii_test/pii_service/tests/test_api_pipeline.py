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


def run(tmp, meta=None, **kw):
    path = make_upload(tmp)
    kw.setdefault("scan", stub_scan())
    kw.setdefault("judge_check", lambda: None)
    return P.run(path, tmp, meta or {}, run_id="r1", max_rows=100, **kw)


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
