"""Final PII result per dataset for lots 2 and 3, after a manual review of the verdicts.

The pipeline's `present` and `permissible` verdicts over-call. On 2026-10-12 every
dataset the pipeline judged `present` (231 in lot 2, 237 rows in lot 3) or
`permissible` (256 and 128) was read again: title, headers, the flagged columns
and their detected values, and the cells themselves where that was not enough.
This script holds what that review decided and writes it out. It changes no
pipeline output: column_class.csv, dataset_class.csv and lot*_pii_result.csv
stay as the pipeline left them, and a pipeline re-run does not carry these
decisions forward.

The three final classes are the pipeline's own:

    present         personal data of private individuals: people named as
                    beneficiaries, patients, victims, accused, owners or next of
                    kin, or a register that gives relatives' names, date of
                    birth or community
    permissible     people named in a public, official or professional role
                    (members, officials, principals, scientists, athletes,
                    advocates and notaries on a register), and the contact
                    details of offices, institutions and businesses
    false_positive  not personal data: place, scheme, institution and disease
                    names read as people, and ordinary numbers read as phone or
                    Aadhaar numbers

Starting point for a `present` dataset is the first reading in
lot{2,3}_present_groups.csv; CORRECTIONS are the datasets where the second,
closer reading disagreed with it. A `permissible` dataset keeps its verdict
unless it is listed in PERMISSIBLE_FALSE. ADDED are files the scan could not
read at all and the review found by looking at their neighbours.

Writes pii_test/final_review/:

    final_results.csv   one row per reviewed dataset: pipeline_result, final_result,
                        what it holds, and a note where the call is arguable
    kept_columns.csv    columns the pipeline rejected that do hold personal data

    python pii_test/build_final_review.py
"""

import os

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PII = os.path.join(REPO_ROOT, "pii_test")
OUT_DIR = os.path.join(PII, "final_review")
UUID_RE = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"

PRIVATE = "private individuals"
ROLE = "named people in a public or professional role"
OFFICE = "office or business contacts"
NOT_PII = "not personal data"

# First reading (group letter in lot*_present_groups.csv) -> (final result, what it holds).
FIRST_READING = {
    2: {"A": ("present", PRIVATE), "B": ("permissible", ROLE),
        "C": ("permissible", OFFICE), "D": ("false_positive", NOT_PII)},
    3: {"A": ("present", PRIVATE), "B": ("permissible", ROLE), "C": ("permissible", ROLE),
        "D": ("permissible", OFFICE), "E": ("false_positive", NOT_PII)},
}

# Where the second reading disagreed with the first: uuid prefix -> (final, holds, why).
CORRECTIONS = {
    2: {
        "f8397904": ("present", PRIVATE,
                     "missing-children cases: girls aged 15-17 named with father's name, home "
                     "address, mobile number and caste"),
        "6dfdd7da": ("present", PRIVATE,
                     "traffic-accident victims named with address, mobile number, caste and "
                     "occupation"),
        "8d7d991e": ("present", PRIVATE,
                     "merchant registration survey: proprietors' PAN numbers, names, mobile "
                     "numbers and IP addresses"),
        "f9419172": ("permissible", ROLE, "named doctors and service-centre operators with locality"),
        "4da4dbd2": ("permissible", ROLE, "named service-centre operators with business address"),
        "8a6e8694": ("permissible", ROLE, "free text naming a college founder and an acting principal"),
    },
    3: {
        "2bf5e7f0": ("false_positive", NOT_PII, "the beneficiary is a workers' union, not a person"),
        "7fff4e1c": ("false_positive", NOT_PII, "constituency names"),
        # Advocate rolls that go beyond name and address.
        "a1d912ee": ("present", PRIVATE, "advocate roll with father's name, address and phone"),
        "c0cc1127": ("present", PRIVATE, "advocate roll with father's name, address and phone"),
        "10205f8f": ("present", PRIVATE, "advocate roll with date of birth and community"),
        "492f1bd5": ("present", PRIVATE,
                     "advocate roll with date of birth, father's and husband's name, community"),
        "ba059a7f": ("present", PRIVATE, "advocate roll with father's name and date of birth"),
        "bc30d4fe": ("permissible", OFFICE, "one office address and landline among statistics"),
        "dd18336f": ("permissible", OFFICE, "one office address and landline among statistics"),
        "bdbde33c": ("permissible", OFFICE, "service-centre landlines"),
        "5cbeb76f": ("permissible", ROLE, "one contractor named"),
    },
}

# Pipeline `permissible` datasets that are false detections. A catalogue entry takes
# every permissible dataset of that catalogue whose flagged columns are all in the set.
PERMISSIBLE_FALSE = {
    2: {
        "03b0094f": "college names", "31e16f75": "college names",
        "d6eab018": "student/faculty ratios read as phone numbers",
        "7da55270": "city names", "07df5cfe": "hospital addresses", "51833678": "a locality name",
        "f6b5a8d8": "school names", "27ecd279": "school names",
        "e6860bae": "project numbers read as phone numbers",
        "c54acf87": "a volume read as a phone number", "bdafc6e5": "a volume read as a phone number",
        "f9ff3de2": "project names", "19ed7dc5": "institute addresses",
        "459bd56a": "amounts read as phone and Aadhaar numbers",
        "cf9bc4a4": "an amount read as a phone number", "99f16a41": "a system name",
    },
    3: {
        "b9113f69": "political party names", "6772a536": "political party names",
        "9e5e965d": "political party names", "3729002f": "political party names",
        "d8cd3611": "an abbreviation", "65632b8b": "department names",
    },
}
PERMISSIBLE_FALSE_CATALOGUES = {
    2: [("Mission Antyodaya Survey Data", {"GP NAME"}, "gram panchayat names")],
    3: [],
}

# Files the scan read nothing from (base64-encoded JSON saved as .csv), found by
# looking at the neighbours of confirmed findings.
ADDED = {
    2: {
        "45035150": ("present", PRIVATE,
                     "added by review: 100 COVID patients with name, address, age, mobile number "
                     "and comorbidity, base64-encoded so the scan read nothing"),
        "008aeb86": ("permissible", ROLE,
                     "added by review: hospital in-charge names and contact numbers, "
                     "base64-encoded so the scan read nothing"),
    },
    3: {},
}

# Columns the pipeline rejected that do hold personal data (dataset stays `present`).
KEPT_COLUMNS = [
    (2, "f26b2921", "enumerator_name", "field staff names"),
    (2, "bd9bdf79", "individual_owner_name", "scheme owners' names"),
    (2, "b7803577", "Name Beneficiary", "beneficiaries' names (single-word names)"),
    (2, "a54c9ed9", "Allegation in Brief", "people named in the allegation text"),
    (2, "8d7d991e", "Unnamed: 25", "PAN numbers"),
    (3, "492f1bd5", "ADDRESS", "a person named in the address"),
]

# Arguable calls, marked so they can be filtered and flipped as a set.
MEMBER_DIRECTORY = ("judgment call: member directory that also gives relatives' names and "
                    "home addresses")
REGISTER = ("judgment call: professional register of advocates or notaries (name and address, "
            "sometimes a phone number)")
STUDENTS = "judgment call: students, trainees or research fellows named"
OPERATORS = "judgment call: service-centre operators listed with their mobile numbers"
OTHER_CALLS = {
    2: {
        "d800da24": STUDENTS, "3b13f438": STUDENTS, "c718b2f4": STUDENTS, "d81281ed": STUDENTS,
        "a2c7ce89": STUDENTS,
        "8ac38867": "judgment call: volunteer animal rescuers named with mobile numbers",
        "a8116d49": "judgment call: child day-care workers named",
        "ab76eef4": "judgment call: self-help group contact numbers and addresses",
        "fd945b55": "judgment call: leaders of insurgent groups named",
        "daae37e8": OPERATORS, "94d19335": OPERATORS,
    },
    3: {"7774dbc6": OPERATORS, "6d8723cc": OPERATORS, "c21a7382": OPERATORS,
        "f58b58ae": OPERATORS},
}
REGISTER_CATALOGUES = ("All India Advocate List",
                       "State-wise List of Notaries Appointed by the Central Government")


def flagged_columns(lot):
    """{file uuid: set of columns the pipeline did not reject}."""
    cc = pd.read_csv(os.path.join(PII, f"lot{lot}", "classification", "column_class.csv"),
                     dtype=str, keep_default_na=False,
                     usecols=["uuid", "column", "pii_class"])
    cc = cc[cc["pii_class"] != "false_positive"]
    cc["file_uuid"] = cc["uuid"].str.extract(UUID_RE)[0]
    return cc.groupby("file_uuid")["column"].agg(lambda s: {c.strip() for c in s}).to_dict()


def by_prefix(table, uuid):
    return table.get(uuid[:8])


def review_lot(lot):
    result = pd.read_csv(os.path.join(PII, f"lot{lot}", f"lot{lot}_pii_result.csv"),
                         dtype=str, keep_default_na=False)
    groups = (pd.read_csv(os.path.join(PII, f"lot{lot}", f"lot{lot}_present_groups.csv"),
                          dtype=str, keep_default_na=False)
              .drop_duplicates("uuid").set_index("uuid")["group"])
    columns = flagged_columns(lot)

    rows = []
    for row in result.itertuples(index=False):
        pipeline = row.pii_status
        note = ""
        if pipeline == "present":
            final, holds = FIRST_READING[lot][groups[row.uuid][0]]
            corrected = by_prefix(CORRECTIONS[lot], row.uuid)
            if corrected:
                final, holds, note = corrected
        elif pipeline == "permissible":
            final, holds = "permissible", "public role or office contact (pipeline verdict kept)"
            why = by_prefix(PERMISSIBLE_FALSE[lot], row.uuid)
            for catalogue, only, reason in PERMISSIBLE_FALSE_CATALOGUES[lot]:
                if row.catalog_title.strip() == catalogue and columns.get(row.uuid, set()) <= only:
                    why = reason
            if why:
                final, holds, note = "false_positive", NOT_PII, why
        elif by_prefix(ADDED[lot], row.uuid):
            final, holds, note = by_prefix(ADDED[lot], row.uuid)
        else:
            continue

        if final == "permissible" and not note:
            if "Father Name" in columns.get(row.uuid, set()):
                note = MEMBER_DIRECTORY
            elif row.catalog_title.strip().startswith(REGISTER_CATALOGUES):
                note = REGISTER
            else:
                note = by_prefix(OTHER_CALLS[lot], row.uuid) or ""
        rows.append({"lot": lot, "nid": row.nid, "uuid": row.uuid, "title": row.title,
                     "catalog_title": row.catalog_title, "publisher": row.publisher,
                     "pipeline_result": pipeline, "final_result": final, "holds": holds,
                     "changed": "yes" if final != pipeline else "no", "note": note})
    return pd.DataFrame(rows)


def main():
    reviewed = pd.concat([review_lot(2), review_lot(3)], ignore_index=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    reviewed.to_csv(os.path.join(OUT_DIR, "final_results.csv"), index=False)
    pd.DataFrame(KEPT_COLUMNS, columns=["lot", "uuid_prefix", "column", "holds"]).to_csv(
        os.path.join(OUT_DIR, "kept_columns.csv"), index=False)

    for lot, part in reviewed.groupby("lot"):
        print(f"\nlot {lot}: {len(part)} rows reviewed "
              f"({part['uuid'].nunique()} distinct datasets)")
        print(pd.crosstab(part["pipeline_result"], part["final_result"], margins=True).to_string())
    calls = reviewed[reviewed["note"].str.startswith("judgment call")]
    print("\njudgment calls:")
    print(calls.groupby(["lot", "note"]).size().to_string())
    print(f"\nwrote {OUT_DIR}/final_results.csv and kept_columns.csv")


if __name__ == "__main__":
    main()
