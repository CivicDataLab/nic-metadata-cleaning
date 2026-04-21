"""
Metadata curation status report generator.

Reads flags from dublin_core_metadata (adding missing flag columns if needed)
and writes a summary CSV with counts for each curation stage.

Usage:
    python curation_status.py                           # prints + writes CSV
    python curation_status.py --output status.csv       # custom output path
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
TABLE = "dublin_core_metadata"
DEFAULT_OUTPUT = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/curation_status.csv"

# Google Drive config — set GDRIVE_FOLDER_ID env var or pass --folder-id
CREDENTIALS_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/credentials.json"
TOKEN_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# Flag columns that must exist in the table.
# Each entry: (column_name, duckdb_type, default_value)
REQUIRED_FLAGS = [
    ("pii_tested",            "BOOLEAN", "FALSE"),
    ("pii_detected",          "BOOLEAN", "FALSE"),
    ("metadata_enhanced",     "BOOLEAN", "FALSE"),
    # dataset_merge and Collection already exist
]


def ensure_flag_columns(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Add any missing flag columns to the table. Returns list of columns added."""
    existing = {
        r[0]
        for r in conn.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{TABLE}'"
        ).fetchall()
    }

    added = []
    for col_name, col_type, default in REQUIRED_FLAGS:
        if col_name not in existing:
            conn.execute(
                f'ALTER TABLE {TABLE} ADD COLUMN "{col_name}" {col_type} DEFAULT {default}'
            )
            added.append(col_name)

    return added


def collect_stats(conn: duckdb.DuckDBPyConnection) -> dict:
    """Query all curation metrics from the database."""

    def count(where: str = "1=1") -> int:
        return conn.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE {where}").fetchone()[0]

    total = count()

    # --- Merge / Collection stats ---
    mergeable = count("dataset_merge = TRUE")
    non_mergeable = count("dataset_merge = FALSE")
    collections = conn.execute(
        f'SELECT COUNT(DISTINCT "Collection") FROM {TABLE} WHERE "Collection" IS NOT NULL'
    ).fetchone()[0]
    mergeable_collections = conn.execute(
        f'SELECT COUNT(DISTINCT "Collection") FROM {TABLE} '
        f"WHERE dataset_merge = TRUE AND \"Collection\" IS NOT NULL"
    ).fetchone()[0]

    # --- PII stats ---
    pii_tested = count("pii_tested = TRUE")
    pii_not_tested = total - pii_tested
    pii_detected = count("pii_detected = TRUE")
    pii_clean = count("pii_tested = TRUE AND pii_detected = FALSE")

    # --- Metadata enhancement stats ---
    metadata_enhanced = count("metadata_enhanced = TRUE")
    metadata_not_enhanced = total - metadata_enhanced

    # LLM keyword generation progress (from llm_keyword_results table)
    llm_keywords_generated = conn.execute(
        "SELECT COUNT(*) FROM llm_keyword_results"
    ).fetchone()[0]

    # --- Gap field fill rates ---
    desc_filled = count("\"Description\" IS NOT NULL AND \"Description\" != ''")
    abstract_filled = count("\"Abstract\" IS NOT NULL AND \"Abstract\" != ''")
    keywords_filled = count("\"Subject[keyword]\" IS NOT NULL AND \"Subject[keyword]\" != ''")
    license_filled = count("\"License\" IS NOT NULL AND \"License\" != ''")
    language_filled = count("\"Language\" IS NOT NULL AND \"Language\" != ''")

    return {
        "report_generated_at":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_datasets":               total,
        # Merge / Collections
        "mergeable_datasets":           mergeable,
        "non_mergeable_datasets":       non_mergeable,
        "total_collections":            collections,
        # PII
        "pii_tested":                   pii_tested,
        "pii_detected":                 pii_detected,
        "pii_clean":                    pii_clean,
        # Enhancement
        "metadata_enhanced":            metadata_enhanced,
        "metadata_not_enhanced":        metadata_not_enhanced,
        "llm_keywords_generated":       llm_keywords_generated,
        # Gap fields filled
        "description_filled":           desc_filled,
        "abstract_filled":              abstract_filled,
        "keywords_filled":              keywords_filled,
        "license_filled":               license_filled,
        "language_filled":              language_filled,
    }


SECTIONS = [
    ("Datasets & Collections", [
        ("Total Datasets",          "total_datasets"),
        ("Mergeable Datasets",      "mergeable_datasets"),
        ("Non-mergeable Datasets",  "non_mergeable_datasets"),
        ("Total Collections",       "total_collections"),
    ]),
    ("PII Testing", [
        ("PII Tested",              "pii_tested"),
        ("PII Detected",            "pii_detected"),
        ("PII Clean",               "pii_clean"),
    ]),
    ("Metadata Enhancement", [
        ("Metadata Enhanced",       "metadata_enhanced"),
        ("LLM Keywords Generated",  "llm_keywords_generated"),
    ]),
    ("Gap Fields Filled", [
        ("Description Filled",      "description_filled"),
        ("Abstract Filled",         "abstract_filled"),
        ("Keywords Filled",         "keywords_filled"),
    ]),
]


def write_csv(stats: dict, output_path: str) -> None:
    """Write a multi-table CSV with sections separated by blank rows."""
    total_unmergeable = stats["non_mergeable_datasets"]
    total = stats["total_datasets"]
    timestamp = stats["report_generated_at"]

    with open(output_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Metadata Curation Status Report"])
        w.writerow(["Generated", timestamp])
        w.writerow([])

        for section_name, fields in SECTIONS:
            w.writerow([section_name, "Count", "%"])
            for label, key in fields:
                val = stats[key]
                if key in ("total_datasets", "llm_keywords_generated", "total_collections"):
                    pct = ""
                if key in ("description_filled", "abstract_filled", "keywords_filled", "llm_keywords_generated", "metadata_enhanced"):
                    pct = f"{val / total_unmergeable * 100:.1f}%"
                else:
                    pct = f"{val / total * 100:.1f}%"
                w.writerow([label, val, pct])
            w.writerow([])


def get_drive_service():
    """Authenticate and return a Google Drive API service object.

    First run opens a browser for OAuth consent and saves token.json.
    Subsequent runs reuse the saved token (refreshing automatically).
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"OAuth credentials not found at {CREDENTIALS_PATH}\n"
                    "Download your OAuth client JSON from Google Cloud Console "
                    "and save it there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            # bind_addr 0.0.0.0 so Windows browser can reach WSL's server
            creds = flow.run_local_server(port=8090, bind_addr="0.0.0.0")
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def upload_to_drive(csv_path: str, folder_id: str | None = None) -> str:
    """Upload (or update) the CSV on Google Drive. Returns the file URL."""
    from googleapiclient.http import MediaFileUpload

    service = get_drive_service()
    filename = Path(csv_path).name
    media = MediaFileUpload(csv_path, mimetype="text/csv", resumable=True)

    # Check if file already exists in the target folder (update instead of duplicate)
    query = f"name = '{filename}' and trashed = false"
    if folder_id:
        query += f" and '{folder_id}' in parents"

    results = service.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
    existing = results.get("files", [])

    if existing:
        file_id = existing[0]["id"]
        service.files().update(fileId=file_id, media_body=media).execute()
        print(f"Updated existing file: {filename} (id: {file_id})")
    else:
        file_metadata = {"name": filename}
        if folder_id:
            file_metadata["parents"] = [folder_id]
        uploaded = service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()
        file_id = uploaded["id"]
        print(f"Uploaded new file: {filename} (id: {file_id})")

    return f"https://drive.google.com/file/d/{file_id}/view"


def print_report(stats: dict) -> None:
    """Pretty-print the status report."""
    total = stats["total_datasets"]
    total_unmergeable = stats["non_mergeable_datasets"]

    print("=" * 60)
    print("  METADATA CURATION STATUS REPORT")
    print(f"  Generated: {stats['report_generated_at']}")
    print("=" * 60)

    for section_name, fields in SECTIONS:
        print(f"\n  {section_name}")
        print(f"  {'-' * 40}")
        for label, key in fields:
            val = stats[key]
            if key in ("total_datasets", "llm_keywords_generated"):
                pct = ""
            else:
                pct = f"({val / total * 100:5.1f}%)"
            print(f"    {label:<28} {val:>8}  {pct}")

    print(f"\n{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="Generate metadata curation status report")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output CSV path")
    parser.add_argument("--db", default=DB_PATH, help="DuckDB database path")
    parser.add_argument("--no-csv", action="store_true", help="Print only, don't write CSV")
    parser.add_argument("--upload", action="store_true", help="Upload CSV to Google Drive")
    parser.add_argument("--folder-id", default=os.environ.get("GDRIVE_FOLDER_ID"),
                        help="Google Drive folder ID (or set GDRIVE_FOLDER_ID env var)")
    args = parser.parse_args()

    conn = duckdb.connect(args.db)

    added = ensure_flag_columns(conn)
    if added:
        print(f"Added missing flag columns: {added}")

    stats = collect_stats(conn)
    conn.close()

    print_report(stats)

    if not args.no_csv:
        write_csv(stats, args.output)
        print(f"\nCSV written to {args.output}")

        if args.upload:
            url = upload_to_drive(args.output, folder_id=args.folder_id)
            print(f"Google Drive: {url}")


if __name__ == "__main__":
    main()
