#!/bin/sh
# Install tmb-cli with uv, pinned to a released tag.
#
#   curl -LsSf https://raw.githubusercontent.com/alegoml/tmb-cli/main/install.sh | sh
#
# Read it first: it only checks for uv and runs `uv tool install` on the tag below.
set -eu

VERSION="0.1.0"  # keep equal to pyproject.toml (tests/test_packaging.py checks it)
REPO="https://github.com/alegoml/tmb-cli"

if ! command -v uv >/dev/null 2>&1; then
    echo "tmb-cli needs uv: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

uv tool install --force "git+${REPO}@v${VERSION}"

cat >&2 <<EOF

tmb ${VERSION} installed. Next:
  1. Get free keys at https://developer.tmb.cat/ (create an application named tmb-cli).
  2. Run \`tmb auth set\` in your terminal (never paste the keys into an agent).
  3. Check it: tmb doctor
EOF
