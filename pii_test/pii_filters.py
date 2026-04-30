"""
Post-processing filters for PII detection results.
Designed for KCC agricultural advisory data — handles IndicNER over-predictions
on common Hindi nouns, scheme names, crop/chemical names, and tokenization fragments.
"""

import re
from presidio_analyzer import RecognizerResult


# Hindi common words that IndicNER frequently mis-tags as PERSON.
# Expand based on your data — these are the high-frequency offenders from KCC.
HINDI_STOPWORDS = {
    # Address/relational
    "भाई", "बहन", "साहब", "जी", "श्री", "आप",
    # Weather/agriculture vocabulary
    "बारिश", "बादल", "तापमान", "हवा", "मौसम", "धूप",
    "संभावना", "अधिकतम", "न्यूनतम", "हल्की", "मध्यम", "भारी",
    # Scheme/government vocabulary
    "निधि", "योजना", "मंत्री", "प्रधान", "किसान", "सम्मान",
    "रजिस्ट्रेशन", "हेल्प", "लाईन", "केंद्र", "खाते",
    # Common verbs/particles getting flagged
    "हैं", "है", "रहे", "सकी", "होने", "की", "का", "के", "कि",
}

# English domain false positives — KCC scheme names, crops, chemicals, programs.
# These trigger PERSON in standard NER models because they're capitalized phrases.
ENGLISH_DOMAIN_BLOCKLIST = {
    # Schemes and programs
    "kisan samman", "nidhi yojna", "nidhi yojana", "kisan samman nidhi",
    "diesel subsidy", "seed subsidy", "weed control",
    "krishi vigyan kendra", "mantri krishi", "bihar rajya fasal",
    "pradhan mantri", "pm kisan",
    # Crops
    "pointed gourd", "bottle gourd", "banana", "rice", "wheat",
    "mung phalli", "moong", "arhar", "tur", "chana",
    # Chemicals/pesticides
    "cartap hydrochloride", "imidacloprid", "carbendazim", "mancozeb",
    # Generic
    "click", "aadhar", "aadhaar",
}


def is_hindi_text(text):
    """True if text contains any Devanagari character."""
    return bool(re.search(r"[\u0900-\u097F]", text or ""))


def filter_person_detection(entity_text, score, source="presidio"):

    if source == "regex":
        return True

    text = (entity_text or "").strip()
    if not text:
        return False

    # 1. Length filter — kills tokenization fragments like "रा", "कि", "RA"
    if is_hindi_text(text):
        # Devanagari chars are denser; 2 chars can still be a fragment
        if len(text) <= 3:
            return False
    else:
        # English: real names are at least 3 chars, "RA" / "DEVE" are fragments
        if len(text) <= 3:
            return False

    # 2. Stopword/blocklist filter
    text_lower = text.lower().strip()
    if is_hindi_text(text):
        # Check if any token in the snippet is a Hindi stopword
        tokens = text.split()
        if any(tok in HINDI_STOPWORDS for tok in tokens):
            return False
        # Also drop if the whole snippet is mostly stopwords
        stopword_ratio = sum(1 for tok in tokens if tok in HINDI_STOPWORDS) / max(len(tokens), 1)
        if stopword_ratio >= 0.5:
            return False
    else:
        if text_lower in ENGLISH_DOMAIN_BLOCKLIST:
            return False
        # Multi-word match (substring) for compound scheme names
        if any(phrase in text_lower for phrase in ENGLISH_DOMAIN_BLOCKLIST):
            return False

    # 3. Score threshold — IndicNER's real predictions on names are usually > 0.7
    # The 0.85 cluster in your data is a Presidio default; treat it with suspicion
    # only when combined with above filters.
    if score < 0.6:
        return False

    return True


def filter_detections(detections):

    kept = []
    for d in detections:
        if d["entity_type"] == "PERSON":
            if not filter_person_detection(d["entity_text"], d["score"], d.get("source", "presidio")):
                continue
        # Other entity types (PHONE, AADHAAR, EMAIL, PAN, FARMER_REG_ID) are mostly
        # regex-based and high-precision — keep them all
        kept.append(d)
    return kept


if __name__ == "__main__":
    # Reproduces the noise patterns from your pii_detections_combined.csv
    test_cases = [
        # (entity_text, score, source, expected_kept, why)
        ("भाई", 0.85, "presidio", False, "Hindi address word, not a name"),
        ("बारिश", 0.85, "presidio", False, "means 'rain'"),
        ("निधि योजना", 0.85, "presidio", False, "scheme name fragment"),
        ("कि", 0.45, "presidio", False, "tokenization fragment"),
        ("रा", 0.52, "presidio", False, "fragment of 'Rahul' or similar"),
        ("RA", 0.47, "presidio", False, "English fragment, too short"),
        ("Kisan Samman", 0.85, "presidio", False, "scheme name"),
        ("Nidhi Yojna", 0.85, "presidio", False, "scheme name"),
        ("Diesel Subsidy", 0.85, "presidio", False, "program name"),
        ("Pointed Gourd", 0.85, "presidio", False, "crop"),
        ("Cartap Hydrochloride", 0.85, "presidio", False, "chemical"),
        # True positives that should survive
        ("Rahul Kumar", 0.92, "presidio", True, "real English name"),
        ("राहुल कुमार", 0.88, "presidio", True, "real Hindi name"),
        ("9876543210", 1.0, "regex", True, "phone via regex"),
        ("ABCDE1234F", 1.0, "regex", True, "PAN via regex"),
    ]

    print(f"{'Entity':<30} {'Score':>6} {'Source':<10} {'Kept?':<6} {'Expected':<10} {'OK?'}")
    print("-" * 80)
    for entity, score, source, expected, _ in test_cases:
        kept = filter_person_detection(entity, score, source) if source == "presidio" else True
        ok = "yes" if kept == expected else "no"
        print(f"{entity:<30} {score:>6.2f} {source:<10} {str(kept):<6} {str(expected):<10} {ok}")
