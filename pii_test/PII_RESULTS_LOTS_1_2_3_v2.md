# Personal data in India's open government datasets: what the check found (v2)

Short version, written 2026-10-12 for readers who do not know the project. The full technical
report, with the source of every number, is `PII_RESULTS_LOTS_1_2_3.md` in the same folder.

No personal details are reproduced here. Only dataset titles and column headings are.

---

## 1. What this is

India's Open Government Data portal (data.gov.in) publishes several hundred thousand datasets
that anyone can download. Most are statistics. Some name people.

This report covers a check of 354,291 of those datasets for personal details: names, phone
numbers, email and home addresses, and identity numbers such as Aadhaar (the national identity
number) and PAN (the tax number). It also covers the call records of the Kisan Call Centre,
the government's farmer helpline ([section 8](#8-the-farmer-helpline-records)).

The question was: **which datasets expose the personal details of private people?**

---

## 2. The answer in brief

- **264,048 datasets were checked**, about three in four. Why the rest were not is in
  [section 9](#9-what-this-check-does-not-tell-you).
- An automatic scan flagged something in **12,182** of them.
- **59 hold personal details of private individuals.** Each needs a decision: withdraw it,
  edit the personal details out, or keep it.
- **638 hold details of people in a public role, or of offices and businesses.** This is
  normally acceptable to publish. 71 of them are borderline and need a decision.
- **11,487 were false alarms**: 94% of everything the scan flagged.
- **The farmer helpline records hold farmers' personal details in at least 408 files.** That
  check is not finished.
- **59 is a minimum.** The check removed false alarms. It did not search for datasets the
  scan missed.

---

## 3. How the check was done

The datasets were handled in three batches, called lots:

| Lot | What it is | Datasets | Checked |
|---|---|---|---|
| 1 | Ministry of Health and Family Welfare; mostly routine health statistics | 206,972 | 123,578 (59.7%) |
| 2 | 156 publishers, among them Parliament, the Census and city bodies under the Smart Cities Mission | 117,721 | 111,638 (94.8%) |
| 3 | 309 publishers, mostly state government departments, chiefly Tamil Nadu and Karnataka | 29,598 | 28,832 (97.4%) |
| All | | 354,291 | 264,048 |

The check had three steps:

1. **Automatic scan.** A program read the first 250 rows of each dataset and flagged every
   value that looked like a person's name, a phone number, an email address or an identity
   number.
2. **Automatic sorting.** Fixed rules and an AI model sorted each flagged column into one of
   the three groups below.
3. **Second reading.** The automatic sorting called far too many datasets personal. Of the
   468 it put in the first group, 58 belong there. So on 12 October 2026, all 852 datasets it
   had put in the first two groups in lots 2 and 3 were read again, one at a time: the title,
   the column headings, the flagged values, and the full table where that was not enough.
   This reading was done by the AI assistant working on the project. No second
   reviewer has checked it.

The three groups:

| Group | What it means | Label in the result files |
|---|---|---|
| Private individuals' data | People named as patients, victims, accused persons, scheme beneficiaries, owners or next of kin. Also a register that gives relatives' names, date of birth or community. | `present` |
| Public-role and office details | People named in a public, official or professional role: members of Parliament, officials, college principals, scientists, athletes, award winners, advocates on a public register. Also the contact details of offices, institutions and businesses. | `permissible` |
| False alarm | Not personal data. A place, scheme or disease name read as a person's name, or an ordinary number read as a phone number. | `false_positive` |

---

## 4. Results

| | Lot 1 | Lot 2 | Lot 3 | All |
|---|---|---|---|---|
| Datasets flagged by the scan | 3,917 | 5,878 | 2,387 | 12,182 |
| **Private individuals' data** | **0** | **32** | **27** | **59** |
| **Public-role and office details** | **8** | **330** | **300** | **638** |
| False alarms | 3,909 | 5,518 | 2,060 | 11,487 |

- Two lot 2 datasets were not flagged by the scan at all, because it could not read them. The
  second reading found them. That is why the three result lines add up to two more than the
  first line.
- Lot 1's result is the automatic sorting's own. It was not part of the second reading: the
  project owner closed lot 1 on 8 October 2026 as holding no private individuals' data.
- The scan flagged 305,565 individual values in all. 116,379 were kept; the other 189,186
  were false alarms.

---

## 5. The 59 datasets with private individuals' data

**The four most serious** are city datasets published under the Smart Cities Mission:

| Dataset title | What it holds |
|---|---|
| "Pimpri Chinchwad Municipal Corporation COVID 19 Admitted_API" | 100 COVID patients: name, address, age, mobile number and other health conditions |
| "TIRUPPUR Covid Patient as on 29/06/2020" | Named patients with age, ward and test result |
| "Cases of Child Missing : 2020 to 2021" (Tiruppur) | Missing children named with father's name, home address, mobile number and caste |
| "Traffic Accidents : 2020 to 2021" (Tiruppur) | Accident victims named with address, mobile number, caste and occupation |

**The other 55:**

| Group | Datasets | What they hold |
|---|---|---|
| Distress Relief Fund for Fishermen (Karnataka) | 16 | Fishermen paid relief for boat damage, and those who died |
| Tables attached to answers given in the Rajya Sabha (upper house of Parliament) | 13 | People accused in criminal cases; people occupying public land in Delhi; soldiers and paramilitary personnel who died, and their next of kin; workers who died in coal-mine accidents; a person killed in a police encounter; couples given a grant for inter-caste marriage; beneficiaries of a micro-finance scheme for minorities; sportspersons given welfare or medical help |
| 6th Minor Irrigation Census, by state | 13 | The owner's name for each irrigation scheme; names and mobile numbers of the survey's field staff |
| All India Advocate List: five rolls from three states | 5 | Beside each advocate's name and address: father's or husband's name, date of birth, community or phone number |
| Other lists of welfare-scheme beneficiaries | 5 | A fisheries scheme (2 datasets), funeral assistance, marriage assistance for differently abled women (Kollam, Kerala), an encouragement fund for Scheduled Caste and Scheduled Tribe students |
| Property records | 2 | "Building CC Permissions in Thane : 2021": owners' names beside the property address. "Property Details within Erode District in Tamil Nadu": mobile numbers beside property-tax numbers |
| "smart_sarth_registration_app" (Pimpri Chinchwad) | 1 | A registration survey of merchants: shop and owner names, 65 PAN numbers, mobile numbers |

32 of the 59 are in lot 2 and 27 in lot 3. None is in the large statistical series that make
up most of each lot. They are open-ended lists from city bodies, tables laid before
Parliament, and state departments' beneficiary lists.

---

## 6. The 638 datasets with public-role and office details

Almost all are directories and registers:

- **Parliament:** attendance registers and member lists of both houses; athletes, artists and
  award winners named in answers.
- **Officials and offices:** contact lists of electricity-board and transport officials,
  police stations, hospitals, helplines, depots and bank branches.
- **Institutions:** college principals, heads of higher-education institutions, scientists
  and faculty of research institutes.
- **Professional registers:** advocates and notaries.
- **Businesses:** hotels, tour operators, laboratories.

### The 71 that need a decision

These 71 are counted as public-role details, but the case can be argued either way. They are
marked in the result files as three sets, so each set can be moved as a whole:

| Set | Datasets | Why it is borderline |
|---|---|---|
| Directories of members of Parliament | 16 | Beside the member's own details they give the names of the member's father, mother and spouse, and home addresses |
| Registers of advocates and notaries | 40 | The people are on a public register, but the address listed may be a home address |
| Smaller lists: students and trainees (5), operators of public service centres with their own mobile numbers (6), volunteer animal rescuers, day-care workers, self-help group contacts, leaders of insurgent groups (4) | 15 | Individuals are named, some with mobile numbers, and they are not office holders |

If all 71 were counted as private individuals' data, the total would be 130, not 59.

Nine of the 16 member directories are published under a title that has nothing to do with
their content, such as a health report or tourism earnings. That is an upload error and
should be fixed whatever is decided.

---

## 7. Why 94% were false alarms

The scan cannot always tell a person's name from another kind of name, or a phone number from
another kind of number. Typical false alarms:

- **Lot 1:** names of health indicators. Three column headings account for 95% of the lot's
  flagged columns.
- **Lot 2:** village and town names in Census tables, crime categories, bus routes and railway
  stations, project names.
- **Lot 3:** names of crops, diseases and local bodies.
- **Lots 2 and 3:** money amounts, map coordinates and tender numbers read as phone or Aadhaar
  numbers. No Aadhaar number flagged in the three lots was a real one.

---

## 8. The farmer helpline records

The Kisan Call Centre records are a separate collection: 2,753 files, of which 1,890 hold
data, covering 2006 to 2026. Each row is one call, with the farmer's question and the agent's
answer.

- **What they hold.** From 2019 onwards, agents paste a farmer's record from the PM-KISAN
  income-support scheme into the answer: the farmer's name, father's name, registration
  number, village address, bank branch code and payment references. A few answers quote a
  full Aadhaar number.
- **How many.** A text search of every line found such records in at least 408 files, across
  31 states. The search only recognises records labelled in English, so the real number may be
  higher.
- **Status.** The scan has now read every row of every file (12.4 million rows). Its results
  have not been sorted into the three groups yet, so there is no final count per file and no
  list of rows to edit out.

---

## 9. What this check does not tell you

- **Nobody searched for misses.** Datasets the scan did not flag, or that the automatic
  sorting judged false alarms, were not read again. Two missed datasets were found by chance:
  both are stored in an encoded form the scan cannot read.
- **Names inside long text can be missed.** In the missing-children and traffic-accident
  datasets the scan caught the phone number but not the names beside it. A dataset like that
  with no phone number would not be flagged at all.
- **Only the first 250 rows of each dataset were read** in the three lots.
- **About 90,000 datasets were not checked.** In lot 1, 83,359 carry only an older check from
  May 2026, which found nothing and is not reliable. In lot 2, 6,039 can no longer be
  downloaded from the portal. The rest are mostly missing files and files that are not tables.
- **The check looks for names, contact details and identity numbers.** It does not judge
  whether individual-level survey records with no names in them are safe to publish.
- **The second reading is one reviewer's judgment**, made per dataset and per column, not per
  value.

---

## 10. What should happen next

1. **Decide what to do with the 59 datasets**: withdraw, edit out the personal details, or
   keep. Start with the four about patients, children and accident victims.
2. **Decide the 71 borderline datasets**, set by set, and fix the nine member directories
   published under the wrong title.
3. **Look for misses where the finds were**: other Smart Cities datasets with a free-text
   "name and address" column, and other files stored in encoded form.
4. **Finish the farmer helpline check**, so the rows to edit out are known.
5. **Improve the automatic sorting.** Its two commonest mistakes:
   - treating any mobile number as a private person's, when most belong to offices, depots,
     hotels and helplines;
   - treating a column headed "name" as people's names because the title suggests personal
     records, when it lists colleges, companies or diseases.

---

## 11. Where the detail is

- **Full technical report:** `pii_test/PII_RESULTS_LOTS_1_2_3.md`.
- **Spreadsheets:** `pii_test/results_excel/` has one workbook per group, listing every
  dataset and every flagged value. They contain real names and phone numbers and should not
  be passed on. They list 637 datasets in the second group where this report says 638,
  because one lot 3 dataset appears twice in the catalogue.
