"""Scan a folder for PII, classify what turns up and redact it -- one command.

    run_pii_s3.py     scan     detectors + filters   -> pii_detections.csv, a summary
    pii_classify.py   Tier 1   rules                 -> false_positive / permissible / present / undecided
    (Tier 2)                   not built; Tier 3 takes the Tier 1 residual directly
    pii_tier3.py      Tier 3   local LLM judge       -> decides what Tier 1 left undecided
    generate_redacted.py       Presidio anonymizer   -> redacted copies of what is `present`

--path DIR scans that folder first and hands the result to the tiers, so a
folder goes from untouched to classified and redacted in one run. --csv DIR
starts from a scan someone already ran, and is what to use when the scan was
expensive enough that you do not want to repeat it.

Every stage runs in this process through the other scripts' own functions, so
each gets the same answer here as from ``run_pii_s3.py --path``,
``pii_classify.py --csv``, ``pii_tier3.py --csv`` and
``generate_redacted.py --run-dir`` run one after another. Nothing is written
to metadata.db or S3.

--output PATH is the result itself: one row per file with its final class
(present / permissible / false_positive). With --summary it is the scan
summary plus that class, so files with no detections or a read error are
listed too; without it, one row per file that had detections. The supporting
files below go to --out-dir, which defaults to --output's folder:

    tier1_column_class.csv   Tier 1 verdict per (file, column)
    tier1_report.txt         Tier 1 class / rule / context breakdown
    tier3_verdicts.csv       the model's verdict and reasoning per undecided pair
    column_class.csv         final verdict per (file, column), after both tiers
    dataset_class.csv        final verdict per file: the loudest column decides
    file_summary.csv         --summary only: the scan summary plus the final class
    redacted/                --redact only: the redacted copies and their log
    scan_summary.csv         --path only: one row per file scanned
    scan.log                 --path only: the scan's own log, per file

--path writes its pii_detections.csv into the folder it scans, beside the
data, because that is where the next run looks for it. Everything else the
pipeline produces goes to --out-dir.

--redact runs generate_redacted.py over the result: every column the tiers
ended up calling `present` is rewritten with Presidio's anonymizer, and a
copy of the file goes to --redact-dir under the same relative path. Columns
the tiers cleared are left alone and every row is redacted, not only the
first --max-rows the scan sampled. Nothing is uploaded; the originals are
not touched. Add --redact-copy-clean if you want --redact-dir to be a
complete copy of the folder rather than only the files that changed.

Tier 3 needs the vLLM judge serving on --endpoint. The server is checked
before any pair is sent, and if it is down the Tier 1 outputs are still
written and the script exits 2 -- rerun once the server is up, or pass
--no-llm to finish on Tier 1 alone (undecided pairs then stay undecided).


    python pii_test/pii_classify_pipeline.py --path DATA_DIR --out-dir OUT \\
        --redact
    python pii_test/pii_classify_pipeline.py --csv SCAN_DIR \\
        --summary SCAN_DIR/summary.csv --output OUT/pii_result.csv
    python pii_test/pii_classify_pipeline.py --csv SCAN_DIR --out-dir OUT \\
        --summary SCAN_DIR/summary.csv
    python pii_test/pii_classify_pipeline.py --csv SCAN_DIR --out-dir OUT --no-llm
    python pii_test/pii_classify_pipeline.py --csv pii_test/kcc/kcc-transcripts \\
        --out-dir OUT --summary pii_test/kcc/kcc_scan_summary.csv --judge-per-folder
    python pii_test/pii_classify_pipeline.py --csv SCAN_DIR --out-dir OUT \\
        --redact --redact-workers 3

--judge-per-folder is for folders that each hold one dataset split into files,
like KCC's per-state quarterly exports: Tier 3 judges each (folder, column,
header row) once and gives every file in it that verdict. Tier 1 still runs
per file. Do not use it where a folder mixes unrelated datasets.
"""

import argparse
import csv
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pii_classify as tier1  # noqa: E402
import pii_tier3 as tier3  # noqa: E402

# Per-file classes for scan-summary rows that have no column verdict.
NO_DETECTIONS = "no_detections"
SCAN_ERROR = "scan_error"
# rollup_datasets' columns, for a header-only --output when nothing was found.
DATASET_FIELDS = ["uuid", "lot", "pii_class", "n_columns", "n_detections",
                  "rule_ids", "dataset_context"]


def server_problem(endpoint, model):
    """Why Tier 3 cannot run against this endpoint, or None if it can."""
    parts = urllib.parse.urlsplit(endpoint)
    models_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/v1/models", "", ""))
    try:
        with urllib.request.urlopen(models_url, timeout=5) as response:
            served = [m.get("id") for m in json.load(response).get("data", [])]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return f"no LLM server at {models_url} ({exc})"
    if served and model not in served:
        return f"{models_url} serves {', '.join(served)}, not --model {model}"
    return None


def inside(path, parent):
    path, parent = os.path.abspath(path), os.path.abspath(parent)
    return os.path.commonpath([path, parent]) == parent


def with_final_class(summary_path, datasets):
    """Scan-summary rows with the final per-file class appended.

    Summary ``file`` paths are relative to the scanned folder and dataset
    uuids are relative to --csv, so they line up when --csv is that folder.
    Returns (rows, number of files with detections but no verdict).
    """
    by_file = {d["uuid"]: d for d in datasets}
    with open(summary_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    unmatched = 0
    for row in rows:
        verdict = by_file.get(row.get("file", "").replace(os.sep, "/"))
        if verdict:
            row["final_pii_class"] = verdict["pii_class"]
            row["class_columns"] = verdict["n_columns"]
            row["class_rule_ids"] = verdict["rule_ids"]
            continue
        if row.get("error"):
            row["final_pii_class"] = SCAN_ERROR
        else:
            row["final_pii_class"] = NO_DETECTIONS
            if str(row.get("entity_count") or "0") not in ("0", ""):
                unmatched += 1
        row["class_columns"] = 0
        row["class_rule_ids"] = ""
    return rows, unmatched


def write_csv(path, rows, fieldnames=None):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def scan_step(args, log_path):
    """Run the detection scan over --path and write its summary to --out-dir.

    Imported here rather than at the top: run_pii_s3 loads torch, spaCy and
    the transformer recognizer, which a --csv run never needs. Importing it
    also repoints the root logger at pii_s3.log -- 65MB of LOT 1 history that
    the frequency blocklist build reads -- so this run takes it back and logs
    to its own file, with the same lines on stderr to watch.
    """
    import run_pii_s3 as scan

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stderr)],
        force=True,
    )
    logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)

    print(f"Scanning {args.path} ({args.workers} worker(s), "
          f"{'GPU' if args.gpu else 'CPU'}, {args.max_rows} rows/file)",
          file=sys.stderr)
    if args.workers > 1:
        # Spawned workers re-run run_pii_s3's configure_logging, which is
        # file-only, so their per-file lines never reach this terminal.
        print(f"per-file progress: tail -f {log_path}", file=sys.stderr)
    return scan.scan_folder(
        args.path, summary_out=args.summary, worker_count=args.workers,
        use_gpu=args.gpu, max_rows=args.max_rows, limit=args.max_files,
        log_path=log_path)


def redact_step(args, rows):
    """Rewrite the classified columns and copy the files under --redact-dir.

    Imported here rather than at the top: generate_redacted pulls in torch,
    boto3 and presidio_anonymizer, which a run without --redact never needs.
    """
    import generate_redacted as redact

    classes = tuple(c.strip() for c in args.redact_classes.split(",") if c.strip())
    targets = redact.targets_from_rows(rows, classes)
    # permissible and false_positive are meant to survive redaction; an
    # undecided column is one nothing ruled on, so say so rather than let it
    # slip out with the corpus.
    undecided = sum(1 for r in rows if r["pii_class"] == "undecided")
    if undecided and "undecided" not in classes:
        print(f"\nnot redacting {undecided} undecided column(s) -- add "
              f"undecided to --redact-classes to include them", file=sys.stderr)
    if not targets:
        print(f"nothing classified {'/'.join(classes)}; no file redacted",
              file=sys.stderr)
        return
    print(f"\nRedacting {sum(len(c) for _, _, c in targets)} column(s) in "
          f"{len(targets)} file(s)", file=sys.stderr)
    redact.redact_to_dir(
        targets, args.redact_dir, use_gpu=args.redact_gpu,
        workers=args.redact_workers, max_rows=args.redact_max_rows or None,
        copy_clean_root=redact.scan_root(args.csv) if args.redact_copy_clean else None)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", metavar="DIR",
                        help="scan this folder first, then classify what it finds; "
                             "use --csv instead to start from a finished scan")
    parser.add_argument("--csv", metavar="PATH", nargs="+",
                        help="the scanned folder, or its pii_detections.csv files")
    parser.add_argument("--max-rows", type=int, default=250, metavar="N",
                        help="--path only: rows sampled per file (default: %(default)s)")
    parser.add_argument("--max-files", type=int, metavar="N",
                        help="--path only: scan just the first N files, for a trial run")
    parser.add_argument("--workers", type=int, default=1, metavar="N",
                        help="--path only: scan processes; 3 is this box's ceiling")
    parser.add_argument("--gpu", action="store_true",
                        help="--path only: scan on the GPU; off by default because "
                             "the Tier 3 judge holds the card")
    parser.add_argument("--output", metavar="CSV",
                        help="final class per file (present / permissible / "
                             "false_positive); with --summary, the scan summary "
                             "plus that class")
    parser.add_argument("--out-dir", metavar="DIR",
                        help="where the supporting outputs go (default: --output's "
                             "folder); must not be inside a --csv folder")
    parser.add_argument("--summary", metavar="CSV",
                        help="the scan's --summary-out file, to add the final class per file")
    parser.add_argument("--no-llm", action="store_true",
                        help="stop after Tier 1; undecided pairs stay undecided")
    parser.add_argument("--redact", action="store_true",
                        help="write redacted copies of the columns the tiers "
                             "classified (see --redact-classes)")
    parser.add_argument("--redact-dir", metavar="DIR",
                        help="where the redacted copies go (default: "
                             "<out-dir>/redacted); must not be inside a --csv folder")
    parser.add_argument("--redact-classes", default="present", metavar="LIST",
                        help="which column classes to redact (default: %(default)s)")
    parser.add_argument("--redact-workers", type=int, default=1, metavar="N",
                        help="redaction processes (default: 1)")
    parser.add_argument("--redact-max-rows", type=int, default=0, metavar="N",
                        help="stop redacting each file after N rows -- for a quick "
                             "look; the default 0 redacts every row")
    parser.add_argument("--redact-copy-clean", action="store_true",
                        help="also copy the files that needed no redaction, so "
                             "--redact-dir is a full copy of the scanned folder")
    parser.add_argument("--redact-gpu", action="store_true",
                        help="redact on the GPU; off by default because the Tier 3 "
                             "judge holds the card")
    parser.add_argument("--judge-per-folder", action="store_true",
                        help="Tier 3 judges each (folder, column, header row) once; "
                             "only for folders holding one dataset split into files")
    parser.add_argument("--limit", type=int,
                        help="Tier 3 judges only the first N undecided pairs (dry run)")
    parser.add_argument("--endpoint", default=tier3.ENDPOINT)
    parser.add_argument("--model", default=tier3.MODEL)
    parser.add_argument("--max-tokens", type=int, default=tier3.MAX_TOKENS)
    parser.add_argument("--presence-penalty", type=float, default=0.0,
                        help="Qwen3 recommends 1.5 against repetition loops")
    args = parser.parse_args()

    if bool(args.path) == bool(args.csv):
        parser.error("give --path to scan a folder, or --csv to start from a "
                     "scan that already ran -- not both")
    if args.path and not os.path.isdir(args.path):
        parser.error(f"--path {args.path} is not a folder")
    if args.path and args.summary:
        parser.error("--path writes its own summary; drop --summary")
    if not (args.output or args.out_dir):
        parser.error("give --output, --out-dir, or both")
    if args.out_dir is None:
        args.out_dir = os.path.dirname(args.output) or "."
    if args.path:
        # The scan's own outputs land in --out-dir, and the folder it scanned
        # becomes the tiers' input. --summary is then the scan's summary: the
        # two agree by construction, which is what the --csv path has to be
        # told by hand.
        args.csv = [args.path]
        args.summary = os.path.join(args.out_dir, "scan_summary.csv")

    if args.redact and not args.redact_dir:
        args.redact_dir = os.path.join(args.out_dir, "redacted")

    # A later scan of that folder would read these outputs as datasets:
    # run_pii_s3 only skips its own detection and summary files.
    destinations = [("--out-dir", args.out_dir)]
    if args.output:
        destinations.insert(0, ("--output", os.path.dirname(args.output) or "."))
    if args.redact:
        destinations.append(("--redact-dir", args.redact_dir))
    for path in args.csv:
        folder = path if os.path.isdir(path) else os.path.dirname(path) or "."
        for flag, where in destinations:
            if inside(where, folder):
                parser.error(f"{flag} {where} is inside the scanned folder "
                             f"{folder}; a rescan would treat the outputs as data")
    os.makedirs(args.out_dir, exist_ok=True)

    def out(name):
        return os.path.join(args.out_dir, name)

    # -- Scan ----------------------------------------------------------------
    if args.path:
        files, _ = scan_step(args, out("scan.log"))
        if not files:
            print(f"no data file under {args.path}; nothing to classify",
                  file=sys.stderr)
            return 1

    # -- Tier 1 --------------------------------------------------------------
    detections, metadata = tier1.load_csv(args.csv)
    print(f"Tier 1: {len(detections)} detections over {len(metadata)} files",
          file=sys.stderr)
    if detections:
        rows = tier1.with_file_context(
            tier1.classify_detections(detections, metadata), metadata)
        report = tier1.summarise(rows)
        tier1.write_rows_csv(out("tier1_column_class.csv"), rows)
        with open(out("tier1_report.txt"), "w", encoding="utf-8") as handle:
            handle.write(report + "\n")
        print(report)
    else:
        rows = []
        print("nothing to classify", file=sys.stderr)

    # -- Tier 3 --------------------------------------------------------------
    final = rows
    pairs = tier3.pairs_from_class_rows(rows, args.limit) if rows else []
    if pairs and not args.no_llm:
        problem = server_problem(args.endpoint, args.model)
        if problem:
            print(f"\nTier 3 not run: {problem}.\nTier 1 results are in "
                  f"{args.out_dir}. Start the judge and rerun, or pass --no-llm "
                  f"to finish with {len(pairs)} pair(s) undecided.", file=sys.stderr)
            return 2

        real_headers = sum(1 for p in pairs if p["headers_source"] != "detected_columns")
        print(f"\nTier 3: {len(pairs)} undecided pair(s) "
              f"({real_headers} with the file's header row)", file=sys.stderr)
        if args.judge_per_folder:
            pairs = tier3.group_pairs(pairs)
            print(f"judging them as {len(pairs)} (folder, column) group(s)",
                  file=sys.stderr)
        client = tier3.VLLMClient(args.endpoint, args.model, args.max_tokens,
                                  presence_penalty=args.presence_penalty)

        def progress(i, total, result):
            mark = result["verdict"] or f"UNDECIDED ({result['error']})"
            where = (f"{result['group']} ({len(result['members'])} files)"
                     if "members" in result else result["uuid"])
            print(f"[{i}/{total}] {where[:40]:<40} "
                  f"{result['column'][:30]:<30} {mark}", file=sys.stderr, flush=True)

        try:
            results = tier3.judge(pairs, client, progress=progress)
        except tier3.ServerGaveUp as exc:
            print(f"\nTier 3 aborted: {exc}\nTier 1 results are in {args.out_dir}.",
                  file=sys.stderr)
            return 1
        print()
        print(tier3.summarise(results))
        if args.judge_per_folder:
            results = tier3.expand_group_results(results)
        tier3.write_verdicts_csv(out("tier3_verdicts.csv"), results)
        final = tier3.apply_verdicts(rows, tier3.to_rows(results))
    elif pairs:
        print(f"\n--no-llm: {len(pairs)} pair(s) left undecided", file=sys.stderr)
    elif rows:
        print("\nTier 1 left nothing undecided; Tier 3 not needed", file=sys.stderr)

    # -- Final outputs -------------------------------------------------------
    datasets = tier1.rollup_datasets(final) if final else []
    if final:
        write_csv(out("column_class.csv"), final)
        write_csv(out("dataset_class.csv"), datasets)

    summary_rows = []
    if args.summary:
        summary_rows, unmatched = with_final_class(args.summary, datasets)
        if summary_rows:
            write_csv(out("file_summary.csv"), summary_rows)
        if unmatched:
            print(f"\nwarning: {unmatched} file(s) in {args.summary} have detections "
                  f"but no verdict -- pass the scanned folder itself as --csv so "
                  f"the paths line up", file=sys.stderr)

    if args.redact:
        redact_step(args, final)

    print("\nFinal class per file")
    for name, count in Counter(d["pii_class"] for d in datasets).most_common():
        print(f"  {name:<16} {count:>6}")
    if args.output:
        if os.path.dirname(args.output):
            os.makedirs(os.path.dirname(args.output), exist_ok=True)
        if args.summary:
            write_csv(args.output, summary_rows)
        else:
            write_csv(args.output, datasets, fieldnames=DATASET_FIELDS)
        print(f"\nresult: {args.output}", file=sys.stderr)
    print(f"outputs in {args.out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
