"""
HVD Pulse -- monthly High Value Dataset scoring with a freshness check.

    hvd_score = 0.20*demand + 0.25*temporal + 0.15*geo
              + 0.30*api + 0.10*liveness

`api` is 1.0 when `field_from_api` is truthy, 0.0 otherwise -- see `signal_api`
for why it is that column and not `is_api_available`, which means the opposite.
Punctuality is still computed and written to the CSV but carries no weight in
this variant; it is gated on the same flag, so weighting both double-counts it.

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

Four sources, same scoring code:

  DuckDB      --db path/to/metadata.db          (local snapshot)
  Postgres    --db pg                           (credentials from the environment)
  Excel       --xlsx dublin_core_metadata.xlsx  (calamine + a Parquet cache)
  Portal      --portal                          (live data.gov.in backend)

Each loader ends at the same normalised frame, so nothing downstream of `load*`
knows or cares where the rows came from. `--table all` pools the three
dublin_core lots into one frame, so every min-max, percentile clip and the cut
itself are taken over all of them together.

--portal is the one with real caveats, because the endpoint is narrower than the
database export. It carries no spatial field at all and a data period on only
~6% of rows, so `geo` reduces to the State/UT-wise title rule and `temporal` is
missing on most rows; both go NaN and `combine` redistributes their weight. It
also needs TWO endpoints: the resource list carries an `ogdp_download_count`
that reads 0 where the analytics endpoint reports real downloads, so the counts
feeding `demand` come from one analytics call per resource. That is ~57 req/s at
16 workers -- about 1.7 hours for all 354,995 -- which is why the result is
cached to Parquet and why the counts are as-of that cache, not as-of the run.

Those analytics counts are not tied to --portal. `--stats` overlays them on a
database or Excel run as well, keyed on `nid`, so `--table all --stats` scores
the three lots on the portal's current views/downloads instead of the snapshot
columns in the table -- and gives dublin_core_lot3, which has no count columns
at all, a demand signal. On by default for --portal (`--no-stats` turns it off)
and off by default everywhere else, because a database run is otherwise offline
and a pure function of the table.

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
    python hvd_scoring/hvd_score_v2.py --db transformation/metadata.db
    python hvd_scoring/hvd_score_v2.py --db <path> --table dublin_core_metadata
    python hvd_scoring/hvd_score_v2.py --db <path> --limit 1000

    python hvd_scoring/hvd_score_v2.py --table all --extra-cuts 10 1
    python hvd_scoring/hvd_score_v2.py --table all --stats        # live counts

    python hvd_scoring/hvd_score_v2.py --xlsx
    python hvd_scoring/hvd_score_v2.py --xlsx /path/to/export.xlsx --sheet Sheet1

    python hvd_scoring/hvd_score_v2.py --portal --limit 2000
    python hvd_scoring/hvd_score_v2.py --portal --no-stats   # fast, wrong counts

    export PGHOST=... PGDATABASE=... PGUSER=... PGPASSWORD=...
    python hvd_scoring/hvd_score_v2.py --db pg --table postgres
    python hvd_scoring/hvd_score_v2.py --db pg --table postgres --print-sql

    python hvd_scoring/hvd_score_v2.py --db <path> --api-only \
        --cut-mode absolute --cut-value 0.42
"""

import argparse
import os
import re
import sys
import time
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
#     HVD_DB=pg python hvd_scoring/hvd_score_v2.py --table postgres
default_db = os.environ.get("HVD_DB", str(repo_root / "transformation" / "metadata.db"))
default_out = str(repo_root / "hvd_scoring" / "hvd_scores_v2.csv")

# What `--table all` pools, in output order.
all_tables = ["dublin_core_metadata", "dublin_core_remaining", "dublin_core_lot3"]

# --- xlsx source -------------------------------------------------------------
default_xlsx = os.environ.get("HVD_XLSX", str(repo_root / "dublin_core_metadata.xlsx"))
default_sheet = "Sheet1"          # Sheet2 of that workbook exists but is empty
default_cache_dir = str(repo_root / "hvd_scoring" / ".cache")
cadence_uri_prefix = "http://purl.org/cld/freq/"

# Workbook column -> the internal name the signal functions read. Same contract
# as a `tables` profile's SELECT aliases, just expressed as a dict.
xlsx_column_map = {
    "nid": "nid",
    "Title": "Title",
    "Collection": "Collection",
    "Publisher[ministry_department]": "Publisher[ministry_department]",
    "Publisher[state_department]": "Publisher[state_department]",
    "Spatial Coverage": "Spatial Coverage",
    "Temporal Coverage": "temporal_raw",
    "ogdp_download_count": "ogdp_download_count",
    "ogdp_view_count": "ogdp_view_count",
    "Date Created": "date_created_raw",
    "Date Issued": "date_issued_raw",
    "Date Modified": "modified_raw",
    "Accrual Periodicity": "cadence_raw",
    "field_from_api": "field_from_api",
    "is_api_available": "api_available_raw",
    "Accrual Method": "resource_type_raw",
    "api_request_count": "request_count_raw",
}

# Absent -> the rule or column goes quiet rather than raising. The first three
# drive the resource-type rules and cost no signal; api_available_raw only feeds
# a diagnostic output column.
optional_internal = ("resource_type_raw", "request_count_raw", "data_end_raw",
                     "api_available_raw")

# --- portal source -----------------------------------------------------------
# data.gov.in's own backend. Two endpoints, because they disagree: the list
# endpoint carries an `ogdp_download_count` that reads 0 on rows the analytics
# endpoint reports real downloads for (nid 605223332: list 0, analytics 33), so
# the counts that feed `demand` are taken from analytics unless --no-stats.
# The analytics endpoint is keyed on nid alone, so `--stats` reads it for the
# database and Excel sources too -- see `overlay_portal_stats`.
portal_list_url = "https://www.data.gov.in/backend/dmspublic/v1/resources"
portal_stats_url = "https://www.data.gov.in/backend/analytics/v1/stats/resources/{nid}"
portal_page_size = 1000      # 5000 works but costs ~37s a page; 1000 is ~5s
portal_workers = 16          # ~57 req/s against analytics, measured, no errors
portal_user_agent = "hvd-score/1.0 (CivicDataLab; NIC metadata curation)"

# Portal field -> internal name. Every value arrives wrapped in a one-element
# list (Solr style) and most fields are SPARSE -- present only when populated --
# so everything here is read with .get() and defaults to blank.
#
# Three columns the DuckDB profiles have simply do not exist on this endpoint:
#   Spatial Coverage      absent entirely -> geo falls back to the State/UT-wise
#                         title rule alone, and is NaN for everything else.
#   Temporal Coverage     only data_time_period_from/to, on ~6% of rows.
#   Collection            catalog_title stands in; it is the portal's own
#                         grouping and is populated on every row.
portal_field_map = {
    "nid": "nid",
    "uuid": "uuid",
    "title": "Title",
    "catalog_title": "Collection",
    "ministry_department": "Publisher[ministry_department]",
    "state_department": "Publisher[state_department]",
    "ogdp_download_count": "ogdp_download_count",
    "ogdp_view_count": "ogdp_view_count",
    "api_request_count": "request_count_raw",
    "field_from_api": "field_from_api",
    "is_api_available": "api_available_raw",
    "field_resource_type": "resource_type_raw",
    "frequency": "cadence_raw",
    "created": "created_epoch",
    "published_date": "published_epoch",
    "changed": "changed_epoch",
    "data_time_period_from": "tp_from_epoch",
    "data_time_period_to": "tp_to_epoch",
}

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
    "demand": 0.20,
    "temporal": 0.25,
    "geo": 0.15,
    "api": 0.30,
    "liveness": 0.10,
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
            "Publisher[state_department]",
            "Collection",
            "Spatial Coverage",
            "Temporal Coverage" AS temporal_raw,
            ogdp_download_count,
            ogdp_view_count,
            COALESCE(NULLIF(trim("Date Created"), ''), "Date Issued") AS issued_raw,
            "Date Modified" AS modified_raw,
            "Accrual Periodicity" AS cadence_raw,
            field_from_api,
            is_api_available AS api_available_raw,
            "Accrual Method" AS resource_type_raw,
            data_time_period_to AS data_end_raw,
        ''',
        "temporal": "interval",
    },
    # Same shape as dublin_core_remaining -- Temporal Coverage is the same
    # interval form, Accrual Periodicity is plain text, data_time_period_to
    # drives the type-2 rule -- except lot3 has no ogdp_download_count,
    # ogdp_view_count, or api_request_count columns at all. Both counts stand
    # in as NULL, which pd.to_numeric/minmax carry through as NaN, so on the
    # table alone demand scores NaN for every row and `combine` redistributes
    # its weight across the other four signals rather than reading "no traffic"
    # as "no value". `--stats` is what gives these rows a demand signal: the
    # analytics endpoint answers for lot3 nids like any other.
    "dublin_core_lot3": {
        "ministry_col": '"Publisher[ministry_department]"',
        "select": '''
            nid,
            "Title",
            "Publisher[ministry_department]",
            "Publisher[state_department]",
            "Collection",
            "Spatial Coverage",
            "Temporal Coverage" AS temporal_raw,
            NULL AS ogdp_download_count,
            NULL AS ogdp_view_count,
            COALESCE(NULLIF(trim("Date Created"), ''), "Date Issued") AS issued_raw,
            "Date Modified" AS modified_raw,
            "Accrual Periodicity" AS cadence_raw,
            field_from_api,
            is_api_available AS api_available_raw,
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
            "Publisher[state_department]",
            "Spatial Coverage",
            "Temporal Coverage" AS temporal_raw,
            ogdp_download_count,
            ogdp_view_count,
            COALESCE(NULLIF(trim("Date Created"), ''), "Date Issued") AS issued_raw,
            "Date Modified" AS modified_raw,
            replace("Accrual Periodicity",
                    'http://purl.org/cld/freq/', '') AS cadence_raw,
            field_from_api,
            is_api_available AS api_available_raw,
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
            "Publisher[state_department]"::TEXT     AS "Publisher[state_department]",
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
            is_api_available::TEXT                 AS api_available_raw,
            "Accrual Method"::TEXT                AS resource_type_raw,
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
    # Missing column -> NaN signal -> weight redistributed, like any other signal.
    if "api_available_raw" not in df.columns:
        df["api_available_raw"] = np.nan
    df["api_available"] = as_text(df["api_available_raw"]).str.strip().str.lower()

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


# -------------------------------------------------------------- xlsx source ----

def read_workbook(xlsx, sheet):
    """Decode `sheet` of `xlsx` into a DataFrame of the mapped columns, as text.

    python_calamine first (~14s on the 77 MB workbook), openpyxl as a fallback
    (minutes). calamine is driven directly rather than through
    `pd.read_excel(engine="calamine")` because that engine needs pandas >= 2.2
    and this repo is on 2.1.3. Only the mapped columns are materialised: the
    sheet has 79 and the other 64 are pure memory cost.
    """
    t0 = time.perf_counter()
    try:
        from python_calamine import CalamineWorkbook
    except ImportError:
        return _read_openpyxl(xlsx, sheet, t0)

    book = CalamineWorkbook.from_path(str(xlsx))
    if sheet not in book.sheet_names:
        raise SystemExit(
            f"No sheet {sheet!r} in {xlsx}; found: {', '.join(book.sheet_names)}")
    rows = book.get_sheet_by_name(sheet).to_python(skip_empty_area=False)
    if not rows:
        raise SystemExit(f"Sheet {sheet!r} of {xlsx} is empty.")

    idx = _resolve_columns([str(h) for h in rows[0]], xlsx)
    df = pd.DataFrame({
        internal: [r[i] if i < len(r) else None for r in rows[1:]]
        for i, internal in idx.items()
    })
    print(f"Decoded {len(df):,} rows x {len(df.columns)} columns via calamine "
          f"in {time.perf_counter() - t0:.1f}s")
    return df


def _read_openpyxl(xlsx, sheet, t0):
    """Fallback path. Correct, just slow -- minutes on a workbook this size."""
    print("WARNING: python_calamine not installed; falling back to openpyxl, "
          "which takes minutes on a workbook this size.\n"
          "         pip install python-calamine", file=sys.stderr)
    raw = pd.read_excel(xlsx, sheet_name=sheet, dtype=str)
    idx = _resolve_columns([str(c) for c in raw.columns], xlsx)
    df = raw.iloc[:, list(idx)].copy()
    df.columns = [idx[i] for i in idx]
    print(f"Decoded {len(df):,} rows x {len(df.columns)} columns via openpyxl "
          f"in {time.perf_counter() - t0:.1f}s")
    return df


def _resolve_columns(header, xlsx):
    """{position -> internal name} for the mapped columns, or a clear exit.

    Reports every missing required column at once: finding out about them one
    re-run at a time, at ~14s a decode, is its own small tax.
    """
    pos, missing = {}, []
    for source, internal in xlsx_column_map.items():
        if source in header:
            pos[header.index(source)] = internal
        elif internal not in optional_internal:
            missing.append(source)
    if missing:
        raise SystemExit(
            f"{xlsx} is missing required column(s): {', '.join(missing)}.\n"
            f"Found {len(header)} columns; this expects a dublin_core export.")
    return pos


def xlsx_cache_path(xlsx, cache_dir):
    """Parquet cache key: workbook size + mtime.

    Content hashing a 77 MB file on a slow spinning external drive costs about
    as much as re-decoding it, so the key is the cheap stat-only pair instead.
    """
    st = Path(xlsx).stat()
    return Path(cache_dir) / f"{Path(xlsx).stem}.{st.st_size}-{int(st.st_mtime)}.parquet"


def read_cached(xlsx, sheet, cache_dir, use_cache=True, refresh=False):
    """`read_workbook`, memoised to Parquet.

    The cache holds the mapped columns AFTER text coercion, never raw Excel
    values: a raw object column mixing str and int is unwritable by Arrow,
    whereas the all-text frame round-trips exactly.
    """
    if not use_cache:
        return _as_all_text(read_workbook(xlsx, sheet))

    path = xlsx_cache_path(xlsx, cache_dir)
    if path.exists() and not refresh:
        t0 = time.perf_counter()
        try:
            df = pd.read_parquet(path)
            print(f"Loaded {len(df):,} rows from cache {path.name} "
                  f"in {time.perf_counter() - t0:.2f}s")
            return df
        except Exception as e:  # noqa: BLE001 - a bad cache must never be fatal
            print(f"Ignoring unreadable cache {path.name}: {e}", file=sys.stderr)

    df = _as_all_text(read_workbook(xlsx, sheet))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        print(f"Cached to {path}")
    except Exception as e:  # noqa: BLE001 - caching is an optimisation only
        print(f"Could not write cache ({e}); continuing.", file=sys.stderr)
    return df


def _as_all_text(df):
    """Every mapped column to str with nulls as '' -- the VARCHAR shape the
    DuckDB path hands the signals, and Parquet-safe in the same step."""
    return pd.DataFrame({c: as_text(df[c]) for c in df.columns})


def _normalise_temporal(tc):
    """`Temporal Coverage` -> the `start:YYYY;end:YYYY` the temporal signal reads.

    Auto-detected rather than declared per source: dublin_core_metadata stores
    it already in start/end form while dublin_core_remaining stores an ISO
    interval, and pointing --xlsx at the wrong one of those would otherwise
    score every row's temporal as missing without saying so.
    """
    tc = tc.fillna("").str.strip()
    if tc.str.contains(r"\d{4}-\d{2}-\d{2}\s*/", regex=True, na=False).any():
        print("Temporal Coverage read as ISO intervals (span by duration)")
        return from_interval(tc)
    print("Temporal Coverage read as start:YYYY;end:YYYY")
    return tc.where(tc != "", "None")


def load_xlsx(xlsx, sheet, cache_dir, use_cache=True, refresh=False,
              ministries=None, limit=None):
    """Read a workbook and normalise it into the columns the signals expect.

    Row filters run in the same order the SQL path applies them -- ministries,
    then limit -- so --limit keeps meaning "the first N of the selected
    ministries". --api-only is applied later, in main, exactly as it was.
    """
    df = read_cached(xlsx, sheet, cache_dir, use_cache, refresh)

    mcol = "Publisher[ministry_department]"
    if ministries:
        df = df[df[mcol].isin(list(ministries))]
    if limit:
        df = df.head(int(limit))
    df = df.reset_index(drop=True)

    # NULLIF(trim(...), '') -> fall back to Date Issued where Date Created is
    # blank, the same coalesce the SQL profiles do and for the same reason.
    created = df["date_created_raw"].str.strip()
    df["issued_raw"] = created.where(created != "", df["date_issued_raw"])
    df["date_issued"] = to_naive_datetime(df["issued_raw"])
    df["date_modified"] = to_naive_datetime(df["modified_raw"])
    df["temporal_coverage"] = _normalise_temporal(df["temporal_raw"])

    df["cadence"] = (df["cadence_raw"].str.replace(cadence_uri_prefix, "", regex=False)
                     .str.strip().str.lower())
    df["Collection"] = as_text(df["Collection"])
    df["from_api"] = as_text(df["field_from_api"]).str.strip()

    for col in optional_internal:
        if col not in df.columns:
            df[col] = np.nan
    df["api_available"] = as_text(df["api_available_raw"]).str.strip().str.lower()
    df["resource_type"] = as_text(df["resource_type_raw"]).str.strip()
    return df


# ------------------------------------------------------------ portal source ----

def portal_session():
    """A pooled requests Session. Not optional: the analytics endpoint answers
    in ~1.6s on a reused connection and ~10s (and erratically, with outright
    failures) on a fresh one per call, so connection reuse is the single
    difference between a run that finishes and one that does not."""
    try:
        import requests
    except ImportError:
        raise SystemExit("--portal needs the requests package: pip install requests")
    s = requests.Session()
    s.headers["User-Agent"] = portal_user_agent
    return s


def _portal_get(session, url, params=None, tries=3, timeout=60):
    """One GET with a bounded retry. Returns the decoded JSON, or None."""
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.ok:
                return r.json()
            # 4xx other than 429 will not fix itself; stop early.
            if r.status_code < 500 and r.status_code != 429:
                return None
        except Exception:  # noqa: BLE001 - transport errors are the retry's job
            pass
        if attempt < tries - 1:
            time.sleep(1.5 * (attempt + 1))
    return None


def _one(v):
    """Portal values arrive wrapped in a one-element list; unwrap to a scalar."""
    if isinstance(v, list):
        return v[0] if v else None
    return v


def enrich_from_xlsx(df, xlsx, sheet, cache_dir, use_cache=True, refresh=False):
    """Fill a portal frame's Spatial / Temporal Coverage from an Excel export.

    The portal endpoint has no spatial field and a data period on ~6% of rows,
    so on its own `geo` collapses to the State/UT-wise title rule and `temporal`
    is missing almost everywhere. An export that does carry both can be joined
    back on `nid`, which is the portal's own node id on both sides.

    Only the two coverage columns are taken. `Collection` deliberately stays the
    portal's `catalog_title` for every row: geo groups by it to count distinct
    States/UTs, and mixing two collection namespaces in one groupby could fold
    unrelated families together where a name happened to collide.

    Coverage is partial and uneven. dublin_core_remaining holds 117,721 of the
    portal's 354,995 resources, clustered in older publication batches rather
    than as a clean cutoff -- sampled by offset, the match rate runs 0% at
    230,000 and 100% at 320,000. A newest-first `--limit` run therefore matches
    almost nothing; the enrichment pays off on a full pull. The match rate is
    printed every run rather than left to be inferred from the signal table.
    """
    ex = read_cached(xlsx, sheet, cache_dir, use_cache, refresh)
    for col in ("nid", "Spatial Coverage", "temporal_raw"):
        if col not in ex.columns:
            raise SystemExit(f"{xlsx} has no {col!r} column to enrich from.")
    ex = ex[["nid", "Spatial Coverage", "temporal_raw"]].copy()
    ex["nid"] = ex["nid"].astype(str).str.strip()
    ex = ex[ex["nid"] != ""].drop_duplicates("nid").set_index("nid")

    matched = df["nid"].isin(ex.index)
    sp = df["nid"].map(ex["Spatial Coverage"]).fillna("")
    tc = df["nid"].map(ex["temporal_raw"]).fillna("")

    df["Spatial Coverage"] = sp.where(sp.str.strip() != "", df["Spatial Coverage"])
    # Normalise the export's own encoding before choosing between the two, so a
    # workbook storing start:YYYY;end:YYYY and a portal row storing an ISO
    # interval can be mixed in one column without either being misread.
    ex_tc = _normalise_temporal(tc)
    df["temporal_coverage"] = ex_tc.where(ex_tc != "None", df["temporal_coverage"])
    df["temporal_raw"] = tc.where(tc.str.strip() != "", df["temporal_raw"])

    print(f"Enriched from {Path(xlsx).name}: {int(matched.sum()):,}/{len(df):,} rows "
          f"matched by nid ({100 * matched.mean():.1f}%)")
    return df


def portal_rows(session, limit=None, page_size=portal_page_size, ministries=None,
                offset=0):
    """Page the resources endpoint. Returns the raw row dicts.

    `--ministry-departments` is pushed down as one paged stream per ministry
    rather than filtered client-side, because the alternative is pulling all
    354,995 rows to keep a few thousand.
    """
    streams = [{"filters[ministry_department]": m} for m in ministries] if ministries \
        else [{}]
    rows = []
    for extra in streams:
        start = offset
        while limit is None or len(rows) < limit:
            want = page_size if limit is None else min(page_size, limit - len(rows))
            params = {"format": "json", "limit": want, "offset": start,
                      "sort[published_date]": "desc", **extra}
            d = _portal_get(session, portal_list_url, params, timeout=180)
            if d is None:
                print(f"  list request failed at offset {start}; stopping early",
                      file=sys.stderr)
                break
            page = d.get("data", {}).get("rows", []) or []
            if not page:
                break
            rows.extend(page)
            start += len(page)
            total = d.get("total")
            print(f"  fetched {len(rows):,}" + (f" of {total:,}" if total else ""),
                  end="\r", flush=True)
            if total is not None and start >= total:
                break
    print()
    return rows


def portal_stats(nids, session, workers=portal_workers, cache_dir=None,
                 use_cache=True, refresh=False):
    """views/download per nid from the analytics endpoint, threaded and cached.

    One request per resource is the only interface there is, so the cost is
    linear: ~57 req/s at 16 workers, about 1.7 hours for the whole portal. The
    Parquet cache makes a re-run of the same corpus nearly free, which is what
    makes iterating on the scoring practical at all. Counts are therefore
    as-of the cache, not as-of the run -- pass --refresh to re-fetch.

    The cache is one file shared by every source and table, so --refresh
    re-fetches the nids of THIS run and leaves the rest of it in place:
    refreshing one lot must not throw away the hour spent fetching the others.
    """
    from concurrent.futures import ThreadPoolExecutor

    path = Path(cache_dir) / "portal_stats.parquet" if cache_dir else None
    have = {}
    if path is not None and use_cache and path.exists():
        try:
            c = pd.read_parquet(path)
            have = {str(r.nid): (r.views, r.download) for r in c.itertuples()}
            print(f"Loaded {len(have):,} cached stat rows from {path.name}")
        except Exception as e:  # noqa: BLE001 - a bad cache must never be fatal
            print(f"Ignoring unreadable stats cache: {e}", file=sys.stderr)

    todo = [n for n in nids if refresh or n not in have]
    if todo:
        print(f"Fetching analytics for {len(todo):,} resources "
              f"({workers} workers, ~{len(todo) / 57 / 60:.1f} min at measured rate)")
        t0 = time.perf_counter()
        done = [0]

        def fetch(nid):
            d = _portal_get(session, portal_stats_url.format(nid=nid), timeout=45)
            done[0] += 1
            if done[0] % 500 == 0:
                rate = done[0] / max(time.perf_counter() - t0, 1e-9)
                print(f"  {done[0]:,}/{len(todo):,}  {rate:.0f} req/s",
                      end="\r", flush=True)
            c = (d or {}).get("data", {}).get("count") or {}
            return c.get("views"), c.get("download")

        with ThreadPoolExecutor(workers) as ex:
            for nid, got in zip(todo, ex.map(fetch, todo)):
                # A failed re-fetch must not blank a count an earlier run got.
                if got[0] is not None or nid not in have:
                    have[nid] = got
        miss = sum(1 for n in todo if have.get(n, (None, None))[0] is None)
        print(f"\nFetched in {time.perf_counter() - t0:.0f}s; "
              f"{miss:,} returned no counts")

        if path is not None and use_cache:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                pd.DataFrame([{"nid": k, "views": v[0], "download": v[1]}
                              for k, v in have.items()]).to_parquet(path, index=False)
                print(f"Cached stats to {path}")
            except Exception as e:  # noqa: BLE001 - caching is an optimisation
                print(f"Could not write stats cache ({e}); continuing.",
                      file=sys.stderr)
    return have


def overlay_portal_stats(df, workers=portal_workers, cache_dir=None,
                         use_cache=True, refresh=False):
    """Replace a frame's view/download counts with the analytics endpoint's.

    Source-independent: the endpoint is keyed on `nid`, the portal's own node
    id, and that is what the database tables, the Excel exports and the portal
    listing all carry. So the same call that corrects the list endpoint's
    under-reported downloads on a --portal run also swaps a table's snapshot
    counts for current ones, and is the only source of counts
    dublin_core_lot3 has.

    Only overwrites where analytics actually answered: a failed call must not
    turn a real count into a null, so such a row keeps whatever its source
    carried. `--table all` can hand the same nid in twice (one sits in both
    lot 2 and lot 3, and lot 3 repeats one of its own), hence the de-duplication
    before fetching.
    """
    keys = as_text(df["nid"]).str.strip()
    stats = portal_stats([n for n in dict.fromkeys(keys) if n], portal_session(),
                         workers, cache_dir, use_cache, refresh)
    got = keys.map(stats)
    views = got.map(lambda t: t[0] if isinstance(t, tuple) else None)
    dls = got.map(lambda t: t[1] if isinstance(t, tuple) else None)
    df["ogdp_view_count"] = views.where(views.notna(), df["ogdp_view_count"])
    df["ogdp_download_count"] = dls.where(dls.notna(), df["ogdp_download_count"])

    answered = views.notna() | dls.notna()
    print(f"Analytics counts applied to {int(answered.sum()):,}/{len(df):,} rows "
          f"({100 * answered.mean():.1f}%); the rest keep their source counts")
    return df


def load_portal(limit=None, ministries=None, page_size=portal_page_size,
                cache_dir=None, use_cache=True, refresh=False, offset=0,
                enrich_xlsx=None, sheet=default_sheet):
    """Pull the corpus from data.gov.in and normalise it like the other sources.

    The counts this returns are the list endpoint's own, which under-report
    downloads; `main` overlays the analytics ones afterwards unless --no-stats.

    What this source cannot give you, and why the run summary will show it:
      geo       there is no spatial field on the endpoint at all, so geo comes
                from the State/UT-wise title rule alone and is NaN otherwise.
      temporal  only data_time_period_from/to, populated on about 6% of rows.
    Both are NaN rather than 0, so `combine` redistributes their weight -- the
    scores stay meaningful, they just rest on fewer signals, which `n_signals`
    and `signals_present` record per row. Passing `enrich_xlsx` fills both from
    an export where the nid matches; see `enrich_from_xlsx`.
    """
    session = portal_session()
    print(f"Fetching resource metadata from {portal_list_url}")
    raw = portal_rows(session, limit, page_size, ministries, offset)
    if not raw:
        raise SystemExit("The portal returned no rows.")

    df = pd.DataFrame({
        internal: [_one(r.get(field)) for r in raw]
        for field, internal in portal_field_map.items()
    })
    df["nid"] = as_text(df["nid"]).str.strip()

    # Every date on this endpoint is Unix epoch seconds.
    for src, dst in (("created_epoch", "date_created"),
                     ("published_epoch", "date_published"),
                     ("changed_epoch", "date_modified"),
                     ("tp_from_epoch", "tp_from"), ("tp_to_epoch", "tp_to")):
        df[dst] = pd.to_datetime(pd.to_numeric(df[src], errors="coerce"),
                                 unit="s", errors="coerce")

    # Date Created, not published_date, is the demand-age basis -- the same
    # choice the SQL profiles make, for the same reason.
    df["date_issued"] = df["date_created"].fillna(df["date_published"])

    # Rebuild an ISO interval so `from_interval` measures the span by duration;
    # year labels alone double-count April-March fiscal years.
    iso = lambda s: s.dt.strftime("%Y-%m-%d")  # noqa: E731
    both = df["tp_from"].notna() & df["tp_to"].notna()
    df["temporal_raw"] = np.where(both, iso(df["tp_from"]) + "/" + iso(df["tp_to"]), "")
    df["temporal_coverage"] = from_interval(pd.Series(df["temporal_raw"], index=df.index))
    df["data_end_raw"] = df["tp_to"]

    # No spatial field exists on this endpoint; blank feeds parse_state a None.
    df["Spatial Coverage"] = ""
    if "Publisher[state_department]" not in df:
        df["Publisher[state_department]"] = ""
    for col in ("Title", "Collection", "Publisher[ministry_department]",
                "Publisher[state_department]"):
        df[col] = as_text(df[col])
    df["cadence"] = as_text(df["cadence_raw"]).str.strip().str.lower()
    df["from_api"] = as_text(df["field_from_api"]).str.strip()
    df["api_available"] = as_text(df["api_available_raw"]).str.strip().str.lower()
    df["resource_type"] = as_text(df["resource_type_raw"]).str.strip()

    if enrich_xlsx:
        df = enrich_from_xlsx(df, enrich_xlsx, sheet, cache_dir, use_cache, refresh)
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


def signal_api(df):
    """1.0 if the dataset is fed from an API, 0.0 if not.

    Reads `field_from_api`, NOT `is_api_available`. The latter looks like the
    right column and is the exact opposite of it: it is set on files the portal
    hosts and serves its own generated endpoint over, and is 0 on every one of
    the 36 resource-type-6 (API-served) rows, all of which have field_from_api
    1. Scored on is_api_available the type-6 cohort averaged 0.0 on this signal
    while plain uploaded files averaged 0.65 -- backwards.

    Absence scores 0, not NaN: field_from_api is a flag the portal sets when a
    dataset is API-fed, so blank/NULL means "not API-fed" rather than "unknown".
    NaN would redistribute the weight and hand the 52,231 blank rows a
    systematic advantage over the 64,533 explicit zeros.
    """
    return df["from_api"].str.lower().isin(api_true).astype(float)


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
                        + ", ".join(sorted(tables))
                        + "; or 'all' to score " + ", ".join(all_tables)
                        + " as one pool")
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
    p.add_argument("--extra-cuts", type=float, nargs="*", default=[],
                   help="Additional top-N%% percentile cuts, written as extra "
                        "hvd_candidate_pXX columns (percentile = 100-N) alongside "
                        "the main --cut-value one")
    p.add_argument("--clip-pct", type=float, default=99.0,
                   help="Winsorise signal upper tails at this percentile")
    p.add_argument("--half-life", type=float, default=half_life_days,
                   help="Days after which liveness halves")
    p.add_argument("--min-start-year", type=int, default=1950,
                   help="Temporal starts before this are treated as unparseable. "
                        "Doubles as the floor on a dataset's own end date, which "
                        f"is what freshness is measured from for resource type "
                        f"{'/'.join(sorted(dataset_date_types))}")

    src = p.add_argument_group(
        "input source", "Default is the DuckDB/Postgres --db. These pick another.")
    src.add_argument("--xlsx", nargs="?", const=default_xlsx, default=None,
                     metavar="PATH",
                     help="Score an Excel export instead of the database. Bare "
                          f"--xlsx uses {default_xlsx} or $HVD_XLSX. Combined "
                          "with --portal it instead fills Spatial and Temporal "
                          "Coverage on the portal rows whose nid it carries")
    src.add_argument("--offset", type=int, default=0,
                     help="Start the --portal listing at this offset. Rows are "
                          "newest-first, and an export's coverage sits in the "
                          "older batches, so a small --limit from offset 0 will "
                          "match almost nothing to enrich against")
    src.add_argument("--sheet", default=default_sheet,
                     help=f"Worksheet to read (default: {default_sheet})")
    src.add_argument("--portal", action="store_true",
                     help="Pull metadata live from data.gov.in instead of the "
                          "database. Note that endpoint carries no spatial field "
                          "and a data period on ~6%% of rows, so geo and temporal "
                          "are mostly NaN and their weight redistributes")
    src.add_argument("--page-size", type=int, default=portal_page_size,
                     help=f"Rows per --portal list request (default: {portal_page_size})")
    src.add_argument("--stats", dest="stats", action="store_true", default=None,
                     help="Take view/download counts from the portal's analytics "
                          "endpoint, one call per nid, instead of the source's own "
                          "columns. Already the default for --portal; pass it to "
                          "do the same on a database or --xlsx run. ~57 req/s, "
                          "cached, so the first full `--table all` takes ~1.7h "
                          "and re-runs are nearly free")
    src.add_argument("--no-stats", dest="stats", action="store_false",
                     help="Skip the per-resource analytics calls on a --portal "
                          "run and use the list endpoint's own counts, which "
                          "under-report downloads (0 where analytics reports "
                          "33). Fast but wrong")
    src.add_argument("--stats-workers", type=int, default=portal_workers,
                     help=f"Threads for the analytics fetch (default: {portal_workers})")
    src.add_argument("--cache-dir", default=default_cache_dir,
                     help="Where the xlsx Parquet and portal stats caches live")
    src.add_argument("--no-cache", action="store_true", help="Bypass those caches")
    src.add_argument("--refresh", action="store_true",
                     help="Re-read the workbook / re-fetch the analytics counts "
                          "of the rows in this run")

    args = p.parse_args()
    if args.limit is not None and args.limit < 1:
        p.error("--limit must be a positive integer")
    source = "portal" if args.portal else ("xlsx" if args.xlsx else "db")
    if source != "db" and args.print_sql:
        p.error("--print-sql applies to the database source only")
    # Analytics counts: the default for --portal, opt-in everywhere else.
    with_stats = args.stats if args.stats is not None else source == "portal"

    if source == "db":
        if args.table != "all" and args.table not in tables:
            raise SystemExit(
                f"No profile for table {args.table!r}; known: all, {', '.join(sorted(tables))}"
            )

        if args.print_sql:
            backend = "postgres" if is_postgres(args.db) else f"duckdb file {args.db}"
            print(f"-- backend: {backend}")
            if is_postgres(args.db):
                # Redact: a DSN assembled from the environment carries a password.
                dsn = pg_dsn() if args.db in pg_aliases else args.db
                print("-- dsn:     " + redact(dsn))
            for t in (all_tables if args.table == "all" else [args.table]):
                print(build_sql(t, args.db, args.ministry_departments, args.limit))
            return
        origin = args.table
        if args.table == "all":
            # One pool, so every min-max, percentile clip and the cut itself are taken
            # over all lots together. Profiles still decide per-table parsing in `load`.
            parts = []
            for t in all_tables:
                part = load(args.db, t, args.ministry_departments, args.limit)
                part["source_table"] = t
                parts.append(part)
            df = pd.concat(parts, ignore_index=True)
        else:
            df = load(args.db, args.table, args.ministry_departments, args.limit)
            df["source_table"] = args.table
    elif source == "xlsx":
        origin = args.xlsx
        df = load_xlsx(args.xlsx, args.sheet, args.cache_dir, not args.no_cache,
                       args.refresh, args.ministry_departments, args.limit)
        df["source_table"] = Path(args.xlsx).name
    else:
        origin = "data.gov.in" + (f" + {Path(args.xlsx).name}" if args.xlsx else "")
        df = load_portal(args.limit, args.ministry_departments, args.page_size,
                         args.cache_dir, not args.no_cache, args.refresh,
                         args.offset, args.xlsx, args.sheet)
        df["source_table"] = "data.gov.in"
    if args.api_only:
        # Same `api_true` set signal_punctuality gates on, not a literal '1'.
        # A Postgres boolean cast to ::TEXT is 'true', so a '1' test here would
        # select zero rows and the run would die at "Nothing to score." -- on
        # the exact invocation the README calls the production shape.
        df = df[df["from_api"].str.lower().isin(api_true)].reset_index(drop=True)
    print(f'Loaded {len(df)} rows from "{origin}"'
          + (f" (--limit {args.limit})" if args.limit else "")
          + (" (API-fed rows only)" if args.api_only else ""))
    if df.empty:
        raise SystemExit("Nothing to score.")

    # After --api-only, so a filtered run only pays for the rows it scores.
    if with_stats:
        df = overlay_portal_stats(df, args.stats_workers, args.cache_dir,
                                  not args.no_cache, args.refresh)
    elif source == "portal":
        print("Skipping analytics (--no-stats): demand reads the list endpoint's "
              "own counts, which under-report downloads.")
    else:
        print("Counts are the source's own columns (--stats reads them from the "
              "portal's analytics endpoint instead).")

    demand, months, dcount, dcount_source = signal_demand(
        df, args.as_of, args.clip_pct)
    temporal, depth, temporal_flag = signal_temporal(
        df, args.clip_pct, args.min_start_year)
    geo, state, coll_states = signal_geo(df)
    fresh_date, data_end, freshness_basis = freshness_date(df, args.min_start_year)
    liveness, days_stale = signal_liveness(fresh_date, args.as_of, args.half_life)
    punctuality, expected, punctuality_flag = signal_punctuality(days_stale, df)
    api = signal_api(df)

    sig = pd.DataFrame({
        "demand": demand, "temporal": temporal, "geo": geo,
        "api": api, "liveness": liveness,
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
        "source_table": df["source_table"],
        "nid": df["nid"],
        "Title": df["Title"],
        "Collection": df["Collection"],
        "ministry": df["Publisher[ministry_department]"],
        "state_department": df.get("Publisher[state_department]", ""),
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
        "is_api_available": df["api_available"],
        "punctuality_flag": punctuality_flag,
        "temporal_span_years": depth,
        "temporal_flag": temporal_flag,
        "state_ut": state,
        "collection_states_covered": coll_states,
        "hvd_demand": demand.round(4),
        "hvd_temporal": temporal.round(4),
        "hvd_geo": geo.round(4),
        "hvd_api": api,
        "hvd_liveness": liveness.round(4),
        "hvd_punctuality": punctuality,
        "hvd_score": score.round(4),
        "hvd_candidate": (score >= cut).astype(int),
        "n_signals": n_signals,
        "signals_present": signals_present,
    })
    for c in args.extra_cuts:
        th = np.nanpercentile(score, 100 - c)
        out[f"hvd_candidate_p{100 - c:g}"] = (score >= th).astype(int)
        print(f"top {c:g}% cut ({100 - c:g}th percentile) = {th:.4f} -> "
              f"{int(out[f'hvd_candidate_p{100 - c:g}'].sum())} candidates")
    out = out.sort_values(["hvd_score", "n_signals"], ascending=[False, False])

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
