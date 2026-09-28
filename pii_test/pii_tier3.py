"""Tier 3 -- local LLM judge for the pairs Tier 1 left undecided.

Reads the ``undecided`` rows out of ``pii_column_class``, asks a locally served
instruct model to classify each (dataset, column) pair, and writes the verdicts
back to the same table with ``tier='llm'``.

Design notes, all of them load-bearing:

* **Tier 3 never revisits a pair a rule already decided.** The rules are the
  high-precision layer; an 8B model is not entitled to overrule them.
* **The model returns a class, nothing else.** Reasoning is left on -- PII
  judgement is genuinely subjective and the trace demonstrably fixes cases the
  non-reasoning prompt got wrong -- but the trace is evidence for a human, not
  a field the pipeline parses. No role question, no self-reported confidence:
  a number the model invents would repeat exactly the mistake that makes the
  detector's 0.85 useless.
* **Publication is not evidence.** Every dataset here is already on
  data.gov.in; that is the thing under audit. The system prompt says so,
  because without it the model reasons "it is published, therefore publishing
  it was lawful" and returns `permissible` for scheme beneficiaries.
* **A bad reply is never a verdict.** Anything unparseable leaves the pair
  ``undecided`` for Tier 4.

Usage:
    python pii_tier3.py --test
    python pii_tier3.py --db ../transformation/metadata.db --limit 15 --out /tmp/t3.csv
    python pii_tier3.py --db ../transformation/metadata.db --write
    python pii_tier3.py --csv tier1.csv --out verdicts.csv --final-out classes.csv

``--csv`` reads the table ``pii_classify.py --csv ... --out`` writes, in place
of pii_column_class. ``--final-out`` writes that table back with the verdicts
applied -- what ``--write`` does to the DB, as a new file. pii_classify_pipeline.py
runs both tiers in one go.
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime

ENDPOINT = "http://127.0.0.1:8000/v1/chat/completions"
MODEL = "tier3-judge"
CLASSES = ("false_positive", "permissible", "present")
MAX_SAMPLE_VALUES = 15
MAX_SIBLING_HEADERS = 30
MAX_TOKENS = 2500
REQUEST_TIMEOUT = 300
TRACE_KEPT = 800

SYSTEM_PROMPT = """You audit PII detections in Indian government open-data tables published on data.gov.in.

An automated detector (Presidio + spaCy + Indic NER) flagged values in ONE column of ONE dataset. The detector sees no context and is wrong often: it flags Indian place names, rivers and water bodies, scheme names, crops and commodities, monuments, castes, species, institutions and job titles as people, because they are capitalised multi-word Indian-language strings.

Decide what the flagged column really is, using the dataset title, catalog title, description and the file's full header row as context.

CRITICAL: this dataset is ALREADY published on data.gov.in. That fact is not evidence of anything -- it is precisely what you are auditing. Never reason "it is published, therefore publishing it was lawful." Judge only from who the people are and the capacity in which they are named.

Indian context you must apply:
- Indian personal names are frequently identical in shape to place, river, deity and institution names. Rama, Krishna, Ganga, Lakshmi and Govind are all common personal names AND common place, river or temple names. The column header and the dataset subject decide which it is -- never the shape of the value.
- Organisations, colleges, hospitals and trusts are often named after people (Rajiv Gandhi Foundation, Smt. Kashibai Navale College). A person's name inside an organisation's name is not personal data. But a bare personal name -- initials, an honorific, a lone given name, with no organisation word -- in a column meant for organisations is more likely a person entered in the wrong field.
- Honorifics that mark a personal name: Shri, Smt, Kum, Sh., Dr, Md, Mohd, Prof, Justice.
- People whose identity is public by virtue of office: MPs (Lok Sabha, Rajya Sabha), MLAs, ministers, IAS and IPS officers, sarpanches, vice-chancellors, nodal officers, Public Information Officers under the RTI Act. Named in that official capacity, they are already public.
- Official channels, not personal: toll-free helplines (1800-series, 104, 108, 112, 1098), STD-coded office landlines, and email on .gov.in / .nic.in / .ac.in / .res.in / .org.in domains.
- Private individuals: scheme beneficiaries, patients, students, applicants, pensioners, farmers, borrowers, complainants, accused and victims. Their names, personal mobile numbers, private email, Aadhaar and PAN are personal data.
- Aggregate or tabulated statistics about people are not personal data: a count, a rate or a district total identifies nobody.

Choose exactly one class:
false_positive -- the flagged values are not people at all.
permissible -- real personal data that is public because THE PERSON holds a public office, or the value is an institutional contact detail. This never applies merely because a dataset is published, or because a government scheme is involved. Beneficiaries, applicants and recipients of a scheme are private individuals however public the scheme itself is.
present -- personal data about a private individual, or a personal contact detail. Not publishable.

If you are torn between permissible and present, answer present.

Reason it through briefly, then end your reply with exactly one final line:
CLASS: <false_positive|permissible|present>"""


def build_prompt(pair):
    """Render one (dataset, column) pair as the user message.

    Deliberately minimal: the title, catalog title and description say what the
    dataset is, the header row says what the column sits next to, and the
    values say what was flagged. Corpus statistics (cardinality, name-shaped
    fraction, frequency) are Tier 1's evidence, not the model's -- Tier 1
    already weighed them and declined to decide, so repeating them here only
    invites the model to re-derive a rule that has already abstained.
    """
    evidence = pair.get("evidence") or {}
    lines = []

    def add(label, value):
        if value not in (None, "", []):
            lines.append(f"{label}: {value}")

    add("Dataset title", pair.get("title"))
    add("Catalog title", pair.get("catalog_title"))
    add("Description", _truncate(pair.get("description"), 600))

    headers = [h for h in (pair.get("headers") or []) if h != pair.get("column")]
    if headers:
        shown = headers[:MAX_SIBLING_HEADERS]
        suffix = f" (+{len(headers) - len(shown)} more)" if len(headers) > len(shown) else ""
        add("File header row", ", ".join(shown) + suffix)

    add("Flagged column", pair.get("column"))
    add("Flagged as", pair.get("entity_types"))

    values = (evidence.get("sample_values") or [])[:MAX_SAMPLE_VALUES]
    add("Sample flagged values", "; ".join(str(v) for v in values))

    return "\n".join(lines)


def _truncate(text, limit):
    if not text:
        return text
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "..."


def parse_verdict(reply):
    """Pull the class out of a reply. Returns (class|None, trace)."""
    if not reply:
        return None, ""
    trace = reply.strip()
    # An unclosed think block means the model was cut off mid-reasoning rather
    # than being genuinely torn. Those look identical downstream (both leave
    # the pair undecided) but only one of them is fixed by more tokens.
    if "<think>" in reply and "</think>" not in reply:
        return None, trace
    body = re.sub(r"<think>.*?</think>", "", reply, flags=re.S)

    matches = re.findall(r"CLASS:\s*([a-z_]+)", body, flags=re.I)
    if not matches:
        # The model sometimes answers without the marker; accept a bare class
        # token only if exactly one of the three appears in the final answer.
        present = {c for c in CLASSES if re.search(rf"\b{c}\b", body, re.I)}
        if len(present) != 1:
            return None, trace
        return present.pop(), trace

    verdict = matches[-1].strip().lower()
    return (verdict if verdict in CLASSES else None), trace


class VLLMClient:
    def __init__(self, endpoint=ENDPOINT, model=MODEL, max_tokens=MAX_TOKENS,
                 timeout=REQUEST_TIMEOUT, presence_penalty=0.0):
        self.endpoint = endpoint
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        # Qwen3's model card: greedy decoding in thinking mode "can lead to
        # ... endless repetitions"; it recommends 1.5 for quantized models.
        # A logit adjustment, not sampling, so temperature 0 stays
        # reproducible with it on.
        self.presence_penalty = presence_penalty

    def __call__(self, user_message):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": user_message}],
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        if self.presence_penalty:
            body["presence_penalty"] = self.presence_penalty
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint, payload, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.load(response)
        return body["choices"][0]["message"]["content"]


class ServerGaveUp(RuntimeError):
    """Raised when the endpoint fails repeatedly -- almost always a dead engine."""


def judge(pairs, client, retries=1, progress=None, max_consecutive_errors=3):
    """Classify every pair. Unparseable replies stay undecided.

    A run of consecutive transport failures aborts rather than grinding
    through the remaining pairs: on this box vLLM dies of CUDA OOM inside the
    engine loop, which takes the whole server with it, and marking every
    remaining pair "undecided (connection refused)" would destroy the Tier 1
    verdicts they still carry.
    """
    results = []
    consecutive = 0
    for index, pair in enumerate(pairs, 1):
        message = build_prompt(pair)
        verdict, trace, error = None, "", None
        for attempt in range(retries + 1):
            try:
                reply = client(message)
            except Exception as exc:                    # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
                continue
            verdict, trace = parse_verdict(reply)
            if verdict:
                break
            error = ("reply truncated mid-reasoning"
                     if "<think>" in reply and "</think>" not in reply
                     else "unparseable reply")
        results.append({**pair,
                        "verdict": verdict,
                        "trace": trace[-TRACE_KEPT:],
                        "error": None if verdict else error})
        if progress:
            progress(index, len(pairs), results[-1])

        transport_failed = (verdict is None and error
                            and "unparseable" not in error
                            and "truncated" not in error)
        consecutive = consecutive + 1 if transport_failed else 0
        if consecutive >= max_consecutive_errors:
            raise ServerGaveUp(
                f"{consecutive} consecutive transport failures at pair {index}"
                f"/{len(pairs)} -- last error: {error}. "
                f"{len(results)} pairs judged; nothing written.")
    return results


def to_rows(results):
    """Shape the judged pairs for pii_column_class."""
    rows = []
    for r in results:
        decided = r["verdict"] is not None
        evidence = dict(r.get("evidence") or {})
        evidence["tier1_rule_id"] = r.get("rule_id")
        evidence["llm_reasoning"] = r["trace"]
        if r.get("error"):
            evidence["llm_error"] = r["error"]
        rows.append({
            "uuid": r["uuid"],
            "lot": r["lot"],
            "column": r["column"],
            "pii_class": r["verdict"] if decided else "undecided",
            "tier": "llm" if decided else "rule",
            "rule_id": "T3-judge" if decided else r.get("rule_id"),
            "rule_strength": "llm" if decided else None,
            "reason": ("Tier 3 local LLM judge" if decided
                       else f"Tier 3 could not decide ({r.get('error')})"),
            "evidence_json": json.dumps(evidence, ensure_ascii=False),
            "classified_at": datetime.now(),
        })
    return rows


UPDATE_SQL = """
UPDATE pii_column_class SET
    pii_class     = ?,
    tier          = ?,
    rule_id       = ?,
    rule_strength = ?,
    reason        = ?,
    evidence_json = ?,
    classified_at = ?
WHERE uuid = ? AND lot = ? AND "column" = ?
"""


def load_undecided(db_path, limit=None, rejudge=False):
    """Read the undecided pairs plus the context the prompt needs."""
    import duckdb
    con = duckdb.connect(db_path, read_only=True)

    query = """
    SELECT c.uuid, c.lot, c."column", c.entity_types, c.n_detections,
           c.n_distinct, c.rule_id, c.evidence_json,
           coalesce(m1."Title", m2.title)                        AS title,
           coalesce(m1."Relation[Catalog Title]", m2.catalog_title) AS catalog_title,
           coalesce(m1."Description", d2."Description")          AS descr,
           coalesce(m1."Publisher[ministry_department]", m2.ministry_department) AS ministry,
           coalesce(m1."Subject[sector]", m2.sector)             AS sector,
           coalesce(m1."Conforms To", d2."Conforms To")          AS conforms_to
    FROM pii_column_class c
    LEFT JOIN dublin_core_metadata  m1 ON m1."Identifier[UUID]" = c.uuid
    LEFT JOIN remain_raw_metadata   m2 ON m2.uuid               = c.uuid
    LEFT JOIN dublin_core_remaining d2 ON d2."Identifier[UUID]" = c.uuid
    WHERE c.pii_class = 'undecided' {also_decided}
    ORDER BY c.lot, c.uuid, c."column"
    """
    query = query.format(
        also_decided="OR c.rule_id = 'T3-judge'" if rejudge else "")
    if limit:
        query += f" LIMIT {int(limit)}"

    # Columns that produced a detection, as the fallback header list.
    detected = {}
    for uuid, column in con.execute(
            'SELECT uuid, "column" FROM pii_column_class').fetchall():
        detected.setdefault(uuid, []).append(column)

    pairs = []
    for row in con.execute(query).fetchall():
        (uuid, lot, column, entity_types, n_detections, n_distinct, rule_id,
         evidence_json, title, catalog_title, descr, ministry, sector,
         conforms_to) = row
        if conforms_to:
            headers = [h.strip() for h in str(conforms_to).split(",") if h.strip()]
        else:
            headers = sorted(detected.get(uuid, []))
        pairs.append({
            "uuid": uuid, "lot": lot, "column": column,
            "entity_types": entity_types, "n_detections": n_detections,
            "n_distinct": n_distinct, "rule_id": rule_id,
            "evidence": json.loads(evidence_json) if evidence_json else {},
            "title": title, "catalog_title": catalog_title,
            "description": descr, "ministry": ministry, "sector": sector,
            "headers": headers,
            "headers_source": "conforms_to" if conforms_to else "detected_columns",
        })
    con.close()
    return pairs


def pairs_from_class_rows(rows, limit=None, rejudge=False):
    """Build Tier 3 pairs from pii_column_class-shaped rows.

    The rows are pii_classify's output, in memory or read back from its
    ``--out`` CSV (every value a string then). Selection and order match
    load_undecided. The header row comes from ``file_headers`` where a --csv
    run recorded one; otherwise the detected columns, as for the DB.
    """
    detected = {}
    for r in rows:
        detected.setdefault(r["uuid"], []).append(r["column"])

    chosen = [r for r in rows
              if r["pii_class"] == "undecided"
              or (rejudge and r.get("rule_id") == "T3-judge")]
    chosen.sort(key=lambda r: (str(r["lot"]), r["uuid"], r["column"]))
    if limit:
        chosen = chosen[:int(limit)]

    pairs = []
    for r in chosen:
        evidence = r.get("evidence_json") or {}
        if isinstance(evidence, str):
            evidence = json.loads(evidence)
        file_headers = r.get("file_headers")
        if isinstance(file_headers, str):
            file_headers = json.loads(file_headers) if file_headers else None
        pairs.append({
            "uuid": r["uuid"], "lot": r["lot"], "column": r["column"],
            "entity_types": r.get("entity_types"),
            "n_detections": r.get("n_detections"),
            "n_distinct": r.get("n_distinct"), "rule_id": r.get("rule_id"),
            "evidence": evidence,
            "title": r.get("title") or None,
            "catalog_title": None, "description": None,
            "ministry": None, "sector": None,
            "headers": file_headers or sorted(detected.get(r["uuid"], [])),
            "headers_source": "file" if file_headers else "detected_columns",
        })
    return pairs


def folder_group_key(pair):
    """Group key for --judge-per-folder: same folder, column and header row.

    The header row is part of the key so that files with different schemas
    in one folder are never judged together.
    """
    uuid = str(pair["uuid"])
    folder = uuid.rsplit("/", 1)[0] if "/" in uuid else ""
    return (folder, pair["column"], tuple(pair.get("headers") or ()))


def group_pairs(pairs, key=folder_group_key):
    """Collapse pairs that share ``key`` into one representative each.

    For a folder holding one dataset split into files -- KCC's per-state
    folders of quarterly exports -- every quarter's KccAns column is the same
    question, and judging each separately spends the model on repeats. The
    representative takes its sample values round-robin across the member
    files so no single quarter dominates the prompt. Its title is kept only if
    every member shares it: per-file names like ``2023_Q4`` say nothing about
    the group, and the folder name is never shown (it may be a test label).
    """
    groups = {}
    for pair in pairs:
        groups.setdefault(key(pair), []).append(pair)

    reps = []
    for group_key, members in groups.items():
        samples, seen = [], set()
        pools = [list((m.get("evidence") or {}).get("sample_values") or []) for m in members]
        while len(samples) < MAX_SAMPLE_VALUES and any(pools):
            for pool in pools:
                while pool:
                    value = pool.pop(0)
                    if value not in seen:
                        seen.add(value)
                        samples.append(value)
                        break
                if len(samples) >= MAX_SAMPLE_VALUES:
                    break
        titles = {m.get("title") for m in members}
        rep = dict(members[0])
        rep.update({
            "evidence": {**(members[0].get("evidence") or {}), "sample_values": samples},
            "entity_types": ",".join(sorted({t for m in members
                                             for t in str(m.get("entity_types") or "").split(",") if t})),
            "n_detections": sum(int(m.get("n_detections") or 0) for m in members),
            "title": titles.pop() if len(titles) == 1 else None,
            "group": group_key[0] or ".",
            "members": members,
        })
        reps.append(rep)
    return reps


def expand_group_results(results):
    """Give every member of a judged group its representative's verdict."""
    out = []
    for r in results:
        for member in r["members"]:
            evidence = dict(member.get("evidence") or {})
            evidence["tier3_group"] = f"{r['group']} / {r['column']} ({len(r['members'])} files)"
            out.append({**member, "evidence": evidence, "verdict": r["verdict"],
                        "trace": r["trace"], "error": r["error"]})
    return out


def read_class_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def apply_verdicts(class_rows, verdict_rows):
    """Apply to_rows output to pii_column_class-shaped rows.

    The in-memory equivalent of write_to_db's UPDATE, touching the same
    columns. Keys compare as strings because one side may have been read back
    from CSV.
    """
    fields = ("pii_class", "tier", "rule_id", "rule_strength", "reason",
              "evidence_json", "classified_at")
    updates = {(str(v["uuid"]), str(v["lot"]), str(v["column"])): v
               for v in verdict_rows}
    out = []
    for row in class_rows:
        update = updates.get((str(row["uuid"]), str(row["lot"]), str(row["column"])))
        out.append({**row, **{f: update[f] for f in fields}} if update else dict(row))
    return out


def write_verdicts_csv(path, results):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["uuid", "lot", "column", "title", "entity_types",
                         "n_detections", "sample_values", "verdict",
                         "error", "trace"])
        for r in results:
            writer.writerow([
                r["uuid"], r["lot"], r["column"], r.get("title"),
                r.get("entity_types"), r.get("n_detections"),
                "; ".join(str(v) for v in
                          (r.get("evidence") or {}).get("sample_values", [])),
                r["verdict"] or "", r.get("error") or "", r["trace"]])


def write_class_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_to_db(db_path, rows):
    import duckdb
    try:
        con = duckdb.connect(db_path)
    except duckdb.IOException as exc:
        raise SystemExit(
            f"cannot open {db_path} for writing -- another process (a running "
            f"scan?) holds the DuckDB write lock.\n{exc}")
    try:
        con.executemany(UPDATE_SQL, [
            (r["pii_class"], r["tier"], r["rule_id"], r["rule_strength"],
             r["reason"], r["evidence_json"], r["classified_at"],
             r["uuid"], r["lot"], r["column"]) for r in rows])
        con.commit()
    finally:
        con.close()


def summarise(results):
    counts = {}
    for r in results:
        counts[r["verdict"] or "undecided"] = counts.get(r["verdict"] or "undecided", 0) + 1
    width = max((len(k) for k in counts), default=0)
    lines = [f"Tier 3 judged {len(results)} pairs", ""]
    for key in sorted(counts, key=lambda k: -counts[k]):
        lines.append(f"  {key:<{width}}  {counts[key]:>5}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# self-tests -- run with no server up
# --------------------------------------------------------------------------

def _prompt_pair():
    return {"uuid": "u1", "lot": 2, "column": "Beneficiary Name",
            "entity_types": "PERSON", "n_detections": 1, "n_distinct": 1,
            "title": "t", "headers": [], "evidence": {"sample_values": ["x"]}}


def _run_tests():
    failures = []

    def check(name, condition):
        if not condition:
            failures.append(name)
            print(f"FAIL {name}")
        else:
            print(f"ok   {name}")

    verdict, _ = parse_verdict("blah blah\nCLASS: present")
    check("parses a well-formed verdict", verdict == "present")

    verdict, trace = parse_verdict(
        "<think>maybe permissible, no</think>\nCLASS: false_positive")
    check("ignores a class named inside the think block",
          verdict == "false_positive")
    check("keeps the reasoning trace", "maybe permissible" in trace)

    verdict, _ = parse_verdict("CLASS: present\nActually CLASS: permissible")
    check("takes the last marker", verdict == "permissible")

    verdict, _ = parse_verdict("I think this is present, clearly.")
    check("accepts one unambiguous bare class", verdict == "present")

    verdict, _ = parse_verdict("could be permissible or present, unsure")
    check("refuses an ambiguous bare reply", verdict is None)

    verdict, trace = parse_verdict("<think>weighing it up, maybe permis")
    check("a truncated think block is not a verdict", verdict is None)
    check("a truncated reply keeps its trace", "weighing it up" in trace)

    truncated_run = judge([_prompt_pair()] * 5,
                          lambda _m: "<think>still thinking",
                          retries=0, max_consecutive_errors=3)
    check("truncation does not trip the circuit breaker",
          len(truncated_run) == 5)
    check("truncation is labelled distinctly",
          "truncated" in truncated_run[0]["error"])

    verdict, _ = parse_verdict("CLASS: pii_present")
    check("refuses a class outside the vocabulary", verdict is None)

    check("refuses an empty reply", parse_verdict("")[0] is None)

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
    prompt = build_prompt(pair)
    check("prompt carries the title", "PMAY-G Beneficiaries" in prompt)
    check("prompt carries the header row", "Age, Village" in prompt)
    check("prompt carries sample values", "Ramesh Kumar" in prompt)
    check("prompt omits corpus statistics",
          "cardinality" not in prompt.lower() and "0.91" not in prompt)
    check("prompt omits empty fields", "Description:" in prompt
          and "Ministry" not in prompt)

    lone = dict(pair, headers=["Beneficiary Name"])
    check("a header row of just the flagged column is dropped",
          "File header row" not in build_prompt(lone))

    long_pair = dict(pair, headers=[f"col{i}" for i in range(60)])
    check("header list is capped",
          "(+30 more)" in build_prompt(long_pair))

    results = judge([pair], lambda _m: "CLASS: present")
    check("judge returns the verdict", results[0]["verdict"] == "present")

    results = judge([pair], lambda _m: "no idea at all")
    check("unparseable reply leaves it undecided", results[0]["verdict"] is None)
    rows = to_rows(results)
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
        judge([pair] * 10, always_dead, retries=0, max_consecutive_errors=3)
        check("circuit breaker trips on a dead server", False)
    except ServerGaveUp as exc:
        check("circuit breaker trips on a dead server", "pair 3/10" in str(exc))

    garbage_run = judge([pair] * 5, lambda _m: "no idea", retries=0,
                        max_consecutive_errors=3)
    check("unparseable replies do not trip the breaker", len(garbage_run) == 5)

    rows = to_rows(judge([pair], lambda _m: "CLASS: false_positive"))
    row = rows[0]
    check("decided row is marked llm",
          row["tier"] == "llm" and row["rule_id"] == "T3-judge")
    evidence = json.loads(row["evidence_json"])
    check("evidence keeps the Tier 1 rule id", "tier1_rule_id" in evidence)
    check("evidence keeps the reasoning", "llm_reasoning" in evidence)
    check("sample values survive the round trip",
          evidence["sample_values"] == ["Ramesh Kumar", "Sunita Devi"])

    # --csv: Tier 1 rows as read back from pii_classify's --out CSV.
    import tempfile
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
        write_class_csv(path, tier1)
        csv_pairs = pairs_from_class_rows(read_class_csv(path))
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
          "Dataset title: 2023_Q4" in build_prompt(csv_pairs[0]))
    check("csv: --limit applies", len(pairs_from_class_rows(tier1, limit=1)) == 1)

    verdicts = to_rows(judge(csv_pairs,
                             lambda m: "CLASS: present" if "2023_Q4" in m else "unsure"))
    final = apply_verdicts(tier1, verdicts)
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
    grouped = group_pairs([
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
          "KERALA" not in build_prompt(kerala))
    expanded = expand_group_results(judge([kerala], lambda _m: "CLASS: present"))
    check("group: every member gets the verdict",
          [r["verdict"] for r in expanded] == ["present", "present"]
          and {r["uuid"] for r in expanded} == {"KERALA/2023_Q4.csv", "KERALA/2023_Q3.csv"})
    check("group: members keep their own evidence",
          expanded[1]["evidence"]["sample_values"] == ["B", "D"]
          and "2 files" in expanded[1]["evidence"]["tier3_group"])
    check("group: expanded rows shape for the table",
          len(to_rows(expanded)) == 2)

    check("csv: integer and string lots still match",
          apply_verdicts([dict(tier1[0], lot=0)], verdicts)[0]["tier"] == "llm")

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all tests passed")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true",
                        help="run self-tests (no server needed) and exit")
    parser.add_argument("--db", metavar="PATH",
                        help="metadata.db to read undecided pairs from")
    parser.add_argument("--csv", metavar="PATH",
                        help="pii_classify.py --out CSV to read undecided pairs from")
    parser.add_argument("--limit", type=int,
                        help="judge only the first N pairs (dry run)")
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--presence-penalty", type=float, default=0.0,
                        help="Qwen3 recommends 1.5 against repetition loops")
    parser.add_argument("--rejudge", action="store_true",
                        help="also re-judge pairs Tier 3 already decided "
                             "(the whole Tier 1 residual), for comparison runs")
    parser.add_argument("--out", metavar="PATH", help="write verdicts to CSV")
    parser.add_argument("--write", action="store_true",
                        help="write verdicts back into --db")
    parser.add_argument("--judge-per-folder", action="store_true",
                        help="--csv only: judge each (folder, column, header row) "
                             "once and apply the verdict to every file in it. Only "
                             "for folders holding one dataset split into files.")
    parser.add_argument("--final-out", metavar="PATH",
                        help="--csv only: write the --csv table with the "
                             "verdicts applied")
    args = parser.parse_args()

    if args.test:
        return _run_tests()
    if bool(args.db) == bool(args.csv):
        parser.error("exactly one of --test, --db or --csv is required")
    if args.write and not args.db:
        parser.error("--write requires --db; use --final-out with --csv")
    if args.final_out and not args.csv:
        parser.error("--final-out requires --csv")
    if args.judge_per_folder and not args.csv:
        parser.error("--judge-per-folder requires --csv")

    if args.csv:
        class_rows = read_class_csv(args.csv)
        pairs = pairs_from_class_rows(class_rows, args.limit, rejudge=args.rejudge)
    else:
        pairs = load_undecided(args.db, args.limit, rejudge=args.rejudge)
    if not pairs:
        print("no undecided pairs", file=sys.stderr)
        if args.final_out and class_rows:
            write_class_csv(args.final_out, class_rows)
            print(f"wrote {len(class_rows)} rows unchanged to {args.final_out}",
                  file=sys.stderr)
        return 0
    real_headers = sum(1 for p in pairs if p["headers_source"] != "detected_columns")
    print(f"loaded {len(pairs)} undecided pairs "
          f"({real_headers} with a real header row)", file=sys.stderr)
    if args.judge_per_folder:
        pairs = group_pairs(pairs)
        print(f"judging them as {len(pairs)} (folder, column) groups", file=sys.stderr)

    client = VLLMClient(args.endpoint, args.model, args.max_tokens,
                        presence_penalty=args.presence_penalty)

    def progress(i, total, result):
        mark = result["verdict"] or f"UNDECIDED ({result['error']})"
        print(f"[{i}/{total}] {result['column'][:40]:<40} {mark}",
              file=sys.stderr)

    try:
        results = judge(pairs, client, progress=progress)
    except ServerGaveUp as exc:
        print(f"\naborted: {exc}", file=sys.stderr)
        return 1
    print()
    print(summarise(results))
    if args.judge_per_folder:
        results = expand_group_results(results)

    if args.out:
        write_verdicts_csv(args.out, results)
        print(f"wrote {len(results)} rows to {args.out}", file=sys.stderr)

    if args.final_out:
        final = apply_verdicts(class_rows, to_rows(results))
        write_class_csv(args.final_out, final)
        print(f"wrote {len(final)} rows to {args.final_out}", file=sys.stderr)

    if args.write:
        rows = to_rows(results)
        write_to_db(args.db, rows)
        decided = sum(1 for r in rows if r["tier"] == "llm")
        print(f"updated {len(rows)} rows in pii_column_class "
              f"({decided} decided by the model)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
