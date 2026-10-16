"""Decisions for curate collections with blank merge_add_columns (2026-09-21)."""
import csv, duckdb
c = duckdb.connect('transformation/metadata.db', read_only=True)
def nids(col):
    return [str(r[0]) for r in c.execute("select nid from dublin_core_remaining where merge_method='curate' and Collection=?", [col]).fetchall()]
cols = [r[0] for r in c.sql("""select distinct Collection from dublin_core_remaining
        where merge_method='curate' and coalesce(trim(merge_add_columns),'')=''""").fetchall()]
SKIP = {"Gram Panchayat-wise Rural Sanitation Coverage by District as on date",
        "Gram Panchayat-wise Rural Sanitation Coverage by District"}
SINGLE = {"Households by Source of Lighting, 2011", "Scheduled Caste Households by Source of Lighting, 2011",
          "Scheduled Tribe Households by Source of Lighting, 2011",
          "Households by Availability of Separate Kitchen and Type of Fuel Used for Cooking, 2011"}
IPC = "All India level Incidence of Cognizable Crime under the Indian Penal Code (IPC) and Population"
LSL66 = "All India level Incidence of Offences under Local & Special Laws and Volume of Such Offences Per One Lakh of Population, 1966 to 1975"
LSL76 = "All India level Incidence of Offences under Local & Special Laws and Volume of Such Offences Per One Lakh of Population, 1976 to 1986"
ACC = "All India level Incidence and Rate of Accidental Deaths"
JUV = "All India level Juveniles Apprehended under IPC & LSL Crimes by Sex"
PROP = "All-India level Value of Property Stolen & Recovered and Percentage Recovery"
TCC = "All India Level Incidence of Total Cognizable Crime"
DROP = "Drop the percentage-change summary rows and repeated years."
NCRB = {  # collection -> (new name, remark, rationale)
    IPC: (IPC + " from 1965 to 1983",
          DROP + " 1974 total reads 192277 in nid 1086781 (typo for 1192277); 1976 population 613.3 vs 613.6 across editions.",
          "User example: All India, Year is a column. 7 files, each 11 continuous year rows; shared years repeat except the 1974 typo and a 1976 revision."),
    ACC: ("All India level Incidence and Rate of Accidental Deaths from 1986 to 2000",
          DROP + " Also drop the Compound Growth Rate rows.",
          "All India, Year is a column. 5 files, each 11 continuous year rows; shared years identical."),
    JUV: ("All India level Juveniles Apprehended under IPC & LSL Crimes by Sex from 1978 to 1995",
          "Drop repeated years. 1986 Percentage of Girls is 4 in nid 721121 and 6 in the others; Title spellings (LSL/SLL/L & SL) differ only.",
          "All India, Year is a column. 8 files, each 11 continuous year rows; shared years repeat except one 1986 percentage."),
    PROP: ("All-India level Value of Property Stolen & Recovered and Percentage Recovery from 1978 to 1995",
           DROP + " 1985 Percentage Recovery is 29.5 in nid 1024221 and 29.6 in the others.",
           "All India, Year is a column. 8 files, each 11 continuous year rows; shared years repeat except a 1985 rounding."),
    LSL76: ("All India level Incidence of Offences under Local & Special Laws and Volume of Such Offences Per Lakh of Population from 1976 to 1986",
            "Drop repeated years. 1983 rate reads 4055 in nid 769461 (typo for 405.5).",
            "All India, Year is a column. 5 files (5-7 continuous year rows each); shared years repeat except the 1983 typo."),
}
out = []
def row(ns, mm, coll, remark, conf, why):
    out.append(dict(source_collection="", members="nid:" + ";".join(ns), merge_method=mm, Collection=coll or "",
                    merge_add_columns="", Remark=remark or "", confidence=conf, rationale=why))
for col in cols:
    ns = nids(col)
    if col in SKIP:
        continue
    if col in SINGLE:
        row(ns, "non-mergeable", "", "", "high", "1-member collection; SC/ST/all-households tables are different subjects.")
    elif col in NCRB:
        name, rem, why = NCRB[col]
        row(ns, "change_in_header", name, rem, "medium", why)
    elif col == LSL66:
        row(ns, "non-mergeable", "", "", "medium",
            "Overlapping 7-year windows 1966-1981; the per-lakh rates for 1971-74 and 1977 were revised between editions (67 disagreeing shared-year pairs), so the editions do not repeat.")
    elif col == TCC:
        row(["2873101", "2872681", "2872101", "2870961", "2868761", "2867761"], "to be removed", "", "", "high",
            "Nested editions from 1948: contained in the 1948 to 1959 edition (nid 2864741), figures identical.")
        row(["2864741"], "non-mergeable", "", "", "medium",
            "Latest 1948-1959 edition; its 1956-59 figures differ from the 'Reported Crime' 1956-61 files (e.g. 1957 581371 vs 603550).")
        row(["2723101", "2722241"], "change_in_header",
            "All India Level Incidence of Total Cognizable Reported Crime from 1956 to 1961",
            "Drop repeated years.", "medium",
            "1956-60 and 1957-61 files: continuous, shared years identical; Year is a column.")
    else:
        # headers already carry the varying dimension (State/District code or Year): plain stacking
        row(ns, "direct", {"Vehicle Registration Details : Surat": "Vehicle Registration Details : Surat from 2009 to 2018"}.get(col, col), "", "high",
            "Curate with no column to add: every member has one identical header that already carries the varying key (State/District code, Area Name or Year).")
with open('data/collection_work/out/CURATE_BLANK.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader(); w.writerows(out)
print(len(out), 'decision rows')
