#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

if [ "${DISPLAY:-}" = "" ] && [ "$(uname -s 2>/dev/null || true)" != "Darwin" ]; then
  echo "FIVSED desktop GUI requires a graphical display (DISPLAY)."
  echo "Boot the Pi into its local LightDM/Openbox session, or run this command from an X session."
  exit 1
fi

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN=${PYTHON_BIN:-python3}
fi

exec "$PYTHON_BIN" -m gui.main
