"""Save raw TMB API responses to captures/ (git-ignored), to design output models and fixtures.

Usage (credentials from `tmb auth set` or TMB_APP_ID/TMB_APP_KEY):

    uv run python scripts/capture.py itransit/bus/parades/108
    uv run python scripts/capture.py "itransit/metro/estacions?estacions=123"
    uv run python scripts/capture.py transit/linies/bus

Each argument is a GET path under https://api.tmb.cat/v1/. Any occurrence of your app_id or app_key
in a response is replaced with "REDACTED" before it is written. Review a capture anyway before
copying it to tests/fixtures/.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from tmb_cli.client import TmbClient
from tmb_cli.config import load_credentials
from tmb_cli.errors import TmbError

CAPTURES = Path(__file__).resolve().parents[1] / "captures"


def redact(text: str, secrets: list[str]) -> tuple[str, int]:
    count = 0
    for secret in sorted(secrets, key=len, reverse=True):
        count += text.count(secret)
        text = text.replace(secret, "REDACTED")
    return text, count


def main(paths: list[str]) -> int:
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        creds = load_credentials()
    except TmbError as err:
        print(f"{err.code}: {err.message} {err.hint or ''}", file=sys.stderr)
        return 3
    CAPTURES.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    status = 0
    with TmbClient(creds.app_id, creds.app_key) as client:
        for raw in paths:
            parts = urlsplit(raw)
            name = re.sub(r"[^A-Za-z0-9]+", "-", f"{parts.path}-{parts.query}").strip("-")
            try:
                payload = client.get(parts.path, params=dict(parse_qsl(parts.query)) or None)
            except TmbError as err:
                print(f"{raw}: {err.code}: {err.message}", file=sys.stderr)
                status = 1
                continue
            text, hits = redact(
                json.dumps(payload, ensure_ascii=False, indent=2), [creds.app_id, creds.app_key]
            )
            out = CAPTURES / f"{name}-{stamp}.json"
            out.write_text(text + "\n")
            note = f" ({hits} credential occurrence(s) redacted)" if hits else ""
            print(f"{raw} -> {out.relative_to(CAPTURES.parent)}{note}", file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
