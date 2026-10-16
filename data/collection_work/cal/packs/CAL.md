# Evidence pack CAL: 9 collections, 56 rows


---

## C1 · All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end

- ministry: Ministry of Home Affairs, Department of States, National Crime Records Bureau (NCRB) | members in scope: 6 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels india | varying dims year | suggested mac year | header dims -
- varying title text: Female Inmates in the Country and Percentage Share at the end of 1998 | Female Inmates in the Country and Percentage Share at the end of 1999 | Female Inmates in the Country and Percentage Share at the end of 2000 | Jail Inmates in the Country and Percentage Share at the end of 1998 | Jail Inmates in the Country and Percentage Share at the end of 1999 | Jail Inmates in the Country and Percentage Share at the end of 2000
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=All India Level Category-wise Distribution of Jail Inmates and Female Inmates in the Country and Percentage Share | mac=year,inmate_group | notes=half the members cover all jail inmates, not female

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [6] 12 cols, year-labelled cols 0%: Type | Mentally ill | Mentally ill  Percentage Share | Convicts | Convicts  Percentage Share | Undertrials | Undertrials  Percentage Share | Detenues | Detenues  Percentage Share | Others | Others  Percentage Share | Total

### Members

nid | group | header | window | yr-cols | period (data) | file | title
3644921 | G1 | H1 | 1998 | 0% | 1998-01-01..1999-12-31 | c8ad10c3-f5a2-486c-ac87-7abc99f8f272.csv | All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end of 1998
3637661 | G1 | H1 | 1999 | 0% | 1999-01-01..2000-12-31 | 38ba56b0-2259-471f-b98c-8f02bc330129.csv | All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end of 1999
3636081 | G1 | H1 | 2000 | 0% | 2000-01-01..2001-12-31 | 26c300fb-d615-4c73-8a62-2cceb7c02c22.csv | All India Level Category-wise Distribution of Female Inmates in the Country and Percentage Share at the end of 2000
3644901 | G2 | H1 | 1998 | 0% | 1998-01-01..1999-12-31 | 4091cb1e-57f0-4159-8248-b97e1e271a01.csv | All India Level Category-wise Distribution of Jail Inmates in the Country and Percentage Share at the end of 1998
3637641 | G2 | H1 | 1999 | 0% | 1999-01-01..2000-12-31 | c606339c-03f7-4b04-9870-230519c67a2b.csv | All India Level Category-wise Distribution of Jail Inmates in the Country and Percentage Share at the end of 1999
3636061 | G2 | H1 | 2000 | 0% | 2000-01-01..2001-12-31 | 1a2e791a-dafc-41b0-90ce-a22ab27e372c.csv | All India Level Category-wise Distribution of Jail Inmates in the Country and Percentage Share at the end of 2000

---

## C2 · All India level Disposal of Crime under Local and Special Laws by Police (schema 1)

- ministry: Ministry of Home Affairs, Department of States, National Crime Records Bureau (NCRB) | members in scope: 6 | current mac: review
- detector: flags SCHEMA_N_SUFFIX,MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels india | varying dims year | suggested mac year | header dims -
- varying title text: 1972 | 1973 | 1974 | 1975 | 1976 | 1977
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=All India level Disposal of Crime under Local and Special Laws by Police | mac=year

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [6] 6 cols, year-labelled cols 0%: Heads of Crime | Total Number of Cases for Investigation During the Year Including Cases Carried over from Previous Year | Number of Cases in which Investigation was Refused or Declared False or Mistake of Facts or Law or Found Non Cognizable | Number of Cases Investigated during the Year | Number of Cases Pending Investigation at the End of the Year | Number of Cases in which Chargesheets were Laid

### Members

nid | group | header | window | yr-cols | period (data) | file | title
1300681 | G3 | H1 | 1972 | 0% | 1972-01-01..1972-12-31 | c2954703-7b3f-4601-a52f-47a789c3bf0e.csv | All India level Disposal of Crime under Local and Special Laws by Police during 1972
1174801 | G3 | H1 | 1973 | 0% | 1973-01-01..1973-12-31 | 0517fb63-4213-440b-a6f6-0c0a821be3d5.csv | All India level Disposal of Crime under Local and Special Laws by Police during 1973
1169261 | G3 | H1 | 1974 | 0% | 1974-01-01..1974-12-31 | 91bcd5bb-bcd0-4727-9369-852468a46c8d.csv | All India level Disposal of Crime under Local and Special Laws by Police during 1974
1118901 | G3 | H1 | 1975 | 0% | 1975-01-01..1975-12-31 | e3a318b7-4606-4ad3-8bc2-dfaed356f73c.csv | All India level Disposal of Crime under Local and Special Laws by Police during 1975
1093341 | G3 | H1 | 1976 | 0% | 1976-01-01..1976-12-31 | 9e529a41-13d4-4886-a966-62b08c82f711.csv | All India level Disposal of Crime under Local and Special Laws by Police during 1976
1087361 | G3 | H1 | 1977 | 0% | 1977-01-01..1977-12-31 | e4d75c00-377c-4dd5-8efd-5c2cf9544a2d.csv | All India level Disposal of Crime under Local and Special Laws by Police during 1977

### Similar rows outside this collection (same ministry)

- collection [5] All India level Disposal of Crime under Local & Special Laws by Police (change_in_header; free); best score 96.49122807017544; e.g. 839621 All India level Disposal of Crime under Local & Special Laws by Police during 1982
- collection [8] All India level Disposal of Cases under Local and Special Laws by Courts (change_in_header; free); best score 86.4406779661017; e.g. 750461 All India level Disposal of Cases under Local and Special Laws by Courts during 1986
- nid 750421 (non-mergeable, no collection; free; score 100.0; window 1986; hdr 'SL. No. Col. 1,Head of Crime Col. 2,Total Number of Cases for Investigation During the Year Including the Cases Carried '; file e5e5401c-ad8b-4a80-9356-1367a8d10515.csv) All India level Disposal of Crime under Local and Special Laws by Police During 1986
- nid 805521 (non-mergeable, no collection; free; score 100.0; window 1983; hdr 'SL. No. Col. 1,Head of Crime Col. 2,Total Number of Cases for Investigation During the Year Including the Cases Carried '; file 476589f7-0b88-4726-85cd-d84cfc0b53ef.csv) All India level Disposal of Crime under Local and Special Laws by Police during 1983
- nid 741801 (non-mergeable, no collection; free; score 96.49122807017544; window 1987; hdr 'SL. No. ,Heads of Crime ,Total Number of Cases for Investigation During the Year Including Cases Carried over from Previ'; file a472461f-bf96-4ef3-bb6d-f4fb7e930d4f.csv) All India level Disposal of Crime under the Local & Special Laws by Police during 1987
- nid 774261 (non-mergeable, no collection; free; score 96.49122807017544; window 1984; hdr 'SL. No. Col. 1,Head of Crime Col. 2,Total Number of Cases for Investigation During the Year Including the Cases Carried '; file fa519db9-5c54-4b34-b2b0-93318b368500.csv) All India level Disposal of Crime under the Local & Special Laws by Police during 1984
- nid 768381 (non-mergeable, no collection; free; score 95.16129032258065; window 1985; hdr 'SL. No. Col. 1,Heads of Crime Col. 2,Total Number of Cases for Investigation During the Year Including the Cases Carried'; file 17d42d92-729d-441c-af06-02f7ac9a79bd.csv) All India level Disposal of Crime Cases under Local and Special Laws by the Police during 1985

---

## C3 · All India Level Incidence and Volume of Accidental Deaths (schema 1)

- ministry: Ministry of Home Affairs, Department of States, National Crime Records Bureau (NCRB) | members in scope: 9 | current mac: review
- detector: flags SCHEMA_N_SUFFIX,MAC_REVIEW | min_header_match  | admin levels india | varying dims year | suggested mac - | header dims year
- varying title text: & Volume of Accidental Deaths from 1964 to 1968 | and Volume of Accidental Deaths from 1964 to 1969 | and Volume of Accidental Deaths from 1964 to 1971 | and Volume of Accidental Deaths from 1967 to 1973 | and Volume of Accidental Deaths from 1967 to 1974 | and Volume of Accidental Deaths from 1976 to 1986 | and Volume of Accidental Deaths from 1977 to 1987 | and Volume of Accidental Deaths from 1978 to 1988 | of Accidental Deaths from 1964 to 1970
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename | name=All India Level Incidence and Volume of Accidental Deaths | mac=- | notes=Year is a column

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [9] 4 cols, year-labelled cols 0%: Year | Estimated MidYear Population in Lakhs | Total Number of Accidental Deaths | Volume of Accidental Deaths per Lakh of Population

### Members

nid | group | header | window | yr-cols | period (data) | file | title
2956381 | G5 | H1 | 1964-1968 | 0% | 1964-01-01..1968-12-31 | 5d75b059-3407-4345-af87-764e2f08f3cc.csv | All India Level Incidence & Volume of Accidental Deaths from 1964 to 1968
2956041 | G4 | H1 | 1964-1969 | 0% | 1964-01-01..1969-12-31 | 46001a27-0c8c-47f3-a021-ddf31eb6d6f1.csv | All India Level Incidence and Volume of Accidental Deaths from 1964 to 1969
2955241 | G4 | H1 | 1964-1971 | 0% | 1964-01-01..1971-12-31 | 2cdb2b29-5479-4b0e-b529-1341c9839cab.csv | All India Level Incidence and Volume of Accidental Deaths from 1964 to 1971
2951741 | G4 | H1 | 1967-1973 | 0% | 1967-01-01..1973-12-31 | 56e64441-163b-40e4-808e-a3d22e986d93.csv | All India Level Incidence and Volume of Accidental Deaths from 1967 to 1973
2950821 | G4 | H1 | 1967-1974 | 0% | 1967-01-01..1974-12-31 | 65e1a236-d0ec-4ba6-b437-01e22b791515.csv | All India Level Incidence and Volume of Accidental Deaths from 1967 to 1974
2920301 | G4 | H1 | 1976-1986 | 0% | 1976-01-01..1986-12-31 | c1505788-c834-49b6-a24b-c993c3a01753.csv | All India Level Incidence and Volume of Accidental Deaths from 1976 to 1986
2919901 | G4 | H1 | 1977-1987 | 0% | 1977-01-01..1987-12-31 | ef4c08a8-88ff-49de-a64d-c2c7ad1ed950.csv | All India Level Incidence and Volume of Accidental Deaths from 1977 to 1987
2919401 | G4 | H1 | 1978-1988 | 0% | 1978-01-01..1988-12-31 | 93f8d529-1c82-4d69-a469-9008ddccf1cf.csv | All India Level Incidence and Volume of Accidental Deaths from 1978 to 1988
2953501 | G6 | H1 | 1964-1970 | 0% | 1964-01-01..1970-12-31 | 88cb4825-6ab9-40f3-9f7d-0ea4712242a8.csv | All India Level Incidence of Accidental Deaths from 1964 to 1970

### Similar rows outside this collection (same ministry)

- collection [5] All India level Incidence and Rate of Accidental Deaths (curate; free); best score 90.69767441860466; e.g. 1310321 All India level Incidence and Rate of Accidental Deaths from 1990 to 2000
- collection [9] All India Level Incidence of Accidental Deaths by Causes (change_in_header; free); best score 90; e.g. 2919441 All India Level Incidence of Accidental Deaths by Causes during 1987 & 1988
- collection [6] All India Level Incidence of Accidental Deaths due to Various Causes (change_in_header; in scope, batch CAL); best score 90; e.g. 2952781 All India Level Incidence of Accidental Deaths due to Various Causes during 1972
- nid 2950801 (non-mergeable, no collection; free; score 100.0; window 1974; hdr 'Sl. No.,Category,Causes of Accidental Deaths,Number of Accidental Deaths,Percentage to Total Accidental Deaths  1974,Per'; file a613e6e1-7a13-4d20-8fd0-6d72feee1720.csv) All India Level Incidence of Accidental Deaths during 1974
- nid 2951721 (non-mergeable, no collection; free; score 100.0; window 1973; hdr 'Sl. No.,Category,Causes of Accidental Deaths,Number of Accidental Death,Percentage to Total Accidental Deaths  1973,Perc'; file 05337765-10da-405e-8f9d-948ddced7ec1.csv) All India Level Incidence of Accidental Deaths during 1973
- nid 6722426 (non-mergeable, no collection; free; score 92.95774647887323; window 2006-2016; hdr 'Sl. No. Col.1,Year Col.2,Total Number of Accidental Deaths  Forces of Nature Col.3,Total Number of Accidental Deaths  Ot'; file 85aaeb61-193e-4ecc-a5cb-870f20931792.csv) All India Level Incidence & Rate of Accidental Deaths from 2006 to 2016
- nid 6748881 (non-mergeable, no collection; free; score 92.95774647887323; window 2007-2017; hdr 'Sl. No. Col.1,Year Col.2,Total number of Accidental Deaths  Forces of Nature Col.3,Total number of Accidental Deaths  Ot'; file aef08ea9-56bf-4d4a-aaf5-d22d06d6eb7a.csv) All India Level Incidence & Rate of Accidental Deaths from 2007 to 2017
- nid 6748923 (non-mergeable, no collection; free; score 92.95774647887323; window 2008-2018; hdr 'Sl. No.  Col.1,Year  Col.2,Total number of Accidental Deaths  Forces of Nature  Col.3,Total number of Accidental Deaths '; file b910148a-b162-4856-ae4e-a2a86c41c1f3.csv) All India Level Incidence & Rate of Accidental Deaths from 2008 to 2018
- nid 2910381 (non-mergeable, no collection; free; score 92.6829268292683; window 1981-1991; hdr 'Sl. No. Col.1,Year Col.2,Total Number of Accidental Deaths Col.3,Estimated MidYear Population In Lakh Col.4,Volume of Ac'; file ccc3c795-c631-4f7f-8458-d3dc5e7eca98.csv) Incidence and Volume of Accidental Deaths from 1981 to 1991
- nid 2911081 (non-mergeable, no collection; free; score 92.6829268292683; window 1980-1990; hdr 'Sl. No. Col.1,Year Col.2,Total Number of Accidental Deaths Col.3,Estimated MidYear Population In Lakh Col.4,Volume of Ac'; file 21ad0284-f45f-4f31-a2ca-8e028d25be70.csv) Incidence and Volume of Accidental Deaths from 1980 to 1990
- nid 2912681 (non-mergeable, no collection; free; score 92.6829268292683; window 1979-1989; hdr 'Sl. No. Col.1,Year Col.2,Total Number of Accidental Deaths Col.3,Estimated MidYear Population In Lakh Col.4,Volume of Ac'; file 2a1bdc28-4fef-4141-9228-71631f721fde.csv) Incidence and Volume of Accidental Deaths from 1979 to 1989
- nid 1916641 (non-mergeable, no collection; free; score 90.69767441860466; window 2005-2015; hdr 'Sl. No. Col.1,YearCol.2,Total number of Accidental Deaths  NaturalCol.3,Total number of Accidental Deaths  UnnaturalCol.'; file c32a117d-513d-4247-9262-af7efe70907b.csv) All India level Incidence and Rate of Accidental Deaths from 2005 to 2015
- nid 2920781 (non-mergeable, no collection; free; score 90; window 1975-1985; hdr 'Sl. No.,Year ,Estimated MidYear Population in Lakhs,Total Number of Accidental Deaths ,Volume of Accidental Deaths Per L'; file c226da92-1c1a-49e8-9ada-2d49d32ea6c6.csv) All India Level Incidence and Volume of Accidental Deaths per Lakh of Population from 1975 to 1985
- nid 2947621 (non-mergeable, no collection; free; score 90; window 1973-1983; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Total Number of Accidental Deaths,Volume of Accidental Deaths per Lak'; file 59351aa6-3369-4d5d-b80d-916f80529a90.csv) All India Level Incidence and Volume of Accidental Deaths per Lakh of Population from 1973 to 1983
- nid 2922781 (non-mergeable, no collection; free; score 90; window 1973-1980; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Total Number of Accidental Deaths,Volume of Accidental Deaths per Lak'; file abd20225-7cba-44a1-beee-fd2f68a69e46.csv) All India Level Incidence of Accidental Deaths and Volume of Accidental Deaths per Lakh of Population from 1973 to 1980
- nid 2923561 (non-mergeable, no collection; free; score 90; window 1974-1981; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Total Number of Accidental Deaths,Volume of Accidental Deaths per Lak'; file 893e60d3-44a6-418f-816e-cd22d512cb11.csv) All India Level Incidence of Accidental Deaths and Volume of Accidental Deaths per Lakh of Population from 1974 to 1981
- nid 2933821 (non-mergeable, no collection; free; score 90; window 1975-1982; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Total Number of Accidental Deaths,Volume of Accidental Deaths per Lak'; file 003fea3a-9fb9-4bde-b2cc-7166b6f91d44.csv) All India Level Incidence of Accidental Deaths and Volume of Accidental Deaths per Lakh of Population from 1975 to 1982
- nid 2948601 (non-mergeable, no collection; free; score 90; window 1974-1984; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Total Number of Accidental Deaths,Volume of Accidental Deaths per Lak'; file 44b9e90f-b50f-4fe5-a55e-6b13c6722aad.csv) All India Level Incidence of Accidental Deaths and Volume of Accidental Deaths per Lakh of Population from 1974 to 1984
- nid 2957781 (non-mergeable, no collection; free; score 90; window 1966; hdr 'Sl. No.,Year,Estimated Population in Millions,Total Number of Accidental Deaths,Volume of Accidental Deaths per Lakh of '; file fe8e72bc-19ca-4e58-95d9-12d3c7d8cc59.csv) All India Level Comparative Statement of Incidence & Volume of Accidental Deaths and Population during 1966 and 1967
- nid 1310081 (non-mergeable, no collection; free; score 90; window 1991-2000; hdr 'Sl. No.,Year,Natural Causes  Incidence,Natural Causes  Percentage change over previous year,UnNatural Causes  Incidence,'; file abf57d94-2c8c-4e4d-bb70-706b447cccc3.csv) All India level Incidence of Accidental Deaths by Natural & Un-Natural Causes from 1991 to 2000
- nid 1310141 (non-mergeable, no collection; free; score 90; window 1999; hdr 'Sl. No.,Category,Cause,No.  1999,Percentage share  1999,Rate  1999,No.  2000,Percentage share  2000,Rate  2000,Percentag'; file bf809710-cf54-4e7b-891d-1e6bf9fa03f2.csv) All India level Incidence, Share & Rate of Accidental Deaths by (Natural and Un-Natural) Causes during 1999 & 2000
- nid 2952801 (non-mergeable, no collection; free; score 90; window 1964-1972; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Total Number of Accidental Deaths,Volume of Accidental Deaths per Lak'; file f8886d7e-006c-4319-9fbc-cee2f7125c39.csv) All India Level Comparative Incidence of Accidental Deaths from 1964 to 1972

### Year windows of the same series (parsed from titles)

- NESTED: 2956041 (from 1964 to 1969) is contained in 2955241 (from 1964 to 1971)
- NESTED: 2951741 (from 1967 to 1973) is contained in 2950821 (from 1967 to 1974)
- NESTED: 2923561 (from 1974 to 1981) is contained in 2948601 (from 1974 to 1984)
- NESTED: 2933821 (from 1975 to 1982) is contained in 2948601 (from 1974 to 1984)
- OVERLAP: 2956041 (from 1964 to 1969) overlaps 2951741 (from 1967 to 1973)
- OVERLAP: 2956041 (from 1964 to 1969) overlaps 2950821 (from 1967 to 1974)
- OVERLAP: 2955241 (from 1964 to 1971) overlaps 2951741 (from 1967 to 1973)
- OVERLAP: 2955241 (from 1964 to 1971) overlaps 2950821 (from 1967 to 1974)
- OVERLAP: 2920301 (from 1976 to 1986) overlaps 2919901 (from 1977 to 1987)
- OVERLAP: 2920301 (from 1976 to 1986) overlaps 2919401 (from 1978 to 1988)
- OVERLAP: 2919901 (from 1977 to 1987) overlaps 2919401 (from 1978 to 1988)
- OVERLAP: 6722426 (from 2006 to 2016) overlaps 6748881 (from 2007 to 2017)
- OVERLAP: 6722426 (from 2006 to 2016) overlaps 6748923 (from 2008 to 2018)
- OVERLAP: 6748881 (from 2007 to 2017) overlaps 6748923 (from 2008 to 2018)
- OVERLAP: 2912681 (from 1979 to 1989) overlaps 2911081 (from 1980 to 1990)
- OVERLAP: 2912681 (from 1979 to 1989) overlaps 2910381 (from 1981 to 1991)
- OVERLAP: 2911081 (from 1980 to 1990) overlaps 2910381 (from 1981 to 1991)
- OVERLAP: 2876441 (from 1986 to 1996) overlaps 2063861 (from 1988 to 1998)
- OVERLAP: 2876441 (from 1986 to 1996) overlaps 1913801 (from 1989 to 1999)
- OVERLAP: 2876441 (from 1986 to 1996) overlaps 1310321 (from 1990 to 2000)
- OVERLAP: 2063861 (from 1988 to 1998) overlaps 1913801 (from 1989 to 1999)
- OVERLAP: 2063861 (from 1988 to 1998) overlaps 1310321 (from 1990 to 2000)
- OVERLAP: 1913801 (from 1989 to 1999) overlaps 1310321 (from 1990 to 2000)
- OVERLAP: 2947621 (from 1973 to 1983) overlaps 2920781 (from 1975 to 1985)
- OVERLAP: 2922781 (from 1973 to 1980) overlaps 2923561 (from 1974 to 1981)
- OVERLAP: 2922781 (from 1973 to 1980) overlaps 2948601 (from 1974 to 1984)
- OVERLAP: 2922781 (from 1973 to 1980) overlaps 2933821 (from 1975 to 1982)
- OVERLAP: 2923561 (from 1974 to 1981) overlaps 2933821 (from 1975 to 1982)

---

## C4 · All India Level Incidence and Volume of Suicides (schema 1)

- ministry: Ministry of Home Affairs, Department of States, National Crime Records Bureau (NCRB) | members in scope: 5 | current mac: review
- detector: flags SCHEMA_N_SUFFIX,MAC_REVIEW | min_header_match  | admin levels india | varying dims year | suggested mac - | header dims year
- varying title text: 1974 to 1984 | 1975 to 1985 | 1976 to 1986 | 1977 to 1987 | 1978 to 1988
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename | name=All India Level Incidence and Volume of Suicides | mac=- | notes=Year is a column

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [5] 4 cols, year-labelled cols 0%: Year | Estimated MidYear Population in Lakhs | Total Number of Suicidal Deaths | Volume of Suicidal Deaths per Lakh of Population

### Members

nid | group | header | window | yr-cols | period (data) | file | title
2948721 | G7 | H1 | 1974-1984 | 0% | 1974-01-01..1984-12-31 | cc02c499-e8d5-4d6e-8ccf-3c43c7679fd1.csv | All India Level Incidence and Volume of Suicides from 1974 to 1984
2920901 | G7 | H1 | 1975-1985 | 0% | 1975-01-01..1985-12-31 | 5e25b94d-d004-49f6-afa3-6e4e9f255267.csv | All India Level Incidence and Volume of Suicides from 1975 to 1985
2920421 | G7 | H1 | 1976-1986 | 0% | 1976-01-01..1986-12-31 | 3d4ac6e3-2ab6-4529-8183-382900d653d2.csv | All India Level Incidence and Volume of Suicides from 1976 to 1986
2920021 | G7 | H1 | 1977-1987 | 0% | 1977-01-01..1987-12-31 | 68dd2c02-08f1-424a-ac26-9923fca22fa7.csv | All India Level Incidence and Volume of Suicides from 1977 to 1987
2919521 | G7 | H1 | 1978-1988 | 0% | 1978-01-01..1988-12-31 | 747880c1-c080-42f1-8d2e-104a3f9a797a.csv | All India Level Incidence and Volume of Suicides from 1978 to 1988

### Similar rows outside this collection (same ministry)

- collection [9] All India level Incidence and Rate of Suicides (change_in_header; free); best score 88.23529411764706; e.g. 1310921 All India level Incidence and Rate of Suicides from 1990 to 2000
- nid 2922901 (non-mergeable, no collection; free; score 100.0; window 1973-1980; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Number of Suicides,Volume of Suicides per 100000 of Population'; file 6bc25f3a-8207-4ebd-a95b-dbe523d0cd2c.csv) All India Level Incidence and Volume of Suicides from 1973 to 1980
- nid 2923681 (non-mergeable, no collection; free; score 100.0; window 1974-1981; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Number of Suicides,Volume of Suicides per 100000 of Population'; file c9c2f7f8-8da6-4073-bdd7-acaa1c30b4f4.csv) All India Level Incidence and Volume of Suicides from 1974 to 1981
- nid 2933961 (non-mergeable, no collection; free; score 100.0; window 1975-1982; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Number of Suicides,Volume of Suicides per 10000 of Population'; file bfc9bdcd-4e80-47e4-9463-860ee20187ff.csv) All India Level Incidence and Volume of Suicides from 1975 to 1982
- nid 2947741 (non-mergeable, no collection; free; score 100.0; window 1973-1983; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Number of Suicides,Volume of Suicides per Lakh of Population'; file 64760e29-2b1c-4e70-b06b-a402b42d9889.csv) All India Level Incidence and Volume of Suicides from 1973 to 1983
- nid 2950901 (non-mergeable, no collection; free; score 100.0; window 1967-1974; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Number of Suicides,Volume of Suicides per 100000 of Population'; file f2ecdc5c-1e3f-4243-b884-71477bdcf7c2.csv) All India Level Incidence and Volume of Suicides from 1967 to 1974
- nid 2951821 (non-mergeable, no collection; free; score 100.0; window 1967-1973; hdr 'Sl. No.,Year,Estimated MidYear Population in Lakhs,Number of Suicides,Volume of Suicides per Lakhs of Population'; file 8e0cd468-0399-427c-a161-4e63856d0b58.csv) All India Level Incidence and Volume of Suicides from 1967 to 1973
- nid 2910481 (non-mergeable, no collection; free; score 90.625; window 1981-1991; hdr 'Sl. No. Col.1,Year Col.2,Total Number of Suicides Col.3,Estimated MidYear Population in Lakhs Col.4,Volume of Suicides C'; file 4360fcc4-341b-4d21-8469-088259e5a822.csv) Incidence and Volume of Suicides from 1981 to 1991
- nid 2911181 (non-mergeable, no collection; free; score 90.625; window 1980-1990; hdr 'Sl. No. Col.1,Year Col.2,Total Number of Suicides Col.3,Estimated MidYear Population in Lakhs Col.4,Volume of Suicides C'; file a2f5be4f-1913-4b87-b923-dd6b71c5c119.csv) Incidence and Volume of Suicides from 1980 to 1990
- nid 2912781 (non-mergeable, no collection; free; score 90.625; window 1979-1989; hdr 'Sl. No. Col.1,Year Col.2,Total Number of Suicides Col.3,Estimated MidYear Population in Lakhs Col.4,Volume of Suicides C'; file b900e3c2-7d11-41d2-a267-8c0e16a34a7f.csv) Incidence and Volume of Suicides from 1979 to 1989
- nid 2957861 (non-mergeable, no collection; free; score 90; window 1966; hdr 'Sl. No.,Year,Estimated Population in Million,Total Number of Suicidal Deaths,Volume of Suicidal per Lakhs of Population'; file af92c57d-0f1f-431d-a5df-54c7a18ca3e4.csv) All India Level Comparative Statement of Incidence & Volume of Suicides and Population during 1966 and 1967

### Year windows of the same series (parsed from titles)

- NESTED: 2951821 (from 1967 to 1973) is contained in 2950901 (from 1967 to 1974)
- NESTED: 2922901 (from 1973 to 1980) is contained in 2947741 (from 1973 to 1983)
- NESTED: 2923681 (from 1974 to 1981) is contained in 2947741 (from 1973 to 1983)
- NESTED: 2923681 (from 1974 to 1981) is contained in 2948721 (from 1974 to 1984)
- NESTED: 2933961 (from 1975 to 1982) is contained in 2947741 (from 1973 to 1983)
- NESTED: 2933961 (from 1975 to 1982) is contained in 2948721 (from 1974 to 1984)
- NESTED: 2933961 (from 1975 to 1982) is contained in 2920901 (from 1975 to 1985)
- OVERLAP: 2951821 (from 1967 to 1973) overlaps 2922901 (from 1973 to 1980)
- OVERLAP: 2951821 (from 1967 to 1973) overlaps 2947741 (from 1973 to 1983)
- OVERLAP: 2950901 (from 1967 to 1974) overlaps 2922901 (from 1973 to 1980)
- OVERLAP: 2950901 (from 1967 to 1974) overlaps 2947741 (from 1973 to 1983)
- OVERLAP: 2950901 (from 1967 to 1974) overlaps 2923681 (from 1974 to 1981)
- OVERLAP: 2950901 (from 1967 to 1974) overlaps 2948721 (from 1974 to 1984)
- OVERLAP: 2922901 (from 1973 to 1980) overlaps 2923681 (from 1974 to 1981)
- OVERLAP: 2922901 (from 1973 to 1980) overlaps 2948721 (from 1974 to 1984)
- OVERLAP: 2922901 (from 1973 to 1980) overlaps 2933961 (from 1975 to 1982)
- OVERLAP: 2922901 (from 1973 to 1980) overlaps 2920901 (from 1975 to 1985)
- OVERLAP: 2922901 (from 1973 to 1980) overlaps 2920421 (from 1976 to 1986)
- OVERLAP: 2922901 (from 1973 to 1980) overlaps 2920021 (from 1977 to 1987)
- OVERLAP: 2922901 (from 1973 to 1980) overlaps 2919521 (from 1978 to 1988)
- OVERLAP: 2947741 (from 1973 to 1983) overlaps 2948721 (from 1974 to 1984)
- OVERLAP: 2947741 (from 1973 to 1983) overlaps 2920901 (from 1975 to 1985)
- OVERLAP: 2947741 (from 1973 to 1983) overlaps 2920421 (from 1976 to 1986)
- OVERLAP: 2947741 (from 1973 to 1983) overlaps 2920021 (from 1977 to 1987)
- OVERLAP: 2947741 (from 1973 to 1983) overlaps 2919521 (from 1978 to 1988)
- OVERLAP: 2923681 (from 1974 to 1981) overlaps 2933961 (from 1975 to 1982)
- OVERLAP: 2923681 (from 1974 to 1981) overlaps 2920901 (from 1975 to 1985)
- OVERLAP: 2923681 (from 1974 to 1981) overlaps 2920421 (from 1976 to 1986)
- OVERLAP: 2923681 (from 1974 to 1981) overlaps 2920021 (from 1977 to 1987)
- OVERLAP: 2923681 (from 1974 to 1981) overlaps 2919521 (from 1978 to 1988)
- OVERLAP: 2948721 (from 1974 to 1984) overlaps 2920901 (from 1975 to 1985)
- OVERLAP: 2948721 (from 1974 to 1984) overlaps 2920421 (from 1976 to 1986)
- OVERLAP: 2948721 (from 1974 to 1984) overlaps 2920021 (from 1977 to 1987)
- OVERLAP: 2948721 (from 1974 to 1984) overlaps 2919521 (from 1978 to 1988)
- OVERLAP: 2933961 (from 1975 to 1982) overlaps 2920421 (from 1976 to 1986)
- OVERLAP: 2933961 (from 1975 to 1982) overlaps 2920021 (from 1977 to 1987)
- OVERLAP: 2933961 (from 1975 to 1982) overlaps 2919521 (from 1978 to 1988)
- OVERLAP: 2920901 (from 1975 to 1985) overlaps 2920421 (from 1976 to 1986)
- OVERLAP: 2920901 (from 1975 to 1985) overlaps 2920021 (from 1977 to 1987)
- OVERLAP: 2920901 (from 1975 to 1985) overlaps 2919521 (from 1978 to 1988)
- OVERLAP: 2920421 (from 1976 to 1986) overlaps 2920021 (from 1977 to 1987)
- OVERLAP: 2920421 (from 1976 to 1986) overlaps 2919521 (from 1978 to 1988)
- OVERLAP: 2920021 (from 1977 to 1987) overlaps 2919521 (from 1978 to 1988)
- OVERLAP: 2912781 (from 1979 to 1989) overlaps 2911181 (from 1980 to 1990)
- OVERLAP: 2912781 (from 1979 to 1989) overlaps 2910481 (from 1981 to 1991)
- OVERLAP: 2911181 (from 1980 to 1990) overlaps 2910481 (from 1981 to 1991)
- OVERLAP: 2876621 (from 1986 to 1996) overlaps 2869861 (from 1987 to 1997)
- ... 15 more overlapping pairs

---

## C5 · All India Level Incidence of Accidental Deaths due to Various Causes

- ministry: Ministry of Home Affairs, Department of States, National Crime Records Bureau (NCRB) | members in scope: 6 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels india | varying dims year | suggested mac year | header dims -
- varying title text: 1967 | 1968 | 1969 | 1970 | 1971 | 1972
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=year

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [6] 4 cols, year-labelled cols 33%: Category | Causes of Accidental Deaths | Number of Accidental Deaths | Percentage to Total Accidental Deaths  1967

### Members

nid | group | header | window | yr-cols | period (data) | file | title
2957761 | G8 | H1 | 1967 | 33% | 1967-01-01..1967-12-31 | cdcff321-bb8d-440c-959b-b2f5b255fa1a.csv | All India Level Incidence of Accidental Deaths due to Various Causes during 1967
2956361 | G8 | H1 | 1968 | 33% | 1968-01-01..1968-12-31 | e2e23be0-5307-4716-9dc8-a10ce30aa507.csv | All India Level Incidence of Accidental Deaths due to Various Causes during 1968
2956021 | G9 | H1 | 1969 | 33% | 1969-01-01..1969-12-31 | 0030146d-8fbf-4662-8488-6b385e63ba12.csv | All India level Incidence of Accidental Deaths due to various Causes during 1969
2953481 | G9 | H1 | 1970 | 33% | 1970-01-01..1970-12-31 | 4b6e9ce9-5098-44a4-9cf0-259f87a0fe9b.csv | All India level Incidence of Accidental Deaths due to various Causes during 1970
2955221 | G8 | H1 | 1971 | 33% | 1971-01-01..1971-12-31 | 9a25045f-2247-4e5a-b906-ef07351e5678.csv | All India Level Incidence of Accidental Deaths due to Various Causes during 1971
2952781 | G8 | H1 | 1972 | 33% | 1972-01-01..1972-12-31 | 0f98d898-78ea-497d-8be5-e5028158da6f.csv | All India Level Incidence of Accidental Deaths due to Various Causes during 1972

### Similar rows outside this collection (same ministry)

- collection [1] All India Level Incidence and Volume of Accidental Deaths (schema 1) (change_in_header; in scope, batch CAL); best score 90; e.g. 2953501 All India Level Incidence of Accidental Deaths from 1964 to 1970
- collection [9] All India Level Incidence of Accidental Deaths by Causes (change_in_header; free); best score 86.31578947368422; e.g. 2919441 All India Level Incidence of Accidental Deaths by Causes during 1987 & 1988
- nid 2950801 (non-mergeable, no collection; free; score 90; window 1974; hdr 'Sl. No.,Category,Causes of Accidental Deaths,Number of Accidental Deaths,Percentage to Total Accidental Deaths  1974,Per'; file a613e6e1-7a13-4d20-8fd0-6d72feee1720.csv) All India Level Incidence of Accidental Deaths during 1974
- nid 2951721 (non-mergeable, no collection; free; score 90; window 1973; hdr 'Sl. No.,Category,Causes of Accidental Deaths,Number of Accidental Death,Percentage to Total Accidental Deaths  1973,Perc'; file 05337765-10da-405e-8f9d-948ddced7ec1.csv) All India Level Incidence of Accidental Deaths during 1973

---

## C6 · All India level Incidence of Crime, Volume of Crime Per Lakh of Population and Percentage Variation during 1987 over 1977, over Quinquennial Average of 1982 to 1986 and over (schema 1)

- ministry: Ministry of Home Affairs, Department of States, National Crime Records Bureau (NCRB) | members in scope: 6 | current mac: review
- detector: flags SCHEMA_N_SUFFIX,MAC_REVIEW | min_header_match  | admin levels india | varying dims year | suggested mac year | header dims -
- varying title text: Lakh of Population from 1974 to 1984 and Percentage Variation during 1984 over 1974, over Quinquennial Average of 1979 to 1983 and over 1983 | One Lakh of Population & Percentage Variation during 1981 over 1971, Over Quinquennial Average of 1976 to 1980 and Over 1980 | One Lakh of Population from 1970 to 1980 & Percentage Variation during 1980 over 1970, over Quinquennial Average of 1975-1979 and over 1979 | One Lakh of Population from 1972 to 1982 & Percentage Variation during 1982 Over 1972, Over Quinquennial Average of 1977 to 1981 and Over 1981 | One Lakh of Population from 1975 to 1985 an
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=All India Level Incidence of Crime, Volume of Crime Per Lakh of Population and Percentage Variation over Base Year and Quinquennial Average | mac=year | notes=same table as the 1960s-edition sibling

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [6] 6 cols, year-labelled cols 90%: Heads of Crime | Incidence  1974 | Volume  1974 | Quinquennial Average 19791983 Q.A. | Percentage Change in 1984  Increase  Decrease  Over  1974 | Percentage Change in 1984  Increase  Decrease  Over  Quinquennial Average

### Members

nid | group | header | window | yr-cols | period (data) | file | title
774581 | G10 | H1 | 1974-1984 | 90% | 1974-01-01..1984-12-31 | f5cfcec8-5310-4552-9631-0301cbc7f7a4.csv | All India level Incidence of Crime, Volume of Crime Per Lakh of Population from 1974 to 1984 and Percentage Variation during 1984 over 1974, over Quinquennial Average of 1979 to 1983 and over 1983
1037921 | G14 | H1 | 1976-1980 | 90% | 1971-01-01..1981-12-31 | 2f5ee15f-3e9b-4e12-90a3-652198a8291f.csv | All India level Incidence of Crime, Volume of Crime per One Lakh of Population & Percentage Variation during 1981 over 1971, Over Quinquennial Average of 1976 to 1980 and Over 1980
1067281 | G15 | H1 | 1970-1980 | 90% | 1970-01-01..1980-12-31 | c57985ef-cbfb-465f-bd89-cea5dbf0247c.csv | All India level Incidence of Crime, Volume of Crime per One Lakh of Population from 1970 to 1980 & Percentage Variation during 1980 over 1970, over Quinquennial Average of 1975-1979 and over 1979
839941 | G11 | H1 | 1972-1982 | 90% | 1972-01-01..1982-12-31 | 52389095-9844-4ddc-b6c5-f41aee2df277.csv | All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1972 to 1982 & Percentage Variation during 1982 Over 1972, Over Quinquennial Average of 1977 to 1981 and Over 1981
768701 | G12 | H1 | 1975-1985 | 90% | 1975-01-01..1985-12-31 | aec98fa3-95ec-486b-afad-84f336f9ae80.csv | All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1975 to 1985 and Percentage Variation during 1985 over 1975, over Quinquennial Average of 1980 to 1984 and over 1984
750801 | G13 | H1 | 1976-1986 | 90% | 1976-01-01..1986-12-31 | 5c0f0554-af0e-4b91-bf2c-a79167b939e4.csv | All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1976 to 1986 and Percentage Variation in 1986 Over 1976, Over Quinquennial Average of 1981 to 1985 and Over 1985

### Similar rows outside this collection (same ministry)

- collection [5] All India Level Incidence of Crime and Population (change_in_header; free); best score 90; e.g. 2065561 All India Level Incidence of Crime and Population from 1963 to 1968
- nid 742121 (non-mergeable, no collection; free; score 100.0; window 1982-1986; hdr 'SL. No.,Heads of Crime,Incidence  1977,Volume  1977,Incidence  1982,Volume  1982,Incidence  1983,Volume  1983,Incidence '; file 89e1a687-8777-4963-86a4-751398072ce5.csv) All India level Incidence of Crime, Volume of Crime Per Lakh of Population and Percentage Variation during 1987 over 1977, over Quinquennial Average of 1982 to 1986 and over 1986
- nid 1897801 (non-mergeable, no collection; free; score 90; window 1960-1971; hdr 'Date,Code,CommodityId,CommodityName,DistrictName,DistrictCode,Stock,CommodityStock,TotalStock'; file 5bc8b325-fbf7-4b6f-a08f-40a3791fb472.csv) All India level Incidence of Crime and Population from 1960 to 1971
- nid 1912521 (non-mergeable, no collection; free; score 90; window 1960-1970; hdr 'SL. No.,Year,Estimated MidYear Population in Millions,Total Cognizable Crime Under the Indian Penal Code,Rate of Crime P'; file b6fc5f8d-0ff6-4481-8ebe-b916a5d4ef51.csv) All India level Incidence of Crime and Population from 1960 to 1970
- nid 2009861 (non-mergeable, no collection; free; score 90; window 1960-1969; hdr 'SL. No.,Year,Estimated MidYear Population in Millions,Total Cognizable Crime Under the Indian Penal Code,Rate of Crime P'; file 5cbd2975-7ace-4a06-98f8-21b3b2db7e31.csv) All India Level Incidence of Crime and Population from 1960 to 1969
- nid 2065621 (non-mergeable, no collection; free; score 90; window 1963-1968; hdr 'SL. No.,Heads of Crime,Incidence  1963,Volume  1963,Incidence  1964,Volume  1964,Incidence  1965,Volume  1965,Incidence '; file 0bf6022e-db9c-44e7-883a-a215a435c83d.csv) All India Level Incidence of Crime from 1963 to 1968
- nid 2374181 (non-mergeable, no collection; free; score 90; window 1962-1967; hdr 'SL. No.,Heads of Crime,Incidence  1962,Volume  1962,Incidence  1963,Volume  1963,Incidence  1964,Volume  1964,Incidence '; file aeea543f-fc6a-4c2c-9019-d926d6a9c6ce.csv) All India Level Incidence of Crime from 1962 to 1967
- nid 2465041 (non-mergeable, no collection; free; score 90; window 1961-1966; hdr 'SL. No.,Heads of Crime,Incidence  1961,Volume  1961,Incidence  1962,Volume  1962,Incidence  1963,Volume  1963,Incidence '; file b20bd13f-c635-4ee9-822b-75220effa893.csv) All India Level Incidence of Crime from 1961 to 1966

### Year windows of the same series (parsed from titles)

- NESTED: 2550501 (from 1960 to 1965) is contained in 2009861 (from 1960 to 1969)
- NESTED: 2550501 (from 1960 to 1965) is contained in 1912521 (from 1960 to 1970)
- NESTED: 2550501 (from 1960 to 1965) is contained in 1897801 (from 1960 to 1971)
- NESTED: 2009861 (from 1960 to 1969) is contained in 1912521 (from 1960 to 1970)
- NESTED: 2009861 (from 1960 to 1969) is contained in 1897801 (from 1960 to 1971)
- NESTED: 1912521 (from 1960 to 1970) is contained in 1897801 (from 1960 to 1971)
- NESTED: 2465001 (from 1961 to 1966) is contained in 2009861 (from 1960 to 1969)
- NESTED: 2465001 (from 1961 to 1966) is contained in 1912521 (from 1960 to 1970)
- NESTED: 2465001 (from 1961 to 1966) is contained in 1897801 (from 1960 to 1971)
- NESTED: 2374121 (from 1962 to 1967) is contained in 2009861 (from 1960 to 1969)
- NESTED: 2374121 (from 1962 to 1967) is contained in 1912521 (from 1960 to 1970)
- NESTED: 2374121 (from 1962 to 1967) is contained in 1897801 (from 1960 to 1971)
- NESTED: 2065561 (from 1963 to 1968) is contained in 2009861 (from 1960 to 1969)
- NESTED: 2065561 (from 1963 to 1968) is contained in 1912521 (from 1960 to 1970)
- NESTED: 2065561 (from 1963 to 1968) is contained in 1897801 (from 1960 to 1971)
- OVERLAP: 2551921 (from 1959 to 1964) overlaps 2550501 (from 1960 to 1965)
- OVERLAP: 2551921 (from 1959 to 1964) overlaps 2009861 (from 1960 to 1969)
- OVERLAP: 2551921 (from 1959 to 1964) overlaps 1912521 (from 1960 to 1970)
- OVERLAP: 2551921 (from 1959 to 1964) overlaps 1897801 (from 1960 to 1971)
- OVERLAP: 2551921 (from 1959 to 1964) overlaps 2465001 (from 1961 to 1966)
- OVERLAP: 2551921 (from 1959 to 1964) overlaps 2374121 (from 1962 to 1967)
- OVERLAP: 2551921 (from 1959 to 1964) overlaps 2065561 (from 1963 to 1968)
- OVERLAP: 2550501 (from 1960 to 1965) overlaps 2465001 (from 1961 to 1966)
- OVERLAP: 2550501 (from 1960 to 1965) overlaps 2374121 (from 1962 to 1967)
- OVERLAP: 2550501 (from 1960 to 1965) overlaps 2065561 (from 1963 to 1968)
- OVERLAP: 2465001 (from 1961 to 1966) overlaps 2374121 (from 1962 to 1967)
- OVERLAP: 2465001 (from 1961 to 1966) overlaps 2065561 (from 1963 to 1968)
- OVERLAP: 2374121 (from 1962 to 1967) overlaps 2065561 (from 1963 to 1968)
- OVERLAP: 2465041 (from 1961 to 1966) overlaps 2374181 (from 1962 to 1967)
- OVERLAP: 2465041 (from 1961 to 1966) overlaps 2065621 (from 1963 to 1968)
- OVERLAP: 2374181 (from 1962 to 1967) overlaps 2065621 (from 1963 to 1968)

---

## C7 · All India Level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1960 to 1969 and their Percentage Variation (schema 1)

- ministry: Ministry of Home Affairs, Department of States, National Crime Records Bureau (NCRB) | members in scope: 5 | current mac: review
- detector: flags SCHEMA_N_SUFFIX,MAC_REVIEW | min_header_match  | admin levels india | varying dims year | suggested mac year | header dims -
- varying title text: 1960 to 1969 | 1960 to 1970 | 1962 to 1972 | 1963 to 1973 | 1965 to 1975
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=All India Level Incidence of Crime, Volume of Crime Per Lakh of Population and Percentage Variation over Base Year and Quinquennial Average | mac=year | notes=same table as the 1987-edition sibling; year columns renamed

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [5] 6 cols, year-labelled cols 85%: Heads of Crime | Incidence  1960 | Volume  1960 | Quinquennial Average 19641968 Q.A. | Percentage Variation  Increase  Decrease  Over  1960 | Percentage Variation  Increase  Decrease  Over  Quinquennial Average

### Members

nid | group | header | window | yr-cols | period (data) | file | title
2009881 | G16 | H1 | 1960-1969 | 85% | 1960-01-01..1969-12-31 | 9323e2d6-78f7-4fc8-8038-69b887f415a3.csv | All India Level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1960 to 1969 and their Percentage Variation
1912541 | G17 | H1 | 1960-1970 | 85% | 1960-01-01..1970-12-31 | d1effdf2-da31-407f-8c0c-2eb3d6746320.csv | All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1960 to 1970 and their Percentage Variation
1300401 | G16 | H1 | 1962-1972 | 85% | 1962-01-01..1972-12-31 | 0197c123-38be-4381-bda1-764b962948bc.csv | All India Level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1962 to 1972 and their Percentage Variation
1174521 | G17 | H1 | 1963-1973 | 85% | 1963-01-01..1973-12-31 | a504efd6-c461-4319-b866-e7d6fad1aacc.csv | All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1963 to 1973 and their Percentage Variation
1118661 | G18 | H1 | 1965-1975 | 85% | 1965-01-01..1975-12-31 | 601b73ad-aa45-4e48-9d60-01ba275619a3.csv | All India level Incidence of Crime, Volume of Crime per One Lakh of Population from 1965 to 1975 and their Percentage Variation

### Similar rows outside this collection (same ministry)

- collection [5] All India Level Incidence of Crime and Population (change_in_header; free); best score 90; e.g. 2065561 All India Level Incidence of Crime and Population from 1963 to 1968
- nid 805841 (non-mergeable, no collection; free; score 100.0; window 1973-1983; hdr 'SL. No.,Heads of Crime,Incidence  1973,Volume  1973,Incidence  1978,Volume  1978,Incidence  1979,Volume  1979,Incidence '; file f28434da-011c-4564-9964-be6dab5a18c8.csv) All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1973 to 1983 and their Percentage Variation
- nid 1073081 (non-mergeable, no collection; free; score 100.0; window 1969-1979; hdr 'SL. No.,Heads of Crime,Incidence  1969,Volume  1969,Incidence  1974,Volume  1974,Incidence  1975,Volume  1975,Incidence '; file 3121542b-45cb-49c0-9ef6-35db77a460bc.csv) All India level Incidence of Crime, Volume of Crime per One Lakh of Population from 1969 to 1979 and their Percentage Variation
- nid 1079821 (non-mergeable, no collection; free; score 100.0; window 1968-1978; hdr 'SL. No.,Heads of Crime,Incidence  1968,Volume  1968,Incidence  1973,Volume  1973,Incidence  1974,Volume  1974,Incidence '; file a2703bb7-7380-4b04-bf7d-9c92657fc539.csv) All India level Incidence of Crime, Volume of Crime per One Lakh of Population from 1968 to 1978 and their Percentage Variation
- nid 1086801 (non-mergeable, no collection; free; score 100.0; window 1967-1977; hdr 'SL. No.,Heads of Crime,Incidence  1967,Volume  1967,Incidence  1972,Volume  1972,Incidence  1973,Volume  1973,Incidence '; file cbcf3086-086a-4e0c-9e73-9b341b20264c.csv) All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1967 to 1977 and their Percentage Variation
- nid 1092981 (non-mergeable, no collection; free; score 100.0; window 1966-1976; hdr 'SL. No.,Heads of Crime,Incidence  1966,Volume  1966,Incidence  1971,Volume  1971,Incidence  1972,Volume  1972,Incidence '; file cb2f06e6-0976-40a5-9e27-28b45d855b63.csv) All India level Incidence of Crime, Volume of Crime per One Lakh of Population from 1966 to 1976 and their Percentage Variation
- nid 1168981 (non-mergeable, no collection; free; score 100.0; window 1964-1974; hdr 'SL. No.,Heads of Crime,Incidence  1964,Volume  1964,Incidence  1969,Volume  1969,Incidence  1970,Volume  1970,Incidence '; file dd903e7a-5a18-4012-877e-5946c336c719.csv) All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1964 to 1974 and their Percentage Variation
- nid 1897821 (non-mergeable, no collection; free; score 100.0; window 1966-1971; hdr 'Date,Code,CommodityId,CommodityName,DistrictName,DistrictCode,Stock,CommodityStock,TotalStock'; file b038dfea-c5b2-4880-83d7-b17750d521e5.csv) All India level Incidence of Crime, Volume of Crime Per One Lakh of Population from 1966 to 1971 and their Percentage Variation
- nid 1897801 (non-mergeable, no collection; free; score 90; window 1960-1971; hdr 'Date,Code,CommodityId,CommodityName,DistrictName,DistrictCode,Stock,CommodityStock,TotalStock'; file 5bc8b325-fbf7-4b6f-a08f-40a3791fb472.csv) All India level Incidence of Crime and Population from 1960 to 1971
- nid 1912521 (non-mergeable, no collection; free; score 90; window 1960-1970; hdr 'SL. No.,Year,Estimated MidYear Population in Millions,Total Cognizable Crime Under the Indian Penal Code,Rate of Crime P'; file b6fc5f8d-0ff6-4481-8ebe-b916a5d4ef51.csv) All India level Incidence of Crime and Population from 1960 to 1970
- nid 2009861 (non-mergeable, no collection; free; score 90; window 1960-1969; hdr 'SL. No.,Year,Estimated MidYear Population in Millions,Total Cognizable Crime Under the Indian Penal Code,Rate of Crime P'; file 5cbd2975-7ace-4a06-98f8-21b3b2db7e31.csv) All India Level Incidence of Crime and Population from 1960 to 1969
- nid 2065621 (non-mergeable, no collection; free; score 90; window 1963-1968; hdr 'SL. No.,Heads of Crime,Incidence  1963,Volume  1963,Incidence  1964,Volume  1964,Incidence  1965,Volume  1965,Incidence '; file 0bf6022e-db9c-44e7-883a-a215a435c83d.csv) All India Level Incidence of Crime from 1963 to 1968
- nid 2374181 (non-mergeable, no collection; free; score 90; window 1962-1967; hdr 'SL. No.,Heads of Crime,Incidence  1962,Volume  1962,Incidence  1963,Volume  1963,Incidence  1964,Volume  1964,Incidence '; file aeea543f-fc6a-4c2c-9019-d926d6a9c6ce.csv) All India Level Incidence of Crime from 1962 to 1967
- nid 2465041 (non-mergeable, no collection; free; score 90; window 1961-1966; hdr 'SL. No.,Heads of Crime,Incidence  1961,Volume  1961,Incidence  1962,Volume  1962,Incidence  1963,Volume  1963,Incidence '; file b20bd13f-c635-4ee9-822b-75220effa893.csv) All India Level Incidence of Crime from 1961 to 1966

### Year windows of the same series (parsed from titles)

- NESTED: 2009881 (from 1960 to 1969) is contained in 1912541 (from 1960 to 1970)
- NESTED: 1897821 (from 1966 to 1971) is contained in 1300401 (from 1962 to 1972)
- NESTED: 1897821 (from 1966 to 1971) is contained in 1174521 (from 1963 to 1973)
- NESTED: 1897821 (from 1966 to 1971) is contained in 1168981 (from 1964 to 1974)
- NESTED: 1897821 (from 1966 to 1971) is contained in 1118661 (from 1965 to 1975)
- NESTED: 1897821 (from 1966 to 1971) is contained in 1092981 (from 1966 to 1976)
- NESTED: 2550501 (from 1960 to 1965) is contained in 2009861 (from 1960 to 1969)
- NESTED: 2550501 (from 1960 to 1965) is contained in 1912521 (from 1960 to 1970)
- NESTED: 2550501 (from 1960 to 1965) is contained in 1897801 (from 1960 to 1971)
- NESTED: 2009861 (from 1960 to 1969) is contained in 1912521 (from 1960 to 1970)
- NESTED: 2009861 (from 1960 to 1969) is contained in 1897801 (from 1960 to 1971)
- NESTED: 1912521 (from 1960 to 1970) is contained in 1897801 (from 1960 to 1971)
- NESTED: 2465001 (from 1961 to 1966) is contained in 2009861 (from 1960 to 1969)
- NESTED: 2465001 (from 1961 to 1966) is contained in 1912521 (from 1960 to 1970)
- NESTED: 2465001 (from 1961 to 1966) is contained in 1897801 (from 1960 to 1971)
- NESTED: 2374121 (from 1962 to 1967) is contained in 2009861 (from 1960 to 1969)
- NESTED: 2374121 (from 1962 to 1967) is contained in 1912521 (from 1960 to 1970)
- NESTED: 2374121 (from 1962 to 1967) is contained in 1897801 (from 1960 to 1971)
- NESTED: 2065561 (from 1963 to 1968) is contained in 2009861 (from 1960 to 1969)
- NESTED: 2065561 (from 1963 to 1968) is contained in 1912521 (from 1960 to 1970)
- NESTED: 2065561 (from 1963 to 1968) is contained in 1897801 (from 1960 to 1971)
- OVERLAP: 2009881 (from 1960 to 1969) overlaps 1300401 (from 1962 to 1972)
- OVERLAP: 2009881 (from 1960 to 1969) overlaps 1174521 (from 1963 to 1973)
- OVERLAP: 2009881 (from 1960 to 1969) overlaps 1168981 (from 1964 to 1974)
- OVERLAP: 2009881 (from 1960 to 1969) overlaps 1118661 (from 1965 to 1975)
- OVERLAP: 2009881 (from 1960 to 1969) overlaps 1897821 (from 1966 to 1971)
- OVERLAP: 2009881 (from 1960 to 1969) overlaps 1092981 (from 1966 to 1976)
- OVERLAP: 2009881 (from 1960 to 1969) overlaps 1086801 (from 1967 to 1977)
- OVERLAP: 2009881 (from 1960 to 1969) overlaps 1079821 (from 1968 to 1978)
- OVERLAP: 2009881 (from 1960 to 1969) overlaps 1073081 (from 1969 to 1979)
- OVERLAP: 1912541 (from 1960 to 1970) overlaps 1300401 (from 1962 to 1972)
- OVERLAP: 1912541 (from 1960 to 1970) overlaps 1174521 (from 1963 to 1973)
- OVERLAP: 1912541 (from 1960 to 1970) overlaps 1168981 (from 1964 to 1974)
- OVERLAP: 1912541 (from 1960 to 1970) overlaps 1118661 (from 1965 to 1975)
- OVERLAP: 1912541 (from 1960 to 1970) overlaps 1897821 (from 1966 to 1971)
- OVERLAP: 1912541 (from 1960 to 1970) overlaps 1092981 (from 1966 to 1976)
- OVERLAP: 1912541 (from 1960 to 1970) overlaps 1086801 (from 1967 to 1977)
- OVERLAP: 1912541 (from 1960 to 1970) overlaps 1079821 (from 1968 to 1978)
- OVERLAP: 1912541 (from 1960 to 1970) overlaps 1073081 (from 1969 to 1979)
- OVERLAP: 1300401 (from 1962 to 1972) overlaps 1174521 (from 1963 to 1973)
- OVERLAP: 1300401 (from 1962 to 1972) overlaps 1168981 (from 1964 to 1974)
- OVERLAP: 1300401 (from 1962 to 1972) overlaps 1118661 (from 1965 to 1975)
- OVERLAP: 1300401 (from 1962 to 1972) overlaps 1092981 (from 1966 to 1976)
- OVERLAP: 1300401 (from 1962 to 1972) overlaps 1086801 (from 1967 to 1977)
- OVERLAP: 1300401 (from 1962 to 1972) overlaps 1079821 (from 1968 to 1978)
- OVERLAP: 1300401 (from 1962 to 1972) overlaps 1073081 (from 1969 to 1979)
- OVERLAP: 1174521 (from 1963 to 1973) overlaps 1168981 (from 1964 to 1974)
- OVERLAP: 1174521 (from 1963 to 1973) overlaps 1118661 (from 1965 to 1975)
- OVERLAP: 1174521 (from 1963 to 1973) overlaps 1092981 (from 1966 to 1976)
- OVERLAP: 1174521 (from 1963 to 1973) overlaps 1086801 (from 1967 to 1977)
- OVERLAP: 1174521 (from 1963 to 1973) overlaps 1079821 (from 1968 to 1978)
- OVERLAP: 1174521 (from 1963 to 1973) overlaps 1073081 (from 1969 to 1979)
- OVERLAP: 1174521 (from 1963 to 1973) overlaps 805841 (from 1973 to 1983)
- OVERLAP: 1168981 (from 1964 to 1974) overlaps 1118661 (from 1965 to 1975)
- OVERLAP: 1168981 (from 1964 to 1974) overlaps 1092981 (from 1966 to 1976)
- OVERLAP: 1168981 (from 1964 to 1974) overlaps 1086801 (from 1967 to 1977)
- OVERLAP: 1168981 (from 1964 to 1974) overlaps 1079821 (from 1968 to 1978)
- OVERLAP: 1168981 (from 1964 to 1974) overlaps 1073081 (from 1969 to 1979)
- OVERLAP: 1168981 (from 1964 to 1974) overlaps 805841 (from 1973 to 1983)
- OVERLAP: 1118661 (from 1965 to 1975) overlaps 1092981 (from 1966 to 1976)
- OVERLAP: 1118661 (from 1965 to 1975) overlaps 1086801 (from 1967 to 1977)
- ... 32 more overlapping pairs

---

## C8 · All India level Juveniles Apprehended by Age Group (schema 1)

- ministry: Ministry of Home Affairs, Department of States, National Crime Records Bureau (NCRB) | members in scope: 8 | current mac: review
- detector: flags NAME_PINS_VALUE,SCHEMA_N_SUFFIX,MAC_REVIEW | min_header_match  | admin levels india | varying dims year | suggested mac year | header dims -
- varying title text: 1965 to 1975 | 1966 to 1976 | 1967 to 1977 | 1968 to 1978 | 1969 to 1979 | 1970 to 1980 | 1971 to 1981 | 1972 to 1982
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename | name=All India level Juveniles Apprehended by Age Group | mac=- | notes=identical columns to the bare collection - folded in

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [8] 3 cols, year-labelled cols 0%: Years | 712 Year  Percentage to Total | Overall Age  Groups

### Members

nid | group | header | window | yr-cols | period (data) | file | title
1119341 | G19 | H1 | 1965-1975 | 0% | 1965-01-01..1975-12-31 | 3d5cc871-ce2b-4b32-a052-8100a6cd17b8.csv | All India level Juvenile Apprehended by Age Group from 1965 to 1975
1093041 | G19 | H1 | 1966-1976 | 0% | 1966-01-01..1976-12-31 | 715c5b4e-e642-4bc0-bc4f-ef3cdb9c1d55.csv | All India level Juvenile Apprehended by Age Group from 1966 to 1976
1087121 | G19 | H1 | 1967-1977 | 0% | 1967-01-01..1977-12-31 | f0ff6873-227d-4af6-a617-914778e6ebc1.csv | All India level Juvenile Apprehended by Age Group from 1967 to 1977
1080541 | G19 | H1 | 1968-1978 | 0% | 1968-01-01..1978-12-31 | 3f6184fc-e50a-4536-839e-b29a268f37ff.csv | All India level Juvenile Apprehended by Age Group from 1968 to 1978
1073801 | G19 | H1 | 1969-1979 | 0% | 1969-01-01..1979-12-31 | a24aee33-92cf-44f0-befe-b6a85e23254d.csv | All India level Juvenile Apprehended by Age Group from 1969 to 1979
1068001 | G19 | H1 | 1970-1980 | 0% | 1970-01-01..1980-12-31 | af0a45f8-15d4-4006-9d7c-e59a46ceeed9.csv | All India level Juvenile Apprehended by Age Group from 1970 to 1980
1038641 | G19 | H1 | 1971-1981 | 0% | 1971-01-01..1981-12-31 | 3e41e931-71a1-4c6e-ab1c-2de0ce67c2a8.csv | All India level Juvenile Apprehended by Age Group from 1971 to 1981
840101 | G19 | H1 | 1972-1982 | 0% | 1972-01-01..1982-12-31 | 0636c504-0c13-4574-be97-81d937166db7.csv | All India level Juvenile Apprehended by Age Group from 1972 to 1982

### Similar rows outside this collection (same ministry)

- collection [7] All India level Juveniles Apprehended by Age Group (change_in_header; free); best score 98.73417721518987; e.g. 768861 All India level Juveniles Apprehended by Age Group from 1975 to 1985
- collection [5] All India level Juveniles Apprehended by Age Group (schema 2) (change_in_header; in scope, batch CAL); best score 90.69767441860466; e.g. 805961 All India level Juvenile Apprehended by Age Group and Sex during 1983
- collection [6] All India level Juveniles Apprehended by Age Group and Sex (change_in_header; free); best score 89.65517241379311; e.g. 840061 All India level Juveniles Apprehended by Age Group and Sex during 1982
- collection [6] All India level Juveniles Apprehended under Age Groups (change_in_header; free); best score 89.1566265060241; e.g. 2465201 All India level Juveniles Apprehended under Age Groups during 1966
- collection [5] All India level Juveniles Apprehended by Sex (schema 1) (change_in_header; free); best score 86.11111111111111; e.g. 805981 All India level Juvenile Apprehended by Sex from 1973 to 1983
- nid 742281 (non-mergeable, no collection; free; score 98.73417721518987; window 1977-1987; hdr 'SL. No.,Year,712 Years,712 Years  Percentage to Total,1216 Years,1216 Years  Percentage to Total,1618 Years,1618 Years  '; file 22cf9b47-40e3-4b61-925f-abe075f46fc9.csv) All India level Juveniles Apprehended by Age Group from 1977 to 1987
- nid 751181 (non-mergeable, no collection; free; score 98.73417721518987; window 1976-1986; hdr 'SL. No.,Year,712 Years,712 Years  Percentage of Total,1216 Years,1216 Years  Percentage to Total,1618 Years,1618 Years  '; file 3fddcfdc-ef89-45ac-9690-0e052cd423c5.csv) All India level Juveniles Apprehended by Age Group from 1976 to 1986
- nid 774741 (non-mergeable, no collection; free; score 98.73417721518987; window 1974-1984; hdr 'SL. No.,Years,712 Years,712 Years  Percentage to Total,1216 Years,1216 Years  Percentage to Total,1618 Years,1618 Years '; file 2513a57d-e72a-45a1-9d9b-01f9731c6adb.csv) All India level Juveniles Apprehended by Age Group from 1974 to 1984
- nid 1898241 (non-mergeable, no collection; free; score 98.73417721518987; window 1960-1971; hdr 'Date,Code,CommodityId,CommodityName,DistrictName,DistrictCode,Stock,CommodityStock,TotalStock'; file 3a5968e4-e75d-48d9-ac37-b23476351a59.csv) All India level Juveniles Apprehended by Age Group from 1960 to 1971
- nid 1087021 (non-mergeable, no collection; free; score 90.69767441860466; window 1977; hdr 'SL. No.,Category,Heads of Crime ,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 '; file a3c923a7-29a5-4f13-8a8b-e8efba277ecf.csv) All India level Juvenile Apprehended by Age Group and Sex during 1977
- nid 751101 (non-mergeable, no collection; free; score 89.65517241379311; window 1986; hdr 'SL. No.,Category,Crime Head,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Years'; file 08d24776-eafb-4c38-bb73-5cb25db86588.csv) All India level Juveniles Apprehended in India by Age Group and Sex during 1986
- nid 768821 (non-mergeable, no collection; free; score 89.65517241379311; window 1985; hdr 'SL. No.,Category,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Y'; file 446b39ce-9b60-470a-aa9c-8973c48760cb.csv) All India level Juveniles Apprehended in India by Age Group and Sex during 1985
- nid 774701 (non-mergeable, no collection; free; score 89.65517241379311; window 1984; hdr 'SL. No.,Category,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Y'; file 8e75425b-64d7-4f6a-a6b1-83c43040c3a7.csv) All India level Juveniles Apprehended in India by Age Group and Sex during 1984
- nid 1092921 (non-mergeable, no collection; free; score 89.65517241379311; window 1976; hdr 'SL. No.,Category,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Y'; file 26e9a793-2526-49b1-90e1-deab11fea8d8.csv) All India level Juveniles Apprehended in India by Age Group and Sex during 1976
- nid 1898201 (non-mergeable, no collection; free; score 89.65517241379311; window 1971; hdr 'Date,Code,CommodityId,CommodityName,DistrictName,DistrictCode,Stock,CommodityStock,TotalStock'; file aa1100fd-a42f-4be8-97ef-6c545fd64a78.csv) All India level Juveniles Apprehended by Age Group and Sex during 1971
- nid 2010161 (non-mergeable, no collection; free; score 89.65517241379311; window 1969; hdr 'SL. No.,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Years  Gir'; file 06e4c768-fe6e-45a4-817b-6adf9cbbc58e.csv) All India level Juveniles Apprehended by Age Group and Sex during 1969
- nid 2065841 (non-mergeable, no collection; free; score 89.65517241379311; window 1968; hdr 'SL. No.,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Years  Gir'; file bd358e0e-c02f-4339-9d27-0a3c291a18ff.csv) All India level Juveniles Apprehended by Age Group and Sex during 1968

### Year windows of the same series (parsed from titles)

- NESTED: 2010201 (from 1960 to 1969) is contained in 1912881 (from 1960 to 1970)
- NESTED: 2010201 (from 1960 to 1969) is contained in 1898241 (from 1960 to 1971)
- NESTED: 1912881 (from 1960 to 1970) is contained in 1898241 (from 1960 to 1971)
- NESTED: 1301121 (from 1963 to 1972) is contained in 1175241 (from 1963 to 1973)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1093041 (from 1966 to 1976)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1087121 (from 1967 to 1977)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1080541 (from 1968 to 1978)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1073801 (from 1969 to 1979)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1068001 (from 1970 to 1980)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 1087121 (from 1967 to 1977)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 1080541 (from 1968 to 1978)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 1073801 (from 1969 to 1979)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 1068001 (from 1970 to 1980)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1087121 (from 1967 to 1977) overlaps 1080541 (from 1968 to 1978)
- OVERLAP: 1087121 (from 1967 to 1977) overlaps 1073801 (from 1969 to 1979)
- OVERLAP: 1087121 (from 1967 to 1977) overlaps 1068001 (from 1970 to 1980)
- OVERLAP: 1087121 (from 1967 to 1977) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1087121 (from 1967 to 1977) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1080541 (from 1968 to 1978) overlaps 1073801 (from 1969 to 1979)
- OVERLAP: 1080541 (from 1968 to 1978) overlaps 1068001 (from 1970 to 1980)
- OVERLAP: 1080541 (from 1968 to 1978) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1080541 (from 1968 to 1978) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1073801 (from 1969 to 1979) overlaps 1068001 (from 1970 to 1980)
- OVERLAP: 1073801 (from 1969 to 1979) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1073801 (from 1969 to 1979) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1068001 (from 1970 to 1980) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1068001 (from 1970 to 1980) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1038641 (from 1971 to 1981) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 2010201 (from 1960 to 1969) overlaps 1301121 (from 1963 to 1972)
- OVERLAP: 2010201 (from 1960 to 1969) overlaps 1175241 (from 1963 to 1973)
- OVERLAP: 2010201 (from 1960 to 1969) overlaps 1169701 (from 1964 to 1974)
- OVERLAP: 1912881 (from 1960 to 1970) overlaps 1301121 (from 1963 to 1972)
- OVERLAP: 1912881 (from 1960 to 1970) overlaps 1175241 (from 1963 to 1973)
- OVERLAP: 1912881 (from 1960 to 1970) overlaps 1169701 (from 1964 to 1974)
- OVERLAP: 1898241 (from 1960 to 1971) overlaps 1301121 (from 1963 to 1972)
- OVERLAP: 1898241 (from 1960 to 1971) overlaps 1175241 (from 1963 to 1973)
- OVERLAP: 1898241 (from 1960 to 1971) overlaps 1169701 (from 1964 to 1974)
- OVERLAP: 1301121 (from 1963 to 1972) overlaps 1169701 (from 1964 to 1974)
- OVERLAP: 1175241 (from 1963 to 1973) overlaps 1169701 (from 1964 to 1974)
- OVERLAP: 1175241 (from 1963 to 1973) overlaps 806001 (from 1973 to 1983)
- ... 18 more overlapping pairs

---

## C9 · All India level Juveniles Apprehended by Age Group (schema 2)

- ministry: Ministry of Home Affairs, Department of States, National Crime Records Bureau (NCRB) | members in scope: 5 | current mac: review
- detector: flags NAME_PINS_VALUE,SCHEMA_N_SUFFIX,MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels india | varying dims year | suggested mac year | header dims -
- varying title text: by Age Group and Sex during 1978 | by Age Group and Sex during 1979 | by Age Group and Sex during 1981 | by Age Group and Sex during 1983 | in India by Age Group and Sex during 1980
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=All India level Juveniles Apprehended by Age Group and Sex under Crime Heads | mac=year

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [5] 7 cols, year-labelled cols 0%: Category | Heads of Crime | Between 712 Years  Boys | Between 712 Years  Girls | Overall Age Groups  Boys | Overall Age Groups  Girls | Total  BoysGirls

### Members

nid | group | header | window | yr-cols | period (data) | file | title
1080501 | G20 | H1 | 1978 | 0% | 1978-01-01..1978-12-31 | 77cb8681-1199-4338-856f-94a69b8c19b7.csv | All India level Juvenile Apprehended by Age Group and Sex during 1978
1073761 | G20 | H1 | 1979 | 0% | 1979-01-01..1979-12-31 | 35373daf-8290-4d05-b71c-0b2717ede65f.csv | All India level Juvenile Apprehended by Age Group and Sex during 1979
1038601 | G20 | H1 | 1981 | 0% | 1981-01-01..1981-12-31 | ecd92e3b-7227-451c-b8a7-ab595a75bfd9.csv | All India level Juvenile Apprehended by Age Group and Sex during 1981
805961 | G20 | H1 | 1983 | 0% | 1983-01-01..1983-12-31 | 2e930aa2-9a05-452c-8283-4568078c53cd.csv | All India level Juvenile Apprehended by Age Group and Sex during 1983
1067961 | G21 | H1 | 1980 | 0% | 1980-01-01..1980-12-31 | 93fc58eb-6793-4a17-a1bc-756c99a416b9.csv | All India level Juvenile Apprehended in India by Age Group and Sex during 1980

### Similar rows outside this collection (same ministry)

- collection [6] All India level Juveniles Apprehended by Age Group and Sex (change_in_header; free); best score 98.94736842105263; e.g. 840061 All India level Juveniles Apprehended by Age Group and Sex during 1982
- collection [8] All India level Juveniles Apprehended by Age Group (schema 1) (change_in_header; in scope, batch CAL); best score 90.69767441860466; e.g. 840101 All India level Juvenile Apprehended by Age Group from 1972 to 1982
- collection [5] All India level Juveniles Apprehended by Sex (schema 1) (change_in_header; free); best score 90; e.g. 805981 All India level Juvenile Apprehended by Sex from 1973 to 1983
- collection [7] All India level Juveniles Apprehended by Age Group (change_in_header; free); best score 89.65517241379311; e.g. 768861 All India level Juveniles Apprehended by Age Group from 1975 to 1985
- nid 1087021 (non-mergeable, no collection; free; score 100.0; window 1977; hdr 'SL. No.,Category,Heads of Crime ,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 '; file a3c923a7-29a5-4f13-8a8b-e8efba277ecf.csv) All India level Juvenile Apprehended by Age Group and Sex during 1977
- nid 751101 (non-mergeable, no collection; free; score 98.94736842105263; window 1986; hdr 'SL. No.,Category,Crime Head,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Years'; file 08d24776-eafb-4c38-bb73-5cb25db86588.csv) All India level Juveniles Apprehended in India by Age Group and Sex during 1986
- nid 768821 (non-mergeable, no collection; free; score 98.94736842105263; window 1985; hdr 'SL. No.,Category,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Y'; file 446b39ce-9b60-470a-aa9c-8973c48760cb.csv) All India level Juveniles Apprehended in India by Age Group and Sex during 1985
- nid 774701 (non-mergeable, no collection; free; score 98.94736842105263; window 1984; hdr 'SL. No.,Category,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Y'; file 8e75425b-64d7-4f6a-a6b1-83c43040c3a7.csv) All India level Juveniles Apprehended in India by Age Group and Sex during 1984
- nid 1092921 (non-mergeable, no collection; free; score 98.94736842105263; window 1976; hdr 'SL. No.,Category,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Y'; file 26e9a793-2526-49b1-90e1-deab11fea8d8.csv) All India level Juveniles Apprehended in India by Age Group and Sex during 1976
- nid 1898201 (non-mergeable, no collection; free; score 98.94736842105263; window 1971; hdr 'Date,Code,CommodityId,CommodityName,DistrictName,DistrictCode,Stock,CommodityStock,TotalStock'; file aa1100fd-a42f-4be8-97ef-6c545fd64a78.csv) All India level Juveniles Apprehended by Age Group and Sex during 1971
- nid 2010161 (non-mergeable, no collection; free; score 98.94736842105263; window 1969; hdr 'SL. No.,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Years  Gir'; file 06e4c768-fe6e-45a4-817b-6adf9cbbc58e.csv) All India level Juveniles Apprehended by Age Group and Sex during 1969
- nid 2065841 (non-mergeable, no collection; free; score 98.94736842105263; window 1968; hdr 'SL. No.,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Years  Gir'; file bd358e0e-c02f-4339-9d27-0a3c291a18ff.csv) All India level Juveniles Apprehended by Age Group and Sex during 1968
- nid 2374361 (non-mergeable, no collection; free; score 91.83673469387756; window 1967; hdr 'SL. No.,Heads of Crime,Between 712 Years  Boys,Between 712 Years  Girls,Between 1216 Years  Boys,Between 1216 Years  Gir'; file 842d6d1f-44c3-40f3-9cb0-5a38d776dcd6.csv) All India level Juveniles Apprehended under Age Group and Sex during 1967
- nid 742281 (non-mergeable, no collection; free; score 89.65517241379311; window 1977-1987; hdr 'SL. No.,Year,712 Years,712 Years  Percentage to Total,1216 Years,1216 Years  Percentage to Total,1618 Years,1618 Years  '; file 22cf9b47-40e3-4b61-925f-abe075f46fc9.csv) All India level Juveniles Apprehended by Age Group from 1977 to 1987
- nid 751181 (non-mergeable, no collection; free; score 89.65517241379311; window 1976-1986; hdr 'SL. No.,Year,712 Years,712 Years  Percentage of Total,1216 Years,1216 Years  Percentage to Total,1618 Years,1618 Years  '; file 3fddcfdc-ef89-45ac-9690-0e052cd423c5.csv) All India level Juveniles Apprehended by Age Group from 1976 to 1986
- nid 774741 (non-mergeable, no collection; free; score 89.65517241379311; window 1974-1984; hdr 'SL. No.,Years,712 Years,712 Years  Percentage to Total,1216 Years,1216 Years  Percentage to Total,1618 Years,1618 Years '; file 2513a57d-e72a-45a1-9d9b-01f9731c6adb.csv) All India level Juveniles Apprehended by Age Group from 1974 to 1984
- nid 1898241 (non-mergeable, no collection; free; score 89.65517241379311; window 1960-1971; hdr 'Date,Code,CommodityId,CommodityName,DistrictName,DistrictCode,Stock,CommodityStock,TotalStock'; file 3a5968e4-e75d-48d9-ac37-b23476351a59.csv) All India level Juveniles Apprehended by Age Group from 1960 to 1971

### Year windows of the same series (parsed from titles)

- NESTED: 2010201 (from 1960 to 1969) is contained in 1912881 (from 1960 to 1970)
- NESTED: 2010201 (from 1960 to 1969) is contained in 1898241 (from 1960 to 1971)
- NESTED: 1912881 (from 1960 to 1970) is contained in 1898241 (from 1960 to 1971)
- NESTED: 1301121 (from 1963 to 1972) is contained in 1175241 (from 1963 to 1973)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1093041 (from 1966 to 1976)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1087121 (from 1967 to 1977)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1080541 (from 1968 to 1978)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1073801 (from 1969 to 1979)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1068001 (from 1970 to 1980)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1119341 (from 1965 to 1975) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 1087121 (from 1967 to 1977)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 1080541 (from 1968 to 1978)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 1073801 (from 1969 to 1979)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 1068001 (from 1970 to 1980)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1093041 (from 1966 to 1976) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1087121 (from 1967 to 1977) overlaps 1080541 (from 1968 to 1978)
- OVERLAP: 1087121 (from 1967 to 1977) overlaps 1073801 (from 1969 to 1979)
- OVERLAP: 1087121 (from 1967 to 1977) overlaps 1068001 (from 1970 to 1980)
- OVERLAP: 1087121 (from 1967 to 1977) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1087121 (from 1967 to 1977) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1080541 (from 1968 to 1978) overlaps 1073801 (from 1969 to 1979)
- OVERLAP: 1080541 (from 1968 to 1978) overlaps 1068001 (from 1970 to 1980)
- OVERLAP: 1080541 (from 1968 to 1978) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1080541 (from 1968 to 1978) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1073801 (from 1969 to 1979) overlaps 1068001 (from 1970 to 1980)
- OVERLAP: 1073801 (from 1969 to 1979) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1073801 (from 1969 to 1979) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1068001 (from 1970 to 1980) overlaps 1038641 (from 1971 to 1981)
- OVERLAP: 1068001 (from 1970 to 1980) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 1038641 (from 1971 to 1981) overlaps 840101 (from 1972 to 1982)
- OVERLAP: 2010201 (from 1960 to 1969) overlaps 1301121 (from 1963 to 1972)
- OVERLAP: 2010201 (from 1960 to 1969) overlaps 1175241 (from 1963 to 1973)
- OVERLAP: 2010201 (from 1960 to 1969) overlaps 1169701 (from 1964 to 1974)
- OVERLAP: 1912881 (from 1960 to 1970) overlaps 1301121 (from 1963 to 1972)
- OVERLAP: 1912881 (from 1960 to 1970) overlaps 1175241 (from 1963 to 1973)
- OVERLAP: 1912881 (from 1960 to 1970) overlaps 1169701 (from 1964 to 1974)
- OVERLAP: 1898241 (from 1960 to 1971) overlaps 1301121 (from 1963 to 1972)
- OVERLAP: 1898241 (from 1960 to 1971) overlaps 1175241 (from 1963 to 1973)
- OVERLAP: 1898241 (from 1960 to 1971) overlaps 1169701 (from 1964 to 1974)
- OVERLAP: 1301121 (from 1963 to 1972) overlaps 1169701 (from 1964 to 1974)
- OVERLAP: 1175241 (from 1963 to 1973) overlaps 1169701 (from 1964 to 1974)
- OVERLAP: 1175241 (from 1963 to 1973) overlaps 806001 (from 1973 to 1983)
- ... 18 more overlapping pairs
