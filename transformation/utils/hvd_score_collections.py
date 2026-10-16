"""
HVD (High Value Dataset) scoring model — collection-aware variant.

This is a copy of hvd_score.py reworked to score at the *collection* grain.

Rationale
---------
We have identified datasets that can be merged, and that merge family lives in
the `Collection` field. High value is a property of the merged family, not of a
lone member row: a single district's HMIS extract is unremarkable, but the
collection that stitches 600+ districts across every State/UT into one
comparable series is exactly the kind of asset an HVD list should surface. So
when a row carries a Collection, its HVD standing is decided by evaluating the
*whole* collection against the three signals, and every member row inherits that
collection-level score.

Key differences from hvd_score.py:

  * Loads the FULL table, not one batch. Collections span batches (the same
    family appears in batch 29, 30, ...), so a batch-filtered geo count would
    undercount the States/UTs a collection actually covers. `--batch` now only
    restricts which rows are *written out*; aggregation always sees the whole
    collection.

  * The three signals are aggregated to collection grain BEFORE normalising, and
    normalisation / the candidate percentile cut are taken over one score per
    collection (not per row). Otherwise a 15,701-member collection would
    single-handedly dominate the distribution.

  * Rows with no Collection are treated as singleton collections (a family of
    one). This keeps a single grain, a single normalisation universe, and a
    single candidate cut — and a singleton scores just as it would row-by-row.

Signal aggregation choices (see hvd_score.py for the per-signal reasoning that
still applies):

  demand    Mean per-member monthly rate across the collection. Intensity, not
            total footprint: summing counts would just reward big collections
            for being big — the same size bias the per-month rate was built to
            avoid.
  temporal  Span of the collection's *union* of years: earliest parseable start
            to latest parseable end across members. The implausible pre-1950
            start mask is applied to member rows BEFORE the min/max, so one
            stray start:1810 can't poison the whole family's span.
  geo       Distinct real States/UTs the (mergeable) members cover, over 36.
            Broad-coverage reading (kept deliberately): 2-3 state collections
            score near the floor; only families covering many States/UTs rank.
            A member tagged bare 'India' makes the collection national -> 1.0.

Reads a read-only DuckDB snapshot and writes a CSV keyed by nid. It does NOT
write to the database and does NOT touch `High Value Dataset Category`.

Usage:
    python transformation/utils/hvd_score_collections.py --db <path> --out hvd_scores_collections.csv
    python transformation/utils/hvd_score_collections.py --db <path> --batch 1   # write only batch 1 rows
"""

import argparse
from datetime import date

import duckdb
import numpy as np
import pandas as pd

# 28 states + 8 union territories.
N_STATES_UT = 36

WEIGHTS = {"demand": 0.40, "temporal": 0.35, "geo": 0.25}

# merge_method values that carry no geographic family, so no geo signal.
NO_GEO_MERGE_METHODS = {"non-mergeable", "to be removed"}

SIGNAL_COLS = [
    "Title", "nid", "Collection", "merge_method", "Subject[sector]",
    "Publisher[ministry_department]", "ogdp_download_count", "ogdp_view_count",
    "Date Issued", "Temporal Coverage", "Spatial Coverage", "batch",
]


def load(db_path):
    """Load the full table. Collections span batches, so aggregation must too."""
    con = duckdb.connect(db_path, read_only=True)
    cols = ", ".join(f'"{c}"' for c in SIGNAL_COLS)
    df = con.execute(f"SELECT {cols} FROM dublin_core_metadata").fetchdf()
    con.close()
    return df


def minmax(s, clip_pct=None):
    """Min-max normalise to [0,1], preserving NaN as missing.

    `clip_pct` winsorises the upper tail before scaling so a handful of extreme
    collections don't flatten everyone else to zero.
    """
    x = s
    if clip_pct is not None and s.notna().any():
        x = s.clip(upper=np.nanpercentile(s.dropna(), clip_pct))
    lo, hi = x.min(), x.max()
    if pd.isna(lo) or hi == lo:
        # Degenerate spread: everything present scores equally.
        return x.notna().astype(float).replace(0.0, np.nan)
    return (x - lo) / (hi - lo)


def parse_state(spatial):
    """State/UT is the token immediately before the trailing 'India'.

    'Bihar, Nalanda, Bihar, India' -> 'Bihar'; bare 'India' -> None (national,
    not attributable to one state).
    """
    if not isinstance(spatial, str):
        return None
    parts = [p.strip() for p in spatial.split(",") if p.strip()]
    if len(parts) < 2 or parts[-1].lower() != "india":
        return None
    return parts[-2]


def collection_key(df):
    """Group key at collection grain.

    Rows with a real Collection group by it; Collection-less rows become
    singleton families keyed by their own nid so they flow through the exact
    same aggregation/normalisation/cut as everything else.
    """
    coll = df["Collection"].fillna("").str.strip()
    has_coll = coll != ""
    key = coll.where(has_coll, "__singleton__" + df["nid"].astype(str))
    return key, has_coll


def per_row_prep(df, as_of, min_start):
    """Row-level signal ingredients, computed before any aggregation.

    Returns a frame indexed like `df` carrying the masked, per-row quantities
    the collection aggregation consumes.
    """
    # ---- demand: per-member monthly rate (intensity) ----
    issued = pd.to_datetime(df["Date Issued"], errors="coerce")
    months = (pd.Timestamp(as_of) - issued).dt.days / 30.44
    months = months.where(months >= 1.0, 1.0)  # floor at 1 month

    facets = []
    for col in ("ogdp_download_count", "ogdp_view_count"):
        raw = pd.to_numeric(df[col], errors="coerce")
        facets.append(raw / months)
    # Per-row demand rate = mean of the download and view rates (skip missing).
    row_rate = pd.concat(facets, axis=1).mean(axis=1, skipna=True)

    # ---- temporal: parsed start/end with the implausible-start mask ----
    tc = df["Temporal Coverage"].fillna("").str.strip()
    start = tc.str.extract(r"start:(\d{4})", expand=False).astype(float)
    end = tc.str.extract(r"end:(\d{4})", expand=False).astype(float)
    # Pre-min_start starts are data-entry artifacts (e.g. start:1810 in an HMIS
    # series), treated as MISSING so they neither score nor poison a span.
    implausible = (start < min_start).fillna(False)
    start = start.mask(implausible)

    # ---- geo: state + national flag, only for mergeable members ----
    mm = df["merge_method"].fillna("").str.strip().str.lower()
    mergeable = ~mm.isin(NO_GEO_MERGE_METHODS)
    state = df["Spatial Coverage"].map(parse_state)
    is_national = (
        df["Spatial Coverage"].fillna("").str.strip().str.lower() == "india"
    )

    return pd.DataFrame({
        "months": months,
        "row_rate": row_rate,
        "start": start,
        "end": end,
        "state": state.where(mergeable),
        "is_national": is_national & mergeable,
        "mergeable": mergeable,
    })


def aggregate_collections(key, has_coll, prep):
    """Collapse per-row ingredients to one row per collection."""
    g = prep.assign(key=key.values)

    demand_raw = g.groupby("key")["row_rate"].mean()          # intensity
    min_start = g.groupby("key")["start"].min()
    max_end = g.groupby("key")["end"].max()
    depth = (max_end - min_start + 1).where(min_start.notna() & max_end.notna())
    depth = depth.where(depth >= 1)                            # guard garbage

    distinct_states = g.dropna(subset=["state"]).groupby("key")["state"].nunique()
    has_national = g.groupby("key")["is_national"].any()
    member_count = g.groupby("key").size()

    agg = pd.DataFrame({
        "demand_raw": demand_raw,
        "depth": depth,
        "distinct_states": distinct_states.reindex(demand_raw.index).fillna(0).astype(int),
        "has_national": has_national.reindex(demand_raw.index).fillna(False),
        "member_count": member_count.reindex(demand_raw.index).fillna(0).astype(int),
    })
    # A family is a singleton (row-level fallback) when it has no real
    # Collection — i.e. its key is not among the present Collection values.
    real_colls = set(key.where(has_coll).dropna().unique())
    agg["is_singleton"] = ~agg.index.isin(real_colls)
    return agg


def score_collections(agg, clip_pct):
    """Normalise the three signals across collections and combine."""
    demand = minmax(np.log1p(agg["demand_raw"]), clip_pct)
    temporal = minmax(np.log1p(agg["depth"]), clip_pct)

    geo = (agg["distinct_states"] / N_STATES_UT).clip(upper=1.0)
    geo = geo.where(agg["distinct_states"] > 0)            # no states -> missing
    geo = geo.mask(agg["has_national"], 1.0)               # national -> full
    # Singleton families (Collection-less rows) have no geographic cohort, so
    # geo is absent and its weight redistributes — exactly the row-level rule.
    geo = geo.mask(agg["is_singleton"])

    sig = pd.DataFrame({"demand": demand, "temporal": temporal, "geo": geo})

    # Weighted sum with proportional redistribution of missing signals' weight.
    w = pd.DataFrame(
        {k: np.where(sig[k].notna(), WEIGHTS[k], 0.0) for k in WEIGHTS},
        index=sig.index,
    )
    total = w.sum(axis=1)
    contrib = sum(w[k] * sig[k].fillna(0.0) for k in WEIGHTS)
    score = (contrib / total).where(total > 0)

    signals_present = sig.notna().apply(
        lambda r: "+".join(c for c in sig.columns if r[c]) or "none", axis=1
    )
    return sig, score, sig.notna().sum(axis=1), signals_present


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--batch", default=None,
                   help="Restrict WRITTEN rows to this batch. Aggregation always "
                        "uses the full table so cross-batch collections stay whole. "
                        "Omit to write every row.")
    p.add_argument("--out", default="transformation/hvd_scores_collections.csv")
    p.add_argument("--as-of", default=str(date.today()))
    p.add_argument("--top-pct", type=float, default=10.0,
                   help="Percentile cut for the candidate flag, taken over the "
                        "families that pass --min-signals")
    p.add_argument("--min-signals", type=int, default=2,
                   help="Minimum number of PRESENT signals a family needs to be "
                        "eligible for the candidate flag. A family scoring on one "
                        "signal alone has that signal's weight redistributed to "
                        "100%%, so a saturated demand rate scores 1.0 on no "
                        "corroborating evidence and outranks genuinely broad "
                        "collections. Set 1 to restore the old behaviour.")
    p.add_argument("--clip-pct", type=float, default=99.0,
                   help="Winsorise signal upper tails at this percentile before min-max")
    p.add_argument("--min-start-year", type=int, default=1950,
                   help="Temporal starts before this are treated as unparseable (missing)")
    args = p.parse_args()

    df = load(args.db)
    print(f"Loaded {len(df)} rows (all batches)")

    key, has_coll = collection_key(df)
    prep = per_row_prep(df, args.as_of, args.min_start_year)
    agg = aggregate_collections(key, has_coll, prep)
    print(f"Aggregated into {len(agg)} families "
          f"({int((~agg['is_singleton']).sum())} real collections, "
          f"{int(agg['is_singleton'].sum())} singletons)")

    sig, score, n_signals, signals_present = score_collections(agg, args.clip_pct)

    # Evidence gate. Weight redistribution means a one-signal family is scored
    # entirely by that signal, so the top of the raw ranking is enriched for thin
    # evidence rather than high value. Gate on signal count FIRST, then take the
    # percentile over the eligible families only — otherwise the cut is set by a
    # distribution the candidates no longer come from.
    eligible = n_signals >= args.min_signals
    n_elig = int(eligible.sum())
    print(f"\nEvidence gate: {n_elig}/{len(agg)} families carry "
          f">= {args.min_signals} signals and are eligible for candidacy")
    if n_elig == 0:
        raise SystemExit(f"No family carries >= {args.min_signals} signals; "
                         f"lower --min-signals")

    # Candidate cut taken over collections, one score each — so a giant
    # collection contributes one vote to the threshold, not thousands.
    cut = np.nanpercentile(score[eligible].dropna(), 100 - args.top_pct)

    coll = pd.DataFrame({
        "hvd_demand": sig["demand"].round(4),
        "hvd_temporal": sig["temporal"].round(4),
        "hvd_geo": sig["geo"].round(4),
        "hvd_score": score.round(4),
        "hvd_candidate": ((score >= cut) & eligible).astype("Int64"),
        "collection_states_covered": agg["distinct_states"],
        "collection_member_count": agg["member_count"],
        "collection_is_national": agg["has_national"],
        "collection_temporal_span_years": agg["depth"],
        "is_singleton": agg["is_singleton"],
        "n_signals": n_signals,
        "signals_present": signals_present,
    })

    # Explode collection-level results back onto every member row.
    joined = df.assign(_key=key.values).merge(
        coll, left_on="_key", right_index=True, how="left"
    )

    out = pd.DataFrame({
        "nid": joined["nid"],
        "batch": joined["batch"],
        "Title": joined["Title"],
        "Collection": joined["Collection"],
        "merge_method": joined["merge_method"],
        "ministry": joined["Publisher[ministry_department]"],
        "downloads": pd.to_numeric(joined["ogdp_download_count"], errors="coerce"),
        "views": pd.to_numeric(joined["ogdp_view_count"], errors="coerce"),
        "date_issued": joined["Date Issued"],
        "state_ut": joined["Spatial Coverage"].map(parse_state),
        "collection_states_covered": joined["collection_states_covered"],
        "collection_member_count": joined["collection_member_count"],
        "collection_is_national": joined["collection_is_national"],
        "collection_temporal_span_years": joined["collection_temporal_span_years"],
        "scored_as": np.where(joined["is_singleton"], "row", "collection"),
        "hvd_demand": joined["hvd_demand"],
        "hvd_temporal": joined["hvd_temporal"],
        "hvd_geo": joined["hvd_geo"],
        "hvd_score": joined["hvd_score"],
        "hvd_candidate": joined["hvd_candidate"],
        "n_signals": joined["n_signals"],
        "signals_present": joined["signals_present"],
    }).sort_values(["hvd_score", "n_signals"], ascending=[False, False])
    
    if args.batch is not None:
        out = out[out["batch"].astype(str) == str(args.batch)]
        print(f"Restricted written rows to batch {args.batch}: {len(out)} rows")

    out.to_csv(args.out, index=False)

    # ---- reporting (at collection grain) ----
    print(f"\nSignal availability across {len(agg)} families "
          f"(missing -> weight redistributed):")
    for k in WEIGHTS:
        n = int(sig[k].notna().sum())
        print(f"  {k:9s} {n:6d}/{len(agg)}  ({100*n/len(agg):5.1f}%)")

    print(f"\nCollection score distribution:")
    print(score.describe().round(4).to_string())

    n_cand_coll = int(((score >= cut) & eligible).sum())
    print(f"\nTop {args.top_pct}% of eligible families, cut = {cut:.4f} -> "
          f"{n_cand_coll} candidate collections "
          f"({int(out['hvd_candidate'].fillna(0).sum())} member rows written)")

    print("\nEvidence depth of candidate collections:")
    cand = coll[coll.hvd_candidate == 1]
    for combo, n in cand["signals_present"].value_counts().items():
        print(f"  {combo:24s} {n:5d}  ({100*n/len(cand):5.1f}% of candidates)")

    # Focus on real merged collections — the point of this variant. Singletons
    # (Collection-less rows) can top the list on a lone saturated demand signal,
    # but they are the row-level fallback, not the collections we're evaluating.
    print("\nTop 15 candidate COLLECTIONS by score (real merge families only):")
    real_cand = cand[~cand.is_singleton].sort_values("hvd_score", ascending=False)
    for k, r in real_cand.head(15).iterrows():
        print(f"  {r['hvd_score']:.3f}  states={int(r['collection_states_covered']):2d} "
              f"members={int(r['collection_member_count']):5d}  {str(k)[:66]}")
    print(f"\n  Candidate breakdown: {len(real_cand)} real collections, "
          f"{int(cand.is_singleton.sum())} singleton rows")

    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
