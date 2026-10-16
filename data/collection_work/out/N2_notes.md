# N2 Collection Decisions - Notes

## Key Decisions and Rationale

### Rule 5 Splits (Different Subject/Measure)

**C3: IPC vs SLL Crimes** — Split into two collections:
- Disposal of Persons Arrested under **IPC Crimes** (nids 5844661, 5848001, 5313261)
- Disposal of Persons Arrested under **SLL Crimes** (nids 5844741, 5695341)
- Rationale: Indian Penal Code and Special & Local Laws cover distinct legal categories, not just title labels. Similar to "female vs all inmates" Rule 5 pattern.

**C13-C15: Different Inmate Categories** — Multiple splits:
- C13 split into three: **Convicts** (G632), **Foreign Convicts** (G633), **Foreigner Detenues** (G634+G635)
- C14 split into two: **Convicts** (G636), **Foreigners Convicted** (G637)
- C15 split into two: **Foreigner Undertrials** (G639), **Undertrials** (G640+G641)
- Rationale: Each inmate type (Convicts, Foreign Convicts, Foreigner Detenues, Undertrials, etc.) represents distinct administrative categories with different row structures, analogous to "Female inmates vs all inmates" Rule 5 example.

### Overlapping Windows

**C2: Crimes under IPC and SLL** (7 members, windows 2015-2023):
- Overlapping 3-year windows: 2015-17 overlaps 2016-18, 2017-19 overlaps 2019-21, etc.
- Confidence: **medium**
- Rationale: Pattern matches Suicides example (continuous one-row-per-year series with overlapping editions). Assumed data is continuous year-series within each window and figures repeat in overlaps (per Rule 3). Recommend verification of sample files 6750527 and 6903547 (2018 overlap year) if figures differ.

### Naming Conventions

- Dropped edition tails like "at the end of" and "during" (Rule: Naming)
- Removed "(schema N)" suffixes per rules
- Used "State/UT-wise" or "State, UT & City-wise" to match source titles exactly
- Used "from X to Y" format for all spanning multiple years, with fiscal year context (e.g., "2007-08" for fiscal series, "2007" for calendar year)

### MAC Tokens Used

- `year` — when single-year datasets are stacked (every collection with single-year members)
- `sex` — when datasets split by Men+Women vs Women Only (C6, C7, C8, C9)
- `victim_group` — when victim category (Children vs Scheduled Tribes) varies only in titles (C1)
- No new tokens coined; all from vocabulary

### Verification Notes

1. **C2 (Crimes IPC/SLL)**: Confirm overlapping years (e.g., 2018 in 2016-2018 and 2018-2020 editions) have identical figures before merge.
2. **C5 (IPC Crimes with year in header)**: Remark flagged year columns ("Percentage variation in 2005 over 2004") can be renamed at merge time.
3. **C16 (Jail Breaks)**: Sparse years (1998-2012 then jump to 2019) in otherwise continuous collection — verify these are intentional gaps vs missed years.

## Coverage

All 158 rows from 18 collections accounted for exactly once. No rows marked LOCKED, "decided in batch", or "do not claim" were claimed.
