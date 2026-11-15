#!/bin/sh
set -u

# FIVSED touch correction for the 90-degree-left portrait display.
# Preferred: identify the XPT2046/touch device dynamically.
MATRIX="1 0 0 0 -1 1 0 0 1"
LOG_FILE="${HOME:-/tmp}/.fivsed-touch-correction.log"

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
{
  echo "$(date '+%F %T') FIVSED touch correction starting. DISPLAY=${DISPLAY:-<unset>}"
  if [ -z "${DISPLAY:-}" ] || ! command -v xinput >/dev/null 2>&1; then
    echo "Touch correction skipped: DISPLAY or xinput unavailable."
    exit 0
  fi

  ids=""
  # XPT2046 is the expected controller; the generic touch fallback keeps this
  # usable when the X driver exposes a different device name.
  ids=$(xinput list 2>/dev/null | sed -n 's/.*id=\([0-9][0-9]*\).*\(XPT2046\|Touch\|touchscreen\).*/\1/p' | sort -u)

  if [ -z "$ids" ]; then
    echo "No XPT2046/touchscreen input device matched on first pass; retrying..."
    tries=0
    while [ "$tries" -lt 10 ] && [ -z "$ids" ]; do
      tries=$((tries + 1))
      sleep 1
      ids=$(xinput list 2>/dev/null | sed -n 's/.*id=\([0-9][0-9]*\).*\(XPT2046\|Touch\|touchscreen\).*/\1/p' | sort -u)
    done
  fi

  if [ -z "$ids" ]; then
    echo "No XPT2046/touchscreen input device matched after retries; leaving input unchanged."
    exit 0
  fi

  for id in $ids; do
    echo "Applying coordinate matrix '$MATRIX' to input device id=$id"
    if xinput set-prop "$id" "Coordinate Transformation Matrix" $MATRIX 2>&1; then
      echo "Touch correction applied to id=$id"
    else
      echo "Touch correction failed for id=$id"
    fi
  done
} >"$LOG_FILE" 2>&1
