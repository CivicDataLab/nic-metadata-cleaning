"""
Calculate token usage and cost from a batch output JSONL file.

Usage:
  python token_usage.py <batch_output.jsonl>
  python token_usage.py                        # scans all batch_output_*.jsonl in this directory
"""

import argparse
import glob
import json
import os

# gpt-4.1-nano batch pricing ($/1M tokens)
PRICING = {
    "input":  0.05,
    "cached": 0.025,   
    "output": 0.20,
}


def analyse_file(path: str) -> dict:
    total_prompt    = 0
    total_cached    = 0
    total_output    = 0
    failed          = 0
    count           = 0

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            # Failed requests have no usage
            if obj.get("error") or obj["response"]["status_code"] != 200:
                failed += 1
                continue

            usage = obj["response"]["body"].get("usage", {})
            prompt_details = usage.get("prompt_tokens_details", {})

            total_prompt += usage.get("prompt_tokens", 0)
            total_cached += prompt_details.get("cached_tokens", 0)
            total_output += usage.get("completion_tokens", 0)
            count += 1

    non_cached = total_prompt - total_cached

    input_cost  = non_cached   * PRICING["input"]  / 1_000_000
    cached_cost = total_cached * PRICING["cached"] / 1_000_000
    output_cost = total_output * PRICING["output"] / 1_000_000
    total_cost  = input_cost + cached_cost + output_cost

    return {
        "file":          os.path.basename(path),
        "requests_ok":   count,
        "requests_failed": failed,
        "prompt_tokens": total_prompt,
        "cached_tokens": total_cached,
        "output_tokens": total_output,
        "total_tokens":  total_prompt + total_output,
        "avg_prompt":    round(total_prompt / count) if count else 0,
        "avg_output":    round(total_output / count) if count else 0,
        "input_cost":    input_cost,
        "cached_cost":   cached_cost,
        "output_cost":   output_cost,
        "total_cost":    total_cost,
    }


def print_report(r: dict) -> None:
    print(f"\n{'='*60}")
    print(f"File    : {r['file']}")
    print(f"{'='*60}")
    print(f"Requests: {r['requests_ok']} ok  |  {r['requests_failed']} failed")
    print()
    print(f"{'Token breakdown':<30} {'Count':>12}")
    print(f"{'-'*44}")
    print(f"{'Prompt (total)':<30} {r['prompt_tokens']:>12,}")
    print(f"{'  of which cached':<30} {r['cached_tokens']:>12,}")
    print(f"{'  of which non-cached':<30} {r['prompt_tokens']-r['cached_tokens']:>12,}")
    print(f"{'Output':<30} {r['output_tokens']:>12,}")
    print(f"{'Total':<30} {r['total_tokens']:>12,}")
    print()
    print(f"{'Averages per request':<30}")
    print(f"  Avg prompt tokens : {r['avg_prompt']:,}")
    print(f"  Avg output tokens : {r['avg_output']:,}")
    print()
    print(f"{'Cost breakdown (Batch API)':<30} {'USD':>12}")
    print(f"{'-'*44}")
    print(f"{'Input (non-cached)':<30} ${r['input_cost']:>11.4f}")
    print(f"{'Input (cached)':<30} ${r['cached_cost']:>11.4f}")
    print(f"{'Output':<30} ${r['output_cost']:>11.4f}")
    print(f"{'TOTAL':<30} ${r['total_cost']:>11.4f}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Token usage and cost report for batch output JSONL files")
    parser.add_argument("files", nargs="*", help="Path(s) to batch output JSONL file(s)")
    args = parser.parse_args()

    files = args.files
    if not files:
        here = os.path.dirname(os.path.abspath(__file__))
        files = sorted(glob.glob(os.path.join(here, "batch_output_*.jsonl")))
        if not files:
            print("No batch_output_*.jsonl files found in current directory.")
            return

    grand = {k: 0 for k in ("requests_ok", "requests_failed", "prompt_tokens",
                              "cached_tokens", "output_tokens", "total_tokens",
                              "input_cost", "cached_cost", "output_cost", "total_cost")}

    for path in files:
        r = analyse_file(path)
        print_report(r)
        for k in grand:
            grand[k] += r[k]

    if len(files) > 1:
        print(f"\n{'='*60}")
        print(f"GRAND TOTAL ({len(files)} files)")
        print(f"{'='*60}")
        print(f"Requests : {grand['requests_ok']:,} ok  |  {grand['requests_failed']} failed")
        print(f"Tokens   : {grand['total_tokens']:,}  (prompt {grand['prompt_tokens']:,} / output {grand['output_tokens']:,})")
        print(f"Cached   : {grand['cached_tokens']:,}")
        print(f"Cost     : ${grand['total_cost']:.4f}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
