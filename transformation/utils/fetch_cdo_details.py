"""
Fetch each CDO's details from the data.gov.in CMS API by email and load them
into the table cdo_details (metadata.db).

  https://www.data.gov.in/backend/cms/v1/ogdp/cdo/<email>?_format=json

where <email> is written the way the portal shows it: "." -> " [dot] ",
"@" -> " [at] " (mohd [dot] salamuddin [at] rss [dot] sansad [dot] in).

The emails are the distinct cdo_email values of dublin_core_metadata,
dublin_core_remaining and dublin_core_lot3. Each is tried as stored (trimmed)
first; a malformed one ("raig@cag .gov.in", two addresses on two lines) is
then tried cleaned: first line, inner spaces dropped, lower case; and a
known typo (ALIASES) is tried corrected.

Responses are cached in data/cdo_api_details.json keyed by the stored email,
so a re-run only fetches what is missing (--refetch fetches all again).

cdo_details: one row per stored email --
  cdo_email, api_email (the form that answered), http_status, name,
  designation, phone, address, govt_type, ministry_department_ids,
  state_department_ids, provider_id, fetched_at

Usage:
  python fetch_cdo_details.py              # fetch missing, rebuild cdo_details
  python fetch_cdo_details.py --refetch
  python fetch_cdo_details.py --no-fetch   # rebuild the table from the cache
"""
import argparse
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
CACHE = HERE.parent.parent / "data" / "cdo_api_details.json"
API = "https://www.data.gov.in/backend/cms/v1/ogdp/cdo/{}?_format=json"
SOURCES = ["dublin_core_metadata", "dublin_core_remaining", "dublin_core_lot3"]
TABLE = "cdo_details"
DELAY = 0.5  # seconds between requests
# Stored emails with a typo the portal does not share: tried after the as-stored
# and cleaned forms. Found by hand 2026-10-14.
ALIASES = {
    "jdmi_south@ediffmail.com": "jdmi_south@rediffmail.com",
    "tnstcsalem@gmailccom": "tnstcsalem@gmail.com",
}


def portal_form(email: str) -> str:
    return email.replace(".", " [dot] ").replace("@", " [at] ")


def cleaned(email: str) -> str:
    first = email.strip().splitlines()[0]
    return "".join(first.split()).lower()


def fetch(email: str) -> tuple[int, dict | None]:
    url = API.format(urllib.parse.quote(portal_form(email), safe="[]"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, {"error": str(e)}


def found(status: int, body: dict | None) -> bool:
    """The API answers an unknown email with 200 and "data": []."""
    return status == 200 and bool((body or {}).get("data"))


def values(data: dict, key: str, sub: str = "value") -> list[str]:
    return [str(v.get(sub)) for v in (data.get(key) or []) if v.get(sub) is not None]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()

    # Read-only while fetching, so the database stays free for other work.
    with duckdb.connect(args.db, read_only=True) as con:
        emails = sorted({r[0] for t in SOURCES for r in con.execute(
            f"SELECT DISTINCT trim(cdo_email) FROM {t} WHERE trim(coalesce(cdo_email, '')) <> ''").fetchall()})
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    if not args.no_fetch:
        todo = [e for e in emails if args.refetch or e not in cache
                or not found(cache[e]["http_status"], cache[e]["body"])]
        print(f"{len(emails)} distinct emails, {len(todo)} to fetch")
        for i, email in enumerate(todo, 1):
            tries = [email] + ([cleaned(email)] if cleaned(email) != email else [])
            if email.lower() != email and email.lower() not in tries:
                tries.append(email.lower())
            if email in ALIASES:
                tries.append(ALIASES[email])
            for form in tries:
                status, body = fetch(form)
                time.sleep(DELAY)
                if found(status, body):
                    break
            cache[email] = {"api_email": form, "http_status": status, "body": body,
                            "fetched_at": dt.datetime.now().isoformat(timespec="seconds")}
            if i % 25 == 0 or i == len(todo):
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
                print(f"  {i}/{len(todo)}", flush=True)

    rows = []
    for email in emails:
        c = cache.get(email)
        if not c:
            continue
        d = (c["body"] or {}).get("data") or {}
        rows.append((
            email, c["api_email"], c["http_status"],
            "; ".join(values(d, "title")) or None,
            "; ".join(values(d, "field_designation")) or None,
            "; ".join(values(d, "field_dc_phone")) or None,
            "; ".join(values(d, "field_dc_address")) or None,
            "; ".join(values(d, "field_ds_govt_type")) or None,
            "; ".join(values(d, "field_dc_ministry_department", "target_id")) or None,
            "; ".join(values(d, "field_state_department", "target_id")) or None,
            str(d["provider_id"]) if d.get("provider_id") is not None else None,
            c["fetched_at"]))
    con = duckdb.connect(args.db)
    con.execute(f"""CREATE OR REPLACE TABLE {TABLE} (
        cdo_email VARCHAR, api_email VARCHAR, http_status INTEGER, name VARCHAR,
        designation VARCHAR, phone VARCHAR, address VARCHAR, govt_type VARCHAR,
        ministry_department_ids VARCHAR, state_department_ids VARCHAR,
        provider_id VARCHAR, fetched_at VARCHAR)""")
    con.executemany(f"INSERT INTO {TABLE} VALUES ({', '.join(['?'] * 12)})", rows)
    hits = sum(1 for r in rows if r[3] is not None)
    print(f"{TABLE}: {len(rows)} emails, {hits} found, {len(rows) - hits} not found")
    con.close()


if __name__ == "__main__":
    main()
