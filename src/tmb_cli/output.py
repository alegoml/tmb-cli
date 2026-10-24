"""Output rules: data goes to stdout as JSON, errors go to stderr as JSON.

Keeping both machine-readable is what makes the CLI usable from shell
pipelines (`| jq`) and coding agents. Output is strict JSON: NaN/Infinity
raise ValueError instead of being written as non-standard literals.
"""

import json
import sys

from tmb_cli.errors import TmbError


def render(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)


def emit(data: object) -> None:
    # Render fully before writing, so a failure never leaves half a document on stdout.
    text = render(data)
    sys.stdout.write(text + "\n")


def emit_error(err: TmbError) -> None:
    sys.stderr.write(json.dumps(err.to_dict(), ensure_ascii=False, allow_nan=False) + "\n")
