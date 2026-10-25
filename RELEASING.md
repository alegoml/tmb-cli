# Releasing

Releases are git tags on GitHub (`alegoml/tmb-cli`); there is no PyPI package. Users install a tag
with `uv tool install git+https://github.com/alegoml/tmb-cli@vX.Y.Z` or `install.sh`.

## Checklist

1. On `main`, clean tree, CI green.
2. Bump the version in the three places that pin it (`tests/test_packaging.py` fails if they
   differ):
   - `pyproject.toml` → `version = "X.Y.Z"` (the CLI reads its version from here)
   - `install.sh` → `VERSION="X.Y.Z"`
   - `README.md` → every `tmb-cli@vX.Y.Z`
3. If commands or output changed: update `src/tmb_cli/SKILL.md`, copy it to `SKILL.md`, and update
   `docs/spec.md`.
4. Check:
   ```bash
   uv lock && uv sync --locked
   uv run ruff check . && uv run ruff format --check . && uv run pytest
   TMB_LIVE=1 TMB_LIVE_STOP=1103 TMB_LIVE_STATION=126 uv run pytest -m live   # your own keys
   ```
5. Commit `Release vX.Y.Z`, then tag and push:
   ```bash
   git tag -a vX.Y.Z -m "tmb-cli X.Y.Z"
   git push origin main vX.Y.Z
   ```
6. Try the published tag from outside the repo:
   ```bash
   uv tool install --force git+https://github.com/alegoml/tmb-cli@vX.Y.Z
   tmb --version && tmb doctor
   ```
7. Create the GitHub release from the tag with a short changelog.

## Versioning

Semantic versioning on the **JSON contract** (field names and types, exit codes, error `code`s):
removing or renaming a field or changing an exit code is a major bump; adding a field or a command
is a minor bump; fixes are a patch. While on 0.x, minor bumps may break the contract, and the
changelog says how.

Never commit or tag anything from `captures/`, credentials, or real favourites.
