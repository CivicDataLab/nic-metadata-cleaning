"""
Read a PDF's text into a table of lines -- page, line, text -- for the check.

A page's own text is used when it has some: most government PDFs are written
by a word processor, and that text is exact where OCR guesses. pytesseract
reads the rest:

    a scanned page         no text layer at all
    a stamped scan         a signature block or page number typed over an
                           image that fills the page; both are kept
    a garbled page         Hindi set in a pre-Unicode font (Kruti Dev and its
                           kin) extracts as Latin gibberish -- "Hkkjr ljdkj"
                           for "भारत सरकार" -- in which nothing would be found

One row per line, not per page: a finding has to say which page it is on, and
the detectors read a line far better than 3,000 characters of mixed table
cells.

Everything that touches the PDF runs in a child process (this file, run as a
script). pdfium and tesseract parse a file a stranger uploaded, and the
service has one worker: a crash, a runaway page or a memory bomb has to end
that one run, not the queue behind it. The child limits its own memory, the
parent enforces the clock, and pages past MAX_PDF_PAGES are not read.

Measured on this host (4 cores, tesseract 4.1.1, eng+hin, 300 dpi): a clean
scanned page takes 3 s on one thread and 1.5 s a page on three; a skewed,
noisy one about three times that.

Nothing here logs or raises the text it reads.
"""

import collections
import csv
import ctypes
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading

MAX_PDF_PAGES = 200
# English first. With Hindi first tesseract reads Latin digits through the
# Devanagari model and got 2 of 4 phone numbers wrong on the test page.
OCR_LANGS = "eng+hin"
OCR_DPI = 300
# A4 at 300 dpi is 8.7 megapixels. The cap is on pixels, not dpi: a page can
# declare any size it likes, and 300 dpi of a 5-metre page is a memory bomb.
MAX_PAGE_PIXELS = 12_000_000
OCR_THREADS = 3                      # of 4 cores; the service keeps one
OCR_PAGE_SECONDS = 120
# --psm 1: tesseract works out the layout itself and turns a sideways scan
# the right way up. A fixed single-block layout (--psm 6) read 0 of 40 names
# off a ruled table.
OCR_CONFIG = "--psm 1"

MIN_TEXT_CHARS = 20                  # fewer than this is a page number, not a text layer
STAMP_TEXT_CHARS = 200               # under this, text over a full-page image is a stamp on a scan
IMAGE_COVER = 0.5

CHILD_SECONDS = 30 * 60
CHILD_MEMORY_BYTES = 3 * 2**30

# Pre-Unicode Devanagari fonts: the PDF stores the keystrokes, not the letters.
LEGACY_HINDI_FONTS = ("kruti", "devlys", "chanakya", "shusha", "shivaji",
                      "aps-dv", "apsdv", "kundli", "walkman")

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f￾￿]")
_INNER_CAPITAL_RE = re.compile(r"[a-z][A-Z]")
_ODD_INSIDE_RE = re.compile(r"[A-Za-z][;\[\]{}\\^~|<>=+][A-Za-z]|[¡-ÿ]")


class PdfError(Exception):
    """The PDF cannot be read. str(exc) is shown to the user."""


# --------------------------------------------------------------------------
# One page's own text
# --------------------------------------------------------------------------

def clean_lines(text):
    """A block of text as its non-empty lines."""
    lines = (_CONTROL_RE.sub("", line).strip() for line in (text or "").splitlines())
    return [line for line in lines if line]


def looks_garbled(text, fonts=()):
    """True when a text layer is keystrokes for a legacy Hindi font.

    The font name settles it when the PDF kept one. Otherwise the text does:
    these fonts put conjuncts and matras on capitals, brackets, semicolons
    and Latin-1 symbols, so words carry them in the middle ("ykHkkFkhZ",
    "mÙkj", "jkT;"), which English and romanised Hindi all but never do.
    """
    if any(legacy in font for font in fonts for legacy in LEGACY_HINDI_FONTS):
        return True
    words = [w for w in (text or "").split() if any(c.isalpha() for c in w)]
    if len(words) < 15:
        return False
    odd = sum(1 for w in words
              if _INNER_CAPITAL_RE.search(w) or _ODD_INSIDE_RE.search(w))
    return odd / len(words) > 0.2


def page_fonts(textpage, samples=48):
    """Lower-cased names of the fonts a page's text is set in (a sample of it)."""
    import pypdfium2.raw as raw
    count = textpage.count_chars()
    names, buffer = set(), ctypes.create_string_buffer(256)
    for index in range(0, count, max(1, count // samples)):
        length = raw.FPDFText_GetFontInfo(textpage, index, buffer, len(buffer), None)
        if 1 < length <= len(buffer):
            names.add(buffer.raw[:length - 1].decode("utf-8", "replace").lower())
    return names


def image_cover(page):
    """Share of the page that its largest image covers."""
    import pypdfium2.raw as raw
    width, height = page.get_size()
    largest = 0.0
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]):
        left, bottom, right, top = obj.get_bounds()
        largest = max(largest, max(0.0, right - left) * max(0.0, top - bottom))
    return largest / (width * height) if width and height else 0.0


def text_layer(page):
    """(what to do with the page, the lines its own text gives).

    "text": the layer is the page. "both": keep it and OCR the scan it sits
    on. "ocr": there is no usable layer.
    """
    textpage = page.get_textpage()
    try:
        text = textpage.get_text_range()
        chars = sum(1 for c in text if not c.isspace())
        if chars < MIN_TEXT_CHARS or looks_garbled(text, page_fonts(textpage)):
            return "ocr", []
    finally:
        textpage.close()
    lines = clean_lines(text)
    if chars < STAMP_TEXT_CHARS and image_cover(page) >= IMAGE_COVER:
        return "both", lines
    return "text", lines


# --------------------------------------------------------------------------
# OCR
# --------------------------------------------------------------------------

def render(page):
    """The page as a greyscale image for tesseract, bounded in pixels."""
    width, height = page.get_size()
    scale = OCR_DPI / 72
    if width * height * scale * scale > MAX_PAGE_PIXELS:
        # A shade under, since pdfium rounds each side up to a whole pixel.
        scale = 0.999 * math.sqrt(MAX_PAGE_PIXELS / (width * height))
    return page.render(scale=scale, grayscale=True).to_pil()


def lines_from_data(data):
    """(lines, mean word confidence) from pytesseract.image_to_data's dict.

    Tesseract numbers every word by block, paragraph and line; a line of the
    page is the words that share all three.
    """
    lines, confidences = collections.OrderedDict(), []
    for i, word in enumerate(data["text"]):
        confidence = float(data["conf"][i])
        if not str(word).strip() or confidence < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(str(word))
        confidences.append(confidence)
    mean = sum(confidences) / len(confidences) if confidences else None
    return clean_lines("\n".join(" ".join(words) for words in lines.values())), mean


def ocr_image(image, langs=OCR_LANGS):
    """Read one page image. Returns (lines, mean confidence 0-100 or None)."""
    import pytesseract
    data = pytesseract.image_to_data(
        image, lang=langs, config=OCR_CONFIG,
        output_type=pytesseract.Output.DICT, timeout=OCR_PAGE_SECONDS)
    return lines_from_data(data)


# --------------------------------------------------------------------------
# The document (runs in the child process)
# --------------------------------------------------------------------------

def read_pdf(pdf_path, out_csv, *, max_pages=MAX_PDF_PAGES, langs=OCR_LANGS,
             ocr=ocr_image, progress=None):
    """Write the PDF's lines to ``out_csv``. Returns the summary.

    pdfium is not thread-safe, so every call into it stays on this thread;
    only tesseract, a process of its own per page, runs on the pool. Pages
    wait for it a few at a time so a long scan is never all held as images.
    """
    import pypdfium2 as pdfium
    from concurrent.futures import ThreadPoolExecutor

    try:
        document = pdfium.PdfDocument(pdf_path)
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise PdfError("The PDF is password-protected; remove the "
                           "password and upload it again") from None
        raise PdfError("Not a valid PDF file") from None
    total = len(document)
    if not total:
        raise PdfError("The PDF has no pages")
    wanted = min(total, max_pages)

    pages, pending, confidences = {}, collections.deque(), []
    summary = {"pages": total, "pages_read": wanted, "pages_text": 0,
               "pages_ocr": 0, "pages_empty": [], "lines": 0,
               "ocr_confidence": None}

    def collect(number, own, future):
        try:
            read, confidence = future.result()
        except Exception:                               # noqa: BLE001
            read, confidence = [], None                 # timed out or unreadable
        if confidence is not None:
            confidences.append(confidence)
        pages[number] = own + [line for line in read if line not in own]

    with ThreadPoolExecutor(OCR_THREADS) as pool:
        for index in range(wanted):
            page = document[index]
            try:
                how, own = text_layer(page)
                if how == "text":
                    summary["pages_text"] += 1
                    pages[index + 1] = own
                else:
                    summary["pages_ocr"] += 1
                    pending.append((index + 1, own,
                                    pool.submit(ocr, render(page), langs)))
            finally:
                page.close()
            while len(pending) > OCR_THREADS * 2 or (pending and pending[0][2].done()):
                collect(*pending.popleft())
            if progress:
                progress(index + 1 - len(pending), wanted)
        while pending:
            collect(*pending.popleft())
            if progress:
                progress(wanted - len(pending), wanted)
    document.close()

    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["page", "line", "text"])
        for number in range(1, wanted + 1):
            lines = pages.get(number, [])
            if not lines:
                summary["pages_empty"].append(number)
            for i, line in enumerate(lines, 1):
                writer.writerow([number, i, line])
            summary["lines"] += len(lines)
    if confidences:
        summary["ocr_confidence"] = round(sum(confidences) / len(confidences))
    return summary


def main(argv):
    """Child entry point: ``pdf_text.py <pdf> <out.csv> <max pages> <langs>``.

    Prints ``PAGE done total`` as it goes, then ``DONE <summary json>`` or
    ``ERROR <message>``. Anything else -- a crash, a kill -- the parent reads
    as an unreadable PDF.
    """
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (CHILD_MEMORY_BYTES, CHILD_MEMORY_BYTES))
    pdf_path, out_csv, max_pages, langs = argv
    try:
        summary = read_pdf(
            pdf_path, out_csv, max_pages=int(max_pages), langs=langs,
            progress=lambda done, total: print(f"PAGE {done} {total}", flush=True))
    except PdfError as exc:
        print(f"ERROR {exc}", flush=True)
        return 2
    print("DONE " + json.dumps(summary), flush=True)
    return 0


# --------------------------------------------------------------------------
# The parent's side
# --------------------------------------------------------------------------

def extract(pdf_path, out_csv, *, max_pages=None, langs=OCR_LANGS,
            progress=None, seconds=None):
    """Read ``pdf_path`` into ``out_csv`` in a child process. Returns the summary.

    Raises PdfError when the PDF cannot be read, takes longer than
    ``seconds``, or brings the child down.
    """
    max_pages = MAX_PDF_PAGES if max_pages is None else max_pages
    seconds = CHILD_SECONDS if seconds is None else seconds
    # One tesseract thread per page: three pages at a time already fill the
    # cores the service can spare.
    env = dict(os.environ, OMP_THREAD_LIMIT="1", OPENBLAS_NUM_THREADS="1")
    # Its own process group, so that stopping it also stops the tesseract
    # processes it started: killed alone, it would leave up to three of them
    # grinding on a page with nobody waiting for the answer.
    child = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), pdf_path, out_csv,
         str(max_pages), langs],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env,
        start_new_session=True)
    timed_out = threading.Event()

    def kill_group():
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def stop():
        timed_out.set()
        kill_group()

    timer = threading.Timer(seconds, stop)
    timer.start()
    summary = error = None
    try:
        for line in child.stdout:
            kind, _, rest = line.rstrip("\n").partition(" ")
            if kind == "PAGE" and progress:
                done, total = rest.split()
                progress(int(done), int(total))
            elif kind == "DONE":
                summary = json.loads(rest)
            elif kind == "ERROR":
                error = rest
        child.wait()
    finally:
        timer.cancel()
        kill_group()                # the child if it is still there, and any page left running
        child.wait()
        child.stdout.close()
    if timed_out.is_set():
        raise PdfError(f"The PDF took too long to read (over "
                       f"{max(1, seconds // 60)} minutes); split it into "
                       f"smaller files")
    if error:
        raise PdfError(error)
    if child.returncode != 0 or summary is None:
        raise PdfError("The PDF could not be read")
    return summary


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
