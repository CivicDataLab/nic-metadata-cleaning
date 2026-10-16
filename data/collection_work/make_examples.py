"""Worked examples from the user's own edits (orig -> final) for the agent brief."""
import sys, re, duckdb
from collections import defaultdict
sys.path.insert(0, "/media/aak/246AF1266AF0F580/nic-metadata-cleaning/transformation")
sys.path.insert(0, "/media/aak/246AF1266AF0F580/nic-metadata-cleaning/transformation/utils")
from header_reconcile import reconcile_cols
con = duckdb.connect("/media/aak/246AF1266AF0F580/nic-metadata-cleaning/transformation/metadata.db", read_only=True)
rows = con.execute("""select w.nid, w.Title, w.ministry, w.orig_merge_method, w.orig_Collection, w.orig_merge_add_columns,
   w.merge_method, w."Collection", w.merge_add_columns, w.Remark, d."Conforms To"
   from collection_worktable w join dublin_core_remaining d on cast(d.nid as varchar)=w.nid
   where w.locked or w.batch='CLEANUP'""").fetchall()
NOTES = {
 "aviation": "Superseded editions: for each airline + service type the older edition (…2007-08 to 2015-16) is contained in the newer 'Year-wise …2007-08 to 2016-17' edition, so the older one is `to be removed`. The latest editions of every airline and service type (Domestic / International / Combined) form ONE collection named for 'Various Airlines' with the full span; airline and service type exist only in the titles, so mac = airline,service_scope.",
 "fleet": "Same: an airline's older edition (…2007-08 to 2015-16) is `to be removed` because '…2007-08 to 2016-17' contains it. Airlines with a single edition (Air Costa 2013-14 to 2015-16, Air Pegasus during 2015-16, Zoom Air during 2016-17) are kept. YEAR is a header column, so mac = airline only.",
 "growth": "Older 2015-16 editions `to be removed`, 2016-17 editions kept, mac airline. NOTE: the user put Passenger and Cargo files in one collection named 'Cargo'; that is under review - by rule 5 (different measure: passengers in thousands vs cargo in tonnes) they belong in two collections. Do NOT copy that part.",
 "personnel": "Single-year editions (during 2015-16, during 2016-17) of each airline do not overlap, so all are merged; no year column in the headers, so mac = airline,year. Name carries the span.",
 "cpi": "Monthly 'upto <Month> <Year>' editions. Split ONLY by the index base (2010=100 item groups 'Cereal and Products, Pulses…' vs 2012=100 'Cereals and products, Meat and fish…'); all editions of one base, including rows that were `direct` or `non-mergeable` with no collection, are pulled into one change_in_header collection named with the edition span. Sector/Year/Month are header columns, so mac is blank. (The user's name says 'to February 2024' though members run to November 2025 - get the span right.)",
 "jal_years": "Headers carry the years ('Upto 1986-87, During 1987-88, …' in the 2nd census vs 'Upto 1993-94, During 1994-95, …' in the 3rd) -> years in (almost) every column -> `non-mergeable`.",
 "jal_cca": "Judgment call by the user, not explained: set `non-mergeable` although the columns match. Do not copy it to look-alikes; decide them by rules 1-6 and mark them LOW.",
 "mi5": "Judgment call by the user, not explained: 5th MI Census village-level tables split by in use / temporarily / permanently not in use / all and by surface flow / lift were set `non-mergeable`. Do not copy it to look-alikes; decide them by rules 1-6 and mark them LOW.",
 "suicides": "Overlapping windows (1967-73, 1967-74, 1973-80, 1974-84 …) merged into one collection with the full span: each file is a continuous one-row-per-year table and the overlapping years carry the same figures (user's Remark: 'Since all the figures are repeating in the datasets these can be merged'). The later files end with a 'Percentage change in <Y> over <X>' row - that did NOT stop the user; it is dropped at merge. Year is a header column, so mac blank. One file had 'per 10000' where the others say 'per 100000' - Remark: 'The dataset has 10,000 instead of 100,000. The header can be changed'.",
 "accdeath": "Same as Suicides: overlapping windows of a continuous one-row-per-year table, figures repeat (one small revision of 1967 between editions did not matter), later files end with a percentage-change row -> merged, span in name, mac blank.",
 "causes": "Single years (during 1967 … during 1972). Two columns carry the year ('Percentage to Total Accidental Deaths 1967', '… 1966') -> merge anyway with Remark 'Year in the header can be changed to previous year or last year'; year only in titles -> mac = year; name with span.",
 "crime_wide": "Years in EVERY column ('Incidence 1960, Volume 1960, Incidence 1964, …') and the windows overlap -> `non-mergeable`.",
 "juv_age": "Overlapping sliding windows (1965-75, 1966-76, …) that are NOT continuous series: each file lists selected years only (the '1965 to 1975' file has 1965, 1968, 1969 … - 1966/1967 missing), a shared year differs between editions, and the age bands are regrouped (16-21 vs 16-18 + 18-21) -> `non-mergeable`.",
 "unexplained_ncrb": "Judgment call by the user, not explained (single years, no overlap, same columns): `non-mergeable`. Do NOT copy it to look-alikes - the user MERGED the near-identical 'Local & Special Laws … 1978-82' set (see the 'disposal' example). Decide look-alikes by rules 1-6 and mark them LOW.",
 "inmates": "Single years 'at the end of 2007 … 2015' with identical-ish columns: the edition tail 'at the end' is dropped from the name, curate/non-mergeable rows of the same series are pulled in, Female and all-inmates series stay SEPARATE collections (rule 5), mac = year (year only in titles).",
 "disposal": "Single years 1978-82 merged (mac should be `year`, the year is only in the titles).",
}
def topic(orig, final, title):
    s = (orig or "") + " " + (final or "") + " " + title
    if "Annual Traffic" in s: return "aviation"
    if "Fleet Strength" in s: return "fleet"
    if "Percentage Growth" in s: return "growth"
    if "Personnel Statistics" in s or "Type of Aircraft" in s: return "personnel"
    if "Consumer Price" in s: return "cpi"
    if "Construction of" in s: return "jal_years"
    if "Culturable Command Area" in s: return "jal_cca"
    if "5th Minor Irrigation" in s: return "mi5"
    if "Suicides" in s: return "suicides"
    if "Volume of Accidental Deaths" in s or "Incidence of Accidental Deaths from" in s: return "accdeath"
    if "Various Causes" in s: return "causes"
    if "Incidence of Crime" in s: return "crime_wide"
    if "Juvenile" in s and "Sex" not in s: return "juv_age"
    if "Percentage Share" in s or ("Juvenile" in s and "Sex" in s) or "Local and Special" in s: return "unexplained_ncrb"
    if "Inmates" in s: return "inmates"
    if "Disposal" in s: return "disposal"
    return "other"
SETS = {"A": {"aviation","fleet","growth","personnel","cpi","jal_years","jal_cca","mi5"},
        "B": {"suicides","accdeath","causes","crime_wide","juv_age","unexplained_ncrb","inmates","disposal"}}
by = defaultdict(list)
for r in rows:
    by[topic(r[4], r[7], r[1])].append(r)
def fmt(tp):
    rs = sorted(by[tp], key=lambda r: (r[7] or "~", r[6] or "", r[1]))
    out = [f"\n### Example: {tp}\n", f"Why: {NOTES[tp]}\n"]
    hdrs = {}
    for r in rs:
        k = frozenset(reconcile_cols(r[10])) if r[10] else None
        hdrs.setdefault(k, (len(hdrs)+1, r[10]))
    for k, (i, h) in hdrs.items():
        out.append(f"- header H{i}: {(h or 'NONE')[:230]}")
    out.append("")
    out.append("nid | before: merge_method / Collection / mac | title | AFTER: merge_method / Collection / mac / Remark")
    seen = defaultdict(int)
    for r in rs:
        k = frozenset(reconcile_cols(r[10])) if r[10] else None
        pat = (r[3], r[4], r[6], r[7], r[8], hdrs[k][0])
        seen[pat] += 1
        if seen[pat] == 7:
            n_more = sum(1 for x in rs if (x[3], x[4], x[6], x[7], x[8], hdrs[frozenset(reconcile_cols(x[10])) if x[10] else None][0]) == pat) - 6
            out.append(f"... (+{n_more} more rows: same before/after as the rows above)")
        if seen[pat] > 6:
            continue
        out.append(f"{r[0]} | {r[3]} / {r[4] or '-'} / {r[5] or '-'} | {r[1]} [H{hdrs[k][0]}] | "
                   f"**{r[6]} / {r[7] or '-'} / {r[8] or '-'}**" + (f" / Remark: {r[9]}" if r[9] else ""))
    return "\n".join(out)
for name, tps in [("A", SETS["A"]), ("B", SETS["B"]), ("ALL", SETS["A"] | SETS["B"])]:
    txt = "\n".join(fmt(tp) for tp in sorted(tps) if by[tp])
    open(f"/media/aak/246AF1266AF0F580/nic-metadata-cleaning/data/collection_work/examples_{name}.md","w").write(txt+"\n")
    print(name, len(txt)//1024, "KB", {tp: len(by[tp]) for tp in sorted(tps)})
print("unassigned:", [(r[0], r[1][:60]) for r in by["other"]][:10])
