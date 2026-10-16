"""
Unit tests for redact: no GPU, no scan -- the scan's detections are written
by hand and the detectors that search free text are a stub.

Run from the repo root:

    .venv/bin/python -m unittest discover -s pii_test/pii_service/tests -v
"""

import csv
import os
import sys
import tempfile
import unittest

import pandas as pd

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_DIR)

import redact as R  # noqa: E402

NAMES = ["Ramesh Kumar Sharma", "Sunita Devi", "Mohammed Irfan Khan",
         "Lakshmi Narayanan", "Priya Rajendran", "Anil Baburao Patil"]
REMARKS = [
    "Called on behalf of Ramesh Kumar Sharma about the delayed installment, asked to ring 9876543210 after noon",
    "No issue reported during the visit to the ward office on the second Monday of the month",
    "Mohammed Irfan Khan says the passbook is held by his brother Salim Khan, who lives in the next village",
    "Wants the payment sent to the new account; documents were handed to the block office last week",
    "Complaint raised by Priya Rajendran against the dealer for refusing the ration twice in one month",
    "Follow-up needed: Anil Baburao Patil could not be reached on the listed number in three attempts",
]


def person(column, row, text):
    return {"column": column, "row_index": row, "entity_type": "PERSON",
            "entity_text": text, "score": 0.85, "source": "presidio"}


def phone(column, row, text):
    return {"column": column, "row_index": row, "entity_type": "PHONE_NUMBER",
            "entity_text": text, "score": 1.0, "source": "regex"}


def finder(*values, calls=None):
    """A find_values that flags any of ``values`` it sees in a text."""
    def find_values(texts):
        if calls is not None:
            calls.append(list(texts))
        return [[(v, "PERSON") for v in values if v in text] for text in texts]
    return find_values


def write_csv(folder, header, rows, name="table.csv", encoding="utf-8"):
    path = os.path.join(folder, name)
    with open(path, "w", newline="", encoding=encoding) as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def read_back(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = folder.name
        self.out = os.path.join(self.tmp, "redacted.csv")

    def redact(self, source, present, detections, **kw):
        return R.redact_file(source, self.out, present, detections, **kw)


class WholeColumn(Base):
    def test_every_filled_cell_goes_even_where_nothing_was_found(self):
        rows = [[n, "Rampur", "6000"] for n in NAMES] + [["", "Sonpur", "0"]]
        source = write_csv(self.tmp, ["Name", "Village", "Amount"], rows)
        # The detector caught half the names; the column was still ruled present.
        found = [person("Name", i, NAMES[i]) for i in (0, 2, 4)]
        done = self.redact(source, ["Name"], found)
        copy = read_back(self.out)
        self.assertEqual(list(copy["Name"]), ["<PERSON>"] * 6 + [""])
        self.assertEqual(done["columns"], [{"column": "Name", "method": "whole_column",
                                            "cells_redacted": 6}])
        self.assertEqual(done["rows"], 7)
        self.assertEqual(done["notes"], [])

    def test_other_columns_come_out_as_they_went_in(self):
        rows = [["Ramesh Kumar Sharma", "007", "NA", " padded ", "1.50"],
                ["Sunita Devi", "0042", "null", "", "7"]]
        source = write_csv(self.tmp, ["Name", "Code", "Flag", "Note", "Amount"], rows)
        self.redact(source, ["Name"], [person("Name", 0, "Ramesh Kumar Sharma")])
        copy = read_back(self.out)
        for i, row in enumerate(rows):
            self.assertEqual(list(copy.iloc[i, 1:]), row[1:])

    def test_placeholder_is_the_columns_commonest_type(self):
        rows = [["9876543210"], ["9123456780"], ["office"]]
        source = write_csv(self.tmp, ["Mobile"], rows)
        self.redact(source, ["Mobile"], [phone("Mobile", 0, "9876543210"),
                                        phone("Mobile", 1, "9123456780"),
                                        person("Mobile", 2, "office")])
        self.assertEqual(list(read_back(self.out)["Mobile"]), ["<PHONE_NUMBER>"] * 3)

    def test_only_the_columns_asked_for(self):
        rows = [[n, n] for n in NAMES]
        source = write_csv(self.tmp, ["Beneficiary", "Officer"], rows)
        found = [person(c, i, n) for c in ("Beneficiary", "Officer")
                 for i, n in enumerate(NAMES)]
        self.redact(source, ["Beneficiary"], found)
        copy = read_back(self.out)
        self.assertEqual(set(copy["Beneficiary"]), {"<PERSON>"})
        self.assertEqual(list(copy["Officer"]), NAMES)

    def test_short_values_never_go_to_the_detectors(self):
        calls = []
        source = write_csv(self.tmp, ["Name"], [[n] for n in NAMES])
        self.redact(source, ["Name"], [person("Name", 0, NAMES[0])],
                    find_values=finder(calls=calls))
        self.assertEqual(calls, [])

    def test_free_text_nobody_can_search_is_replaced_whole(self):
        def broken(texts):
            raise RuntimeError("CUDA out of memory")

        source = write_csv(self.tmp, ["Remarks"], [[r] for r in REMARKS])
        for find_values in (None, broken):
            with self.subTest(find_values=find_values), self.assertLogs("pii_api", "ERROR"):
                done = self.redact(source, ["Remarks"], [phone("Remarks", 0, "9876543210")],
                                   find_values=find_values)
                self.assertEqual(done["columns"], [{"column": "Remarks",
                                                    "method": "whole_column",
                                                    "cells_redacted": 6}])
                self.assertEqual(set(read_back(self.out)["Remarks"]), {"<PHONE_NUMBER>"})
                self.assertIn("every filled cell was replaced: Remarks", done["notes"][0])


class FoundValues(Base):
    def source(self):
        return write_csv(self.tmp, ["Id", "Remarks"],
                         [[str(i), r] for i, r in enumerate(REMARKS)])

    def test_found_values_are_cut_and_the_sentence_stays(self):
        found = [person("Remarks", 0, "Ramesh Kumar Sharma"),
                 phone("Remarks", 0, "9876543210")]
        done = self.redact(self.source(), ["Remarks"], found,
                           find_values=finder("Mohammed Irfan Khan", "Salim Khan"))
        copy = list(read_back(self.out)["Remarks"])
        self.assertEqual(copy[0], "Called on behalf of <PERSON> about the delayed "
                                  "installment, asked to ring <PHONE_NUMBER> after noon")
        self.assertEqual(copy[2], "<PERSON> says the passbook is held by his brother "
                                  "<PERSON>, who lives in the next village")
        self.assertEqual(copy[1], REMARKS[1])
        self.assertEqual(done["columns"], [{"column": "Remarks", "method": "found_values",
                                            "cells_redacted": 2}])
        self.assertIn("a name they missed may remain: Remarks", done["notes"][0])

    def test_name_the_scan_dropped_for_want_of_a_cue_is_still_cut(self):
        # What the real scan returns for these sentences: the phone number and
        # no names. Its column pass drops a name that no "Shri" or "Name:"
        # introduces, which is every name here.
        scanned = [phone("Remarks", 0, "9876543210")]
        done = self.redact(self.source(), ["Remarks"], scanned, find_values=finder(*NAMES))
        copy = "\n".join(read_back(self.out)["Remarks"])
        self.assertEqual([n for n in NAMES if n in copy], [])
        self.assertNotIn("9876543210", copy)
        self.assertEqual(done["columns"][0]["cells_redacted"], 4)

    def test_every_filled_row_is_searched_whatever_the_scan_read(self):
        calls = []
        rows = [[r] for r in REMARKS] + [[""], ["  " + REMARKS[4] + "  "]]
        source = write_csv(self.tmp, ["Remarks"], rows)
        self.redact(source, ["Remarks"], [], find_values=finder(*NAMES, calls=calls))
        self.assertEqual(calls, [REMARKS + [REMARKS[4]]])       # stripped, blanks skipped
        copy = list(read_back(self.out)["Remarks"])
        self.assertEqual(copy[6], "")
        self.assertEqual(copy[7], "  Complaint raised by <PERSON> against the dealer "
                                  "for refusing the ration twice in one month  ")

    def test_long_columns_are_searched_in_batches(self):
        self.addCleanup(setattr, R, "FIND_BATCH", R.FIND_BATCH)
        R.FIND_BATCH = 4
        calls, steps = [], []
        self.redact(self.source(), ["Remarks"], [], find_values=finder(calls=calls),
                    progress=lambda *step: steps.append(step))
        self.assertEqual([len(c) for c in calls], [4, 2])
        self.assertEqual(steps, [(0, 1, 4, 6), (0, 1, 6, 6)])

    def test_text_past_the_search_budget_is_replaced_whole(self):
        # Two free-text columns of six cells each, and room to search eight.
        self.addCleanup(setattr, R, "MAX_SEARCH_CELLS", R.MAX_SEARCH_CELLS)
        R.MAX_SEARCH_CELLS = 8
        calls = []
        source = write_csv(self.tmp, ["Remarks", "Notes"], [[r, r] for r in REMARKS])
        done = self.redact(source, ["Remarks", "Notes"], [],
                           find_values=finder(*NAMES, calls=calls))
        copy = read_back(self.out)
        self.assertEqual([c["method"] for c in done["columns"]],
                         ["found_values", "whole_column"])
        self.assertEqual(len(calls), 1)                         # Notes was never searched
        self.assertIn("<PERSON> about the delayed", copy["Remarks"][0])
        self.assertEqual(set(copy["Notes"]), {"<REDACTED>"})
        self.assertTrue(any("too long to search (more than 8 cells" in n and "Notes" in n
                            for n in done["notes"]))

    def test_nothing_found_changes_nothing(self):
        done = self.redact(self.source(), ["Remarks"], [], find_values=finder())
        self.assertEqual(list(read_back(self.out)["Remarks"]), REMARKS)
        self.assertEqual(done["columns"][0],
                         {"column": "Remarks", "method": "found_values", "cells_redacted": 0})

    def test_every_occurrence_in_the_cell_goes(self):
        text = ("Ravi Kumar Verma called twice; the second time Ravi Kumar Verma "
                "asked for the supervisor and left a number")
        source = write_csv(self.tmp, ["Remarks"], [[text]])
        self.redact(source, ["Remarks"], [person("Remarks", 0, "Ravi Kumar Verma")],
                    find_values=finder())
        self.assertNotIn("Ravi", read_back(self.out)["Remarks"][0])

    def test_overlapping_finds_become_one_placeholder(self):
        text = ("Name: MOHAN VERMA\nAddress: Ward 4, Rampur, near the primary "
                "school, district Sitapur, Uttar Pradesh")
        source = write_csv(self.tmp, ["Remarks"], [[text]])
        self.redact(source, ["Remarks"], [person("Remarks", 0, "MOHAN VERMA")],
                    find_values=finder("MOHAN VERMA\nAddress"))
        self.assertTrue(read_back(self.out)["Remarks"][0].startswith("Name: <PERSON>: Ward 4"))

    def test_value_not_in_its_cell_replaces_the_whole_column(self):
        # Row 1 does not hold that name: the detections and the table do not
        # line up, so nothing about where the names are can be trusted.
        found = [person("Remarks", 0, "Ramesh Kumar Sharma"),
                 person("Remarks", 1, "Mohammed Irfan Khan")]
        done = self.redact(self.source(), ["Remarks"], found, find_values=finder())
        self.assertEqual(done["columns"][0],
                         {"column": "Remarks", "method": "whole_column", "cells_redacted": 6})
        self.assertEqual(set(read_back(self.out)["Remarks"]), {"<PERSON>"})
        self.assertTrue(any("every filled cell was replaced: Remarks" in n
                            for n in done["notes"]))

    def test_row_past_the_end_replaces_the_whole_column(self):
        done = self.redact(self.source(), ["Remarks"], [person("Remarks", 99, "Someone")],
                           find_values=finder())
        self.assertEqual(done["columns"][0]["method"], "whole_column")


class Reading(Base):
    def test_rows_longer_than_the_header_are_refused(self):
        path = os.path.join(self.tmp, "ragged.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Name,Village\nRamesh Kumar Sharma,Rampur,\nSunita Devi,Sonpur,\n")
        with self.assertRaises(R.RedactionError) as caught:
            self.redact(path, ["Name"], [person("Name", 0, "Rampur")])
        self.assertIn("more fields than the header", str(caught.exception))
        self.assertFalse(os.path.exists(self.out))

    def test_unknown_column_is_refused(self):
        source = write_csv(self.tmp, ["Name"], [[n] for n in NAMES])
        with self.assertRaises(R.RedactionError):
            self.redact(source, ["Nmae"], [person("Nmae", 0, NAMES[0])])

    def test_cp1252_file_is_read_like_the_scan_reads_it(self):
        rows = [["Jos\xe9 Fernandes", "Margao"], ["Sunita Devi", "Sonpur"]]
        source = write_csv(self.tmp, ["Name", "Town"], rows, encoding="cp1252")
        self.redact(source, ["Name"], [person("Name", 0, "Jos\xe9 Fernandes")], rows_read=200)
        copy = read_back(self.out)
        self.assertEqual(list(copy["Name"]), ["<PERSON>"] * 2)
        self.assertEqual(list(copy["Town"]), ["Margao", "Sonpur"])

    def test_stray_byte_below_the_scanned_rows_keeps_the_text_above_it(self):
        # The scan read the top as UTF-8, and that is what its detections
        # quote. pandas decodes in chunks, so the stray byte has to sit well
        # below the scanned rows for the scan not to have met it too.
        text = ("रमेश कुमार शर्मा ने किस्त के बारे में पूछा और कहा कि बैंक खाता बदल गया है")
        path = os.path.join(self.tmp, "mixed.csv")
        with open(path, "wb") as fh:
            fh.write("Remarks\n".encode() + (text + "\n").encode())
            fh.write(b"an ordinary line of filler text for the block office\n" * 25_000)
            fh.write(b"caf\xe9 owner called about the pending certificate again\n")
        done = self.redact(path, ["Remarks"], [person("Remarks", 0, "रमेश कुमार शर्मा")],
                           rows_read=1, find_values=finder())
        self.assertTrue(read_back(self.out)["Remarks"][0].startswith("<PERSON> ने किस्त"))
        self.assertEqual(done["rows"], 25_002)

    def test_workbook_is_redacted_into_a_csv(self):
        source = os.path.join(self.tmp, "book.xlsx")
        frame = pd.DataFrame({"Name": NAMES[:3], "Mobile": [9876543210, None, 9123456780],
                              "Village": ["Rampur", "Sonpur", "Rampur"]})
        with pd.ExcelWriter(source) as writer:
            frame.to_excel(writer, sheet_name="People", index=False)
            pd.DataFrame({"Officer": ["A. Sharma"]}).to_excel(
                writer, sheet_name="Contacts", index=False)
        done = self.redact(source, ["Name", "Mobile"],
                           [person("Name", 0, NAMES[0]), phone("Mobile", 0, "9876543210")])
        copy = read_back(self.out)
        self.assertEqual(list(copy["Name"]), ["<PERSON>"] * 3)
        self.assertEqual(list(copy["Mobile"]), ["<PHONE_NUMBER>", "", "<PHONE_NUMBER>"])
        self.assertEqual(list(copy["Village"]), ["Rampur", "Sonpur", "Rampur"])
        self.assertEqual(done["rows"], 3)


class Verify(Base):
    def test_a_copy_that_still_holds_a_found_value_is_deleted(self):
        source = write_csv(self.tmp, ["Remarks"], [[r] for r in REMARKS])
        self.addCleanup(setattr, R, "cut", R.cut)
        R.cut = lambda text, found: text                 # a rewrite that does nothing
        with self.assertRaises(R.RedactionError) as caught:
            self.redact(source, ["Remarks"], [person("Remarks", 0, "Ramesh Kumar Sharma")],
                        find_values=finder())
        self.assertIn("failed its own check", str(caught.exception))
        self.assertEqual(os.listdir(self.tmp), ["table.csv"])

    def test_a_whole_column_with_a_cell_left_in_is_deleted(self):
        source = write_csv(self.tmp, ["Name"], [[n] for n in NAMES])
        self.addCleanup(setattr, R, "replace_filled", R.replace_filled)
        R.replace_filled = lambda *a, **k: 0
        with self.assertRaises(R.RedactionError):
            self.redact(source, ["Name"], [person("Name", 0, NAMES[0])])
        self.assertFalse(os.path.exists(self.out))

    def test_no_error_message_quotes_a_cell(self):
        source = write_csv(self.tmp, ["Remarks"], [[r] for r in REMARKS])
        self.addCleanup(setattr, R, "cut", R.cut)
        R.cut = lambda text, found: text
        with self.assertRaises(R.RedactionError) as caught:
            self.redact(source, ["Remarks"], [person("Remarks", 0, "Ramesh Kumar Sharma")],
                        find_values=finder())
        self.assertNotIn("Ramesh", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
