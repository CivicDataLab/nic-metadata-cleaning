import re
import csv
import time
import sys
from typing import List, Dict
import requests


OUT_CSV = "cdo_contacts_all.csv"
DELAY_BETWEEN = 0.7
TIMEOUT = 35
HEADERS_OUT = [
    # CDO fields
    "vCard:fn",
    "vcard:title",
    "vcard:role",
    "vcard:organization-name",
    "vcard:hasEmail",
    "vcard:hasAddress",
    "vcard:street-address",
    "vcard:postal-code",
    "vcard:locality",
    "title",


    #urls
                 
    "ref_url_html",         
    "sourced_webservices",  
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

EMAIL_FIXES = [
    (r"\s*\[at\]\s*", "@"), (r"\s*\(at\)\s*", "@"), (r"\bat\b", "@"),
    (r"\s*\[dot\]\s*", "."), (r"\s*\(dot\)\s*", "."), (r"\bdot\b", "."),
]

#emails like: "name [dot] surname [at] domain [dot] com"
def deobfuscate_email(text: str | None) -> str:
    if not text:
        return ""
    s = text
    for pat, rep in EMAIL_FIXES:
        s = re.sub(pat, rep, s, flags=re.I)
    s = re.sub(r"\s+", "", s)
    return s


def fetch_html(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def extract_nuxt_blob(html: str) -> str:
    # grab contents of any <script> ... </script>
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S | re.I)
    # prefer a script that has both window.__NUXT__ AND cdoDetails
    for s in scripts:
        if "window.__NUXT__" in s and "cdoDetails" in s:
            return s
    for s in scripts:
        if "window.__NUXT__" in s:
            return s
    return ""


def grab(pattern: str, text: str, flags=re.S) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""

def extract_html_links(html: str) -> Dict[str, str]:
    # Extract Reference URL of Resource and Sourced Webservices/APIs links directly from the HTML.


    ref_url_html = ""
    m_ref = re.search(
        r'<a[^>]*class=["\']ref_url["\'][^>]*>\s*([^<\s][^<]*)',
        html,
        flags=re.I
    )
    if m_ref:
        ref_url_html = m_ref.group(1).strip()

    # 2) Sourced Webservices/APIs:
    #    Links usually pointing to /datasets_webservices/...
    #    Example:
    #    <a href="/datasets_webservices/datasets/6737060" ...>
    sourced_ws_links = re.findall(
        r'<a[^>]+href=["\']([^"\']*datasets_webservices[^"\']*)["\']',
        html,
        flags=re.I,
    )

    full_links: List[str] = []
    for href in sourced_ws_links:
        href = href.strip()
        if not href:
            continue
        # make relative links absolute
        if href.startswith("/"):
            href = "https://www.data.gov.in" + href
        full_links.append(href)

    # de-duplicate while preserving order
    seen = set()
    deduped = []
    for link in full_links:
        if link not in seen:
            seen.add(link)
            deduped.append(link)

    sourced_webservices = " | ".join(deduped)

    return {
        "ref_url_html": ref_url_html,
        "sourced_webservices": sourced_webservices,
    }

def extract_cdo(nuxt: str) -> Dict[str, str]:
    """
    Pull CDO fields directly from the window.__NUXT__ blob.
    This avoids extra API calls and works with obfuscated email.
    """
    # name / title / address live under cdoDetails.data...
    name = grab(
        r'cdoDetails\s*:\s*\{.*?data\s*:\s*\{.*?title\s*:\s*\[\{\s*value\s*:\s*"([^"]+)"\}\]',
        nuxt,
    )
    title = grab(
        r'field_designation\s*:\s*\[\{\s*value\s*:\s*"([^"]+)"\}\]',
        nuxt,
    )
    address = grab(
        r'field_dc_address\s*:\s*\[\{\s*value\s*:\s*"([^"]+)"\}\]',
        nuxt,
    )

    # email: first try cdoDetails.email; else fallback to any obfuscated pattern in the blob
    email_raw = grab(
        r'cdoDetails\s*:\s*\{[^}]*?"email"\s*:\s*"([^"]+)"',
        nuxt,
    )
    if not email_raw:
        
        email_raw = grab(
            r'"([A-Za-z0-9.\s]+\[\s*dot\s*\]\s*[A-Za-z0-9.\s]+\s*\[\s*at\s*\]\s*[A-Za-z0-9.\s]+\s*\[\s*dot\s*\]\s*[A-Za-z0-9.\s]+)"',
            nuxt,
        )
    email = deobfuscate_email(email_raw)

    
    org_combo = grab(
        r'catalogData\s*:\s*\{.*?field_ministry_department\s*:\s*"([^"]+)"',
        nuxt,
    )
    org = " ; ".join(x.strip() for x in org_combo.split("||")) if org_combo else ""

    # best-effort postal/locality from address
    street = address or ""
    postal = ""
    locality = ""
    if address:
        m_pin = re.search(r"\b(\d{6})\b", address)
        postal = m_pin.group(1) if m_pin else ""
        parts = [p.strip() for p in address.split(",") if p.strip()]
        if parts:
            locality = parts[-1]

    return {
        "vCard:fn": name,
        "vcard:title": title,
        "vcard:role": "",  
        "vcard:organization-name": org,
        "vcard:hasEmail": email,
        "vcard:hasAddress": address,
        "vcard:street-address": street,
        "vcard:postal-code": postal,
        "vcard:locality": locality,
        "title": grab(
            r'catalogData\s*:\s*\{.*?title\s*:\s*"([^"]+)"',
            nuxt,
        ),
        "Source:": grab(
            r'catalogData\s*:\s*\{.*?source\s*:\s*"([^"]+)"',
            nuxt,
        ),
        "ref_url": grab(
            r'catalogData\s*:\s*\{.*?url\s*:\s*"([^"]+)"',
            nuxt,
        ),
    }


def process_all(urls: List[str], out_csv: str = OUT_CSV):
    rows = []
    for i, url in enumerate(urls, 1):
        try:
            html = fetch_html(url)
            nuxt = extract_nuxt_blob(html)
            if not nuxt:
                raise RuntimeError("window.__NUXT__ not found")


            rec = extract_cdo(nuxt)
            html_links = extract_html_links(html)
            rec.update(html_links)

            #ensure all columns exist
            rec = {**{h: "" for h in HEADERS_OUT}, **rec}
            rec["source_url"] = url
            rows.append(rec)
            print(f"[{i}/{len(urls)}] OK  {url}")
        except Exception as e:
            print(f"[{i}/{len(urls)}] ERR {url} -> {e}")
            err = {h: "" for h in HEADERS_OUT}
            err["source_url"] = url
            err["vcard:role"] = f"ERROR: {e}"
            rows.append(err)
        time.sleep(DELAY_BETWEEN)

    cols = ["source_url"] + HEADERS_OUT
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    print(f"Done. Wrote {out_csv} with {len(rows)} rows.")



if __name__ == "__main__":
    # read from a text file passed as first arg
    # (one URL per line)
    if len(sys.argv) >= 2:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            urls = [ln.strip() for ln in f if ln.strip()]
    else:

        urls = [
            "https://www.data.gov.in/resource/variety-wise-daily-market-prices-data-commodity",
            "https://www.data.gov.in/resource/kisan-call-centre-kcc-transcripts-farmers-queries-answers",
            "https://www.data.gov.in/resource/all-india-pincode-directory-till-last-month",
            "https://www.data.gov.in/resource/registrars-companies-roc-wise-company-master-data",
            "https://www.data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi",
            "https://www.data.gov.in/resource/list-msme-registered-units-under-udyam",
            "https://www.data.gov.in/resource/health-indicator-wise-monthly-datasets-sub-district-level-hmis",
            "https://www.data.gov.in/resource/real-time-air-quality-index-various-locations",
            "https://www.data.gov.in/resource/wholesale-price-index-base-year-2011-12-till-last-month",
            "https://www.data.gov.in/resource/daily-data-reservoir-level-central-water-commission-cwc",
            "https://www.data.gov.in/resource/all-india-and-stateut-wise-factsheets-national-family-health-survey-nfhs-5-2019-2021",
            "https://www.data.gov.in/resource/fdi-equity-inflows-year-2000-till-last-quarter",
            "https://www.data.gov.in/resource/india-districts-factsheets-national-family-health-survey-nfhs-5-2019-2021",
            "https://www.data.gov.in/resource/month-wise-all-india-crowdsourced-mobile-data-speed-measurement",
            "https://www.data.gov.in/resource/sub-divisional-monthly-rainfall-1901-2017",
            "https://www.data.gov.in/resource/voice-call-quality-customer-experience-till-last-month",
            "https://www.data.gov.in/resource/wholesale-price-index-base-year-2011-12-till-last-financial-year",
            "https://www.data.gov.in/resource/indian-railways-time-table-trains-available-reservation-01112017",
            "https://www.data.gov.in/resource/daily-data-soil-moisture",
            "https://www.data.gov.in/resource/seasonal-and-annual-mean-temperature-series-period-1901-2021",
            "https://www.data.gov.in/resource/district-wise-season-wise-crop-production-statistics-1997",
            "https://www.data.gov.in/resource/global-youth-tobacco-survey-gyts-4-india-and-states-2019",
            "https://www.data.gov.in/resource/local-government-directory-lgd-villages-pin-codes",
            "https://www.data.gov.in/resource/local-government-directory-lgd-local-bodies-pin-codes",
            "https://www.data.gov.in/resource/industry-state-and-year-wise-startups-recognized-dpiit-till-last-week",
            "https://www.data.gov.in/resource/crime-head-wise-police-disposal-ipc-crime-cases-crime-head-wise-during-2019",
            "https://www.data.gov.in/resource/district-wise-total-msme-registered-enterprises-under-udyam-registration-till-last-date",
            "https://www.data.gov.in/resource/shapefile-rivers",
            "https://www.data.gov.in/resource/rainfall-all-india-and-its-departure-normal-during-monsoon-session-june-sept-1901-2019",
            "https://www.data.gov.in/resource/enrolment-age-and-class-udise-plus-during-2012-13",
            "https://www.data.gov.in/resource/district-wise-services-msme-registered-enterprises-under-udyam-registration-till-last-date",
            "https://www.data.gov.in/resource/seasonal-and-annual-minmax-temp-series-india-1901-2017",
            "https://www.data.gov.in/resource/daily-data-evapotranspiration-nrsc",
            "https://www.data.gov.in/resource/district-wise-disability-wise-age-group-wise-gender-wise-unique-disability-id-udid-data",
            "https://www.data.gov.in/resource/all-india-consumer-price-index-ruralurban-upto-may-2023",
            "https://www.data.gov.in/resource/all-india-area-weighted-monthly-seasonal-and-annual-rainfall-mm-1901-2015",
            "https://www.data.gov.in/resource/crime-head-wise-police-disposal-ipc-crime-cases-during-2021",
            "https://www.data.gov.in/resource/foreign-tourist-arrivals-ftas-arrivals-non-resident-indians-nris-and-international-0",
            "https://www.data.gov.in/resource/enrolment-age-and-class-udise-plus-during-2019-20",
            "https://www.data.gov.in/resource/year-wise-retail-inflation-rate-based-consumer-price-index-combined-cpi-c-2017-18-2022-23",
            "https://www.data.gov.in/resource/gsva-economic-activity-current-prices-tamil-nadu-2011-12-2016-17-31032017",
            "https://www.data.gov.in/resource/district-wise-demographic-data-unorganised-workers-registered-eshram-previous-day",
            "https://www.data.gov.in/resource/monthly-crude-oil-processed-refineries",
            "https://www.data.gov.in/resource/statistics-road-accidents-india-2013-2016",
            "https://www.data.gov.in/resource/cbse-result-statistics-class-xii-2023",
            "https://www.data.gov.in/resource/district-wise-availability-health-centres-india-31st-march-2017",
            "https://www.data.gov.in/resource/area-weighted-monthly-seasonal-and-annual-rainfall-mm-36-meteorological-subdivisions-1901",
            "https://www.data.gov.in/resource/monthly-mean-maximum-minimum-temperature-and-total-rainfall-based-upon-1901-2000-data-3",
            "https://www.data.gov.in/resource/monthly-consumption-petroleum-products",
            "https://www.data.gov.in/resource/state-wise-population-decadal-population-growth-rate-and-population-density-2011",
            "https://www.data.gov.in/resource/district-wise-total-msme-registered-manufacturing-enterprises-till-last-date",
            "https://www.data.gov.in/resource/district-wise-mgnrega-data-glance",
            "https://www.data.gov.in/resource/district-level-manufacturing-msme-registered-enterprises-under-udyam-registration-till",
            "https://www.data.gov.in/resource/indian-sign-language-dictionary-till-january-2024",
            "https://www.data.gov.in/resource/percentage-households-having-electricity-improved-source-drinking-water-having-access",
            "https://www.data.gov.in/resource/district-rainfall-normal-mm-monthly-seasonal-and-annual-data-period-1951-2000",
            "https://www.data.gov.in/resource/location-wise-daily-ambient-air-quality-tamil-nadu-year-2014",
            "https://www.data.gov.in/resource/district-wise-number-poultry-farms-and-poultry-birds-farms-2007-tamil-nadu",
            "https://www.data.gov.in/resource/longitudinal-ageing-study-india-lasi-wave-i-2017-18",
            "https://www.data.gov.in/resource/state-level-consumer-price-index-ruralurban-upto-november-2021",
            "https://www.data.gov.in/resource/number-newly-registered-motor-vehicles-2009-10-and-2010-11-and-number-registered-motor-22",
            "https://www.data.gov.in/resource/stateut-wise-district-score-during-2021-22",
            "https://www.data.gov.in/resource/seasonal-and-annual-minimum-maximum-temperature-series-period-1901-2021",
            "https://www.data.gov.in/resource/shape-watershed-boundaries-india",
            "https://www.data.gov.in/resource/number-newly-registered-motor-vehicles-2011-12-and-number-registered-motor-vehicles-31st-7",
            "https://www.data.gov.in/resource/total-number-registered-motor-vehicles-india-during-1951-2013",
            "https://www.data.gov.in/resource/year-wise-annual-frequency-cyclones-34-knots-or-more-and-severe-cyclones-48-knots-or-more",
            "https://www.data.gov.in/resource/weekly-patent-application-granted",
            "https://www.data.gov.in/resource/monthly-seasonal-and-annual-mean-temperature-series-period-1901-2021",
            "https://www.data.gov.in/resource/eight-core-industries-base-year-2011-12-till-last-financial-year",
            "https://www.data.gov.in/resource/list-all-startups-meity-startup-hub",
            "https://www.data.gov.in/resource/list-msme-registered-units-under-udyog-aadhaar-memorandum-maharashtra",
            "https://www.data.gov.in/resource/imports-major-chemical-product-wise-group-wise-2014-15-2021-22",
            "https://www.data.gov.in/resource/subdivision-wise-rainfall-and-its-departure-1901-2015",
            "https://www.data.gov.in/resource/daily-rainfall-data-india-meteorological-department-imd-grid-model-agency-during-july-2023",
            "https://www.data.gov.in/resource/elephant-population-1993-2017",
            "https://www.data.gov.in/resource/web-map-service-362-osm-topo-sheets-survey-india-and-panchromatic-imagery-bhuvan-andhra",
            "https://www.data.gov.in/resource/inbound-tourism-foreign-tourist-arrivals-arrivals-non-resident-indians-and-international",
            "https://www.data.gov.in/resource/state-level-consumer-price-index-ruralurban-upto-may-2023",
            "https://www.data.gov.in/resource/delivery-post-office-pincode-boundary",
            "https://www.data.gov.in/resource/district-wise-tele-law-case-registration-and-advice-enabled-data-fy-2021-22-2022-23",
            "https://www.data.gov.in/resource/stateut-wise-details-rainfall-observed-during-monsoon-season-2020-2022",
            "https://www.data.gov.in/resource/eight-core-industries-base-year-2011-12-till-last-month",
            "https://www.data.gov.in/resource/stateut-wise-number-udid-card-generated-28072021",
            "https://www.data.gov.in/resource/state-wise-details-youth-hostels-2023",
            "https://www.data.gov.in/resource/import-export-petroleum-products-volumes-year-2022-23",
            "https://www.data.gov.in/resource/quarterly-estimates-gdp-constant-2011-12-prices-2011-12-2022-23",
            "https://www.data.gov.in/resource/stateut-wise-number-indian-penal-code-ipc-crimes-2020-2022",
            "https://www.data.gov.in/resource/list-msme-registered-units-under-udyog-aadhaar-memorandum-andhra-pradesh",
            "https://www.data.gov.in/resource/rainfall-ne-india-and-its-departure-normal-monsoon-session-1901-2021",
            "https://www.data.gov.in/resource/digital-seismotectonic-atlas-india-and-its-environs-0",
            "https://www.data.gov.in/resource/disclosed-ground-water-level-data-under-atal-bhujal-yojana-2015-2022",
            "https://www.data.gov.in/resource/digital-seismotectonic-atlas-india-and-its-environs",
            "https://www.data.gov.in/resource/number-newly-registered-motor-vehicles-2009-10-and-2010-11-and-number-registered-motor-25",
            "https://www.data.gov.in/resource/quarterly-estimates-gdp-current-prices-2011-12-series-2011-12-2022-23",
            "https://www.data.gov.in/resource/boundaries-agro-climatic-regions",
            "https://www.data.gov.in/resource/state-wise-population-decadal-population-growth-rate-and-population-density-2011-0",
            "https://www.data.gov.in/resource/state-wise-details-infant-mortality-rate-institutional-delivery-and-prevalence-under",
            "https://www.data.gov.in/resource/sector-wise-estimated-number-workers-under-fourth-round-quarterly-employment-survey-jan",
            "https://www.data.gov.in/resource/shape-file-reservoir",
        ]
    process_all(urls)
