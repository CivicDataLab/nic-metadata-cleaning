#!/usr/bin/env python3
"""
Evidence packs for reviewing collections, one per batch, for the subagents that
decide them (see transformation/collection_rules_change_in_header.md).

Scope: collections in collection_worktable with merge_method = change_in_header
and merge_add_columns = 'review', on rows no one has decided yet (not locked,
no batch). --state orig builds from the orig_* columns instead and ignores
locks -- used for the calibration pack, whose answers are the user's edits.

Per batch it writes, into --out:
  <B>.md    what the agent reads: per collection the detector evidence, my
            earlier (unapproved) proposal, reconciled header variants, members
            (all of them up to 60, else grouped), parsed year windows with
            nested / overlapping pairs, and similar rows outside the collection
  <B>.json  the machine side: member nids per collection and per group id, so
            collection_worktable.py load can expand 'all' / 'rest' / 'G3'
plus table_index.tsv (nid, ministry, merge_method, Collection, status, Title)
for grepping, and batches.csv (collection -> batch).

Read-only on the DB.
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
from rapidfuzz import fuzz, process

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))     # dataset_merge
sys.path.insert(0, str(HERE))            # sibling utils (takes precedence)

from detect_collection_defects import DIST_RE_WIDE, analyse              # noqa: E402
from header_reconcile import BROKEN, header_match, reconcile_cols         # noqa: E402
from refine_direct_merge_method import MONTH_RE, STATE_RE, YEAR_RE        # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
MAIN = "dublin_core_remaining"
WORK = "collection_worktable"
PRIOR = HERE.parent / "collection_decisions_change_in_header.csv"
DOWNLOADS = HERE.parent.parent / "data" / "final_batch_downloads"
LIST_ALL_UP_TO = 60

# ── title parsing ────────────────────────────────────────────────────────────
Y = r"(?:19|20)\d{2}(?:\s*-\s*\d{2,4})?"
SPAN_PATTERNS = [
    re.compile(rf"\b(?:from|between)\s+({Y})\s+(?:to|and|till|-)\s+({Y})", re.I),
    re.compile(rf"\b({Y})\s+(?:to|till)\s+({Y})\b", re.I),
]
POINT_PATTERNS = [
    re.compile(rf"\b(?:during|for|in|of|at the end of|end of|as on\s+[\d.]*|"
               rf"up\s*to\s+\w+,?|upto\s+\w+\.?,?)\s*({Y})\b", re.I),
    re.compile(rf",\s*({Y})\b"),
    re.compile(rf"\b({Y})\s*$"),
]
LEAD_NOISE = re.compile(r"^(?:year[- ]wise|yearly|annual)\s+", re.I)


def year_of(s):
    m = re.match(r"(19|20)\d{2}", s)
    return int(m.group(0)) if m else None


def parse_window(title):
    """-> (series key, start, end, label) from a title; start/end None if none."""
    t = title or ""
    for pat in SPAN_PATTERNS:
        m = pat.search(t)
        if m:
            a, b = year_of(m.group(1)), year_of(m.group(2))
            key = series_key(t[:m.start()] + " " + t[m.end():])
            return key, a, b, m.group(0).strip()
    for pat in POINT_PATTERNS:
        m = pat.search(t)
        if m:
            a = year_of(m.group(1))
            key = series_key(t[:m.start()] + " " + t[m.end():])
            return key, a, a, m.group(0).strip()
    return series_key(t), None, None, ""


def series_key(t):
    t = LEAD_NOISE.sub("", t.strip())
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def template(title):
    """Title with district / state / year / month values replaced by slots."""
    t = title or ""
    t = DIST_RE_WIDE.sub("<DIST> District", t)
    t = STATE_RE.sub("<STATE>", t)
    t = YEAR_RE.sub("<YEAR>", t)
    t = MONTH_RE.sub(" <MONTH> ", t)
    return re.sub(r"\s+", " ", t).strip()


def match_key(title):
    """Template further stripped of slots and punctuation, for similarity search."""
    t = re.sub(r"<[A-Z]+>", " ", template(title))
    t = re.sub(r"\b(?:during|from|to|for|in|of|the|at|end|up|upto|as|on|district)\b", " ", t, flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


YEAR_IN_COL = re.compile(r"(?:19|20)\d{2}")


def year_col_share(conforms_to):
    cols = [c for c in (conforms_to or "").split(",") if c.strip()]
    if not cols:
        return None
    return sum(bool(YEAR_IN_COL.search(c)) for c in cols) / len(cols)


# ── batches ──────────────────────────────────────────────────────────────────
CENSUS_FAMILIES = [
    ("C1", r"married women|scheduled castes? population|scheduled tribes? population|"
           r"religion wise|other religions|mother tongue|distribution of scheduled caste"),
    ("C2", r"^main workers"),
    ("C4", r"workers|non-workers|occupational classification"),
    ("C3", r".*"),
]


def assign_batches(colls):
    """colls: {name: ministry} -> {name: batch id}."""
    out = {}
    by_min = defaultdict(list)
    for c, m in colls.items():
        by_min[m].append(c)
    small = []
    for m, cs in sorted(by_min.items()):
        cs.sort(key=str.lower)
        low = m.lower()
        if "census" in low:
            for c in cs:
                out[c] = next(b for b, pat in CENSUS_FAMILIES if re.search(pat, c, re.I))
        elif "ncrb" in low:
            k = 4
            size = -(-len(cs) // k)
            for i, c in enumerate(cs):
                out[c] = f"N{i // size + 1}"
        elif "statistics" in low or "civil aviation" in low:
            for c in cs:
                out[c] = "MA"
        elif "animal husbandry" in low:
            for c in cs:
                out[c] = "AH"
        elif "road transport" in low:
            for c in cs:
                out[c] = "RT"
        else:
            small += cs
    for c in small:
        out[c] = "SM"
    return out


# ── pack writing ─────────────────────────────────────────────────────────────

def file_map(cache):
    """uuid -> file name in data/final_batch_downloads (one scandir, cached)."""
    if cache.exists():
        return json.loads(cache.read_text())
    print("listing downloads (one-off, ~2 min) ...", flush=True)
    m = {}
    with os.scandir(DOWNLOADS) as it:
        for e in it:
            stem = e.name.split(".", 1)[0]
            m[stem] = e.name
    cache.write_text(json.dumps(m))
    return m


def fmt_span(a, b):
    if a is None:
        return "-"
    return str(a) if a == b else f"{a}-{b}"


def build(args):
    con = duckdb.connect(args.db, read_only=True)
    st = "orig_" if args.state == "orig" else ""
    mm_col = f"w.{st}merge_method"
    coll_col = f'w.{st}Collection' if st else 'w."Collection"'
    mac_col = f"w.{st}merge_add_columns"

    rows = con.execute(f"""
        SELECT w.nid, w.Title, w.ministry, {mm_col}, {coll_col}, {mac_col},
               w.locked, w.batch, w.merge_method, w."Collection",
               d."Conforms To", d.header_count, d.year,
               d.data_time_period_from, d.data_time_period_to, d."Identifier[UUID]"
        FROM {WORK} w JOIN {MAIN} d ON CAST(d.nid AS VARCHAR) = w.nid""").fetchall()
    R = {r[0]: r for r in rows}
    NID, TITLE, MIN, MM, COLL, MAC, LOCKED, BATCH, NOW_MM, NOW_COLL, HDR, HC, YR, PF, PT, UUID = range(16)

    if args.collections:
        scope = set(Path(args.collections).read_text().splitlines()) - {""}
    else:
        scope = {r[COLL] for r in rows if r[MM] == "change_in_header" and r[MAC] == "review"
                 and r[COLL] and (args.state == "orig" or (not r[LOCKED] and not r[BATCH]))}
    members = defaultdict(list)
    for r in rows:
        if r[COLL] in scope:
            members[r[COLL]].append(r)
    if args.state != "orig":
        # a collection only partly undecided: pack just the undecided part
        for c in list(members):
            members[c] = [r for r in members[c] if not r[LOCKED] and not r[BATCH]]
            if not members[c]:
                del members[c]
    ministries = {c: Counter(r[MIN] for r in ms).most_common(1)[0][0] for c, ms in members.items()}
    batch_of = ({c: args.batch_name for c in members} if args.batch_name
                else assign_batches(ministries))
    if args.only_batch:
        wanted = set(args.only_batch.split(","))
    else:
        wanted = set(batch_of.values())

    # detector evidence (keyed by collection) and my earlier proposals
    recs, _, _ = analyse(con, MAIN, "change_in_header", 0.5)
    detector = {r["Collection"]: r for r in recs}
    prior = {}
    if PRIOR.exists():
        with open(PRIOR, newline="", encoding="utf-8") as fh:
            prior = {r["Collection"]: r for r in csv.DictReader(fh)}

    fmap = file_map(Path(args.out) / "uuid_files.json")

    # similarity index per ministry
    by_min_rows = defaultdict(list)
    for r in rows:
        by_min_rows[r[MIN]].append(r)
    keys_by_min = {}
    for m, rs in by_min_rows.items():
        kk = defaultdict(list)
        for r in rs:
            kk[match_key(r[TITLE])].append(r[NID])
        keys_by_min[m] = kk

    def status(r):
        c = r[COLL]
        if args.state != "orig" and r[LOCKED]:
            return f"LOCKED(user: {r[NOW_MM]} / {r[NOW_COLL] or '-'})"
        if args.state != "orig" and r[BATCH]:
            return f"decided in batch {r[BATCH]}"
        if c in batch_of:
            b = batch_of[c]
            return f"in scope, batch {b}" + ("" if b in wanted and b == cur_batch else " - do not claim")
        return "free"

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    gnum = 0
    for cur_batch in sorted(wanted):
        colls = sorted((c for c, b in batch_of.items() if b == cur_batch), key=str.lower)
        md, js = [], {"batch": cur_batch, "collections": {}}
        md.append(f"# Evidence pack {cur_batch}: {len(colls)} collections, "
                  f"{sum(len(members[c]) for c in colls)} rows\n")
        for ci, c in enumerate(colls, 1):
            ms = sorted(members[c], key=lambda r: (r[TITLE] or "").lower())
            det = detector.get(c, {})
            pr = prior.get(c)
            md.append(f"\n---\n\n## C{ci} · {c}\n")
            md.append(f"- ministry: {ministries[c]} | members in scope: {len(ms)} | "
                      f"current mac: {Counter(r[MAC] for r in ms).most_common(1)[0][0]}")
            if det:
                md.append(f"- detector: flags {det.get('defect_flags', '')} | min_header_match "
                          f"{det.get('min_header_match', '')} | admin levels {det.get('admin_levels') or '-'}"
                          f" | varying dims {det.get('varying_dims') or '-'} | suggested mac "
                          f"{det.get('suggested_mac') or '-'} | header dims {det.get('header_dims') or '-'}")
                if det.get("varying_title_tokens"):
                    md.append(f"- varying title text: {det['varying_title_tokens'][:600]}")
            if pr:
                md.append(f"- prior proposal (Claude, NOT approved by the user; the rules override it): "
                          f"action={pr['action']} | name={pr['new_collection_name'] or '(unchanged)'} | "
                          f"mac={pr['new_merge_add_columns'] or '-'}"
                          + (f" | split_rule={pr['split_rule'][:700]}" if pr.get("split_rule") else "")
                          + (f" | notes={pr['notes']}" if pr.get("notes") else ""))

            # header variants
            hgroups = defaultdict(list)
            for r in ms:
                h = r[HDR]
                key = ("BROKEN" if h and BROKEN.search(h)
                       else (frozenset(reconcile_cols(h)) if h else None))
                hgroups[key].append(r)
            hord = sorted(hgroups.items(), key=lambda kv: -len(kv[1]))
            hid = {k: f"H{i}" for i, (k, _) in enumerate(hord, 1)}
            dom = next((k for k, _ in hord if isinstance(k, frozenset)), None)
            md.append("\n### Header variants (after reconciling spelling/case/units/S.No./years)\n")
            for k, rs in hord:
                if not isinstance(k, frozenset):
                    md.append(f"- {hid[k]} [{len(rs)}] {'NO HEADERS EXTRACTED' if k is None else 'ERROR PAGE, not data'}")
                    continue
                cols = reconcile_cols(rs[0][HDR])
                ycs = max((year_col_share(r[HDR]) or 0) for r in rs)
                line = (f"- {hid[k]} [{len(rs)}] {len(cols)} cols, year-labelled cols "
                        f"{ycs:.0%}: " + " | ".join(list(cols.values())[:30])
                        + (f" ... (+{len(cols) - 30} more)" if len(cols) > 30 else ""))
                if k != dom and dom is not None:
                    score = header_match(set(k), set(dom))
                    only_here = [cols[x] for x in k - dom][:10]
                    only_dom = sorted(dom - k)[:10]
                    line += (f"\n    match vs H1 {'-' if score is None else f'{score:.2f}'}; "
                             f"only here: {only_here}; only in H1: {only_dom}")
                md.append(line)

            # groups: header variant x title template
            gmap = defaultdict(list)
            for r in ms:
                hk = r[HDR]
                k = ("BROKEN" if hk and BROKEN.search(hk)
                     else (frozenset(reconcile_cols(hk)) if hk else None))
                gmap[(hid[k], template(r[TITLE]))].append(r)
            gid = {}
            groups_js = {}
            for (h, tpl), rs in sorted(gmap.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                gnum += 1
                gid[(h, tpl)] = f"G{gnum}"
                groups_js[f"G{gnum}"] = [r[NID] for r in rs]
            js["collections"][c] = {"nids": [r[NID] for r in ms], "groups": groups_js,
                                    "ministry": ministries[c]}

            # windows over members + outside candidates of the same series
            wins = {r[NID]: parse_window(r[TITLE]) for r in ms}

            md.append("\n### Members\n")
            if len(ms) <= 25 or (len(ms) <= LIST_ALL_UP_TO and len(gmap) * 3 > len(ms)):
                md.append("nid | group | header | window | yr-cols | period (data) | file | title")
                for r in ms:
                    k = ("BROKEN" if r[HDR] and BROKEN.search(r[HDR])
                         else (frozenset(reconcile_cols(r[HDR])) if r[HDR] else None))
                    g = gid[(hid[k], template(r[TITLE]))]
                    _, a, b, _ = wins[r[NID]]
                    ycs = year_col_share(r[HDR])
                    f = fmap.get(r[UUID] or "", "")
                    md.append(f"{r[NID]} | {g} | {hid[k]} | {fmt_span(a, b)} | "
                              f"{'-' if ycs is None else f'{ycs:.0%}'} | "
                              f"{str(r[PF] or '')[:10]}..{str(r[PT] or '')[:10]} | "
                              f"{f or 'NOT DOWNLOADED'} | {r[TITLE]}")
            else:
                md.append(f"{len(ms)} members, grouped (group | header | members | years in titles | sample titles):")
                for (h, tpl), rs in sorted(gmap.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                    yrs = Counter(fmt_span(*wins[r[NID]][1:3]) for r in rs)
                    samples = sorted({r[TITLE] for r in rs})[:3]
                    md.append(f"- {gid[(h, tpl)]} | {h} | {len(rs)} | "
                              + ", ".join(f"{y}x{n}" for y, n in sorted(yrs.items()))
                              + f" | template: {tpl}\n    e.g. " + " || ".join(samples))

            # outside candidates
            mkeys = {match_key(r[TITLE]) for r in ms}
            pool = keys_by_min.get(ministries[c], {})
            choices = list(pool.keys())
            cand = {}
            for mk in mkeys:
                if not mk:
                    continue
                for ch, sc, _ in process.extract(mk, choices, scorer=fuzz.ratio,
                                                 score_cutoff=85, limit=None):
                    cand[ch] = max(cand.get(ch, 0), sc)
                for ch, sc, _ in process.extract(mk, choices, scorer=fuzz.token_set_ratio,
                                                 score_cutoff=97, limit=None):
                    cand[ch] = max(cand.get(ch, 0), round(sc * 0.9))
            member_ids = {r[NID] for r in ms}
            outside = [R[n] for ch in cand for n in pool[ch] if n not in member_ids]
            score_of = {n: cand[ch] for ch in cand for n in pool[ch]}
            if outside:
                # rows sitting in other collections: one line per collection
                by_coll = defaultdict(list)
                loose = []
                for r in outside:
                    if r[COLL]:
                        by_coll[(r[COLL], r[MM])].append(r)
                    else:
                        loose.append(r)
                md.append("\n### Similar rows outside this collection (same ministry)\n")
                for (oc, omm), rs in sorted(by_coll.items(), key=lambda kv: -max(score_of[r[NID]] for r in kv[1]))[:12]:
                    st_ = Counter(status(r) for r in rs).most_common(1)[0][0]
                    md.append(f"- collection [{len(rs)}] {oc} ({omm}; {st_}); best score "
                              f"{max(score_of[r[NID]] for r in rs)}; e.g. {rs[0][NID]} {rs[0][TITLE]}")
                loose.sort(key=lambda r: -score_of[r[NID]])
                for r in loose[:20]:
                    _, a, b, _ = parse_window(r[TITLE])
                    f = fmap.get(r[UUID] or "", "")
                    md.append(f"- nid {r[NID]} ({r[MM]}, no collection; {status(r)}; score "
                              f"{score_of[r[NID]]}; window {fmt_span(a, b)}; hdr "
                              f"{(r[HDR] or 'NONE')[:120]!r}; file {f or 'NOT DOWNLOADED'}) {r[TITLE]}")
                if len(loose) > 20:
                    md.append(f"- ... {len(loose) - 20} more loose rows (grep table_index.tsv)")
                for r in outside:
                    wins.setdefault(r[NID], parse_window(r[TITLE]))

            # nested / overlapping windows among members + outside rows
            series = defaultdict(list)
            for n, (key, a, b, lab) in wins.items():
                if a is not None and a != b:
                    series[key].append((a, b, n, lab))
            nested, overlap = [], []
            for key, ws in series.items():
                ws.sort()
                for i in range(len(ws)):
                    for j in range(len(ws)):
                        if i == j:
                            continue
                        a1, b1, n1, l1 = ws[i]
                        a2, b2, n2, l2 = ws[j]
                        if (a1, b1) == (a2, b2):
                            if n1 < n2:
                                nested.append(f"{n1} and {n2} cover the same window {l1}")
                        elif a2 <= a1 and b1 <= b2:
                            nested.append(f"{n1} ({l1}) is contained in {n2} ({l2})")
                        elif i < j and a1 < a2 <= b1 < b2:
                            overlap.append(f"{n1} ({l1}) overlaps {n2} ({l2})")
            if nested or overlap:
                md.append("\n### Year windows of the same series (parsed from titles)\n")
                for x in nested[:40]:
                    md.append(f"- NESTED: {x}")
                if len(nested) > 40:
                    md.append(f"- ... {len(nested) - 40} more nested pairs")
                for x in overlap[:40]:
                    md.append(f"- OVERLAP: {x}")
                if len(overlap) > 40:
                    md.append(f"- ... {len(overlap) - 40} more overlapping pairs")

        (out_dir / f"{cur_batch}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        (out_dir / f"{cur_batch}.json").write_text(json.dumps(js, indent=1), encoding="utf-8")
        print(f"{cur_batch}: {len(colls)} collections, "
              f"{sum(len(members[c]) for c in colls)} rows, {len(chr(10).join(md)) // 1024} KB")

    with open(out_dir / "batches.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Collection", "batch", "ministry", "n_rows"])
        for c, b in sorted(batch_of.items(), key=lambda x: (x[1], x[0].lower())):
            w.writerow([c, b, ministries[c], len(members[c])])

    if args.index:
        with open(out_dir / "table_index.tsv", "w", encoding="utf-8") as fh:
            fh.write("nid\tministry\tmerge_method\tCollection\tstatus\tTitle\n")
            for r in rows:
                s = ("LOCKED" if (args.state != "orig" and r[LOCKED]) else
                     f"batch {batch_of[r[COLL]]}" if r[COLL] in batch_of else "free")
                fh.write("\t".join(str(x or "").replace("\t", " ") for x in
                                   (r[NID], r[MIN], r[MM], r[COLL], s, r[TITLE])) + "\n")
    con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--out", required=True, help="directory for the packs")
    ap.add_argument("--state", choices=["now", "orig"], default="now")
    ap.add_argument("--collections", default=None,
                    help="file with one collection name per line (default: the review scope)")
    ap.add_argument("--batch-name", default=None, help="put everything in one batch of this name")
    ap.add_argument("--only-batch", default=None, help="comma list of batch ids to write")
    ap.add_argument("--index", action="store_true", help="also write table_index.tsv")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
