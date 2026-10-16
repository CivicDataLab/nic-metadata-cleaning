
### Example: accdeath

Why: Same as Suicides: overlapping windows of a continuous one-row-per-year table, figures repeat (one small revision of 1967 between editions did not matter), later files end with a percentage-change row -> merged, span in name, mac blank.

- header H1: Sl. No.,Year,Estimated MidYear Population in Lakhs,Total Number of Accidental Deaths,Volume of Accidental Deaths per Lakh of Population

nid | before: merge_method / Collection / mac | title | AFTER: merge_method / Collection / mac / Remark
2956381 | change_in_header / All India Level Incidence and Volume of Accidental Deaths (schema 1) / review | All India Level Incidence & Volume of Accidental Deaths from 1964 to 1968 [H1] | **change_in_header / All India Level Incidence and Volume of Accidental Deaths from 1964 to 1988 / -**
2956041 | change_in_header / All India Level Incidence and Volume of Accidental Deaths (schema 1) / review | All India Level Incidence and Volume of Accidental Deaths from 1964 to 1969 [H1] | **change_in_header / All India Level Incidence and Volume of Accidental Deaths from 1964 to 1988 / -**
2955241 | change_in_header / All India Level Incidence and Volume of Accidental Deaths (schema 1) / review | All India Level Incidence and Volume of Accidental Deaths from 1964 to 1971 [H1] | **change_in_header / All India Level Incidence and Volume of Accidental Deaths from 1964 to 1988 / -**
2951741 | change_in_header / All India Level Incidence and Volume of Accidental Deaths (schema 1) / review | All India Level Incidence and Volume of Accidental Deaths from 1967 to 1973 [H1] | **change_in_header / All India Level Incidence and Volume of Accidental Deaths from 1964 to 1988 / -**
2950821 | change_in_header / All India Level Incidence and Volume of Accidental Deaths (schema 1) / review | All India Level Incidence and Volume of Accidental Deaths from 1967 to 1974 [H1] | **change_in_header / All India Level Incidence and Volume of Accidental Deaths from 1964 to 1988 / -**
2920301 | change_in_header / All India Level Incidence and Volume of Accidental Deaths (schema 1) / review | All India Level Incidence and Volume of Accidental Deaths from 1976 to 1986 [H1] | **change_in_header / All India Level Incidence and Volume of Accidental Deaths from 1964 to 1988 / -**
... (+3 more rows: same before/after as the rows above)

### Example: causes

Why: Single years (during 1967 … during 1972). Two columns carry the year ('Percentage to Total Accidental Deaths 1967', '… 1966') -> merge anyway with Remark 'Year in the header can be changed to previous year or last year'; year only in titles -> mac = year; name with span.

- header H1: Sl. No.,Category,Causes of Accidental Deaths,Number of Accidental Deaths,Percentage to Total Accidental Deaths  1967,Percentage to Total Accidental Deaths  1966

nid | before: merge_method / Collection / mac | title | AFTER: merge_method / Collection / mac / Remark
2957761 | change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes / review | All India Level Incidence of Accidental Deaths due to Various Causes during 1967 [H1] | **change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes from 1967 to 1972 / year** / Remark: Year in the header can be changed to previous year or last year
2956361 | change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes / review | All India Level Incidence of Accidental Deaths due to Various Causes during 1968 [H1] | **change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes from 1967 to 1972 / year** / Remark: Year in the header can be changed to previous year or last year
2955221 | change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes / review | All India Level Incidence of Accidental Deaths due to Various Causes during 1971 [H1] | **change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes from 1967 to 1972 / year** / Remark: Year in the header can be changed to previous year or last year
2952781 | change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes / review | All India Level Incidence of Accidental Deaths due to Various Causes during 1972 [H1] | **change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes from 1967 to 1972 / year** / Remark: Year in the header can be changed to previous year or last year
2956021 | change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes / review | All India level Incidence of Accidental Deaths due to various Causes during 1969 [H1] | **change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes from 1967 to 1972 / year** / Remark: Year in the header can be changed to previous year or last year
2953481 | change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes / review | All India level Incidence of Accidental Deaths due to various Causes during 1970 [H1] | **change_in_header / All India Level Incidence of Accidental Deaths due to Various Causes from 1967 to 1972 / year** / Remark: Year in the header can be changed to previous year or last year

### Example: crime_wide

Why: Years in EVERY column ('Incidence 1960, Volume 1960, Incidence 1964, …') and the windows overlap -> `non-mergeable`.

- header H1: SL. No.,Heads of Crime,Incidence  1960,Volume  1960,Incidence  1964,Volume  1964,Incidence  1965,Volume  1965,Incidence  1966,Volume  1966,Incidence  1967,Volume  1967,Incidence  1968,Volume  1968,Quinquennial Average 19641968 Q.A
- header H2: SL. No.,Heads of Crime,Incidence  1974,Volume  1974,Incidence  1979,Volume  1979,Incidence  1980,Volume  1980,Incidence  1981,Volume  1981,Incidence  1982,Volume  1982,Incidence  1983,Volume  1983,Quinquennial Average 19791983 Q.A

nid | before: merge_method / Collection / mac | title | AFTER: merge_method / Collection / mac / Remark
2009881 | change_in_header / All India Level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1960 to 1969 and their Percentage Variation (schema 1) / review | All India Level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1960 to 1969 and their Percentage Variation [H1] | **non-mergeable / - / -**
1300401 | change_in_header / All India Level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1960 to 1969 and their Percentage Variation (schema 1) / review | All India Level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1962 to 1972 and their Percentage Variation [H1] | **non-mergeable / - / -**
774581 | change_in_header / All India level Incidence of Crime, Volume of Crime Per Lakh of Population and Percentage Variation during 1987 over 1977, over Quinquennial Average of 1982 to 1986 and over (schema 1) / review | All India level Incidence of Crime, Volume of Crime Per Lakh of Population from 1974 to 1984 and Percentage Variation during 1984 over 1974, over Quinquennial Average of 1979 to 1983 and over 1983 [H2] | **non-mergeable / - / -**
1912541 | change_in_header / All India Level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1960 to 1969 and their Percentage Variation (schema 1) / review | All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1960 to 1970 and their Percentage Variation [H1] | **non-mergeable / - / -**
1174521 | change_in_header / All India Level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1960 to 1969 and their Percentage Variation (schema 1) / review | All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1963 to 1973 and their Percentage Variation [H1] | **non-mergeable / - / -**
839941 | change_in_header / All India level Incidence of Crime, Volume of Crime Per Lakh of Population and Percentage Variation during 1987 over 1977, over Quinquennial Average of 1982 to 1986 and over (schema 1) / review | All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1972 to 1982 & Percentage Variation during 1982 Over 1972, Over Quinquennial Average of 1977 to 1981 and Over 1981 [H2] | **non-mergeable / - / -**
768701 | change_in_header / All India level Incidence of Crime, Volume of Crime Per Lakh of Population and Percentage Variation during 1987 over 1977, over Quinquennial Average of 1982 to 1986 and over (schema 1) / review | All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1975 to 1985 and Percentage Variation during 1985 over 1975, over Quinquennial Average of 1980 to 1984 and over 1984 [H2] | **non-mergeable / - / -**
750801 | change_in_header / All India level Incidence of Crime, Volume of Crime Per Lakh of Population and Percentage Variation during 1987 over 1977, over Quinquennial Average of 1982 to 1986 and over (schema 1) / review | All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1976 to 1986 and Percentage Variation in 1986 Over 1976, Over Quinquennial Average of 1981 to 1985 and Over 1985 [H2] | **non-mergeable / - / -**
1037921 | change_in_header / All India level Incidence of Crime, Volume of Crime Per Lakh of Population and Percentage Variation during 1987 over 1977, over Quinquennial Average of 1982 to 1986 and over (schema 1) / review | All India level Incidence of Crime, Volume of Crime per One Lakh of Population & Percentage Variation during 1981 over 1971, Over Quinquennial Average of 1976 to 1980 and Over 1980 [H2] | **non-mergeable / - / -**
1118661 | change_in_header / All India Level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1960 to 1969 and their Percentage Variation (schema 1) / review | All India level Incidence of Crime, Volume of Crime per One Lakh of Population from 1965 to 1975 and their Percentage Variation [H1] | **non-mergeable / - / -**
1067281 | change_in_header / All India level Incidence of Crime, Volume of Crime Per Lakh of Population and Percentage Variation during 1987 over 1977, over Quinquennial Average of 1982 to 1986 and over (schema 1) / review | All India level Incidence of Crime, Volume of Crime per One Lakh of Population from 1970 to 1980 & Percentage Variation during 1980 over 1970, over Quinquennial Average of 1975-1979 and over 1979 [H2] | **non-mergeable / - / -**

### Example: disposal

Why: Single years 1978-82 merged (mac should be `year`, the year is only in the titles).

- header H1: SL. No. ,Heads of Crime,Total Number of Cases for Investigation During the Year Including Cases Carried over from Previous Year,Number of Cases in which Investigation was Refused or Declared False or Mistake of Facts or Law or Fou

nid | before: merge_method / Collection / mac | title | AFTER: merge_method / Collection / mac / Remark
1080101 | change_in_header / All India level Disposal of Crime under Local & Special Laws by Police / - | All India level Disposal of Crime under Local & Special Laws by Police during 1978 [H1] | **change_in_header / All India level Disposal of Crime under Local & Special Laws by Police from 1978 to 1982 / -**
1073361 | change_in_header / All India level Disposal of Crime under Local & Special Laws by Police / - | All India level Disposal of Crime under Local & Special Laws by Police during 1979 [H1] | **change_in_header / All India level Disposal of Crime under Local & Special Laws by Police from 1978 to 1982 / -**
1067561 | change_in_header / All India level Disposal of Crime under Local & Special Laws by Police / - | All India level Disposal of Crime under Local & Special Laws by Police during 1980 [H1] | **change_in_header / All India level Disposal of Crime under Local & Special Laws by Police from 1978 to 1982 / -**
1038201 | change_in_header / All India level Disposal of Crime under Local & Special Laws by Police / - | All India level Disposal of Crime under Local & Special Laws by Police during 1981 [H1] | **change_in_header / All India level Disposal of Crime under Local & Special Laws by Police from 1978 to 1982 / -**
839621 | change_in_header / All India level Disposal of Crime under Local & Special Laws by Police / - | All India level Disposal of Crime under Local & Special Laws by Police during 1982 [H1] | **change_in_header / All India level Disposal of Crime under Local & Special Laws by Police from 1978 to 1982 / -**

### Example: inmates

Why: Single years 'at the end of 2007 … 2015' with identical-ish columns: the edition tail 'at the end' is dropped from the name, curate/non-mergeable rows of the same series are pulled in, Female and all-inmates series stay SEPARATE collections (rule 5), mac = year (year only in titles).

- header H1: Sl. No,Type,Convicts,Convicts  Percentage Share,Undertrials,Undertrials  Percentage Share,Detenues,Detenues  Percentage Share,Others,Others  Percentage Share,Total
- header H2: S.No.,Type,Convicts,Convicts  % Share,Undertrials,Undertrials  % Share,Detenues,Detenues  % Share,Others,Others  % Share,Total

nid | before: merge_method / Collection / mac | title | AFTER: merge_method / Collection / mac / Remark
3633981 | curate / All India Level Category-wise Distribution of Female Inmates in Different Jails at the end / year | All India Level Category-wise Distribution of Female Inmates in Different Jails at the end of 2007 [H1] | **change_in_header / All India Level Category-wise Distribution of Female Inmates in Different Jails / year**
3630881 | curate / All India Level Category-wise Distribution of Female Inmates in Different Jails at the end / year | All India Level Category-wise Distribution of Female Inmates in Different Jails at the end of 2008 [H1] | **change_in_header / All India Level Category-wise Distribution of Female Inmates in Different Jails / year**
3628641 | curate / All India Level Category-wise Distribution of Female Inmates in Different Jails at the end / year | All India Level Category-wise Distribution of Female Inmates in Different Jails at the end of 2009 [H1] | **change_in_header / All India Level Category-wise Distribution of Female Inmates in Different Jails / year**
3610601 | curate / All India Level Category-wise Distribution of Female Inmates in Different Jails at the end / year | All India Level Category-wise Distribution of Female Inmates in Different Jails at the end of 2010 [H1] | **change_in_header / All India Level Category-wise Distribution of Female Inmates in Different Jails / year**
3512141 | curate / All India Level Category-wise Distribution of Female Inmates in Different Jails at the end / year | All India Level Category-wise Distribution of Female Inmates in Different Jails at the end of 2011 [H1] | **change_in_header / All India Level Category-wise Distribution of Female Inmates in Different Jails / year**
3413601 | curate / All India Level Category-wise Distribution of Female Inmates in Different Jails at the end / year | All India Level Category-wise Distribution of Female Inmates in Different Jails at the end of 2012 [H1] | **change_in_header / All India Level Category-wise Distribution of Female Inmates in Different Jails / year**
... (+2 more rows: same before/after as the rows above)
1303601 | non-mergeable / - / - | All India level Category-wise Distribution of Female Inmates in Different Jails at the end of 2015 [H2] | **change_in_header / All India Level Category-wise Distribution of Female Inmates in Different Jails / year**
3086081 | curate / All India Level Category-wise Distribution of Female Inmates in Different Jails at the end / year | All India Level Category-wise Distribution of Jail Inmates in Different Jails in the Country at the end of 2014 [H1] | **change_in_header / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails / year**
3633961 | curate / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end / year | All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end of 2007 [H1] | **change_in_header / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails / year**
3630861 | curate / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end / year | All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end of 2008 [H1] | **change_in_header / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails / year**
3628621 | curate / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end / year | All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end of 2009 [H1] | **change_in_header / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails / year**
3610581 | curate / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end / year | All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end of 2010 [H1] | **change_in_header / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails / year**
3512121 | curate / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end / year | All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end of 2011 [H1] | **change_in_header / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails / year**
3390321 | curate / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end / year | All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails at the end of 2013 [H1] | **change_in_header / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails / year**
... (+1 more rows: same before/after as the rows above)
1304001 | non-mergeable / - / - | All India level Category-wise Distribution of Jail Inmates in Different Jails at the end of 2015 [H2] | **change_in_header / All India Level Category-wise Distribution of Jail Inmates in the Country in Various Jails / year**

### Example: juv_age

Why: Overlapping sliding windows (1965-75, 1966-76, …) that are NOT continuous series: each file lists selected years only (the '1965 to 1975' file has 1965, 1968, 1969 … - 1966/1967 missing), a shared year differs between editions, and the age bands are regrouped (16-21 vs 16-18 + 18-21) -> `non-mergeable`.

- header H1: SL. No.,Years,712 Years,712 Year  Percentage to Total,1216 Years,1216 Year  Percentage to Total,1618 Years,1618 Year  Percentage to Total,1821 Years,1821 Year  Percentage to Total,Overall Age  Groups

nid | before: merge_method / Collection / mac | title | AFTER: merge_method / Collection / mac / Remark
1119341 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 1) / review | All India level Juvenile Apprehended by Age Group from 1965 to 1975 [H1] | **non-mergeable / - / -**
1093041 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 1) / review | All India level Juvenile Apprehended by Age Group from 1966 to 1976 [H1] | **non-mergeable / - / -**
1087121 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 1) / review | All India level Juvenile Apprehended by Age Group from 1967 to 1977 [H1] | **non-mergeable / - / -**
1080541 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 1) / review | All India level Juvenile Apprehended by Age Group from 1968 to 1978 [H1] | **non-mergeable / - / -**
1073801 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 1) / review | All India level Juvenile Apprehended by Age Group from 1969 to 1979 [H1] | **non-mergeable / - / -**
1068001 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 1) / review | All India level Juvenile Apprehended by Age Group from 1970 to 1980 [H1] | **non-mergeable / - / -**
... (+2 more rows: same before/after as the rows above)
2010201 | change_in_header / All India level Juveniles Apprehended by Age Group / - | All India level Juveniles Apprehended by Age Group from 1960 to 1969 [H1] | **non-mergeable / - / -**
1912881 | change_in_header / All India level Juveniles Apprehended by Age Group / - | All India level Juveniles Apprehended by Age Group from 1960 to 1970 [H1] | **non-mergeable / - / -**
1301121 | change_in_header / All India level Juveniles Apprehended by Age Group / - | All India level Juveniles Apprehended by Age Group from 1963 to 1972 [H1] | **non-mergeable / - / -**
1175241 | change_in_header / All India level Juveniles Apprehended by Age Group / - | All India level Juveniles Apprehended by Age Group from 1963 to 1973 [H1] | **non-mergeable / - / -**
1169701 | change_in_header / All India level Juveniles Apprehended by Age Group / - | All India level Juveniles Apprehended by Age Group from 1964 to 1974 [H1] | **non-mergeable / - / -**
806001 | change_in_header / All India level Juveniles Apprehended by Age Group / - | All India level Juveniles Apprehended by Age Group from 1973 to 1983 [H1] | **non-mergeable / - / -**
... (+1 more rows: same before/after as the rows above)

### Example: suicides

Why: Overlapping windows (1967-73, 1967-74, 1973-80, 1974-84 …) merged into one collection with the full span: each file is a continuous one-row-per-year table and the overlapping years carry the same figures (user's Remark: 'Since all the figures are repeating in the datasets these can be merged'). The later files end with a 'Percentage change in <Y> over <X>' row - that did NOT stop the user; it is dropped at merge. Year is a header column, so mac blank. One file had 'per 10000' where the others say 'per 100000' - Remark: 'The dataset has 10,000 instead of 100,000. The header can be changed'.

- header H1: Sl. No.,Year,Estimated MidYear Population in Lakhs,Number of Suicides,Volume of Suicides per Lakhs of Population
- header H2: Sl. No.,Year,Estimated MidYear Population in Lakhs,Total Number of Suicidal Deaths,Volume of Suicidal Deaths per Lakh of Population

nid | before: merge_method / Collection / mac | title | AFTER: merge_method / Collection / mac / Remark
2951821 | non-mergeable / - / - | All India Level Incidence and Volume of Suicides from 1967 to 1973 [H1] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: Since all the figures are repeating in the the datasets these can be merged
2950901 | non-mergeable / - / - | All India Level Incidence and Volume of Suicides from 1967 to 1974 [H1] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: Since all the figures are repeating in the the datasets these can be merged
2922901 | non-mergeable / - / - | All India Level Incidence and Volume of Suicides from 1973 to 1980 [H1] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: Since all the figures are repeating in the the datasets these can be merged
2947741 | non-mergeable / - / - | All India Level Incidence and Volume of Suicides from 1973 to 1983 [H1] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: Since all the figures are repeating in the the datasets these can be merged
2923681 | non-mergeable / - / - | All India Level Incidence and Volume of Suicides from 1974 to 1981 [H1] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: Since all the figures are repeating in the the datasets these can be merged
2948721 | change_in_header / All India Level Incidence and Volume of Suicides (schema 1) / review | All India Level Incidence and Volume of Suicides from 1974 to 1984 [H2] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: Since all the figures are repeating in the the datasets these can be merged
2933961 | non-mergeable / - / - | All India Level Incidence and Volume of Suicides from 1975 to 1982 [H1] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: The dataset has 10,000 instead of 100,000. The header can be changed
2920901 | change_in_header / All India Level Incidence and Volume of Suicides (schema 1) / review | All India Level Incidence and Volume of Suicides from 1975 to 1985 [H2] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: Since all the figures are repeating in the the datasets these can be merged
2920421 | change_in_header / All India Level Incidence and Volume of Suicides (schema 1) / review | All India Level Incidence and Volume of Suicides from 1976 to 1986 [H2] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: Since all the figures are repeating in the the datasets these can be merged
2920021 | change_in_header / All India Level Incidence and Volume of Suicides (schema 1) / review | All India Level Incidence and Volume of Suicides from 1977 to 1987 [H2] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: Since all the figures are repeating in the the datasets these can be merged
2919521 | change_in_header / All India Level Incidence and Volume of Suicides (schema 1) / review | All India Level Incidence and Volume of Suicides from 1978 to 1988 [H2] | **change_in_header / All India Level Incidence and Volume of Suicides from 1967 to 1988 / -** / Remark: Since all the figures are repeating in the the datasets these can be merged

### Example: unexplained_ncrb

Why: Judgment call by the user, not explained (single years, no overlap, same columns): `non-mergeable`. Do NOT copy it to look-alikes - the user MERGED the near-identical 'Local & Special Laws … 1978-82' set (see the 'disposal' example). Decide look-alikes by rules 1-6 and mark them LOW.

- header H1: Sl. No,Type,Mentally ill,Mentally ill  Percentage Share,Convicts,Convicts  Percentage Share,Undertrials,Undertrials  Percentage Share,Detenues,Detenues  Percentage Share,Others,Others  Percentage Share,Total
- header H2: SL. No.,Heads of Crime,Total Number of Cases for Investigation During the Year Including Cases Carried over from Previous Year,Number of Cases in which Investigation was Refused or Declared False or Mistake of Facts or Law or Foun
- header H3: SL. No.,Category,Heads of Crime ,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Years  Girls,Between 1618 Years  Boys,Between 1618 Years  Girls,Between 1821 Years  Boys,Between 1821 Years  G

nid | before: merge_method / Collection / mac | title | AFTER: merge_method / Collection / mac / Remark
3644921 | change_in_header / All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end / review | All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end of 1998 [H1] | **non-mergeable / - / -**
3637661 | change_in_header / All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end / review | All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end of 1999 [H1] | **non-mergeable / - / -**
3636081 | change_in_header / All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end / review | All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end of 2000 [H1] | **non-mergeable / - / -**
3644901 | change_in_header / All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end / review | All India Level Category-wise Distribution of Jail Inmates in the Country and Percentage Share at the end of 1998 [H1] | **non-mergeable / - / -**
3637641 | change_in_header / All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end / review | All India Level Category-wise Distribution of Jail Inmates in the Country and Percentage Share at the end of 1999 [H1] | **non-mergeable / - / -**
3636061 | change_in_header / All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end / review | All India Level Category-wise Distribution of Jail Inmates in the Country and Percentage Share at the end of 2000 [H1] | **non-mergeable / - / -**
1300681 | change_in_header / All India level Disposal of Crime under Local and Special Laws by Police (schema 1) / review | All India level Disposal of Crime under Local and Special Laws by Police during 1972 [H2] | **non-mergeable / - / -**
1174801 | change_in_header / All India level Disposal of Crime under Local and Special Laws by Police (schema 1) / review | All India level Disposal of Crime under Local and Special Laws by Police during 1973 [H2] | **non-mergeable / - / -**
1169261 | change_in_header / All India level Disposal of Crime under Local and Special Laws by Police (schema 1) / review | All India level Disposal of Crime under Local and Special Laws by Police during 1974 [H2] | **non-mergeable / - / -**
1118901 | change_in_header / All India level Disposal of Crime under Local and Special Laws by Police (schema 1) / review | All India level Disposal of Crime under Local and Special Laws by Police during 1975 [H2] | **non-mergeable / - / -**
1093341 | change_in_header / All India level Disposal of Crime under Local and Special Laws by Police (schema 1) / review | All India level Disposal of Crime under Local and Special Laws by Police during 1976 [H2] | **non-mergeable / - / -**
1087361 | change_in_header / All India level Disposal of Crime under Local and Special Laws by Police (schema 1) / review | All India level Disposal of Crime under Local and Special Laws by Police during 1977 [H2] | **non-mergeable / - / -**
1080501 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 2) / review | All India level Juvenile Apprehended by Age Group and Sex during 1978 [H3] | **non-mergeable / - / -**
1073761 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 2) / review | All India level Juvenile Apprehended by Age Group and Sex during 1979 [H3] | **non-mergeable / - / -**
1038601 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 2) / review | All India level Juvenile Apprehended by Age Group and Sex during 1981 [H3] | **non-mergeable / - / -**
805961 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 2) / review | All India level Juvenile Apprehended by Age Group and Sex during 1983 [H3] | **non-mergeable / - / -**
1067961 | change_in_header / All India level Juveniles Apprehended by Age Group (schema 2) / review | All India level Juvenile Apprehended in India by Age Group and Sex during 1980 [H3] | **non-mergeable / - / -**
