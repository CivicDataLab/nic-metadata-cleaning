import pandas as pd, re, os, json

input_path = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/notebooks/results_100_with_separate_link.csv"
output_path = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/notebooks/results_100_reordered.csv"

df = pd.read_csv(input_path, dtype=str, keep_default_na=False)

queue_text = """/resource/variety-wise-daily-market-prices-data-commodity
/resource/kisan-call-centre-kcc-transcripts-farmers-queries-answers
https://www./resource/all-india-pincode-directory-till-last-month
/resource/registrars-companies-roc-wise-company-master-data
/resource/current-daily-price-various-commodities-various-markets-mandi
/resource/list-msme-registered-units-under-udyam
/resource/health-indicator-wise-monthly-datasets-sub-district-level-hmis
/resource/real-time-air-quality-index-various-locations
/resource/wholesale-price-index-base-year-2011-12-till-last-month
/resource/daily-data-reservoir-level-central-water-commission-cwc
/resource/all-india-and-stateut-wise-factsheets-national-family-health-survey-nfhs-5-2019-2021
/resource/fdi-equity-inflows-year-2000-till-last-quarter
/resource/india-districts-factsheets-national-family-health-survey-nfhs-5-2019-2021
/resource/month-wise-all-india-crowdsourced-mobile-data-speed-measurement
/resource/sub-divisional-monthly-rainfall-1901-2017
/resource/voice-call-quality-customer-experience-till-last-month
/resource/wholesale-price-index-base-year-2011-12-till-last-financial-year
/resource/indian-railways-time-table-trains-available-reservation-01112017
/resource/daily-data-soil-moisture
/resource/seasonal-and-annual-mean-temperature-series-period-1901-2021
/resource/district-wise-season-wise-crop-production-statistics-1997
/resource/global-youth-tobacco-survey-gyts-4-india-and-states-2019
/resource/local-government-directory-lgd-villages-pin-codes
/resource/local-government-directory-lgd-local-bodies-pin-codes
https://www./resource/industry-state-and-year-wise-startups-recognized-dpiit-till-last-week
/resource/crime-head-wise-police-disposal-ipc-crime-cases-crime-head-wise-during-2019
/resource/district-wise-total-msme-registered-enterprises-under-udyam-registration-till-last-date
/resource/shapefile-rivers
/resource/rainfall-all-india-and-its-departure-normal-during-monsoon-session-june-sept-1901-2019
/resource/enrolment-age-and-class-udise-plus-during-2012-13
/resource/district-wise-services-msme-registered-enterprises-under-udyam-registration-till-last-date
/resource/seasonal-and-annual-minmax-temp-series-india-1901-2017
/resource/daily-data-evapotranspiration-nrsc
/resource/district-wise-disability-wise-age-group-wise-gender-wise-unique-disability-id-udid-data
/resource/all-india-consumer-price-index-ruralurban-upto-may-2023
/resource/all-india-area-weighted-monthly-seasonal-and-annual-rainfall-mm-1901-2015
/resource/crime-head-wise-police-disposal-ipc-crime-cases-during-2021
/resource/foreign-tourist-arrivals-ftas-arrivals-non-resident-indians-nris-and-international-0
/resource/enrolment-age-and-class-udise-plus-during-2019-20
/resource/year-wise-retail-inflation-rate-based-consumer-price-index-combined-cpi-c-2017-18-2022-23
/resource/gsva-economic-activity-current-prices-tamil-nadu-2011-12-2016-17-31032017
/resource/district-wise-demographic-data-unorganised-workers-registered-eshram-previous-day
/resource/monthly-crude-oil-processed-refineries
/resource/statistics-road-accidents-india-2013-2016
/resource/cbse-result-statistics-class-xii-2023
/resource/district-wise-availability-health-centres-india-31st-march-2017
/resource/area-weighted-monthly-seasonal-and-annual-rainfall-mm-36-meteorological-subdivisions-1901
/resource/monthly-mean-maximum-minimum-temperature-and-total-rainfall-based-upon-1901-2000-data-3
/resource/monthly-consumption-petroleum-products
/resource/state-wise-population-decadal-population-growth-rate-and-population-density-2011
/resource/district-wise-total-msme-registered-manufacturing-enterprises-till-last-date
/resource/district-wise-mgnrega-data-glance
/resource/district-level-manufacturing-msme-registered-enterprises-under-udyam-registration-till
/resource/indian-sign-language-dictionary-till-january-2024
/resource/percentage-households-having-electricity-improved-source-drinking-water-having-access
/resource/district-rainfall-normal-mm-monthly-seasonal-and-annual-data-period-1951-2000
/resource/location-wise-daily-ambient-air-quality-tamil-nadu-year-2014
/resource/district-wise-number-poultry-farms-and-poultry-birds-farms-2007-tamil-nadu
/resource/longitudinal-ageing-study-india-lasi-wave-i-2017-18
/resource/state-level-consumer-price-index-ruralurban-upto-november-2021
/resource/number-newly-registered-motor-vehicles-2009-10-and-2010-11-and-number-registered-motor-22
/resource/stateut-wise-district-score-during-2021-22
/resource/seasonal-and-annual-minimum-maximum-temperature-series-period-1901-2021
/resource/shape-watershed-boundaries-india
/resource/number-newly-registered-motor-vehicles-2011-12-and-number-registered-motor-vehicles-31st-7
/resource/total-number-registered-motor-vehicles-india-during-1951-2013
/resource/year-wise-annual-frequency-cyclones-34-knots-or-more-and-severe-cyclones-48-knots-or-more
/resource/weekly-patent-application-granted
/resource/monthly-seasonal-and-annual-mean-temperature-series-period-1901-2021
/resource/eight-core-industries-base-year-2011-12-till-last-financial-year
/resource/list-all-startups-meity-startup-hub
/resource/list-msme-registered-units-under-udyog-aadhaar-memorandum-maharashtra
/resource/imports-major-chemical-product-wise-group-wise-2014-15-2021-22
/resource/subdivision-wise-rainfall-and-its-departure-1901-2015
/resource/daily-rainfall-data-india-meteorological-department-imd-grid-model-agency-during-july-2023
/resource/elephant-population-1993-2017
/resource/web-map-service-362-osm-topo-sheets-survey-india-and-panchromatic-imagery-bhuvan-andhra
/resource/inbound-tourism-foreign-tourist-arrivals-arrivals-non-resident-indians-and-international
/resource/state-level-consumer-price-index-ruralurban-upto-may-2023
https://www./resource/delivery-post-office-pincode-boundary
/resource/district-wise-tele-law-case-registration-and-advice-enabled-data-fy-2021-22-2022-23
/resource/stateut-wise-details-rainfall-observed-during-monsoon-season-2020-2022
/resource/eight-core-industries-base-year-2011-12-till-last-month
/resource/stateut-wise-number-udid-card-generated-28072021
/resource/state-wise-details-youth-hostels-2023
/resource/import-export-petroleum-products-volumes-year-2022-23
/resource/quarterly-estimates-gdp-constant-2011-12-prices-2011-12-2022-23
/resource/stateut-wise-number-indian-penal-code-ipc-crimes-2020-2022
/resource/list-msme-registered-units-under-udyog-aadhaar-memorandum-andhra-pradesh
/resource/rainfall-ne-india-and-its-departure-normal-monsoon-session-1901-2021
/resource/digital-seismotectonic-atlas-india-and-its-environs-0
/resource/disclosed-ground-water-level-data-under-atal-bhujal-yojana-2015-2022
/resource/digital-seismotectonic-atlas-india-and-its-environs
/resource/number-newly-registered-motor-vehicles-2009-10-and-2010-11-and-number-registered-motor-25
/resource/quarterly-estimates-gdp-current-prices-2011-12-series-2011-12-2022-23
/resource/boundaries-agro-climatic-regions
/resource/state-wise-population-decadal-population-growth-rate-and-population-density-2011-0
/resource/state-wise-details-infant-mortality-rate-institutional-delivery-and-prevalence-under
/resource/sector-wise-estimated-number-workers-under-fourth-round-quarterly-employment-survey-jan
/resource/shape-file-reservoir
"""

queue = [line.strip() for line in queue_text.splitlines() if line.strip()]

def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

order_map = {}
for i, t in enumerate(queue):
    nt = norm(t)
    if nt not in order_map:
        order_map[nt] = i

title_col = "link" if "link" in df.columns else df.columns[0]

df["_order"] = df[title_col].apply(lambda x: order_map.get(norm(x), 10**9))
df["_orig_idx"] = range(len(df))

df_sorted = df.sort_values(by=["_order", "_orig_idx"], kind="mergesort").drop(columns=["_order", "_orig_idx"])
df_sorted.to_csv(output_path, index=False, encoding="utf-8")
output_path
