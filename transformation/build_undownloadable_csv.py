import pandas as pd, duckdb, sys
from urllib.parse import urlparse

EXCLUDE_CENSUS = '--exclude-census' in sys.argv
SNAP = 'transformation/undownloadable_meta_snapshot.parquet'
STRICT = 'transformation/undownloadable_host_status.csv'

meta = duckdb.connect().execute(f"SELECT * FROM read_parquet('{SNAP}')").fetchdf()
meta['uuid'] = meta['uuid'].astype(str)
meta['host'] = meta['datafile_url'].fillna('').apply(lambda u: urlparse(u).netloc if u else '')

# sanity: census rows must be populated (explains old all-blank CSV if not)
cen = meta[meta['host'].str.contains('census', na=False)]
print(f"[sanity] census rows in snapshot: {len(cen)} | with title: {cen['title'].notna().sum()} | with url: {cen['datafile_url'].notna().sum()}")

def landing(r):
    na = r.get('node_alias')
    if isinstance(na, str) and na.strip():
        na = na.strip(); return 'https://www.data.gov.in' + (na if na.startswith('/') else '/'+na)
    ru = r.get('Reference_url'); return ru.strip() if isinstance(ru, str) and ru.strip() else ''
meta['landing_page'] = meta.apply(landing, axis=1)

strict = pd.read_csv(STRICT).dropna(subset=['host'])
host_status = dict(zip(strict['host'].astype(str), strict['status']))

# hosts where a failure is just the pre-fix SSL issue and WOULD recover with verify=False
# (ssl_recoverable hosts EXCEPT censusindia.gov.in, whose files genuinely 404).
# Match censusindia exactly so wrcensus.mowr.gov.in (also ssl_recoverable, genuinely downloads) stays recoverable.
RECOVERABLE_SSL_HOSTS = {h for h, s in host_status.items() if s == 'ssl_recoverable' and h != 'censusindia.gov.in'}
# truly-dead external hosts the run never attempts; EXCLUDE data.gov.in (mis-flagged; serves 42,904) + blank host
NOT_DEAD = {'data.gov.in', 'api.data.gov.in', ''}
UNREACHABLE_HOSTS = {h for h, s in host_status.items() if s == 'unreachable' and h not in NOT_DEAD}

log = pd.read_csv('data/final_dataset_download_log.csv').drop_duplicates(subset='uuid', keep='last')
log['uuid'] = log['uuid'].astype(str)
st = dict(zip(log['uuid'], log['status']))
dt = dict(zip(log['uuid'], log['detail']))
failed_uuids  = set(log.loc[log['status'] == 'failed',  'uuid'])
success_uuids = set(log.loc[log['status'] == 'success', 'uuid'])

meta['status']      = meta['uuid'].map(st).fillna('not_attempted')
meta['host_status'] = meta['host'].map(host_status).fillna('not_probed')
meta['detail']      = meta['uuid'].map(dt).fillna('')

# recoverable-ssl failures: exclude from undownloadable, queue for retry after the run
meta['recoverable_ssl_fail'] = meta['uuid'].isin(failed_uuids) & meta['host'].isin(RECOVERABLE_SSL_HOSTS)

# INCLUSION = (log-failed, minus recoverable-ssl) OR (on a truly-dead host, never attempted); minus any success
attempted_fail = meta['uuid'].isin(failed_uuids) & (~meta['recoverable_ssl_fail'])
dead_host      = meta['host'].isin(UNREACHABLE_HOSTS)
mask = (attempted_fail | dead_host) & (~meta['uuid'].isin(success_uuids))
rows = meta[mask].copy()

if EXCLUDE_CENSUS:
    rows = rows[~rows['host'].str.contains('census', na=False)].copy()

def why(r):
    if r['uuid'] in failed_uuids:
        d = str(r['detail']).lower()
        if '404' in d: kind = '404_file_missing'
        elif 'timed out' in d or 'timeout' in d: kind = 'timeout'
        elif 'ssl' in d: kind = 'ssl'
        elif 'unable to' in d or 'error body' in d: kind = 'dms_unavailable'
        elif 'connection' in d or 'refused' in d or 'resolve' in d: kind = 'conn_error'
        else: kind = 'other'
        return f'attempted_failed[{kind}]: ' + str(r['detail'])[:90]
    return 'host_unreachable (not attempted; host down)'
rows['fail_reason']   = rows.apply(why, axis=1)
rows['download_status'] = rows['status']
rows['download_detail'] = rows['detail']
rows['recoverable_via_ssl_off'] = False   # everything included here genuinely failed even with the SSL fix

cols = ['uuid','nid','title','field_resource_type','resource_category','host','host_status',
        'recoverable_via_ssl_off','datafile_url','landing_page','ministry_department','state_department',
        'download_status','download_detail','fail_reason']
rows = rows[cols]
# drop any blank rows (empty uuid) before writing
before = len(rows)
rows = rows[rows['uuid'].notna() & (rows['uuid'].astype(str).str.strip() != '') & (rows['uuid'].astype(str).str.lower() != 'nan')]
rows = rows.sort_values(['host_status','host','field_resource_type','title'])
rows.to_csv('data/undownloadable_datasets.csv', index=False)
print(f"[write] dropped {before-len(rows)} blank-uuid rows")

# host summary
hs = rows.groupby(['host','host_status']).size().reset_index(name='datasets').sort_values(['host_status','datasets'], ascending=[True,False])
hs.to_csv('data/undownloadable_hosts_summary.csv', index=False)

# retry queue: recoverable-ssl failures (would succeed with the fix once log rows are cleared)
rq = meta[meta['recoverable_ssl_fail']][['uuid','host','detail']]
rq.to_csv('data/recoverable_ssl_retry_queue.csv', index=False)

print(f"\nWROTE data/undownloadable_datasets.csv -> {len(rows)} rows (exclude_census={EXCLUDE_CENSUS})")
print("successes leaked:", (rows['download_status']=='success').sum(), "| blank rows:", (rows['uuid'].astype(str).str.strip()=='').sum())
print("\nby fail_reason bucket:")
print(rows['fail_reason'].str.extract(r'^(attempted_failed\[[a-z_0-9]+\]|host_unreachable)')[0].value_counts().to_string())
print("\nby host_status:"); print(rows['host_status'].value_counts().to_string())
print("\ntop hosts:"); print(rows['host'].value_counts().head(12).to_string())
print("\ncensus rows in output:", rows['host'].str.contains('census', na=False).sum())
print("recoverable-ssl failures excluded + queued for retry:", len(rq))
