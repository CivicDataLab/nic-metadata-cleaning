#!/usr/bin/env python3
"""
Check the Haiku agents' templates (out/*.tsv) against haiku_items.csv and
assemble data/dataset_description_templates.csv from them, the rule templates
and fixes.tsv (hand corrections: id<TAB>template, which win over everything).

A template is accepted when it has its slot exactly once, carries no year,
month name or "merged", keeps the places and the ministry the original names,
stays close to the original wording and adds no new content words. Everything
else is listed in review.csv with the reason, and is left out of the final CSV
until it is fixed.

Usage: python3 check_templates.py [--write]
"""
import csv
import difflib
import glob
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FINAL = os.path.join(os.path.dirname(HERE), "dataset_description_templates.csv")

MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)"
BAD = re.compile(r"\b(?:19|20)\d{2}\b|\b" + MONTH + r"\b|\bmerg\w*|\bas on\b|\d{1,2}:\d{2}")
SOFT = ("soft:",)
# words an edit may add without it counting as new content
FREE = set("""a an the this that these those it its is are was be been being of for in on at by to from with within
under and or as per file files dataset datasets data report reports reporting covers cover covering covered
period periods figures figure provisional provides provide presents present compiles compile gives contains
single one month monthly cumulative financial year may where applicable available source sourced published
which who their there also not no only each all any such used use using supports support based includes include
record records information scope indicator indicators attendance performance facility facilities public health
district districts state states level""".split())


def words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def problems(row, template: str) -> list[str]:
    slot = "{" + row.slot + "}"
    out = []
    if template.count(slot) != 1 or len(re.findall(r"[{}]", template)) != 2:
        out.append("slot")
    if row.slot == "title" and not template.startswith(slot):
        out.append("title not first")
    body = template.replace(slot, " ")
    hit = BAD.search(body)
    if hit and not (hit.group(0) == "May" and re.search(r"(?:^|[.;]\s+)May\b", body)):
        out.append(f"has '{hit.group(0)}'")
    n = len(body.split())
    if not 25 <= n <= 75:
        out.append(f"{n} words")
    old = row.Description
    ratio = difflib.SequenceMatcher(None, words(old), words(body)).ratio()
    if ratio < 0.6:
        out.append(f"similarity {ratio:.2f}")
    added = sorted(set(words(body)) - set(words(old)) - FREE)
    if len(added) > 4:
        out.append("new words: " + " ".join(added[:10]))
    if row.slot == "period":
        # "... for Sub-districts of <District>, <State> (FY ...)" or "... of <State>"
        place = re.search(r"\bof ([^()]+?)(?: \(FY| for |, FY|$)", row.group)
        for name in (place.group(1).split(", ") if place else []):
            if name in old and name not in template:
                out.append(f"lost place {name}")
    if "Ministry" in old and "Ministry" not in template:
        out.append("lost ministry")
    if re.search(r"provisional", old, re.I) and not re.search(r"provisional", template, re.I):
        out.append("soft: lost provisional")
    if "timestamp" in body:
        out.append("soft: timestamp")
    return out


def main():
    items = pd.read_csv(os.path.join(HERE, "haiku_items.csv")).set_index("pid")
    got, dupes, stray = {}, [], []
    for path in sorted(glob.glob(os.path.join(HERE, "out", "*.tsv"))):
        for line in open(path, encoding="utf-8"):
            m = re.match(r"^\s*(P\d{4})\s*\t\s*(.+?)\s*$", line) or re.match(r"^\s*(P\d{4})\s{2,}(.+?)\s*$", line)
            if not m:
                if line.strip():
                    stray.append((os.path.basename(path), line.strip()[:80]))
                continue
            pid, template = m.group(1), m.group(2).strip().strip('"')
            if pid not in items.index:
                stray.append((os.path.basename(path), f"unknown id {pid}"))
            elif pid in got and got[pid] != template:
                dupes.append(pid)
            else:
                got[pid] = template

    fixes_path = os.path.join(HERE, "fixes.tsv")
    fixes = {}
    if os.path.exists(fixes_path):
        for line in open(fixes_path, encoding="utf-8"):
            if "\t" in line:
                pid, template = line.rstrip("\n").split("\t", 1)
                fixes[pid.strip()] = template.strip()

    accepted, review = {}, []
    for pid, row in items.iterrows():
        template = fixes.get(pid, got.get(pid))
        if template is None:
            review.append((pid, row.slot, row.n, "missing", row.Description, ""))
            continue
        why = problems(row, template)
        hard = [w for w in why if not w.startswith(SOFT)]
        if why:
            review.append((pid, row.slot, row.n, "; ".join(why), row.Description, template))
        if hard and pid not in fixes:
            continue
        else:
            if hard:
                print(f"  note: fix for {pid} still trips: {'; '.join(hard)}")
            accepted[pid] = template

    print(f"items {len(items)} | returned {len(got)} | fixes {len(fixes)} | accepted {len(accepted)} | held back {len(items) - len(accepted)} | listed in review.csv {len(review)}")
    print(f"duplicate ids with different text {len(dupes)} | stray lines {len(stray)}")
    for s in stray[:8]:
        print("   stray:", s)
    rv = pd.DataFrame(review, columns=["pid", "slot", "n", "why", "Description", "template"])
    rv.to_csv(os.path.join(HERE, "review.csv"), index=False)
    if len(rv):
        kinds = rv.why.str.split("; ").explode().str.replace(r"(new words|similarity|has|lost place|\d+ words).*", r"\1", regex=True)
        print("review reasons:", kinds.value_counts().to_dict())

    if "--write" in sys.argv:
        rule = pd.read_csv(os.path.join(HERE, "rule_templates.csv"))
        rows = [(r.group, r.Description, r.slot, "rule", r.template) for r in rule.itertuples()]
        # the slot is read off the template: four fixes moved a {period} pair to {title}
        # because its members also differ by indicator, or mix monthly and cumulative files
        rows += [(items.loc[p].group, items.loc[p].Description, "title" if "{title}" in t else "period",
                  "fix" if p in fixes else "haiku", t) for p, t in accepted.items()]
        final = pd.DataFrame(rows, columns=["group", "Description", "slot", "method", "template"])
        # groups made up for no-collection rows carry no Collection in the table
        final.insert(0, "Collection", final.pop("group").where(lambda g: ~g.str.startswith("(no collection) "), ""))
        # single datasets outside any collection that still carried a collection-style text
        extra = os.path.join(HERE, "extra_templates.csv")
        if os.path.exists(extra):
            final = pd.concat([final, pd.read_csv(extra, dtype=str, keep_default_na=False)], ignore_index=True)
        final.sort_values(["Collection", "Description"]).to_csv(FINAL, index=False, quoting=csv.QUOTE_ALL)
        print(f"wrote {FINAL}: {len(final)} templates", final.method.value_counts().to_dict())


if __name__ == "__main__":
    main()
