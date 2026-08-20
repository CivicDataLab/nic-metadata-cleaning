"""
Measure what the improved filters do to the existing LOT 2 detections.

Replays every row of pii_detections_lot2 through the new column selection and
the new entity filters, and reports what survives and why. This is a *replay*,
not a re-scan: it cannot show detections the old pipeline missed (Bug B's
silent false negatives), so it measures precision only. Recall needs the
labelled set -- see --write-label-template.

Usage:
    # Corpus-wide before/after, with the reasons things were dropped
    python pii_test/evaluate_filters.py

    # One dataset, detection by detection
    python pii_test/evaluate_filters.py --uuid 00215472-af1c-48c3-8009-2f524dd22a19

    # What survives, so the next round of vocabulary work has a target list
    python pii_test/evaluate_filters.py --survivors 40

    # Scaffold for hand-labelling; fill in the has_pii column by inspection
    python pii_test/evaluate_filters.py --write-label-template labels.csv --sample 200
"""

import argparse
import logging
import os
import sys

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pii_filters import filter_detection, rejection_reason  # noqa: E402
from pii_utils import classify_column_name  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

DB_PATH = "transformation/metadata.db"
DETECTIONS_TABLE = "pii_detections_lot2"
DETECTIONS_BASELINE = "pii_detections_lot2_baseline"
METADATA_TABLE = "remain_raw_metadata"
METADATA_BASELINE = "remain_raw_metadata_pii_baseline"

# The dataset the whole exercise started from: an aggregate table of school
# infrastructure counts that produced 21 detections, all false.
REFERENCE_UUID = "00215472-af1c-48c3-8009-2f524dd22a19"


def verdict(column, entity_text, entity_type, source, score):
    """Replay one detection. Returns (kept, reason)."""
    decision, why = classify_column_name(column)
    if decision == "skip":
        return False, f"column: {why}"
    detection = {"entity_type": entity_type, "entity_text": entity_text,
                 "score": score, "source": source}
    if not filter_detection(detection):
        if entity_type == "PERSON":
            return False, f"entity: {rejection_reason(entity_text) or 'score/length'}"
        return False, f"entity: invalid {entity_type.lower()}"
    return True, "survives"


def load(conn, uuid=None):
    where, params = ("WHERE uuid = ?", [uuid]) if uuid else ("", [])
    return conn.execute(f"""
        SELECT uuid, ministry, "column", entity_text, entity_type, source,
               AVG(score) AS score, COUNT(*) AS n
        FROM {DETECTIONS_TABLE} {where}
        GROUP BY 1,2,3,4,5,6
    """, params).fetchall()


def report_corpus(rows, survivor_limit):
    total = sum(r[7] for r in rows)
    if not total:
        logging.warning("No detections to evaluate.")
        return

    dropped_reasons, survivors, kept_total = {}, {}, 0
    for _uuid, _min, column, text, etype, source, score, n in rows:
        kept, reason = verdict(column, text, etype, source, score)
        if kept:
            kept_total += n
            survivors[(column, text)] = survivors.get((column, text), 0) + n
        else:
            dropped_reasons[reason] = dropped_reasons.get(reason, 0) + n

    logging.info("=" * 72)
    logging.info(f"Baseline detections   {total:>10,}")
    logging.info(f"Surviving             {kept_total:>10,}   {100 * kept_total / total:5.1f}%")
    logging.info(f"Removed               {total - kept_total:>10,}   "
                 f"{100 * (total - kept_total) / total:5.1f}%")
    logging.info("=" * 72)
    logging.info("Removed by:")
    for reason, n in sorted(dropped_reasons.items(), key=lambda kv: -kv[1]):
        logging.info(f"  {n:>10,}  {100 * n / total:5.1f}%  {reason}")

    if survivor_limit and survivors:
        logging.info("")
        logging.info(f"Top {survivor_limit} surviving (column, text) pairs -- "
                     f"the target list for the next vocabulary pass:")
        for (column, text), n in sorted(survivors.items(), key=lambda kv: -kv[1])[:survivor_limit]:
            logging.info(f"  {n:>7,}  {column!r:36} {text!r}")


def report_dataset(rows, uuid):
    if not rows:
        logging.info(f"{uuid}: no detections in {DETECTIONS_TABLE}")
        return
    total = sum(r[7] for r in rows)
    kept_total = 0
    logging.info(f"{uuid}: {total} detection(s)")
    logging.info(f"  {'count':>6}  {'column':<32} {'text':<36} verdict")
    for _uuid, _min, column, text, etype, source, score, n in sorted(rows, key=lambda r: -r[7]):
        kept, reason = verdict(column, text, etype, source, score)
        kept_total += n if kept else 0
        logging.info(f"  {n:>6}  {column!r:<32} {text!r:<36} "
                     f"{'KEEP' if kept else 'drop'} ({reason})")
    logging.info(f"  => {kept_total} of {total} survive")


def write_label_template(conn, path, sample_size):
    """Write a hand-labelling scaffold: one row per dataset, has_pii blank.

    Sampling is deterministic (ordered by uuid hash) so the same set comes
    back on re-run and labels stay valid.
    """
    rows = conn.execute(f"""
        WITH scanned AS (
            SELECT uuid, ministry_folder, pii_detected
            FROM {METADATA_TABLE}
            WHERE pii_tested = TRUE
        ),
        counts AS (
            SELECT uuid, COUNT(*) AS baseline_detections
            FROM {DETECTIONS_TABLE} GROUP BY uuid
        )
        SELECT s.uuid, s.ministry_folder, s.pii_detected,
               COALESCE(c.baseline_detections, 0) AS baseline_detections
        FROM scanned s LEFT JOIN counts c USING (uuid)
        ORDER BY hash(s.uuid)
        LIMIT ?
    """, [sample_size]).fetchall()

    have_reference = any(r[0] == REFERENCE_UUID for r in rows)
    if not have_reference:
        ref = conn.execute(f"""
            SELECT uuid, ministry_folder, pii_detected,
                   (SELECT COUNT(*) FROM {DETECTIONS_TABLE} d WHERE d.uuid = m.uuid)
            FROM {METADATA_TABLE} m WHERE uuid = ?
        """, [REFERENCE_UUID]).fetchall()
        rows = ref + rows

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("uuid,ministry,baseline_pii_detected,baseline_detections,has_pii,notes\n")
        for uuid, ministry, detected, n in rows:
            fh.write(f"{uuid},{ministry},{detected},{n},,\n")
    logging.info(f"Wrote {len(rows)} rows to {path}")
    logging.info("Fill in has_pii (yes/no) by inspecting each dataset, then re-run "
                 "with --labels to score precision and recall.")


def score_against_labels(conn, path):
    """Score the dataset-level flag against hand labels."""
    labels = {}
    with open(path, encoding="utf-8") as fh:
        header = fh.readline().strip().split(",")
        try:
            i_uuid, i_has = header.index("uuid"), header.index("has_pii")
        except ValueError:
            raise SystemExit("Label file needs 'uuid' and 'has_pii' columns")
        for line in fh:
            parts = line.rstrip("\n").split(",")
            value = parts[i_has].strip().lower()
            if value in ("yes", "y", "true", "1"):
                labels[parts[i_uuid]] = True
            elif value in ("no", "n", "false", "0"):
                labels[parts[i_uuid]] = False

    if not labels:
        raise SystemExit(f"No filled-in labels found in {path}")

    tp = fp = fn = tn = 0
    for uuid, truth in labels.items():
        rows = load(conn, uuid)
        predicted = any(verdict(c, t, e, s, sc)[0] for _u, _m, c, t, e, s, sc, _n in rows)
        if truth and predicted:
            tp += 1
        elif truth and not predicted:
            fn += 1
        elif not truth and predicted:
            fp += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    logging.info(f"Labelled datasets: {len(labels)}")
    logging.info(f"  TP {tp}  FP {fp}  FN {fn}  TN {tn}")
    logging.info(f"  precision {precision:.3f}   recall {recall:.3f}")
    if fn:
        logging.warning(f"{fn} dataset(s) with known PII are no longer flagged -- "
                        f"recall regressions matter more than precision gains here.")


def compare_baseline(conn):
    """Per-ministry detections and flags, before vs after a re-scan."""
    tables = {t[0] for t in conn.execute("SHOW TABLES").fetchall()}
    if DETECTIONS_BASELINE not in tables:
        raise SystemExit(f"{DETECTIONS_BASELINE} does not exist -- "
                         f"run reset_lot2_run.py before re-scanning")

    rows = conn.execute(f"""
        WITH before AS (
            SELECT ministry, COUNT(*) AS n, COUNT(DISTINCT uuid) AS datasets
            FROM {DETECTIONS_BASELINE} GROUP BY ministry
        ),
        after AS (
            SELECT ministry, COUNT(*) AS n, COUNT(DISTINCT uuid) AS datasets
            FROM {DETECTIONS_TABLE} GROUP BY ministry
        )
        SELECT COALESCE(b.ministry, a.ministry) AS ministry,
               COALESCE(b.n, 0), COALESCE(a.n, 0),
               COALESCE(b.datasets, 0), COALESCE(a.datasets, 0)
        FROM before b FULL OUTER JOIN after a USING (ministry)
        ORDER BY 2 DESC
    """).fetchall()

    logging.info(f"{'ministry':<62} {'before':>10} {'after':>10} {'change':>9}")
    logging.info("-" * 95)
    tot_b = tot_a = 0
    for ministry, b, a, db, da in rows:
        tot_b += b
        tot_a += a
        change = f"{100 * (a - b) / b:+.1f}%" if b else "new"
        logging.info(f"{(ministry or '(none)'):<62} {b:>10,} {a:>10,} {change:>9}"
                     f"   [{db}->{da} datasets]")
    logging.info("-" * 95)
    total_change = f"{100 * (tot_a - tot_b) / tot_b:+.1f}%" if tot_b else "new"
    logging.info(f"{'TOTAL':<62} {tot_b:>10,} {tot_a:>10,} {total_change:>9}")

    if METADATA_BASELINE in tables:
        flags = conn.execute(f"""
            SELECT
                SUM(CASE WHEN b.pii_detected THEN 1 ELSE 0 END),
                SUM(CASE WHEN m.pii_detected THEN 1 ELSE 0 END),
                COUNT(*)
            FROM {METADATA_BASELINE} b JOIN {METADATA_TABLE} m USING (uuid)
            WHERE m.pii_tested = TRUE
        """).fetchone()
        before_flagged, after_flagged, compared = flags
        logging.info("")
        logging.info(f"Dataset-level flags over {compared:,} re-scanned datasets: "
                     f"{before_flagged:,} -> {after_flagged:,} flagged")


def main():
    parser = argparse.ArgumentParser(
        description="Replay LOT 2 detections through the improved filters.")
    parser.add_argument("--compare-baseline", action="store_true",
                        help="After a re-scan: per-ministry detections and flags, before vs after")
    parser.add_argument("--uuid", help="Evaluate one dataset, detection by detection")
    parser.add_argument("--reference", action="store_true",
                        help=f"Shorthand for --uuid {REFERENCE_UUID}")
    parser.add_argument("--survivors", type=int, default=25,
                        help="How many surviving (column, text) pairs to list (0 to skip)")
    parser.add_argument("--write-label-template", metavar="PATH",
                        help="Write a hand-labelling scaffold and exit")
    parser.add_argument("--sample", type=int, default=200,
                        help="Datasets to include in the label template")
    parser.add_argument("--labels", metavar="PATH",
                        help="Score the flag against a filled-in label file")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        raise SystemExit(f"Database not found: {DB_PATH} (run from the repo root)")

    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        if args.write_label_template:
            write_label_template(conn, args.write_label_template, args.sample)
            return
        if args.labels:
            score_against_labels(conn, args.labels)
            return
        if args.compare_baseline:
            compare_baseline(conn)
            return

        uuid = REFERENCE_UUID if args.reference else args.uuid
        if uuid:
            report_dataset(load(conn, uuid), uuid)
        else:
            report_corpus(load(conn), args.survivors)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
