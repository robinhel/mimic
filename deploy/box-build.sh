#!/bin/sh
# Bygger livetestet för en Amp Box. Körs av `amp boxes deploy` i en tillfällig klon.
# Releasen får en egen Python och bara det livetestet behöver (requests), ingen venv.
set -eu
UV_PYTHON_INSTALL_DIR="$PWD/py" uv python install 3.13
PY=$(ls -d "$PWD"/py/cpython-3.13*/bin/python3 | head -n 1)
uv pip install --quiet --python "$PY" --target vendor "requests>=2.32"
