"""Re-merge the 4 merge_method='direct' collections with an nid column, chunking two of them.

Adds `nid` as the LAST column of every row so a reader can trace any row back to the
dataset it came from. Two collections are additionally split into <=1 GiB chunks.

Written as a fresh pass over the original per-dataset sources, not over the previously
merged files -- the merged files don't carry nid.

LOAD-BEARING PRECONDITION: the nid is appended with a byte-level
    block.replace(b'\\r\\n', b',<nid>\\r\\n')
which is only correct because no field in these files contains an embedded newline.
That was verified on all four merged outputs: physical line count == CSV-parsed record
count exactly (769,582 / 2,077,539 / 11,653,126 / 68,784,955), with zero ragged rows.
If that ever stops holding, this approach corrupts rows silently and must be replaced
with a real CSV round-trip.

Note: adding nid means the outputs no longer match their `Conforms To` string, and the
last column is now nid rather than year/id/Id.
"""

import csv
import io
import os
import re
import sys
import time
from collections import Counter

import duckdb

DB = "transformation/metadata.db"
SRC_DIR = "data/first_batch_downloads"
OUT_DIR = "data/direct_merged/with_nid"
READ_BLOCK = 32 * 1024 * 1024
GIB = 1024 * 1024 * 1024          # Google Drive labels binary units "GB"
CHUNK_LIMIT = GIB                  # roll BEFORE exceeding, so every chunk is <= 1 GiB

# collections to split into chunks (the rest are written as one file)
CHUNKED = {
    "Annual Health Survey : Woman Schedule (Section-II)",
    "Annual Health Survey : Woman Schedule (Section-I)",
    "Combined Household Houselist Information under Annual Health Survey",
}

# row counts established by full CSV parse of the previous merge -- used as an
# independent cross-check, not as this run's source of truth
PREV_VERIFIED = {
    "Annual Health Survey : Mortality Schedule": 769_582,
    "Annual Health Survey : Woman Schedule (Section-II)": 2_077_539,
    "Annual Health Survey : Woman Schedule (Section-I)": 11_653_126,
    "Combined Household Houselist Information under Annual Health Survey": 68_784_955,
}


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
        groups.setdefault(collection, []).append((uuid, str(nid).strip(), title, conforms))
    for members in groups.values():
        members.sort(key=lambda m: m[0])
    return groups


class Output:
    """Writes whole CSV lines, rolling to a new chunk before exceeding the limit."""

    def __init__(self, header, single_path=None, chunk_dir=None, base=None, limit=None):
        self.header = header
        self.single_path = single_path
        self.chunk_dir = chunk_dir
        self.base = base
        self.limit = limit
        self.f = None
        self.n_chunks = 0
        self.bytes = 0
        self.rows = 0
        self.nidrows = Counter()
        self.index = []          # per-chunk stats
        self.nid_map = []        # (chunk_name, nid, rows)
        self.total_rows = 0

    # -- file lifecycle (lazy open, so a roll never leaves an empty trailing chunk)
    def _ensure(self):
        if self.f is not None:
            return
        if self.limit is None:
            self.path = self.single_path
        else:
            self.n_chunks += 1
            self.path = os.path.join(self.chunk_dir, f"{self.base}_part_{self.n_chunks:04d}.csv")
        self.f = open(self.path, "wb")
        self.f.write(self.header)
        self.bytes = len(self.header)
        self.rows = 0
        self.nidrows = Counter()

    def _close(self):
        if self.f is None:
            return
        self.f.close()
        name = os.path.basename(self.path)
        self.index.append({"chunk": name, "rows": self.rows, "bytes": self.bytes})
        for nid, n in self.nidrows.items():
            self.nid_map.append((name, nid, n))
        self.f = None

    def _put(self, piece, nid):
        self.f.write(piece)
        n = piece.count(b"\r\n")
        self.bytes += len(piece)
        self.rows += n
        self.nidrows[nid] += n
        self.total_rows += n

    def write(self, data, nid):
        while data:
            self._ensure()
            if self.limit is None:
                self._put(data, nid)
                return
            room = self.limit - self.bytes
            if len(data) <= room:
                self._put(data, nid)
                return
            # need to split at a line boundary that still fits
            cut = data.rfind(b"\r\n", 0, room)
            if cut == -1:
                if self.rows > 0:
                    self._close()      # nothing fits; start a fresh chunk
                    continue
                # pathological: a single line larger than the limit -> write it whole
                nl = data.find(b"\r\n")
                cut = nl if nl != -1 else len(data) - 2
            self._put(data[: cut + 2], nid)
            data = data[cut + 2 :]
            self._close()

    def finish(self):
        self._close()


def stream_source(path, nid, stats):
    """Yield transformed blocks of whole lines, nid appended to each row."""
    suffix = b"," + nid.encode("ascii") + b"\r\n"
    carry = b""
    header_done = False
    with open(path, "rb") as f:
        while True:
            block = f.read(READ_BLOCK)
            if not block:
                break
            data = carry + block
            carry = b""
            if not header_done:
                i = data.find(b"\r\n")
                if i == -1:
                    carry = data
                    continue
                data = data[i + 2 :]
                header_done = True
            idx = data.rfind(b"\r\n")
            if idx == -1:
                carry = data
                continue
            carry = data[idx + 2 :]
            yield data[: idx + 2].replace(b"\r\n", suffix)
    if carry:
        # final line had no terminator -- never observed in this corpus, so flag it
        stats["terminatorless"] += 1
        yield carry + suffix


def merge_sidecar(path, fieldnames, new_rows, processed):
    """Rewrite a sidecar, replacing only the processed collections' rows.

    A filtered run must not drop the other collections' entries, so existing rows
    are carried forward untouched unless their collection was reprocessed.
    """
    kept = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            kept = [r for r in csv.DictReader(f) if r["collection"] not in processed]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(kept)
        w.writerows({k: r[k] for k in fieldnames} for r in new_rows)
    return len(kept), len(new_rows)


def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].lower()

    os.makedirs(OUT_DIR, exist_ok=True)
    groups = fetch_members()
    if only:
        groups = {c: m for c, m in groups.items() if only in c.lower()}
        if not groups:
            print(f"no collection matches --only {only!r}", flush=True)
            return 1
        print(f"--only {only!r} -> {list(groups)}", flush=True)

    missing = [
        (c, m[0]) for c, ms in groups.items() for m in ms
        if not os.path.exists(os.path.join(SRC_DIR, m[0] + ".csv"))
    ]
    if missing:
        print(f"MISSING {len(missing)} source files: {missing[:5]}", flush=True)
        return 1

    manifest = []
    chunk_index = []
    nid_map = []
    all_ok = True

    order = sorted(groups, key=lambda c: sum(
        os.path.getsize(os.path.join(SRC_DIR, m[0] + ".csv")) for m in groups[c]))

    for collection in order:
        members = groups[collection]
        cols = next(csv.reader(io.StringIO(members[0][3])))
        header = (",".join(cols + ["nid"])).encode("utf-8") + b"\r\n"
        base = slug(collection)
        chunked = collection in CHUNKED
        started = time.time()

        if chunked:
            cdir = os.path.join(OUT_DIR, base)
            os.makedirs(cdir, exist_ok=True)
            for old in os.listdir(cdir):
                os.remove(os.path.join(cdir, old))
            out = Output(header, chunk_dir=cdir, base=base, limit=CHUNK_LIMIT)
            dest = cdir
        else:
            out = Output(header, single_path=os.path.join(OUT_DIR, base + ".csv"))
            dest = out.single_path

        stats = Counter()
        for i, (uuid, nid, title, _) in enumerate(members, 1):
            before = out.total_rows
            for blk in stream_source(os.path.join(SRC_DIR, uuid + ".csv"), nid, stats):
                out.write(blk, nid)
            manifest.append({
                "collection": collection, "uuid": uuid, "nid": nid,
                "title": title, "data_rows": out.total_rows - before,
            })
            if i % 25 == 0 or i == len(members):
                print(f"  [{base[:40]}] {i}/{len(members)} files, "
                      f"{out.total_rows:,} rows, {time.time()-started:.0f}s", flush=True)
        out.finish()

        for e in out.index:
            e["collection"] = collection
            chunk_index.append(e)
        nid_map.extend((c, n, r, collection) for c, n, r in out.nid_map)

        prev = PREV_VERIFIED[collection]
        rows_ok = out.total_rows == prev
        sizes = [e["bytes"] for e in out.index]
        # the 1 GiB cap only applies to collections we actually chunk; a single-file
        # output is legitimately larger and must not be failed for it
        size_ok = all(s <= CHUNK_LIMIT for s in sizes) if chunked else True
        nonempty_ok = all(e["rows"] >= 1 for e in out.index)
        chunk_sum_ok = sum(e["rows"] for e in out.index) == out.total_rows
        ok = rows_ok and size_ok and nonempty_ok and chunk_sum_ok
        all_ok &= ok

        cap_note = f"(<=1 GiB: {size_ok})" if chunked else "(single file, cap n/a)"
        print(
            f"DONE {collection}\n"
            f"  dest      : {dest}\n"
            f"  columns   : {len(cols)} + nid = {len(cols)+1}\n"
            f"  parts     : {len(out.index)}\n"
            f"  rows      : {out.total_rows:,} (prev verified {prev:,}) {'MATCH' if rows_ok else 'MISMATCH'}\n"
            f"  max part  : {max(sizes)/GIB:.4f} GiB {cap_note}\n"
            f"  parts sum : {chunk_sum_ok}   nonempty: {nonempty_ok}\n"
            f"  no-term   : {stats['terminatorless']} source files ended without newline\n"
            f"  check     : {'PASS' if ok else 'FAIL'}\n",
            flush=True,
        )

    processed = set(groups)
    nid_rows = [{"collection": coll, "chunk": c, "nid": n, "rows": r} for c, n, r, coll in nid_map]

    a = merge_sidecar(os.path.join(OUT_DIR, "merge_manifest.csv"),
                      ["collection", "uuid", "nid", "title", "data_rows"], manifest, processed)
    b = merge_sidecar(os.path.join(OUT_DIR, "chunk_index.csv"),
                      ["collection", "chunk", "rows", "bytes"], chunk_index, processed)
    c = merge_sidecar(os.path.join(OUT_DIR, "chunk_nid_map.csv"),
                      ["collection", "chunk", "nid", "rows"], nid_rows, processed)
    print(f"manifest kept/{a[0]} new/{a[1]} | chunk_index kept/{b[0]} new/{b[1]} "
          f"| nid_map kept/{c[0]} new/{c[1]}", flush=True)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
