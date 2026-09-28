"""Stopgap: move KCC columns from ``present`` to ``permissible`` when every
phone number in them is a public or officer contact.

KCC answers routinely quote who the farmer should call -- the block ADO, a KVK
scientist, the district JDA's office, a helpline. Tier 1's
``R11-personal-channel`` reads any such number as a personal channel, and on
the KCC run it put 652 files in ``present`` on phone numbers alone. This
script corrects those verdicts in a finished ``pii_classify_pipeline.py`` run
until a proper KCC rule replaces it in Tier 1.

A number is judged from the text around it in the source file (the detection
CSVs keep the row index), in this order -- the first match decides:

  private   a farmer-record field right beside it: PM-Kisan / KCC-loan blocks
            ("UTR No:", "Mobile No" under "Father/Spouse/Guardian", a
            registration ID such as KL281760912, bank name, loan account)
  public    an STD-coded landline -- an office line
  public    the same number in 3+ files -- a farmer's own number does not
            recur across quarters and states
  public    an officer / institution cue nearby: contact, ADO/AO/JDA, Dr.,
            KVK, scientist, department, dealer, helpline ... in English and
            the Indic scripts the corpus uses
  unknown   none of these

A column moves only if it has at least one phone number, every one is public,
it holds no farmer registration ID or Aadhaar, and no name or email in it sits
beside a farmer-record cue. Unknown numbers keep the column ``present``: this
errs towards leaving a verdict loud.

Rewrites column_class.csv, dataset_class.csv and file_summary.csv in --run-dir
(the originals are kept once as *.before_override.csv) and writes
public_contact_override.csv: every moved column with its numbers and why.
tier1_column_class.csv and tier3_verdicts.csv are left as the tiers wrote them.

Usage:
    python pii_test/kcc_public_contact_override.py \\
        --run-dir pii_test/kcc/classification --scan-dir pii_test/kcc/kcc-transcripts \\
        --summary pii_test/kcc/kcc_scan_summary.csv
    python pii_test/kcc_public_contact_override.py ... --dry-run
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pii_classify as tier1  # noqa: E402
from pii_classify_pipeline import with_final_class, write_csv  # noqa: E402
from pii_filters import classify_phone_number, phone_digits  # noqa: E402

RULE_ID = "KCC-public-contact"
PUBLIC_WINDOW = 120    # characters before a number searched for officer cues
PRIVATE_WINDOW = 70    # a record field sits right beside its value
AFTER = 40             # characters after a number, for both
RECURRING_FILES = 3
STRONG_TYPES = ("FARMER_REGISTRATION_ID", "AADHAAR_NUMBER")

PRIVATE_CUES = re.compile(
    r"\b[a-z]{2}\d{9}\b|registration\s*(no|number|id)|date\s*of\s*registration|"
    r"father|spouse|guardian|name\s*of\s*(the\s*)?farmer|farmer'?s?\s*name|"
    r"aadh?aa?r|account|ifsc|utr\b|credit\s*date|beneficiary|date\s*of\s*birth|\bdob\b|"
    r"bank\s*name|loan\s*(type|account|amount)|kcc\s*account|"
    r"पंजीकरण\s*(संख्या|नंबर|क्रमांक)|पिता|आधार|खाता|अकाउंट|ऋण|बैंक\s*का\s*नाम|लाभार्थी",
    re.I)

PUBLIC_CUES = re.compile(
    r"contact|contect|officer|\bado\b|\bao\b|\ba\.?o\b|\bada\b|\bdda\b|\bjda\b|\bdao\b|"
    r"\bbao\b|\bsdao\b|\bsao\b|\bheo\b|\bhdo\b|director|deputy|assistant|scientist|"
    r"specialist|professor|\bdr\b|\bdr\.|\bsh\.|\bshri\b|\bsmt\b|\bmrs?\b\.?|b\.?\s?sc|"
    r"kvk|krishi|vigyan|bhavan|bhawan|university|\bdept|department|office|\bo/o\b|"
    r"helpline|toll|market|\bfarm\b|seed|cent(re|er)|institute|station|horticultur|"
    r"extension|project|accountant|secretary|enterprises?|traders?|agency|agencies|"
    r"dealer|\bshop\b|society|nursery|\bbank\b|call\b|\bph\b|phone|mob(ile)?\b|"
    r"\brsk\b|raitha|\bnumbers?\b|suggest|"
    # Tamil, Telugu, Kannada, Bengali, Odia: officer / contact / phone / agriculture
    r"அதிகாரி|அணுகவும்|போன்|அலைபேசி|தொடர்பு|வேளாண்|நிலையம்|அலுவலர்|"
    r"సంప్రదించ|అధికారి|ఫోన్|ಸಂಪರ್ಕ|ಅಧಿಕಾರಿ|যোগাযোগ|আধিকারিক|ଯୋଗାଯୋଗ|"
    # Hindi / Marathi, Gujarati
    r"नर्सरी|कांटेक्ट|कॉन्टैक्ट|नंबर|संपर्क|सम्पर्क|अधिकारी|डॉ|डॉक्टर|वैज्ञानिक|विभाग|"
    r"केंद्र|केन्द्र|कृषि|एडीओ|कार्यालय|સંપર્ક|અધિકારી|ડૉ|કેન્દ્ર|ખેતીવાડી",
    re.I)


def _around(cell, text, before):
    i = cell.find(text)
    if i < 0:
        return cell
    return cell[max(0, i - before): i + len(text) + AFTER]


def near_private_cue(cell, text):
    return bool(PRIVATE_CUES.search(_around(cell, text, PRIVATE_WINDOW)))


def judge_number(cell, text, kind, files):
    """"private", "public:<why>" or "unknown" for one quoted phone number."""
    if near_private_cue(cell, text):
        return "private"
    if kind == "landline":
        return "public:landline"
    if files >= RECURRING_FILES:
        return "public:recurring"
    if PUBLIC_CUES.search(_around(cell, text, PUBLIC_WINDOW)):
        return "public:cue"
    return "unknown"


def load_detections(scan_dir, keys):
    """Detections for the given (uuid, column) pairs, with their source cell."""
    frames = []
    for det_path in tier1.find_detection_csvs([scan_dir]):
        det = pd.read_csv(det_path, dtype={"entity_text": str})
        folder = os.path.relpath(os.path.dirname(det_path), scan_dir).replace(os.sep, "/")
        det["uuid"] = [f"{folder}/{f}" if folder != "." else f for f in det["file"]]
        frames.append(det[[(u, c) in keys for u, c in zip(det["uuid"], det["column"])]])
    det = pd.concat(frames, ignore_index=True)
    det["entity_text"] = det["entity_text"].fillna("")

    cells = {}
    for uuid, group in det.groupby("uuid"):
        src = pd.read_csv(os.path.join(scan_dir, uuid), dtype=str, on_bad_lines="skip",
                          nrows=int(group["row_index"].max()) + 1)
        for row, column in set(zip(group["row_index"], group["column"])):
            ok = row < len(src) and column in src.columns
            cells[(uuid, row, column)] = str(src.iloc[row][column]) if ok else ""
    det["cell"] = [cells[k] for k in zip(det["uuid"], det["row_index"], det["column"])]
    return det


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True, help="pii_classify_pipeline.py --out-dir")
    parser.add_argument("--scan-dir", required=True, help="the scanned folder (its --csv)")
    parser.add_argument("--summary", help="the scan's --summary-out, to rebuild file_summary.csv")
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = parser.parse_args()

    column_path = os.path.join(args.run_dir, "column_class.csv")
    classes = pd.read_csv(column_path, dtype=str, keep_default_na=False)
    present = classes[classes["pii_class"] == "present"]
    keys = set(zip(present["uuid"], present["column"]))
    det = load_detections(args.scan_dir, keys)

    phones = det[det["entity_type"] == "PHONE_NUMBER"].copy()
    phones["digits"] = phones["entity_text"].map(phone_digits)
    phones["kind"] = phones["entity_text"].map(classify_phone_number)
    spread = phones.groupby("digits")["uuid"].nunique().rename("files")
    phones = phones.join(spread, on="digits")
    phones["judged"] = [judge_number(c, t, k, f) for c, t, k, f in
                        zip(phones["cell"], phones["entity_text"], phones["kind"], phones["files"])]

    others = det[det["entity_type"].isin(["PERSON", "EMAIL_ADDRESS"])]
    blocked = {(u, c) for u, c, cell, t in zip(others["uuid"], others["column"],
                                              others["cell"], others["entity_text"])
               if near_private_cue(cell, t)}

    by_column = phones.groupby(["uuid", "column"])
    moves = {}
    for (uuid, column), group in by_column:
        row = present[(present["uuid"] == uuid) & (present["column"] == column)].iloc[0]
        if any(t in row["entity_types"] for t in STRONG_TYPES):
            continue
        if (uuid, column) in blocked or not group["judged"].str.startswith("public").all():
            continue
        moves[(uuid, column)] = group

    print(f"present columns: {len(present)} | moving to permissible: {len(moves)}")
    print("phone numbers behind present columns:",
          phones.drop_duplicates(["uuid", "column", "digits"])["judged"].value_counts().to_dict())
    if args.dry_run:
        return 0

    for name in ("column_class.csv", "dataset_class.csv", "file_summary.csv"):
        path = os.path.join(args.run_dir, name)
        backup = path.replace(".csv", ".before_override.csv")
        if os.path.exists(path) and not os.path.exists(backup):
            shutil.copy2(path, backup)

    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    audit = []
    for index, row in classes.iterrows():
        group = moves.get((row["uuid"], row["column"]))
        if group is None:
            continue
        numbers = group.drop_duplicates("digits")
        evidence = json.loads(row["evidence_json"] or "{}")
        evidence["override"] = {
            "previous_class": row["pii_class"], "previous_tier": row["tier"],
            "previous_rule_id": row["rule_id"],
            "numbers": {n: j for n, j in zip(numbers["entity_text"], numbers["judged"])},
        }
        classes.loc[index, ["pii_class", "tier", "rule_id", "rule_strength",
                            "reason", "evidence_json", "classified_at"]] = [
            "permissible", "override", RULE_ID, "override",
            "every phone number is a public or officer contact (stopgap until a KCC rule)",
            json.dumps(evidence, ensure_ascii=False), now]
        audit.append({
            "uuid": row["uuid"], "column": row["column"],
            "previous_tier": row["tier"], "previous_rule_id": row["rule_id"],
            "n_numbers": len(numbers),
            "landline": int((numbers["judged"] == "public:landline").sum()),
            "recurring": int((numbers["judged"] == "public:recurring").sum()),
            "officer_cue": int((numbers["judged"] == "public:cue").sum()),
            "numbers": "; ".join(numbers["entity_text"]),
        })

    rows = classes.to_dict("records")
    datasets = tier1.rollup_datasets(rows)
    write_csv(column_path, rows)
    write_csv(os.path.join(args.run_dir, "dataset_class.csv"), datasets)
    write_csv(os.path.join(args.run_dir, "public_contact_override.csv"), audit)
    if args.summary:
        summary_rows, _ = with_final_class(args.summary, datasets)
        write_csv(os.path.join(args.run_dir, "file_summary.csv"), summary_rows)

    counts = pd.Series([d["pii_class"] for d in datasets]).value_counts()
    print("final class per file:", counts.to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
