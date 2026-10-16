"""
HVD (High Value Dataset) scoring model — batch 1 sample.

Implements the methodology's three signals plus a recency term:

    HVD_score = w1*demand + w2*temporal_depth + w3*geo_coverage + w4*recency
    weights     0.40        0.30               0.20              0.10

Signals are each normalised to [0,1]. Where a signal is unavailable for a row,
its weight is redistributed proportionally across the remaining signals rather
than being scored zero (a missing signal is not evidence of low value).

Recency rewards datasets whose metadata was updated recently, on exponential
decay rather than the min-max the other three use: 92.5% of dublin_core_remaining
was last modified 2+ years ago, so min-max would compress that bulk into a
near-identical band and spend the whole scale on it. Decay lets the stale bulk
sit near zero and gives the live tail real separation. It is the smallest weight
because ~43% of the table's modification dates are bulk portal edits (24,933 rows
share 2021-12-10 across 40 ministries), not data refreshes -- those are all old
enough that decay scores them near zero anyway, but the weight is sized so the
signal cannot dominate if that ever stops being true.

Reads from a read-only DuckDB snapshot and writes a CSV keyed by nid. It does
NOT write to the database, and deliberately does not touch the portal's `High
Value Dataset Category` field — that is reserved for the human review step that
follows candidate selection.

Two source tables are supported via --table, each with its own profile in
SOURCE_PROFILES that synthesizes the canonical signal columns (see `load`):

  remaining-raw-datasets  raw, ungrouped OGD API import (see import_csv.py)
  dublin_core_remaining   the Dublin-Core transform of the same datasets
                          (metdata_transform_dublin.py), which additionally
                          carries Collection / merge_method

`remaining-raw-datasets` carries no merge grouping (no Collection) and no
per-row state_department, but the geo signal is still derived here from the
`spatial_coverage` column (populated by extract_coverage_from_title.py) and the
title: a 'State-wise'/'UT-wise' title spans all 36 States/UTs (geo 1.0), a
national 'India' dataset without such a breakdown gets half credit (geo 0.5),
and anything with no spatial signal is left missing so `combine()` redistributes
its 0.25 weight into demand/temporal rather than scoring it zero.

Usage:
    python transformation/utils/hvd_score.py --db <path> --out hvd_scores.csv
    python transformation/utils/hvd_score.py --db <path> \
        --table dublin_core_remaining --out hvd_scores_dublin_remaining.csv
    python transformation/utils/hvd_score.py --db <path> \
        --ministry-departments "Ministry of Health and Family Welfare" "NITI Aayog" \
        --out hvd_scores_mohfw_niti.csv
"""

import argparse
import re
from datetime import date

import duckdb
import numpy as np
import pandas as pd

# A "State-wise" / "UT-wise" title reports one row per State/UT, so the dataset
# already spans all 36 States/UTs — full geographic coverage. "District-wise",
# "Crop-wise", "Village and Gender-wise" etc. deliberately do NOT match.
STATE_WISE_RE = re.compile(
    r"\b(?:state|ut|u\.?t\.?|union\s+territor(?:y|ies))[\s/-]*wise\b", re.I
)

# 28 states + 8 union territories. Matches the 36 distinct values parsed out of
# `Spatial Coverage` in batch 1.
N_STATES_UT = 36

WEIGHTS = {"demand": 0.40, "temporal": 0.30, "geo": 0.20, "recency": 0.10}

SOURCE_TABLE = "remaining-raw-datasets"

# Per-table SQL for the columns the signal functions consume. Everything else
# (date normalisation, Temporal Coverage reshaping) happens in `load`.
SOURCE_PROFILES = {
    # Raw OGD API landing table: snake_case columns, DD-MM-YYYY dates, no
    # Collection, temporal split across two native timestamp columns.
    "remaining-raw-datasets": {
        "ministry_col": "ministry_department",
        "select": '''
            nid,
            title AS "Title",
            ministry_department AS "Publisher[ministry_department]",
            sector AS "Subject[sector]",
            ogdp_download_count,
            ogdp_view_count,
            created AS issued_raw,
            changed AS modified_raw,
            data_time_period_from AS tc_from,
            data_time_period_to AS tc_to,
            CAST(NULL AS VARCHAR) AS "Collection",
        ''',
        "date_format": "%d-%m-%Y",
        "temporal": "year_prefix",
    },
    # Dublin-Core transform of the same datasets: bracketed canonical column
    # names, ISO dates, a single `Temporal Coverage` ISO interval, and a
    # populated Collection (so signal_geo's per-collection rule actually fires).
    #
    # Date Issued is deliberately NOT the demand-age basis here: it carries the
    # API's `published`, blank on 49,381 of 116,111 rows. `Date Created` carries
    # `created` — the same field the raw profile uses, populated on every row —
    # so the two profiles measure age the same way and stay comparable.
    "dublin_core_remaining": {
        "ministry_col": '"Publisher[ministry_department]"',
        "select": '''
            nid,
            "Title",
            "Publisher[ministry_department]",
            "Subject[sector]",
            ogdp_download_count,
            ogdp_view_count,
            COALESCE(NULLIF(trim("Date Created"), ''), "Date Issued") AS issued_raw,
            "Date Modified" AS modified_raw,
            "Temporal Coverage" AS tc_interval,
            "Collection",
        ''',
        "date_format": "%Y-%m-%d",
        "temporal": "iso_interval",
    },
}


def _temporal_from_year_prefix(df):
    """`start:YYYY;end:YYYY` from two native timestamp columns' year prefixes.

    remaining-raw-datasets stores the bounds as ISO timestamps in
    data_time_period_from/_to, so the year prefix is the whole signal.
    """
    year_from = df["tc_from"].fillna("").str.slice(0, 4)
    year_to = df["tc_to"].fillna("").str.slice(0, 4)
    has_span = (year_from != "") & (year_to != "")
    return pd.Series(
        np.where(has_span, "start:" + year_from + ";end:" + year_to, "None"),
        index=df.index,
    )


def _temporal_from_iso_interval(df):
    """`start:YYYY;end:YYYY` from a `YYYY-MM-DD/YYYY-MM-DD` interval.

    Year labels alone would double-count fiscal years: 2019-04-01/2020-03-31 is
    twelve months, but its labels say 2019..2020, which signal_temporal reads as
    a two-year span — twice the depth of a calendar-year peer covering the same
    twelve months. Fiscal years are the norm on this table (Apr–Mar is what
    extract_coverage_from_title.py mints), so the span is taken from the
    interval's duration and re-expressed as an end year the existing
    `end - start + 1` reproduces exactly. The start year stays real, so
    signal_temporal's implausible-start mask still sees the true date.
    """
    tc = df["tc_interval"].fillna("").str.strip()
    parts = tc.str.split("/", n=1, expand=True)
    if parts.shape[1] < 2:
        return pd.Series("None", index=df.index)
    start = pd.to_datetime(parts[0], errors="coerce")
    end = pd.to_datetime(parts[1], errors="coerce")

    days = (end - start).dt.days
    # Reversed or unparseable intervals are missing, not zero-length.
    valid = start.notna() & end.notna() & (days >= 0)
    span = (days / 365.25).round().clip(lower=1)

    start_year = start.dt.year
    end_year = start_year + span - 1
    return pd.Series(
        np.where(
            valid,
            "start:" + start_year.astype("Int64").astype(str)
            + ";end:" + end_year.astype("Int64").astype(str),
            "None",
        ),
        index=df.index,
    )


TEMPORAL_BUILDERS = {
    "year_prefix": _temporal_from_year_prefix,
    "iso_interval": _temporal_from_iso_interval,
}


def load(db_path, ministries=None, table=SOURCE_TABLE):
    """Load `table`, reshaped into the canonical signal columns.

    The signal functions expect one shape — Title / Date Issued / Temporal
    Coverage (`start:YYYY;end:YYYY`) / Spatial Coverage / Collection. Neither
    source table is stored in that shape, and they differ from each other in
    column naming, date format and how the temporal bounds are encoded. Rather
    than teach signal_temporal's winsorisation and implausible-start masking, or
    signal_geo's grouping, about a second schema, each profile synthesizes those
    canonical columns here:

      - Date Issued <- the profile's `issued_raw`, parsed with its date format.
      - Date Modified <- the profile's `modified_raw` (raw `changed` /
        Dublin `Date Modified`), same date format. Populated on every row of
        both tables.
      - Temporal Coverage <- rebuilt as `start:YYYY;end:YYYY` by the profile's
        temporal builder.
      - Collection <- the real column on dublin_core_remaining (61,117 rows
        carry one), NULL on the raw table, which has no merge grouping.
      - Spatial Coverage <- the `spatial_coverage` column (populated by
        extract_coverage_from_title.py: "[District, ]State, India", or bare
        "India" for national datasets). NaN if that column has not been created
        yet, in which case the geo signal falls back to being unavailable.
    """
    if table not in SOURCE_PROFILES:
        raise SystemExit(
            f"No source profile for table {table!r}; "
            f"known: {', '.join(sorted(SOURCE_PROFILES))}"
        )
    profile = SOURCE_PROFILES[table]

    con = duckdb.connect(db_path, read_only=True)

    has_spatial = con.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = ? AND column_name = 'spatial_coverage'",
        [table],
    ).fetchone()[0] > 0
    spatial_expr = "spatial_coverage" if has_spatial else "CAST(NULL AS VARCHAR)"

    where = []
    params = []
    if ministries:
        placeholders = ", ".join("?" for _ in ministries)
        where.append(f"{profile['ministry_col']} IN ({placeholders})")
        params.extend(ministries)
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    df = con.execute(
        f"""
        SELECT
            {profile['select'].strip()}
            {spatial_expr} AS "Spatial Coverage"
        FROM "{table}"
        {where_clause}
        """,
        params,
    ).fetchdf()
    con.close()

    df["Date Issued"] = pd.to_datetime(
        df["issued_raw"], format=profile["date_format"], errors="coerce")
    df["Date Modified"] = pd.to_datetime(
        df["modified_raw"], format=profile["date_format"], errors="coerce")

    df["Temporal Coverage"] = TEMPORAL_BUILDERS[profile["temporal"]](df)

    df["Collection"] = df["Collection"].fillna("")

    return df


def minmax(s, clip_pct=None):
    """Min-max normalise to [0,1], preserving NaN as missing.

    `clip_pct` winsorises the upper tail before scaling. The log transform alone
    does not achieve the methodology's stated goal of stopping "a handful of
    viral datasets from flattening everything else to zero": in batch 1 the top
    download count is ~360x the median, and one 211-year temporal span crushed
    the 3-year majority to 0.009. Capping at a high percentile keeps the
    intended behaviour. Values above the cap saturate at 1.0 — they are
    unambiguously top-tier on that signal and rank as candidates regardless.
    """
    x = s
    if clip_pct is not None and s.notna().any():
        x = s.clip(upper=np.nanpercentile(s.dropna(), clip_pct))
    lo, hi = x.min(), x.max()
    if pd.isna(lo) or hi == lo:
        # Degenerate spread: everything present scores equally.
        return x.notna().astype(float).replace(0.0, np.nan)
    return (x - lo) / (hi - lo)


def signal_demand(df, as_of, clip_pct):
    """Downloads and views per month since publication, log-damped, normalised.

    Raw counts are long-tailed, so we log-transform before normalising to stop a
    handful of viral datasets flattening everything else to zero. Rates are used
    rather than lifetime totals because counts are age-biased.
    """
    issued = pd.to_datetime(df["Date Issued"], errors="coerce")
    months = (pd.Timestamp(as_of) - issued).dt.days / 30.44
    months = months.where(months >= 1.0, 1.0)  # floor at 1 month

    out = {}
    for name, col in (("dl", "ogdp_download_count"), ("vw", "ogdp_view_count")):
        raw = pd.to_numeric(df[col], errors="coerce")
        out[name] = minmax(np.log1p(raw / months), clip_pct)

    # Average the two facets; if only one is present, use it alone.
    demand = pd.concat([out["dl"], out["vw"]], axis=1).mean(axis=1, skipna=True)
    return demand, out["dl"], out["vw"], months


def signal_temporal(df, clip_pct, min_start):
    """Span in years parsed from `start:YYYY;end:YYYY`.

    A single snapshot supports lookup; multiple years support trend analysis.
    The literal string 'None' is a missing marker, not a zero-length span.

    Depth is log-transformed: the analytical gain from 1 -> 3 years is large,
    from 100 -> 200 years negligible. Batch 1 also contains implausible starts
    (start:1810 in an HMIS health series) that are data-entry artifacts; log +
    winsorisation stops them setting the scale for everyone else.
    """
    tc = df["Temporal Coverage"].fillna("").str.strip()
    start = tc.str.extract(r"start:(\d{4})", expand=False).astype(float)
    end = tc.str.extract(r"end:(\d{4})", expand=False).astype(float)

    depth = (end - start + 1).where(start.notna() & end.notna())
    depth = depth.where(depth >= 1)  # guard reversed/garbage ranges

    # Starts before `min_start` are parse artifacts, not history: the affected
    # rows are single-year AHS/HMIS surveys ("...Annual Health Survey in
    # Dhamtari" carrying start:1910). Left in, they scored temporal ~1.0 and
    # made up 38% of the candidate set. Treated as MISSING rather than zero, so
    # the weight redistributes -- an unparseable field is not evidence of low
    # value. Genuine long series (e.g. "Crude Death Rate, 1971 to 2012") start
    # well after the cutoff and keep their full temporal score.
    implausible = (start < min_start).fillna(False)
    depth = depth.mask(implausible)

    # Why temporal is absent, so a reviewer can tell a bad date from no date.
    flag = pd.Series("ok", index=df.index)
    flag[tc.isin(["", "None"]) | start.isna() | end.isna()] = "no_date"
    flag[implausible] = f"implausible_start_pre_{min_start}"
    return minmax(np.log1p(depth), clip_pct), depth, flag, implausible


def signal_recency(df, as_of, half_life_days):
    """Exponential decay on days since last modification: 0.5 ** (days/half_life).

    A dataset refreshed last month is more valuable than the same dataset last
    touched in 2016, and unlike the other three signals this one is about the
    *series being alive*, not about its content.

    Decay rather than min-max because the age distribution is not spread out:
    92.5% of dublin_core_remaining was modified 2+ years ago, so min-max would
    hand almost the entire [0,1] range to distinctions inside the stale bulk and
    leave the live tail crowded at the top. Decay is absolute -- a half-life of a
    year means a year-old row scores 0.5 whatever the rest of the table looks
    like -- so the 585 rows refreshed in the last quarter separate cleanly and
    the 2021 bulk-edit cohort lands near zero on its own.

    Rows modified after `as_of` (clock skew, or scoring against a past date)
    saturate at 1.0 rather than scoring above it.
    """
    modified = pd.to_datetime(df["Date Modified"], errors="coerce")
    days = (pd.Timestamp(as_of) - modified).dt.days
    recency = np.power(0.5, days / half_life_days)
    return recency.clip(upper=1.0).where(modified.notna()), days


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


def signal_geo(df):
    """Fraction of the 36 States/UTs a dataset spans.

    Coverage precedence (later rules override earlier):
      1. Per-Collection fraction of distinct States/UTs the merge family spans
         (partial credit: 28/36 beats 4/36). Only relevant on tables that carry
         a Collection; blank here.
      2. National ('India') datasets that are NOT reported per State/UT get
         HALF credit (0.5): they cover the whole country but as one aggregate,
         not resolved to every State/UT.
      3. A 'State-wise' / 'UT-wise' title reports one row per State/UT, so the
         dataset already spans all 36 — FULL credit (1.0).

    Mergeability is deliberately NOT considered here — merge-cohort scoring
    lives in hvd_score_collections.py. This script scores every row on the geo
    signal it has, regardless of merge_method.
    """
    state = df["Spatial Coverage"].map(parse_state)
    is_national = df["Spatial Coverage"].fillna("").str.strip().str.lower() == "india"
    state_wise = df["Title"].fillna("").str.contains(STATE_WISE_RE)

    coll = df["Collection"].fillna("").str.strip()
    has_coll = coll != ""

    # distinct real States/UTs per collection
    per_coll = (
        pd.DataFrame({"coll": coll, "state": state})
        .dropna(subset=["state"])
        .groupby("coll")["state"]
        .nunique()
    )
    coll_frac = coll.map(per_coll).astype(float) / N_STATES_UT
    coll_frac = coll_frac.clip(upper=1.0)

    geo = coll_frac.where(has_coll)
    # Precedence is deliberate: national (0.5) overrides any Collection fraction,
    # and State/UT-wise (1.0) overrides both. On remaining-raw-datasets Collection
    # is always blank so coll_frac is always NaN and only rules 2-3 fire. On a
    # table with populated Collections, a national row in a partial-coverage
    # collection is intentionally pinned to 0.5 rather than its coll_frac.
    geo = geo.mask(is_national, 0.5)   # national but aggregate -> half credit
    geo = geo.mask(state_wise, 1.0)    # per-State/UT breakdown -> full credit
    # Report the state count only where a collection actually exists; rows with
    # no Collection would otherwise inherit the empty-string group's tally.
    return geo, state, coll.map(per_coll).where(has_coll)


def combine(sig):
    """Weighted sum with proportional redistribution of missing signals' weight."""
    w = pd.DataFrame(
        {k: np.where(sig[k].notna(), WEIGHTS[k], 0.0) for k in WEIGHTS},
        index=sig.index,
    )
    total = w.sum(axis=1)
    contrib = sum(w[k] * sig[k].fillna(0.0) for k in WEIGHTS)
    return (contrib / total).where(total > 0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--table", default=SOURCE_TABLE, choices=sorted(SOURCE_PROFILES),
                   help="Source table to score; each has a profile mapping its "
                        "columns onto the canonical signal columns")
    p.add_argument("--ministry-departments", nargs="+", default=None,
                   help="Restrict to these ministry_department values only (exact match, "
                        "space-separated; quote multi-word names). Omit to score all rows")
    p.add_argument("--out", default="transformation/hvd_scores.csv")
    p.add_argument("--as-of", default=str(date.today()))
    p.add_argument("--top-pct", type=float, default=10.0,
                   help="Percentile cut for the candidate flag")
    p.add_argument("--clip-pct", type=float, default=99.0,
                   help="Winsorise signal upper tails at this percentile before min-max")
    p.add_argument("--recency-half-life", type=float, default=365.0,
                   help="Days after which the recency signal halves (365 = a "
                        "year-old modification scores 0.5, two years 0.25)")
    p.add_argument("--min-start-year", type=int, default=1950,
                   help="Temporal starts before this are treated as unparseable (missing)")
    p.add_argument("--drop-implausible-temporal", action="store_true",
                   help="Exclude implausible-start rows from the scored output entirely, "
                        "writing them to a companion _excluded.csv instead of scoring them")
    args = p.parse_args()

    df = load(args.db, args.ministry_departments, args.table)
    scope = f"ministries {args.ministry_departments}" if args.ministry_departments else "all rows"
    print(f"Loaded {len(df)} rows for {scope} from \"{args.table}\"")

    demand, dl, vw, months = signal_demand(df, args.as_of, args.clip_pct)
    temporal, depth, tflag, implausible = signal_temporal(
        df, args.clip_pct, args.min_start_year)
    print(f"Temporal starts before {args.min_start_year} "
          f"(treated as missing, not zero): {int(implausible.sum())}")
    geo, state, coll_states = signal_geo(df)
    recency, days_since_mod = signal_recency(df, args.as_of, args.recency_half_life)
    print(f"Modified within the last year (recency >= 0.5 at a "
          f"{args.recency_half_life:g}-day half-life): "
          f"{int((days_since_mod <= args.recency_half_life).sum())}")

    sig = pd.DataFrame({"demand": demand, "temporal": temporal, "geo": geo,
                        "recency": recency})
    score = combine(sig)

    # How much evidence a score rests on. Weight redistribution means a row with
    # one saturated signal can score 1.0 on thin evidence, outranking a row that
    # is strong on all three. The methodology mandates redistribution, so this
    # column surfaces the thinness for the reviewer instead of suppressing it.
    n_signals = sig.notna().sum(axis=1)
    signals_present = sig.notna().apply(
        lambda r: "+".join(c for c in sig.columns if r[c]) or "none", axis=1
    )

    # Percentile cut is taken over whatever is actually being scored, so
    # dropping rows re-sizes the candidate set rather than shrinking it.
    keep = ~implausible if args.drop_implausible_temporal else pd.Series(True, index=df.index)
    cut = np.nanpercentile(score[keep], 100 - args.top_pct)

    out = pd.DataFrame({
        "nid": df["nid"],
        "Title": df["Title"],
        "Collection": df["Collection"],
        "ministry": df["Publisher[ministry_department]"],
        "downloads": pd.to_numeric(df["ogdp_download_count"], errors="coerce"),
        "views": pd.to_numeric(df["ogdp_view_count"], errors="coerce"),
        "date_issued": df["Date Issued"],
        "months_since_issue": months.round(1),
        "date_modified": df["Date Modified"],
        "days_since_modified": days_since_mod,
        "temporal_span_years": depth,
        "temporal_flag": tflag,
        "state_ut": state,
        "collection_states_covered": coll_states,
        "hvd_demand": demand.round(4),
        "hvd_temporal": temporal.round(4),
        "hvd_geo": geo.round(4),
        "hvd_recency": recency.round(4),
        "hvd_score": score.round(4),
        "hvd_candidate": (score >= cut).astype(int),
        "n_signals": n_signals,
        "signals_present": signals_present,
    }).sort_values(["hvd_score", "n_signals"], ascending=[False, False])

    if args.drop_implausible_temporal:
        # Excluded rows are written out, never silently discarded: their dates
        # are untrustworthy but the datasets themselves may still be valuable.
        excluded = out[implausible.reindex(out.index).fillna(False)]
        kept = out[~implausible.reindex(out.index).fillna(False)]
        exc_path = args.out.replace(".csv", "_excluded.csv")
        excluded.to_csv(exc_path, index=False)
        kept.to_csv(args.out, index=False)
        print(f"\nExcluded {len(excluded)} implausible-start rows -> {exc_path}"
              f"  ({int(excluded.hvd_candidate.sum())} of them would have been candidates)")
        out = kept
    else:
        out.to_csv(args.out, index=False)

    # ---- reporting ----
    print(f"\nSignal availability (missing -> weight redistributed):")
    for k in WEIGHTS:
        n = int(sig[k].notna().sum())
        print(f"  {k:9s} {n:5d}/{len(df)}  ({100*n/len(df):5.1f}%)")

    print(f"\nScore distribution:")
    print(score.describe().round(4).to_string())
    print("\nDeciles:")
    for q in range(10, 101, 10):
        print(f"  p{q:<3d} {np.nanpercentile(score, q):.4f}")

    print(f"\nTop {args.top_pct}% cut = {cut:.4f} -> "
          f"{int(out['hvd_candidate'].sum())} candidates")

    print("\nEvidence depth of candidates (how many signals the score rests on):")
    cand = out[out.hvd_candidate == 1]
    for combo, n in cand["signals_present"].value_counts().items():
        print(f"  {combo:24s} {n:4d}  ({100*n/len(cand):5.1f}% of candidates)")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
