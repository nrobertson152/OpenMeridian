"""The family's product rules, enforced."""
import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "openmeridian"
NETWORK = {"socket", "http", "urllib", "requests", "ftplib", "smtplib", "ssl"}


def imports(path):
    out = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            out.add(n.module.split(".")[0])
    return out


def test_core_has_no_gui_and_only_the_standard_library():
    for f in PKG.glob("*.py"):
        for m in imports(f):
            allowed = {"openmeridian", "PySide6"} if f.name == "cli.py" else {"openmeridian"}    # cli.py only checks for it, lazily
            assert m in sys.stdlib_module_names or m in allowed, f"{f.name}: {m}"


def test_no_network_anywhere():
    for f in PKG.rglob("*.py"):
        assert not imports(f) & NETWORK, f


def test_self_test_passes():
    r = subprocess.run([sys.executable, "-m", "openmeridian", "--self-test"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "PASSED" in r.stdout, r.stdout + r.stderr


def test_resources_exist():
    assert (PKG / "resources" / "openmeridian-64.png").exists() and (PKG / "resources" / "openmeridian.ico").exists()
