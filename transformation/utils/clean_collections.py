"""
Clean collections in the `dublin_core_metadata` sheet.

Three passes (per user spec):
  1. HEADER MERGEABILITY  (only collections with 2 or 3 datasets)
       Compare members' `Conforms To` headers (normalized, temporal/spatial/noise
       stripped). If the members don't overlap enough (Jaccard < HDR_JACCARD) the
       collection isn't really mergeable -> clear Collection / merge_method /
       merge_add_columns on those rows.
  2. DUPLICATE TITLES     (only collections with 2 or 3 datasets)
       Two members are duplicates iff their dimension-stripped base concept is
       near-identical (ratio >= DUP_RATIO) AND their extracted year/state/district
       values are equal. (Same base but DIFFERENT year/state = the legitimate merge
       the collection exists for -> NOT a duplicate.) Any duplicate pair -> the
       whole collection is eliminated (same clearing as pass 1).
  3. SPATIAL / TEMPORAL    (all surviving collections, any size)
       Recompute merge_add_columns: if the collection varies by state/district/year
       but that discriminator column is absent from the headers, add it.

Dry-run (default) works off the cached subset pickle and only prints a report.
Pass --write to load the full workbook and write the cleaned sheet to a new file.

Usage:
  python clean_collections.py            # dry-run report (uses /tmp/meta_subset.pkl)
  python clean_collections.py --write    # produce dublin_core_metadata_cleaned.xlsx
"""
import sys, os, re
from itertools import combinations
import pandas as pd, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detector as D

SRC_XLSX   = 'dublin_core_metadata_main.xlsx'
SHEET      = 'dublin_core_metadata'
OUT_XLSX   = 'dublin_core_metadata_cleaned.xlsx'
SUBSET_PKL = '/tmp/meta_subset.pkl'

HDR_JACCARD = 0.50   # pass 1: min normalized-header overlap to stay merged
CONTAIN_THR = 0.70   # pass 1: rescue threshold for prefixed/suffixed headers
DUP_RATIO   = 0.90   # pass 2: min word-set similarity to call a duplicate
# thresholds overridable from the CLI: --hdr 0.5 --dup 0.9

# ----------------------------------------------------------------- helpers
# header tokens that are organizational, not data (serial no., note columns)
NOISE = re.compile(r'^(s\s*no|sl\s*no|sr\s*no|sno|note.*)$')

def clean_sig(conforms_to):
    """Normalized data-header set for mergeability comparison.
    Per token: detector.norm_token (lowercase, temporal/spatial stripped), drop
    serial-number / note noise, then strip ALL digits and whitespace. Digits are
    removed because years are frequently FUSED into header names
    ('Achievements 2010-11' -> 'achievements201011') and single-digit footnote
    markers drift ('Required R1' vs 'Required R'); without this, legitimately
    year-varying collections look disjoint. Spaceless also absorbs spacing
    artifacts ('Sanctioned S' vs 'SanctionedS')."""
    out = set()
    for h in D.header_list(conforms_to):
        n = D.norm_token(h)
        if not n or NOISE.match(n):
            continue
        n = re.sub(r'\d+', '', n).replace(' ', '')
        if n:
            out.add(n)
    return frozenset(out)

def coll_jaccard(sigs):
    """Global intersection-over-union across all member header sets."""
    sets = [set(s) for s in sigs]
    union = set().union(*sets) if sets else set()
    if not union:
        return 0.0
    inter = set.intersection(*sets)
    return len(inter) / len(union)

def contain_overlap(sigs):
    """Fraction of the SMALLEST member's tokens that appear (exactly or as a
    substring) in EVERY other member. Catches the common NIC pattern where one
    member prefixes each column with the metric name ('Doctors at PHCs Required R'
    vs 'Required R') - same schema, but exact-set Jaccard reads near zero.
    Returns 0 unless every member has a non-empty signature."""
    sigs = [set(s) for s in sigs]
    if len(sigs) < 2 or not all(sigs):
        return 0.0
    base = min(sigs, key=len)
    matched = sum(1 for t in base
                  if all(any(t == u or t in u or u in t for u in s) for s in sigs))
    return matched / len(base)

def is_mergeable(sigs):
    """A collection is mergeable if members share enough normalized headers OR
    one member merely prefixes/suffixes the shared columns (containment)."""
    return coll_jaccard(sigs) >= HDR_JACCARD or contain_overlap(sigs) >= CONTAIN_THR

YEAR_RE = re.compile(r'(?:19|20)\d{2}')

def title_key(t):
    """(base_concept, state, district, frozenset(years)) used by pass-3 variation."""
    base, state, dist, _ = D.decompose_title(t)
    years = frozenset(YEAR_RE.findall(str(t)))
    return base, state, dist, years

def title_wordset(t):
    """Content tokens of a title with temporal tokens removed, punctuation dropped.
    PLACE words are KEPT - so two titles differing only by district/state name
    (Anjaw vs Tirap) have different sets and are NOT duplicates. DIGITS are KEPT
    (years already removed by TEMPORAL_RE) so edition/dose numbers distinguish
    datasets ('(5th Dose)' vs '(9th Dose)' are not duplicates)."""
    s = str(t).lower()
    s = D.TEMPORAL_RE.sub(' ', s)
    s = re.sub(r'[^a-z0-9 ]', ' ', s)      # drop punctuation; keep letters+digits
    return frozenset(w for w in s.split() if len(w) > 1)

def is_duplicate(a, b):
    """True iff a and b are the SAME dataset reworded: identical year set AND
    near-identical word content (>= DUP_RATIO Jaccard). Different year OR different
    place words -> not a duplicate (it's a legitimate merge dimension)."""
    if frozenset(YEAR_RE.findall(str(a))) != frozenset(YEAR_RE.findall(str(b))):
        return False
    wa, wb = title_wordset(a), title_wordset(b)
    if not wa or not wb:
        return False
    j = len(wa & wb) / len(wa | wb)
    return j >= DUP_RATIO

def augment_addcols(sub, current):
    """merge_add_columns for a surviving collection. AUGMENT-only: keep every
    discriminator already listed (the source pipeline's variation detection is
    stronger than title parsing alone), and ADD a spatial/temporal discriminator
    when the collection varies by it but no such column exists in the headers.
    Never removes an existing dimension."""
    have = set() if pd.isna(current) or not str(current).strip() else \
        {d.strip() for d in str(current).split(',') if d.strip()}

    raw_union = set()
    for h in sub['Conforms To']:
        raw_union |= {x.strip().lower() for x in D.header_list(h)}
    has_state = any('state' in c for c in raw_union)
    has_dist  = any('district' in c for c in raw_union)
    has_year  = any(re.search(r'\byear\b', c) for c in raw_union)
    has_month = any(re.search(r'\bmonth\b', c) for c in raw_union)

    keys = [title_key(t) for t in sub['Title']]
    varies_state = len({k[1] for k in keys if k[1] is not None}) > 1
    varies_dist  = len({k[2] for k in keys if k[2] is not None}) > 1
    varies_year  = len({k[3] for k in keys if k[3]}) > 1

    if varies_state and not has_state: have.add('state')
    if varies_dist  and not has_dist:  have.add('district')
    if varies_year  and not (has_year or has_month): have.add('year')

    order = {'state': 0, 'district': 1, 'year': 2}
    return ','.join(sorted(have, key=lambda d: order.get(d, 9)))

# ----------------------------------------------------------------- core
def compute(df):
    """Return (clear_set, addcols_map, report_dict). df needs Title/Conforms To/
    Collection columns."""
    coll = df[df['Collection'].notna()]
    sizes = coll.groupby('Collection').size()

    clear_set = set()           # collections to dissolve
    broken, dups = [], []       # for reporting
    jdist = []                  # (collection, jaccard) for all small collections
    small = sizes[(sizes == 2) | (sizes == 3)].index

    for c in small:
        sub = coll[coll['Collection'] == c]
        # pass 1: header mergeability (exact-overlap OR prefixed/suffixed columns)
        sigs = [clean_sig(h) for h in sub['Conforms To']]
        j = coll_jaccard(sigs)
        jdist.append((c, j))
        if not is_mergeable(sigs):
            clear_set.add(c); broken.append((c, round(j, 2))); continue
        # pass 2: duplicate titles
        titles = list(sub['Title'])
        if any(is_duplicate(a, b) for a, b in combinations(titles, 2)):
            clear_set.add(c); dups.append(c)

    # current add_columns per collection (first non-null member value)
    cur = (coll.groupby('Collection')['merge_add_columns']
              .agg(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan))

    # pass 3: augment add_columns for survivors (all sizes)
    addcols_map = {}
    for c in sizes.index:
        if c in clear_set:
            continue
        addcols_map[c] = augment_addcols(coll[coll['Collection'] == c], cur.get(c))

    report = dict(
        total_collections=int(sizes.size),
        small_collections=int(len(small)),
        broken_headers=broken,
        duplicates=dups,
        cleared_total=len(clear_set),
        addcols_map=addcols_map,
        jdist=jdist,
    )
    return clear_set, addcols_map, report

def print_report(df, clear_set, addcols_map, report):
    print('=== collection cleaning report ===')
    print('total collections        :', report['total_collections'])
    print('2-3 dataset collections  :', report['small_collections'])
    print('broken (header mismatch) :', len(report['broken_headers']))
    print('eliminated (duplicates)  :', len(report['duplicates']))
    print('collections dissolved    :', report['cleared_total'])

    coll = df[df['Collection'].notna()]
    cleared_rows = coll['Collection'].isin(clear_set).sum()
    print('dataset rows un-collected:', int(cleared_rows))

    # add_columns change summary vs current value (mode per collection)
    cur = (coll.groupby('Collection')['merge_add_columns']
              .agg(lambda s: s.dropna().iloc[0] if s.notna().any() else ''))
    changed = sum(1 for c, v in addcols_map.items()
                  if str(cur.get(c, '')) != str(v) and not (pd.isna(cur.get(c)) and v == ''))
    print('add_columns recomputed   :', len(addcols_map), '| changed vs current:', changed)

    # header-Jaccard distribution to calibrate HDR_JACCARD
    js = sorted(j for _, j in report['jdist'])
    bins = [0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    print('\n-- header-Jaccard distribution (250 small collections) --')
    for lo, hi in zip(bins, bins[1:]):
        n = sum(1 for x in js if lo <= x < hi)
        print(f'  [{lo:.1f},{hi:.1f}): {"#"*n} {n}')
    for thr in (0.5, 0.6, 0.7, 0.8):
        print(f'  would break at thr={thr}: {sum(1 for x in js if x < thr)}')

    print('\n-- sample broken (collection, header Jaccard) --')
    for c, j in report['broken_headers'][:12]:
        print(f'  {j}  {c[:70]}')
    print('\n-- sample duplicates eliminated --')
    for c in report['duplicates'][:12]:
        print(f'  {c[:70]}')
    print('\n-- sample add_columns changes (augment-only) --')
    shown = 0
    for c, v in addcols_map.items():
        old = '' if pd.isna(cur.get(c)) else str(cur.get(c))
        if old != str(v):
            print(f'  [{old or "-"}] -> [{v or "-"}]  {c[:55]}')
            shown += 1
            if shown >= 15:
                break

    print('\n-- VERIFY duplicate eliminations (member titles) --')
    for c in report['duplicates'][:8]:
        print(f'  COLLECTION: {c[:75]}')
        for t in coll.loc[coll['Collection'] == c, 'Title']:
            print(f'      - {str(t)[:90]}')

def apply_to_full(df, clear_set, addcols_map):
    dec = df['Collection'].map(lambda c: 'clear' if c in clear_set else
                               ('keep' if pd.notna(c) else None))
    clear = dec == 'clear'
    df.loc[clear, ['Collection', 'merge_method', 'merge_add_columns']] = np.nan
    keep = dec == 'keep'
    df.loc[keep, 'merge_add_columns'] = (
        df.loc[keep, 'Collection'].map(addcols_map).replace('', np.nan))
    return df

# ----------------------------------------------------------------- main
def main():
    global HDR_JACCARD, DUP_RATIO
    if '--hdr' in sys.argv: HDR_JACCARD = float(sys.argv[sys.argv.index('--hdr') + 1])
    if '--dup' in sys.argv: DUP_RATIO   = float(sys.argv[sys.argv.index('--dup') + 1])
    write = '--write' in sys.argv
    if write:
        print('loading full workbook (slow)...')
        df = pd.read_excel(SRC_XLSX, sheet_name=SHEET)
    else:
        df = pd.read_pickle(SUBSET_PKL)

    clear_set, addcols_map, report = compute(df)
    print_report(df, clear_set, addcols_map, report)

    if write:
        df = apply_to_full(df, clear_set, addcols_map)
        print('\nwriting', OUT_XLSX, '...')
        with pd.ExcelWriter(OUT_XLSX, engine='openpyxl') as xl:
            df.to_excel(xl, sheet_name=SHEET, index=False)
        print('done:', OUT_XLSX, df.shape)
    else:
        print('\n(dry-run; pass --write to produce', OUT_XLSX + ')')

if __name__ == '__main__':
    main()
