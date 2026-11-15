#!/bin/sh
set -u

LOG_FILE="${HOME:-/tmp}/.fivsed-rotation.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

{
  echo "$(date '+%F %T') FIVSED LEFT-90 display rotation starting."
  echo "$(date '+%F %T') DISPLAY=${DISPLAY:-<unset>}"

  if [ -z "${DISPLAY:-}" ]; then
    echo "$(date '+%F %T') ERROR: DISPLAY is not set."
    exit 1
  fi

  OUTPUT=""
  i=1
  while [ "$i" -le 20 ]; do
    if command -v xrandr >/dev/null 2>&1; then
      OUTPUT=$(xrandr --query 2>/dev/null | awk '$2 == "connected" {print $1; exit}') || OUTPUT=""
      if [ -n "$OUTPUT" ]; then
        echo "$(date '+%F %T') Detected X11 output: $OUTPUT"
        break
      fi
    else
      echo "$(date '+%F %T') ERROR: xrandr not installed."
      exit 1
    fi
    echo "$(date '+%F %T') Waiting for connected display (attempt $i/20)..."
    sleep 1
    i=$((i + 1))
  done

  if [ -z "$OUTPUT" ]; then
    echo "$(date '+%F %T') ERROR: No connected X11 display found."
    xrandr --query 2>&1 || true
    exit 1
  fi

  echo "$(date '+%F %T') Applying: xrandr --output $OUTPUT --rotate left"
  if xrandr --output "$OUTPUT" --rotate left >>"$LOG_FILE.xrandr" 2>&1; then
    echo "$(date '+%F %T') LEFT 90-degree rotation applied successfully."
  else
    echo "$(date '+%F %T') ERROR: xrandr rotation failed."
    xrandr --query 2>&1 || true
    exit 1
  fi

  sleep 1
  echo "$(date '+%F %T') Final X11 display state:"
  xrandr --query 2>&1 || true
} >"$LOG_FILE" 2>&1

exit 0
