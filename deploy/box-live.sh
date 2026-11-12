#!/bin/sh
# Livetest (fas 6) på en Amp Box. Pappershandel, bara läsning. Data i deploymentens datamapp.
set -eu
cd "$(dirname "$0")/.."
PY=$(ls -d py/cpython-3.13*/bin/python3 | head -n 1)
export PYTHONPATH="$PWD/src:$PWD/vendor" PYTHONUNBUFFERED=1
DATA="$AMP_DEPLOYMENT_DATA_DIRECTORY"
exec "$PY" -c 'from copycheck.cli import main; main()' live \
  --db "$DATA/live.db" --backup "$DATA/backups/live-latest.db" --port "$PORT" \
  --wallets 0xc8b9a30184244d427169cf62485dde6041b2b836
