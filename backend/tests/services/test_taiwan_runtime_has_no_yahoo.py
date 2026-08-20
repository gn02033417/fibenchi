"""Guards that the Taiwan runtime can import without the legacy Yahoo stack."""

import ast
import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"


def _is_legacy_provider(path: Path) -> bool:
    relative = path.relative_to(APP_ROOT).as_posix()
    return relative.startswith("services/yahoo/") or relative == "services/price_providers/yahoo.py"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_active_app_sources_do_not_import_yahoo():
    offenders = []
    for path in APP_ROOT.rglob("*.py"):
        if _is_legacy_provider(path):
            continue
        for module in _imported_modules(path):
            if module == "yahooquery" or module == "app.services.yahoo" or module.startswith("app.services.yahoo."):
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}: {module}")

    assert offenders == []
    assert "yahooquery" not in (BACKEND_ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_taiwan_runtime_imports_without_yahooquery():
    modules = [
        "app.main",
        "app.routers.prices",
        "app.routers.holdings",
        "app.routers.search",
        "app.services.asset_service",
        "app.services.earnings_cache",
        "app.services.fundamentals_cache",
        "app.services.holdings_service",
        "app.services.intraday",
        "app.services.price_service",
        "app.services.price_providers",
        "app.services.price_providers.shioaji",
        "app.services.price_sync",
        "app.services.quote_service",
        "app.services.search_service",
    ]
    script = """
import builtins
import importlib

real_import = builtins.__import__

def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "yahooquery" or name == "app.services.yahoo" or name.startswith("app.services.yahoo."):
        raise AssertionError(f"legacy Yahoo import reached Taiwan runtime: {name}")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = blocked_import
for module_name in MODULES:
    importlib.import_module(module_name)
"""
    script = "MODULES = " + repr(modules) + "\n" + script
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(BACKEND_ROOT) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
