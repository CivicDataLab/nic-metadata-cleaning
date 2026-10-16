# Evidence pack AH: 15 collections, 416 rows


---

## C1 · Details of bovines by sex

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 31 | current mac: review
- detector: flags HEADER_IRRECONCILABLE,MAC_REVIEW,MAC_MISSING_DIM | min_header_match 0.5 | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [17] 4 cols, year-labelled cols 0%: District | Bovine  Male | Bovine  Female | Bovine  Total
- H2 [12] 10 cols, year-labelled cols 0%: District | Bovine  Rural Male | Bovine  Urban Male | Bovine  Male Total | Bovine  Rural Female | Bovine  Urban Female | Bovine  Female Total | Bovine  Total Rural | Bovine  Total Urban | Bovine  Total
    match vs H1 1.00; only here: ['Bovine  Rural Female', 'Bovine  Rural Male', 'Bovine  Total Rural', 'Bovine  Female Total', 'Bovine  Male Total', 'Bovine  Total Urban', 'Bovine  Urban Female', 'Bovine  Urban Male']; only in H1: ['bovine female', 'bovine male']
- H3 [2] 10 cols, year-labelled cols 0%: District | Male  Rural | Male  Urban | Male  Total | Female  Rural | Female  Urban | Female  Total | Total Bovine  Rural | Total Bovine  Urban | Total Bovine  Total
    match vs H1 0.50; only here: ['Total Bovine  Rural', 'Male  Total', 'Male  Rural', 'Female  Rural', 'Female  Total', 'Total Bovine  Total', 'Female  Urban', 'Total Bovine  Urban', 'Male  Urban']; only in H1: ['bovine female', 'bovine male', 'bovine total']

### Members

31 members, grouped (group | header | members | years in titles | sample titles):
- G1 | H1 | 17 | 2012x17 | template: Details of bovines by sex for <STATE> - <YEAR>
    e.g. Details of bovines by sex for Chandigarh - 2012 || Details of bovines by sex for Dadra and Nagar Haveli - 2012 || Details of bovines by sex for Daman and Diu - 2012
- G2 | H2 | 12 | 2012x12 | template: Details of bovines by sex for <STATE> - <YEAR>
    e.g. Details of bovines by sex for Andhra Pradesh - 2012 || Details of bovines by sex for Arunachal Pradesh - 2012 || Details of bovines by sex for Assam - 2012
- G3 | H3 | 2 | 2012x2 | template: Details of bovines by sex for <STATE> - <YEAR>
    e.g. Details of bovines by sex for Uttarakhand - 2012 || Details of bovines by sex for West Bengal - 2012

### Similar rows outside this collection (same ministry)

- nid 297041 (non-mergeable, no collection; free; score 100.0; window 2012; hdr 'SNo.,District,Bovine  Male,Bovine  Male,Bovine  Total'; file e0e35ebc-bd4b-4fb1-99d7-612389c479a8.csv) Details of bovines by sex for Jammu and Kashmir - 2012
- nid 298641 (non-mergeable, no collection; free; score 100.0; window 2012; hdr 'SNo.,District,Bovine  Rural Male,Bovine  Female,Bovine  Total'; file 79825985-0f53-46f6-8bc1-5ba19e524347.csv) Details of bovines by sex for Lakshadweep - 2012
- nid 301841 (non-mergeable, no collection; free; score 100.0; window 2012; hdr 'SNo.,District,Bovine  Male,Bovine  Female,Total Bovine'; file 09fb0170-d2bf-4f1c-8d55-9c33372e66c2.csv) Details of bovines by sex for Puducherry - 2012
- nid 291841 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Bovine  Male,Bovine  Female,Bovine  Total'; file e4fd4304-877a-47e7-aea5-6b1d21dfafd3.csv) Details of bovines by sex for Andman and Nicobar Islands - 2012

---

## C2 · Details of camels by age and sex in rural and urban combined

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 34 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match 1.0 | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [31] 8 cols, year-labelled cols 0%: District | Camels  Male Under 4 year | Camels  Male 4 Year and Above | Camels  Male Total | Camels  Female Under 4 year | Camels  Female 4 Year and Above | Camels  Female Total | Camels  Total
- H2 [1] 9 cols, year-labelled cols 0%: S No. | District | Camels  Male Under 4 year | Camels  Male 4 Year and Above | Camels  Male Total | Camels  Female Under 4 year | Camels  Female 4 Year and Above | Camels  Female Total | Camels  Total
    match vs H1 1.00; only here: ['S No.']; only in H1: []
- H3 [1] 9 cols, year-labelled cols 0%: S No. | District | Male  Under 4 Years | Male  4 Years and Above | Male  Total | Female  Under 4 Years | Female  4 Years and Above | Female  Total | Total Camel
    match vs H1 1.00; only here: ['Male  Under 4 Years', 'Male  Total', 'Female  4 Years and Above', 'Female  Total', 'Female  Under 4 Years', 'Male  4 Years and Above', 'S No.']; only in H1: ['above camel female year', 'above camel male year', 'camel female total', 'camel female under year', 'camel male total', 'camel male under year']
- H4 [1] 8 cols, year-labelled cols 0%: District | Male  Under 4 Years | Male  4 Years and Above | Male  Total | Female  Under 4 Years | Female  4 Years and Above | Female  Total | Total Camel
    match vs H1 1.00; only here: ['Male  Under 4 Years', 'Male  Total', 'Female  4 Years and Above', 'Female  Total', 'Female  Under 4 Years', 'Male  4 Years and Above']; only in H1: ['above camel female year', 'above camel male year', 'camel female total', 'camel female under year', 'camel male total', 'camel male under year']

### Members

34 members, grouped (group | header | members | years in titles | sample titles):
- G4 | H1 | 31 | 2012x31 | template: Details of camels by age and sex in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of camels by age and sex in rural and urban combined for Andhra Pradesh - 2012 || Details of camels by age and sex in rural and urban combined for Arunachal Pradesh - 2012 || Details of camels by age and sex in rural and urban combined for Assam - 2012
- G5 | H2 | 1 | 2012x1 | template: Details of camels by age and sex in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of camels by age and sex in rural and urban combined for Puducherry - 2012
- G6 | H3 | 1 | 2012x1 | template: Details of camels by age and sex in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of camels by age and sex in rural and urban combined for Uttarakhand - 2012
- G7 | H4 | 1 | 2012x1 | template: Details of camels by age and sex in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of camels by age and sex in rural and urban combined for West Bengal - 2012

### Similar rows outside this collection (same ministry)

- collection [34] Details of yaks by age and sex rural and urban combined (change_in_header; in scope, batch AH); best score 94.33962264150944; e.g. 291521 Details of yaks by age and sex rural and urban combined for Andhra Pradesh - 2012
- collection [32] Details of cattle by age, sex and use in rural and urban combined (curate; free); best score 89.28571428571429; e.g. 291461 Details of cattle by age, sex and use in rural and urban combined for Andhra Pradesh - 2012
- collection [34] Details of goats by age, sex and use in rural and urban combined (change_in_header; in scope, batch AH); best score 88.28828828828829; e.g. 291561 Details of goats by age, sex and use in rural and urban combined for Andhra Pradesh - 2012
- nid 292041 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Camels  Male Under 4 year,Camels  Male 4 Year and Above,Camels  Male Total,Camels  Female Under 4 year,Cam'; file bddcb783-9210-4993-8102-5f4180e4ec11.csv) Details of camels by age and sex in rural and urban combined for Andman and Nicobar Islands - 2012
- nid 304661 (non-mergeable, no collection; free; score 89.28571428571429; window 2012; hdr 'SNo.,District,Exotic / Crossbred Cattle  Male  Upto 1.5 Years,Exotic / Crossbred Cattle  Male  Over 1.5 Years  Used for '; file 60e5ca67-2be8-4a48-8dea-01c6af049a7d.csv) Details of cattle by age, sex and use in rural and urban combined for Uttarakhand - 2012
- nid 305061 (non-mergeable, no collection; free; score 89.28571428571429; window 2012; hdr 'SNo.,District,Exotic / Crossbred Cattle  Male Upto 1.5 Years,Exotic / Crossbred Cattle  Male  Over 1.5 Years  Used for B'; file 2c0597c4-0485-42e2-a591-2debd09e7514.csv) Details of cattle by age, sex and use in rural and urban combined for West Bengal - 2012

---

## C3 · Details of dogs, rabbits and elephants in rural and urban combined

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 34 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match 1.0 | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [33] 10 cols, year-labelled cols 0%: District | Dogs  Male | Dogs  Female | Dogs  Total | Rabbits  Male | Rabbits  Female | Rabbits  Total | Elephants  Male | Elephants  Female | Elephants  Total
- H2 [1] 11 cols, year-labelled cols 0%: S No. | District | Dogs  Male | Dogs  Female | Dogs  Total | Rabbits  Male | Rabbits  Female | Rabbits  Total | Elephants  Male | Elephants  Female | Elephants  Total
    match vs H1 1.00; only here: ['S No.']; only in H1: []

### Members

34 members, grouped (group | header | members | years in titles | sample titles):
- G8 | H1 | 33 | 2012x33 | template: Details of dogs, rabbits and elephants in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of dogs, rabbits and elephants in rural and urban combined for Andhra Pradesh - 2012 || Details of dogs, rabbits and elephants in rural and urban combined for Arunachal Pradesh - 2012 || Details of dogs, rabbits and elephants in rural and urban combined for Assam - 2012
- G9 | H2 | 1 | 2012x1 | template: Details of dogs, rabbits and elephants in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of dogs, rabbits and elephants in rural and urban combined for Uttar Pradesh - 2012

### Similar rows outside this collection (same ministry)

- nid 292061 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Dogs  Male,Dogs  Female,Dogs  Total,Rabbits  Male,Rabbits  Female,Rabbits  Total,Elephants  Male,Elephants'; file f89ec649-cd6a-452f-b4ed-66c6afcfd27a.csv) Details of dogs, rabbits and elephants in rural and urban combined for Andman and Nicobar Islands - 2012

---

## C4 · Details of goats by age, sex and use in rural and urban combined

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 34 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match 1.0 | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [32] 10 cols, year-labelled cols 0%: District | Goats  Male Under 1 Year | Goats  Male 1 Year and Above | Goats  Male Total | Goats  Female Under 1 Year | Goats  Female 1 Year and Above  In Milk | Goats  Female 1 Year and Above  Dry | Goats  Female 1 Year and Above  Not Calved Once | Goats  Female Total | Goats  Total
- H2 [2] 10 cols, year-labelled cols 0%: District | Male  Under 1 Year | Male  1 Year and Above | Male  Total | Female  Under 1 Year | Female  1 Year and Above  In Milk | Female  1 Year and Above  Dry | Female  1 Year and Above  Not Calved Once | Female  Total | Total Goats
    match vs H1 1.00; only here: ['Male  Under 1 Year', 'Male  Total', 'Female  1 Year and Above  Dry', 'Female  Total', 'Female  Under 1 Year', 'Male  1 Year and Above', 'Female  1 Year and Above  In Milk', 'Female  1 Year and Above  Not Calved Once']; only in H1: ['above calved female goat not once year', 'above dry female goat year', 'above female goat milk year', 'above goat male year', 'female goat total', 'female goat under year', 'goat male total', 'goat male under year']

### Members

34 members, grouped (group | header | members | years in titles | sample titles):
- G10 | H1 | 32 | 2012x32 | template: Details of goats by age, sex and use in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of goats by age, sex and use in rural and urban combined for Andhra Pradesh - 2012 || Details of goats by age, sex and use in rural and urban combined for Arunachal Pradesh - 2012 || Details of goats by age, sex and use in rural and urban combined for Assam - 2012
- G11 | H2 | 2 | 2012x2 | template: Details of goats by age, sex and use in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of goats by age, sex and use in rural and urban combined for Uttarakhand - 2012 || Details of goats by age, sex and use in rural and urban combined for West Bengal - 2012

### Similar rows outside this collection (same ministry)

- collection [32] Details of cattle by age, sex and use in rural and urban combined (curate; free); best score 93.91304347826087; e.g. 291461 Details of cattle by age, sex and use in rural and urban combined for Andhra Pradesh - 2012
- collection [34] Details of yaks by age and sex rural and urban combined (change_in_header; in scope, batch AH); best score 89.90825688073394; e.g. 291521 Details of yaks by age and sex rural and urban combined for Andhra Pradesh - 2012
- collection [34] Details of horses & ponies by age, sex and use in rural and urban combined (change_in_header; in scope, batch AH); best score 88.52459016393442; e.g. 291601 Details of horses & ponies by age, sex and use in rural and urban combined for Andhra Pradesh - 2012
- collection [34] Details of camels by age and sex in rural and urban combined (change_in_header; in scope, batch AH); best score 88.28828828828829; e.g. 291641 Details of camels by age and sex in rural and urban combined for Andhra Pradesh - 2012
- nid 304661 (non-mergeable, no collection; free; score 93.91304347826087; window 2012; hdr 'SNo.,District,Exotic / Crossbred Cattle  Male  Upto 1.5 Years,Exotic / Crossbred Cattle  Male  Over 1.5 Years  Used for '; file 60e5ca67-2be8-4a48-8dea-01c6af049a7d.csv) Details of cattle by age, sex and use in rural and urban combined for Uttarakhand - 2012
- nid 305061 (non-mergeable, no collection; free; score 93.91304347826087; window 2012; hdr 'SNo.,District,Exotic / Crossbred Cattle  Male Upto 1.5 Years,Exotic / Crossbred Cattle  Male  Over 1.5 Years  Used for B'; file 2c0597c4-0485-42e2-a591-2debd09e7514.csv) Details of cattle by age, sex and use in rural and urban combined for West Bengal - 2012
- nid 291961 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Goats  Male Under 1 Year,Goats  Male 1 Year and Above,Goats  Male Total,Goats  Female Under 1 Year,Goats  '; file 93db2e49-2735-44eb-b43c-97d2d6cc3cfb.csv) Details of goats by age, sex and use in rural and urban combined for Andman and Nicobar Islands - 2012

---

## C5 · Details of horses & ponies by age, sex and use in rural and urban combined

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 34 | current mac: review
- detector: flags HEADER_IRRECONCILABLE,MAC_REVIEW,MAC_MISSING_DIM | min_header_match 0.22 | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [32] 9 cols, year-labelled cols 0%: District | Horses  Ponies  Male Under 3 Year | Horses  Ponies  Male 3 Year and Above  Used for Cart and Carriage | Horses  Ponies  Male 3 Year and Above  Used for Sport | Horses  Ponies  Male Total | Horses  Ponies  Female Under 3 Year | Horses  Ponies  Female 3 Year and Above | Horses  Ponies  Female Total | Horses  Ponies  Total
- H2 [1] 10 cols, year-labelled cols 0%: S No. | District | Male  Under 3 Year | Male  3 Year and Above  Used for Cart and Carriage | Male  3 Year and Above  Used for Sport | Male  Total | Female  Under 3 Year | Female  3 Year and Above | Female  Total | Total Horses and Ponies
    match vs H1 0.22; only here: ['Male  Under 3 Year', 'Male  3 Year and Above  Used for Sport', 'Male  Total', 'Female  3 Year and Above', 'Female  Total', 'Female  Under 3 Year', 'S No.', 'Male  3 Year and Above  Used for Cart and Carriage']; only in H1: ['above carriage cart horse male ponie used year', 'above female horse ponie year', 'above horse male ponie sport used year', 'female horse ponie total', 'female horse ponie under year', 'horse male ponie total', 'horse male ponie under year']
- H3 [1] 9 cols, year-labelled cols 0%: District | Male  Under 3 Year | Male  3 Year and Above  Used for Cart and Carriage | Male  3 Year and Above  Used for Sport | Male  Total | Female  Under 3 Year | Female  3 Year and Above | Female  Total | Total Horses and Ponies
    match vs H1 0.22; only here: ['Male  Under 3 Year', 'Male  3 Year and Above  Used for Sport', 'Male  Total', 'Female  3 Year and Above', 'Female  Total', 'Female  Under 3 Year', 'Male  3 Year and Above  Used for Cart and Carriage']; only in H1: ['above carriage cart horse male ponie used year', 'above female horse ponie year', 'above horse male ponie sport used year', 'female horse ponie total', 'female horse ponie under year', 'horse male ponie total', 'horse male ponie under year']

### Members

34 members, grouped (group | header | members | years in titles | sample titles):
- G12 | H1 | 32 | 2012x32 | template: Details of horses & ponies by age, sex and use in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of horses & ponies by age, sex and use in rural and urban combined for Andhra Pradesh - 2012 || Details of horses & ponies by age, sex and use in rural and urban combined for Arunachal Pradesh - 2012 || Details of horses & ponies by age, sex and use in rural and urban combined for Assam - 2012
- G13 | H2 | 1 | 2012x1 | template: Details of horses & ponies by age, sex and use in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of horses & ponies by age, sex and use in rural and urban combined for Uttarakhand - 2012
- G14 | H3 | 1 | 2012x1 | template: Details of horses & ponies by age, sex and use in rural and urban combined for <STATE> - <YEAR>
    e.g. Details of horses & ponies by age, sex and use in rural and urban combined for West Bengal - 2012

### Similar rows outside this collection (same ministry)

- collection [34] Details of goats by age, sex and use in rural and urban combined (change_in_header; in scope, batch AH); best score 88.52459016393442; e.g. 291561 Details of goats by age, sex and use in rural and urban combined for Andhra Pradesh - 2012
- collection [32] Details of cattle by age, sex and use in rural and urban combined (curate; free); best score 86.1788617886179; e.g. 291461 Details of cattle by age, sex and use in rural and urban combined for Andhra Pradesh - 2012
- nid 292001 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Horses  Ponies  Male Under 3 Year,Horses  Ponies  Male 3 Year and Above  Used for Cart and Carriage,Horses'; file 801e9ad0-c028-4d05-b796-8fdc321655c5.csv) Details of horses & ponies by age, sex and use in rural and urban combined for Andman and Nicobar Islands - 2012
- nid 304661 (non-mergeable, no collection; free; score 86.1788617886179; window 2012; hdr 'SNo.,District,Exotic / Crossbred Cattle  Male  Upto 1.5 Years,Exotic / Crossbred Cattle  Male  Over 1.5 Years  Used for '; file 60e5ca67-2be8-4a48-8dea-01c6af049a7d.csv) Details of cattle by age, sex and use in rural and urban combined for Uttarakhand - 2012
- nid 305061 (non-mergeable, no collection; free; score 86.1788617886179; window 2012; hdr 'SNo.,District,Exotic / Crossbred Cattle  Male Upto 1.5 Years,Exotic / Crossbred Cattle  Male  Over 1.5 Years  Used for B'; file 2c0597c4-0485-42e2-a591-2debd09e7514.csv) Details of cattle by age, sex and use in rural and urban combined for West Bengal - 2012

---

## C6 · Details of mithun by age and sex in urban and rural combined

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 34 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match 1.0 | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [32] 8 cols, year-labelled cols 0%: District | Mithuns  Male Under 3 Years | Mithuns  Female Under 3 Years | Mithuns  Total Under 3 Years | Mithuns  Male 3 Years and Above | Mithuns  Female 3 Years and Above | Mithuns  Total 3 Years and Above | Mithuns  Total
- H2 [1] 9 cols, year-labelled cols 0%: S No. | District | Under 3 Years  Male | Under 3 Years  Female | Under 3 Years  Total | 3 Years and Above  Male | 3 Years and Above  Female | 3 Years and Above  Total | Total Mithuns
    match vs H1 1.00; only here: ['Under 3 Years  Male', 'Under 3 Years  Total', '3 Years and Above  Female', 'Under 3 Years  Female', '3 Years and Above  Male', 'S No.', '3 Years and Above  Total']; only in H1: ['above female mithun year', 'above male mithun year', 'above mithun total year', 'female mithun under year', 'male mithun under year', 'mithun total under year']
- H3 [1] 8 cols, year-labelled cols 0%: District | Under 3 Years  Male | Under 3 Years  Female | Under 3 Years  Total | 3 Years and Above  Male | 3 Years and Above  Female | 3 Years and Above  Total | Total Mithuns
    match vs H1 1.00; only here: ['Under 3 Years  Male', 'Under 3 Years  Total', '3 Years and Above  Female', 'Under 3 Years  Female', '3 Years and Above  Male', '3 Years and Above  Total']; only in H1: ['above female mithun year', 'above male mithun year', 'above mithun total year', 'female mithun under year', 'male mithun under year', 'mithun total under year']

### Members

34 members, grouped (group | header | members | years in titles | sample titles):
- G15 | H1 | 32 | 2012x32 | template: Details of mithun by age and sex in urban and rural combined for <STATE> - <YEAR>
    e.g. Details of mithun by age and sex in urban and rural combined for Andhra Pradesh - 2012 || Details of mithun by age and sex in urban and rural combined for Arunachal Pradesh - 2012 || Details of mithun by age and sex in urban and rural combined for Assam - 2012
- G16 | H2 | 1 | 2012x1 | template: Details of mithun by age and sex in urban and rural combined for <STATE> - <YEAR>
    e.g. Details of mithun by age and sex in urban and rural combined for Uttarakhand - 2012
- G17 | H3 | 1 | 2012x1 | template: Details of mithun by age and sex in urban and rural combined for <STATE> - <YEAR>
    e.g. Details of mithun by age and sex in urban and rural combined for West Bengal - 2012

### Similar rows outside this collection (same ministry)

- nid 291901 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Mithuns  Male Under 3 Years,Mithuns  Female Under 3 Years,Mithuns  Total Under 3 Years,Mithuns  Male 3 Yea'; file 81e7a905-87e0-4d29-addd-744d59648c4a.csv) Details of mithun by age and sex in urban and rural combined for Andman and Nicobar Islands - 2012

---

## C7 · Details of mules and donkeys by age and sex in rural and urban combined areas

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 34 | current mac: review
- detector: flags HEADER_IRRECONCILABLE,MAC_REVIEW,MAC_MISSING_DIM | min_header_match 0.82 | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [32] 11 cols, year-labelled cols 0%: District | Mules  Under 3 year | Mules  3 Year and Above | Mules  Total | Donkeys  Male Under 3 year | Donkeys  Male 3 Year and Above | Donkeys  Male Total | Donkeys  Female Under 3 year | Donkeys  Female 3 Year and Above | Donkeys  Female Total | Donkeys  Total
- H2 [1] 12 cols, year-labelled cols 0%: S No. | District | Mules  Under 3 year | Mules  3 Year and Above | Mules  Total Mules | Donkeys  Male  Under 3 year | Donkeys  Male  3 Year and Above | Donkeys  Male  Total | Donkeys  Female  Under 3 year | Donkeys  Female  3 Year and Above | Donkeys  Female  Total | Donkeys  Total Donkeys
    match vs H1 0.82; only here: ['S No.', 'Mules  Total Mules', 'Donkeys  Total Donkeys']; only in H1: ['donkey total', 'mule total']
- H3 [1] 11 cols, year-labelled cols 0%: District | Mules  Under 3 year | Mules  3 Year and Above | Mules  Total Mules | Donkeys  Male  Under 3 year | Donkeys  Male  3 Year and Above | Donkeys  Male  Total | Donkeys  Female  Under 3 year | Donkeys  Female  3 Year and Above | Donkeys  Female  Total | Donkeys  Total Donkeys
    match vs H1 0.82; only here: ['Mules  Total Mules', 'Donkeys  Total Donkeys']; only in H1: ['donkey total', 'mule total']

### Members

34 members, grouped (group | header | members | years in titles | sample titles):
- G18 | H1 | 32 | 2012x32 | template: Details of mules and donkeys by age and sex in rural and urban combined areas for <STATE> - <YEAR>
    e.g. Details of mules and donkeys by age and sex in rural and urban combined areas for Andhra Pradesh - 2012 || Details of mules and donkeys by age and sex in rural and urban combined areas for Arunachal Pradesh - 2012 || Details of mules and donkeys by age and sex in rural and urban combined areas for Assam - 2012
- G19 | H2 | 1 | 2012x1 | template: Details of mules and donkeys by age and sex in rural and urban combined areas for <STATE> - <YEAR>
    e.g. Details of mules and donkeys by age and sex in rural and urban combined areas for Uttarakhand - 2012
- G20 | H3 | 1 | 2012x1 | template: Details of mules and donkeys by age and sex in rural and urban combined areas for <STATE> - <YEAR>
    e.g. Details of mules and donkeys by age and sex in rural and urban combined areas for West Bengal - 2012

### Similar rows outside this collection (same ministry)

- nid 292021 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Mules  Under 3 year,Mules  3 Year and Above,Mules  Total,Donkeys  Male Under 3 year,Donkeys  Male 3 Year a'; file d3f62ce9-2cf5-41f6-94a8-ed7e761dc4d4.csv) Details of mules and donkeys by age and sex in rural and urban combined areas for Andman and Nicobar Islands - 2012

---

## C8 · Details of pigs by age and sex in rural and urban combined for exotic crossbred and indigenous

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 34 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [34] 16 cols, year-labelled cols 0%: District | Pigs  Exotic / Crossbred  Male Under 6 Months | Pigs  Exotic / Crossbred  Male 6 Months  Above | Pigs  Exotic / Crossbred  Male Total | Pigs  Exotic / Crossbred  Female Under 6 Months | Pigs  Exotic / Crossbred  Female 6 Months  Above | Pigs  Exotic / Crossbred  Female Total | Pigs  Exotic / Crossbred  Total | Pigs  Indigenous  Male Under 6 Months | Pigs  Indigenous  Male 6 Months  Above | Pigs  Indigenous  Male Total | Pigs  Indigenous  Female Under 6 Months | Pigs  Indigenous  Female 6 Months  Above | Pigs  Indigenous  Female Total | Pigs  Indigenous  Total | Pigs  Total

### Members

34 members, grouped (group | header | members | years in titles | sample titles):
- G21 | H1 | 34 | 2012x34 | template: Details of pigs by age and sex in rural and urban combined for exotic crossbred and indigenous for <STATE> - <YEAR>
    e.g. Details of pigs by age and sex in rural and urban combined for exotic crossbred and indigenous for Andhra Pradesh - 2012 || Details of pigs by age and sex in rural and urban combined for exotic crossbred and indigenous for Arunachal Pradesh - 2012 || Details of pigs by age and sex in rural and urban combined for exotic crossbred and indigenous for Assam - 2012

### Similar rows outside this collection (same ministry)

- collection [34] Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous (change_in_header; in scope, batch AH); best score 95.85798816568047; e.g. 291541 Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous for Andhra Pradesh - 2012
- nid 291981 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Pigs  Exotic / Crossbred  Male Under 6 Months,Pigs  Exotic / Crossbred  Male 6 Months  Above,Pigs  Exotic '; file 570dee71-42ae-45ee-8ba3-b8a863e22402.csv) Details of pigs by age and sex in rural and urban combined for exotic crossbred and indigenous for Andman and Nicobar Islands - 2012

---

## C9 · Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 34 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match 0.94 | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [32] 16 cols, year-labelled cols 0%: District | Sheep  Indigenous  Male Under 1 year | Sheep  Indigenous  Male 1 Year and Above | Sheep  Indigenous  Male Total | Sheep  Indigenous  Female Under 1 year | Sheep  Indigenous  Female 1 Year and Above | Sheep  Indigenous  Female Total | Sheep  Indigenous  Total | Sheep  Total | Sheep  Exotic / Crossbred  Male Under 1 year | Sheep  Exotic / Crossbred  Male 1 Year and Above | Sheep  Exotic / Crossbred  Male Total | Sheep  Exotic / Crossbred  Female Under 1 year | Sheep  Exotic / Crossbred  Female 1 Year and Above | Sheep  Exotic / Crossbred  Female Total | Sheep  Exotic / Crossbred  Total
- H2 [2] 16 cols, year-labelled cols 0%: District | Exotic / Crossbred Sheep  Male  Under 1 year | Exotic / Crossbred Sheep  Male  1 Year and Above | Exotic / Crossbred Sheep  Male  Total | Exotic / Crossbred Sheep  Female  Under 1 year | Exotic / Crossbred Sheep  Female  1 Year and Above | Exotic / Crossbred Sheep  Female  Total | Total Exotic / Crossbred Sheep | Indigenous Sheep  Male  Under 1 year | Indigenous Sheep  Male  1 Year and Above | Indigenous Sheep  Male  Total Indigenous Sheep | Indigenous Sheep  Female  Under 1 year | Indigenous Sheep  Female  1 Year and Above | Indigenous Sheep  Female  Total | Total Indigenous Sheep | Total Sheep
    match vs H1 0.94; only here: ['Indigenous Sheep  Male  Total Indigenous Sheep']; only in H1: ['indigenou male sheep total']

### Members

34 members, grouped (group | header | members | years in titles | sample titles):
- G22 | H1 | 32 | 2012x32 | template: Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous for <STATE> - <YEAR>
    e.g. Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous for Andhra Pradesh - 2012 || Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous for Arunachal Pradesh - 2012 || Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous for Assam - 2012
- G23 | H2 | 2 | 2012x2 | template: Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous for <STATE> - <YEAR>
    e.g. Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous for Uttarakhand - 2012 || Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous for West Bengal - 2012

### Similar rows outside this collection (same ministry)

- collection [34] Details of pigs by age and sex in rural and urban combined for exotic crossbred and indigenous (change_in_header; in scope, batch AH); best score 95.85798816568047; e.g. 291581 Details of pigs by age and sex in rural and urban combined for exotic crossbred and indigenous for Andhra Pradesh - 2012
- nid 291941 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Sheep  Exotic / Crossbred  Male Under 1 year,Sheep  Exotic / Crossbred  Male 1 Year and Above,Sheep  Exoti'; file 8621c656-a431-4111-ad0f-ff56c5789e57.csv) Details of sheep by age and sex in rural and urban combined for exotic crossbred and indigenous for Andman and Nicobar Islands - 2012

---

## C10 · Details of yaks by age and sex rural and urban combined

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 34 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match 1.0 | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [32] 8 cols, year-labelled cols 0%: District | Yaks  Male Under 3 Years | Yaks  Female Under 3 Years | Yaks  Total Under 3 Years | Yaks  Male 3 Years and Above | Yaks  Female 3 Years and Above | Yaks  Total 3 Years and Above | Yaks  Total
- H2 [2] 8 cols, year-labelled cols 0%: District | Under 3 Years  Male | Under 3 Years  Female | Under 3 Years  Total | 3 Years and Above  Male | 3 Years and Above  Female | 3 Years and Above  Total | Total Yaks
    match vs H1 1.00; only here: ['Under 3 Years  Male', 'Under 3 Years  Total', '3 Years and Above  Female', 'Under 3 Years  Female', '3 Years and Above  Male', '3 Years and Above  Total']; only in H1: ['above female yaks year', 'above male yaks year', 'above total yaks year', 'female under yaks year', 'male under yaks year', 'total under yaks year']

### Members

34 members, grouped (group | header | members | years in titles | sample titles):
- G24 | H1 | 32 | 2012x32 | template: Details of yaks by age and sex rural and urban combined for <STATE> - <YEAR>
    e.g. Details of yaks by age and sex rural and urban combined for Andhra Pradesh - 2012 || Details of yaks by age and sex rural and urban combined for Arunachal Pradesh - 2012 || Details of yaks by age and sex rural and urban combined for Assam - 2012
- G25 | H2 | 2 | 2012x2 | template: Details of yaks by age and sex rural and urban combined for <STATE> - <YEAR>
    e.g. Details of yaks by age and sex rural and urban combined for Uttarakhand - 2012 || Details of yaks by age and sex rural and urban combined for West Bengal - 2012

### Similar rows outside this collection (same ministry)

- collection [34] Details of camels by age and sex in rural and urban combined (change_in_header; in scope, batch AH); best score 94.33962264150944; e.g. 291641 Details of camels by age and sex in rural and urban combined for Andhra Pradesh - 2012
- collection [34] Details of goats by age, sex and use in rural and urban combined (change_in_header; in scope, batch AH); best score 89.90825688073394; e.g. 291561 Details of goats by age, sex and use in rural and urban combined for Andhra Pradesh - 2012
- collection [32] Details of cattle by age, sex and use in rural and urban combined (curate; free); best score 87.27272727272728; e.g. 291461 Details of cattle by age, sex and use in rural and urban combined for Andhra Pradesh - 2012
- nid 291921 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Yaks  Male Under 3 Years,Yaks  Female Under 3 Years,Yaks  Total Under 3 Years,Yaks  Male 3 Years and Above'; file c8b253b9-91fa-4e27-a636-c240b560d87a.csv) Details of yaks by age and sex rural and urban combined for Andman and Nicobar Islands - 2012
- nid 304661 (non-mergeable, no collection; free; score 87.27272727272728; window 2012; hdr 'SNo.,District,Exotic / Crossbred Cattle  Male  Upto 1.5 Years,Exotic / Crossbred Cattle  Male  Over 1.5 Years  Used for '; file 60e5ca67-2be8-4a48-8dea-01c6af049a7d.csv) Details of cattle by age, sex and use in rural and urban combined for Uttarakhand - 2012
- nid 305061 (non-mergeable, no collection; free; score 87.27272727272728; window 2012; hdr 'SNo.,District,Exotic / Crossbred Cattle  Male Upto 1.5 Years,Exotic / Crossbred Cattle  Male  Over 1.5 Years  Used for B'; file 2c0597c4-0485-42e2-a591-2debd09e7514.csv) Details of cattle by age, sex and use in rural and urban combined for West Bengal - 2012

---

## C11 · District wise Number of Indigenous Cattle by breed

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 32 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels district | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa | Gujarat
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [32] 51 cols, year-labelled cols 0%: District Name | Indigenous breed  Alambadi | Indigenous breed  Amritmahal | Indigenous breed  Bachaur | Indigenous breed  Bargur | Indigenous breed  Bengali | Indigenous breed  Binjharpuri | Indigenous breed  Dangi | Indigenous breed  Deoni | Indigenous breed  Gangatiri | Indigenous breed  Gaolao | Indigenous breed  Ghumsuri | Indigenous breed  Gir | Indigenous breed  Hallikar | Indigenous breed  Hariana | Indigenous breed  Jellicut | Indigenous breed  Kangayam | Indigenous breed  Kankrej | Indigenous breed  Kenkatha | Indigenous breed  Kherigarh | Indigenous breed  Khilari | Indigenous breed  Krishna valley | Indigenous breed  Kumauni | Indigenous breed  Ladakhi | Indigenous breed  Maland Gidda | Indigenous breed  Malvi | Indigenous breed  Mampati | Indigenous breed  Manapari | Indigenous breed  Mewati | Indigenous breed  Mottu ... (+21 more)

### Members

32 members, grouped (group | header | members | years in titles | sample titles):
- G26 | H1 | 31 | 2007x31 | template: District wise Number of Indigenous Cattle by breed, <YEAR> - <STATE>
    e.g. District wise Number of Indigenous Cattle by breed, 2007 - Andhra Pradesh || District wise Number of Indigenous Cattle by breed, 2007 - Arunachal Pradesh || District wise Number of Indigenous Cattle by breed, 2007 - Assam
- G27 | H1 | 1 | 2007x1 | template: District wise Number of Indigenous Cattle by breed, <YEAR> - Orissa
    e.g. District wise Number of Indigenous Cattle by breed, 2007 - Orissa

### Similar rows outside this collection (same ministry)

- collection [32] District wise Number of Cattle by breed (curate; free); best score 90; e.g. 398501 District wise Number of Cattle by breed, 2007 - Andhra Pradesh
- collection [32] District wise Number of Indigenous Sheep by Breed (curate; free); best score 89.8876404494382; e.g. 401801 District wise Number of Indigenous Sheep by Breed, 2007 - Andhra Pradesh
- collection [32] District wise Number of Indigenous pig by breed (curate; free); best score 89.65517241379311; e.g. 406521 District wise Number of  Indigenous pig by breed, 2007 - Andhra Pradesh
- nid 399221 (non-mergeable, no collection; free; score 90; window 2007; hdr 'District Name,Indigenous breed  Alambadi,Indigenous breed  Amritmahal,Indigenous breed  Bachaur,Indigenous breed  Bargur'; file 03b2fd56-dd99-42f1-95f7-e450e9c5340b.csv) District wise Number of Indigenous Cattle by breed, 2007 - Andaman and Nicobar Island

---

## C12 · Number of stray cattle and dogs

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 32 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match 1.0 | admin levels - | varying dims state | suggested mac state | header dims district
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state | notes=one file per state, District is the only geo column; column-prefix and rural/urban-breakdown differences are reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [18] 3 cols, year-labelled cols 0%: District | Stray Cattle | Stray Dogs
- H2 [14] 7 cols, year-labelled cols 0%: District | Stray Cattle  Rural | Stray Cattle  Urban | Stray Cattle  Total | Stray Dogs  Rural | Stray Dogs  Urban | Stray Dogs  Total
    match vs H1 1.00; only here: ['Stray Dogs  Total', 'Stray Cattle  Rural', 'Stray Dogs  Urban', 'Stray Cattle  Total', 'Stray Dogs  Rural', 'Stray Cattle  Urban']; only in H1: ['cattle stray', 'dogs stray']

### Members

32 members, grouped (group | header | members | years in titles | sample titles):
- G28 | H1 | 18 | 2012x18 | template: Number of stray cattle and dogs for <STATE> - <YEAR>
    e.g. Number of stray cattle and dogs for Chandigarh - 2012 || Number of stray cattle and dogs for Dadra and Nagar Haveli - 2012 || Number of stray cattle and dogs for Daman and Diu - 2012
- G29 | H2 | 14 | 2012x14 | template: Number of stray cattle and dogs for <STATE> - <YEAR>
    e.g. Number of stray cattle and dogs for Andhra Pradesh - 2012 || Number of stray cattle and dogs for Arunachal Pradesh - 2012 || Number of stray cattle and dogs for Assam - 2012

### Similar rows outside this collection (same ministry)

- nid 300181 (non-mergeable, no collection; free; score 100.0; window 2012; hdr 'SNo.,District,Stray Rural,Stray Dogs'; file 67c6fc0c-cb5e-4ddc-8918-a8ed06e39d98.csv) Number of stray cattle and dogs for Meghalaya - 2012
- nid 303381 (non-mergeable, no collection; free; score 100.0; window 2012; hdr 'SNo.,District,Stray Cattle,Strat Dogs'; file e63363f1-5f98-4099-b82a-49c4d8945a94.csv) Number of stray cattle and dogs for Sikkim - 2012
- nid 292181 (non-mergeable, no collection; free; score 90; window 2012; hdr 'SNo.,District,Stray Cattle,Stray Dogs'; file 6f441cb6-1148-4e85-aa0f-50b0f7caf369.csv) Number of stray cattle and dogs for Andman and Nicobar Islands - 2012

---

## C13 · Share of milk production by cows, buffaloes and goats

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 5 | current mac: review
- detector: flags MAC_REVIEW | min_header_match 1.0 | admin levels - | varying dims year | suggested mac year | header dims state
- varying title text: 2008-09 | 2009-10 | 2010-11 | 2011-12 | 2012-13
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=year

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [4] 8 cols, year-labelled cols 0%: S. No. | States/UTs | Cow Milk  CB | Cow Milk  ND | Cow Milk  Total | Buffalo Milk | Goat Milk | Total
- H2 [1] 7 cols, year-labelled cols 0%: States/UTs | Cow Milk  CB | Cow Milk  ND | Cow Milk  Total | Buffalo Milk | Goat Milk | Total
    match vs H1 1.00; only here: []; only in H1: ['number s']

### Members

nid | group | header | window | yr-cols | period (data) | file | title
305461 | G30 | H1 | 2008 | 0% | 2008-04-01..2009-03-31 | 28641fe6-e01f-446e-953c-43b237ae83d0.csv | Share of milk production by cows, buffaloes and goats during 2008-09
305481 | G30 | H1 | 2009 | 0% | 2009-04-01..2010-03-31 | f45b1d34-e2b6-401d-ae91-e580f2ee470a.csv | Share of milk production by cows, buffaloes and goats during 2009-10
305501 | G30 | H1 | 2010 | 0% | 2010-04-01..2011-03-31 | fd867267-e11e-4cc2-9cdb-aa3f7e1c2e99.csv | Share of milk production by cows, buffaloes and goats during 2010-11
305521 | G30 | H1 | 2011 | 0% | 2011-04-01..2012-03-31 | 39cff09e-d0c1-4e38-b423-a68b2f337f40.csv | Share of milk production by cows, buffaloes and goats during 2011-12
305541 | G31 | H2 | 2012 | 0% | 2012-04-01..2013-03-31 | b22812ee-f7aa-4e52-acd7-7d1fd946b265.csv | Share of milk production by cows, buffaloes and goats during 2012-13

---

## C14 · State & UT-wise Milk Production by Cows, Buffaloes & Goats

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 5 | current mac: review
- detector: flags MAC_REVIEW | min_header_match 1.0 | admin levels state | varying dims year | suggested mac year | header dims state
- varying title text: 2009-10 | 2010-11 | 2011-12 | 2012-13 | 2013-14
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=year

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [3] 8 cols, year-labelled cols 0%: S. No. | States/UTs | Cow Milk  Exotic/CB | Cow Milk  IND/ND | Cow Milk  Total | Buffalo Milk | Goat Milk | Total
- H2 [2] 7 cols, year-labelled cols 0%: States/UTs | Cow Milk  Exotic/CB | Cow Milk  IND/ND | Cow Milk  Total | Buffalo Milk | Goat Milk | Total
    match vs H1 1.00; only here: []; only in H1: ['number s']

### Members

nid | group | header | window | yr-cols | period (data) | file | title
836941 | G32 | H1 | 2009 | 0% | 2009-04-01..2010-03-31 | 6e9c6cda-fb25-4fc1-8460-1d2f76e627c2.csv | State & UT-wise Milk Production by Cows, Buffaloes & Goats during 2009-10
836961 | G33 | H2 | 2010 | 0% | 2010-04-01..2011-03-31 | 11ea61fa-1e60-4ecc-a8e0-cd360b06ccf5.csv | State & UT-wise Milk Production by Cows, Buffaloes & Goats during 2010-11
836981 | G32 | H1 | 2011 | 0% | 2011-04-01..2012-03-31 | 53d507ba-1acf-49c9-bcc8-2f68e5b28406.csv | State & UT-wise Milk Production by Cows, Buffaloes & Goats during 2011-12
837001 | G33 | H2 | 2012 | 0% | 2012-04-01..2013-03-31 | 5b285793-42c9-4f36-b130-81fee557e1e5.csv | State & UT-wise Milk Production by Cows, Buffaloes & Goats during 2012-13
837021 | G32 | H1 | 2013 | 0% | 2013-04-01..2014-03-31 | a235478a-d123-4d09-aff8-6d213f1b11d3.csv | State & UT-wise Milk Production by Cows, Buffaloes & Goats during 2013-14

---

## C15 · State/ Union Territory-wise Preserved and Processed Commodities

- ministry: Ministry of Fisheries, Animal Husbandry and Dairying,Department of Animal Husbandry and Dairying | members in scope: 5 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels - | varying dims year | suggested mac year | header dims state
- varying title text: 2008 | 2009 | 2010 | 2011 | 2012
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=year

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [5] 25 cols, year-labelled cols 0%: S.No. | State / Union Territory | Tuna Frozen | Marine Fish Frozen | Fish Dried Unsalted | Fish Dried  Salted or smoked | Shark fins Dried Salted etc. | Crab Meat Frozen | Frozen Whole cooked Lobster | Frozen Lobster tails | Shrimp  Prawn Frozen | Freeze Dried Shrimp | Dried Prawn/ Shrimp | Frozen Cuttlefish fillets | Frozen Squids | Dried Squids | Canned Fish | Canned Shrimp/ Prawn | Fish body oil | Fish meals soluble or similar feedings | Pomfret Frozen | Mackerels frozen | Jellyfish dried salted or in brine | Miscellaneous | Total

### Members

nid | group | header | window | yr-cols | period (data) | file | title
679621 | G34 | H1 | 2008 | 0% | 2008-01-01..2009-12-31 | b192992a-0f23-40fa-a538-441f7f93c917.csv | State/ Union Territory-wise Preserved and Processed Commodities during 2008
679641 | G34 | H1 | 2009 | 0% | 2009-01-01..2010-12-31 | 6fffb74e-c5f0-4d0a-aec3-28de56c91f85.csv | State/ Union Territory-wise Preserved and Processed Commodities during 2009
679661 | G34 | H1 | 2010 | 0% | 2010-01-01..2011-12-31 | 57447786-dabe-41fc-b077-4b41795a7e68.csv | State/ Union Territory-wise Preserved and Processed Commodities during 2010
679681 | G34 | H1 | 2011 | 0% | 2011-01-01..2012-12-31 | 9d4fef4f-c656-484e-a8cf-4e94aec03b1e.csv | State/ Union Territory-wise Preserved and Processed Commodities during 2011
679701 | G34 | H1 | 2012 | 0% | 2012-01-01..2013-12-31 | 2abd7fd0-ec4a-4cb4-8b04-707b58b62d10.csv | State/ Union Territory-wise Preserved and Processed Commodities during 2012
