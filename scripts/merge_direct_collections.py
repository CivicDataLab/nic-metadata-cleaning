"""Vertically merge the collections flagged merge_method='direct'.

These collections were flagged 'direct' because every member dataset already
carries the full header set recorded in the `Conforms To` column, so the merge
is a plain vertical concatenation -- no column addition, no reshaping.

The concat is done at the byte level (header from the first file, everything
after the first newline for the rest) so that no value is ever re-parsed or
re-quoted. A trailing newline is injected when a source file lacks one.

Outputs one CSV per collection plus a manifest into data/direct_merged/.
"""

import csv
import io
import os
import re
import sys
import time

import duckdb

DB = "transformation/metadata.db"
SRC_DIR = "data/first_batch_downloads"
OUT_DIR = "data/direct_merged"
CHUNK = 16 * 1024 * 1024


def slug(name):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def fetch_members():
    con = duckdb.connect(DB, read_only=True)
    rows = con.execute(
        """
        select Collection, "Identifier[UUID]", nid, Title, "Conforms To"
        from dublin_core_metadata
        where lower(trim(merge_method)) = 'direct'
        """
    ).fetchall()
    con.close()
    groups = {}
    for collection, uuid, nid, title, conforms in rows:
        groups.setdefault(collection, []).append((uuid, nid, title, conforms))
    for members in groups.values():
        members.sort(key=lambda m: m[0])
    return groups


def copy_body(src, dst):
    """Stream everything after the first line; return (lines, ended_with_newline)."""
    first = True
    lines = 0
    last = b"\n"
    while True:
        buf = src.read(CHUNK)
        if not buf:
            break
        if first:
            nl = buf.find(b"\n")
            while nl == -1:
                more = src.read(CHUNK)
                if not more:
                    return 1, buf.endswith(b"\n")
                buf += more
                nl = buf.find(b"\n")
            lines += 1
            buf = buf[nl + 1:]
            first = False
        lines += buf.count(b"\n")
        if buf:
            last = buf[-1:]
            dst.write(buf)
    return lines, last == b"\n"


def merge(collection, members, manifest):
    out_path = os.path.join(OUT_DIR, slug(collection) + ".csv")
    expected = next(csv.reader(io.StringIO(members[0][3])))
    total_src_lines = 0
    started = time.time()

    with open(out_path, "wb") as out:
        # Every source file is CRLF; the data bytes are passed through untouched,
        # so the header must be CRLF too. A lone LF header makes the whole file
        # mixed-ending, which DuckDB's dialect sniffer refuses to read.
        header = ",".join(expected).encode("utf-8") + b"\r\n"
        out.write(header)
        for i, (uuid, nid, title, conforms) in enumerate(members, 1):
            path = os.path.join(SRC_DIR, uuid + ".csv")
            with open(path, "rb") as src:
                lines, ends_nl = copy_body(src, out)
            if not ends_nl:
                out.write(b"\r\n")
                lines += 1
            total_src_lines += lines
            manifest.append(
                {
                    "collection": collection,
                    "uuid": uuid,
                    "nid": nid,
                    "title": title,
                    "source_lines": lines,
                    "data_lines": lines - 1,
                }
            )
            if i % 25 == 0 or i == len(members):
                print(
                    f"  [{collection[:45]}] {i}/{len(members)} files, "
                    f"{total_src_lines - i:,} data lines, {time.time() - started:.0f}s",
                    flush=True,
                )

    out_lines = 1
    with open(out_path, "rb") as f:
        while True:
            buf = f.read(CHUNK)
            if not buf:
                break
            out_lines += buf.count(b"\n")
    out_lines -= 1  # the counted header newline is the same one seeded above

    # A lone-LF header among CRLF data rows makes the file mixed-ending and
    # DuckDB's dialect sniffer rejects it outright, while every line-count check
    # still passes. Assert the ending rather than trusting the write above.
    with open(out_path, "rb") as f:
        head = f.read(4096)
    nl = head.find(b"\n")
    crlf_header = head[nl - 1:nl] == b"\r"

    ok = (out_lines - 1) == (total_src_lines - len(members)) and crlf_header
    print(
        f"DONE {collection}\n"
        f"  file      : {out_path} ({os.path.getsize(out_path) / 1e9:.2f} GB)\n"
        f"  columns   : {len(expected)}\n"
        f"  sources   : {len(members)}\n"
        f"  src lines : {total_src_lines:,} (incl. {len(members)} headers)\n"
        f"  out lines : {out_lines:,} (incl. 1 header)\n"
        f"  crlf hdr  : {crlf_header}\n"
        f"  check     : {'PASS' if ok else 'FAIL'}\n",
        flush=True,
    )
    return ok


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    groups = fetch_members()

    missing = []
    for collection, members in groups.items():
        for uuid, nid, title, _ in members:
            if not os.path.exists(os.path.join(SRC_DIR, uuid + ".csv")):
                missing.append((collection, uuid, nid, title))
    if missing:
        print(f"MISSING {len(missing)} source files:", flush=True)
        for row in missing:
            print("  ", row, flush=True)
        return 1

    # smallest collections first so a bad idiom surfaces in minutes
    order = sorted(
        groups,
        key=lambda c: sum(
            os.path.getsize(os.path.join(SRC_DIR, m[0] + ".csv")) for m in groups[c]
        ),
    )

    manifest = []
    all_ok = True
    for collection in order:
        all_ok &= merge(collection, groups[collection], manifest)

    man_path = os.path.join(OUT_DIR, "merge_manifest.csv")
    with open(man_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
        w.writeheader()
        w.writerows(manifest)
    print(f"manifest -> {man_path} ({len(manifest)} rows)", flush=True)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
