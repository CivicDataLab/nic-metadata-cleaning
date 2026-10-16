"""
Run the LLM batch classifier over an explicit list of nids from a text file
(one nid per line) instead of a batch partition.

Reuses the batch machinery in llm_batch_classifier.py. Only nids not already
present in the results table are submitted to the API (append-only, no dedup),
then a deduped CSV of every requested nid is exported from the results table.

Usage:
    python run_nids_classifier.py <nids_file> [--out <csv_path>] [--force]
"""
import argparse
import logging
import os

import duckdb
import pandas as pd

import llm_batch_classifier as bc


def read_nids(path: str) -> list[int]:
    with open(path, encoding="utf-8") as f:
        return [int(line.strip()) for line in f if line.strip()]


def already_done(con, nids: list[int]) -> set[int]:
    """nids that already have a row in the results table."""
    table_exists = con.execute(
        f"SELECT COUNT(*) FROM information_schema.tables "
        f"WHERE table_name = '{bc.RESULTS_TABLE}'"
    ).fetchone()[0]
    if not table_exists:
        return set()
    ph = ", ".join(str(n) for n in nids)
    rows = con.execute(
        f"SELECT DISTINCT CAST(nid AS BIGINT) FROM {bc.RESULTS_TABLE} "
        f"WHERE CAST(nid AS BIGINT) IN ({ph})"
    ).fetchall()
    return {r[0] for r in rows}


def load_rows_for_nids(con, nids: list[int]) -> pd.DataFrame:
    """Select source rows for the given nids (no OFFSET/partition logic)."""
    available = [
        r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{bc.SOURCE_TABLE}'"
        ).fetchall()
    ]
    available_lower = {c.lower(): c for c in available}
    cols = [
        f'"{available_lower[c.lower()]}" AS "{c}"'
        for c in bc.SOURCE_FIELDS
        if c.lower() in available_lower
    ]
    ph = ", ".join(str(n) for n in nids)
    df = con.execute(
        f"SELECT {', '.join(cols)} FROM {bc.SOURCE_TABLE} "
        f"WHERE nid IN ({ph})"
    ).fetchdf()
    logging.info(f"Loaded {len(df)} source rows for {len(nids)} nid(s)")
    return df


def export_csv(con, nids: list[int], out_path: str) -> int:
    """Write a deduped CSV of results for every requested nid."""
    ph = ", ".join(str(n) for n in nids)
    df = con.execute(
        f"SELECT * FROM {bc.RESULTS_TABLE} "
        f"WHERE CAST(nid AS BIGINT) IN ({ph}) "
        f"QUALIFY row_number() OVER (PARTITION BY CAST(nid AS BIGINT) ORDER BY nid) = 1"
    ).fetchdf()
    df.to_csv(out_path, index=False, encoding="utf-8")
    logging.info(f"Wrote {len(df)} deduped rows to {out_path}")
    return len(df)


def main():
    parser = argparse.ArgumentParser(description="LLM batch classifier over an explicit nid list or a merge_method flag")
    parser.add_argument("nids_file", nargs="?", help="Text file with one nid per line")
    parser.add_argument("--merge-method", default=None,
                        help="Instead of a file, pull nids WHERE merge_method = this value (e.g. 'non-mergeable')")
    parser.add_argument("--out", default=None, help="Output CSV path")
    parser.add_argument("--force", action="store_true", help="Re-run nids even if already in the results table")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--concurrent", action="store_true",
                        help="Submit all chunks up front and poll together (faster, but large "
                             "runs may trip OpenAI's enqueued-token limit). Default is sequential.")
    args = parser.parse_args()

    if bool(args.nids_file) == bool(args.merge_method):
        parser.error("provide exactly one of: <nids_file> or --merge-method")

    con = duckdb.connect(bc.DB_PATH)

    if args.merge_method:
        nids = [r[0] for r in con.execute(
            f"SELECT nid FROM {bc.SOURCE_TABLE} WHERE merge_method = ? AND nid IS NOT NULL",
            [args.merge_method],
        ).fetchall()]
        default_out = f"{args.merge_method.replace('-', '_')}_llm_output.csv"
        logging.info(f"Pulled {len(nids)} nid(s) with merge_method='{args.merge_method}'")
    else:
        nids = read_nids(args.nids_file)
        default_out = os.path.splitext(args.nids_file)[0] + "_llm_output.csv"

    out_path = args.out or default_out

    found = {r[0] for r in con.execute(
        f"SELECT nid FROM {bc.SOURCE_TABLE} WHERE nid IN ({', '.join(map(str, nids))})"
    ).fetchall()}
    missing_from_db = [n for n in nids if n not in found]
    if missing_from_db:
        logging.warning(f"{len(missing_from_db)} nid(s) not in {bc.SOURCE_TABLE}: {missing_from_db}")

    done = set() if args.force else already_done(con, nids)
    todo = [n for n in nids if n in found and n not in done]

    logging.info(
        f"{len(nids)} requested | {len(done)} already in results | "
        f"{len(todo)} to submit | out={out_path}"
    )

    if todo:
        df = load_rows_for_nids(con, todo)
        con.close()  # release the DB lock before merge_and_save reopens it

        chunks = [df.iloc[i:i + args.chunk_size] for i in range(0, len(df), args.chunk_size)]

        if args.concurrent:
            # Submit every chunk up front, then poll them together. Faster, but on
            # large runs the requests in flight can exceed OpenAI's enqueued-token
            # limit and one batch will fail at enqueue (total=0). Re-run to recover
            # the missing nids (dedup skips the ones that merged). Opt-in only.
            batch_ids: list[str] = []
            for i, chunk in enumerate(chunks, 1):
                batch_ids.extend(bc._submit_with_autosplit(chunk, suffix=f"_chunk{i}"))
            logging.info(f"Submitted {len(batch_ids)} batch(es) concurrently across {len(chunks)} chunk(s): {batch_ids} — polling...")
            results: dict[str, dict] = {}
            for batch in bc.poll_all_batches(batch_ids):
                results.update(bc.download_results(batch))
            bc.merge_and_save(df, results)
        else:
            # Default: submit -> poll -> merge one chunk at a time. Only one batch is
            # ever in flight, so the enqueued-token limit can't be tripped, and each
            # completed chunk is persisted before the next is submitted (a mid-run
            # failure only loses the in-flight chunk).
            for i, chunk in enumerate(chunks, 1):
                batch_ids = bc._submit_with_autosplit(chunk, suffix=f"_chunk{i}")
                logging.info(f"Chunk {i}/{len(chunks)} ({len(chunk)} rows): submitted {batch_ids} — polling...")
                results = {}
                for batch in bc.poll_all_batches(batch_ids):
                    results.update(bc.download_results(batch))
                bc.merge_and_save(chunk, results)

        con = duckdb.connect(bc.DB_PATH)
    else:
        logging.info("Nothing new to submit — all requested nids already have results.")

    n = export_csv(con, [n for n in nids if n in found], out_path)
    con.close()
    logging.info(f"Done. {n} rows in {out_path}")
    print(f"\nOutput CSV -> {out_path} ({n} rows)")


if __name__ == "__main__":
    main()
