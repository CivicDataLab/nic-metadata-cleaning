# Evidence pack SM: 23 collections, 300 rows


---

## C1 · Consumer category wise sale of power

- ministry: NITI Aayog | members in scope: 5 | current mac: review
- detector: flags MAC_REVIEW | min_header_match 0.9 | admin levels - | varying dims year | suggested mac year | header dims state
- varying title text: 2009-10 | 2010-11 | 2011-12 | 2012-13 | 2013-14
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=year

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [4] 10 cols, year-labelled cols 0%: Category | State | Domestic | Commercial | Agri/ irrig. | Industry | Railway traction | Outside the State/UT | Others | Total
- H2 [1] 10 cols, year-labelled cols 0%: Category | State | Domestic | Commercial | Agri/ Irrigigation | Industry | Railway traction | Outside the State/UT | Others | Total
    match vs H1 0.90; only here: ['Agri/ Irrigigation']; only in H1: ['agri irrig']

### Members

nid | group | header | window | yr-cols | period (data) | file | title
100564 | G829 | H2 | 2009 | 0% | 2009-04-01..2010-03-31 | c8464d5c-6bc5-4e90-af60-dade5efa2909.csv | Consumer category wise sale of power, 2009-10
100565 | G828 | H1 | 2010 | 0% | 2010-04-01..2011-03-31 | d24dd711-7447-4e8f-addc-20fa1862c71c.csv | Consumer category wise sale of power, 2010-11
100566 | G828 | H1 | 2011 | 0% | 2011-04-01..2012-03-31 | 25e43ed7-f0e7-44c0-a1f6-3043d1aaadbc.csv | Consumer category wise sale of power, 2011-12
100567 | G828 | H1 | 2012 | 0% | 2012-04-01..2013-03-31 | 1f052f88-82c1-4ea8-a82a-035612b86b28.csv | Consumer category wise sale of power, 2012-13
100568 | G828 | H1 | 2013 | 0% | 2013-04-01..2014-03-31 | 608160e6-7245-47e2-b8c7-bcc57253c5e0.csv | Consumer category wise sale of power, 2013-14

### Similar rows outside this collection (same ministry)

- nid 100563 (non-mergeable, no collection; free; score 90; window 2009-2013; hdr 'Category,State,200910 Actual,201011 Actual,201112 Prov.,201213 RE,201314 AP'; file c0981f42-f8a7-402a-bcf4-ad6b60aa4b3b.csv) Sale of power from 2009-10 to 2013-14

---

## C2 · Financial Performance of Goa during Tenth Plan

- ministry: NITI Aayog | members in scope: 10 | current mac: review
- detector: flags NAME_PINS_VALUE,MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels - | varying dims state | suggested mac state | header dims -
- varying title text: Goa | Gujarat | Haryana | Jharkhand | Karnataka | Kerala | Maharashtra | Meghalaya | Mizoram | Nagaland
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=State-wise Financial Performance during Tenth Plan | mac=state

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [10] 6 cols, year-labelled cols 89%: Category of Major Heads of Development | Major Heads of Development | Tenth Plan  200207   Projected Outlay | Annual Plan 200203  Approved Outlay | Annual Plan 200203  Revised Outlay | Annual Plan 200203  Actual Expenditure

### Members

nid | group | header | window | yr-cols | period (data) | file | title
103991 | G830 | H1 | - | 89% | 2002-04-01..2007-03-31 | f85e8f36-8680-408c-9a92-a6cde7e6d453.csv | Financial Performance of Goa during Tenth Plan
103992 | G830 | H1 | - | 89% | 2002-04-01..2007-03-31 | d4c74e96-fafd-48b1-8287-1890f34b00ad.csv | Financial Performance of Gujarat during Tenth Plan
103993 | G830 | H1 | - | 89% | 2002-04-01..2007-03-31 | ba767a9f-22e0-41b2-91a8-e75d2b0bbdd9.csv | Financial Performance of Haryana during Tenth Plan
104043 | G830 | H1 | - | 89% | 2002-04-01..2007-03-31 | c83578ca-70fb-4665-9631-332ab98ee41a.csv | Financial Performance of Jharkhand during Tenth Plan
104044 | G830 | H1 | - | 89% | 2002-04-01..2007-03-31 | f14166b9-95e7-44d1-8377-fa2f9a1d7c5c.csv | Financial Performance of Karnataka during Tenth Plan
104045 | G830 | H1 | - | 89% | 2002-04-01..2007-03-31 | b007c6bd-5273-41eb-9e6f-2c51016f0f09.csv | Financial Performance of Kerala during Tenth Plan
104048 | G830 | H1 | - | 89% | 2002-04-01..2007-03-31 | e9151191-b313-46e4-b2ee-c1016ea39350.csv | Financial Performance of Maharashtra during Tenth Plan
104049 | G830 | H1 | - | 89% | 2002-04-01..2007-03-31 | 40ce1364-1e60-43fe-98b0-ee3a959ddd1d.csv | Financial Performance of Meghalaya during Tenth Plan
104050 | G830 | H1 | - | 89% | 2002-04-01..2007-03-31 | 759d62bc-c60b-4966-9f32-5637e8137237.csv | Financial Performance of Mizoram during Tenth Plan
104051 | G830 | H1 | - | 89% | 2002-04-01..2007-03-31 | ec745360-4b32-4f17-a04a-0fb5572db8a2.csv | Financial Performance of Nagaland during Tenth Plan

### Similar rows outside this collection (same ministry)

- nid 103981 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan  200207   Projected Outlay,Annual Plan 2002'; file ddb5a3c2-f7ed-4783-be50-b805fae672e5.csv) Financial Performance of Andhra Pradesh during Tenth Plan
- nid 103983 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan  200207   Projected Outlay,Annual Plan 2002'; file 7607ea71-864a-4c29-9496-a2f5b692bd97.csv) Financial Performance of Arunachal Pradesh during Tenth Plan
- nid 103984 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan  200207   Projected Outlay,Annual Plan 2002'; file 4e70be7f-c67d-484a-87a4-be17b340d374.csv) Financial Performance of Assam during Tenth Plan
- nid 103985 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan  200207   Projected Outlay,Annual Plan 2002'; file 66a8faf8-363c-4f6d-a472-290d5dd5f47f.csv) Financial Performance of Bihar during Tenth Plan
- nid 103986 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan  200207   Projected Outlay,Annual Plan 2002'; file edcbf449-ad4d-4414-9876-4a0ddab8c13b.csv) Financial Performance of Chandigarh during Tenth Plan
- nid 103987 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan  200207   Projected Outlay,Annual Plan 2002'; file c5eeb471-165d-4832-9ef5-67495075a156.csv) Financial Performance of Chhattisgarh during Tenth Plan
- nid 103988 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan  200207   Projected Outlay,Annual Plan 2002'; file 2e62b6c6-8be9-4087-9598-74dc88cf6357.csv) Financial Performance of Daman and Diu during Tenth Plan
- nid 103989 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan  200207   Projected Outlay,Annual Plan 2002'; file d3bd4724-33b0-4ff2-8ad8-6472866ae6fe.csv) Financial Performance of Delhi during Tenth Plan
- nid 104042 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file b5437f20-b0d5-4aad-8db2-4457feb51e21.csv) Financial Performance of Himachal Pradesh during Tenth Plan
- nid 104046 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file 06696b93-05e3-414f-bd21-8532ec74dd1f.csv) Financial Performance of Lakshadweep during Tenth Plan
- nid 104047 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file 93ce51d5-cfab-42a3-8858-a9142881eb98.csv) Financial Performance of Madhya Pradesh during Tenth Plan
- nid 104054 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file 1337fb94-a0e2-448a-9a13-d8f73d6fde3b.csv) Financial Performance of Puducherry during Tenth Plan
- nid 104056 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file 038f937c-c432-4ac9-a2e4-0beb2d150e90.csv) Financial Performance of Punjab during Tenth Plan
- nid 104057 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file 91497919-19db-43d0-bfe9-0651f133e90b.csv) Financial Performance of Rajasthan during Tenth Plan
- nid 104058 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file 4b5f8351-a47f-416d-aacf-e09674e969bb.csv) Financial Performance of Sikkim during Tenth Plan
- nid 104059 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file 93cc4138-5984-435e-b7e1-4999f5903d31.csv) Financial Performance of Tamil Nadu during Tenth Plan
- nid 104060 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file e61ed6c2-2f14-4192-a512-b03635fc5093.csv) Financial Performance of Tripura during Tenth Plan
- nid 104062 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file d0d3c241-548d-402c-b9ce-a259ca07422a.csv) Financial Performance of Uttar Pradesh during Tenth Plan
- nid 104064 (non-mergeable, no collection; free; score 100.0; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file 4b982a61-458c-4233-ba62-3c628d438808.csv) Financial Performance of West Bengal during Tenth Plan
- nid 104053 (non-mergeable, no collection; free; score 90.14084507042254; window -; hdr 'Category of Major Heads of Development,Major Heads of Development,Tenth Plan 200207  Projected Outlay,Annual Plan 200203'; file c7d548d8-3803-4715-9648-6c5606172d92.csv) Financial Performance of Orissa during Tenth Plan
- ... 1 more loose rows (grep table_index.tsv)

---

## C3 · Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto First Quarter (schema 1)

- ministry: Ministry of Finance, Department of Financial Services | members in scope: 5 | current mac: review
- detector: flags SCHEMA_N_SUFFIX,MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels - | varying dims year,quarter | suggested mac year,quarter | header dims -
- varying title text: First Quarter -2015-16 | First Quarter -2016-17 | First Quarter-2014-15 | Second Quarter -2015-16 | Second Quarter -2016-17
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=Financial Performance of The Oriental Insurance Company Ltd.(OICL) by Quarter | mac=year,quarter

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [5] 8 cols, year-labelled cols 92%: ParametersAmt in Rs Crs | GROSS PREMIUM  First Quarter 201516 | GROSS REMIUM  First Quarter 201415 | NET PREMIUM  First Quarter 201516 | Net Retention %  First Quarter 201516 | NET PREMIUM EARNED  First Quarter 201516 | INCURRED CLAIMS NET  First Quarter 201516 | INCURRED CLAIMS RATIO Net earned basis  First Quarter 201516 Values in %

### Members

nid | group | header | window | yr-cols | period (data) | file | title
358901 | G831 | H1 | 2015 | 92% | 2015-04-01..2016-03-31 | 225e2662-4d57-4d8e-86f7-35151c718cd3.csv | Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto First Quarter -2015-16
2860881 | G831 | H1 | 2016 | 92% | 2016-04-01..2017-03-31 | 6349c72e-fa12-4453-9a5f-2da2de9b5321.csv | Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto First Quarter -2016-17
324781 | G833 | H1 | 2014 | 92% | 2014-04-01..2015-03-31 | d49189a2-2491-4cab-8fb0-7cc6c2de8ef4.csv | Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto First Quarter-2014-15
512401 | G832 | H1 | 2015 | 92% | 2015-04-01..2016-03-31 | 0525662e-e943-4ab6-b82d-ece54f120edf.csv | Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Second Quarter -2015-16
2860981 | G832 | H1 | 2016 | 92% | 2016-04-01..2017-03-31 | 571a01e8-5ba0-43b0-8d12-04f23d21082f.csv | Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Second Quarter -2016-17

### Similar rows outside this collection (same ministry)

- nid 324841 (non-mergeable, no collection; free; score 100.0; window 2013; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  Second Quarter 201314,GROSS REMIUM  Second Quarter 201213,NET PREMIUM  Second Q'; file 1d5b5b20-03a7-4343-a49c-da96ee593061.csv) Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Second Quarter-2013-14
- nid 324861 (non-mergeable, no collection; free; score 100.0; window 2014; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  Second Quarter 201415,GROSS REMIUM  Second Quarter 201314,NET PREMIUM  Second Q'; file 38dd2fc8-0164-4556-98ef-9d3f8c540871.csv) Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Second Quarter-2014-15
- nid 324761 (non-mergeable, no collection; free; score 100.0; window 2013; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  First Quarter 201314,GROSS PREMIUM  First Quarter 201213,NET PREMIUM  First Qua'; file 6d9fff13-6739-45cc-9d1d-7f62870e089d.csv) Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto First Quarter-2013-14
- nid 324801 (non-mergeable, no collection; free; score 96.5034965034965; window 2012; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  Current Year 201213,GROSS PREMIUM  Previous Year 201112,NET PREMIUM  Current Ye'; file d7fc2acf-290f-495d-988f-4f507ae0b3d7.csv) Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Fourth Quarter-2012-13
- nid 324821 (non-mergeable, no collection; free; score 96.5034965034965; window 2013; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  Fourth Quarter 201314,GROSS REMIUM  Fourth Quarter 201213,NET PREMIUM  Fourth Q'; file 50046c16-e72d-4690-abbd-d669274fa61f.csv) Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Fourth Quarter-2013-14
- nid 351201 (non-mergeable, no collection; free; score 96.5034965034965; window 2014; hdr 'ParametersAmt in Rs Crs,GROSS PREMIUM  Fourth Quarter 201415 ,GROSS REMIUM  Fourth Quarter 201314 ,NET PREMIUM  Fourth Q'; file c5726efd-dc1a-4570-9a06-c18404fdc7ef.csv) Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Fourth Quarter-2014-15
- nid 1066861 (non-mergeable, no collection; free; score 96.5034965034965; window 2015; hdr 'ParametersAmt in Rs Crs,GROSS PREMIUM  Fourth Quarter 201516 ,GROSS REMIUM  Fourth Quarter 201415 ,NET PREMIUM  Fourth Q'; file d8388548-5bff-4a93-987e-b7de126e38f2.csv) Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Fourth Quarter -2015-16
- nid 324881 (non-mergeable, no collection; free; score 95.77464788732395; window 2013; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  Third Quarter 201314,GROSS REMIUM  Third Quarter 201213,NET PREMIUM  Third Quar'; file 04cf2550-a07b-40a1-9d5e-d08709daee53.csv) Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Third Quarter-2013-14
- nid 324901 (non-mergeable, no collection; free; score 95.77464788732395; window 2014; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  Third Quarter 201415,GROSS REMIUM  Third Quarter 201314,NET PREMIUM  Third Quar'; file 90387651-d523-4015-b96b-92cdb80138cc.csv) Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Third Quarter-2014-15
- nid 686621 (non-mergeable, no collection; free; score 95.77464788732395; window 2015; hdr 'ParametersAmt in Rs Crs,GROSS PREMIUM  Third Quarter 201516 ,GROSS REMIUM  Third Quarter 201415 ,NET PREMIUM  Third Quar'; file 19f12165-7bc5-43e6-8d13-88dad58ed829.csv) Financial Performance of The Oriental Insurance Company Ltd.(OICL) upto Third Quarter -2015-16
- nid 324681 (non-mergeable, no collection; free; score 93.05555555555556; window 2013; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  Second Quarter 201314,GROSS PREMIUM  Second Quarter 201213,NET PREMIUM  Second '; file cb2c8837-69aa-4ef0-8d8a-5923c6ef0bf5.csv) Financial Performance of National Insurance Company Ltd (NICL) upto Second Quarter-2013-14
- nid 324701 (non-mergeable, no collection; free; score 93.05555555555556; window 2014; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  Second Quarter 201415,GROSS PREMIUM  Second Quarter 201314,NET PREMIUM  Second '; file a8e8b19d-1c15-44d9-89da-10754337e2c7.csv) Financial Performance of National Insurance Company Ltd (NICL) upto Second Quarter-2014-15
- nid 512381 (non-mergeable, no collection; free; score 93.05555555555556; window 2015; hdr 'ParametersAmt in Rs Crs,GROSS PREMIUM  Second Quarter 201415 ,GROSS PREMIUM  Second Quarter 201314 ,NET PREMIUM  Second '; file 925c34c7-da3d-4ab7-8753-a1b866bba1b3.csv) Financial Performance of National Insurance Company Ltd.(NICL) upto Second Quarter-2015-16
- nid 2861021 (non-mergeable, no collection; free; score 93.05555555555556; window 2016; hdr 'ParametersAmt in Rs Crs,GROSS PREMIUM  Second Quarter 201617 ,GROSS PREMIUM  Second Quarter 201516 ,NET PREMIUM  Second '; file d18002ca-3fa3-4a01-84ed-fb4691487f49.csv) Financial Performance of National Insurance Company Ltd.(NICL) upto Second Quarter-2016-17
- nid 324601 (non-mergeable, no collection; free; score 92.95774647887323; window 2013; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  First Quarter 201314,GROSS PREMIUM  First Quarter 201213,NET PREMIUM  First Qua'; file 7cf3dbdb-3019-4365-9d60-a9880cb4e0cc.csv) Financial Performance of National Insurance Company Ltd (NICL) upto First Quarter-2013-14
- nid 324621 (non-mergeable, no collection; free; score 92.95774647887323; window 2014; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  First Quarter 201415,GROSS PREMIUM  First Quarter 201314,NET PREMIUM  First Qua'; file f75c43fa-31eb-4d4f-b0b2-3cf0831173ea.csv) Financial Performance of National Insurance Company Ltd (NICL) upto First Quarter-2014-15
- nid 358941 (non-mergeable, no collection; free; score 92.95774647887323; window 2015; hdr 'ParametersAmt in Rs Crs,GROSS PREMIUM  Fourth Quarter 201415 ,GROSS PREMIUM  Fourth Quarter 201314 ,NET PREMIUM  Fourth '; file c9e35ac7-bfc7-4f7d-bd65-dddd22b2c995.csv) Financial Performance of National Insurance Company Ltd.(NICL) upto First Quarter-2015-16
- nid 2860861 (non-mergeable, no collection; free; score 92.95774647887323; window 2016; hdr 'ParametersAmt in Rs Crs,GROSS PREMIUM  First Quarter 201617 ,GROSS PREMIUM  First Quarter 201516 ,NET PREMIUM  First Qua'; file c80dcd2f-57b4-402f-905c-0863bb885647.csv) Financial Performance of National Insurance Company Ltd.(NICL) upto First Quarter-2016-17
- nid 325001 (non-mergeable, no collection; free; score 90.9090909090909; window 2013; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  Second Quarter 201314,GROSS PREMIUM  Second Quarter 201213,NET PREMIUM  Second '; file f3cc920e-6cd7-4916-aa69-e3ce23418f40.csv) Financial Performance of UNITED INDIA INSURANCE COMPANY LTD.(UIICL) upto Second Quarter-2013-14
- nid 325021 (non-mergeable, no collection; free; score 90.9090909090909; window 2014; hdr 'Parameters Amt. in Rs Crs,GROSS PREMIUM  Second Quarter 201415,GROSS PREMIUM  Second Quarter 201314,NET PREMIUM  Second '; file 01cbdaa4-994f-4511-9fab-65efc92c4f84.csv) Financial Performance of UNITED INDIA INSURANCE COMPANY LTD.(UIICL) upto Second Quarter-2014-15
- ... 24 more loose rows (grep table_index.tsv)

---

## C4 · Forest and Tree Cover

- ministry: NITI Aayog | members in scope: 30 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels - | varying dims state | suggested mac state | header dims -
- varying title text: Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Delhi | Goa | Gujarat | Haryana | Himachal Pradesh
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [30] 2 cols, year-labelled cols 0%: Particulars | Specifications

### Members

30 members, grouped (group | header | members | years in titles | sample titles):
- G834 | H1 | 30 | 2013x30 | template: Forest and tree cover - <STATE> - <YEAR>
    e.g. Forest and tree cover - Arunachal Pradesh - 2013 || Forest and tree cover - Assam - 2013 || Forest and tree cover - Bihar - 2013

### Similar rows outside this collection (same ministry)

- collection [33] Forest and Tree Cover 2011 (change_in_header; free); best score 100.0; e.g. 87987 Forest and tree cover - Andhra Pradesh
- nid 88020 (non-mergeable, no collection; free; score 100.0; window -; hdr '2009 Assessment,2011 Assessment  VDF,2011 Assessment  MDF,2011 Assessment  OF,2011 Assessment  Scrub,2011 Assessment  NF'; file 515ab898-8dc7-4dc6-887e-3ae5a3e35772.xls) Forest and tree cover - West Bengal
- nid 88021 (non-mergeable, no collection; free; score 100.0; window 2007; hdr 'Class,Area million ha,% of Geographical Area G. A.'; file fda73aef-d732-429b-9c1e-f00fdb9242e6.csv) Forest and Tree Cover of India in 2007
- nid 88022 (non-mergeable, no collection; free; score 100.0; window 2011; hdr 'Class,Area km square,Percentage of Geographical Area'; file 4442f656-4b16-482c-90dc-8bbca4f5f140.xls) Forest and tree cover of India in 2011
- nid 87985 (change_in_header, no collection; free; score 90; window -; hdr 'Category,Area,% of Geographical Area'; file 59b43698-e378-4a20-b7a2-f99a812260f1.xls) Forest and tree cover - Andaman and Nicobar
- nid 88025 (non-mergeable, no collection; free; score 90; window -; hdr 'Class Name,Area sq. Km. '; file bf2cca48-3604-4731-be44-ddcb8d13e658.xls) Forest Cover Andaman and Nicobar Islands
- nid 88090 (non-mergeable, no collection; free; score 90; window -; hdr 'Forest Cover,Area sq. Km,Percent Of Geographical Area'; file 8fc73981-1438-4fab-8449-a9570d02462b.xls) Forest Cover of India
- nid 123031 (non-mergeable, no collection; free; score 90; window 2013; hdr 'Class,Area sq. km.,Per cent of Geographical Area'; file 03e16d11-81e4-43ec-8c89-79b14982eced.csv) Forest Cover of India - 2013
- nid 91717 (non-mergeable, no collection; free; score 90; window -; hdr 'State/UTs,Category,Tree Cover,Forest Cover,Forest  Tree Cover'; file 5b5f3fbe-366b-4f85-ad14-643709f7ec78.csv) States/UTs-wise Forest and Tree Cover
- nid 122825 (non-mergeable, no collection; free; score 90; window 2013; hdr 'Particulars,Specifications,'; file 99c120c8-401b-4207-9f44-1d297072b9fe.csv) Forest and tree cover - Andra pradesh - 2013
- nid 122857 (non-mergeable, no collection; free; score 90; window 2013; hdr 'Particulars,Specifications,,,'; file 0d743c70-5094-41db-82e8-f7ad479f8057.csv) Forest and tree cover - Andaman Nicobar Island - 2013
- nid 122859 (non-mergeable, no collection; free; score 90; window 2013; hdr 'Particulars,Specifications,,'; file 2af53ca1-d9a4-4c93-b4f3-8a02f236c3f4.csv) Forest and tree cover - Dadra Nagar Haveli - 2013
- nid 122860 (non-mergeable, no collection; free; score 90; window 2013; hdr 'Particulars,Specifications,,,'; file a5ae96c5-f121-447b-b5a9-456386562f37.csv) Forest and tree cover - Daman Diu - 2013
- nid 122862 (non-mergeable, no collection; free; score 90; window 2013; hdr 'Particulars,Specifications,,'; file 70f23bf0-0a1c-4c90-9df4-d86d72b3fbe8.csv) Forest and tree cover - Puducheiry - 2013

---

## C5 · Forest cover change matrix

- ministry: NITI Aayog | members in scope: 62 | current mac: review
- detector: flags HEADER_IRRECONCILABLE,MAC_REVIEW,MAC_MISSING_DIM | min_header_match 0.33 | admin levels - | varying dims year,state | suggested mac year | header dims state
- varying title text: - Andhra Pradesh | - Arunachal Pradesh | - Arunachal Pradesh - 2013 | - Assam | - Assam - 2013 | - Bihar | - Bihar - 2013 | - Chhattisgarh | - Chhattisgarh - 2013 | - Daman and Diu
- prior proposal (Claude, NOT approved by the user; the rules override it): action=split | name=(unchanged) | mac=- | split_rule=for India|assessment years => !non-mergeable ;; * => Forest cover change matrix | year,state | notes=3 India-level files have different shapes; state files differ only by assessment year in column names

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [59] 6 cols, year-labelled cols 100%: 2009 Assessment | 2011 Assessment VDF | 2011 Assessment MDF | 2011 Assessment Scrub | 2011 Assessment NF | Total 2009
- H2 [1] 7 cols, year-labelled cols 14%: Class | Very Dense Forest | Moderately Dense Forest | Open Forest | Scrub | Non Forest | Total  2005
    match vs H1 0.33; only here: ['Class', 'Moderately Dense Forest', 'Very Dense Forest', 'Non Forest', 'Open Forest', 'Scrub']; only in H1: ['assessment', 'assessment mdf', 'assessment nf', 'assessment scrub', 'assessment vdf']
- H3 [1] 6 cols, year-labelled cols 14%: Class | VDF | MDF | Scrub | NF | Total ISFR 2009
    match vs H1 0.83; only here: ['Class', 'MDF', 'NF', 'Scrub', 'Total ISFR 2009', 'VDF']; only in H1: ['assessment', 'assessment mdf', 'assessment nf', 'assessment scrub', 'assessment vdf', 'total']
- H4 [1] 9 cols, year-labelled cols 80%: States/UTs | Class | Very Dense Forest  2007 | Moderately Dense Forest  2007 | Open Forest  2007 | Scrub  2007 | Non Forest  2007 | Total  2007 | Period of Assessment for 2005
    match vs H1 0.50; only here: ['States/UTs', 'Class', 'Moderately Dense Forest  2007', 'Period of Assessment for 2005', 'Very Dense Forest  2007', 'Non Forest  2007', 'Open Forest  2007', 'Scrub  2007']; only in H1: ['assessment', 'assessment mdf', 'assessment nf', 'assessment scrub', 'assessment vdf']

### Members

62 members, grouped (group | header | members | years in titles | sample titles):
- G835 | H1 | 31 | -x31 | template: Forest cover change matrix - <STATE>
    e.g. Forest cover change matrix -  Chhattisgarh || Forest cover change matrix - Andhra Pradesh || Forest cover change matrix - Arunachal Pradesh
- G836 | H1 | 27 | 2013x27 | template: Forest cover change matrix - <STATE> - <YEAR>
    e.g. Forest cover change matrix - Arunachal Pradesh - 2013 || Forest cover change matrix - Assam - 2013 || Forest cover change matrix - Bihar - 2013
- G837 | H1 | 1 | -x1 | template: Forest cover change matrix - Orissa
    e.g. Forest cover change matrix - Orissa
- G838 | H2 | 1 | 2005-2007x1 | template: Forest Cover Change Matrix for <STATE> Between <YEAR> and <YEAR>
    e.g. Forest Cover Change Matrix for India Between 2005 and 2007
- G839 | H3 | 1 | 2009-2011x1 | template: Forest Cover Change Matrix for <STATE> between <YEAR> and <YEAR>
    e.g. Forest Cover Change Matrix for India between 2009 and 2011
- G840 | H4 | 1 | 2007x1 | template: Forest Cover Change Matrix for the assessment years <YEAR> and <YEAR>
    e.g. Forest Cover Change Matrix for the assessment years 2005 and 2007

### Similar rows outside this collection (same ministry)

- nid 88025 (non-mergeable, no collection; free; score 90; window -; hdr 'Class Name,Area sq. Km. '; file bf2cca48-3604-4731-be44-ddcb8d13e658.xls) Forest Cover Andaman and Nicobar Islands
- nid 88090 (non-mergeable, no collection; free; score 90; window -; hdr 'Forest Cover,Area sq. Km,Percent Of Geographical Area'; file 8fc73981-1438-4fab-8449-a9570d02462b.xls) Forest Cover of India
- nid 123031 (non-mergeable, no collection; free; score 90; window 2013; hdr 'Class,Area sq. km.,Per cent of Geographical Area'; file 03e16d11-81e4-43ec-8c89-79b14982eced.csv) Forest Cover of India - 2013
- nid 88029 (non-mergeable, no collection; free; score 90; window -; hdr '2009 Assessment,2011 Assessment  VDF,2011 Assessment  MDF,2011 Assessment  OF,2011 Assessment  Scrub,2011 Assessment  NF'; file a5ad8c02-a22a-4c57-a357-faf73b753458.xls) Forest cover change matrix - Andaman and Nicobar
- nid 122589 (non-mergeable, no collection; free; score 90; window 2013; hdr '2011 Assessment,2013 Assessment  VDF,2013 Assessment  MDF,2013 Assessment  OF,2013 Assessment  Scrub,2013 Assessment  NF'; file a095a0b1-da00-4fe7-a7df-bd89cad1bc19.csv) Forest cover change matrix - Andra pradesh - 2013
- nid 122621 (non-mergeable, no collection; free; score 90; window 2013; hdr '2011 Assessment,2013 Assessment  VDF,2013 Assessment  MDF,2013 Assessment  OF,2013 Assessment  Scrub,2013 Assessment  NF'; file 8c03c9d5-54f7-4e4a-9190-88e9edc9864e.csv) Forest cover change matrix - Dadra Nagar Haveli - 2013
- nid 122630 (non-mergeable, no collection; free; score 90; window 2013; hdr '2011 Assessment,2013 Assessment  VDF,2013 Assessment  MDF,2013 Assessment  OF,2013 Assessment  Scrub,2013 Assessment  NF'; file 3b5d0a01-71bd-492d-a1d6-c16d91a56b2f.csv) Forest cover change matrix - Andaman Nicobar Island - 2013
- nid 122631 (non-mergeable, no collection; free; score 90; window 2013; hdr '2011 Assessment,2013 Assessment  VDF,2013 Assessment  MDF,2013 Assessment  OF,2013 Assessment  Scrub,2013 Assessment  NF'; file 7027d2b4-31ed-49ea-9bf8-6f1c4d7191a3.csv) Forest cover change matrix - Daman Diu - 2013
- nid 122633 (non-mergeable, no collection; free; score 90; window 2013; hdr '2011 Assessment,2013 Assessment  VDF,2013 Assessment  MDF,2013 Assessment  OF,2013 Assessment  Scrub,2013 Assessment  NF'; file 283fbb97-af40-46ab-9e97-ee4d7585c109.csv) Forest cover change matrix - Puducheiry - 2013

---

## C6 · Gross power generation (mkwh)

- ministry: NITI Aayog | members in scope: 7 | current mac: review
- detector: flags HEADER_IRRECONCILABLE,MAC_REVIEW | min_header_match 0.67 | admin levels - | varying dims year | suggested mac year | header dims state
- varying title text: (mkwh) from 2006-07 to 2011-12 | (mkwh), 2006-07 | (mkwh), 2007-08 | (mkwh), 2008-09 | (mkwh), 2009-10 | (mkwh), 2010-11 | (mkwh), 2011-12
- prior proposal (Claude, NOT approved by the user; the rules override it): action=split | name=(unchanged) | mac=- | split_rule=from 2006-07 to => !non-mergeable ;; * => Gross power generation (mkwh) | year | notes=the span file is a long-format table (Total/Sector), the rest are yearly wide tables

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [6] 12 cols, year-labelled cols 0%: Category | States/U.T. | Hydro  SEB/COR. | Hydro  PVT. | Hydro  Total | Thermal  SEB/COR. | Thermal  PVT. | Thermal  Total | Renewables  SEB/COR. | Renewables  PVT. | Renewables  Total | Total
- H2 [1] 3 cols, year-labelled cols 67%: Category | States/UTs | Total/Sector
    match vs H1 0.67; only here: ['Total/Sector', 'States/UTs']; only in H1: ['cor hydro seb', 'cor renewable seb', 'cor seb thermal', 'hydro pvt', 'hydro total', 'pvt renewable', 'pvt thermal', 'renewable total', 'state t u', 'thermal total']

### Members

nid | group | header | window | yr-cols | period (data) | file | title
100544 | G842 | H2 | 2006-2011 | 67% | 2006-04-01..2012-03-31 | 7ee6633b-ebbe-47fb-9efe-0c700a1331e9.csv | Gross power generation (mkwh) from 2006-07 to 2011-12
100545 | G841 | H1 | 2006 | 0% | 2006-04-01..2007-03-31 | 9ffa5348-e263-4ca6-ab6c-ec8c96162120.csv | Gross power generation (mkwh), 2006-07
100546 | G841 | H1 | 2007 | 0% | 2007-04-01..2008-03-31 | fea4c747-5b41-4738-8d89-9ad566f750e7.csv | Gross power generation (mkwh), 2007-08
100547 | G841 | H1 | 2008 | 0% | 2008-04-01..2009-03-31 | fdcbb2cc-e00b-466f-87d3-ca4d2dd09e9b.csv | Gross power generation (mkwh), 2008-09
100548 | G841 | H1 | 2009 | 0% | 2009-04-01..2010-03-31 | 9b8c0bc3-f205-4178-b576-d030604f5ca5.csv | Gross power generation (mkwh), 2009-10
100549 | G841 | H1 | 2010 | 0% | 2010-04-01..2011-03-31 | 770ae771-2386-4b5b-a97d-4035472c56cf.csv | Gross power generation (mkwh), 2010-11
100550 | G841 | H1 | 2011 | 0% | 2011-04-01..2012-03-31 | c0883be6-f2d4-4ca7-b6eb-0e35950f6642.csv | Gross power generation (mkwh), 2011-12

---

## C7 · Growth in Subscribers

- ministry: NITI Aayog | members in scope: 5 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels - | varying dims year | suggested mac year | header dims -
- varying title text: 2009 | 2010 | 2011 | 2012 | 2013
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=year

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [5] 7 cols, year-labelled cols 57%: Service Provider | Subscriber Base Million  in March 2009 | Subscriber Base Million  in June 2009 | Subscriber Base Million  Net Additions | Rate of growth | Market share  March 2009 | Market share  June 2009

### Members

nid | group | header | window | yr-cols | period (data) | file | title
97551 | G843 | H1 | 2009 | 57% | 2009-01-01..2010-12-31 | c434d760-60ec-4184-8cc1-d990a2bea169.csv | Growth in Subscribers during 2009
97553 | G843 | H1 | 2010 | 57% | 2010-01-01..2011-12-31 | 9ddac4e0-1827-4e89-a2c7-8fe6f788b890.csv | Growth in Subscribers during 2010
97554 | G843 | H1 | 2011 | 57% | 2011-01-01..2012-12-31 | 10c0e78f-0ff2-4b96-acef-442345921137.csv | Growth in Subscribers during 2011
97555 | G843 | H1 | 2012 | 43% | 2012-01-01..2013-12-31 | 55ffa37e-a127-4898-a327-11300d944034.csv | Growth in Subscribers during 2012
97556 | G843 | H1 | 2013 | 57% | 2013-01-01..2014-12-31 | 84ef1a5d-0ff8-464f-9669-6a73ed5933d2.csv | Growth in Subscribers during 2013

---

## C8 · Higher secondary schools according to type of management in Rural & Urban areas

- ministry: Ministry of Education, Department of School Education and Literacy, National Council of Educational Research and Training (NCERT) | members in scope: 6 | current mac: review
- detector: flags NAME_PINS_VALUE,MAC_REVIEW | min_header_match  | admin levels - | varying dims - | suggested mac urban_rural | header dims state
- varying title text: Higher secondary schools according to type of management in Rural & Urban areas | Higher secondary schools according to type of management in Rural area | Higher secondary schools according to type of management in Urban area | Secondary schools according to type of management in Rural & Urban areas | Secondary schools according to type of management in Rural area | Secondary schools according to type of management in Urban area
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=Secondary and Higher Secondary Schools according to Type of Management by Area | mac=area,school_level

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [6] 5 cols, year-labelled cols 0%: STATE/U.T. | Type of Management  Government | Type of Management  Local Body | Type of Management  Private Aided | Type of Management  Private Unaided

### Members

nid | group | header | window | yr-cols | period (data) | file | title
156910 | G844 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 235e9f60-2507-4aee-8286-5a8335ccc0bb.csv | Higher secondary schools according to type of management in Rural & Urban areas as on 30th September 2009
156901 | G845 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | e3a7914c-884e-4a43-9bcf-1542f048bad0.csv | Higher secondary schools according to type of management in Rural area as on 30th September 2009
156907 | G846 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | f6e7f6b1-36fa-4c1f-9a14-c48fc03e2550.csv | Higher secondary schools according to type of management in Urban area as on 30th September 2009
156898 | G847 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 0406cd7a-4a75-4bf0-8e43-52eba6f567d7.csv | Secondary schools according to type of management in Rural & Urban areas as on 30th September 2009
156871 | G848 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 57097bf0-8ed2-40a9-81e8-7d2d95c805f4.csv | Secondary schools according to type of management in Rural area as on 30th September 2009
156895 | G849 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 64c25c5e-a1af-49c1-b004-62cc37303e09.csv | Secondary schools according to type of management in Urban area as on 30th September 2009

### Similar rows outside this collection (same ministry)

- collection [6] Schools according to type of management, by area (curate; free); best score 91.66666666666666; e.g. 156826 Primary schools according to type of management in Rural area as on 30th September 2009

---

## C9 · Higher secondary schools in Rural & Urban areas according to type of building in which majority of classes are held

- ministry: Ministry of Education, Department of School Education and Literacy, National Council of Educational Research and Training (NCERT) | members in scope: 6 | current mac: review
- detector: flags NAME_PINS_VALUE,MAC_REVIEW | min_header_match  | admin levels - | varying dims - | suggested mac urban_rural | header dims state
- varying title text: Higher secondary schools in Rural & Urban areas | Higher secondary schools in Urban area | Higher secondary schools in rural area | Secondary schools in Rural & Urban areas | Secondary schools in Rural area | Secondary schools in Urban area
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=Secondary and Higher Secondary Schools by Area according to Type of Building in which Majority of Classes are Held | mac=area,school_level

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [6] 7 cols, year-labelled cols 0%: STATE/U.T. | Type of School Building  Pucca | Type of School Building  Partly Pucca | Type of School Building  Kuchcha | Type of School Building  Tent | Type of School Building  Open Space | Total

### Members

nid | group | header | window | yr-cols | period (data) | file | title
159970 | G850 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | fc187008-82dd-47f7-a29b-772ea417d37a.csv | Higher secondary schools in Rural & Urban areas according to type of building in which majority of classes are held as on 30th September 2009
159964 | G852 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 1676dc31-f5b7-4c6c-bd43-6d45b6ceb167.csv | Higher secondary schools in rural area according to type of building in which majority of classes are held  as on 30th September 2009
159967 | G851 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 7cdddfc3-1cb3-48b7-b621-28ac0b6bd989.csv | Higher secondary schools in Urban area according to type of building in which majority of classes are held as on 30th September 2009
159961 | G853 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | f26df2bb-dcc8-442e-a3e4-495bdde12254.csv | Secondary schools in Rural & Urban areas according to type of building in which majority of classes are held as on 30th September 2009
159955 | G854 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 90390091-1dc2-412d-83f0-79252c4a1334.csv | Secondary schools in Rural area according to type of building in which majority of classes are held as on 30th September 2009
159946 | G855 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | c26be9cb-ac77-4d8e-9ec5-fa854990e286.csv | Secondary schools in Urban area according to type of building in which majority of classes are held as on 30th September 2009

### Similar rows outside this collection (same ministry)

- nid 159928 (non-mergeable, no collection; free; score 94.44444444444444; window 2009; hdr 'Sl. No.,STATE/U.T.,Type of School Building  Pucca,Type of School Building  Partly Pucca,Type of School Building  Kuchcha'; file ef88609f-6e40-4fa9-8b91-aac678ddb668.csv) Primary schools in Rural & Urban areas according to type of building in which majority of classes are held as on 30th September 2009
- nid 159919 (non-mergeable, no collection; free; score 93.97590361445783; window 2009; hdr 'Sl. No.,STATE/U.T.,Type of School Building  Pucca,Type of School Building  Partly Pucca,Type of School Building  Kuchcha'; file 65ff277a-642f-4ef0-bc2a-21af44de4d78.csv) Primary schools in Rural area according to type of building in which majority of classes are held as on 30th September 2009
- nid 159922 (non-mergeable, no collection; free; score 93.97590361445783; window 2009; hdr 'Sl. No.,STATE/U.T.,Type of School Building  Pucca,Type of School Building  Partly Pucca,Type of School Building  Kuchcha'; file eab8beb9-8888-4615-81b3-ef32bb680709.csv) Primary schools in Urban area according to type of building in which majority of classes are held as on 30th September 2009
- nid 159943 (non-mergeable, no collection; free; score 92.47311827956989; window 2009; hdr 'Sl. No.,STATE/U.T.,Type of School Building   Pucca,Type of School Building  Partly Pucca,Type of School Building  Kuchch'; file 6bb4c06b-69fc-4115-b7b8-14d5082c9957.csv) Upper primary schools in Rural & Urban areas according to type of building in which majority of classes are held as on 30th September 2009
- nid 159931 (non-mergeable, no collection; free; score 91.86046511627907; window 2009; hdr 'Sl. No.,STATE/U.T.,Type of School Building  Pucca,Type of School Building  Partly Pucca,Type of School Building  Kuchcha'; file 908ada85-b717-4835-b3ad-d569e11b78d5.csv) Upper primary schools in Rural area according to type of building in which majority of classes are held as on 30th September 2009
- nid 159937 (non-mergeable, no collection; free; score 91.86046511627907; window 2009; hdr 'Sl. No.,STATE/U.T.,Type of School Building  Pucca,Type of School Building  Partly Pucca,Type of School Building  Kuchcha'; file 3cdbf9e5-9c32-4b7a-9480-b76535e3de8a.csv) Upper primary schools in Urban area according to type of building in which majority of classes are held as on 30th September 2009

---

## C10 · Land use pattern

- ministry: NITI Aayog | members in scope: 34 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels - | varying dims state | suggested mac state | header dims -
- varying title text: Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi | Goa
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=state

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [34] 3 cols, year-labelled cols 0%: Land Use | Area in thousands ha | Percentage

### Members

34 members, grouped (group | header | members | years in titles | sample titles):
- G856 | H1 | 33 | -x33 | template: Land use pattern - <STATE>
    e.g. Land use pattern - Andhra Pradesh || Land use pattern - Arunachal Pradesh || Land use pattern - Assam
- G857 | H1 | 1 | -x1 | template: Land use pattern - Orissa
    e.g. Land use pattern - Orissa

### Similar rows outside this collection (same ministry)

- nid 88748 (non-mergeable, no collection; free; score 90; window -; hdr 'Land Use,Area in thousands ha,Percentage'; file e68ec6fa-3fbc-43f8-a1c0-6fb9f8ae2e9a.xls) Land use pattern - Andaman and Nicobar
- nid 88784 (non-mergeable, no collection; free; score 90; window -; hdr 'States/UTs,Category,Total geographical area,Reporting area for land utilization,Forests,Not available for cultivation,Pe'; file eb9be5be-21d5-4134-a154-d10d08fe87ec.csv) States/UTs-wise Land Use Pattern

---

## C11 · List of MSME Registered Units under Udyog Aadhaar Memorandum

- ministry: Ministry of Micro, Small and Medium Enterprises | members in scope: 36 | current mac: review
- detector: flags HEADER_NULL_MIX,BROKEN_HEADER,MAC_REVIEW | min_header_match  | admin levels - | varying dims state | suggested mac - | header dims state,district
- varying title text: Andaman and Nicobar Islands | Andhra Pradesh | Arunachal Pradesh | Assam | Bihar | Chandigarh | Chhattisgarh | Dadra and Nagar Haveli | Daman and Diu | Delhi
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=- | notes=State/District are columns. nids 6690671 (Andhra Pradesh) and 6690685 (Maharashtra) downloaded an error page ('Download Token Expired') - re-download, kept in collection

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [19] 20 cols, year-labelled cols 0%: AID | EnterpriseName | SocialCategory | Gender | PH | OrganisationType | PlantLocation | Address | State | District | PINCode | CommmenceDate | MajorActivity | EnterpriseType | NIC5DigitCode | TotalEmp | InvestmentCost | Dic_Name | RegistrationDate | LG_Dist_Code
- H2 [15] NO HEADERS EXTRACTED
- H3 [2] ERROR PAGE, not data

### Members

36 members, grouped (group | header | members | years in titles | sample titles):
- G858 | H1 | 19 | -x19 | template: List of MSME Registered Units under Udyog Aadhaar Memorandum - <STATE>
    e.g. List of MSME Registered Units under Udyog Aadhaar Memorandum - Andaman and Nicobar Islands || List of MSME Registered Units under Udyog Aadhaar Memorandum - Arunachal Pradesh || List of MSME Registered Units under Udyog Aadhaar Memorandum - Assam
- G859 | H2 | 15 | -x15 | template: List of MSME Registered Units under Udyog Aadhaar Memorandum - <STATE>
    e.g. List of MSME Registered Units under Udyog Aadhaar Memorandum - Bihar || List of MSME Registered Units under Udyog Aadhaar Memorandum - Delhi || List of MSME Registered Units under Udyog Aadhaar Memorandum - Gujarat
- G860 | H3 | 2 | -x2 | template: List of MSME Registered Units under Udyog Aadhaar Memorandum - <STATE>
    e.g. List of MSME Registered Units under Udyog Aadhaar Memorandum - Andhra Pradesh || List of MSME Registered Units under Udyog Aadhaar Memorandum - Maharashtra

---

## C12 · Month wise break up of Non Residents Indians arrivals (schema 1)

- ministry: Ministry of Tourism | members in scope: 5 | current mac: review
- detector: flags SCHEMA_N_SUFFIX,MAC_REVIEW | min_header_match  | admin levels - | varying dims year | suggested mac year | header dims -
- varying title text: Month wise break up of Non Residents Indians arrivals 2018-2020 | Month wise break-up of Non-Resident Indians (NRIs) Arrivals from 2017 to 2019 | Month wise break-up of Non-Residents Indians (NRIs) arrivals 2018-2020 | Month wise break-up of non resident indians (nris) arrivals 2019-2021 | Month-wise break-up of Non-Residents indians (NRIs) Arrivals from 2016 to 2018
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=Month wise break up of Non Residents Indians arrivals | mac=year

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [5] 2 cols, year-labelled cols 83%: Months | Growth 2019/18 %

### Members

nid | group | header | window | yr-cols | period (data) | file | title
7059501 | G861 | H1 | 2018 | 83% | 2018-01-01..2020-12-31 | 8db754ef-1776-416a-bfbd-bc5696e31492.csv | Month wise break up of Non Residents Indians arrivals 2018-2020
7278577 | G864 | H1 | 2019 | 83% | 2019-01-01..2021-12-31 | c131ebfc-24b3-4bcf-8176-c40e56bada7b.csv | Month wise break-up of non resident indians (nris) arrivals 2019-2021
6879832 | G862 | H1 | 2017-2019 | 83% | 2017-01-01..2019-12-31 | d8db6d28-354a-4ba9-ba0f-4b4dc9d6446f.csv | Month wise break-up of Non-Resident Indians (NRIs) Arrivals from 2017 to 2019
7052261 | G863 | H1 | 2018 | 83% | 2018-04-01..2020-03-31 | 7c8569e5-3c5a-40b1-90e0-74a755544156.csv | Month wise break-up of Non-Residents Indians (NRIs) arrivals 2018-2020
6819404 | G865 | H1 | 2016-2018 | 83% | 2016-01-01..2018-12-31 | dee78a42-30ce-40c4-9135-c96c71e57e18.csv | Month-wise break-up of Non-Residents indians (NRIs) Arrivals from 2016 to 2018

### Similar rows outside this collection (same ministry)

- nid 6649046 (non-mergeable, no collection; free; score 97.14285714285714; window 2015-2017; hdr 'Months,2015,2016,2017,Percentage Growth  2016/2015,Percentage Growth  2017/2016'; file cf65451a-77f0-4cb9-b179-d001be2abc59.csv) Month-wise break-up of Non-Residential Indians (NRIs) Arrivals from 2015 to 2017
- nid 6651716 (to be removed, no collection; free; score 97.14285714285714; window 2015-2017; hdr 'Months,2015,2016,2017,Percentage Growth  2016/2015,Percentage Growth  2017/2016'; file 52510a7c-460b-4c71-bd4c-825a5b1d96c9.csv) Month-wise break-up of Non-Residential Indians (NRIs) Arrivals from 2015 to 2017
- nid 604708545 (non-mergeable, no collection; free; score 92.85714285714286; window 2019-2021; hdr 'Sl. No.,Months,2019,2020,2021,Growth 2020/2019 In Percentage,Growth 2021/2020 In Percentage'; file 77b38fbd-1c1c-4ac6-8121-feb47f9aabcf.xls) Month-wise Details of Break-up of Non-Residents Indians (NRIs) Arrivals from 2019 to 2021
- nid 604709535 (to be removed, no collection; free; score 92.85714285714286; window 2019-2021; hdr 'Months,2020,2021,2022,Growth 2021/2020 In Percentage,Growth 2022/2021 In Percentage'; file 8141f93a-ebe1-4d27-b6b6-111410e75fca.xls) Month-wise Details of Break-up of Non-Residents Indians (NRIs) Arrivals from 2019 to 2021

### Year windows of the same series (parsed from titles)

- NESTED: 6649046 and 6651716 cover the same window from 2015 to 2017
- NESTED: 604708545 and 604709535 cover the same window from 2019 to 2021

---

## C13 · Monthly Coal Statement of Thermal Power Stations

- ministry: Ministry of Power, Central Electricity Authority | members in scope: 26 | current mac: review
- detector: flags HEADER_IRRECONCILABLE,MAC_REVIEW,MAC_MISSING_DIM | min_header_match 0.71 | admin levels - | varying dims year,month | suggested mac year,month | header dims -
- varying title text: April 2017 | April 2018 | August 2017 | August 2018 | August 2023 | December 2017 | February 2018 | January 2018 | July 2017 | July 2018
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=year,month | notes=2023 edition adds consumption columns and drops unit text

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [17] 14 cols, year-labelled cols 0%: Region | Name of TPS | Installed  CapacityMW | Monthly Allocation from CIL/SCCL | Opening Stocks | Receipt  CIL/SCCL in 000 Tonnes | Receipt  Captive in 000 Tonnes | Receipt  EAuction in 000 Tonnes | Receipt  Import in 000 Tonnes | Receipt  Others in 000 Tonnes | Receipt  Total in 000 Tonnes | % Receipt w.r.t. Alloted Coal | Total Consumption in 000 Tonnes | Closing Stocks in 000 Tonnes
- H2 [6] 17 cols, year-labelled cols 0%: Thermal Power Station TPS | Zone | Installed Capacity MW | Monthly Allocation from CIL/SCCL | Opening Stocks | Receipt  CIL | Receipt  SCCL | Receipt  Captive | Receipt  EAuction | Receipt  Import | Receipt  Others | Receipt  Total | Receipt  % Receipt w.r.t. Alloted Coal | Consumption  Domestic | Consumption  Imported | Consumption  Total Consumption | Closing Stocks
    match vs H1 0.71; only here: ['Receipt  % Receipt w.r.t. Alloted Coal', 'Consumption  Domestic', 'Consumption  Total Consumption', 'Zone', 'Receipt  SCCL', 'Receipt  CIL', 'Thermal Power Station TPS', 'Consumption  Imported']; only in H1: ['alloted coal r receipt t w', 'cil receipt sccl', 'consumption total', 'name tps', 'region']
- H3 [3] 13 cols, year-labelled cols 0%: Region | Name of TPS | Installed Capacity MW | Monthly Allocation from CIL/SCCL in 000 Tonnes | Opening Stocks  in 000 Tonnes | Receipt  CIL/SCCL  in 000 Tonnes | Receipt  Captive  in 000 Tonnes | Receipt  EAuction  in 000 Tonnes | Receipt  Import  in 000 Tonnes | Receipt Total  in 000 Tonnes | % Receipt w.r.t. Alloted Coal | Total Consumption  in 000 Tonnes | Closing Stocks  in 000 Tonnes
    match vs H1 1.00; only here: []; only in H1: ['other receipt']

### Members

26 members, grouped (group | header | members | years in titles | sample titles):
- G866 | H1 | 17 | 2017x6, 2018x11 | template: Monthly Coal Statement of Thermal Power Stations for <MONTH> <YEAR>
    e.g. Monthly Coal Statement of Thermal Power Stations for April 2018 || Monthly Coal Statement of Thermal Power Stations for August 2017 || Monthly Coal Statement of Thermal Power Stations for August 2018
- G867 | H2 | 6 | 2023x6 | template: Monthly Coal Statement of Thermal Power Stations for <MONTH> <YEAR>
    e.g. Monthly Coal Statement of Thermal Power Stations for August 2023 || Monthly Coal Statement of Thermal Power Stations for July 2023 || Monthly Coal Statement of Thermal Power Stations for June 2023
- G868 | H3 | 3 | 2017x3 | template: Monthly Coal Statement of Thermal Power Stations for <MONTH> <YEAR>
    e.g. Monthly Coal Statement of Thermal Power Stations for April 2017 || Monthly Coal Statement of Thermal Power Stations for June 2017 || Monthly Coal Statement of Thermal Power Stations for May 2017

### Similar rows outside this collection (same ministry)

- collection [108] Monthly Coal Statement of Thermal Power Stations (direct merge) (direct; free); best score 100.0; e.g. 86712 Monthly Coal Statement of Thermal Power Stations for April 2008
- nid 603066852 (non-mergeable, no collection; free; score 100.0; window 2024; hdr 'Sl. No.,Region,Name of TPS,Installed Capacity MW,Receipt  CIL,Receipt  SCCL,Receipt  Captive,Receipt  EAuction,Receipt  '; file 558fcf41-7ec8-46b0-a2c6-2712bc3808ae.csv) Monthly Coal Statement of Thermal Power Stations for January 2024

---

## C14 · Primary schools in Rural & Urban areas according to availability of facilities within school premises

- ministry: Ministry of Education, Department of School Education and Literacy, National Council of Educational Research and Training (NCERT) | members in scope: 6 | current mac: review
- detector: flags NAME_PINS_VALUE,MAC_REVIEW | min_header_match  | admin levels - | varying dims - | suggested mac urban_rural | header dims state
- varying title text: Primary schools in Rural & Urban areas | Primary schools in Rural area | Primary schools in Urban area | Upper primary schools in Rural & Urban areas | Upper primary schools in Rural area | Upper primary schools in Urban area
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=Primary and Upper Primary Schools by Area according to Availability of Facilities within School Premises | mac=area,school_level

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [6] 4 cols, year-labelled cols 0%: STATE/U.T. | Availability Within School Premises  Drinking Water | Availability Within School Premises  Usable Urinal | Availability Within School Premises  Playground

### Members

nid | group | header | window | yr-cols | period (data) | file | title
163780 | G869 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | efdd21b4-beb6-4078-a139-24aa9170ce5c.csv | Primary schools in Rural & Urban areas according to availability of facilities within school premises as on 30th September 2009
163774 | G870 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 4b9e75f0-1bd6-479e-80dc-1a0751092c93.csv | Primary schools in Rural area according to availability of facilities within school premises as on 30th September 2009
163777 | G871 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 99949355-3d1a-4931-90cb-eee3fcb213dc.csv | Primary schools in Urban area according to availability of facilities within school premises as on 30th September 2009
163789 | G872 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 6b78d73f-c19d-4890-8c5f-579f50e2bc8f.csv | Upper primary schools in Rural & Urban areas according to availability of facilities within school premises as on 30th September 2009
163783 | G873 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | d999ae13-043d-4230-b89c-f1b7c1f53307.csv | Upper primary schools in Rural area according to availability of facilities within school premises as on 30th September 2009
163786 | G874 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 114c0f40-3d7f-407b-bbc1-cfb5898625f2.csv | Upper primary schools in Urban area according to availability of facilities within school premises as on 30th September 2009

### Similar rows outside this collection (same ministry)

- collection [6] Schools according to availability of facilities within school premises, by area (curate; free); best score 94.5054945054945; e.g. 163798 Secondary schools in Rural & Urban areas according to availability of facilities within school premises as on 30th September 2009

---

## C15 · Rainfall in Central India and its departure from normal for Monsoon session

- ministry: Ministry of Earth Sciences | members in scope: 10 | current mac: review
- detector: flags NAME_PINS_VALUE,HEADER_NULL_MIX,HEADER_IRRECONCILABLE,MAC_REVIEW | min_header_match 0.83 | admin levels - | varying dims year,month | suggested mac month | header dims year
- varying title text: All India and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2015 | All India and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2016 | Central India and its departure from normal for Monsoon session from 1901 to 2019 | Central India and its departure from normal for Monsoon session from 1901-2021 | NE India and its departure from normal for Monsoon session from 1901-2021 | NW India and its departure from normal for Monsoon session from 1901-2021 | North East India and its departure from normal for Monsoon Session from 1901 to 2019 | North West I
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=Rainfall in India by Region and its Departure from Normal for Monsoon Season | mac=region | notes=All India, Central, NE and NW India tables mixed

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [8] NO HEADERS EXTRACTED
- H2 [1] 6 cols, year-labelled cols 0%: YEAR | JUN | JUL | AUG | SEP | JUNSEP
- H3 [1] 6 cols, year-labelled cols 0%: YEAR | JUN | JUL | AUG | SEP | JNSP
    match vs H1 0.83; only here: ['JNSP']; only in H1: ['junsep']

### Members

nid | group | header | window | yr-cols | period (data) | file | title
6803241 | G882 | H2 | 1901-2019 | 0% | .. | af34a228-2b53-4044-89c9-5f73412d7823.csv | Rainfall in all India and its departure from normal during Monsoon session (June-Sept) from 1901 to 2019
3973101 | G875 | H1 | 1901-2016 | - | .. | 364aaef4-1b5b-4cf6-8b21-e2515d0e772b.csv | Rainfall in All India and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2016
1090561 | G875 | H1 | 1901-2015 | - | .. | 9a0e4d2f-afe5-4df1-a18a-7bdb46416dd4.csv | Rainfall in All India and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2015
7175407 | G876 | H1 | 1901 | - | .. | af312c2d-c771-44da-9b43-dcd7ea7679f6.csv | Rainfall in all India and its departure from normal for Monsoon session from 1901-2021
6803245 | G878 | H1 | 1901-2019 | - | .. | 40e1b431-eae6-4ab2-8587-b8ddbdd6bf1c.csv | Rainfall in Central India and its departure from normal for Monsoon session from 1901 to 2019
7175391 | G877 | H1 | 1901 | - | .. | 471c26a1-2888-49da-baa2-0f034bf411a9.csv | Rainfall in Central India and its departure from normal for Monsoon session from 1901-2021
7175401 | G883 | H3 | 1901 | 0% | .. | 5aa7cd83-f317-4145-8be8-f12b115ecfe7.csv | Rainfall in NE India and its departure from normal for Monsoon session from 1901-2021
6803243 | G880 | H1 | 1901-2019 | - | .. | 67c57ef9-5918-4189-b0ea-f7cce507e46a.csv | Rainfall in North East India and its departure from normal for Monsoon Session from 1901 to 2019
6803244 | G881 | H1 | 1901-2019 | - | .. | 4a9a45e9-bf89-447c-bc32-b85d5b2cccc4.csv | Rainfall in North West India and its departure from normal for Monsoon session from 1901 to 2019
7175397 | G879 | H1 | 1901 | - | .. | 01dbcadf-f191-4282-b697-dbfbcc93522b.csv | Rainfall in NW India and its departure from normal for Monsoon session from 1901-2021

### Similar rows outside this collection (same ministry)

- nid 6803246 (non-mergeable, no collection; free; score 90; window 1901-2019; hdr 'NONE'; file 4820e9ac-614e-414d-8c1d-c18d7fe816da.csv) Rainfall in South Peninsula and its departure from normal for Monsoon Session from 1901 to 2019
- nid 7175404 (non-mergeable, no collection; free; score 90; window 1901; hdr 'NONE'; file c23cc496-ead7-47b8-9595-7e7da20268ec.csv) Rainfall in South Peninsula and its departure from normal for Monsoon session from 1901-2021
- nid 1090581 (non-mergeable, no collection; free; score 90; window 1901-2015; hdr 'NONE'; file d0e31e04-863e-442b-a438-d61fd26bd0e1.csv) Rainfall in North West India  (9 subdivision) and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2015
- nid 3973161 (non-mergeable, no collection; free; score 90; window 1901-2016; hdr 'NONE'; file 9ba9e285-4cda-4185-b63d-6210775a957e.csv) Rainfall in North West India (9 subdivision) and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2016
- nid 1090601 (non-mergeable, no collection; free; score 90; window 1901-2015; hdr 'NONE'; file ae52d3a3-6e82-499c-8261-1986ba9c10a9.csv) Rainfall in North East India  (7 subdivision) and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2015
- nid 3973121 (non-mergeable, no collection; free; score 90; window 1901-2016; hdr 'NONE'; file 87ffae44-c477-4a6a-a28a-324d0277777b.csv) Rainfall in North East India (7 subdivision) and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2016
- nid 7175424 (non-mergeable, no collection; free; score 90; window 1901; hdr 'NONE'; file 54356459-ab30-48e8-a830-0eeb8cfd5a3f.csv) Rainfall in sub-division and its departure from normal for Monsoon session from 1901-2021
- nid 1090621 (non-mergeable, no collection; free; score 90; window 1901-2015; hdr 'NONE'; file 4e66f875-d51a-4502-bfcf-d404abc946d2.csv) Rainfall in Central India  (10 subdivision) and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2015
- nid 3973201 (non-mergeable, no collection; free; score 90; window 1901-2016; hdr 'NONE'; file a3e68398-a99f-41ba-b57d-df8a4d884e6b.csv) Rainfall in Central India (10 subdivision) and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2016
- nid 1090641 (non-mergeable, no collection; free; score 90; window 1901-2015; hdr 'NONE'; file 40700927-e6da-4d6d-ba1a-d0abc33c61da.csv) Rainfall in South Peninsula (10 subdivisions) and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2015
- nid 3973141 (non-mergeable, no collection; free; score 90; window 1901-2016; hdr 'NONE'; file 35babda8-94e2-4d34-a4c7-7906725540c2.csv) Rainfall in South Peninsula (10 subdivisions) and its departure from normal for Monsoon Session (June-Sept) from 1901 to 2016

### Year windows of the same series (parsed from titles)

- NESTED: 1090561 (from 1901 to 2015) is contained in 3973101 (from 1901 to 2016)
- NESTED: 1090581 (from 1901 to 2015) is contained in 3973161 (from 1901 to 2016)
- NESTED: 1090601 (from 1901 to 2015) is contained in 3973121 (from 1901 to 2016)
- NESTED: 1090621 (from 1901 to 2015) is contained in 3973201 (from 1901 to 2016)
- NESTED: 1090641 (from 1901 to 2015) is contained in 3973141 (from 1901 to 2016)

---

## C16 · Share of Major Countries of the World in International Tourist Arrivals

- ministry: Ministry of Tourism | members in scope: 5 | current mac: review
- detector: flags MAC_REVIEW,MAC_MISSING_DIM | min_header_match 1.0 | admin levels - | varying dims year | suggested mac year | header dims -
- varying title text: during 2016 and 2017 | during 2017 & 2018 | in 2018 and 2019 | in 2019 & 2020 | in 2020 & 2021
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=year

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [4] 4 cols, year-labelled cols 67%: S. No. | Country | International Tourist Arrivals  in million  2020 | Percentage % Share  2020
- H2 [1] 3 cols, year-labelled cols 80%: Country | International tourist Arrivals in Million  2016 | Percentage Share  2016
    match vs H1 1.00; only here: []; only in H1: ['number s']

### Members

nid | group | header | window | yr-cols | period (data) | file | title
7280528 | G887 | H1 | 2020 | 67% | 2020-01-01..2021-12-31 | deae82bb-54f2-41ee-a7d9-4a3f112ac476.csv | Share of Major countries of  the world in international tourist arrivals in 2020 & 2021
6651742 | G888 | H2 | 2016 | 80% | 2017-01-01..2018-12-31 | 5ea21eb2-cbf8-49e4-859e-ce884eb4e6f2.csv | Share of major countries of the world in International Tourist arrivals during 2016 and 2017
6819427 | G884 | H1 | 2017 | 67% | 2018-01-01..2019-12-31 | ff6ac6d0-2cc4-4001-b24d-90e1d96912e7.csv | Share of Major Countries of the World in International Tourist Arrivals during 2017 & 2018
6879857 | G886 | H1 | 2018 | 67% | 2019-01-01..2020-12-31 | 1028692a-09e7-46ba-973f-c4d453414a0a.csv | Share of Major Countries of the World in International Tourist Arrivals in 2018 and 2019
7060630 | G885 | H1 | 2019 | 67% | 2020-01-01..2021-12-31 | 391b40f0-1601-40a2-869a-e7ae1da59471.csv | Share of Major Countries of the World in International Tourist Arrivals in 2019 & 2020

### Similar rows outside this collection (same ministry)

- nid 604709219 (non-mergeable, no collection; free; score 92.53731343283582; window 2020; hdr 'Rank,Country,International Tourist Arrivals  2020 in Million,International Tourist Arrivals  2021 in Million,Percentage '; file a0e368db-3858-452a-9631-080ec9470b19.xls) Rank-wise Share of Major Countries of the World in International Tourist Arrivals during 2020 and 2021
- nid 604712872 (to be removed, no collection; free; score 92.53731343283582; window 2020; hdr 'Rank,Country,International Tourist Arrivals  2020 in Million,International Tourist Arrivals  2021 in Million,Percentage '; file 7de24430-11c9-48db-b611-ae4ce0a8f9eb.csv) Rank-wise Share of Major Countries of the World in International Tourist Arrivals during 2020 and 2021
- nid 6651741 (non-mergeable, no collection; free; score 90; window 2000-2017; hdr 'Year,World   Arrival in Million,World  Percentage change,India  Arrival in Million,India  Percentage change,Percentage s'; file 563c2d80-692e-47d4-919b-30388925da27.csv) International Tourist Arrivals in world and India from 2000 to 2017
- nid 6819426 (non-mergeable, no collection; free; score 90; window 2000-2018; hdr 'Year,World  Number in million,World  % Change,India  Number in million,India  % Change,Percentage Share of India,Rank of'; file 6894c074-644a-4041-a839-feecf1edbdd8.csv) International Tourist Arrivals in World and India from 2000 to 2018
- nid 6879856 (non-mergeable, no collection; free; score 90; window 2001-2019; hdr 'Year,World   Number in million,World  % Change,India  Number in million,India  % Change,Percentage Share of India,Rank o'; file bb4f879e-28e7-465b-8af3-31ec4662a4fd.csv) International Tourist Arrivals in World and India from 2001 to 2019
- nid 7060623 (non-mergeable, no collection; free; score 90; window 2001; hdr 'Year,World   Number in million,World  % Change,India  Number  in million,India  % Change,Percentage Share of India,Rank '; file 2905d253-b39e-4347-83ad-49d25f5058b3.csv) International Tourist Arrivals in World and India, 2001-2020
- nid 7280494 (non-mergeable, no collection; free; score 90; window 2001; hdr 'Year,World   Number in million,World  % Change,India  Number  in million,India  % Change,Percentage Share of India,Rank '; file d6273525-abe0-4416-ba2e-79120615eb3d.csv) International tourist arrivals in world and India 2001-2021

### Year windows of the same series (parsed from titles)

- NESTED: 6651741 (from 2000 to 2017) is contained in 6819426 (from 2000 to 2018)
- OVERLAP: 6651741 (from 2000 to 2017) overlaps 6879856 (from 2001 to 2019)
- OVERLAP: 6819426 (from 2000 to 2018) overlaps 6879856 (from 2001 to 2019)

---

## C17 · State Wise Distribution Of Enterprises By Nature Of Operation (Fourth All India Census of MSME: Unregistered Sector)

- ministry: Ministry of Micro, Small and Medium Enterprises | members in scope: 5 | current mac: review
- detector: flags NAME_PINS_VALUE,HEADER_IRRECONCILABLE,MAC_REVIEW | min_header_match 0.2 | admin levels state | varying dims - | suggested mac - | header dims state
- varying title text: Industry-Wise Distribution Of Enterprises By Type Of Organisation | State Wise Distribution Of Enterprises By Nature Of Operation | State Wise Distribution Of Enterprises By Type Of Organisation | State-Wise Distribution Of Enterprises By Nature Of Activity | State-Wise Distribution Of Enterprises By Religion Of The Owner
- prior proposal (Claude, NOT approved by the user; the rules override it): action=split | name=(unchanged) | mac=- | split_rule=* => !non-mergeable | notes=five different tables (operation, activity, organisation, religion, industry-wise) - nothing to stack

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [1] 9 cols, year-labelled cols 10%: NIC 2004 | Description | Proprietary Number in Lakhs | Partnership Number in Lakhs | Private Co. Number in Lakhs | Cooperative Number in Lakhs | Others Number in Lakhs | Not Recorded Number in Lakhs | Total Number in Lakhs
- H2 [1] 6 cols, year-labelled cols 0%: State/UT | Perennial Number in Lakhs | Seasonal Number in Lakhs | Casual Number in Lakhs | Not Recorded Number in Lakhs | Total Number in Lakhs
    match vs H1 0.33; only here: ['Seasonal Number in Lakhs', 'State/UT', 'Casual Number in Lakhs', 'Perennial Number in Lakhs']; only in H1: ['co number private', 'cooperative number', 'description', 'nic', 'number other', 'number partnership', 'number proprietary']
- H3 [1] 8 cols, year-labelled cols 0%: State/UT | Proprietary Numbers in Lakhs | Partnership Numbers in Lakhs | Private Co. Numbers in Lakhs | Cooperative Numbers in Lakhs | Others Numbers in Lakhs | Not Recorded Numbers in Lakhs | Total Numbers in Lakhs
    match vs H1 0.88; only here: ['State/UT']; only in H1: ['description', 'nic']
- H4 [1] 5 cols, year-labelled cols 0%: State/UT | Manufacturing/ Assembly/Processing Number in Lakhs | Services Number in Lakhs | Repairing  Maintenance Number in Lakhs | Total Number in Lakhs
    match vs H1 0.20; only here: ['Manufacturing/ Assembly/Processing Number in Lakhs', 'State/UT', 'Services Number in Lakhs', 'Repairing  Maintenance Number in Lakhs']; only in H1: ['co number private', 'cooperative number', 'description', 'nic', 'not number recorded', 'number other', 'number partnership', 'number proprietary']
- H5 [1] 10 cols, year-labelled cols 0%: State/UT | Hindu Values in Lakh | Muslim Values in Lakh | Sikh Values in Lakh | Christian Values in Lakh | Jain Values in Lakh | Buddhist Values in Lakh | Others Values in Lakh | Not Recorded Values in Lakh | Total Values in Lakh
    match vs H1 0.00; only here: ['State/UT', 'Others Values in Lakh', 'Jain Values in Lakh', 'Hindu Values in Lakh', 'Not Recorded Values in Lakh', 'Total Values in Lakh', 'Sikh Values in Lakh', 'Buddhist Values in Lakh', 'Muslim Values in Lakh', 'Christian Values in Lakh']; only in H1: ['co number private', 'cooperative number', 'description', 'nic', 'not number recorded', 'number other', 'number partnership', 'number proprietary', 'number total']

### Members

nid | group | header | window | yr-cols | period (data) | file | title
103562 | G889 | H1 | - | 10% | .. | b9087879-4497-455b-89d6-4fba8587e709.csv | Industry-Wise Distribution Of Enterprises By Type Of Organisation (Fourth All India Census of MSME: Unregistered Sector)
103560 | G890 | H2 | - | 0% | .. | 38af0182-4329-4145-9ae0-d2135f287eb1.csv | State Wise Distribution Of Enterprises By Nature Of Operation (Fourth All India Census of MSME: Unregistered Sector)
103561 | G891 | H3 | - | 0% | .. | fb044d2b-eaac-4222-a867-9b090f1144a1.csv | State Wise Distribution Of Enterprises By Type Of Organisation (Fourth All India Census of MSME: Unregistered Sector)
103559 | G892 | H4 | - | 0% | .. | ebd6189d-8b6f-43e2-8bcc-96b40f029415.csv | State-Wise Distribution Of  Enterprises By Nature Of Activity  (Fourth All India Census of MSME: Unregistered Sector)
103566 | G893 | H5 | - | 0% | .. | cda6ba5b-d251-479f-adde-af3ec86934bc.csv | State-Wise Distribution Of  Enterprises By Religion Of The Owner  (Fourth All India Census of MSME: Unregistered Sector)

### Similar rows outside this collection (same ministry)

- nid 103481 (non-mergeable, no collection; free; score 95.04950495049505; window -; hdr 'Sl. No.,NIC 2004 ,Description,Proprietary,Partnership,Private Company,Public Ltd. Company,Cooperative,Others,Total'; file 34a69d9f-67ab-4fc1-be4d-53c43b0d916e.csv) Industry-Wise Distribution Of Working Enterprises By Type Of Organisation (Fourth All India Census of MSME: Registered Sector)
- nid 103479 (non-mergeable, no collection; free; score 94.89795918367348; window -; hdr 'Sl. No.,State/UT,Proprietary,Partnership,Private Company,Public Ltd. Company,Cooperative,Others,Total'; file 8822dce8-adfd-42c0-b4c4-c593c2aad39c.csv) State Wise Distribution Of Working Enterprises By Type Of Organisation (Fourth All India Census of MSME: Registered Sector)
- nid 103497 (non-mergeable, no collection; free; score 94.73684210526316; window -; hdr 'NONE'; file e1013d45-3e2f-4a64-be9f-8cc10aef1bb1.csv) State Wise Distribution Of Working Enterprises By Religion Of The Owner (Fourth All India Census of MSME 2006-07 : Registered Sector)
- nid 103558 (non-mergeable, no collection; free; score 91.75257731958763; window -; hdr 'Sl.No,NIC 2004 ,Description,Micro Numbers in Lakh,Small Numbers in Lakh,Total Numbers in Lakh'; file b5dec9f5-42e9-4a75-845b-d947ebae47ec.csv) Industry-Wise Distribution Of  Enterprises By Type Of Enterprise  (Fourth All India Census of MSME: Unregistered Sector)
- nid 103557 (non-mergeable, no collection; free; score 91.48936170212765; window -; hdr 'Sl.No,State/UT,Micro Numbers in Lakh,Small Numbers in Lakh,Total Numbers in Lakh'; file 802bc38b-06b2-4e18-b866-b86ed0bc3f9d.csv) State-Wise Distribution Of  Enterprises By Type Of Enterprise  (Fourth All India Census of MSME: Unregistered Sector)
- nid 103568 (non-mergeable, no collection; free; score 90.42553191489363; window -; hdr 'NONE'; file 05dee3a8-cad5-4b35-8b8b-56b7c7a9d24f.csv) State-Wise Distribution Of  Enterprises By Main Source Of Energy  (Fourth All India Census of MSME 2006-07 : Unregistered Sector)
- nid 103569 (non-mergeable, no collection; free; score 87.30964467005076; window -; hdr 'NONE'; file 1c2d0958-9f7f-4dbe-8872-b9b07993bc53.csv) Industry-Wise Distribution Of  Enterprises By Main Source Of Energy (Fourth All India Census of MSME 2006-07 : Unregistered Sector)
- nid 103485 (non-mergeable, no collection; free; score 86.01036269430051; window -; hdr 'NONE'; file 3beaa7cf-279d-440c-a3c1-f8e5b8e3d550.csv) State-Wise Distribution Of Working Enterprises By Type Of EnterpriseFourth All India Census of MSME 2006-07 : Registered Sector)
- nid 103487 (non-mergeable, no collection; free; score 85.56701030927836; window -; hdr 'NONE'; file 7c057144-b3b2-4737-b763-dcab864a06e3.csv) State-Wise Distribution Of Working Enterprises By Main Source Of Energy  (Fourth All India Census of MSME 2006-07 : Registered Sector)
- nid 103488 (non-mergeable, no collection; free; score 85.42713567839196; window -; hdr 'NONE'; file c36962eb-706d-4c89-9029-65701f6edff9.csv) Industry Wise Distribution Of Working Enterprises By Type Of Fuel Used Fourth All India Census of MSME 2006-07 : Registered Sector)

---

## C18 · State wise/Sector wise Approved Outlay, Revised Outlay and Expenditure for Annual Plan

- ministry: NITI Aayog | members in scope: 5 | current mac: review
- detector: flags HEADER_IRRECONCILABLE,MAC_REVIEW | min_header_match 0.51 | admin levels state | varying dims year | suggested mac - | header dims year
- varying title text: 2007-08 | 2008-09 | 2009-10 | 2010-11 | 2011-12
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=year | notes=later years say Revised Outlay/Anticipated Expenditure

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [3] 117 cols, year-labelled cols 0%: Fin_year | Major_head | HeadsofDevelopmentallfiguresinRslakhs | AndhraPradeshApprovedOutlay | AndhraPradeshRevisedOutlay | AndhraPradeshExpenditure | ArunachalPradeshApprovedOutlay | ArunachalPradeshRevisedOutlay | ArunachalPradeshExpenditure | AssamApprovedOutlay | AssamRevisedOutlay | AssamExpenditure | BiharApprovedOutlay | BiharRevisedOutlay | BiharExpenditure | ChhatisgarhApprovedOutlay | ChhatisgarhRevisedOutlay | ChhatisgarhExpenditure | GoaApprovedOutlay | GoaRevisedOutlay | GoaExpenditure | GujaratApprovedOutlay | GujaratRevisedOutlay | GujaratExpenditure | HaryanaApprovedOutlay | HaryanaRevisedOutlay | HaryanaExpenditure | HimachalpradeshApprovedOutlay | HimachalpradeshRevisedOutlay | HimachalpradeshExpenditure ... (+87 more)
- H2 [1] 79 cols, year-labelled cols 0%: Fin_year | Major_head | HeadsofDevelopmentallfiguresinRslakhs | AndhraPradeshApprovedOutlay | AndhraPradeshRevisedOutlayanticipatedexpenditure | ArunachalPradeshApprovedOutlay | ArunachalPradeshRevisedOutlayanticipatedexpenditure | AssamApprovedOutlay | AssamRevisedOutlayanticipatedexpenditure | BiharApprovedOutlay | BiharRevisedOutlayanticipatedexpenditure | ChhatisgarhApprovedOutlay | ChhatisgarhRevisedOutlayanticipatedexpenditure | GoaApprovedOutlay | GoaRevisedOutlayanticipatedexpenditure | GujaratApprovedOutlay | GujaratRevisedOutlayanticipatedexpenditure | HaryanaApprovedOutlay | HaryanaRevisedOutlayanticipatedexpenditure | HimachalpradeshApprovedOutlay | HimachalpradeshRevisedOutlayanticipatedexpenditure | JammuKashmirApprovedOutlay | JammuKashmirRevisedOutlayanticipatedexpenditure | JharkhandApprovedOutlay | JharkhandRevisedOutlayanticipatedexpenditure | KarnatakaApprovedOutlay | KarnatakaRevisedOutlayanticipatedexpenditure | KeralaApprovedOutlay | KeralaRevisedOutlayanticipatedexpenditure | MPApprovedOutlay ... (+49 more)
    match vs H1 0.52; only here: ['KeralaRevisedOutlayanticipatedexpenditure', 'TamilNaduRevisedOutlayanticipatedexpenditure', 'KarnatakaRevisedOutlayanticipatedexpenditure', 'BiharRevisedOutlayanticipatedexpenditure', 'TotalStatesRevisedOutlayanticipatedexpenditure', 'RajasthanRevisedOutlayanticipatedexpenditure', 'DandDiuRevisedOutlayanticipatedexpenditure', 'GoaRevisedOutlayanticipatedexpenditure', 'PuducherryRevisedOutlayanticipatedexpenditure', 'PunjabRevisedOutlayanticipatedexpenditure']; only in H1: ['aand expenditure nisland', 'aand nisland outlay revised', 'andhra expenditure pradesh', 'andhra outlay pradesh revised', 'arunachal expenditure pradesh', 'arunachal outlay pradesh revised', 'assam expenditure', 'assam outlay revised', 'bihar expenditure', 'bihar outlay revised']
- H3 [1] 79 cols, year-labelled cols 0%: finanical_year | Major_head | HeadsofDevelopmentallfiguresinRslakhs | AndhraPradeshApprovedOutlay | AndhraPradeshRevisedOutlayorAnticipatedExpenditure | ArunachalPradeshApprovedOutlay | ArunachalPradeshRevisedOutlayorAnticipatedExpenditure | AssamApprovedOutlay | AssamRevisedOutlayorAnticipatedExpenditure | BiharApprovedOutlay | BiharRevisedOutlayorAnticipatedExpenditure | ChhatisgarhApprovedOutlay | ChhatisgarhRevisedOutlayorAnticipatedExpenditure | GoaApprovedOutlay | GoaRevisedOutlayorAnticipatedExpenditure | GujaratApprovedOutlay | GujaratRevisedOutlayorAnticipatedExpenditure | HaryanaApprovedOutlay | HaryanaRevisedOutlayorAnticipatedExpenditure | HimachalpradeshApprovedOutlay | HimachalpradeshRevisedOutlayorAnticipatedExpenditure | JammuKashmirApprovedOutlay | JammuKashmirRevisedOutlayorAnticipatedExpenditure | JharkhandApprovedOutlay | JharkhandRevisedOutlayorAnticipatedExpenditure | KarnatakaApprovedOutlay | KarnatakaRevisedOutlayorAnticipatedExpenditure | KeralaApprovedOutlay | KeralaRevisedOutlayorAnticipatedExpenditure | MPApprovedOutlay ... (+49 more)
    match vs H1 0.51; only here: ['HimachalpradeshRevisedOutlayorAnticipatedExpenditure', 'DandDiuRevisedOutlayorAnticipatedExpenditure', 'PunjabRevisedOutlayorAnticipatedExpenditure', 'MeghalayaRevisedOutlayorAnticipatedExpenditure', 'OrissaRevisedOutlayorAnticipatedExpenditure', 'JammuKashmirRevisedOutlayorAnticipatedExpenditure', 'RajasthanRevisedOutlayorAnticipatedExpenditure', 'KeralaRevisedOutlayorAnticipatedExpenditure', 'SikkimRevisedOutlayorAnticipatedExpenditure', 'HaryanaRevisedOutlayorAnticipatedExpenditure']; only in H1: ['aand expenditure nisland', 'aand nisland outlay revised', 'andhra expenditure pradesh', 'andhra outlay pradesh revised', 'approved outlay uttrakhand', 'arunachal expenditure pradesh', 'arunachal outlay pradesh revised', 'assam expenditure', 'assam outlay revised', 'bihar expenditure']

### Members

nid | group | header | window | yr-cols | period (data) | file | title
91393 | G894 | H1 | 2007 | 0% | 2007-04-01..2008-03-31 | e0792875-51a2-4b47-bfab-f8dfe2473030.xls | State wise/Sector wise Approved Outlay, Revised Outlay and Expenditure for Annual Plan 2007-08
91395 | G894 | H1 | 2008 | 0% | 2008-04-01..2009-03-31 | 290a403a-9c72-46e8-98b7-8e6fa9ad8fb9.xls | State wise/Sector wise Approved Outlay, Revised Outlay and Expenditure for Annual Plan 2008-09
91396 | G894 | H1 | 2009 | 0% | 2009-04-01..2010-03-31 | 388d473a-c20d-4bd1-b062-772229545398.xls | State wise/Sector wise Approved Outlay, Revised Outlay and Expenditure for Annual Plan 2009-10
91397 | G895 | H2 | 2010 | 0% | 2010-04-01..2011-03-31 | 10205652-a7d7-4e64-b039-1fd4ce113c74.xls | State wise/Sector wise Approved Outlay, Revised Outlay and Expenditure for Annual Plan 2010-11
91398 | G896 | H3 | 2011 | 0% | 2011-04-01..2012-03-31 | c27df2f9-ad7f-4343-ab40-d61604ead86b.xls | State wise/Sector wise Approved Outlay, Revised Outlay and Expenditure for Annual Plan 2011-12

### Similar rows outside this collection (same ministry)

- nid 103247 (non-mergeable, no collection; free; score 90; window 2007; hdr 'States and UTs name,Agriculture and Allied Activities,Rural Development,Special Area Programmes,Irrigation and Flood Con'; file caafc553-a7a1-49db-9f8d-198223f6c1d8.csv) State plan outlay and expenditure sector-wise 2007-08
- nid 103248 (non-mergeable, no collection; free; score 90; window 2008; hdr 'State/Union Territory,Agriculture and Allied Activities,Rural Development,Special Area Programmes,Irrigation and Flood C'; file 3a96fb69-87f6-48f3-9869-dddfc40d1f67.csv) State plan outlay and expenditure sector-wise 2008-09
- nid 103250 (non-mergeable, no collection; free; score 90; window 2009; hdr 'State/Union Territory,Agriculture and Allied Activities,Rural Development,Special Area Programmes,Irrigation and Flood C'; file 88566a35-78b0-4572-b64d-278029a10c0a.csv) State plan outlay and expenditure sector-wise 2009-10
- nid 103258 (non-mergeable, no collection; free; score 90; window 2010; hdr 'State/UTs,Agriculture and Allied Activities,Rural Development,Special Area Programmes,Irrigation and flood Control,Energ'; file e051d256-413c-4960-8e48-0d7167c3249a.csv) State plan outlay and expenditure sector-wise 2010-11
- nid 103259 (non-mergeable, no collection; free; score 90; window 2011; hdr 'State/UTs,Agriculture and Allied Activities,Rural Development,Special Area Programmes,Irrigation and flood Control,Energ'; file b6a11529-51a7-46f3-8fc9-8ad5b2899fba.csv) State plan outlay and expenditure sector-wise- Revised Plan Outlay 2011-12
- nid 103260 (non-mergeable, no collection; free; score 90; window 2012; hdr 'State/UTs,Agriculture and Allied Activities,Rural Development,Special Area Programmes,Irrigation and flood Control,Energ'; file a5325c5b-f904-4427-b38a-b49feedf693e.csv) State plan outlay and expenditure sector-wise- Approved Plan Outlay 2012-13

---

## C19 · State-wise outlay and expenditure for the Eighth plan for power sector and comparison of outlay and expenditure in the power sector with all sectors

- ministry: NITI Aayog | members in scope: 5 | current mac: review
- detector: flags NAME_PINS_VALUE,MAC_REVIEW | min_header_match 0.9 | admin levels state | varying dims - | suggested mac - | header dims state
- varying title text: Eighth | Eleventh | Ninth | Seventh | Tenth
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=State-wise Outlay and Expenditure for Power Sector by Five Year Plan and Comparison with All Sectors | mac=plan | notes=Seventh to Eleventh plan tables mixed

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [4] 10 cols, year-labelled cols 0%: Category | State | Power SectorOutlay | Power SectorExpenditure | Power SectorExpenditure as % of outlay | All SectorsOutlay | All SectorsExpenditure | All SectorsExpenditure as % of outlay | Power Sector outlay as % of All Sectors outlay | Power Sector expenditure as % of All Sectors expenditure
- H2 [1] 10 cols, year-labelled cols 0%: Type | State | Power SectorOutlay | Power SectorExpenditure | Power SectorExpenditure as % of outlay | All SectorsOutlay | All SectorsExpenditure | All SectorsExpenditure as % of outlay | Power Sector outlay as % of All Sectors outlay | Power Sector expenditure as % of All Sectors expenditure
    match vs H1 0.90; only here: ['Type']; only in H1: ['category']

### Members

nid | group | header | window | yr-cols | period (data) | file | title
103021 | G897 | H1 | - | 0% | .. | 5591bd8f-dd9e-40ef-acbc-7df6c85ce8e6.csv | State-wise outlay and expenditure for the Eighth plan for power sector and comparison of outlay and expenditure in the power sector with all sectors
103025 | G898 | H1 | - | 0% | .. | 18e0acb4-358d-42d4-811d-95881963477c.csv | State-wise outlay and expenditure for the Eleventh plan for power sector and comparison of outlay and expenditure in the power sector with all sectors
103022 | G899 | H1 | - | 0% | .. | 4cff0e16-02e3-44ab-a1b5-71cd07c66f50.csv | State-wise outlay and expenditure for the Ninth plan for power sector and comparison of outlay and expenditure in the power sector with all sectors
103020 | G901 | H2 | - | 0% | .. | 81fdb52d-38ba-4412-a707-5fa1645df822.csv | State-wise outlay and expenditure for the Seventh plan for power sector and comparison of outlay and expenditure in the power sector with all sectors
103024 | G900 | H1 | - | 0% | .. | d12e89b4-4eb5-4f1c-93dc-479ceb59a31c.csv | State-wise outlay and expenditure for the Tenth plan for power sector and comparison of outlay and expenditure in the power sector with all sectors

### Similar rows outside this collection (same ministry)

- nid 103247 (non-mergeable, no collection; free; score 90; window 2007; hdr 'States and UTs name,Agriculture and Allied Activities,Rural Development,Special Area Programmes,Irrigation and Flood Con'; file caafc553-a7a1-49db-9f8d-198223f6c1d8.csv) State plan outlay and expenditure sector-wise 2007-08
- nid 103248 (non-mergeable, no collection; free; score 90; window 2008; hdr 'State/Union Territory,Agriculture and Allied Activities,Rural Development,Special Area Programmes,Irrigation and Flood C'; file 3a96fb69-87f6-48f3-9869-dddfc40d1f67.csv) State plan outlay and expenditure sector-wise 2008-09
- nid 103250 (non-mergeable, no collection; free; score 90; window 2009; hdr 'State/Union Territory,Agriculture and Allied Activities,Rural Development,Special Area Programmes,Irrigation and Flood C'; file 88566a35-78b0-4572-b64d-278029a10c0a.csv) State plan outlay and expenditure sector-wise 2009-10
- nid 103258 (non-mergeable, no collection; free; score 90; window 2010; hdr 'State/UTs,Agriculture and Allied Activities,Rural Development,Special Area Programmes,Irrigation and flood Control,Energ'; file e051d256-413c-4960-8e48-0d7167c3249a.csv) State plan outlay and expenditure sector-wise 2010-11

---

## C20 · State/UT-wise District Score

- ministry: Ministry of Education, Department of School Education and Literacy | members in scope: 6 | current mac: review
- detector: flags HEADER_IRRECONCILABLE,MAC_REVIEW | min_header_match 0.3 | admin levels state | varying dims year | suggested mac year | header dims state,district
- varying title text: 2018-19 | 2019-20 | 2020-21 | 2021-22 | 2022-23 | 2023-24
- prior proposal (Claude, NOT approved by the user; the rules override it): action=addcol | name=(unchanged) | mac=year | notes=category column labels restructured 2022-23; reconcilable

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [4] 10 cols, year-labelled cols 70%: State/UT | District | Grade | District Score 201819  Overall | District Score 201819  Category  1.Outcome 290 | District Score 201819  Category  2. ECT 90 | District Score 201819  Category  3. IFSE 51 | District Score 201819  Category  4.SSCP 35 | District Score 201819  Category  5. DL 50 | District Score 201819  Category  6. GP 84
- H2 [2] 10 cols, year-labelled cols 0%: State | District | Grade | Overall | Categories  1.Outcome 290 | Categories  2. ECT 90 | Categories  3. IFSE 51 | Categories  4. SSCP 35 | Categories  5. DL50 | Categories  6. GP84
    match vs H1 0.30; only here: ['Categories  2. ECT 90', 'Categories  4. SSCP 35', 'Categories  3. IFSE 51', 'Categories  5. DL50', 'Categories  1.Outcome 290', 'Categories  6. GP84', 'Overall', 'State']; only in H1: ['category district dl score', 'category district ect score', 'category district gp score', 'category district ifse score', 'category district outcome score', 'category district score sscp', 'district overall score', 'state ut']

### Members

nid | group | header | window | yr-cols | period (data) | file | title
7676802 | G902 | H1 | 2018 | 70% | 2018-04-01..2019-03-31 | 5f76d891-6861-4d68-9bed-0d1ddea28940.csv | State/UT-wise District Score during 2018-19
7676801 | G902 | H1 | 2019 | 70% | 2019-04-01..2020-03-31 | ef9e134e-16ca-4f37-9e5a-b26d5f5cef7e.csv | State/UT-wise District Score during 2019-20
7676800 | G902 | H1 | 2020 | 64% | 2020-04-01..2021-03-31 | 1b8e37f4-2ee8-48e6-b017-4ef27e3eb7ae.csv | State/UT-wise District Score during 2020-21
7676799 | G902 | H1 | 2021 | 64% | 2021-04-01..2022-03-31 | 82262974-8c41-4deb-8678-f7890095face.csv | State/UT-wise District Score during 2021-22
603868581 | G903 | H2 | 2022 | 0% | 2025-07-03..2025-07-03 | 1e163843-0420-48b6-bb48-8ce8e60269b9.xls | State/UT-wise District Score during 2022-23
603868593 | G903 | H2 | 2023 | 0% | 2025-07-03..2025-07-03 | 99e870fb-069c-4f40-a63f-ae0c2d99a6cb.xls | State/UT-wise District Score during 2023-24

---

## C21 · State/UT-wise Percentage of Schools having Functional Girls Toilets by Management

- ministry: Ministry of Education, Department of School Education and Literacy | members in scope: 6 | current mac: review
- detector: flags MAC_REVIEW | min_header_match  | admin levels state | varying dims year | suggested mac year | header dims state
- varying title text: State/UT-wise Percentage of Schools having Functional Girls Toilets by Management during 2022-23 | State/UT-wise Percentage of Schools having functional Girls Toilets by Management during 2021-22 | State/UTs-wise Percentage of Schools having Functional Boys Toilets by Management during 2023-24 | State/UTs-wise Percentage of Schools having Functional CWSN Friendly Toilets by Management during 2023-24 | State/UTs-wise Percentage of Schools having Functional Girls Toilets by Management during 2023-24 | State/UTs-wise Percentage of Schools having Functional Toilets by Management during 2023-24
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=State/UT-wise Percentage of Schools having Functional Toilets by Toilet Type and Management | mac=year,toilet_type | notes=girls, boys, CWSN and all toilets mixed

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [6] 10 cols, year-labelled cols 0%: India/ State/ UT | All Management | Government  Total | Government  KVS | Government  NVS | Government  Other Central Government | Government  State Government | Government Aided | Private Unaided Recognized | Others

### Members

nid | group | header | window | yr-cols | period (data) | file | title
7676768 | G905 | H1 | 2021 | 0% | 2021-04-01..2022-03-31 | 16bf10e5-0659-4e57-b968-65213c4b695d.csv | State/UT-wise Percentage of Schools having functional Girls Toilets by Management during 2021-22
603854678 | G904 | H1 | 2022 | 0% | 2022-04-01..2023-03-31 | 0ed024fa-fc55-4be6-9527-17f511d3c9ed.csv | State/UT-wise Percentage of Schools having Functional Girls Toilets by Management during 2022-23
603854564 | G906 | H1 | 2023 | 0% | 2023-04-01..2024-03-31 | db271316-c30b-4d61-95ac-75b2005d5fd7.csv | State/UTs-wise Percentage of Schools having Functional Boys Toilets by Management during 2023-24
603854565 | G907 | H1 | 2023 | 0% | 2023-04-01..2024-03-31 | 0ef6b708-8621-4b77-8a72-9ca81aeaf973.csv | State/UTs-wise Percentage of Schools having Functional CWSN Friendly Toilets by Management during 2023-24
603854563 | G908 | H1 | 2023 | 0% | 2023-04-01..2024-03-31 | a21f3799-f082-4e17-b548-6d86b261e081.csv | State/UTs-wise Percentage of Schools having Functional Girls Toilets by Management during 2023-24
603854562 | G909 | H1 | 2023 | 0% | 2023-04-01..2024-03-31 | fe5c58b5-b7a7-44e6-9245-46888f68d45a.csv | State/UTs-wise Percentage of Schools having Functional Toilets by Management during 2023-24

### Similar rows outside this collection (same ministry)

- nid 7676770 (non-mergeable, no collection; free; score 99.42196531791907; window 2021; hdr 'India/ State/ UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Government,G'; file 92bb0232-77f8-4c7b-9223-0ff2827277e6.csv) State/UT-wise Percentage of Schools having Functional CWSN Friendly Toilets by Management during 2021-22
- nid 603854680 (non-mergeable, no collection; free; score 99.42196531791907; window 2022; hdr 'Sl. No.,India/State/ UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Gover'; file 487f223d-63e5-43df-bc3a-a7fc42c748b4.csv) State/UT-wise Percentage of Schools having Functional CWSN Friendly Toilets by Management during 2022-23
- nid 7676769 (non-mergeable, no collection; free; score 99.35483870967742; window 2021; hdr 'India/ State/ UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Government,G'; file b6fa1157-b940-4793-96d4-6132993e79f4.csv) State/UT-wise Percentage of Schools having Functional Boys Toilets by Management during 2021-22
- nid 603854679 (non-mergeable, no collection; free; score 99.35483870967742; window 2022; hdr 'Sl. No.,India/State/UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Govern'; file ca81c48a-6883-42c6-a1b6-2feee8cee972.csv) State/UT-wise Percentage of Schools having Functional Boys Toilets by Management during 2022-23
- nid 7676767 (non-mergeable, no collection; free; score 99.3103448275862; window 2021; hdr 'India/ State/ UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Government,G'; file 40c05e9d-8191-4125-ae77-421ee125866a.csv) State/UT-wise Percentage of Schools having Functional Toilets by Management during 2021-22
- nid 603854677 (non-mergeable, no collection; free; score 99.3103448275862; window 2022; hdr 'Sl. No.,India/State/ UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Gover'; file f19fe86f-5e57-4ec6-ada9-73e27a423db4.csv) State/UT-wise Percentage of Schools having Functional Toilets by Management during 2022-23
- nid 603854561 (non-mergeable, no collection; free; score 92.0; window 2023; hdr 'Sl. No.,India/State/UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Govern'; file 1ea91238-b7a0-4956-9429-be75ee8d45ae.csv) State/UTs-wise Percentage of Schools having Functional Electricity by Management during 2023-24
- nid 7676766 (non-mergeable, no collection; free; score 91.2751677852349; window 2021; hdr 'India/ State/ UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Government,G'; file 4ad13b55-8881-4843-8b87-4007bad53c9e.csv) State/UT-wise Percentage of Schools having Functional Electricity by Management during 2021-22
- nid 603854676 (non-mergeable, no collection; free; score 91.2751677852349; window 2022; hdr 'Sl. No.,India/State/UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Govern'; file bdc3683b-1995-41e6-b213-9cdb91f47e9c.csv) State/UT-wise Percentage of Schools having Functional Electricity by Management during 2022-23
- nid 603854570 (non-mergeable, no collection; free; score 85.91549295774648; window 2023; hdr 'Sl. No.,India/State/UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Govern'; file 311e7886-7a9e-45c6-9a5a-6f3896ded2b9.csv) State/UTs-wise Percentage of Schools having Tinkering Labs by Management during 2023-24
- nid 603854569 (non-mergeable, no collection; free; score 85.71428571428572; window 2023; hdr 'Sl. No.,India/State/UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Govern'; file 2c52acc5-f51b-40f1-8dec-3f9216b5df1b.csv) State/UTs-wise Percentage of Schools having Solar Panels by Management during 2023-24
- nid 7676774 (non-mergeable, no collection; free; score 85.1063829787234; window 2021; hdr 'India/ State/ UT,All Management,Government  Total,Government  KVS,Government  NVS,Government  Other Central Government,G'; file d4fcc217-f4a4-4891-acc9-83814d25ed59.csv) State/UT-wise Percentage of Schools having Tinkering Labs by Management during 2021-22

---

## C22 · Surat Profession Tax EC Registration Data as on 31.12.2015 (schema 1)

- ministry: Ministry of Housing and Urban Affairs, Smart Cities Mission, Gujarat, Surat | members in scope: 9 | current mac: review
- detector: flags SCHEMA_N_SUFFIX,MAC_REVIEW,MAC_MISSING_DIM | min_header_match  | admin levels - | varying dims year | suggested mac year | header dims -
- varying title text: EC Registration Data as on 31.12.2015 | EC Registration Data as on 31.12.2016 | EC Registration Data as on 31.12.2017 | EC Registration Data as on 31.12.2018 | EC Registration Data as on 31.12.2019 | RC Registration Data as on 31.12.2015 | RC Registration Data as on 31.12.2017 | RC Registration Data as on 31.12.2018 | RC Registration Data as on 31.12.2019
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=Surat Profession Tax EC and RC Registration Data | mac=year,registration_type | notes=EC and RC registrations mixed

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [9] 5 cols, year-labelled cols 0%: City | SiteName | Usage Category | Usage Category Description | Count of Certificate

### Members

nid | group | header | window | yr-cols | period (data) | file | title
602909354 | G910 | H1 | 2015 | 0% | 2015-12-31..2015-12-31 | de63a55f-dcb9-4fcd-a3bb-16ae531dd3bb.csv | Surat Profession Tax EC Registration Data as on 31.12.2015
602909359 | G910 | H1 | 2016 | 0% | 2016-12-31..2016-12-31 | 7c4bef5a-a2bf-4e48-a2dd-1239b06cb046.csv | Surat Profession Tax EC Registration Data as on 31.12.2016
602909363 | G910 | H1 | 2017 | 0% | 2017-12-31..2017-12-31 | d313409d-f9a1-480f-b399-67774703d65a.csv | Surat Profession Tax EC Registration Data as on 31.12.2017
602909412 | G910 | H1 | 2018 | 0% | 2018-12-31..2018-12-31 | ec11d046-d993-4fa8-a47d-9012167a4f9d.csv | Surat Profession Tax EC Registration Data as on 31.12.2018
602919813 | G910 | H1 | 2019 | 0% | 2019-12-31..2019-12-31 | cfc3d21d-cb22-40bd-acaf-e36a74785acb.csv | Surat Profession Tax EC Registration Data as on 31.12.2019
602909376 | G911 | H1 | 2015 | 0% | 2015-12-31..2015-12-31 | fc471f95-69af-4e34-9b31-645ff623daf5.csv | Surat Profession Tax RC Registration Data as on 31.12.2015
602909381 | G911 | H1 | 2017 | 0% | 2017-12-31..2017-12-31 | 603a80f0-9b80-4cfc-8423-60a49b0f54ac.csv | Surat Profession Tax RC Registration Data as on 31.12.2017
602909416 | G911 | H1 | 2018 | 0% | 2018-12-31..2018-12-31 | 8fecd9c7-0ed3-45d8-8767-80e60366c17b.csv | Surat Profession Tax RC Registration Data as on 31.12.2018
602919814 | G911 | H1 | 2019 | 0% | 2019-12-31..2019-12-31 | 4cdede1c-7efd-46e7-8921-4aae1f02412e.csv | Surat Profession Tax RC Registration Data as on 31.12.2019

### Similar rows outside this collection (same ministry)

- nid 602909380 (non-mergeable, no collection; free; score 100.0; window 2016; hdr 'SiteName,Usage Category,Usage Category Description,Count Of Certificate'; file 237e0ef4-efe9-4bf5-a278-8efb144d6882.csv) Surat Profession Tax RC Registration Data as on 31.12.2016

---

## C23 · Teachers in position in primary schools in Rural & Urban areas

- ministry: Ministry of Education, Department of School Education and Literacy, National Council of Educational Research and Training (NCERT) | members in scope: 6 | current mac: review
- detector: flags NAME_PINS_VALUE,MAC_REVIEW | min_header_match  | admin levels - | varying dims - | suggested mac urban_rural | header dims state
- varying title text: primary schools in Rural & Urban areas | primary schools in Rural area | primary schools in Urban area | upper primary schools in Rural & Urban areas | upper primary schools in Rural area | upper primary schools in Urban area
- prior proposal (Claude, NOT approved by the user; the rules override it): action=rename+addcol | name=Teachers in Position in Primary and Upper Primary Schools by Area | mac=area,school_level

### Header variants (after reconciling spelling/case/units/S.No./years)

- H1 [6] 7 cols, year-labelled cols 0%: STATE/U.T. | Full Time Teachers  Male | Full Time Teachers  Female | Full Time Teachers  Total | Para/Contract Teachers  Male | Para/Contract Teachers  Female | Para/Contract Teachers  Total

### Members

nid | group | header | window | yr-cols | period (data) | file | title
238163 | G912 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | fecea335-766e-4e70-b702-99fe18317b85.csv | Teachers in position in primary schools in Rural & Urban areas as on 30th September 2009
238123 | G913 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 95493691-a02b-484b-8e46-0763031de6b4.csv | Teachers in position in primary schools in Rural area as on 30th September 2009
238143 | G914 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 169fccb4-449e-4af1-85de-0a59ad2196a0.csv | Teachers in position in primary schools in Urban area as on 30th September 2009
238223 | G915 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | b800eb59-7815-4e90-a880-c5ed9f00f5a2.csv | Teachers in position in upper primary schools in Rural & Urban areas as on 30th September 2009
238183 | G916 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 90ccd5cf-8262-4dda-9079-c2ac06781da0.csv | Teachers in position in upper primary schools in Rural area as on 30th September 2009
238203 | G917 | H1 | 2009 | 0% | 2009-09-30..2009-09-30 | 3ad652a3-df6d-45b4-82e3-dca8b2cd6172.csv | Teachers in position in upper primary schools in Urban area as on 30th September 2009

### Similar rows outside this collection (same ministry)

- collection [4] Teachers in position in schools, by area (curate; free); best score 90.38461538461539; e.g. 238263 Teachers in position in secondary schools in Urban area as on 30th September 2009
- nid 146131 (non-mergeable, no collection; free; score 90; window 2009; hdr 'Sl. No.,STATE/U.T.,Primary Schools According to Number of Teachers   0,Primary Schools According to Number of Teachers  '; file 0883ce39-13cf-4808-9397-15b6e375672e.csv) Primary schools according to number of teachers in position in urban area as on 30th September 2009
- nid 146129 (non-mergeable, no collection; free; score 90; window 2009; hdr 'Sl. No.,STATE/U.T.,Primary Schools According to Number of Teachers  0,Primary Schools According to Number of Teachers   '; file ed8638df-4c13-48d9-b404-115b6470fb9d.csv) Primary schools according to number of teachers in position in rural area as on 30th September 2009
- nid 146132 (non-mergeable, no collection; free; score 90; window 2009; hdr 'Sl. No.,STATE/U.T.,Primary Schools According to Number of Teachers   0,Primary Schools According to Number of Teachers  '; file a032e8c6-f02a-448a-b029-9afcfe659b26.csv) Primary schools according to number of teachers in position in rural and urban areas as on 30th September 2009
