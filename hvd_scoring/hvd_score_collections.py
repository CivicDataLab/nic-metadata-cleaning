"""
HVD scoring with the merged dataset as the unit, not the file.

A `Collection` is a set of files that will be merged into one dataset, so this
scores every collection as ONE unit and every file outside a collection as its
own unit. The scoring itself is hvd_score_v2's and is imported, not copied: the
loaders, the weights, `minmax`, the signal definitions and `combine`. The only
new step sits between loading and scoring -- rolling a collection's members up
into one row -- and every min-max, percentile clip and cut then runs over units.

Why it matters: scored per file, a collection's members compete as slices. One
district-month file of an eight-year series reads as one year, one state and a
sliver of the series' traffic, and 205,151 such slices in lot 1 alone set the
bottom of every scale.

How a merged unit's inputs are built from its members:

  demand     the members' downloads per month and views per month, summed --
             each member's count over its own age, so a late addition is not
             diluted by the age of the oldest member. Summed because the merged
             dataset is the one page all of that traffic would land on.
             `--demand-agg mean|max` are there to test how much this matters.
  temporal   earliest member start to latest member end, in years, which is the
             Temporal Coverage the merged record will carry. Members with an
             unusable range are skipped, exactly as `signal_temporal` skips
             them per file. `years_covered` in the output counts the distinct
             years instead, so a gappy series is visible.
  geo        the widest member. A member's value already is its collection's
             share of the 36 States/UTs unless the national or State/UT-wise
             rule fired, so this is that share, or better where a member is
             itself national or State/UT-wise. The collection's own name is
             also put through the State/UT-wise rule.
  api        1.0 when any member is API-fed.
  liveness   from the most recently refreshed member, on `freshness_date`'s
             date, so the external-link rule still applies per member.

A file outside a collection goes through unchanged, so its inputs are exactly
what hvd_score_v2 reads; only the scales it is normalised against differ.

Rows whose merge_method is 'to be removed' are dropped before anything else:
they are duplicates and superseded editions that will not exist after the merge.

Punctuality is not carried up. It has no weight in hvd_score_v2 and is a
per-file audit of a declared cadence, which a merged series does not inherit
from any one member.

`--api-only` is hvd_score_v2's flag of the same name, applied to units: only
units with an API-fed member are scored, so every scale and every cut is taken
over those alone. A unit keeps all of its members, API-fed or not, because the
merged dataset will hold all of them. `--abs-cuts` adds fixed score thresholds
next to the percentile ones, which is what that mode is run with in production.

Usage:
    python hvd_scoring/hvd_score_collections.py
    python hvd_scoring/hvd_score_collections.py --cuts 10 5 1
    python hvd_scoring/hvd_score_collections.py --demand-agg mean
    python hvd_scoring/hvd_score_collections.py --stats      # live counts
    python hvd_scoring/hvd_score_collections.py --api-only --abs-cuts 0.42 \
        --out hvd_scoring/hvd_scores_collections_api_only.csv
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

import hvd_score_v2 as v2

default_out = str(v2.repo_root / "hvd_scoring" / "hvd_scores_collections.csv")

# merge_method values that mean the row will not survive the merge.
drop_methods = {"to be removed"}

demand_aggs = ("sum", "mean", "max")


def load_members(db):
    """Every file of the three lots, normalised by hvd_score_v2's own `load`.

    `merge_method` is not one of the columns the v2 profiles select, so it is
    appended to each profile here rather than read in a second query: lot 3 has
    a null nid and a repeated one, so there is no key to join a second read on.
    """
    parts = []
    for t in v2.all_tables:
        profile = v2.tables[t]
        if "merge_method_raw" not in profile["select"]:
            profile["select"] = (profile["select"].rstrip().rstrip(",")
                                 + ",\n            merge_method AS merge_method_raw,\n")
        part = v2.load(db, t)
        part["source_table"] = t
        parts.append(part)
    df = pd.concat(parts, ignore_index=True)

    method = v2.as_text(df["merge_method_raw"]).str.strip().str.lower()
    dropped = method.isin(drop_methods)
    print(f"Loaded {len(df):,} files; dropping {int(dropped.sum()):,} marked "
          f"{', '.join(sorted(drop_methods))}")
    return df[~dropped].reset_index(drop=True)


def api_fed_units(df):
    """The files of every unit that has an API-fed member, the unit kept whole."""
    key, _ = unit_key(df)
    fed = v2.signal_api(df) > 0
    return df[key.isin(key[fed])].reset_index(drop=True)


def member_inputs(df, as_of, clip_pct, min_start):
    """Per-file inputs, each from the hvd_score_v2 function that owns it.

    The raw inputs, not the normalised signals: a signal normalised over files
    cannot be rolled up, so demand and temporal are taken before their min-max
    and re-normalised over units in `score_units`.
    """
    _, months, count, _ = v2.signal_demand(df, as_of, clip_pct)
    views = pd.to_numeric(df["ogdp_view_count"], errors="coerce")

    # Same parse and the same three guards as `signal_temporal`: both years
    # present, not reversed, start not before `min_start`.
    tc = df["temporal_coverage"].fillna("").str.strip()
    start = tc.str.extract(r"start:(\d{4})", expand=False).astype(float)
    end = tc.str.extract(r"end:(\d{4})", expand=False).astype(float)
    usable = start.notna() & end.notna() & (end >= start) & (start >= min_start)

    geo, state, _ = v2.signal_geo(df)
    fresh, _, _ = v2.freshness_date(df, min_start)

    return pd.DataFrame({
        "downloads": count,
        "views": views,
        "download_rate": count / months,
        "view_rate": views / months,
        "start": start.where(usable),
        "end": end.where(usable),
        "geo": geo,
        "state": state,
        "api": v2.signal_api(df),
        "fresh": fresh,
    }, index=df.index)


def unit_key(df):
    """One key per future dataset: the collection, or the file itself.

    Qualified by table so two lots could never fold into one unit on a shared
    name. No collection name is shared across the three lots today.
    """
    coll = df["Collection"].fillna("").str.strip()
    in_coll = coll != ""
    key = (df["source_table"] + "|" + coll).where(
        in_coll, "file|" + df.index.astype(str))
    return key, in_coll


def years_covered(key, start, end):
    """Distinct years each unit's members cover, counting a gap as a gap."""
    ok = start.notna() & end.notna()
    s, e = start[ok].astype(int), end[ok].astype(int)
    reps = (e - s + 1).to_numpy()
    years = np.repeat(s.to_numpy(), reps) + (
        np.arange(reps.sum()) - np.repeat(np.cumsum(reps) - reps, reps))
    pairs = pd.DataFrame({"key": np.repeat(key[ok].to_numpy(), reps), "year": years})
    return pairs.drop_duplicates().groupby("key").size()


def roll_up(df, m, demand_agg="sum"):
    """Collapse the member inputs to one row per unit."""
    key, in_coll = unit_key(df)
    g = m.groupby(key, sort=False)

    def rate(col):
        # min_count=1: a unit whose members all lack a count has no demand
        # signal, rather than a demand of zero.
        if demand_agg == "sum":
            return g[col].sum(min_count=1)
        return g[col].agg(demand_agg)

    # A collection sits under one publisher in all three lots; first() is that
    # publisher, and is the file's own for a file outside a collection.
    first = df.groupby(key, sort=False).first()
    units = pd.DataFrame({
        "unit_type": np.where(in_coll.groupby(key, sort=False).first(),
                              "collection", "file"),
        "source_table": first["source_table"],
        "nid": first["nid"],
        "Title": first["Title"],
        "Collection": first["Collection"].str.strip(),
        "ministry": first["Publisher[ministry_department]"],
        "state_department": first["Publisher[state_department]"],
        "n_members": g.size(),
        "downloads": g["downloads"].sum(min_count=1),
        "views": g["views"].sum(min_count=1),
        "download_rate": rate("download_rate"),
        "view_rate": rate("view_rate"),
        "span_start": g["start"].min(),
        "span_end": g["end"].max(),
        "states_covered": g["state"].nunique(),
        "geo_members": g["geo"].max(),
        "api_members": g["api"].sum(),
        "date_freshness": g["fresh"].max(),
    })
    is_coll = units["unit_type"] == "collection"
    # A merged dataset is named after its collection, and has no nid of its own.
    units["Title"] = units["Title"].where(~is_coll, units["Collection"])
    units["nid"] = units["nid"].where(~is_coll)
    units["years_covered"] = years_covered(key, m["start"], m["end"]).reindex(units.index)
    return units


def score_units(units, as_of, clip_pct, half_life, min_start):
    """The five signals over units, through hvd_score_v2's own functions."""
    demand = pd.concat(
        [v2.minmax(np.log1p(units[c]), clip_pct)
         for c in ("download_rate", "view_rate")], axis=1,
    ).mean(axis=1, skipna=True)

    # Hand `signal_temporal` the envelope in the form it parses, so the clip,
    # the log and the min-max are its own and not a second copy of them.
    has_span = units["span_start"].notna() & units["span_end"].notna()
    envelope = pd.Series("None", index=units.index)
    envelope[has_span] = (
        "start:" + units.loc[has_span, "span_start"].astype(int).astype(str)
        + ";end:" + units.loc[has_span, "span_end"].astype(int).astype(str))
    temporal, depth, _ = v2.signal_temporal(
        pd.DataFrame({"temporal_coverage": envelope}), clip_pct, min_start)

    state_wise = units["Title"].fillna("").str.contains(v2.state_wise_re)
    geo = units["geo_members"].mask(state_wise, 1.0)

    api = (units["api_members"] > 0).astype(float)
    liveness, days = v2.signal_liveness(units["date_freshness"], as_of, half_life)

    sig = pd.DataFrame({"demand": demand, "temporal": temporal, "geo": geo,
                        "api": api, "liveness": liveness})
    return sig, v2.combine(sig), depth, days


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--db", default=v2.default_db)
    p.add_argument("--out", default=default_out)
    p.add_argument("--as-of", default=str(date.today()))
    p.add_argument("--cuts", type=float, nargs="+", default=[10.0, 5.0, 1.0],
                   help="Top-N%% cuts over units, each written as an "
                        "hvd_candidate_pXX column (percentile = 100-N)")
    p.add_argument("--abs-cuts", type=float, nargs="*", default=[],
                   help="Fixed score thresholds, each written as an "
                        "hvd_candidate_ge<score> column")
    p.add_argument("--api-only", action="store_true",
                   help="Score only units with an API-fed member, as "
                        "hvd_score_v2 --api-only does per file. Scales and "
                        "percentile cuts are then taken over those units alone")
    p.add_argument("--demand-agg", choices=demand_aggs, default="sum",
                   help="How a collection's member traffic rates combine")
    p.add_argument("--clip-pct", type=float, default=99.0)
    p.add_argument("--half-life", type=float, default=v2.half_life_days)
    p.add_argument("--min-start-year", type=int, default=1950)
    p.add_argument("--stats", action="store_true",
                   help="Take view/download counts from the portal's analytics "
                        "endpoint, as hvd_score_v2 --stats does")
    p.add_argument("--cache-dir", default=v2.default_cache_dir)
    args = p.parse_args()

    df = load_members(args.db)
    if args.api_only:
        df = api_fed_units(df)
        if df.empty:
            raise SystemExit("Nothing to score.")
    # After --api-only, so a filtered run only fetches counts for what it scores.
    if args.stats:
        df = v2.overlay_portal_stats(df, cache_dir=args.cache_dir)
    m = member_inputs(df, args.as_of, args.clip_pct, args.min_start_year)
    units = roll_up(df, m, args.demand_agg)
    sig, score, depth, days = score_units(
        units, args.as_of, args.clip_pct, args.half_life, args.min_start_year)

    n_coll = int((units["unit_type"] == "collection").sum())
    print(("API-fed units only: " if args.api_only else "")
          + f"{len(df):,} files -> {len(units):,} units "
          f"({n_coll:,} collections holding "
          f"{int(units.loc[units['unit_type'] == 'collection', 'n_members'].sum()):,} "
          f"files, {len(units) - n_coll:,} files on their own)")

    out = units.drop(columns=["geo_members"]).assign(
        temporal_span_years=depth,
        days_since_freshness=days,
        hvd_demand=sig["demand"].round(4),
        hvd_temporal=sig["temporal"].round(4),
        hvd_geo=sig["geo"].round(4),
        hvd_api=sig["api"],
        hvd_liveness=sig["liveness"].round(4),
        hvd_score=score.round(4),
        n_signals=sig.notna().sum(axis=1),
    )
    print()
    for c in args.cuts:
        th = np.nanpercentile(score, 100 - c)
        col = f"hvd_candidate_p{100 - c:g}"
        out[col] = (score >= th).astype(int)
        cand = out[out[col] == 1]
        print(f"top {c:g}% cut ({100 - c:g}th percentile) = {th:.4f} -> "
              f"{len(cand):,} units ({int((cand['unit_type'] == 'collection').sum()):,} "
              f"collections), holding {int(cand['n_members'].sum()):,} files")
    for th in args.abs_cuts:
        col = f"hvd_candidate_ge{th:g}"
        out[col] = (score >= th).astype(int)
        cand = out[out[col] == 1]
        print(f"score >= {th:g} -> "
              f"{len(cand):,} units ({int((cand['unit_type'] == 'collection').sum()):,} "
              f"collections), holding {int(cand['n_members'].sum()):,} files")
    out = out.sort_values(["hvd_score", "n_signals"], ascending=[False, False])
    out.to_csv(args.out, index=False)

    print("\nSignal availability (missing -> weight redistributed):")
    for k in v2.weights:
        n = int(sig[k].notna().sum())
        print(f"  {k:12s} {n:6d}/{len(units)}  ({100 * n / len(units):5.1f}%)")

    print("\nScore distribution:")
    print(score.describe().round(4).to_string())
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
