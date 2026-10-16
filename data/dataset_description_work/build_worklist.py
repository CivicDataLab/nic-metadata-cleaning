#!/usr/bin/env python3
"""
Build the per-dataset description worklist for lot 1 (dublin_core_metadata).

Every collection carries one Description shared by all its members. This turns
each (Collection, Description) pair into a template with one slot, filled per
dataset later:

  {period}  item-wise HMIS collections, where members differ only by month and
            financial year. Parsed from the dataset's own Title.
  {title}   every other collection (members differ by state, district,
            indicator and period): the dataset's own title is the slot.

Rule pass: a description whose only period statement is one FY range (or one
FY) behind a plain lead-in gets that statement swapped for {period}, and the
word "merged" dropped. Anything else goes to the Haiku packs in packs/.

Outputs (this folder): periods.parquet, rule_templates.csv, haiku_items.csv,
packs/period_NN.jsonl, packs/title_01.jsonl
"""
import json
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PACK_SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 480

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
MONTH_RE = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
TITLE_PERIOD = re.compile(
    r"\b(for|upto|up to)\s+(" + MONTH_RE + r")\s*[-,]?\s*((?:19|20)\d{2})\s?[-–]\s?(\d{2}|\d{4})\s*$", re.I)


def period_from_title(title: str):
    """('monthly'|'cumulative', text) for an item-wise title, else (None, None)."""
    m = TITLE_PERIOD.search(title or "")
    if not m:
        return None, None
    month = next(i for i, name in enumerate(MONTHS) if name.lower().startswith(m.group(2).lower()[:3]))
    start = int(m.group(3))
    fy = f"FY {start}-{str(start + 1)[2:]}"
    if int(m.group(4)[-2:]) != (start + 1) % 100:
        return None, None
    year = start if month >= 3 else start + 1          # FY runs April to March
    if m.group(1).lower() == "for":
        return "monthly", f"{MONTHS[month]} {year} ({fy})"
    if month == 3:
        return "cumulative", f"April {start} ({fy})"
    return "cumulative", f"April {start} to {MONTHS[month]} {year} ({fy})"


YEAR = r"(?:19|20)\d{2}"
FY = YEAR + r"(?:\s?[-–/]\s?(?:\d{4}|\d{2}))?"
FYWORD = r"(?:(?:the\s+)?(?:financial|fiscal)\s+years?(?:\s+of)?\s+|FYs?\s*)?"
SPAN = (FYWORD + FY + r"(?:\s*(?:to|through|till|until|and|[-–—])\s*" + FYWORD + FY + r")?")
LEAD = r"(?P<lead>covering|covers|cover|spanning|spans|span|for|during|across|over|within|in|from|between)"
PLAIN = re.compile(r"\b" + LEAD + r"\s+(?:the\s+)?(?:period\s+(?:of\s+|from\s+)?)?(?P<span>" + SPAN + r")(?=[\s.,;)]|$)", re.I)
PAREN = re.compile(r",?\s*\((?P<span>" + SPAN + r")\)")
KEEP_LEAD = {"covering": "covering", "covers": "covers", "cover": "cover",
             "spanning": "covering", "spans": "covers", "span": "cover"}
# What a single file's description must not say once the period is swapped.
FLAGS = re.compile(
    r"\b" + YEAR + r"\b|\b" + MONTH_RE + r"\b|merg|consolidat|timestamp|\bstatus\b|\bas on\b|month[- ]?wise|"
    r"year[- ]?wise|across (?:the )?(?:months|(?:financial |fiscal )?years|periods|reporting periods)|"
    r"multiple (?:months|years|periods)|over the years|latest period|up ?to\b|financial years\b|"
    r"(?:specified|stated)\s+(?:financial|fiscal|fy|years?)|\bnoted\b|\bseveral\b|longitudinal|"
    r"time[- ]series|histor|multi-?year|year[- ](?:on|over)[- ]year|consistent view|"
    r"(?:initial|early|earlier|later|latest|recent|selected|certain|some|different|various) (?:periods?|months?|years?)", re.I)


def drop_merged(text: str) -> str:
    text = re.sub(r"\b([Mm])erged\s+", "", text)
    return re.sub(r"\b([Aa])\s+(?=[aeiouAEIOU])", lambda m: m.group(1) + "n ", text)


def rule_template(desc: str):
    """Template with {period}, or None when the edit needs a reader."""
    text = drop_merged(desc)
    spans = [m for m in re.finditer(SPAN, text) if re.search(YEAR, m.group(0))]
    if len(spans) != 1:
        return None
    m = PLAIN.search(text) or PAREN.search(text)
    if not m or m.group("span") != spans[0].group(0).strip() and spans[0].group(0).strip() not in m.group(0):
        return None
    # "provisional figures for 2017-18" names one member's provisional year, not
    # the collection's span: only a reader can tell what to do with it.
    before = " ".join(text[:m.start()].split()[-4:])
    if re.search(r"provisional", before + " " + m.group(0), re.I):
        return None
    if m.re is PAREN:
        out = text[:m.start()] + ", for {period}" + text[m.end():]
    else:
        lead = m.group("lead").lower()
        out = text[:m.start()] + KEEP_LEAD.get(lead, "for") + " {period}" + text[m.end():]
        if m.group("lead")[0].isupper():
            out = out[:m.start()] + out[m.start()].upper() + out[m.start() + 1:]
    out = polish(re.sub(r"\s+([.,;])", r"\1", out))
    if out.count("{period}") != 1 or FLAGS.search(out.replace("{period}", "")):
        return None
    return out


def polish(out: str) -> str:
    """Two swaps that read badly: "coverage covers {period}", "months for {period}"."""
    out = re.sub(r"\b([Cc]overage) cover(s|ing)? \{period\}",
                 lambda m: m.group(1) + {None: " span", "s": " spans", "ing": " spanning"}[m.group(2)] + " {period}", out)
    return re.sub(r"\bfor (?:specific|specified|selected) months for \{period\}", "for {period}", out)


def main():
    df = pd.read_parquet(os.path.join(HERE, "lot1_snapshot.parquet"))
    df["title"] = df["nt"].fillna(df["Title"])
    parsed = df["title"].map(period_from_title)
    df["mode"], df["period"] = [p[0] for p in parsed], [p[1] for p in parsed]

    # no-collection rows that share a description behave like a collection
    solo = df["Collection"].isna()
    shared = solo & df["Description"].duplicated(keep=False)
    df["group"] = df["Collection"]
    df.loc[shared, "group"] = "(no collection) " + df.loc[shared, "Description"].str[:40]
    df[["nid", "title", "group", "Description", "mode", "period"]].to_parquet(os.path.join(HERE, "periods.parquet"))

    members = df[df["group"].notna()]
    pairs = members.groupby(["group", "Description"], sort=True).agg(
        n=("nid", "size"), parsed=("period", "count"), modes=("mode", lambda s: "/".join(sorted(set(s.dropna())))),
        ex_title=("title", "first"), ex_period=("period", "first"), ex_title2=("title", "last"),
        in_collection=("Collection", lambda s: s.notna().all())).reset_index()
    pairs["slot"] = (pairs["parsed"] == pairs["n"]).map({True: "period", False: "title"})
    pairs.insert(0, "pid", [f"P{i:04d}" for i in range(1, len(pairs) + 1)])
    pairs["template"] = [rule_template(d) if s == "period" else None
                         for d, s in zip(pairs["Description"], pairs["slot"])]

    rule = pairs[pairs["template"].notna()]
    haiku = pairs[pairs["template"].isna()]
    rule[["pid", "group", "n", "slot", "Description", "template"]].to_csv(os.path.join(HERE, "rule_templates.csv"), index=False)
    haiku.drop(columns="template").to_csv(os.path.join(HERE, "haiku_items.csv"), index=False)

    print(f"datasets {len(df)} | in a collection {int(df['Collection'].notna().sum())} | "
          f"no collection, own description {int((solo & ~shared).sum())} | no collection, shared description {int(shared.sum())}")
    print(f"(group, description) pairs {len(pairs)}: slot period {int((pairs.slot == 'period').sum())}, slot title {int((pairs.slot == 'title').sum())}")
    print(f"rule templates {len(rule)} covering {int(rule.n.sum())} datasets | for Haiku {len(haiku)} covering {int(haiku.n.sum())} datasets "
          f"(period {int((haiku.slot == 'period').sum())}, title {int((haiku.slot == 'title').sum())})")

    os.makedirs(os.path.join(HERE, "packs"), exist_ok=True)
    for old in os.listdir(os.path.join(HERE, "packs")):
        os.remove(os.path.join(HERE, "packs", old))

    # {title} items: one pack, with up to four member titles so the template can
    # be checked against members that differ by state, indicator and period.
    spread = members.groupby(["group", "Description"])["title"].agg(
        lambda t: list(dict.fromkeys(t.iloc[[int(i * (len(t) - 1) / 3) for i in range(4)]])))
    by_title = haiku[haiku.slot == "title"].sort_values("n", ascending=False)
    with open(os.path.join(HERE, "packs", "title_01.jsonl"), "w", encoding="utf-8") as f:
        for r in by_title.itertuples():
            f.write(json.dumps({"id": r.pid, "collection": r.group if r.in_collection else "", "members": int(r.n),
                                "example_titles": spread[(r.group, r.Description)],
                                "description": r.Description}, ensure_ascii=False) + "\n")
    print(f"  title_01.jsonl: {len(by_title)} items")

    # {period} items: sorted by group so siblings sit together, dealt round-robin
    by_period = haiku[haiku.slot == "period"].sort_values("group").reset_index(drop=True)
    n_packs = max(1, -(-len(by_period) // PACK_SIZE))
    for k in range(n_packs):
        part = by_period.iloc[k::n_packs]
        with open(os.path.join(HERE, "packs", f"period_{k + 1:02d}.jsonl"), "w", encoding="utf-8") as f:
            for r in part.itertuples():
                f.write(json.dumps({"id": r.pid, "mode": r.modes, "description": r.Description}, ensure_ascii=False) + "\n")
        print(f"  period_{k + 1:02d}.jsonl: {len(part)} items")


if __name__ == "__main__":
    main()
