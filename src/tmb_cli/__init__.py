"""Unofficial, agent-friendly CLI for TMB (Barcelona) bus and metro arrivals."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tmb-cli")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0"
