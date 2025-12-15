#!/usr/bin/env sh
set -eu

echo "[INFO] Building distributions..."
python3 -m pip install -U build twine >/dev/null

rm -rf dist build
python3 -m build

echo "[INFO] Checking distributions..."
python3 -m twine check dist/*

echo ""
echo "[ACTION REQUIRED] Set TWINE_USERNAME=__token__ and TWINE_PASSWORD to your PyPI API token."
echo "Example:"
echo "  export TWINE_USERNAME=__token__"
echo "  export TWINE_PASSWORD=pypi-...your-token..."
echo ""
echo "[INFO] Uploading to PyPI..."
python3 -m twine upload dist/*

echo "[OK] Uploaded. Next: configure Trusted Publishing in PyPI for GitHub Actions."
