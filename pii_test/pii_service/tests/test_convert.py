"""
Unit tests for convert: no external service calls, no GPU models.

Run from the repo root:

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

import convert as C  # noqa: E402


class TestAccepted(unittest.TestCase):
    """Test the accepted() function."""

    def test_accepted_csv(self):
        self.assertTrue(C.accepted("a.csv"))

    def test_accepted_json_uppercase(self):
        self.assertTrue(C.accepted("A.JSON"))

    def test_accepted_xlsx(self):
        self.assertTrue(C.accepted("b.xlsx"))

    def test_accepted_xls_uppercase(self):
        self.assertTrue(C.accepted("c.XLS"))

    def test_not_accepted_txt(self):
        self.assertFalse(C.accepted("a.txt"))

    def test_not_accepted_csv_bare(self):
        self.assertFalse(C.accepted("csv"))

    def test_not_accepted_empty(self):
        self.assertFalse(C.accepted(""))

    def test_not_accepted_exe(self):
        self.assertFalse(C.accepted("a.csv.exe"))


class TestSniff(unittest.TestCase):
    """Test the sniff() function."""

    def test_sniff_zip(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"PK\x03\x04" + b"junk")
            f.flush()
            path = f.name
        try:
            self.assertEqual(C.sniff(path), "zip")
        finally:
            os.unlink(path)

    def test_sniff_ole(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"junk")
            f.flush()
            path = f.name
        try:
            self.assertEqual(C.sniff(path), "ole")
        finally:
            os.unlink(path)

    def test_sniff_binary_with_nul(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello\x00world")
            f.flush()
            path = f.name
        try:
            self.assertEqual(C.sniff(path), "binary")
        finally:
            os.unlink(path)

    def test_sniff_html(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"<html><body>test</body></html>")
            f.flush()
            path = f.name
        try:
            self.assertEqual(C.sniff(path), "html")
        finally:
            os.unlink(path)

    def test_sniff_html_with_bom(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\xef\xbb\xbf<html>test</html>")
            f.flush()
            path = f.name
        try:
            self.assertEqual(C.sniff(path), "html")
        finally:
            os.unlink(path)

    def test_sniff_html_with_whitespace(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"  \n  <html>test</html>")
            f.flush()
            path = f.name
        try:
            self.assertEqual(C.sniff(path), "html")
        finally:
            os.unlink(path)

    def test_sniff_text_empty(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.flush()
            path = f.name
        try:
            self.assertEqual(C.sniff(path), "text")
        finally:
            os.unlink(path)

    def test_sniff_text_plain(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"plain text content")
            f.flush()
            path = f.name
        try:
            self.assertEqual(C.sniff(path), "text")
        finally:
            os.unlink(path)


class TestJsonToCsv(unittest.TestCase):
    """Test JSON to CSV conversion."""

    def test_json_list_of_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            records = [
                {"name": "Ramesh Kumar Sharma", "village": "Rampur", "amount": "6000"},
                {"name": "Sunita Devi", "village": "Rampur", "amount": "5000"},
            ]
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f)

            count = C.json_to_csv(json_path, csv_path)
            self.assertEqual(count, 2)

            # Read back and verify
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["name"], "Ramesh Kumar Sharma")
            self.assertEqual(rows[1]["name"], "Sunita Devi")

    def test_json_wrapper_object_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            doc = {
                "data": [
                    {"id": "1", "name": "Alice"},
                    {"id": "2", "name": "Bob"},
                ]
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(doc, f)

            count = C.json_to_csv(json_path, csv_path)
            self.assertEqual(count, 2)

    def test_json_wrapper_object_rows_preferred(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            doc = {
                "metadata": [{"unused": "value"}],
                "rows": [
                    {"id": "1", "name": "Alice"},
                    {"id": "2", "name": "Bob"},
                ],
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(doc, f)

            count = C.json_to_csv(json_path, csv_path)
            self.assertEqual(count, 2)

            # Verify the right list was used
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertEqual(rows[0]["id"], "1")

    def test_json_wrapper_preference_order_rows_over_records(self):
        """When both rows and records are present, rows takes priority."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            doc = {
                "rows": [{"id": "1", "type": "rows"}],
                "records": [{"id": "2", "type": "records"}],
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(doc, f)

            count = C.json_to_csv(json_path, csv_path)
            self.assertEqual(count, 1)

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertEqual(rows[0]["type"], "rows")

    def test_json_case_insensitive_preference(self):
        """Preference matching is case-insensitive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            doc = {
                "Rows": [{"id": "1"}],
                "other": [{"id": "2"}],
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(doc, f)

            count = C.json_to_csv(json_path, csv_path)
            self.assertEqual(count, 1)

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertEqual(rows[0]["id"], "1")

    def test_json_nested_object(self):
        """Nested objects are flattened with dot notation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            records = [
                {"name": "Alice", "address": {"city": "Pune", "state": "Maharashtra"}},
            ]
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f)

            count = C.json_to_csv(json_path, csv_path)
            self.assertEqual(count, 1)

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertIn("address.city", rows[0])
            self.assertEqual(rows[0]["address.city"], "Pune")

    def test_json_list_value(self):
        """List values are JSON-serialized into one cell."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            records = [
                {"name": "Alice", "tags": ["tag1", "tag2"]},
            ]
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f)

            count = C.json_to_csv(json_path, csv_path)

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            # Should be JSON-serialized
            self.assertIn("[", rows[0]["tags"])

    def test_json_none_becomes_empty(self):
        """None values become empty cells."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            records = [
                {"name": "Alice", "note": None},
            ]
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f)

            count = C.json_to_csv(json_path, csv_path)

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertEqual(rows[0]["note"], "")

    def test_json_boolean_values(self):
        """Booleans are serialized as 'true'/'false'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            records = [
                {"name": "Alice", "active": True, "deleted": False},
            ]
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f)

            count = C.json_to_csv(json_path, csv_path)

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertEqual(rows[0]["active"], "true")
            self.assertEqual(rows[0]["deleted"], "false")

    def test_json_different_keys_across_records(self):
        """Records with different keys create union of columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            records = [
                {"name": "Alice", "age": "25"},
                {"name": "Bob", "city": "Pune"},
            ]
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f)

            count = C.json_to_csv(json_path, csv_path)
            self.assertEqual(count, 2)

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            # First record has age, second doesn't
            self.assertEqual(rows[0]["age"], "25")
            self.assertEqual(rows[1]["age"], "")
            # Second record has city, first doesn't
            self.assertEqual(rows[0]["city"], "")
            self.assertEqual(rows[1]["city"], "Pune")

    def test_json_single_column_empty_value(self):
        """Single-column table with empty value preserves row count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            records = [
                {"id": "1"},
                {"id": ""},
                {"id": "3"},
            ]
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f)

            count = C.json_to_csv(json_path, csv_path)
            self.assertEqual(count, 3)

            import pandas as pd
            df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
            self.assertEqual(len(df), 3)

    def test_json_truncated_error_no_data(self):
        """Truncated JSON shows error without quoting data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            with open(json_path, "w", encoding="utf-8") as f:
                f.write('[{"Name": "Ramesh Kum')

            with self.assertRaises(C.ConversionError) as ctx:
                C.json_to_csv(json_path, csv_path)

            error_msg = str(ctx.exception)
            self.assertIn("Not valid JSON:", error_msg)
            # Must not quote the data
            self.assertNotIn("Ramesh", error_msg)

    def test_json_error_status_fail(self):
        """Object without a list of records raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"status": "FAIL"}, f)

            with self.assertRaises(C.ConversionError) as ctx:
                C.json_to_csv(json_path, csv_path)
            self.assertIn("No table found", str(ctx.exception))

    def test_json_error_empty_list(self):
        """Empty list raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([], f)

            with self.assertRaises(C.ConversionError) as ctx:
                C.json_to_csv(json_path, csv_path)
            self.assertIn("The JSON holds no records", str(ctx.exception))

    def test_json_error_list_of_non_dicts(self):
        """List of non-dicts raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([1, 2], f)

            with self.assertRaises(C.ConversionError) as ctx:
                C.json_to_csv(json_path, csv_path)
            self.assertIn("No table found", str(ctx.exception))

    def test_json_error_list_of_empty_dicts(self):
        """List of empty dicts has no columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([{}, {}], f)

            with self.assertRaises(C.ConversionError) as ctx:
                C.json_to_csv(json_path, csv_path)
            self.assertIn("The JSON holds no records", str(ctx.exception))

    def test_json_error_non_utf8(self):
        """Non-UTF-8 bytes raise error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            with open(json_path, "wb") as f:
                f.write(b"\xff\xfe\x00[")

            with self.assertRaises(C.ConversionError) as ctx:
                C.json_to_csv(json_path, csv_path)
            self.assertIn("The file is not UTF-8 text", str(ctx.exception))

    def test_json_two_lists_neither_preferred(self):
        """Two lists with no preferred key raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "output.csv")

            doc = {
                "list1": [{"id": "1"}],
                "list2": [{"id": "2"}],
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(doc, f)

            with self.assertRaises(C.ConversionError) as ctx:
                C.json_to_csv(json_path, csv_path)
            self.assertIn("more than one list of records", str(ctx.exception))


class TestPrepare(unittest.TestCase):
    """Test the prepare() function: the main entry point."""

    def test_prepare_csv_passthrough(self):
        """CSV file passes through untouched."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test.csv")
            with open(csv_path, "w") as f:
                f.write("name,age\nAlice,25\n")

            result = C.prepare(csv_path, tmpdir)

            self.assertEqual(result["path"], csv_path)
            self.assertEqual(result["kind"], "csv")
            self.assertFalse(result["converted"])
            self.assertIsNone(result["records"])
            self.assertEqual(result["sheets"], [])
            self.assertFalse(result["disguised"])

    def test_prepare_json_conversion(self):
        """JSON file is converted to CSV."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            records = [
                {"name": "Alice", "village": "Rampur"},
                {"name": "Bob", "village": "Rampur"},
            ]
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f)

            result = C.prepare(json_path, tmpdir)

            self.assertEqual(result["kind"], "json")
            self.assertTrue(result["converted"])
            self.assertEqual(result["records"], 2)
            self.assertEqual(result["sheets"], [])
            self.assertFalse(result["disguised"])
            # Check the output path
            self.assertTrue(result["path"].endswith("converted/test.csv"))
            # Verify the CSV was created
            self.assertTrue(os.path.exists(result["path"]))

    def test_prepare_json_creates_converted_dir(self):
        """JSON conversion creates the converted directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([{"id": "1"}], f)

            result = C.prepare(json_path, tmpdir)

            converted_dir = os.path.join(tmpdir, "converted")
            self.assertTrue(os.path.isdir(converted_dir))

    def test_prepare_excel_zip_format(self):
        """Excel .xlsx file (zip format) is detected and sheets listed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = os.path.join(tmpdir, "test.xlsx")

            # Create a real Excel file with pandas
            import pandas as pd
            with pd.ExcelWriter(excel_path) as writer:
                pd.DataFrame({"col1": [1, 2]}).to_excel(writer, sheet_name="People", index=False)
                pd.DataFrame({"col2": [3, 4]}).to_excel(writer, sheet_name="Contacts", index=False)

            result = C.prepare(excel_path, tmpdir)

            self.assertEqual(result["kind"], "excel")
            self.assertFalse(result["converted"])
            self.assertEqual(result["path"], excel_path)
            self.assertEqual(result["sheets"], ["People", "Contacts"])
            self.assertIsNone(result["records"])
            self.assertFalse(result["disguised"])

    def test_prepare_excel_xls_ole_format(self):
        """Excel .xls file (OLE format) is detected via sheet_names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = os.path.join(tmpdir, "test.xls")

            # Create a real Excel file with pandas (it may create .xls)
            import pandas as pd
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                pd.DataFrame({"col1": [1, 2]}).to_excel(writer, sheet_name="People", index=False)
                pd.DataFrame({"col2": [3, 4]}).to_excel(writer, sheet_name="Contacts", index=False)

            result = C.prepare(excel_path, tmpdir)

            self.assertEqual(result["kind"], "excel")
            self.assertFalse(result["converted"])
            # Should still be able to get sheet names
            self.assertTrue(len(result["sheets"]) > 0)

    def test_prepare_excel_zip_size_limit(self):
        """Unpacked size over limit raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = os.path.join(tmpdir, "test.xlsx")

            # Create a real Excel file
            import pandas as pd
            df = pd.DataFrame({"col": range(1000)})
            with pd.ExcelWriter(excel_path) as writer:
                df.to_excel(writer, index=False)

            # Patch the limit to something tiny
            original_limit = C.MAX_UNPACKED_BYTES
            self.addCleanup(setattr, C, "MAX_UNPACKED_BYTES", original_limit)
            C.MAX_UNPACKED_BYTES = 10

            with self.assertRaises(C.ConversionError) as ctx:
                C.prepare(excel_path, tmpdir)

            self.assertIn("unpacks to", str(ctx.exception))
            self.assertIn("MB", str(ctx.exception))

    def test_prepare_text_file_named_xls(self):
        """Plain text file named .xls is copied to CSV and marked disguised."""
        with tempfile.TemporaryDirectory() as tmpdir:
            xls_path = os.path.join(tmpdir, "test.xls")
            csv_content = b"name,age\nAlice,25\nBob,30\n"
            with open(xls_path, "wb") as f:
                f.write(csv_content)

            result = C.prepare(xls_path, tmpdir)

            self.assertEqual(result["kind"], "csv")
            self.assertTrue(result["converted"])
            self.assertTrue(result["disguised"])
            self.assertFalse(result["records"])
            # Verify the copy's contents
            with open(result["path"], "rb") as f:
                copied = f.read()
            self.assertEqual(copied, csv_content)

    def test_prepare_html_file_named_xls(self):
        """File named .xls holding HTML raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            xls_path = os.path.join(tmpdir, "test.xls")
            with open(xls_path, "wb") as f:
                f.write(b"<html><table>data</table></html>")

            with self.assertRaises(C.ConversionError) as ctx:
                C.prepare(xls_path, tmpdir)

            self.assertIn("holds HTML or XML", str(ctx.exception))
            self.assertIn(".xls", str(ctx.exception).lower())

    def test_prepare_html_file_named_xlsx(self):
        """File named .xlsx holding HTML raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            xlsx_path = os.path.join(tmpdir, "test.xlsx")
            with open(xlsx_path, "wb") as f:
                f.write(b"<html><table>data</table></html>")

            with self.assertRaises(C.ConversionError) as ctx:
                C.prepare(xlsx_path, tmpdir)

            self.assertIn("holds HTML or XML", str(ctx.exception))
            self.assertIn(".xlsx", str(ctx.exception).lower())

    def test_prepare_binary_file_named_xlsx(self):
        """Random binary file named .xlsx raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            xlsx_path = os.path.join(tmpdir, "test.xlsx")
            # Random binary with NUL bytes (not zip, not OLE, not HTML)
            with open(xlsx_path, "wb") as f:
                f.write(b"\x89PNG\x00random binary\x00junk")

            with self.assertRaises(C.ConversionError) as ctx:
                C.prepare(xlsx_path, tmpdir)

            self.assertIn("Not a valid Excel workbook", str(ctx.exception))

    def test_prepare_bad_zip_file_named_xlsx(self):
        """File starting with ZIP magic but corrupted raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            xlsx_path = os.path.join(tmpdir, "test.xlsx")
            with open(xlsx_path, "wb") as f:
                f.write(b"PK\x03\x04junk not a real zip")

            with self.assertRaises(C.ConversionError) as ctx:
                C.prepare(xlsx_path, tmpdir)

            self.assertIn("Not a valid Excel workbook", str(ctx.exception))

    def test_prepare_unknown_extension(self):
        """File with unknown extension raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = os.path.join(tmpdir, "test.txt")
            with open(txt_path, "w") as f:
                f.write("data")

            with self.assertRaises(C.ConversionError) as ctx:
                C.prepare(txt_path, tmpdir)

            self.assertIn(C.NOT_ACCEPTED, str(ctx.exception))


class TestPdf(unittest.TestCase):
    """A .pdf goes to pdf_text; convert only decides that it is one."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = folder.name
        self.addCleanup(setattr, C.pdf_text, "extract", C.pdf_text.extract)

    def upload(self, name, content=b"%PDF-1.4\n%made up\n"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(content)
        return path

    def test_pdf_names_are_accepted(self):
        self.assertTrue(C.accepted("orders.pdf"))
        self.assertTrue(C.accepted("ORDERS.PDF"))
        self.assertIn(".pdf", C.NOT_ACCEPTED)

    def test_sniff_knows_a_pdf_even_after_leading_junk(self):
        self.assertEqual(C.sniff(self.upload("a.pdf")), "pdf")
        self.assertEqual(C.sniff(self.upload("b.pdf", b"\r\n junk %PDF-1.7\n")), "pdf")

    def test_pdf_is_read_into_the_converted_table(self):
        calls = []
        summary = {"pages": 3, "pages_read": 3, "pages_text": 1, "pages_ocr": 2,
                   "pages_empty": [], "lines": 40, "ocr_confidence": 93}

        def extract(pdf_path, out_csv, progress=None):
            calls.append((pdf_path, out_csv))
            progress(3, 3)
            return summary

        C.pdf_text.extract = extract
        steps = []
        path = self.upload("orders.pdf")
        table = C.prepare(path, self.tmp, progress=lambda d, t: steps.append((d, t)))
        converted = os.path.join(self.tmp, "converted", "orders.csv")
        self.assertEqual(calls, [(path, converted)])
        self.assertEqual(steps, [(3, 3)])
        self.assertEqual(table, {"path": converted, "kind": "pdf", "converted": True,
                                 "records": None, "sheets": [], "disguised": False,
                                 "pdf": summary})

    def test_unreadable_pdf_is_a_conversion_error(self):
        def extract(pdf_path, out_csv, progress=None):
            raise C.pdf_text.PdfError("The PDF is password-protected; remove the "
                                      "password and upload it again")

        C.pdf_text.extract = extract
        with self.assertRaises(C.ConversionError) as ctx:
            C.prepare(self.upload("locked.pdf"), self.tmp)
        self.assertIn("password-protected", str(ctx.exception))

    def test_file_named_pdf_that_is_not_one_never_reaches_the_reader(self):
        def extract(*args, **kwargs):
            raise AssertionError("opened a file that is not a PDF")

        C.pdf_text.extract = extract
        with self.assertRaises(C.ConversionError) as ctx:
            C.prepare(self.upload("notes.pdf", b"Name,Village\nRamesh,Rampur\n"), self.tmp)
        self.assertEqual(str(ctx.exception), C.NOT_A_PDF)

    def test_pdf_named_as_a_workbook_is_not_a_workbook(self):
        with self.assertRaises(C.ConversionError) as ctx:
            C.prepare(self.upload("orders.xls"), self.tmp)
        self.assertEqual(str(ctx.exception), C.NOT_A_WORKBOOK)

    def test_other_kinds_carry_no_pdf_summary(self):
        self.assertIsNone(C.prepare(os.path.join(self.tmp, "a.csv"), self.tmp)["pdf"])


class TestFlatten(unittest.TestCase):
    """Test the flatten() function."""

    def test_flatten_simple_dict(self):
        record = {"name": "Alice", "age": 25}
        flat = C.flatten(record)
        self.assertEqual(flat["name"], "Alice")
        self.assertEqual(flat["age"], 25)

    def test_flatten_nested_dict(self):
        record = {"address": {"city": "Pune", "state": "Maharashtra"}}
        flat = C.flatten(record)
        self.assertEqual(flat["address.city"], "Pune")
        self.assertEqual(flat["address.state"], "Maharashtra")

    def test_flatten_empty_nested_dict(self):
        record = {"nested": {}}
        flat = C.flatten(record)
        self.assertNotIn("nested", flat)

    def test_flatten_list_value(self):
        record = {"tags": ["tag1", "tag2"]}
        flat = C.flatten(record)
        self.assertIn("[", flat["tags"])
        self.assertIn("tag1", flat["tags"])

    def test_flatten_none_value(self):
        record = {"value": None}
        flat = C.flatten(record)
        self.assertEqual(flat["value"], "")

    def test_flatten_boolean_true(self):
        record = {"active": True}
        flat = C.flatten(record)
        self.assertEqual(flat["active"], "true")

    def test_flatten_boolean_false(self):
        record = {"active": False}
        flat = C.flatten(record)
        self.assertEqual(flat["active"], "false")


class TestFindRecords(unittest.TestCase):
    """Test the find_records() function."""

    def test_find_records_list(self):
        doc = [{"id": "1"}, {"id": "2"}]
        records = C.find_records(doc)
        self.assertEqual(len(records), 2)

    def test_find_records_empty_list_error(self):
        doc = []
        with self.assertRaises(C.ConversionError) as ctx:
            C.find_records(doc)
        self.assertIn("holds no records", str(ctx.exception))

    def test_find_records_list_with_non_dict_error(self):
        doc = [{"id": "1"}, "not a dict"]
        with self.assertRaises(C.ConversionError) as ctx:
            C.find_records(doc)
        self.assertIn("expected a list of records", str(ctx.exception))

    def test_find_records_dict_single_list(self):
        doc = {"data": [{"id": "1"}, {"id": "2"}]}
        records = C.find_records(doc)
        self.assertEqual(len(records), 2)

    def test_find_records_dict_multiple_lists(self):
        doc = {
            "rows": [{"id": "1"}],
            "other": [{"id": "2"}],
        }
        records = C.find_records(doc)
        # Should return rows (preferred)
        self.assertEqual(records[0]["id"], "1")

    def test_find_records_dict_no_lists_error(self):
        doc = {"key": "value"}
        with self.assertRaises(C.ConversionError) as ctx:
            C.find_records(doc)
        self.assertIn("No table found", str(ctx.exception))

    def test_find_records_non_dict_non_list_error(self):
        doc = "string"
        with self.assertRaises(C.ConversionError) as ctx:
            C.find_records(doc)
        self.assertIn("No table found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
