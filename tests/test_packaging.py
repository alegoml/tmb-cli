"""The release pins agree, and a build never ships captures or credentials."""

import re
import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_install_script_pins_the_project_version():
    assert re.search(r'^VERSION="([^"]+)"', (ROOT / "install.sh").read_text(), re.M)[1] == VERSION


def test_readme_pins_the_project_version():
    pins = re.findall(r"tmb-cli@v([0-9][^\s`]*)", (ROOT / "README.md").read_text())
    assert pins and set(pins) == {VERSION}


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to build")
def test_build_ships_the_skill_but_no_secrets(tmp_path):
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    tree = tmp_path / "tree"
    for name in tracked:
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, tree / name)
    # Plant what must never ship, as if left in the tree by mistake.
    for planted in ["captures/raw.json", "src/tmb_cli/credentials.json", "src/tmb_cli/.env"]:
        (tree / planted).parent.mkdir(parents=True, exist_ok=True)
        (tree / planted).write_text('{"app_key": "planted-secret"}')

    out = tmp_path / "dist"
    subprocess.run(["uv", "build", "-q", "--out-dir", str(out)], cwd=tree, check=True)

    with tarfile.open(next(out.glob("*.tar.gz"))) as sdist:
        sdist_names = sdist.getnames()
    with zipfile.ZipFile(next(out.glob("*.whl"))) as wheel:
        wheel_names = wheel.namelist()
    for names in (sdist_names, wheel_names):
        assert any(n.endswith("tmb_cli/SKILL.md") for n in names)
        leaked = [n for n in names if re.search(r"captures|credentials\.json|\.env", n)]
        assert leaked == []
