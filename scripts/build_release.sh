#!/usr/bin/env bash
# Build a standalone MacMedic.app with py2app and zip it for release.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "python3 is required" >&2
  exit 1
fi

"$PYTHON" - <<'PY' || exit 1
import importlib.util
for mod in ("py2app", "rumps", "psutil"):
    if importlib.util.find_spec(mod) is None:
        print(f"missing dependency: {mod}. Run: python3 -m pip install -r requirements.txt", file=__import__("sys").stderr)
        raise SystemExit(1)
PY

VERSION=$("$PYTHON" -c "import macmedic; print(macmedic.__version__)")
echo "Building MacMedic $VERSION"

rm -rf build dist release
"$PYTHON" setup.py py2app
mkdir -p release
zip -r "release/MacMedic-${VERSION}.zip" dist/MacMedic.app >/dev/null

echo "Built release/MacMedic-${VERSION}.zip"
echo "Upload this file to your GitHub release."