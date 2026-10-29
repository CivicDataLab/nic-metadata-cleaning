"""Tier 3 -- local LLM judge for the pairs Tier 1 left undecided.

Takes the ``undecided`` rows of Tier 1's column table, asks a locally served
instruct model to classify each (dataset, column) pair, and gives the rows
back with the verdicts applied (``tier='llm'``).

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
  ``undecided``.

run.py's ``classify`` step calls topairs, judge, torows and apply.
"""

import csv
import json
import os
import re
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

ENDPOINT = "http://127.0.0.1:8000/v1/chat/completions"
MODEL = "tier3-judge"
CLASSES = ("false_positive", "permissible", "present")
SAMPLES = 15
MAXHEADERS = 30
MAXTOKENS = 2500
TIMEOUT = 300
TRACEKEPT = 800

SYSTEM = """You audit PII detections in Indian government open-data tables published on data.gov.in.

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


def prompt(pair):
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
    description = " ".join(str(pair.get("description") or "").split())
    add("Description", description if len(description) <= 600 else description[:600] + "...")

    headers = [h for h in (pair.get("headers") or []) if h != pair.get("column")]
    if headers:
        shown = headers[:MAXHEADERS]
        suffix = f" (+{len(headers) - len(shown)} more)" if len(headers) > len(shown) else ""
        add("File header row", ", ".join(shown) + suffix)

    add("Flagged column", pair.get("column"))
    add("Flagged as", pair.get("entity_types"))

    values = (evidence.get("sample_values") or [])[:SAMPLES]
    add("Sample flagged values", "; ".join(str(v) for v in values))

    return "\n".join(lines)


def parse(reply):
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


class Client:
    def __init__(self, endpoint=ENDPOINT, model=MODEL, maxtokens=MAXTOKENS,
                 timeout=TIMEOUT, penalty=0.0):
        self.endpoint = endpoint
        self.model = model
        self.maxtokens = maxtokens
        self.timeout = timeout
        # Qwen3's model card: greedy decoding in thinking mode "can lead to
        # ... endless repetitions"; it recommends 1.5 for quantized models.
        # A logit adjustment, not sampling, so temperature 0 stays
        # reproducible with it on.
        self.penalty = penalty

    def __call__(self, message):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": message}],
            "temperature": 0,
            "max_tokens": self.maxtokens,
        }
        if self.penalty:
            body["presence_penalty"] = self.penalty
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint, payload, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.load(response)
        return body["choices"][0]["message"]["content"]


class ServerGaveUp(RuntimeError):
    """Raised when the endpoint fails repeatedly -- almost always a dead engine."""


def judge(pairs, client, progress=None, keep=None, workers=1, retries=1, maxerrors=3):
    """Classify every pair. Unparseable replies stay undecided.

    ``keep`` is a JSON-lines file of verdicts. Each verdict is written as it
    arrives, and a pair with a verdict in the file is not sent again; one the
    model could not decide is. Without it a server that dies hours into a lot
    takes every verdict so far with it.

    ``workers`` is how many pairs are sent at once. The model writes ~390
    tokens of reasoning per verdict at ~30 tokens/s on the T4, so one pair at
    a time is ~14s a pair with the server's batch otherwise empty. vLLM
    decodes concurrent requests together: 8 at once measured 3.8s a pair with
    the same verdicts. Each worker takes every ``workers``-th pair.

    A run of consecutive transport failures aborts rather than grinding
    through the remaining pairs: on this box vLLM dies of CUDA OOM inside the
    engine loop, which takes the whole server with it, and marking every
    remaining pair "undecided (connection refused)" would destroy the Tier 1
    verdicts they still carry.
    """
    judged = {}
    if keep and os.path.exists(keep):
        with open(keep, encoding="utf-8") as handle:
            for line in handle:
                kept = json.loads(line)
                judged[(kept["uuid"], kept["column"])] = kept
    todo = [p for p in pairs if (p["uuid"], p["column"]) not in judged]
    if len(todo) < len(pairs):
        print(f"{len(pairs) - len(todo)} pair(s) already judged in {keep}", file=sys.stderr)

    lock, count = threading.Lock(), [0]
    handle = open(keep, "a", encoding="utf-8") if keep else None

    def work(part):
        results, consecutive = [], 0
        for pair in part:
            message = prompt(pair)
            verdict, trace, error = None, "", None
            for attempt in range(retries + 1):
                try:
                    reply = client(message)
                except Exception as exc:                    # noqa: BLE001
                    error = f"{type(exc).__name__}: {exc}"
                    continue
                verdict, trace = parse(reply)
                if verdict:
                    break
                error = ("reply truncated mid-reasoning"
                         if "<think>" in reply and "</think>" not in reply
                         else "unparseable reply")
            results.append({**pair,
                            "verdict": verdict,
                            "trace": trace[-TRACEKEPT:],
                            "error": None if verdict else error})
            with lock:
                count[0] += 1
                if handle and verdict:
                    handle.write(json.dumps(results[-1], ensure_ascii=False, default=str) + "\n")
                    handle.flush()
                if progress:
                    progress(count[0], len(todo), results[-1])

            transport = (verdict is None and error
                         and "unparseable" not in error
                         and "truncated" not in error)
            consecutive = consecutive + 1 if transport else 0
            if consecutive >= maxerrors:
                raise ServerGaveUp(
                    f"{consecutive} consecutive transport failures at pair "
                    f"{count[0]}/{len(todo)} -- last error: {error}.")
        return results

    workers = max(1, min(workers, len(todo)))
    try:
        with ThreadPoolExecutor(workers) as pool:
            parts = [pool.submit(work, todo[i::workers]) for i in range(workers)]
        for part in parts:
            for result in part.result():                    # re-raises ServerGaveUp
                judged[(result["uuid"], result["column"])] = result
    finally:
        if handle:
            handle.close()
    return [judged[(p["uuid"], p["column"])] for p in pairs]


def torows(results):
    """Shape the judged pairs as Tier 1 column rows, for apply."""
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


def topairs(rows, limit=None, rejudge=False):
    """Build Tier 3 pairs from Tier 1's column rows.

    The rows are classify.py's output, in memory or read back from its CSV
    (every value a string then): the undecided ones, sorted by lot, file and
    column. The header row comes from ``file_headers`` where the file's own
    was read; otherwise the detected columns. run.py adds the catalogue
    fields (catalog title, description, ministry, sector) for a lot.
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
        fileheaders = r.get("file_headers")
        if isinstance(fileheaders, str):
            fileheaders = json.loads(fileheaders) if fileheaders else None
        pairs.append({
            "uuid": r["uuid"], "lot": r["lot"], "column": r["column"],
            "entity_types": r.get("entity_types"),
            "n_detections": r.get("n_detections"),
            "n_distinct": r.get("n_distinct"), "rule_id": r.get("rule_id"),
            "evidence": evidence,
            "title": r.get("title") or None,
            "catalog_title": None, "description": None,
            "ministry": None, "sector": None,
            "headers": fileheaders or sorted(detected.get(r["uuid"], [])),
            "headers_source": "file" if fileheaders else "detected_columns",
        })
    return pairs


def group(pairs):
    """Collapse pairs of one folder, column and header row into one each.

    For a folder holding one dataset split into files -- KCC's per-state
    folders of quarterly exports -- every quarter's KccAns column is the same
    question, and judging each separately spends the model on repeats. The
    representative takes its sample values round-robin across the member
    files so no single quarter dominates the prompt. Its title is kept only if
    every member shares it: per-file names like ``2023_Q4`` say nothing about
    the group, and the folder name is never shown (it may be a test label).
    The header row is part of the key so that files with different schemas in
    one folder are never judged together.
    """
    groups = {}
    for pair in pairs:
        uuid = str(pair["uuid"])
        folder = uuid.rsplit("/", 1)[0] if "/" in uuid else ""
        key = (folder, pair["column"], tuple(pair.get("headers") or ()))
        groups.setdefault(key, []).append(pair)

    reps = []
    for key, members in groups.items():
        samples, seen = [], set()
        pools = [list((m.get("evidence") or {}).get("sample_values") or []) for m in members]
        while len(samples) < SAMPLES and any(pools):
            for pool in pools:
                while pool:
                    value = pool.pop(0)
                    if value not in seen:
                        seen.add(value)
                        samples.append(value)
                        break
                if len(samples) >= SAMPLES:
                    break
        titles = {m.get("title") for m in members}
        rep = dict(members[0])
        rep.update({
            "evidence": {**(members[0].get("evidence") or {}), "sample_values": samples},
            "entity_types": ",".join(sorted({t for m in members
                                             for t in str(m.get("entity_types") or "").split(",") if t})),
            "n_detections": sum(int(m.get("n_detections") or 0) for m in members),
            "title": titles.pop() if len(titles) == 1 else None,
            "group": key[0] or ".",
            "members": members,
        })
        reps.append(rep)
    return reps


def expand(results):
    """Give every member of a judged group its representative's verdict."""
    out = []
    for r in results:
        for member in r["members"]:
            evidence = dict(member.get("evidence") or {})
            evidence["tier3_group"] = f"{r['group']} / {r['column']} ({len(r['members'])} files)"
            out.append({**member, "evidence": evidence, "verdict": r["verdict"],
                        "trace": r["trace"], "error": r["error"]})
    return out


def apply(rows, verdicts):
    """Apply torows output to Tier 1's column rows.

    Keys compare as strings because one side may have been read back from CSV.
    """
    fields = ("pii_class", "tier", "rule_id", "rule_strength", "reason",
              "evidence_json", "classified_at")
    updates = {(str(v["uuid"]), str(v["lot"]), str(v["column"])): v
               for v in verdicts}
    out = []
    for row in rows:
        update = updates.get((str(row["uuid"]), str(row["lot"]), str(row["column"])))
        out.append({**row, **{f: update[f] for f in fields}} if update else dict(row))
    return out


def writeverdicts(path, results):
    """The model's verdict and reasoning per judged pair."""
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


def summarise(results):
    """Text report: how many pairs got each verdict."""
    counts = {}
    for r in results:
        counts[r["verdict"] or "undecided"] = counts.get(r["verdict"] or "undecided", 0) + 1
    width = max((len(k) for k in counts), default=0)
    lines = [f"Tier 3 judged {len(results)} pairs", ""]
    for key in sorted(counts, key=lambda k: -counts[k]):
        lines.append(f"  {key:<{width}}  {counts[key]:>5}")
    return "\n".join(lines)
