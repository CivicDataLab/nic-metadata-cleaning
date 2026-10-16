"""Map dublin_core_metadata -> DCAT v3 column names.

Driven by the mapping sheet:
  data/[shared] Mapping_Sheet_DCAT_Dublin_Core_V1.6 - dataset_distribution_mapping_sheet (1).csv

Builds `dcat_metadata` (a VIEW by default, --materialize for a table) that selects
every column of dublin_core_metadata under its DCAT term. The source table is never
modified, so the existing pipeline scripts keep working.

Sheet term strings are normalised on the way in: the sheet has dcat:Keywords,
dcat:ByteSize, dct:accrualPeriodicity, 'dcterms:accessRight ', 'dcterms:spatial '
and 'dcatin: applicableLegislation'.
"""

import argparse
import csv
import os

import duckdb

DB = os.path.join(os.path.dirname(__file__), "metadata.db")
MANIFEST = os.path.join(os.path.dirname(__file__), "dcat_mapping_manifest.csv")

# db_column -> (dcat_term or "" to keep the name as-is, sheet_row, status, note)
# status: exact/gap/ambiguous  -> renamed to the DCAT term
#         unmappable/internal  -> carried through unchanged
#         keep                 -> has a DCAT term but the term went to a twin column
#         drop                 -> omitted from the output
MAPPING = {
    "Title":                      ("dcterms:title", 2, "exact", ""),
    "Description":                ("dcterms:description", 3, "exact", ""),
    "Abstract":                   ("dcterms:abstract", 54, "gap", ""),
    "Subject[keyword]":           ("dcat:keyword", 24, "exact", "sheet writes dcat:Keywords"),
    # Sheet row 25 leaves the DCAT cell blank, but both keyword columns are fully populated
    # with distinct content and both are to be kept, so the sponsored set is carried under a
    # qualified name rather than folded into dcat:keyword.
    "Subject[sponsored_keyword]": ("dcat:keyword[sponsored]", 25, "exact", "qualified; sheet leaves the DCAT cell blank"),
    "Conforms To":                ("dcterms:conformsTo", None, "not-in-sheet", "sheet omits it; holds the CSV header list"),
    "Collection":                 ("", 68, "keep", "sheet says dcat:DatasetSeries, which is a class not a property"),
    "new_title":                  ("", None, "internal", ""),
    "new_unmerged_dataset_title": ("", None, "internal", "Title, cleaned where too short or misspelt"),
    "nid":                        ("", None, "internal", ""),
    "Identifier[UUID]":           ("dcterms:identifier", 13, "exact", ""),
    "Relation":                   ("dcterms:relation", 12, "exact", ""),
    "Access Rights":              ("dcterms:accessRights", 21, "exact", "sheet writes 'dcterms:accessRight '"),
    "Type":                       ("dcterms:type", 9, "exact", ""),
    "Accrual Method":             ("dcterms:accrualMethod", 44, "ambiguous", "values are codes '1'/'5'"),
    "Relation[Catalog Title]":    ("dcat:inCatalog", 30, "exact", ""),
    "Jurisdiction":               ("dcatin:jurisdictionLevel", 19, "exact", ""),
    "Publisher[ministry_department]": ("dcterms:publisher", 47, "exact", ""),
    "Publisher[state_department]":    ("", 46, "drop", "0 non-null; dropped per instruction, ministry kept"),
    "Date Issued":                ("dcterms:issued", 7, "exact", ""),
    "Date Modified":              ("dcterms:modified", 8, "exact", ""),
    "Date Created":               ("dcterms:created", 6, "exact", ""),
    "Subject[sector]":            ("", 26, "keep", "dcat:theme reserved for sector_resource per instruction"),
    "Subject[sector_resource]":   ("dcat:theme", 4, "exact", ""),
    "Accrual Periodicity":        ("dcterms:accrualPeriodicity", 22, "exact", "sheet writes dct: prefix"),
    "Coverage":                   ("dcat:temporalResolution", 23, "exact", ""),
    "Extent":                     ("dcat:byteSize", 10, "exact", "sheet writes dcat:ByteSize"),
    "Format":                     ("dcat:mediaType", 11, "exact", ""),
    "field_from_api":             ("", 79, "unmappable", "sheet lists it as 'from_api'"),
    "is_api_available":           ("", 77, "unmappable", ""),
    "external_api_reference":     ("", 76, "unmappable", ""),
    "Relation[download_url]":     ("dcat:downloadURL", 27, "exact", ""),
    "Relation[endpointURL]":      ("dcat:endpointURL", 56, "gap", ""),
    "High Value Dataset Category": ("dcatin:hvdCategory", 43, "ambiguous", ""),
    "field_show_export":          ("", 74, "unmappable", ""),
    "Creator":                    ("dcterms:creator", 45, "ambiguous", ""),
    "Note":                       ("dcatin:note", 51, "gap", ""),
    "ogdp_download_count":        ("", 72, "unmappable", ""),
    "ogdp_view_count":            ("", 71, "unmappable", ""),
    "is_visualized":              ("", 78, "unmappable", ""),
    "api_request_count":          ("", 73, "unmappable", ""),
    "is_rated":                   ("", 75, "unmappable", ""),
    "batch":                      ("", None, "internal", ""),
    "Identifier[landing_page]":   ("dcat:landingPage", 14, "exact", "sheet row 15 also offers foaf:homePage"),
    "Rights":                     ("dcterms:rights", 42, "ambiguous", ""),
    "License":                    ("dcterms:license", 52, "gap", ""),
    "Language":                   ("dcterms:language", 53, "gap", ""),
    "Alternative Title":          ("dcterms:alternative", 55, "gap", ""),
    "Source":                     ("dcterms:source", 16, "exact", ""),
    "Spatial Coverage":           ("dcterms:spatial", 17, "exact", "sheet has a trailing space"),
    "Temporal Coverage":          ("dcterms:temporal", 18, "exact", ""),
    "Rights Statement":           ("dcatin:applicableLegislation", 20, "exact", "sheet has a space after the colon"),
    "Depiction":                  ("foaf:depiction", 29, "exact", ""),
    "Relation[Access URL]":       ("dcat:accessURL", 28, "exact", ""),
    "Relation[Has Part]":         ("dcterms:hasPart", 60, "gap", ""),
    "Relation[Is Referenced By]": ("dcterms:isReferencedBy", 62, "gap", ""),
    "Relation[Is Replaced By]":   ("dcterms:isReplacedBy", 63, "gap", ""),
    "Relation[Replaces]":         ("dcterms:replaces", 64, "gap", ""),
    "Relation[Is Version Of]":    ("dcterms:isVersionOf", 65, "gap", ""),
    "Relation[Has Version]":      ("dcterms:hasVersion", 66, "gap", ""),
    "Description[endpointDescription]": ("dcat:endpointDescription", 67, "gap", ""),
    "Relation[Is Part Of]":       ("dcterms:isPartOf", 61, "gap", "sheet row 69 also offers dcat:inSeries"),
    "pii_tested":                 ("", None, "internal", ""),
    "pii_detected":               ("", None, "internal", ""),
    "headers_cleaned":            ("", None, "internal", ""),
    "row_count":                  ("", None, "internal", ""),
    "pii_test_timestamp":         ("", None, "internal", ""),
    "archive":                    ("", None, "internal", ""),
    "header_count":               ("", None, "internal", ""),
    "archive_reason":             ("", None, "internal", ""),
    "merge_method":               ("", None, "internal", ""),
    "merge_add_columns":          ("", None, "internal", ""),
    "Remark for change in header": ("", None, "internal", ""),
    "new_catalog_title":          ("", None, "internal", ""),
    "Year":                       ("", None, "internal", ""),
    "Month":                      ("", None, "internal", ""),
    "Financial_Year":             ("", None, "internal", ""),
    "Quarter":                    ("", None, "internal", ""),
    "Temporal_Raw":               ("", None, "internal", ""),
    "facility":                   ("", None, "internal", ""),
    "new_unmerged_dataset_description": ("", None, "internal", "Description, made true for the one dataset"),
}

# Publisher[ministry_department] packs "Ministry,Department[,further bodies]" into one
# comma-joined string. The ministry alone is the publisher; everything after it is a
# qualified attribution, re-joined with '; ' so multiple departments stay separable.
# The split is on every comma, so a body whose own name contains one is listed in
# COMMA_NAMES and kept whole: its commas are swapped for COMMA_MARK before the
# split and put back after. Without that, "Ministry of Micro, Small and Medium
# Enterprises" publishes as "Ministry of Micro" and the Registrar General's
# "..., India" becomes an attribution of its own. A new publisher with a comma in
# its name has to be added here.
SRC_PUBLISHER = "Publisher[ministry_department]"
COMMA_NAMES = [
    "Ministry of Consumer Affairs, Food and Public Distribution",
    "Ministry of Environment, Forest and Climate Change",
    "Ministry of Fisheries, Animal Husbandry and Dairying",
    "Ministry of Micro, Small and Medium Enterprises",
    "Ministry of Personnel, Public Grievances and Pensions",
    "Ministry of Ports, Shipping and Waterways",
    "Department of Water Resources, River Development & Ganga Rejuvenation",
    "Registrar General and Census Commissioner, India",
]
COMMA_MARK = "\u241f"


def lit(text):
    return "'" + text.replace("'", "''") + "'"


def whole_names(expr):
    """`expr` with the commas inside each of COMMA_NAMES marked, not to be split on."""
    for name in COMMA_NAMES:
        expr = f"replace({expr}, {lit(name)}, {lit(name.replace(',', COMMA_MARK))})"
    return expr


# The bodies of one publisher cell, in order, trimmed.
PUBLISHER_PARTS = ("list_transform(str_split(" + whole_names("{col}") + ", ','), "
                   "x -> trim(replace(x, " + lit(COMMA_MARK) + ", ',')))")
PUBLISHER_EXPR = PUBLISHER_PARTS + "[1] AS {out}"
# One column per department rather than one ';'-joined cell, so each attributed
# body is independently readable. Empty parts are filtered out *before* indexing:
# without that, a stray "Ministry X, , Dept Y" would push Dept Y into column 2 on
# that row while it sits in column 1 elsewhere, silently misaligning the columns.
# "Government of India" after the ministry is not a body of its own and is not
# attributed (user, 2026-10-14; "..., Department of Biotechnology, Government of India").
ATTRIBUTION_LIST = ("list_filter(" + PUBLISHER_PARTS
                    + ", (x, i) -> x <> '' AND (i = 1 OR lower(x) <> 'government of india'))")
ATTRIBUTION_EXPR = "nullif(" + ATTRIBUTION_LIST + "[{idx}], '')"
ATTRIBUTION_TERM = "prov:qualifiedAttribution[{n}]"
# The role of the attributed bodies, right after dcterms:publisher: they publish
# under the ministry (user, 2026-10-14). Set on rows that have an attribution.
ROLE_TERM = "dcat:hadRole"
ROLE_EXPR = "CASE WHEN len(" + ATTRIBUTION_LIST + ") > 1 THEN 'publisher' END"


def attribution_derived(con, source):
    """-> [(term, sheet_row, expr, note)], one entry per department slot.

    The slot count comes from the data (max bodies after the ministry), so a table
    with three departments gets three columns. Always indexed from [1], even when
    the max is 1 -- an unindexed first column would have to be renamed the day a
    second department shows up.
    """
    n = con.execute(
        f'SELECT max(len({ATTRIBUTION_LIST.format(col=q(SRC_PUBLISHER))})) - 1 '
        f'FROM {q(source)}'
    ).fetchone()[0] or 0
    return [
        (ATTRIBUTION_TERM.format(n=i), 48,
         ATTRIBUTION_EXPR.format(col="{col}", idx=i + 1),
         f"department {i} split off ministry_department (list slot {i + 1})")
        for i in range(1, n + 1)
    ]


# Emitted after dcterms:publisher. contactPoint stays empty pending CDO data.
DERIVED = None  # built per-source by attribution_derived()
PLACEHOLDERS = [("dcat:contactPoint", 31,
                 "CDO contact block; vCard sub-fields deliberately not created")]
PLACEHOLDER_AFTER = SRC_PUBLISHER

# --- AIKosh -----------------------------------------------------------------
# dublin_core_aikosh is a 61-column subset of the same Dublin Core names plus a
# few source passthroughs. Entries here override / extend MAPPING for it.
AIKOSH_EXTRA = {
    # Both publisher columns are fully populated in this export (the main table
    # has state_department empty), so neither can be dropped. The ministry keeps
    # dcterms:publisher; the state column is carried under a qualified name.
    "Publisher[state_department]": ("dcterms:publisher[state]", 46, "exact", "aikosh populates this"),
    # Raw endpoints stay as passthrough. dcat:startDate / dcat:endDate are
    # derived by splitting the already-normalised dcterms:temporal interval, so
    # the period and its two halves cannot drift apart.
    "data_time_period_from":       ("", None, "internal", "raw; the labelled start endpoint is rendered into dcterms:temporal"),
    "data_time_period_to":         ("", None, "internal", "raw; the labelled end endpoint is rendered into dcterms:temporal"),
    # vCard for the Chief Data Officer (sheet rows 32-40). DCAT only: the Dublin
    # Core table deliberately carries these unmapped.
    "cdo_username":                ("vcard:fn", 32, "exact", "CDO name"),
    "cdo_email":                   ("vcard:hasEmail", 36, "exact", "CDO email"),
    "till_date":                   ("", None, "internal", "data-currency marker, no DC/DCAT term"),
    "spatial_coverage":            ("", None, "internal", "raw source col; dcterms:spatial holds the mapped value"),
}

# Sheet row 18 maps the from/to pair to dcterms:temporal, and DCAT v3 expresses
# that period with dcat:startDate / dcat:endDate. Both endpoints are rendered
# into the single dcterms:temporal cell, labelled -- rather than kept as two
# extra columns -- so the period reads as one value:
#     "dcat:startDate: 2000-03-01; dcat:endDate: 2000-06-30"
# The source is a DCMI interval, "2011-04-01/2012-03-31", so the halves are split
# off the already-normalised value and can never disagree with it.
SRC_TEMPORAL = "Temporal Coverage"
TEMPORAL_EXPR = (
    "nullif(concat_ws('; ',"
    " CASE WHEN nullif(split_part({col}, '/', 1), '') IS NOT NULL"
    " THEN 'dcat:startDate: ' || split_part({col}, '/', 1) END,"
    " CASE WHEN nullif(split_part({col}, '/', 2), '') IS NOT NULL"
    " THEN 'dcat:endDate: ' || split_part({col}, '/', 2) END"
    "), '')"
)
TEMPORAL_NOTE = ("both endpoints in one cell, "
                 "'dcat:startDate: <from>; dcat:endDate: <to>'")

# --- controlled values --------------------------------------------------------
# dublin_core_metadata already holds accrual periodicity as a DCMI frequency URI
# (http://purl.org/cld/freq/monthly) and granularity as an xsd:duration literal
# (P1M^^xsd:duration). The other lots hold the OGD dropdown label ("Monthly"), so
# their two columns are rendered in those forms here. A value that is not one of
# the labels -- a URI already, a blank -- is passed through as it is.
SRC_PERIODICITY = "Accrual Periodicity"
SRC_RESOLUTION = "Coverage"
FREQ_URI = "http://purl.org/cld/freq/"
# OGD label, lower case -> term under FREQ_URI.
PERIODICITY_TERMS = {
    "daily": "daily",
    "weekly": "weekly",
    "fortnightly": "biweekly",
    "monthly": "monthly",
    "quarterly": "quarterly",
    "half yearly": "semiannual",
    "biannual": "semiannual",
    "annual": "annual",
    "biennial": "biennial",
    "others": "irregular",
    # The DCMI vocabulary has no term for these. They are named in its style under
    # the same prefix, as dublin_core_metadata already does with "onetime".
    "one-time": "onetime",
    "hourly": "hourly",
    "five yearly": "quinquennial",
    "decadal": "decennial",
}
# OGD label, lower case -> xsd:duration. None: no period to resolve, left empty.
RESOLUTION_DURATIONS = {
    "hourly": "PT1H",
    "daily": "P1D",
    "weekly": "P7D",
    "fortnightly": "P14D",
    "monthly": "P1M",
    "quarterly": "P3M",
    "half yearly": "P6M",
    "biannual": "P6M",
    "annual": "P1Y",
    "biennial": "P2Y",
    "five yearly": "P5Y",
    "decadal": "P10Y",
    "one-time": None,
    "others": None,
}


def label_case(values, render):
    whens = " ".join(
        f"WHEN {lit(label)} THEN {'NULL' if value is None else lit(render(value))}"
        for label, value in values.items())
    return "CASE lower(trim({col})) " + whens + " ELSE {col} END"


PERIODICITY_EXPR = label_case(PERIODICITY_TERMS, lambda term: FREQ_URI + term)
PERIODICITY_NOTE = f"OGD frequency label as a DCMI frequency URI ({FREQ_URI}<term>)"
RESOLUTION_EXPR = label_case(RESOLUTION_DURATIONS, lambda d: d + "^^xsd:duration")
RESOLUTION_NOTE = ("OGD granularity label as an xsd:duration (P1M^^xsd:duration); "
                   "'Others' and 'One-time' left empty")
# For the profiles whose source table holds the labels (remaining, lot3).
LOT_EXPR = {
    SRC_PERIODICITY: (PERIODICITY_EXPR, PERIODICITY_NOTE),
    SRC_RESOLUTION: (RESOLUTION_EXPR, RESOLUTION_NOTE),
}

# CDO details from the data.gov.in CMS API (utils/fetch_cdo_details.py, copied
# onto the lot tables by utils/fill_cdo_details.py, 2026-10-14). The sheet has
# no phone row; vcard:hasTelephone is the vCard term for it.
CDO_VCARD = {
    "cdo_designation":             ("vcard:title", 33, "exact", "CDO designation, from the CDO API"),
    "cdo_address":                 ("vcard:hasAddress", 37, "exact", "CDO address, from the CDO API"),
    "cdo_phone":                   ("vcard:hasTelephone", None, "gap", "CDO phone, from the CDO API; no sheet row"),
}

# --- remaining-raw-datasets corpus -------------------------------------------
# dublin_core_remaining is the same Dublin Core names plus the source passthroughs
# that rode along from the transform profile, and the merge bookkeeping columns.
# Entries here override / extend MAPPING for it.
REMAINING_EXTRA = {
    # Populated on 115,471 rows here (the main table has neither), so the CDO gets
    # real vCard fields rather than the empty dcat:contactPoint placeholder.
    "cdo_name":                    ("vcard:fn", 32, "exact", "CDO name"),
    "cdo_email":                   ("vcard:hasEmail", 36, "exact", "CDO email"),
    **CDO_VCARD,
    # Raw endpoints stay as passthrough; dcat:startDate / dcat:endDate are derived
    # from the already-normalised dcterms:temporal interval so they cannot drift.
    "data_time_period_from":       ("", None, "internal", "raw; the labelled start endpoint is rendered into dcterms:temporal"),
    "data_time_period_to":         ("", None, "internal", "raw; the labelled end endpoint is rendered into dcterms:temporal"),
    "till_date":                   ("", None, "internal", "data-currency marker, no DC/DCAT term"),
    # Raw spatial columns from the content-based detector; dcterms:spatial holds
    # the mapped value, so these are carried through unchanged.
    "spatial_coverage":            ("", None, "internal", "raw source col; dcterms:spatial holds the mapped value"),
    "spatial_states":              ("", None, "internal", "raw spatial detector output"),
    "spatial_districts":           ("", None, "internal", "raw spatial detector output"),
    "spatial_subdistricts":        ("", None, "internal", "raw spatial detector output"),
    "spatial_level":               ("", None, "internal", "raw spatial detector output"),
    "spatial_source":              ("", None, "internal", "raw spatial detector output"),
    # Provenance / pipeline bookkeeping, no DCAT term.
    "source_file":                 ("", None, "internal", "source export filename"),
    "file_present":                ("", None, "internal", "whether the datafile exists on disk"),
    "dataset_merge":               ("", None, "internal", "merge pipeline flag"),
    "exact_merge_group_name":      ("", None, "internal", "merge pipeline bookkeeping"),
    "exact_merge_group_id":        ("", None, "internal", "merge pipeline bookkeeping"),
    "needs_review":                ("", None, "internal", "merge pipeline flag"),
    # Columns added to dublin_core_remaining after the first mapping.
    "year":                        ("", None, "internal", "temporal parts parsed from the title"),
    "month":                       ("", None, "internal", "temporal parts parsed from the title"),
    "quarter":                     ("", None, "internal", "temporal parts parsed from the title"),
    "financial_year":              ("", None, "internal", "temporal parts parsed from the title"),
    "state":                       ("", None, "internal", "state parsed from the title"),
    "Remark":                      ("", None, "internal", "twin of 'Remark for change in header'"),
    "Subject[keyword_fullform]":   ("dcat:keyword[fullform]", 24, "exact", "qualified like the sponsored set; abbreviation full forms"),
    "sponsored_keyword_search":    ("", None, "internal", "keyword-generation bookkeeping"),
    "title_search":                ("", None, "internal", "keyword-generation bookkeeping"),
    "sponsored_keyword_needed":    ("", None, "internal", "keyword-generation bookkeeping"),
    "collection_sponsored_keyword_needed": ("", None, "internal", "keyword-generation bookkeeping"),
}

# dublin_core_lot3 has the remaining columns minus a few, plus two temporal checks.
LOT3_EXTRA = {
    **REMAINING_EXTRA,
    "temporal_source":             ("", None, "internal", "how the temporal coverage was derived"),
    "temporal_check":              ("", None, "internal", "temporal coverage check flag"),
}

# Lot 1's CDO, set on every dublin_core_metadata row 2026-10-14 (one CDO for
# the whole lot), mapped like the remaining profile's.
METADATA_EXTRA = {
    "cdo_name":                    ("vcard:fn", 32, "exact", "CDO name"),
    "cdo_email":                   ("vcard:hasEmail", 36, "exact", "CDO email"),
    **CDO_VCARD,
}

PROFILES = {
    "metadata": {
        "source": "dublin_core_metadata",
        "target": "dcat_metadata",
        "extra": METADATA_EXTRA,
        "derived": None,  # attribution_derived() fills this from the data
        # cdo_name / cdo_email give real vcard:fn / vcard:hasEmail, so no empty
        # dcat:contactPoint placeholder, as in the other profiles.
        "placeholders": [],
    },
    "aikosh": {
        "source": "dublin_core_aikosh",
        "target": "dcat_aikosh",
        "extra": AIKOSH_EXTRA,
        "derived": None,  # attribution_derived() fills this from the data
        # vcard:fn / vcard:hasEmail come from real columns, so no empty
        # dcat:contactPoint placeholder is needed here.
        "placeholders": [],
        "expr": {SRC_TEMPORAL: (TEMPORAL_EXPR, TEMPORAL_NOTE)},
    },
    "remaining": {
        "source": "dublin_core_remaining",
        "target": "dcat_remaining",
        "extra": REMAINING_EXTRA,
        "derived": None,  # attribution_derived() fills this from the data
        # cdo_name / cdo_email give real vcard:fn / vcard:hasEmail, so no empty
        # dcat:contactPoint placeholder — same call as the aikosh profile.
        "placeholders": [],
        "expr": {SRC_TEMPORAL: (TEMPORAL_EXPR, TEMPORAL_NOTE), **LOT_EXPR},
    },
    "lot3": {
        "source": "dublin_core_lot3",
        "target": "dcat_lot3",
        "extra": LOT3_EXTRA,
        "derived": None,
        "placeholders": [],
        "expr": {SRC_TEMPORAL: (TEMPORAL_EXPR, TEMPORAL_NOTE), **LOT_EXPR},
    },
}


def q(name):
    return '"' + name.replace('"', '""') + '"'


def build_select(src_cols, profile):
    """Return (list of SELECT expressions, list of manifest rows)."""
    mapping = {**MAPPING, **profile["extra"]}
    derived = profile["derived"]
    placeholders = profile["placeholders"]
    after = profile.get("after", {})
    expr_override = profile.get("expr", {})
    exprs, manifest = [], []
    for col in src_cols:
        term, row, status, note = mapping[col]
        if status == "drop":
            manifest.append([col, "", row or "", "dropped", note])
            continue
        out = term if term else col
        if col == SRC_PUBLISHER:
            exprs.append(PUBLISHER_EXPR.format(col=q(col), out=q(out)))
            manifest.append([col, out, row or "", "derived", "ministry only; the first body of the cell"])
            # no source column: it is a constant, not a raw field
            exprs.append(f"{ROLE_EXPR.format(col=q(col))} AS {q(ROLE_TERM)}")
            manifest.append(["", ROLE_TERM, 48, "derived",
                             "'publisher' where the row has a prov:qualifiedAttribution"])
        elif col in expr_override:
            oexpr, onote = expr_override[col]
            exprs.append(f"{oexpr.format(col=q(col))} AS {q(out)}")
            manifest.append([col, out, row or "", "derived", onote])
        elif term:
            exprs.append(f"{q(col)} AS {q(out)}")
            manifest.append([col, out, row or "", "renamed", note])
        else:
            exprs.append(q(col))
            manifest.append([col, out, row or "", "unchanged", note])
        for aterm, arow, aexpr, anote in after.get(col, ()):
            exprs.append(f"{aexpr} AS {q(aterm)}")
            manifest.append([col, aterm, arow, "derived", anote])
        if col == PLACEHOLDER_AFTER:
            for dterm, drow, dexpr, dnote in derived:
                exprs.append(f"{dexpr.format(col=q(SRC_PUBLISHER))} AS {q(dterm)}")
                manifest.append([SRC_PUBLISHER, dterm, drow, "derived", dnote])
            for pterm, prow, pnote in placeholders:
                exprs.append(f"CAST(NULL AS VARCHAR) AS {q(pterm)}")
                manifest.append(["", pterm, prow, "placeholder", pnote])
    return exprs, manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--materialize", action="store_true",
                    help="build a TABLE instead of a VIEW (duplicates ~3GB of data)")
    ap.add_argument("--profile", default="metadata", choices=sorted(PROFILES),
                    help="which Dublin Core source table to map")
    ap.add_argument("--target", default=None)
    ap.add_argument("--dry-run", action="store_true", help="print SQL, write manifest, touch nothing")
    args = ap.parse_args()

    profile = PROFILES[args.profile]
    source = profile["source"]
    target = args.target or profile["target"]
    manifest_path = MANIFEST if args.profile == "metadata" else MANIFEST.replace(
        ".csv", f"_{args.profile}.csv")

    con = duckdb.connect(DB, read_only=args.dry_run)
    src_cols = [r[0] for r in con.execute(
        "select column_name from duckdb_columns() "
        "where table_name=? order by column_index", [source]).fetchall()]
    if not src_cols:
        raise SystemExit(f"source table {source!r} not found in {DB}")

    mapping = {**MAPPING, **profile["extra"]}
    unknown = [c for c in src_cols if c not in mapping]
    if unknown:
        raise SystemExit(f"{source}: no mapping entry for {unknown}")

    profile = {**profile, "derived": attribution_derived(con, source)}
    exprs, manifest = build_select(src_cols, profile)

    # Reconcile: every source column is renamed, carried through, or explicitly dropped.
    dropped = [c for c in src_cols if mapping[c][2] == "drop"]
    n_after = sum(len(v) for v in profile.get("after", {}).values())
    has_role = SRC_PUBLISHER in src_cols and SRC_PUBLISHER not in dropped    # ROLE_TERM
    expected = (len(src_cols) - len(dropped) + n_after + has_role
                + len(profile["derived"]) + len(profile["placeholders"]))
    assert len(exprs) == expected, f"expected {expected} output columns, built {len(exprs)}"

    out_names = [r[1] for r in manifest if r[3] != "dropped"]
    dupes = {n for n in out_names if out_names.count(n) > 1}
    assert not dupes, f"duplicate output column names: {dupes}"

    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source_column", "dcat_column", "sheet_row", "action", "note"])
        w.writerows(manifest)

    kind = "TABLE" if args.materialize else "VIEW"
    sql = (f"CREATE OR REPLACE {kind} {q(target)} AS SELECT\n  "
           + ",\n  ".join(exprs)
           + f"\nFROM {q(source)}")

    if args.dry_run:
        print(sql)
    else:
        con.execute(sql)
        n = con.execute(f"select count(*) from {q(target)}").fetchone()[0]
        print(f"{kind} {target}: {len(exprs)} columns, {n} rows")

    print(f"source table   : {source}")
    print(f"source columns : {len(src_cols)}")
    print(f"  renamed      : {sum(1 for r in manifest if r[3] == 'renamed')}")
    print(f"  unchanged    : {sum(1 for r in manifest if r[3] == 'unchanged')}")
    print(f"  derived      : {sum(1 for r in manifest if r[3] == 'derived')}")
    print(f"  dropped      : {len(dropped)} ({', '.join(dropped) or '-'})")
    print(f"  placeholders : {len(profile['placeholders'])}")
    print(f"output columns : {len(exprs)}")
    print(f"manifest       : {manifest_path}")
    con.close()


if __name__ == "__main__":
    main()
