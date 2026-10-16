"""
Unit tests for pdf_text: no GPU, and no tesseract except in the one test that
says so -- OCR is a stub that returns what the "scan" was drawn from.

Fixtures are made on the spot: a scanned page is an image saved as a PDF, a
digital page comes from Ghostscript (tests that need one skip without it).

    .venv/bin/python -m unittest discover -s pii_test/pii_service/tests -v
"""

import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageFont

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_DIR)

import pdf_text as T  # noqa: E402

GS = shutil.which("gs")
PEOPLE = [("Ramesh Kumar Sharma", "9876543210"), ("Sunita Devi", "9123456780"),
          ("Mohammed Irfan Khan", "9812345678")]
# "भारत सरकार, उत्तर प्रदेश राज्य के लाभार्थियों की सूची ..." as a Kruti Dev PDF gives it up.
KRUTI_DEV = ("Hkkjr ljdkj mÙkj izns'k jkT; ds ykHkkfFkZ;ksa dh lwph xzke jkeiqj ftyk "
             "y[kuÅ Jh jes'k dqekj 'kekZ firk dk uke Jh ';ke yky eksckby uEcj fnukad "
             "ls ysdj vkt rd dh fLFkfr ds vuqlkj rS;kj dh xbZ gS")


def scanned_pdf(folder, pages=1, name="scan.pdf", size=(600, 800), resolution=72):
    """An image-only PDF: what a scanner produces."""
    images = [Image.new("L", size, 255) for _ in range(pages)]
    path = os.path.join(folder, name)
    images[0].save(path, "PDF", resolution=resolution, save_all=True,
                   append_images=images[1:])
    return path


def digital_pdf(folder, pages, name="digital.pdf", password=None):
    """A PDF with a text layer; ``pages`` is a list of lists of lines."""
    script = ["%!PS", "/Helvetica findfont 11 scalefont setfont"]
    for lines in pages:
        for i, line in enumerate(lines):
            script.append(f"72 {760 - 18 * i} moveto ({line}) show")
        script.append("showpage")
    source = os.path.join(folder, name + ".ps")
    with open(source, "w", encoding="ascii") as fh:
        fh.write("\n".join(script))
    path = os.path.join(folder, name)
    lock = [f"-sOwnerPassword={password}x", f"-sUserPassword={password}"] if password else []
    subprocess.run([GS, "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite", *lock,
                    f"-sOutputFile={path}", source], check=True)
    return path


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = folder.name
        self.out = os.path.join(self.tmp, "converted", "doc.csv")


class Text(unittest.TestCase):
    def test_clean_lines_drops_blanks_and_control_characters(self):
        self.assertEqual(T.clean_lines("  Ramesh Kumar \r\n\r\n\x00\x0c\nSunita￾ Devi\n"),
                         ["Ramesh Kumar", "Sunita Devi"])

    def test_legacy_hindi_text_is_garbled(self):
        self.assertTrue(T.looks_garbled(KRUTI_DEV))

    def test_ordinary_text_is_not(self):
        english = " ".join(f"{i} {name} resident of Rampur may be contacted on {phone}."
                           for i, (name, phone) in enumerate(PEOPLE * 3))
        hindi = "श्री रमेश कुमार शर्मा, ग्राम रामपुर, ज़िला लखनऊ, मोबाइल 9812345670 " * 4
        codes = "ANP/A/OMC2/BMD1/6000008391 N-PAR/C/OMC4/EMD2/6000002890 PM-KISAN PWD " * 6
        for text in (english, hindi, codes, "", "McDonald iPhone"):
            with self.subTest(text=text[:20]):
                self.assertFalse(T.looks_garbled(text))

    def test_font_name_settles_it(self):
        self.assertTrue(T.looks_garbled("uke", {"abcdef+krutidev010"}))
        self.assertTrue(T.looks_garbled("uke", {"devlys 010"}))
        self.assertFalse(T.looks_garbled("name", {"abcdef+mangal", "helvetica"}))

    def test_words_on_a_line_are_joined_and_noise_is_left_out(self):
        data = {"text": ["", "Ramesh", "Kumar", "9876543210", " ", "Sunita", "Devi", "x"],
                "conf": ["-1", "96", "94", "90", "95", "92", "88", "-1"],
                "block_num": [1, 1, 1, 1, 1, 1, 1, 2],
                "par_num": [1, 1, 1, 1, 1, 1, 1, 1],
                "line_num": [0, 1, 1, 1, 1, 2, 2, 1]}
        lines, confidence = T.lines_from_data(data)
        self.assertEqual(lines, ["Ramesh Kumar 9876543210", "Sunita Devi"])
        self.assertEqual(confidence, 92.0)
        self.assertEqual(T.lines_from_data({"text": [], "conf": [], "block_num": [],
                                            "par_num": [], "line_num": []}), ([], None))


class Scanned(Base):
    def test_page_without_text_goes_to_ocr(self):
        seen = []

        def ocr(image, langs):
            seen.append((image.size, image.mode, langs))
            return [f"{name} {phone}" for name, phone in PEOPLE], 93.0

        summary = T.read_pdf(scanned_pdf(self.tmp, pages=2), self.out, ocr=ocr)
        rows = read_rows(self.out)
        self.assertEqual(summary, {"pages": 2, "pages_read": 2, "pages_text": 0,
                                   "pages_ocr": 2, "pages_empty": [], "lines": 6,
                                   "ocr_confidence": 93})
        self.assertEqual([(r["page"], r["line"]) for r in rows],
                         [("1", "1"), ("1", "2"), ("1", "3"),
                          ("2", "1"), ("2", "2"), ("2", "3")])
        self.assertEqual(rows[0]["text"], "Ramesh Kumar Sharma 9876543210")
        # 600 x 800 points at 300 dpi, greyscale, English before Hindi.
        self.assertEqual(seen[0], ((2500, 3334), "L", "eng+hin"))

    def test_page_the_ocr_cannot_read_is_reported_not_fatal(self):
        calls = []

        def ocr(image, langs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("Tesseract process timeout")
            return ["some text"], 90.0

        summary = T.read_pdf(scanned_pdf(self.tmp, pages=3), self.out, ocr=ocr)
        self.assertEqual(summary["pages_empty"], [2])
        self.assertEqual(summary["lines"], 2)
        self.assertEqual([r["page"] for r in read_rows(self.out)], ["1", "3"])

    def test_blank_scan_writes_a_header_only_table(self):
        summary = T.read_pdf(scanned_pdf(self.tmp), self.out, ocr=lambda i, l: ([], None))
        self.assertEqual(summary["pages_empty"], [1])
        self.assertIsNone(summary["ocr_confidence"])
        with open(self.out, encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "page,line,text")

    def test_pages_past_the_cap_are_not_read(self):
        calls = []
        summary = T.read_pdf(scanned_pdf(self.tmp, pages=5), self.out, max_pages=2,
                             ocr=lambda i, l: (calls.append(1) or ["x"], 90.0))
        self.assertEqual((summary["pages"], summary["pages_read"], len(calls)), (5, 2, 2))

    def test_progress_ends_at_the_last_page(self):
        steps = []
        T.read_pdf(scanned_pdf(self.tmp, pages=4), self.out, ocr=lambda i, l: (["x"], 90.0),
                   progress=lambda done, total: steps.append((done, total)))
        self.assertEqual(steps[-1], (4, 4))
        self.assertTrue(all(total == 4 and 0 <= done <= 4 for done, total in steps))
        self.assertEqual(sorted(steps), steps)

    def test_page_that_claims_to_be_huge_is_rendered_within_the_cap(self):
        import pypdfium2 as pdfium
        path = scanned_pdf(self.tmp, size=(200, 200), resolution=1)     # 14,400 points a side
        image = T.render(pdfium.PdfDocument(path)[0])
        self.assertLessEqual(image.size[0] * image.size[1], T.MAX_PAGE_PIXELS)
        self.assertGreater(image.size[0], 3000)


@unittest.skipUnless(GS, "Ghostscript makes the digital fixtures")
class Digital(Base):
    def never(self, image, langs):
        raise AssertionError("OCR ran on a page that has its own text")

    def lines(self):
        return [f"{i}  {name}   Rampur   {phone}" for i, (name, phone) in enumerate(PEOPLE, 1)]

    def test_text_layer_is_read_without_ocr(self):
        path = digital_pdf(self.tmp, [["List of Beneficiaries, Block Rampur"] + self.lines(),
                                      ["Totals only on this page: 2000 4000 6000"]])
        summary = T.read_pdf(path, self.out, ocr=self.never)
        rows = read_rows(self.out)
        self.assertEqual((summary["pages_text"], summary["pages_ocr"], summary["lines"]),
                         (2, 0, 5))
        self.assertEqual(rows[1], {"page": "1", "line": "2",          # pdfium closes up runs of spaces
                                   "text": "1 Ramesh Kumar Sharma Rampur 9876543210"})
        self.assertEqual(rows[-1]["page"], "2")

    def test_garbled_text_layer_is_ocred_instead(self):
        path = digital_pdf(self.tmp, [KRUTI_DEV.replace("Ù", "U").replace("Å", "A").split(" jkT; ")])
        summary = T.read_pdf(path, self.out, ocr=lambda i, l: (["भारत सरकार"], 91.0))
        self.assertEqual((summary["pages_text"], summary["pages_ocr"]), (0, 1))
        self.assertEqual([r["text"] for r in read_rows(self.out)], ["भारत सरकार"])

    def test_stamp_typed_over_a_scan_keeps_both(self):
        # A signature line on a page that is otherwise one big image.
        path = digital_pdf(self.tmp, [["Digitally signed by A. Sharma, Block Officer"]])
        self.addCleanup(setattr, T, "image_cover", T.image_cover)
        T.image_cover = lambda page: 1.0
        scan = ["1 Ramesh Kumar Sharma 9876543210",
                "Digitally signed by A. Sharma, Block Officer"]
        summary = T.read_pdf(path, self.out, ocr=lambda i, l: (scan, 90.0))
        self.assertEqual(summary["pages_ocr"], 1)
        self.assertEqual([r["text"] for r in read_rows(self.out)],
                         ["Digitally signed by A. Sharma, Block Officer",
                          "1 Ramesh Kumar Sharma 9876543210"])

    def test_a_few_characters_are_not_a_text_layer(self):
        path = digital_pdf(self.tmp, [["- 7 -"]])
        summary = T.read_pdf(path, self.out, ocr=lambda i, l: (["scanned text"], 90.0))
        self.assertEqual((summary["pages_text"], summary["pages_ocr"]), (0, 1))

    def test_password_protected_pdf_says_so(self):
        path = digital_pdf(self.tmp, [self.lines()], password="secret")
        with self.assertRaises(T.PdfError) as caught:
            T.read_pdf(path, self.out, ocr=self.never)
        self.assertIn("password-protected", str(caught.exception))

    def test_child_process_reads_a_pdf(self):
        steps = []
        path = digital_pdf(self.tmp, [self.lines(), ["page two has text as well, enough of it"]])
        summary = T.extract(path, self.out, progress=lambda d, t: steps.append((d, t)))
        self.assertEqual((summary["pages"], summary["pages_text"], summary["lines"]), (2, 2, 4))
        self.assertEqual(steps[-1], (2, 2))
        self.assertEqual(len(read_rows(self.out)), 4)

    def test_child_process_reports_a_locked_pdf(self):
        path = digital_pdf(self.tmp, [self.lines()], password="secret")
        with self.assertRaises(T.PdfError) as caught:
            T.extract(path, self.out)
        self.assertIn("password-protected", str(caught.exception))


class Child(Base):
    """extract(): the PDF is read in another process, and that process can fail."""

    def test_file_that_is_not_a_pdf(self):
        path = os.path.join(self.tmp, "x.pdf")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Name,Village\nRamesh Kumar Sharma,Rampur\n")
        for read in (lambda: T.read_pdf(path, self.out), lambda: T.extract(path, self.out)):
            with self.assertRaises(T.PdfError) as caught:
                read()
            self.assertEqual(str(caught.exception), "Not a valid PDF file")
            self.assertNotIn("Ramesh", str(caught.exception))

    def test_child_that_dies_is_an_unreadable_pdf_not_a_crash_here(self):
        with self.assertRaises(T.PdfError) as caught:
            T.extract(scanned_pdf(self.tmp), self.out, max_pages="not a number")
        self.assertEqual(str(caught.exception), "The PDF could not be read")

    def test_child_that_runs_out_of_time_is_stopped(self):
        with self.assertRaises(T.PdfError) as caught:
            T.extract(scanned_pdf(self.tmp, pages=3), self.out, seconds=0)
        self.assertIn("took too long", str(caught.exception))


@unittest.skipUnless(shutil.which("tesseract"), "needs the tesseract binary")
class RealTesseract(Base):
    def test_a_drawn_page_is_read(self):
        image = Image.new("L", (1700, 500), 255)
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
        except OSError:
            self.skipTest("no DejaVu font to draw the page with")
        for i, (name, phone) in enumerate(PEOPLE):
            draw.text((80, 80 + 110 * i), f"{i + 1}  {name}   Rampur   {phone}", font=font, fill=0)
        path = os.path.join(self.tmp, "drawn.pdf")
        image.save(path, "PDF", resolution=300)
        summary = T.extract(path, self.out)
        text = "\n".join(r["text"] for r in read_rows(self.out))
        self.assertEqual(summary["pages_ocr"], 1)
        for name, phone in PEOPLE:
            self.assertIn(name, text)
            self.assertIn(phone, text)


if __name__ == "__main__":
    unittest.main()
