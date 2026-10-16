"""
HVD Pulse -- monthly High Value Dataset scoring with a freshness check.

    hvd_score = 0.35*demand + 0.25*temporal + 0.15*geo
              + 0.10*liveness + 0.15*punctuality

Every signal is normalised to [0,1]. A signal that is unavailable for a row is
NaN, not zero, and `combine` redistributes its weight across the rest -- a
missing signal is not evidence of low value.

The two freshness terms are separate on purpose:

  liveness     how stale is this, in absolute terms. 0.5 ** (days/365), so a
               year-old row scores 0.5 whatever cadence it declared. Universal.

  punctuality  did this refresh inside its OWN declared period. Binary: 1.0 on
               time, 0.0 late. NaN when the check does not apply -- not API-fed,
               cadence coarser than annual, or no modification date.

Making the half-life itself cadence-relative (one term instead of two) inverts
the score: a Decadal table 8.5 years stale scores 0.55 while a Quarterly one 4
years stale scores 0.00002, and Daily underflows to a hard 0.0. Since the
cadence is a publisher-controlled dropdown, that is a score you can buy by
editing a field. Here, declaring a lax cadence only ever buys NaN -- the neutral
outcome -- so a publisher who does refresh monthly can only lose by declaring
Decadal.

Two rules key off the dataset's RESOURCE TYPE (the portal's
`field_resource_type`, carried as `Accrual Method` on the dublin_core tables),
because two kinds of dataset are misread by the generic signals:

  type 6   API-served datasets -- dashboards and JSON feeds. Nobody downloads
           them, they are polled, so `ogdp_download_count` reads near zero and
           demand understates them. The download facet reads
           `api_request_count` instead.

  type 2   external links to a publisher's own host. The portal row is a
           POINTER, so `Date Modified` records edits to the pointer rather than
           refreshes of the data behind it -- on dublin_core_remaining 35,277 of
           the 36,316 type-2 rows carry a modification date NEWER than their own
           data, by a median of 19 years. Both freshness terms are measured from
           the last date the DATA covers instead.

Both rules are inert on a profile that does not select the column they need, so
a table without `api_request_count` or a data-end column scores exactly as it
did before.

Stateless by design: no snapshot ledger, no cadence table, no score history.
Each run is a pure function of the table it reads, so it can run anywhere the
same columns exist. Locally the modification dates are stale; on the portal they
are live and the same logic works unchanged.

Reads read-only and writes one CSV. It never writes the portal's
`High Value Dataset Category` field -- that stays a human publishing decision.

Two backends, same scoring code:

  DuckDB      --db path/to/metadata.db          (local snapshot)
  Postgres    --db pg                           (credentials from the environment)

The Postgres path goes through DuckDB's `postgres` extension (ATTACH ... TYPE
POSTGRES, READ_ONLY), which is what the rest of this repo already uses to reach
Postgres -- see transformation/setup_ducklake.py. No extra Python driver is
needed, and every SELECT below stays valid DuckDB SQL on both backends.

To point this at YOUR Postgres table, edit exactly two things:

  1. the environment (see `pg_dsn` below) -- nothing about creds lives in this
     file;
  2. the `postgres` entry in `tables` -- the column list. That entry is a
     template with every column the five signals consume, aliased to the names
     the code expects; rename the left-hand side of each alias to match your
     schema and you are done.

Types matter more on Postgres than on DuckDB, so the profile SQL casts
explicitly (`::TEXT`, `::TIMESTAMP`). See the comment on the `postgres` profile
-- an uncast boolean or date column produces a CSV that looks fine and is
wrong.

Usage:
    python hvd_scoring/hvd_score.py --db transformation/metadata.db
    python hvd_scoring/hvd_score.py --db <path> --table dublin_core_metadata
    python hvd_scoring/hvd_score.py --db <path> --limit 1000

    export PGHOST=... PGDATABASE=... PGUSER=... PGPASSWORD=...
    python hvd_scoring/hvd_score.py --db pg --table postgres
    python hvd_scoring/hvd_score.py --db pg --table postgres --print-sql

    python hvd_scoring/hvd_score.py --db <path> --api-only \
        --cut-mode absolute --cut-value 0.42
"""

import argparse
import os
import re
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# ---------------------------------------------------------------- config ----
# Change these three things to run this somewhere else: the db string, the
# `connect` function below, and (if the columns differ) a `tables` entry.

# Anchored to the repo root, so the defaults resolve from any working directory.
repo_root = Path(__file__).resolve().parent.parent

# Either a DuckDB file path, or one of `pg_aliases` to go to Postgres. $HVD_DB
# overrides, so a scheduled run can be pointed at Postgres with no flags:
#     HVD_DB=pg python hvd_scoring/hvd_score.py --table postgres
default_db = os.environ.get("HVD_DB", str(repo_root / "transformation" / "metadata.db"))
default_out = str(repo_root / "hvd_scoring" / "hvd_scores.csv")

# --db values that mean "the Postgres in the environment". A libpq URL
# (postgres://... / postgresql://...) is also recognised, in `is_postgres`.
pg_aliases = {"pg", "postgres", "postgresql", "env"}

# Name the ATTACHed Postgres catalog gets inside DuckDB. `load` qualifies the
# table as <pg_catalog_alias>.<schema>.<table>, so this is only visible if you
# write your own SQL against the connection.
pg_catalog_alias = "pg"

# Postgres schema holding the table. Postgres tables are not necessarily in
# `public`; override per run with $PGSCHEMA or per profile with a "schema" key.
pg_default_schema = os.environ.get("PGSCHEMA", "public")

# Parameter marker for the --ministry-departments IN (...) list. `?` is correct
# for both backends here because the Postgres path is still a DuckDB
# connection; it would become '%s' only if this ever moved to psycopg directly.
placeholder = "?"


def pg_dsn():
    """Build a libpq DSN from the environment. Nothing lives in this file.

    Precedence:
      1. HVD_PG_DSN / DATABASE_URL -- a complete DSN or URL, used verbatim.
         This is the one to use for Neon and friends, whose connection strings
         carry options (channel_binding, endpoint id) that the discrete vars
         below cannot express.
      2. the standard libpq vars: PGHOST, PGPORT, PGDATABASE, PGUSER,
         PGPASSWORD, PGSSLMODE.

    Only the keys that are actually set are emitted, so libpq's own defaults
    (localhost, 5432, USER, ~/.pgpass) still apply to whatever is left out --
    which also means a password never has to appear in a command line or in
    this repo.

    sslmode defaults to `require` and connect_timeout to 15s: every managed
    Postgres this would realistically point at requires TLS, and without a
    timeout a blocked 5432 (a known hazard on this network -- see
    transformation/setup_ducklake.py) hangs the run instead of failing it.
    """
    url = os.environ.get("HVD_PG_DSN") or os.environ.get("DATABASE_URL")
    if url:
        return url

    parts = {
        "host": os.environ.get("PGHOST"),
        "port": os.environ.get("PGPORT"),
        "dbname": os.environ.get("PGDATABASE"),
        "user": os.environ.get("PGUSER"),
        "password": os.environ.get("PGPASSWORD"),
        "sslmode": os.environ.get("PGSSLMODE", "require"),
        "connect_timeout": os.environ.get("PGCONNECT_TIMEOUT", "15"),
    }
    dsn = " ".join(f"{k}={v}" for k, v in parts.items() if v)
    if "host=" not in dsn and "dbname=" not in dsn:
        raise SystemExit(
            "Postgres requested but the environment is empty. Set either\n"
            "  HVD_PG_DSN='postgresql://user:pw@host/db?sslmode=require'\n"
            "or the standard PGHOST / PGDATABASE / PGUSER / PGPASSWORD vars."
        )
    return dsn


def is_postgres(db):
    return db in pg_aliases or str(db).startswith(("postgres://", "postgresql://"))


def redact(text):
    """Mask any password in a DSN. Both spellings: `password=...` and the
    `://user:pw@host` form. Used on everything that prints a DSN -- including
    DuckDB's own connection errors, which echo the DSN back verbatim and would
    otherwise put the password in a log or CI transcript."""
    text = re.sub(r"(password=)[^ ]+", r"\1***", text)
    return re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1***@", text)

weights = {
    "demand": 0.15,
    "temporal": 0.25,
    "geo": 0.15,
    "liveness": 0.20,
    "punctuality": 0.25,
}

# Declared cadence -> days it is allowed to go without a refresh. Anything not
# listed here is not auditable by a monthly run (decadal, five yearly, biennial,
# one-time, others, irregular, blank) and scores punctuality NaN.
cadence_days = {
    "hourly": 30.0,
    "daily": 30.0,
    "weekly": 30.0,
    "fortnightly": 30.0,
    "monthly": 30.0,
    "quarterly": 91.0,
    "half yearly": 183.0,
    "biannual": 183.0,
    "annual": 365.0,
}

# One run interval, and the floor under every cadence above. A monthly job
# cannot resolve anything finer, so sub-monthly cadences all collapse to it and
# the check reduces to exactly the intended question: was it updated this month
# or not. Keep this equal to the sub-monthly entries in `cadence_days` -- the
# floor is applied AFTER the lookup, so a larger value here silently overrides
# them.
run_interval_days = 30.0

# Accepted spellings of the field_from_api gate. Free-text VARCHAR: this
# database already holds '1', '0', '' and NULL in it across tables, plus the
# literal string 'NULL' in the aikosh tables. Compared lower-cased.
api_true = {"1", "true", "yes", "y", "t"}
api_blank = {"", "null", "none", "nan"}

half_life_days = 365.0

# Resource types that get a substituted signal input. The value is the portal's
# `field_resource_type` code, which the dublin_core tables carry as
# `Accrual Method`; matched as a trimmed string because it arrives as VARCHAR.
#
# Both sets are deliberately narrow. The generic behaviour is right for type 1
# (a file the portal itself serves); these two are the shapes where the generic
# column is measuring the wrong object.
request_count_types = {"6"}   # demand reads api_request_count, not downloads
dataset_date_types = {"2"}    # freshness reads the data's own last date

n_states_ut = 36  # 28 states + 8 union territories

# A "State-wise" / "UT-wise" title reports one row per State/UT, so the dataset
# already spans all 36. "District-wise", "Crop-wise" etc. deliberately do not.
state_wise_re = re.compile(
    r"\b(?:state|ut|u\.?t\.?|union\s+territor(?:y|ies))[\s/-]*wise\b", re.I
)

# Per-table SQL for the columns the signals consume. `temporal` says how that
# table encodes Temporal Coverage: "start_end" is already `start:YYYY;end:YYYY`,
# "interval" is an ISO `YYYY-MM-DD/YYYY-MM-DD` that needs converting.
#
# Date Created, not Date Issued, is the demand-age basis: Date Issued carries
# the API's `published`, blank on 49,381 rows of dublin_core_remaining, while
# Date Created carries `created` and is populated on effectively every row of
# both tables.
tables = {
    # `data_time_period_to` is the portal's own "data covers up to" timestamp
    # and is what the type-2 freshness rule reads. There is no
    # api_request_count on this table, so the type-6 demand substitution cannot
    # fire here and its 36 rows keep scoring on downloads -- that column exists
    # on dublin_core_metadata and on the portal's live table.
    "dublin_core_remaining": {
        "ministry_col": '"Publisher[ministry_department]"',
        "select": '''
            nid,
            "Title",
            "Publisher[ministry_department]",
            "Collection",
            "Spatial Coverage",
            "Temporal Coverage" AS temporal_raw,
            ogdp_download_count,
            ogdp_view_count,
            COALESCE(NULLIF(trim("Date Created"), ''), "Date Issued") AS issued_raw,
            "Date Modified" AS modified_raw,
            "Accrual Periodicity" AS cadence_raw,
            field_from_api,
            "Accrual Method" AS resource_type_raw,
            data_time_period_to AS data_end_raw,
        ''',
        "temporal": "interval",
    },
    # Same shape, three differences: Temporal Coverage is already in start/end
    # form, Accrual Periodicity arrives as a purl.org CLD URI that has to have
    # its prefix stripped before it matches `cadence_days`, and there is no
    # data_time_period_to -- so a type-2 row here falls back to the end year of
    # its Temporal Coverage (see `dataset_last_date`). Every row on this table
    # is currently resource type 1, so neither rule changes its output.
    "dublin_core_metadata": {
        "ministry_col": '"Publisher[ministry_department]"',
        "select": '''
            nid,
            "Title",
            "Collection",
            "Publisher[ministry_department]",
            "Spatial Coverage",
            "Temporal Coverage" AS temporal_raw,
            ogdp_download_count,
            ogdp_view_count,
            COALESCE(NULLIF(trim("Date Created"), ''), "Date Issued") AS issued_raw,
            "Date Modified" AS modified_raw,
            replace("Accrual Periodicity",
                    'http://purl.org/cld/freq/', '') AS cadence_raw,
            field_from_api,
            "Accrual Method" AS resource_type_raw,
            api_request_count AS request_count_raw,
        ''',
        "temporal": "start_end",
    },

    # ------------------------------------------------------------------------
    # THE POSTGRES PROFILE -- this is the one to edit.
    #
    # It is a template, not a working query: the column names below are the
    # DuckDB ones. Change the LEFT side of every alias to whatever your
    # Postgres table calls it; never change the right side (`AS temporal_raw`
    # etc.) -- those alias names are the contract the signal functions read.
    # A column you genuinely do not have: delete the line. Its signal then
    # scores NaN for every row and `combine` redistributes the weight, which is
    # the intended behaviour for a missing signal. The exceptions are `nid` and
    # `"Title"`, which the output CSV needs, and which the geo signal reads.
    #
    # Set "table" to the real relation name and "schema" if it is not public.
    # `--table postgres` then selects this profile regardless of what the
    # underlying relation is called, so the profile name and the SQL name are
    # free to differ.
    #
    # CASTS ARE NOT DECORATION. DuckDB hands every text-ish column back as a
    # pandas object column; Postgres does not, and the signal code assumes the
    # DuckDB shape. Three ways an uncast column produces a plausible-looking
    # CSV that is wrong or a crash:
    #
    #   field_from_api as boolean/integer -> `.str.strip()` in `load` yields
    #       all-NaN -> the api_true test is False on every row -> punctuality
    #       is NaN table-wide, which is indistinguishable in the output from
    #       "this table has no API-fed datasets". Silent. ::TEXT gives
    #       'true'/'false', both of which api_true/api_blank already handle.
    #   a real `date`/`timestamp` column inside trim() -> Postgres has no
    #       trim(date); the query errors out. Loud, at least.
    #   `timestamptz` -> tz-aware datetimes, and `as_of` is tz-naive, so the
    #       date arithmetic in signal_demand/signal_liveness raises. `load`
    #       defensively strips tz as well, but cast here so the profile stays
    #       the single place types are pinned.
    #
    # Numeric counts are safe uncast -- signal_demand and the output block both
    # go through pd.to_numeric, which handles Decimal.
    #
    # THREE OPTIONAL COLUMNS drive the resource-type rules. Unlike the rest,
    # deleting one of these does not cost a signal -- it just switches that rule
    # off and the row scores the generic way:
    #
    #   resource_type_raw   the field_resource_type code. Without it NEITHER
    #                       rule can fire, whatever the other two say.
    #   request_count_raw   api_request_count, for the type-6 demand swap.
    #   data_end_raw        the data's own end date (data_time_period_to here),
    #                       for the type-2 freshness swap. Cast it the same way
    #                       as modified_raw -- it goes through the same parser
    #                       and a timestamptz has the same tz hazard. This is
    #                       the one line here that the local dublin_core_metadata
    #                       does NOT have a column for, so if your table is
    #                       shaped like that one, delete it (or point it at your
    #                       own data-till field) or the SELECT will fail. The
    #                       rule then falls back to the Temporal Coverage end.
    #                       --print-sql catches this without connecting.
    # ------------------------------------------------------------------------
    "postgres": {
        "table": "dublin_core_metadata",
        "schema": pg_default_schema,
        "ministry_col": '"Publisher[ministry_department]"',
        "select": '''
            nid                                    AS nid,
            "Title"::TEXT                          AS "Title",
            "Publisher[ministry_department]"::TEXT  AS "Publisher[ministry_department]",
            "Collection"::TEXT                     AS "Collection",
            "Spatial Coverage"::TEXT               AS "Spatial Coverage",
            "Temporal Coverage"::TEXT              AS temporal_raw,
            ogdp_download_count                    AS ogdp_download_count,
            ogdp_view_count                        AS ogdp_view_count,
            COALESCE(NULLIF(trim("Date Created"::TEXT), ''),
                     "Date Issued"::TEXT)          AS issued_raw,
            "Date Modified"::TIMESTAMP::TEXT       AS modified_raw,
            replace("Accrual Periodicity"::TEXT,
                    'http://purl.org/cld/freq/', '') AS cadence_raw,
            field_from_api::TEXT                   AS field_from_api,
            "Accrual Method"::TEXT                 AS resource_type_raw,
            api_request_count                      AS request_count_raw,
            data_time_period_to::TIMESTAMP::TEXT   AS data_end_raw,
        ''',
        # "interval" if Temporal Coverage is an ISO YYYY-MM-DD/YYYY-MM-DD range,
        # "start_end" if it is already `start:YYYY;end:YYYY`.
        "temporal": "start_end",
    },
}


def connect(db):
    """The only place that knows how we reach the data.

    Returns a DuckDB connection either way, so every SELECT in `tables` and all
    of the pandas below is backend-agnostic.

      DuckDB file    opened read_only.
      Postgres       an in-memory DuckDB with the Postgres database ATTACHed
                     READ_ONLY through the `postgres` extension. This is the
                     same mechanism transformation/setup_ducklake.py uses, so
                     there is no second driver to install and no second SQL
                     dialect to maintain; DuckDB pushes projections and filters
                     down to Postgres.

    READ_ONLY is not just hygiene here: this script's whole contract is that it
    never writes `High Value Dataset Category`, and the attach-level flag makes
    that true by construction rather than by convention.
    """
    if not is_postgres(db):
        return duckdb.connect(db, read_only=True)

    dsn = pg_dsn() if db in pg_aliases else db
    con = duckdb.connect()  # in-memory; the data stays in Postgres
    con.execute("INSTALL postgres")
    con.execute("LOAD postgres")
    # Single-quotes inside a DSN would break out of the literal; libpq DSNs do
    # not contain them in practice, but doubling costs nothing.
    try:
        con.execute(
            f"ATTACH '{dsn.replace(chr(39), chr(39) * 2)}' AS {pg_catalog_alias} "
            "(TYPE POSTGRES, READ_ONLY)"
        )
    except Exception as e:  # noqa: BLE001 - re-raised redacted; see `redact`
        raise SystemExit(f"Could not attach Postgres: {redact(str(e))}") from None
    return con


def relation(table, db):
    """Fully-qualified, quoted relation name for `table`'s profile.

    A profile's "table" key overrides the SQL relation name, so the profile
    name (`--table postgres`) and the real relation are free to differ; a
    "schema" key qualifies it. Over Postgres the catalog alias goes in front as
    well, because the database is ATTACHed under it -- but only then, so the
    same profile can be pointed at a DuckDB file to test the column list
    without a live connection.
    """
    profile = tables[table]
    parts = []
    if is_postgres(db):
        parts.append(pg_catalog_alias)
    if profile.get("schema"):
        parts.append(f'"{profile["schema"]}"')
    parts.append(f'"{profile.get("table", table)}"')
    return ".".join(parts)


def build_sql(table, db, ministries=None, limit=None):
    """The SELECT this run will issue. Split out so --print-sql can show it."""
    profile = tables[table]
    where = ""
    if ministries:
        slots = ", ".join(placeholder for _ in ministries)
        where = f"WHERE {profile['ministry_col']} IN ({slots})"
    sql = (
        f"SELECT {profile['select'].strip().rstrip(',')} "
        f"FROM {relation(table, db)} {where}"
    )
    # No ORDER BY: repeatable on a DuckDB file (insertion order), not guaranteed over Postgres.
    if limit:
        sql += f" LIMIT {int(limit)}"
    return sql


def load(db, table, ministries=None, limit=None):
    """Read `table` and normalise it into the columns the signals expect."""
    if table not in tables:
        raise SystemExit(
            f"No profile for table {table!r}; known: {', '.join(sorted(tables))}"
        )
    profile = tables[table]

    sql = build_sql(table, db, ministries, limit)
    con = connect(db)
    df = con.execute(sql, list(ministries) if ministries else []).fetchdf()
    con.close()

    # Both tables store ISO dates. Anything unparseable becomes NaT, which the
    # signals read as missing. `utc=True` then tz-strip is a backstop for a
    # Postgres timestamptz that got past the profile's cast: `as_of` is
    # tz-naive, and subtracting a tz-aware series from it raises rather than
    # degrading, so one un-cast column would take down the whole run.
    df["date_issued"] = to_naive_datetime(df["issued_raw"])
    df["date_modified"] = to_naive_datetime(df["modified_raw"])

    if profile["temporal"] == "interval":
        df["temporal_coverage"] = from_interval(df["temporal_raw"])
    else:
        df["temporal_coverage"] = df["temporal_raw"].fillna("None")

    # astype(str) before the .str accessor: on DuckDB these arrive as object
    # columns and this is a no-op, but a Postgres boolean/integer/date that was
    # not cast in the profile would otherwise make `.str` return all-NaN --
    # which for field_from_api means punctuality silently goes NaN table-wide.
    # Failing soft here (and loudly in --print-sql / the load summary) beats
    # producing a CSV that reads as "no API datasets".
    df["cadence"] = as_text(df["cadence_raw"]).str.strip().str.lower()
    df["Collection"] = as_text(df["Collection"])
    df["from_api"] = as_text(df["field_from_api"]).str.strip()

    # The three columns the resource-type rules read are OPTIONAL: a profile
    # whose table does not have one simply leaves the line out, and the rule
    # that needs it goes quiet instead of raising. Same "delete the line"
    # contract as every other column here, except that these cost no signal --
    # the row scores the generic way rather than scoring NaN.
    for col in ("resource_type_raw", "request_count_raw", "data_end_raw"):
        if col not in df.columns:
            df[col] = np.nan
    df["resource_type"] = as_text(df["resource_type_raw"]).str.strip()
    return df


def as_text(s):
    """Series -> object dtype of str, with nulls as ''. Idempotent on VARCHAR."""
    return s.astype("object").where(s.notna(), "").astype(str)


def to_naive_datetime(s):
    """Parse to tz-naive datetimes; NaT for anything unparseable."""
    out = pd.to_datetime(s, errors="coerce", utc=True)
    try:
        return out.dt.tz_localize(None)
    except (TypeError, AttributeError):
        return out


def from_interval(tc):
    """`YYYY-MM-DD/YYYY-MM-DD` -> `start:YYYY;end:YYYY`, by duration.

    Year labels alone double-count fiscal years: 2019-04-01/2020-03-31 is twelve
    months but its labels say 2019..2020, which reads as two years -- twice the
    depth of a calendar-year peer covering the same twelve months. Apr-Mar is
    the norm on this table, so the span comes from the interval's duration and
    is re-expressed as an end year that `end - start + 1` reproduces exactly.
    The start year stays real, so the implausible-start mask still sees the true
    date.
    """
    parts = tc.fillna("").str.strip().str.split("/", n=1, expand=True)
    if parts.shape[1] < 2:
        return pd.Series("None", index=tc.index)

    start = pd.to_datetime(parts[0], errors="coerce")
    end = pd.to_datetime(parts[1], errors="coerce")
    days = (end - start).dt.days

    # Reversed or unparseable intervals are missing, not zero-length.
    ok = start.notna() & end.notna() & (days >= 0)
    span = (days / 365.25).round().clip(lower=1)
    end_year = start.dt.year + span - 1

    return pd.Series(
        np.where(
            ok,
            "start:" + start.dt.year.astype("Int64").astype(str)
            + ";end:" + end_year.astype("Int64").astype(str),
            "None",
        ),
        index=tc.index,
    )


def minmax(s, clip_pct=None):
    """Min-max to [0,1], keeping NaN as missing.

    `clip_pct` winsorises the upper tail first. Without it a handful of outliers
    flatten everything else to zero: the top download count is ~360x the median,
    and one 211-year temporal span crushed the 3-year majority to 0.009. Values
    above the cap saturate at 1.0 -- they are top-tier on that signal either way.
    """
    x = s
    if clip_pct is not None and s.notna().any():
        x = s.clip(upper=np.nanpercentile(s.dropna(), clip_pct))
    lo, hi = x.min(), x.max()
    if pd.isna(lo) or hi == lo:
        return x.notna().astype(float).replace(0.0, np.nan)
    return (x - lo) / (hi - lo)


def demand_count(df):
    """The access count `demand` reads, per row, and where it came from.

    Downloads everywhere except the API-served resource types, whose download
    counter is near zero by construction -- those datasets are polled, not
    downloaded -- so `api_request_count` is the only count that reflects their
    use at all.

    A row of a request-count type whose request count is NULL keeps its download
    count, flagged. Zero requests is evidence and is used as a zero; an absent
    or unselected column is not evidence of anything.

    Both counts go into ONE min-max downstream rather than a scale each. The
    point of the substitution is to put an API-served row on the same demand
    ladder as everything else, and a private ladder over a cohort this small
    (36 rows on dublin_core_remaining) would hand its top row a 1.0 for being
    the best of 36. The cost is that the two counters have to be roughly
    commensurable: if a live api_request_count arrives orders of magnitude above
    the download counts, every row of those types saturates demand. The run
    summary prints both distributions so that shows up rather than passing
    silently.
    """
    downloads = pd.to_numeric(df["ogdp_download_count"], errors="coerce")
    requests = pd.to_numeric(df["request_count_raw"], errors="coerce")

    api_served = df["resource_type"].isin(request_count_types)
    use_requests = api_served & requests.notna()

    count = downloads.mask(use_requests, requests)

    # Last write wins, so the order is precedence lowest-first.
    source = pd.Series("downloads", index=df.index)
    source[api_served] = "no_request_count"
    source[use_requests] = "api_requests"
    return count, source


def signal_demand(df, as_of, clip_pct):
    """Access count and views per month since publication, log-damped.

    Rates rather than lifetime totals, because raw counts are age-biased.

    The first facet is `demand_count`, not `ogdp_download_count` directly: on
    the API-served resource types it is the request count instead.
    """
    months = (pd.Timestamp(as_of) - df["date_issued"]).dt.days / 30.44
    months = months.where(months >= 1.0, 1.0)

    count, count_source = demand_count(df)

    facets = [
        minmax(np.log1p(pd.to_numeric(s, errors="coerce") / months), clip_pct)
        for s in (count, df["ogdp_view_count"])
    ]
    # Average the two; if only one is present, use it alone.
    demand = pd.concat(facets, axis=1).mean(axis=1, skipna=True)
    return demand, months, count, count_source


def signal_temporal(df, clip_pct, min_start):
    """Span in years parsed from `start:YYYY;end:YYYY`.

    One snapshot supports lookup; multiple years support trend analysis. Log-
    transformed because the gain from 1 -> 3 years is large and from 100 -> 200
    negligible. The literal string 'None' is a missing marker, not a zero span.
    """
    tc = df["temporal_coverage"].fillna("").str.strip()
    start = tc.str.extract(r"start:(\d{4})", expand=False).astype(float)
    end = tc.str.extract(r"end:(\d{4})", expand=False).astype(float)

    depth = (end - start + 1).where(start.notna() & end.notna())
    depth = depth.where(depth >= 1)  # guard reversed / garbage ranges

    # Starts before `min_start` are parse artifacts, not history -- single-year
    # AHS/HMIS surveys carrying start:1910. Left in, they scored temporal ~1.0
    # and made up 38% of the candidate set. Treated as missing rather than zero:
    # an unparseable field is not evidence of low value.
    implausible = (start < min_start).fillna(False)
    depth = depth.mask(implausible)

    # Why temporal is absent, so a reviewer can tell a bad date from no date.
    flag = pd.Series("ok", index=df.index)
    flag[tc.isin(["", "None"]) | start.isna() | end.isna()] = "no_date"
    flag[implausible] = f"implausible_start_pre_{min_start}"

    return minmax(np.log1p(depth), clip_pct), depth, flag


def signal_geo(df):
    """Fraction of the 36 States/UTs a dataset spans.

    Later rules override earlier ones:
      1. per-Collection fraction of distinct States/UTs the merge family spans
         (28/36 beats 4/36),
      2. national ('India') but not resolved per State/UT -> half credit,
      3. a State/UT-wise title already spans all 36 -> full credit.

    A national row inside a partial-coverage collection is deliberately pinned
    to 0.5 rather than its collection fraction.
    """
    spatial = df["Spatial Coverage"]
    state = spatial.map(parse_state)
    is_national = spatial.fillna("").str.strip().str.lower() == "india"
    state_wise = df["Title"].fillna("").str.contains(state_wise_re)

    coll = df["Collection"].fillna("").str.strip()
    has_coll = coll != ""
    per_coll = (
        pd.DataFrame({"coll": coll, "state": state})
        .dropna(subset=["state"])
        .groupby("coll")["state"]
        .nunique()
    )

    geo = (coll.map(per_coll).astype(float) / n_states_ut).clip(upper=1.0)
    geo = geo.where(has_coll)
    geo = geo.mask(is_national, 0.5)
    geo = geo.mask(state_wise, 1.0)

    # Report the state count only where a collection exists, or rows without one
    # inherit the empty-string group's tally.
    return geo, state, coll.map(per_coll).where(has_coll)


def parse_state(spatial):
    """State/UT is the token before the trailing 'India'.

    'Bihar, Nalanda, Bihar, India' -> 'Bihar'; bare 'India' -> None (national,
    not attributable to one state).
    """
    if not isinstance(spatial, str):
        return None
    parts = [p.strip() for p in spatial.split(",") if p.strip()]
    if len(parts) < 2 or parts[-1].lower() != "india":
        return None
    return parts[-2]


def dataset_last_date(df, min_start_year):
    """The last date the DATA itself covers, from the most precise source there is.

    In precedence order:

      1. `data_end_raw` -- the portal's own data_time_period_to. A real
         timestamp, and the most direct statement of the question; populated on
         35,330 of the 36,316 type-2 rows of dublin_core_remaining.
      2. the end of a `YYYY-MM-DD/YYYY-MM-DD` Temporal Coverage interval. Also a
         full date, so it is used as-is.
      3. the end YEAR of a `start:YYYY;end:YYYY` Temporal Coverage, read as 31
         December of that year -- the last date a dataset labelled that year
         could cover. Charitable by up to a year on purpose: this is the
         fallback that keeps the rule alive on the year-granularity tables, and
         reading it as 1 January would invent staleness the metadata never
         claimed.

    Ends before `min_start_year` are parse artifacts rather than history -- the
    same guard `signal_temporal` puts on starts -- and are dropped, so the row
    falls back to its Date Modified instead of being scored maximally stale off
    a bad parse.
    """
    tc = as_text(df["temporal_raw"]).str.strip()

    explicit = to_naive_datetime(df["data_end_raw"])
    interval_end = to_naive_datetime(tc.str.split("/", n=1).str[1])
    year_end = to_naive_datetime(
        tc.str.extract(r"end:(\d{4})", expand=False) + "-12-31"
    )

    end = explicit.fillna(interval_end).fillna(year_end)
    return end.mask(end.dt.year < min_start_year)


def freshness_date(df, min_start_year):
    """The date both freshness terms are measured from, per row, and why.

    `Date Modified` everywhere except the resource types in
    `dataset_date_types` -- external links, where the portal row is a pointer to
    a file on someone else's host and the modification date is the edit date of
    the POINTER. On dublin_core_remaining 35,277 of those 36,316 rows carry a
    Date Modified NEWER than their own data, by a median of 19 years, so scoring
    them on it reads a metadata touch as a refresh. Scoring them on the data's
    last date asks what was actually meant: is this data current.

    Applied to liveness AND punctuality, because a pointer edit answers neither
    question. Note the direction of the correction -- these rows generally get
    LESS fresh, not more.

    Falls back to Date Modified when there is no usable dataset end date, rather
    than dropping the row's freshness signals: a stale date is still evidence.
    `freshness_basis` in the output says which of the two every row used.
    """
    data_end = dataset_last_date(df, min_start_year)
    prefer_data = df["resource_type"].isin(dataset_date_types)
    use_data = prefer_data & data_end.notna()

    date = df["date_modified"].mask(use_data, data_end)

    # Last write wins, so the order is precedence lowest-first.
    basis = pd.Series("metadata_modified", index=df.index)
    basis[prefer_data] = "no_dataset_date"
    basis[use_data] = "dataset_last_date"
    return date, data_end, basis


def signal_liveness(dates, as_of, half_life):
    """Exponential decay on days since last refresh: 0.5 ** (days/half_life).

    Decay rather than min-max because the age distribution is not spread out:
    92.5% of dublin_core_remaining was modified 2+ years ago, so min-max would
    hand almost the whole [0,1] range to distinctions inside the stale bulk and
    crowd the live tail at the top. Decay is absolute, so the live rows separate
    cleanly and the 2021 bulk-edit cohort lands near zero on its own.

    Rows dated after `as_of` (clock skew, scoring against a past date, or a
    dataset whose data runs into the future) saturate at 1.0 rather than scoring
    above it.

    Takes `freshness_date`'s output rather than reading `date_modified` itself,
    because on the external-link resource types that date is the data's own last
    date instead.
    """
    days = (pd.Timestamp(as_of) - dates).dt.days
    live = np.power(0.5, days / half_life)
    return live.clip(upper=1.0).where(dates.notna()), days


def signal_punctuality(days_stale, df):
    """Did this refresh inside its own declared period? 1.0 yes, 0.0 no, NaN n/a.

    Binary, not graded, because liveness already carries how-stale as a gradient
    -- grading this too would just double-count it. Late is a hard 0 rather than
    NaN on purpose: a monthly dataset that missed its month is real evidence,
    not absent evidence.

    Gated on field_from_api. A dataset nobody promised to auto-refresh should
    not be marked down for not auto-refreshing; those rows score NaN and their
    weight redistributes across the other four signals.

    The gate accepts a small set of truthy spellings rather than the literal
    '1' alone: the column is free-text VARCHAR, other tables in this database
    already carry the string 'NULL' in it, and utils/kpi_calculator.py expects
    'TRUE'/'FALSE'. A stricter test would silently score every row NaN if the
    upstream backfill lands a different spelling, which looks identical to
    "no API datasets" in the output.

    `days_stale` is days since `freshness_date`, so on the external-link
    resource types the question asked is "is the DATA inside its declared
    period", not "was the pointer edited recently".
    """
    # NaN here means "not auditable" and must stay NaN -- `fillna` would quietly
    # turn all 550 unauditable rows into scored (mostly late) ones. The floor
    # only applies to cadences that ARE mapped.
    expected = df["cadence"].map(cadence_days)
    expected = expected.where(expected.isna(), expected.clip(lower=run_interval_days))

    token = df["from_api"].str.lower()
    is_api = token.isin(api_true)
    is_blank = token.isin(api_blank)
    has_date = days_stale.notna()
    scored = is_api & has_date & expected.notna()

    punctual = pd.Series(np.nan, index=df.index)
    punctual[scored] = (days_stale[scored] <= expected[scored]).astype(float)

    # Why the check did or did not apply, so a 0 (missed its window) never gets
    # read as a NaN (did not apply) in the CSV.
    #
    # These are mask overwrites, not an if/elif chain: the LAST write wins, so
    # the order below is precedence lowest-first. Effective precedence is
    # on_time/late > from_api_blank > not_from_api > no_modified_date >
    # cadence_not_auditable -- i.e. a row that is not API-fed reads as
    # `not_from_api` even if it also has no date, because that is the more
    # informative reason. Reordering these lines changes which reason surfaces.
    # `no_modified_date` keeps its name for continuity with the CSVs already
    # produced, but it now means "no freshness date at all" -- no Date Modified,
    # and, on the external-link types, no dataset end date to stand in for it.
    flag = pd.Series("cadence_not_auditable", index=df.index)
    flag[~has_date] = "no_modified_date"
    flag[~is_api & ~is_blank] = "not_from_api"
    flag[is_blank] = "from_api_blank"
    flag[scored] = np.where(punctual[scored] == 1.0, "on_time", "late")

    return punctual, expected, flag


def combine(sig):
    """Weighted sum, with a missing signal's weight redistributed proportionally."""
    w = pd.DataFrame(
        {k: np.where(sig[k].notna(), weights[k], 0.0) for k in weights},
        index=sig.index,
    )
    total = w.sum(axis=1)
    contrib = sum(w[k] * sig[k].fillna(0.0) for k in weights)
    return (contrib / total).where(total > 0)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--db", default=default_db,
                   help=f"DuckDB file path, or 'pg' / a postgres:// URL to use "
                        f"Postgres with credentials from the environment "
                        f"(default: {default_db}, or $HVD_DB)")
    p.add_argument("--table", default="dublin_core_remaining",
                   help="Profile name from `tables` in this file -- NOT "
                        "necessarily the SQL relation name, which a profile can "
                        "override with its 'table' key. Known: "
                        + ", ".join(sorted(tables)))
    p.add_argument("--print-sql", action="store_true",
                   help="Print the SELECT this run would issue, plus the "
                        "resolved backend, and exit without connecting. Use it "
                        "to sanity-check a freshly edited profile")
    p.add_argument("--out", default=default_out)
    p.add_argument("--as-of", default=str(date.today()))
    p.add_argument("--ministry-departments", nargs="+", default=None,
                   help="Restrict to these ministry_department values (exact match)")
    p.add_argument("--limit", type=int, default=None,
                   help="Read at most N rows (SQL LIMIT, applied after "
                        "--ministry-departments and before --api-only). For "
                        "smoke tests: signals and a percentile cut are normalised "
                        "over the rows loaded, so scores are not comparable to a "
                        "full run")
    p.add_argument("--api-only", action="store_true",
                   help="Score only API-fed rows (field_from_api in "
                        f"{sorted(api_true)}), instead of scoring "
                        "everything and gating punctuality alone. Note this also "
                        "narrows a percentile cut, which is taken over the loaded "
                        "rows: top 10%% of the 957 API rows is 0.35, of the whole "
                        "table 0.40")
    p.add_argument("--cut-mode", choices=("percentile", "absolute"), default="percentile",
                   help="How to pick candidates. 'absolute' is the prod setting: a "
                        "percentile cut cannot move in aggregate, so the candidate "
                        "count would never change month to month")
    p.add_argument("--cut-value", type=float, default=5.0,
                   help="Top N%% for percentile mode (computed over the rows actually "
                        "loaded, so --ministry-departments and --api-only both move it), "
                        "or the score threshold for absolute mode")
    p.add_argument("--clip-pct", type=float, default=99.0,
                   help="Winsorise signal upper tails at this percentile")
    p.add_argument("--half-life", type=float, default=half_life_days,
                   help="Days after which liveness halves")
    p.add_argument("--min-start-year", type=int, default=1950,
                   help="Temporal starts before this are treated as unparseable. "
                        "Doubles as the floor on a dataset's own end date, which "
                        f"is what freshness is measured from for resource type "
                        f"{'/'.join(sorted(dataset_date_types))}")
    args = p.parse_args()
    if args.limit is not None and args.limit < 1:
        p.error("--limit must be a positive integer")

    if args.table not in tables:
        raise SystemExit(
            f"No profile for table {args.table!r}; known: {', '.join(sorted(tables))}"
        )

    if args.print_sql:
        backend = "postgres" if is_postgres(args.db) else f"duckdb file {args.db}"
        print(f"-- backend: {backend}")
        if is_postgres(args.db):
            # Redact: a DSN assembled from the environment carries a password.
            dsn = pg_dsn() if args.db in pg_aliases else args.db
            print("-- dsn:     " + redact(dsn))
        print(build_sql(args.table, args.db, args.ministry_departments, args.limit))
        return

    df = load(args.db, args.table, args.ministry_departments, args.limit)
    if args.api_only:
        # Same `api_true` set signal_punctuality gates on, not a literal '1'.
        # A Postgres boolean cast to ::TEXT is 'true', so a '1' test here would
        # select zero rows and the run would die at "Nothing to score." -- on
        # the exact invocation the README calls the production shape.
        df = df[df["from_api"].str.lower().isin(api_true)].reset_index(drop=True)
    print(f'Loaded {len(df)} rows from "{args.table}"'
          + (f" (--limit {args.limit})" if args.limit else "")
          + (" (API-fed rows only)" if args.api_only else ""))
    if df.empty:
        raise SystemExit("Nothing to score.")

    demand, months, dcount, dcount_source = signal_demand(
        df, args.as_of, args.clip_pct)
    temporal, depth, temporal_flag = signal_temporal(
        df, args.clip_pct, args.min_start_year)
    geo, state, coll_states = signal_geo(df)
    fresh_date, data_end, freshness_basis = freshness_date(df, args.min_start_year)
    liveness, days_stale = signal_liveness(fresh_date, args.as_of, args.half_life)
    punctuality, expected, punctuality_flag = signal_punctuality(days_stale, df)

    sig = pd.DataFrame({
        "demand": demand, "temporal": temporal, "geo": geo,
        "liveness": liveness, "punctuality": punctuality,
    })
    score = combine(sig)

    # How much evidence a score rests on. Weight redistribution means a row with
    # one saturated signal can score high on thin evidence; this surfaces the
    # thinness for the reviewer rather than suppressing it.
    n_signals = sig.notna().sum(axis=1)
    signals_present = sig.notna().apply(
        lambda r: "+".join(c for c in sig.columns if r[c]) or "none", axis=1
    )

    if args.cut_mode == "absolute":
        cut = args.cut_value
    else:
        cut = np.nanpercentile(score, 100 - args.cut_value)

    out = pd.DataFrame({
        "nid": df["nid"],
        "Title": df["Title"],
        "Collection": df["Collection"],
        "ministry": df["Publisher[ministry_department]"],
        "resource_type": df["resource_type"],
        "downloads": pd.to_numeric(df["ogdp_download_count"], errors="coerce"),
        "views": pd.to_numeric(df["ogdp_view_count"], errors="coerce"),
        "api_requests": pd.to_numeric(df["request_count_raw"], errors="coerce"),
        "demand_count": dcount,
        "demand_count_source": dcount_source,
        "date_issued": df["date_issued"],
        "months_since_issue": months.round(1),
        "date_modified": df["date_modified"],
        "date_dataset_end": data_end,
        "date_freshness": fresh_date,
        "freshness_basis": freshness_basis,
        "days_since_freshness": days_stale,
        "declared_cadence": df["cadence"],
        "expected_period_days": expected,
        "field_from_api": df["from_api"],
        "punctuality_flag": punctuality_flag,
        "temporal_span_years": depth,
        "temporal_flag": temporal_flag,
        "state_ut": state,
        "collection_states_covered": coll_states,
        "hvd_demand": demand.round(4),
        "hvd_temporal": temporal.round(4),
        "hvd_geo": geo.round(4),
        "hvd_liveness": liveness.round(4),
        "hvd_punctuality": punctuality,
        "hvd_score": score.round(4),
        "hvd_candidate": (score >= cut).astype(int),
        "n_signals": n_signals,
        "signals_present": signals_present,
    }).sort_values(["hvd_score", "n_signals"], ascending=[False, False])

    out.to_csv(args.out, index=False)

    print("\nSignal availability (missing -> weight redistributed):")
    for k in weights:
        n = int(sig[k].notna().sum())
        print(f"  {k:12s} {n:6d}/{len(df)}  ({100 * n / len(df):5.1f}%)")

    print("\nResource-type rules (demand count / freshness date):")
    for name, s in (("demand count", dcount_source), ("freshness", freshness_basis)):
        for f, n in s.value_counts().items():
            print(f"  {name:14s} {f:20s} {n:6d}")
    # The substitution puts two counters on one min-max, so print both scales:
    # a request count far above the download distribution would saturate demand
    # for every row of those types, and that should be visible, not inferred.
    on_req = dcount_source == "api_requests"
    if on_req.any():
        dl = dcount[dcount_source == "downloads"].dropna()
        rq = dcount[on_req].dropna()
        if len(dl) and len(rq):
            print(f"  scale check    downloads median {dl.median():.0f}, "
                  f"p99 {np.nanpercentile(dl, 99):.0f}  |  requests median "
                  f"{rq.median():.0f}, max {rq.max():.0f}")

    print("\nPunctuality:")
    for f, n in punctuality_flag.value_counts().items():
        print(f"  {f:24s} {n:6d}")

    print("\nScore distribution:")
    print(score.describe().round(4).to_string())

    print(f"\n{args.cut_mode} cut = {cut:.4f} -> "
          f"{int(out['hvd_candidate'].sum())} candidates")

    print("\nEvidence depth of candidates:")
    cand = out[out.hvd_candidate == 1]
    for combo, n in cand["signals_present"].value_counts().items():
        print(f"  {combo:48s} {n:5d}  ({100 * n / len(cand):5.1f}%)")

    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
