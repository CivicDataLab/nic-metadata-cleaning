"""Repair agent CSVs: unquoted commas in merge_add_columns (9 fields) / missing Remark (7 fields)."""
import csv, sys
HDR = ["source_collection","members","merge_method","Collection","merge_add_columns","Remark","confidence","rationale"]
CONF = {"high","medium","low"}
src, dst = sys.argv[1], sys.argv[2]
rows = list(csv.reader(open(src, newline="", encoding="utf-8")))
out, bad = [], 0
for r in rows[1:]:
    if not any(x.strip() for x in r):
        continue
    if len(r) == 8 and r[6].strip() in CONF:
        out.append(r); continue
    # locate the confidence field; everything between Collection and it is mac + Remark
    ci = next((i for i in range(len(r) - 1, 3, -1) if r[i].strip() in CONF), None)
    if ci is None:
        print("cannot repair:", r[:4]); bad += 1; continue
    mid = r[4:ci]
    rationale = ",".join(r[ci + 1:])
    toks = [m for m in mid if m.strip() and all(t.strip().replace("_", "").isalpha() and t.strip().islower() for t in m.split(","))]
    remark = [m for m in mid if m not in toks]
    out.append(r[:4] + [",".join(t.strip() for t in toks), " ".join(x for x in remark if x.strip()), r[ci], rationale])
w = csv.writer(open(dst, "w", newline="", encoding="utf-8")); w.writerow(HDR); w.writerows(out)
print(f"{len(out)} rows written, {bad} unrepairable")
