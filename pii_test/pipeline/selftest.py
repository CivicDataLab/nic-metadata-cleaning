"""Self-tests for the rules in filters.py, classify.py and judge.py. No files written, no server.

    python pii_test/pipeline/selftest.py

These came from the old modules' own self-tests (pii_filters.py's __main__,
pii_classify.py --test, pii_tier3.py --test) and check the same cases.
"""

import sys


def testfilters():
    """Person, phone, Aadhaar, header, column and dataset-flag rules."""
    from filters import (CROSSCOUNTS, CROSSMAX, GAZETTEERS, SCOREFLOOR, columnfilter,
                         datasetflag, headerrule, incontext, keepperson, keepphone,
                         namelike, normalize, phonekind, regexmatches)

    # (entity_text, score, source, expected_kept, why)
    personcases = [
        # Hindi noise
        ("भाई", 0.85, "presidio", False, "Hindi address word, not a name"),
        ("बारिश", 0.85, "presidio", False, "means 'rain'"),
        ("निधि योजना", 0.85, "presidio", False, "scheme name fragment"),
        ("कि", 0.45, "presidio", False, "tokenization fragment"),
        ("रा", 0.52, "presidio", False, "fragment of 'Rahul' or similar"),
        ("RA", 0.47, "presidio", False, "English fragment, too short"),
        # KCC agricultural vocabulary
        ("Kisan Samman", 0.85, "presidio", False, "scheme name"),
        ("Nidhi Yojna", 0.85, "presidio", False, "scheme name"),
        ("Diesel Subsidy", 0.85, "presidio", False, "program name"),
        ("Pointed Gourd", 0.85, "presidio", False, "crop"),
        ("Cartap Hydrochloride", 0.85, "presidio", False, "chemical"),
        ("Pradhan Mantri Kisan Samman Nidhi", 0.9, "presidio", False,
         "compound scheme name, matched as a phrase"),
        # LOT 1 administrative areas: block and council names that NER reads
        # as PERSON because they are short capitalised phrases.
        ("Kharkutta Block", 0.85, "presidio", False, "block, not a person"),
        ("Ranikor Block", 0.85, "presidio", False, "block, not a person"),
        ("Urban Block", 0.85, "presidio", False, "block with a category word"),
        ("Vaseitlang MC", 0.85, "presidio", False, "municipal council"),
        ("Khagaria Sadar", 0.85, "presidio", True,
         "one-off block name is name-shaped; the dataset flag, not the "
         "detection, is what withholds it"),
        # The LOT 2 offenders the previous rewrite targeted
        ("Urban", 0.997, "presidio", False, "location category, 47% of LOT 2"),
        ("URBAN", 0.997, "presidio", False, "same, different case"),
        ("Rural", 0.99, "presidio", False, "location category"),
        ("M.Phil", 0.996, "presidio", False, "qualification"),
        ("MPhil", 0.996, "presidio", False, "same, no punctuation"),
        ("Ph.D", 0.676, "presidio", False, "qualification"),
        ("B.El", 0.85, "presidio", False, "qualification"),
        ("Kendriya Vidyalaya / Central School", 0.85, "presidio", False, "school scheme"),
        ("Jawahar Navodaya Vidyalaya", 0.85, "presidio", False, "school scheme"),
        ("KHIMYANG", 0.694, "presidio", False, "census block, via gazetteer"),
        ("RAJGARH", 0.85, "presidio", False, "district, via gazetteer"),
        ("JAISALMER", 0.85, "presidio", False, "district, via gazetteer"),
        # Organisations found in ambiguous "name" columns (LOT 2 re-run)
        ("Gujarat Vidyapith", 0.85, "presidio", False, "university"),
        ("Ramakrishna Mission", 0.85, "presidio", False, "organisation"),
        ("Sanskrit Vishwavidyalaya", 0.85, "presidio", False, "university"),
        ("Kalu Kanya Mahavidhyalya", 0.85, "presidio", False, "college"),
        ("Nidhi Hostel", 0.85, "presidio", False, "hostel, not a person"),
        ("Shri M. T. Doshi Kanya Chhatralaya", 0.85, "presidio", False,
         "hostel named after a person -- still a building"),
        ("SAMAJ WADI", 0.85, "presidio", False, "organisation"),
        # Round 2: the families the harvested gazetteers cover. Every one of
        # these was a whole-word false positive that no list matched before,
        # because the stored spans were subword fragments ("Robb", "lerks").
        ("Dacoity", 0.9, "presidio", False, "NCRB crime head"),
        ("Robbery", 0.9, "presidio", False, "NCRB crime head -- stored as 'Robb' before"),
        ("Arson", 0.9, "presidio", False, "NCRB crime head"),
        ("Clerks", 0.9, "presidio", False, "NCO occupation -- stored as 'lerks' before"),
        ("Stock Clerks", 0.9, "presidio", False, "NCO occupation"),
        ("BAJRA", 0.9, "presidio", False, "crop, largest single commodity FP"),
        ("PADDY", 0.9, "presidio", False, "crop"),
        ("POTTERY", 0.9, "presidio", False, "handicraft commodity"),
        ("Hindi", 0.9, "presidio", False, "language, from Mother Tongue Name"),
        ("Assamese", 0.9, "presidio", False, "language"),
        ("Hilsa Ilisha", 0.9, "presidio", False, "fish species"),
        ("JHUNJHUNUN", 0.9, "presidio", False,
         "district -- only reaches the gazetteer once un-fragmented"),
        # Round 2: score floor
        ("Some Person", SCOREFLOOR - 0.01, "presidio", False,
         "below the tuned score floor"),
        ("Some Person", SCOREFLOOR, "presidio", True, "exactly at the floor"),
        # True positives that must survive
        ("Rahul Kumar", 0.92, "presidio", True, "real English name"),
        ("Vidya Balan", 0.9, "presidio", True,
         "'vidya' is a personal name -- must not be an organisation token"),
        ("Gyan Prakash", 0.9, "presidio", True, "same for 'gyan'"),
        ("Shri Ram Sharma", 0.9, "presidio", True, "honorific, still a person"),
        ("राहुल कुमार", 0.88, "presidio", True, "real Hindi name"),
        ("Maurice Fernandes", 0.9, "presidio", True,
         "must not be rejected for containing the crop 'rice'"),
        ("Priya Sharma", 0.75, "presidio", True, "real name, moderate score"),
        ("M.A. RAFIQ AHMED", 0.9, "presidio", True,
         "initials, not the qualification 'M.A.' -- single-letter phrases "
         "must not match inside a name"),
        ("9876543210", 1.0, "regex", True, "phone via regex"),
        ("ABCDE1234F", 1.0, "regex", True, "PAN via regex"),
        ("Dacoity", 1.0, "regex", True, "regex source is exempt from every entity rule"),
    ]

    print(f"{'Entity':<38} {'Score':>6} {'Source':<10} {'Kept?':<6} {'Expected':<9} OK?")
    print("-" * 88)
    failures = 0
    for entity, score, source, expected, _why in personcases:
        kept = keepperson(entity, score, source)
        ok = kept == expected
        failures += not ok
        print(f"{entity:<38} {score:>6.2f} {source:<10} {str(kept):<6} {str(expected):<9} "
              f"{'yes' if ok else 'NO'}")

    # Phone-number length, from the "Schools having Functional Mobile
    # Phones ..." count columns that a force token pulls into the scan.
    print()
    lengthcases = [
        ("9866012345", True, "10-digit Indian mobile"),
        ("+91 98660 12345", True, "with country code"),
        ("169938", False, "school count, not a phone"),
        ("1644", False, "school count"),
        ("356819", False, "school count"),
    ]
    for text, expected, _why in lengthcases:
        kept = keepphone(text)
        ok = kept == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} phone {text!r:20} -> {kept} (expected {expected})")

    # Aadhaar: the shape regex alone accepts any 12-digit code, so the
    # Verhoeff check is what earns AADHAAR_NUMBER its place in
    # HIGHPRECISION. Exercised through regexmatches rather than
    # the validator directly, so the wiring is covered too.
    print()
    aadhaarcases = [
        ("234567890124", True, "valid check digit"),
        ("2345 6789 0124", True, "same number, printed in groups"),
        ("Aadhaar: 987654321096", True, "embedded in a sentence"),
        ("234512345678", False, "right shape, wrong check digit"),
        ("999999999999", False, "repeated-digit filler; passes Verhoeff, is a palindrome"),
        ("333333333333", False, "the other repdigit Verhoeff accepts"),
        ("202512345678", False, "year-prefixed serial, the common FP shape"),
        ("123456789012", False, "leading 1 -- never issued"),
        ("23456789012", False, "11 digits"),
    ]
    for text, expected, _why in aadhaarcases:
        found = any(label == "AADHAAR_NUMBER"
                    for label, *_ in regexmatches(text))
        ok = found == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} aadhaar {text!r:20} -> {found} "
              f"(expected {expected})")

    # Column classification: the negative-bigram rule and the split force
    # bypass.
    print()
    columncases = [
        ("Sub District Head Quarter (Name)", "skip", "census geography, 8,434 detections"),
        ("District Head Quarter (Name)", "skip", "census geography, 3,889 detections"),
        ("Head Quarters Name", "skip", "plural form of the same bigram"),
        ("Mother Tongue Name", "skip", "census language list, 2,005 detections"),
        ("MotherTongueName", "skip", "same header, camelCase"),
        ("mothertonguename", "skip", "same header, glued"),
        ("Name of Vice-Chancellor/ Director/ Principal/ Head", "force-person",
         "the genuine name column the person-token override exists for"),
        ("District_Officer_Name", "force-person",
         "'district' skip token overridden by 'officer'"),
        ("Mother Name", "force-person", "'mother' with no negative bigram"),
        ("Name of Head Master", "force-person", "'head' with no negative bigram"),
        ("Contact No", "force-pii", "int64 phone column must bypass the dtype checks"),
        ("E-mail id", "force-pii", "'id' must not skip it"),
        ("Village Name", "skip", "geography"),
    ]
    for column, expected, _why in columncases:
        decision, reason = headerrule(column)
        ok = decision == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} column {column!r:52} -> {decision} ({reason})")

    # Devanagari normalisation. Combining marks are not \w in Python's re, so
    # the old punctuation class shattered every matra into a space.
    print()
    scriptcases = [
        ("मनोहर प्रसाद सिंह", 3, True, "3-token Hindi name, was 7 fragments"),
        ("स्व. श्रीमती कॉर्नेलिया बाई साल्वे", 5, True,
         "stacked honorifics -- the case the token cap was widened to 5 for"),
        ("माध्यम", 1, False, "single Hindi word is not name-shaped"),
        ("G.L.Puram", 3, True, "initials still split on punctuation"),
        ("Dr. K.R. Menon", 4, True, "English honorific plus initials"),
    ]
    for text, tokens, shaped, _why in scriptcases:
        n = normalize(text)
        ok = len(n.split()) == tokens and namelike(text) == shaped
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} normalise {text!r:40} -> "
              f"{len(n.split())} token(s), shaped={namelike(text)}")

    # Numbering plan. 44 of the 58 phone numbers in the KCC sample are
    # helplines and ministry switchboards quoted inside advisory answers.
    print()
    phonecases = [
        ("7701234567", "mobile", True, "the genuine one in the KCC sample"),
        ("+91-8101234567", "mobile", True, "country code stripped"),
        ("99340 12345", "mobile", True, "printed with a space"),
        ("18001800110", "institutional", False, "Kisan Call Centre toll-free"),
        ("1800-1800-110", "institutional", False, "same number, hyphenated"),
        ("155261", "institutional", False, "PM-Kisan short code"),
        ("011-24300606", "landline", True, "Ministry of Agriculture -- kept, but demoted"),
        ("0612-2233555", "landline", True, "Bihar agriculture department"),
        ("5650012345", None, False, "10 digits opening 5 -- no such mobile series"),
        ("169938", None, False, "a school count, not a phone"),
    ]
    for text, kind, kept, _why in phonecases:
        got = phonekind(text)
        ok = got == kind and keepphone(text) == kept
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} phone {text!r:18} -> {str(got):14} "
              f"kept={keepphone(text)}")

    # Column-aware pass. These are the rules that need more than one detection
    # to decide, so each case is a whole column.
    print()
    def personcolumn(column, values):
        return [{"column": column, "entity_type": "PERSON", "entity_text": v,
                 "score": 0.85, "source": "presidio"} for v in values]

    contextcases = [
        ("QueryText", ["Farmer"] * 62 + ["Weather"] * 60
         + ["Rahul Kumar", "Amar Singh", "मनोहर प्रसाद सिंह"], 3,
         "boilerplate label repeated 60x is not 60 people"),
        ("Member Name",
         [f"Shri {first} {last}" for first in
          ("Amar", "Rahul", "Suresh", "Vijay", "Mohan", "Arun", "Kiran", "Deepak")
          for last in ("Kumar", "Singh", "Sharma", "Yadav", "Patel")], 40,
         "an all-distinct roster is untouched"),
        ("First Name", ["Alphonse", "Devi", "Chauhan", "Ghanshyam", "Dave",
                        "Indira", "Ramesh", "Sunita", "Kavita", "Mohan",
                        "Priya", "Rajesh", "Anita", "Vijay", "Suresh",
                        "Meena", "Arun", "Geeta", "Kiran", "Deepa",
                        "Nidhi"], 21,
         "mononym column keeps single tokens rather than emptying"),
        ("Notes", ["Rahul Kumar", "Farmer", "Amar Singh"], 2,
         "under 20 detections the share test is skipped, but shape still applies"),
        ("Notes", ["Rahul Kumar"] * 3 + ["Amar Singh"], 4,
         "a value repeated 3 of 4 times survives -- too few to judge a share"),
    ]
    # Where a PERSON span sits inside its cell, and whether its column is a
    # roster at all. Both taken from the KCC advisory export -- the cells are
    # the real ones, truncated only where length is not the point.
    print()
    kccanswer = (" जिन किसान का बैंक खाता एवं NPCI से नहीं जुड़ा है वैसे किसान "
                  "तुरंत पोस्ट ऑफिस जा कर खाता खुलवाएं |\n\nRegistration NO.\n"
                  "BR900000017\nName Of Farmer\nMOHAN VERMA\nAddress\n"
                  "Parasrampur\nFather/Spouse/Guardian Name:\nHARENDRA YADAV\n"
                  "Mobile No\n7701234567\n")
    querytext = "Query Related to Pradhan Mantri Kisan Samman Nidhi Yojna "
    advisory = ("किसान भाई  बैगन के फसल में तना और फल छेदक किट के नियंत्रण के लिए "
                "इमामेक्टिन बेंजोएट 5% SG 4 ग्राम प्रति 10 लीटर पानी में घोल बनाकर "
                "छिड़काव  करे| ")
    cellcases = [
        (kccanswer, "MOHAN VERMA", True,
         "0.8% of its cell, but introduced by 'Name Of Farmer'"),
        (kccanswer, "HARENDRA YADAV", True,
         "introduced by 'Father/Spouse/Guardian Name:'"),
        (" कटिहार, श्री मनोहर प्रसाद सिंह                      9430012345 ",
         "मनोहर प्रसाद सिंह", True, "introduced by the honorific श्री"),
        (querytext, "Samman", False, "a fragment of scheme boilerplate"),
        (querytext, "Query Related", False,
         "23% of the cell and nothing introduces it"),
        (advisory, "छिड़काव  करे|", False, "a fragment of a spraying instruction"),
        ("गेहूं की- डीबीडबल्यू 303 (करण वैष्णवी), करण नरेंद्र आदि किस्में बोयें",
         "करण नरेंद्र", False, "a wheat cultivar listed among cultivars"),
        ("Rahul Kumar", "Rahul Kumar", True, "the whole of a short cell"),
        ("Kumar, Rahul (Bihar)", "Rahul", True,
         "a short cell is a label, not prose -- no cue required"),
    ]
    for cell, entity, expected, why in cellcases:
        start = cell.index(entity)
        detection = {"column": "KccAns", "entity_type": "PERSON",
                     "entity_text": entity, "score": 0.85, "source": "presidio",
                     "cell_len": len(cell),
                     "left_context": cell[max(0, start - 64):start]}
        got = incontext(detection)
        ok = got == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} cell-context {entity[:22]!r:26} "
              f"-> {str(got):<5} ({why})")

    print()
    cardinalitycases = [
        ("Crop", ["French Bean", "Beet Root"], {"Crop": 0.09}, 0,
         "23 crop names over 250 rows is a vocabulary, not a roster"),
        ("Crop", ["French Bean", "Beet Root"], {}, 2,
         "an unmeasured column is not judged categorical"),
        ("Member Name", ["Rahul Kumar", "Amar Singh"], {"Member Name": 0.98}, 2,
         "an all-distinct roster is untouched"),
    ]
    for column, values, ratios, expected, why in cardinalitycases:
        kept = len(columnfilter(personcolumn(column, values), ratios))
        ok = kept == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} cardinality  {column!r:14} "
              f"{len(values)} -> {kept} (expected {expected}; {why})")

    print()
    for column, values, expected, _why in contextcases:
        kept = len(columnfilter(personcolumn(column, values)))
        ok = kept == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} column-context {column!r:14} "
              f"{len(values):>3} -> {kept:>3} (expected {expected})")

    # Dataset-level flag. The frequency map is injected per case so these stay
    # deterministic regardless of what the generated blocklist currently holds.
    print()
    flagcases = [
        ("regex hit alone flags",
         [{"entity_type": "PHONE_NUMBER", "column": "Contact", "entity_text": "9866012345",
           "source": "regex"}],
         {}, {}, True),
        ("PERSON in a name-like column flags",
         [{"entity_type": "PERSON", "column": "Father_Name", "entity_text": n,
           "source": "presidio"}
          for n in ("Rahul Kumar", "Priya Sharma", "Amit Verma")],
         {"Father_Name": 0.94}, {}, True),
        ("PERSON in a categorical column does not flag",
         [{"entity_type": "PERSON", "column": "Location", "entity_text": "Urban",
           "source": "presidio"}],
         {"Location": 0.03}, {}, False),
        ("PERSON in an unmeasured column does not flag alone",
         [{"entity_type": "PERSON", "column": "Mystery", "entity_text": "Rahul Kumar",
           "source": "presidio"}],
         {}, {}, False),
        ("wide-format vocabulary does not flag despite ratio 1.00",
         [{"entity_type": "PERSON", "column": "Crime Head", "entity_text": t,
           "source": "presidio"}
          for t in ("Extortion", "Kidnapping", "Rioting", "Cheating")],
         {"Crime Head": 1.00},
         {"extortion": 400, "kidnapping": 380, "rioting": 360, "cheating": 350},
         False),
        ("single-token village names do not flag despite ratio 1.00",
         [{"entity_type": "PERSON", "column": "VILLNAME", "entity_text": t,
           "source": "presidio"}
          for t in ("Gudari", "Papasi", "Bandika", "Pikusi")],
         {"VILLNAME": 1.00}, {}, False),
        ("a real roster still flags",
         [{"entity_type": "PERSON", "column": "Name of Awardee", "entity_text": t,
           "source": "presidio"}
          for t in ("Rahul Kumar", "Priya Sharma", "Dr. K.R. Menon", "Amit Verma")],
         {"Name of Awardee": 0.98}, {}, True),
        ("no detections", [], {}, {}, False),
        # Density: the one-off place names that defeat all three of the
        # earlier tests. Two names in a 250-row column is not a roster.
        ("sparse one-off place names do not flag",
         [{"entity_type": "PERSON", "column": "Indicator", "entity_text": t,
           "source": "presidio"}
          for t in ("Buxar Sadar", "Chowki Chowra")],
         {"Indicator": 1.00}, {}, False, 250),
        ("a dense roster still flags at the same row count",
         [{"entity_type": "PERSON", "column": "Name",
           "entity_text": f"Rahul {chr(97 + i // 26)}{chr(97 + i % 26)}sharma",
           "source": "presidio"} for i in range(40)],
         {"Name": 0.98}, {}, True, 250),
        ("a lone name-shaped value does not corroborate",
         [{"entity_type": "PERSON", "column": "Indicator",
           "entity_text": "Mipi Anini", "source": "presidio"}],
         {"Indicator": 1.00}, {}, False, 4),
        ("density is skipped when the row count is unknown",
         [{"entity_type": "PERSON", "column": "Indicator", "entity_text": t,
           "source": "presidio"}
          for t in ("Buxar Sadar", "Chowki Chowra")],
         {"Indicator": 1.00}, {}, True, None),
    ]
    for label, dets, card, frequencies, expected, *rest in flagcases:
        rows = rest[0] if rest else None
        saved = dict(CROSSCOUNTS)
        CROSSCOUNTS.update(frequencies)
        try:
            flagged, reason = datasetflag(dets, card, rows=rows)
        finally:
            CROSSCOUNTS.clear()
            CROSSCOUNTS.update(saved)
        ok = flagged == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} {label:<52} -> {flagged} ({reason})")

    print()
    total = (len(cellcases) + len(cardinalitycases)
             + len(personcases) + len(lengthcases) + len(aadhaarcases)
             + len(columncases) + len(scriptcases) + len(phonecases)
             + len(contextcases) + len(flagcases))
    print(f"{total - failures}/{total} passed, {failures} failed")
    for label, names in sorted(GAZETTEERS.items()):
        print(f"gazetteer {label:<12} {len(names):>6,} entries")
    print(f"cross-dataset counts   {len(CROSSCOUNTS):>6,} values "
          f"({sum(1 for c in CROSSCOUNTS.values() if c > CROSSMAX):,} "
          f"above CROSSMAX={CROSSMAX})")
    print(f"SCOREFLOOR     {SCOREFLOOR}")
    return failures


def testclassify():
    """Tier 1: dataset context, the rule cascade, loading a scan, the roll-up."""
    import json
    import os
    import tempfile

    from classify import (CLASSES, CSVLOT, PRESENTRULES, classify, classifypair,
                          datasetcontext, dialled, emailclass, features, headertokens,
                          load, rollup, schemacontext, siblingheaders, withcontext)
    from filters import normalize

    def feat(column, values, types=("PERSON",), cardinality=None,
              frequency=1, siblings=()):
        detections = [{"uuid": "u", "lot": 1, "column": column,
                       "entity_type": types[i % len(types)],
                       "entity_text": v, "score": 0.85, "source": "presidio",
                       "cardinality": cardinality}
                      for i, v in enumerate(values)]
        index = {normalize(v): frequency for v in values}
        return features(detections, index, siblings)

    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    # -- datasetcontext ---------------------------------------------------
    check("ctx directory",
          datasetcontext("Former Members of Rajya Sabha")[0],
          "official_directory")
    check("ctx nodal",
          datasetcontext("List of Nodal Officers under RTI Act")[0],
          "official_directory")
    check("ctx survey",
          datasetcontext("Annual Health Survey - Woman Schedule")[0],
          "individual_records")
    check("ctx aggregate",
          datasetcontext("Performance of Key HMIS Indicators for Dibang "
                          "Valley")[0],
          "aggregate_statistics")
    check("ctx both prefers individual",
          datasetcontext("Directory of Beneficiaries under the scholarship "
                          "scheme")[0],
          "individual_records")
    check("ctx empty", datasetcontext(None)[0], "unknown")

    # -- header tokens -----------------------------------------------------
    check("glued father", "father" in headertokens("fathername"), True)
    check("camel case", "enterprise" in headertokens("EnterpriseName"), True)
    check("short glued not substring-matched",
          "mp" in headertokens("employment"), False)

    # -- Q1: controlled vocabularies ---------------------------------------
    crime = feat("Crime Head", ["Murder", "Dacoity", "Theft"], frequency=288)
    check("crime head is FP",
          classifypair(crime, "aggregate_statistics")["pii_class"],
          "false_positive")

    indicator = feat("Indicator",
                      ["Number of pregnant women registered for ANC",
                       "Number of children fully immunised"], frequency=1500)
    check("HMIS indicator is FP",
          classifypair(indicator, "aggregate_statistics")["pii_class"],
          "false_positive")

    commodity = feat("Agricultural Commodities (First)",
                      ["PADDY", "BARLEY", "MUSTARD"], frequency=190)
    check("commodity is FP",
          classifypair(commodity, "aggregate_statistics")["pii_class"],
          "false_positive")

    tongue = feat("Mother Tongue Name", ["Hindi", "Bhojpuri"], frequency=18)
    check("mother tongue is FP (skip header beats 'mother')",
          classifypair(tongue, "aggregate_statistics")["rule_id"],
          "R1-skip-header")

    hq = feat("Sub District Head Quarter (Name)",
               ["Chhatarpur", "Bijawar"], frequency=162)
    check("head quarter is FP",
          classifypair(hq, "aggregate_statistics")["pii_class"],
          "false_positive")

    # A numbering-plan miss: an aggregate read as a phone number. "1800..."
    # satisfies the toll-free prefix test, so only the absence of any phone
    # formatting separates it from a real helpline.
    volume = feat("Aggregate Evapotranspiration Volume",
                   ["1800234567890"], types=("PHONE_NUMBER",))
    check("evapotranspiration volume is FP, not a helpline",
          classifypair(volume, "aggregate_statistics")["rule_id"],
          "R3-not-a-number")
    check("dialled-number test rejects a bare digit run",
          dialled("1800234567890"), False)
    check("dialled-number test accepts a formatted toll-free number",
          dialled("1800-180-1551"), True)

    # -- Q2: permissible ---------------------------------------------------
    member = feat("Member Name",
                   ["H.K. Javare Gowda", "Janeshwar Mishra", "M.J. Varkey"],
                   cardinality=0.98)
    check("MP name in directory is permissible",
          classifypair(member, "official_directory")["pii_class"],
          "permissible")

    father = feat("Father Name",
                   ["Shri Gopalan Pillai", "Ramdin Bhagat", "Shri Umashanker"],
                   cardinality=0.97)
    check("MP's father in a directory is permissible",
          classifypair(father, "official_directory")["rule_id"],
          "R7-directory-context")
    check("same header in a survey is present",
          classifypair(father, "individual_records")["pii_class"],
          "present")

    vc = feat("Name of Vice-Chancellor/ Director/ Principal/ Head",
               ["Anil Sahasrabudhe", "R. Subrahmanyam"], cardinality=1.0)
    check("vice-chancellor is permissible without directory context",
          classifypair(vc, "unknown")["pii_class"], "permissible")

    helpline = feat("Contact Details", ["1800-180-1551", "011-24300606"],
                     types=("PHONE_NUMBER",))
    check("helpline is permissible",
          classifypair(helpline, "unknown")["rule_id"],
          "R4-institutional-channel")

    gov_email = feat("Email ID", ["okazmi@sansad.nic.in", "cs@gov.in"],
                      types=("EMAIL_ADDRESS",))
    check("gov email is permissible",
          classifypair(gov_email, "unknown")["pii_class"], "permissible")

    # -- Q2: present -------------------------------------------------------
    beneficiary = feat("Beneficiary Name", ["Rahul Kumar", "Sita Devi"],
                        cardinality=0.99)
    check("beneficiary overrides directory context",
          classifypair(beneficiary, "official_directory")["pii_class"],
          "present")

    mother = feat("Mother Name", ["Shanti Devi", "Kamla Devi"],
                   cardinality=0.96)
    check("mother name in a survey is present",
          classifypair(mother, "individual_records")["pii_class"], "present")

    mobile = feat("KccAns", ["7701234567"], types=("PHONE_NUMBER",))
    check("subscriber mobile in free text is present",
          classifypair(mobile, "unknown")["rule_id"], "R11-personal-channel")

    consumer_email = feat("KccAns", ["dbtcellagri@gmail.com"],
                           types=("EMAIL_ADDRESS",))
    check("consumer email is present",
          classifypair(consumer_email, "unknown")["pii_class"], "present")

    # -- residual ----------------------------------------------------------
    enterprise = feat("EnterpriseName", ["Jay Mataji", "Ranjit Diamond"],
                       cardinality=0.98)
    got = classifypair(enterprise, "unknown")
    check("MSME enterprise name lands on a controlled-vocab or residual rule",
          got["rule_id"] in ("R1-controlled-vocab", "R12-residual"), True)

    # -- regressions -------------------------------------------------------
    # A republished directory: the same members appear in six near-duplicate
    # datasets, so corpus frequency is 6. Frequency alone must not reject a
    # column that is entirely name-shaped and almost entirely distinct.
    republished = feat("Member Name",
                        ["H.K. Javare Gowda", "Janeshwar Mishra",
                         "M.J. Varkey"], cardinality=1.0, frequency=6)
    check("a six-times-republished member list is not rejected on frequency",
          classifypair(republished, "official_directory")["pii_class"],
          "permissible")

    # A genuine controlled vocabulary at high frequency and mediocre shape.
    scheme = feat("healthscheme_1", ["RSBY card", "State scheme", "None"],
                   cardinality=1.0, frequency=22)
    check("a high-frequency scheme list is still rejected",
          classifypair(scheme, "individual_records")["pii_class"],
          "false_positive")

    # Dataset context must not convict a column that is not about people.
    monument = feat("Name of the Monument", ["Taj Mahal", "Red Fort"],
                     cardinality=1.0)
    check("a monument list in an individual-records dataset is not present",
          classifypair(monument, "individual_records")["pii_class"],
          "undecided")
    depth = feat("Depth range (m)", ["Ten Twenty"], cardinality=1.0)
    check("a measurement column is not present",
          classifypair(depth, "individual_records")["pii_class"], "undecided")

    # Schema-derived context, for the six datasets whose catalogue title
    # describes a different file than the one that was scanned.
    sansad_headers = ["Member Name", "Father Name", "Spouse Name",
                      "Position(s) Held", "Books Published",
                      "Other Profession(s)"]
    check("member-biography schema is recognised as a directory",
          schemacontext(sansad_headers)[0], "official_directory")
    check("an HMIS schema is not",
          schemacontext(["Indicator", "District", "Value"])[0], None)
    check("schema context rescues the mistitled directory",
          classifypair(
              feat("Father Name", ["Shri Gopalan Pillai", "Ramdin Bhagat"],
                    cardinality=1.0, frequency=6),
              *schemacontext(sansad_headers))["pii_class"],
          "permissible")

    # -- R6, the office-holder allow-list ----------------------------------
    # Driven through the feature dict rather than the real gazetteer, so the
    # rule is tested whether or not the list has been built on this machine.
    roster = feat("Name", ["Kapil Sibal", "Amar Singh", "Ahmed Patel",
                            "Anand Sharma"], cardinality=1.0)
    roster["office_holder_matches"] = 4
    roster["office_holder_match_rate"] = 1.0
    check("a column of known office holders is permissible",
          classifypair(roster, "unknown")["rule_id"], "R6-office-allowlist")

    stray = dict(roster)
    stray["office_holder_matches"] = 1
    stray["office_holder_match_rate"] = 0.25
    check("one office holder among private names decides nothing",
          classifypair(stray, "unknown")["rule_id"] == "R6-office-allowlist",
          False)

    beneficiaries = feat("Beneficiary Name", ["Kapil Sibal", "Amar Singh",
                                               "Ahmed Patel"], cardinality=1.0)
    beneficiaries["office_holder_matches"] = 3
    beneficiaries["office_holder_match_rate"] = 1.0
    check("a beneficiary column is present even if every name matches",
          classifypair(beneficiaries, "unknown")["pii_class"], "present")

    # -- invariants --------------------------------------------------------
    check("PRESENTRULES is accurate",
          set(PRESENTRULES),
          {"R5-private-absolute", "R9-private-contextual",
           "R10-individual-records", "R11-personal-channel"})

    for name in CLASSES:
        check(f"{name} is a known class", name in CLASSES, True)

    # -- email domain classes ---------------------------------------------
    check("mixed domains", emailclass(
        ["a@nic.in", "b@gmail.com"]), "mixed")
    check("no emails", emailclass(["not an email"]), None)

    # -- --csv input -------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        def write(rel, text):
            path = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            return path
        # Folder-run output: same file name in two folders.
        write("pii-present/2023_Q4.csv", "State,KccAns,Crop\nX,y,z\n")
        write("pii-present/pii_detections.csv",
              "file,column,row_index,entity_type,entity_text,score,source\n"
              "2023_Q4.csv,KccAns,3,PHONE_NUMBER,9876543210,1.0,regex\n"
              "2023_Q4.csv,KccAns,4,PERSON,Ramesh Kumar,0.85,presidio\n")
        write("other/pii_detections.csv",
              "file,column,row_index,entity_type,entity_text,score,source\n"
              "2023_Q4.csv,Name,1,PERSON,Sunita Devi,,presidio\n")
        # Single-file-run output: stem in uuid, no file column.
        write("single/msme - assam.csv", "Enterprise Name\nA\n")
        write("single/msme - assam_pii_detections.csv",
              "uuid,column,row_index,entity_type,entity_text,score,source\n"
              "msme - assam,Enterprise Name,0,PERSON,Asha Traders,0.85,presidio\n")
        rid = "3b1f0c2a-9d4e-4f1b-8a2c-5e6d7f8a9b0c"
        write(f"ids/pii_detections.csv",
              "file,column,row_index,entity_type,entity_text,score,source\n"
              f"{rid}.csv,Name,0,PERSON,Ravi Shankar,0.85,presidio\n")
        summary = write("summary.csv", "file,label,pii_found\na.csv,x,True\n")

        dets, meta = load([tmp])
        uuids = sorted(meta)
        check("csv: one dataset per scanned file", uuids,
              [f"ids/{rid}.csv", "other/2023_Q4.csv", "pii-present/2023_Q4.csv",
               "single/msme - assam.csv"])
        check("csv: a descriptive file name is the title",
              meta["single/msme - assam.csv"]["title"], "msme - assam")
        check("csv: a UUID-named file gives no title",
              meta[f"ids/{rid}.csv"]["title"], None)
        check("csv: lot is the CSV lot", {d["lot"] for d in dets}, {CSVLOT})
        check("csv: title is the file, not the label folder",
              meta["pii-present/2023_Q4.csv"]["title"], "2023_Q4")
        check("csv: header row read from the source file",
              meta["pii-present/2023_Q4.csv"]["headers"],
              ["State", "KccAns", "Crop"])
        check("csv: single-file run recovers the extension",
              meta["single/msme - assam.csv"]["headers"], ["Enterprise Name"])
        check("csv: missing source file has no headers",
              meta["other/2023_Q4.csv"]["headers"], None)
        check("csv: blank score reads as None",
              [d["score"] for d in dets if d["uuid"] == "other/2023_Q4.csv"], [None])
        check("csv: a single detections file resolves too",
              sorted(load([os.path.join(tmp, "other", "pii_detections.csv")])[1]),
              ["2023_Q4.csv"])
        try:
            load([summary])
            check("csv: a summary file is rejected", "accepted", "ValueError")
        except ValueError as exc:
            check("csv: a summary file is rejected", "--summary-out" in str(exc), True)

        rows = withcontext(classify(dets, meta), meta)
        check("csv: classifies every (file, column)", len(rows), 4)
        sib = siblingheaders(dets, meta)
        check("csv: real header row joins the detected columns",
              sib["pii-present/2023_Q4.csv"], {"State", "KccAns", "Crop"})
        check("csv: no header row keeps the detected columns",
              sib["other/2023_Q4.csv"], {"Name"})
        check("db: no metadata keeps the detected columns",
              siblingheaders(dets)["pii-present/2023_Q4.csv"], {"KccAns"})
        check("csv: carries header row for Tier 3",
              json.loads(next(r["file_headers"] for r in rows
                              if r["uuid"] == "pii-present/2023_Q4.csv")),
              ["State", "KccAns", "Crop"])

    # -- dataset roll-up ---------------------------------------------------
    def crow(uuid, cls, n=1):
        return {"uuid": uuid, "lot": 0, "pii_class": cls, "n_detections": n,
                "rule_id": "R", "dataset_context": "unknown"}
    rolled = {r["uuid"]: r for r in rollup([
        crow("a", "undecided"), crow("a", "present", "2"),
        crow("b", "false_positive"), crow("b", "undecided"),
        crow("c", "false_positive"), crow("c", "permissible")])}
    check("rollup: present beats undecided", rolled["a"]["pii_class"], "present")
    check("rollup: undecided beats false_positive", rolled["b"]["pii_class"], "undecided")
    check("rollup: permissible beats false_positive", rolled["c"]["pii_class"], "permissible")
    check("rollup: sums detections read back from CSV", rolled["a"]["n_detections"], 3)

    if failures:
        print(f"classify: FAILED {len(failures)} check(s):")
        for f in failures:
            print("  -", f)
    else:
        print("classify: all self-tests passed")
    return len(failures)


def testjudge():
    """Tier 3: parsing replies, the prompt, the judge loop, grouping, applying verdicts."""
    import csv
    import json
    import os
    import tempfile
    import urllib.error

    from classify import writecsv
    from judge import ServerGaveUp, apply, expand, group, judge, parse, prompt, topairs, torows

    def promptpair():
        return {"uuid": "u1", "lot": 2, "column": "Beneficiary Name",
                "entity_types": "PERSON", "n_detections": 1, "n_distinct": 1,
                "title": "t", "headers": [], "evidence": {"sample_values": ["x"]}}

    failures = []

    def check(name, condition):
        if not condition:
            failures.append(name)
            print(f"FAIL {name}")
        else:
            print(f"ok   {name}")

    verdict, _ = parse("blah blah\nCLASS: present")
    check("parses a well-formed verdict", verdict == "present")

    verdict, trace = parse(
        "<think>maybe permissible, no</think>\nCLASS: false_positive")
    check("ignores a class named inside the think block",
          verdict == "false_positive")
    check("keeps the reasoning trace", "maybe permissible" in trace)

    verdict, _ = parse("CLASS: present\nActually CLASS: permissible")
    check("takes the last marker", verdict == "permissible")

    verdict, _ = parse("I think this is present, clearly.")
    check("accepts one unambiguous bare class", verdict == "present")

    verdict, _ = parse("could be permissible or present, unsure")
    check("refuses an ambiguous bare reply", verdict is None)

    verdict, trace = parse("<think>weighing it up, maybe permis")
    check("a truncated think block is not a verdict", verdict is None)
    check("a truncated reply keeps its trace", "weighing it up" in trace)

    truncated_run = judge([promptpair()] * 5,
                          lambda _m: "<think>still thinking",
                          retries=0, maxerrors=3)
    check("truncation does not trip the circuit breaker",
          len(truncated_run) == 5)
    check("truncation is labelled distinctly",
          "truncated" in truncated_run[0]["error"])

    verdict, _ = parse("CLASS: pii_present")
    check("refuses a class outside the vocabulary", verdict is None)

    check("refuses an empty reply", parse("")[0] is None)

    pair = {
        "uuid": "u1", "lot": 2, "column": "Beneficiary Name",
        "entity_types": "PERSON", "n_detections": 40, "n_distinct": 38,
        "title": "PMAY-G Beneficiaries", "catalog_title": "Rural Housing",
        "description": "Sanctioned beneficiaries.", "ministry": "Rural Development",
        "sector": None,
        "headers": ["Beneficiary Name", "Age", "Village"],
        "evidence": {"sample_values": ["Ramesh Kumar", "Sunita Devi"],
                     "name_shaped_fraction": 0.91, "cardinality": 0.94,
                     "sibling_quasi_identifiers": ["age", "village"]},
    }
    message = prompt(pair)
    check("prompt carries the title", "PMAY-G Beneficiaries" in message)
    check("prompt carries the header row", "Age, Village" in message)
    check("prompt carries sample values", "Ramesh Kumar" in message)
    check("prompt omits corpus statistics",
          "cardinality" not in message.lower() and "0.91" not in message)
    check("prompt omits empty fields", "Description:" in message
          and "Ministry" not in message)

    lone = dict(pair, headers=["Beneficiary Name"])
    check("a header row of just the flagged column is dropped",
          "File header row" not in prompt(lone))

    long_pair = dict(pair, headers=[f"col{i}" for i in range(60)])
    check("header list is capped",
          "(+30 more)" in prompt(long_pair))

    results = judge([pair], lambda _m: "CLASS: present")
    check("judge returns the verdict", results[0]["verdict"] == "present")

    results = judge([pair], lambda _m: "no idea at all")
    check("unparseable reply leaves it undecided", results[0]["verdict"] is None)
    rows = torows(results)
    check("undecided row keeps the Tier 1 rule",
          rows[0]["pii_class"] == "undecided" and rows[0]["tier"] == "rule")

    calls = []

    def flaky(message):
        calls.append(message)
        return "garbage" if len(calls) == 1 else "CLASS: permissible"

    results = judge([pair], flaky)
    check("retries once on a bad reply", results[0]["verdict"] == "permissible")

    def boom(_message):
        raise urllib.error.URLError("connection refused")

    results = judge([pair], boom)
    check("a dead server leaves it undecided", results[0]["verdict"] is None)
    check("a dead server records the error", "URLError" in results[0]["error"])

    def always_dead(_message):
        raise urllib.error.URLError("connection refused")

    try:
        judge([pair] * 10, always_dead, retries=0, maxerrors=3)
        check("circuit breaker trips on a dead server", False)
    except ServerGaveUp as exc:
        check("circuit breaker trips on a dead server", "pair 3/10" in str(exc))

    garbage_run = judge([pair] * 5, lambda _m: "no idea", retries=0,
                        maxerrors=3)
    check("unparseable replies do not trip the breaker", len(garbage_run) == 5)

    rows = torows(judge([pair], lambda _m: "CLASS: false_positive"))
    row = rows[0]
    check("decided row is marked llm",
          row["tier"] == "llm" and row["rule_id"] == "T3-judge")
    evidence = json.loads(row["evidence_json"])
    check("evidence keeps the Tier 1 rule id", "tier1_rule_id" in evidence)
    check("evidence keeps the reasoning", "llm_reasoning" in evidence)
    check("sample values survive the round trip",
          evidence["sample_values"] == ["Ramesh Kumar", "Sunita Devi"])

    # --csv: Tier 1 rows as read back from pii_classify's --out CSV.
    tier1 = [
        {"uuid": "KERALA/2023_Q4.csv", "lot": "0", "column": "KccAns",
         "entity_types": "PERSON", "n_detections": "4", "n_distinct": "4",
         "pii_class": "undecided", "rule_id": "R12-residual",
         "evidence_json": json.dumps({"sample_values": ["Ramesh Kumar"]}),
         "title": "2023_Q4", "file_headers": json.dumps(["StateName", "KccAns"])},
        {"uuid": "KERALA/2023_Q4.csv", "lot": "0", "column": "Crop",
         "entity_types": "PERSON", "n_detections": "2", "n_distinct": "2",
         "pii_class": "false_positive", "rule_id": "R01",
         "evidence_json": "{}", "title": "2023_Q4", "file_headers": ""},
        {"uuid": "PUNJAB/2022_Q2.csv", "lot": "0", "column": "QueryText",
         "entity_types": "PERSON", "n_detections": "1", "n_distinct": "1",
         "pii_class": "undecided", "rule_id": "R12-residual",
         "evidence_json": "{}", "title": "2022_Q2", "file_headers": ""},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "tier1.csv")
        writecsv(path, tier1)
        with open(path, newline="", encoding="utf-8") as handle:
            csv_pairs = topairs(list(csv.DictReader(handle)))
    check("csv: only undecided rows become pairs", len(csv_pairs) == 2)
    check("csv: evidence JSON is decoded",
          csv_pairs[0]["evidence"]["sample_values"] == ["Ramesh Kumar"])
    check("csv: the file's header row is used",
          csv_pairs[0]["headers"] == ["StateName", "KccAns"]
          and csv_pairs[0]["headers_source"] == "file")
    check("csv: no header row falls back to detected columns",
          csv_pairs[1]["headers"] == ["QueryText"]
          and csv_pairs[1]["headers_source"] == "detected_columns")
    check("csv: the file name reaches the prompt",
          "Dataset title: 2023_Q4" in prompt(csv_pairs[0]))
    check("csv: --limit applies", len(topairs(tier1, limit=1)) == 1)

    verdicts = torows(judge(csv_pairs,
                             lambda m: "CLASS: present" if "2023_Q4" in m else "unsure"))
    final = apply(tier1, verdicts)
    check("csv: a verdict replaces the undecided class",
          final[0]["pii_class"] == "present" and final[0]["tier"] == "llm")
    check("csv: rule-decided rows are untouched", final[1] == tier1[1])
    check("csv: an unparseable reply stays undecided with the reason",
          final[2]["pii_class"] == "undecided"
          and "could not decide" in final[2]["reason"])
    def member(uuid, column, samples, headers=("StateName", "KccAns")):
        return {"uuid": uuid, "lot": "0", "column": column,
                "entity_types": "PERSON", "n_detections": str(len(samples)),
                "rule_id": "R12-residual", "title": uuid.rsplit("/", 1)[-1][:-4],
                "evidence": {"sample_values": samples},
                "headers": list(headers), "headers_source": "file"}
    grouped = group([
        member("KERALA/2023_Q4.csv", "KccAns", ["A", "B", "C"]),
        member("KERALA/2023_Q3.csv", "KccAns", ["B", "D"]),
        member("KERALA/2023_Q2.csv", "KccAns", ["E"], headers=("Other",)),
        member("PUNJAB/2023_Q4.csv", "KccAns", ["F"]),
        member("KERALA/2023_Q4.csv", "QueryText", ["G"]),
    ])
    by_key = {(g["group"], g["column"], len(g["members"])): g for g in grouped}
    check("group: same folder, column and headers merge",
          ("KERALA", "KccAns", 2) in by_key and len(grouped) == 4)
    check("group: a different header row stays separate",
          sum(1 for g in grouped if g["group"] == "KERALA" and g["column"] == "KccAns") == 2)
    kerala = by_key[("KERALA", "KccAns", 2)]
    check("group: samples round-robin across files, deduplicated",
          kerala["evidence"]["sample_values"] == ["A", "B", "C", "D"])
    check("group: detections are summed", kerala["n_detections"] == 5)
    check("group: per-file titles are dropped", kerala["title"] is None)
    check("group: the folder name never reaches the prompt",
          "KERALA" not in prompt(kerala))
    expanded = expand(judge([kerala], lambda _m: "CLASS: present"))
    check("group: every member gets the verdict",
          [r["verdict"] for r in expanded] == ["present", "present"]
          and {r["uuid"] for r in expanded} == {"KERALA/2023_Q4.csv", "KERALA/2023_Q3.csv"})
    check("group: members keep their own evidence",
          expanded[1]["evidence"]["sample_values"] == ["B", "D"]
          and "2 files" in expanded[1]["evidence"]["tier3_group"])
    check("group: expanded rows shape for the table",
          len(torows(expanded)) == 2)

    check("csv: integer and string lots still match",
          apply([dict(tier1[0], lot=0)], verdicts)[0]["tier"] == "llm")

    print()
    if failures:
        print(f"judge: {len(failures)} FAILED: {', '.join(failures)}")
    else:
        print("judge: all tests passed")
    return len(failures)


if __name__ == "__main__":
    failed = testfilters() + testclassify() + testjudge()
    print("\nall self-tests passed" if not failed else f"\n{failed} self-test(s) failed")
    sys.exit(1 if failed else 0)
