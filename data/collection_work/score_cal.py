"""Score the calibration batch against the user's own decisions."""
import sys, json, itertools, duckdb
from collections import Counter, defaultdict
sys.path.insert(0, "/media/aak/246AF1266AF0F580/nic-metadata-cleaning/transformation")
sys.path.insert(0, "/media/aak/246AF1266AF0F580/nic-metadata-cleaning/transformation/utils")
from collection_worktable import read_decisions, expand
SP = "/media/aak/246AF1266AF0F580/nic-metadata-cleaning/data/collection_work/cal"
dec = read_decisions(f"{SP}/out/CAL.csv")
pack = json.load(open(f"{SP}/packs/CAL.json"))
owner, errors = expand(dec, pack)
print("expand errors:", errors or "none")
con = duckdb.connect("/media/aak/246AF1266AF0F580/nic-metadata-cleaning/transformation/metadata.db", read_only=True)
truth = {r[0]: r[1:] for r in con.execute(
    'select nid, merge_method, "Collection", merge_add_columns, Title, orig_merge_method, orig_Collection, (locked or batch = \'CLEANUP\') from collection_worktable').fetchall()}
members = {n for c in pack["collections"].values() for n in c["nids"]}
final_colls = {truth[n][1] for n in members if truth[n][1]}
user_pulled = {n for n, t in truth.items() if t[1] in final_colls and n not in members}
agent_pulled = {n for n in owner if n not in members}
rows = members | user_pulled | agent_pulled
not_user = {n for n in rows if not truth[n][6]}
print(f"rows the user never decided (excluded from scoring): {len(not_user)} -> {sorted((truth[n][3][:60], agent_of) for n in not_user for agent_of in [None])[:0]}")
rows = rows - not_user
print(f"pack members {len(members)} | user pulled in {len(user_pulled)} | agent pulled in {len(agent_pulled)} "
      f"| both {len(user_pulled & agent_pulled)}")
def agent(n):
    if n in owner:
        d = dec[owner[n]]
        return d["merge_method"], d["Collection"] or None, d["merge_add_columns"] or None, d["confidence"]
    return truth[n][4], truth[n][5], None, "-"   # untouched -> stays as it was
mm_ok = sum(agent(n)[0] == truth[n][0] for n in rows)
print(f"merge_method agreement: {mm_ok}/{len(rows)} = {mm_ok/len(rows):.0%}")
by_conf = defaultdict(lambda: [0, 0])
for n in rows:
    c = agent(n)[3]; by_conf[c][1] += 1; by_conf[c][0] += agent(n)[0] == truth[n][0]
print("  by agent confidence:", {k: f"{a}/{b}" for k, (a, b) in by_conf.items()})
# co-membership (pairs of rows): same collection or not
agree = tot = 0
for a, b in itertools.combinations(sorted(rows), 2):
    ta = truth[a][1] is not None and truth[a][1] == truth[b][1]
    ag = agent(a)[1] is not None and agent(a)[1] == agent(b)[1]
    if ta or ag:
        tot += 1; agree += ta == ag
print(f"co-membership agreement (pairs grouped by either side): {agree}/{tot} = {agree/max(tot,1):.0%}")
mac_rows = [n for n in rows if truth[n][0] == "change_in_header" and agent(n)[0] == "change_in_header"]
mac_ok = sum((agent(n)[2] or "") == (truth[n][2] or "") for n in mac_rows)
print(f"mac agreement on rows both call change_in_header: {mac_ok}/{len(mac_rows)}")
print("\nper row disagreements:")
for n in sorted(rows, key=lambda n: truth[n][3]):
    a, t = agent(n), truth[n]
    if a[0] != t[0] or (a[0] == "change_in_header" and (a[2] or "") != (t[2] or "")):
        print(f"  {n} {t[3][:80]}\n      user : {t[0]} / {str(t[1])[:70]} / {t[2]}\n      agent: {a[0]} / {str(a[1])[:70]} / {a[2]} ({a[3]})")
print("\nnames: user -> agent")
pairs = Counter((truth[n][1], agent(n)[1]) for n in rows if truth[n][1] or agent(n)[1])
for (u, g), k in pairs.most_common():
    print(f"  [{k}] U: {u}\n       A: {g}")
