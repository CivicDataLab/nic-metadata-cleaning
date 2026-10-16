#!/usr/bin/env bash
# Download the lot 2 (dublin_core_remaining) files that are on neither S3 nor this
# server. The worklist is data/lot2_download_worklist.csv (built 2026-10-08: rows with
# no file under s3://nic-ogdp-datasets/downloaded-datasets/ministry-*/ and not on
# data/undownloadable_datasets_20260915.csv).
#
# The download log is also the resume source, so a row that failed only because no
# JWT could be minted (captcha endpoint down) would be skipped forever. Between
# passes those rows are dropped from the log and tried again.
#
#   setsid nohup scripts/lot2_download_missing.sh > /dev/null 2>&1 &
#   tail -f data/lot2_download_status.log
set -u
cd "$(dirname "$0")/.."

WORK=data/lot2_download_worklist.csv
OUT=data/lot2_downloads
LOG=data/lot2_download_log.csv
RUN=data/lot2_download_run.log
STATUS=data/lot2_download_status.log
DONE=data/lot2_download.done
CAPTCHA='https://www.data.gov.in/backend/dms/v1/ogdp/captcha/refresh/image/download_purpose?_format=json'
JWT_FAILED='JWT acquisition failed\|JWT retry exhausted'
MIN_FREE_GB=6

say() { echo "$(date -u +%FT%TZ) $*" >> "$STATUS"; }

rm -f "$DONE"
mkdir -p "$OUT"
for pass in 1 2 3 4 5 6; do
    free_gb=$(df --output=avail -BG "$OUT" | tail -1 | tr -dc '0-9')
    if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
        say "pass $pass: stopped, only ${free_gb}G free"
        exit 1
    fi
    until curl -s -m 20 "$CAPTCHA" | grep -q '"token"'; do
        say "captcha endpoint not ready"
        sleep 120
    done
    say "pass $pass: starting"
    .venv/bin/python scripts/dataset-download.py --metadata-path "$WORK" \
        --downloads-folder "$OUT" --log-path "$LOG" --no-db-flag \
        --workers 8 --connect-timeout 15 >> "$RUN" 2>&1
    code=$?
    jwt=$(grep -c "$JWT_FAILED" "$LOG" || true)
    say "pass $pass: exit=$code log_rows=$(($(wc -l < "$LOG") - 1)) files=$(ls "$OUT" | wc -l) jwt_failed=$jwt"
    if [ "$code" -eq 0 ] && [ "$jwt" -eq 0 ]; then
        break
    fi
    grep -v "$JWT_FAILED" "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
    sleep 60
done
say "done"
touch "$DONE"
