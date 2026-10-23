"""Output rules: data goes to stdout as JSON, errors go to stderr as JSON.

Keeping both machine-readable is what makes the CLI usable from shell
pipelines (`| jq`) and coding agents.
"""

import json
import sys

from tmb_cli.errors import TmbError


def emit(data: object) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def emit_error(err: TmbError) -> None:
    json.dump(err.to_dict(), sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")
