#!/usr/bin/env python3
"""Dependency-free test runner — runs the suite without pytest.

Why this exists: the project's only runtime dependency is `requests`, and the
test suite should stay runnable on a fresh clone (and in minimal CI images)
before anyone installs dev extras. `pytest` remains the primary runner
(`pip install -e ".[dev]"`); this script covers the same tests with a
~150-line fixture engine.

Supported fixtures (the only ones the suite uses):

    tmp_path     fresh temp directory per test, removed afterwards
    capsys       stdout/stderr capture with .readouterr()
    monkeypatch  os.environ setenv/delenv with automatic undo
    + every plain fixture function defined in tests/conftest.py

Usage:
    python scripts/run_tests.py            # all tests
    python scripts/run_tests.py transform  # only tests whose name matches
    python scripts/run_tests.py -v         # list each test as it runs
"""
from __future__ import annotations

import importlib.util
import inspect
import io
import os
import shutil
import sys
import tempfile
import traceback
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# --------------------------------------------------------------------------- #
# minimal pytest shim — injected ONLY when pytest is not installed, so the
# suite stays importable on a bare clone. With real pytest present it is
# never touched.
# --------------------------------------------------------------------------- #
def _install_pytest_shim():
    try:
        import pytest  # noqa: F401
        return
    except ImportError:
        pass
    import contextlib
    import re as _re

    shim = types.ModuleType("pytest")

    def fixture(*args, **kwargs):
        if len(args) == 1 and inspect.isfunction(args[0]) and not kwargs:
            return args[0]
        def wrap(fn):
            return fn
        return wrap

    class _Raises:
        def __init__(self, exc_type, match=None):
            self.exc_type = exc_type
            self.match = match
            self.value = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is None:
                raise AssertionError(f"expected {self.exc_type.__name__}, "
                                     f"nothing raised")
            if not issubclass(exc_type, self.exc_type):
                return False
            if self.match and not _re.search(self.match, str(exc)):
                raise AssertionError(f"pattern {self.match!r} not found in "
                                     f"{str(exc)!r}")
            self.value = exc
            return True

    @contextlib.contextmanager
    def _nullcontext(*a, **kw):
        yield

    shim.fixture = fixture
    shim.raises = lambda exc, match=None: _Raises(exc, match)
    shim.mark = SimpleNamespace(**{
        name: (lambda *a, **k: (lambda fn: fn))
        for name in ("parametrize", "skip", "skipif", "usefixtures",
                     "xfail", "filterwarnings")
    })
    shim.approx = lambda v, **k: v
    sys.modules["pytest"] = shim


_install_pytest_shim()


# --------------------------------------------------------------------------- #
# fixture engine
# --------------------------------------------------------------------------- #
class MiniMonkeyPatch:
    def __init__(self):
        self._undo = []

    def setenv(self, name, value):
        self._undo.append((name, os.environ.get(name)))
        os.environ[name] = value

    def delenv(self, name, raising=True):
        if name not in os.environ:
            if raising:
                raise KeyError(name)
            return
        self._undo.append((name, os.environ.get(name)))
        del os.environ[name]

    def undo(self):
        for name, old in reversed(self._undo):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        self._undo.clear()


class MiniCapsys:
    """pytest-compatible capsys: .readouterr() -> object with .out / .err."""

    def __init__(self):
        self._out, self._err = io.StringIO(), io.StringIO()

    def readouterr(self):
        out, err = self._out.getvalue(), self._err.getvalue()
        self._out.seek(0), self._out.truncate()
        self._err.seek(0), self._err.truncate()
        return SimpleNamespace(out=out, err=err)


class FixtureEngine:
    """Resolve fixtures by name, recursively, with yield-teardown support.

    Lookup order: conftest fixtures, then fixtures defined in the module the
    test itself lives in (mirroring pytest's resolution rules closely enough
    for this suite).
    """

    def __init__(self, conftest, module=None):
        self.available = dict(conftest.FIXTURES)
        if module is not None:
            self.available.update(
                {name: obj for name, obj in vars(module).items()
                 if not name.startswith("_")
                 and inspect.isfunction(obj)
                 and name not in self.available})
        self.cache = {}
        self.finalizers = []

    def _builtin(self, name):
        if name == "tmp_path":
            path = Path(tempfile.mkdtemp(prefix="na-test-"))
            self.finalizers.append(lambda: shutil.rmtree(path, ignore_errors=True))
            return path
        if name == "monkeypatch":
            mp = MiniMonkeyPatch()
            self.finalizers.append(mp.undo)
            return mp
        if name == "capsys":
            return MiniCapsys()
        raise LookupError(f"unknown fixture {name!r}")

    def resolve(self, name):
        if name in self.cache:
            return self.cache[name]
        func = self.available.get(name)
        if func is None:
            return self._builtin(name)
        kwargs = {p: self.resolve(p)
                  for p in inspect.signature(func).parameters}
        result = func(**kwargs)
        if inspect.isgenerator(result):
            value = next(result)
            self.finalizers.append(
                lambda g=result: (next(g, None), g.close()))
        else:
            value = result
        self.cache[name] = value
        return value

    def teardown(self):
        for fin in reversed(self.finalizers):
            try:
                fin()
            except Exception:  # noqa: BLE001
                pass
        self.finalizers.clear()
        self.cache.clear()


# --------------------------------------------------------------------------- #
# collection
# --------------------------------------------------------------------------- #
def load_conftest():
    spec = importlib.util.spec_from_file_location(
        "na_conftest", TESTS / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["na_conftest"] = module
    spec.loader.exec_module(module)
    fixtures = {name: obj for name, obj in vars(module).items()
                if not name.startswith("_")
                and inspect.isfunction(obj)
                and name not in ("load_dotenv",)}
    module.FIXTURES = fixtures
    return module


def collect(pattern=None):
    conftest = load_conftest()
    cases = []  # (name, callable, owner_class, module)
    for path in sorted(TESTS.glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)
        for name, obj in vars(module).items():
            if name.startswith("Test"):
                for mname, meth in vars(obj).items():
                    if mname.startswith("test_") and inspect.isfunction(meth):
                        cases.append((f"{path.stem}::{name}::{mname}",
                                      meth, obj, module))
            elif name.startswith("test_") and inspect.isfunction(obj):
                cases.append((f"{path.stem}::{name}", obj, None, module))
    if pattern:
        cases = [c for c in cases if pattern in c[0]]
    return conftest, cases


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
def run_one(conftest, entry):
    name, func, cls, module = entry
    engine = FixtureEngine(conftest, module)
    capsys = MiniCapsys()
    kwargs = {}
    for p in inspect.signature(func).parameters:
        if p == "self":
            continue
        if p == "capsys":
            kwargs[p] = capsys
        else:
            kwargs[p] = engine.resolve(p)
    instance = cls() if cls is not None else None
    with redirect_stdout(capsys._out), redirect_stderr(capsys._err):
        try:
            if instance is not None:
                func(instance, **kwargs)
            else:
                func(**kwargs)
        finally:
            engine.teardown()
    return capsys


def main(argv):
    verbose = "-v" in argv
    argv = [a for a in argv if a != "-v"]
    pattern = argv[0] if argv else None

    conftest, cases = collect(pattern)
    if not cases:
        print("no tests matched" + (f" /{pattern}/" if pattern else ""))
        return 1

    passed, failed = 0, []
    for entry in cases:
        name = entry[0]
        try:
            run_one(conftest, entry)
        except SystemExit as exc:
            code = exc.code
            if code not in (0, None):
                failed.append((name, f"SystemExit({code!r})"))
                continue
        except Exception:  # noqa: BLE001
            failed.append((name, traceback.format_exc(limit=6)))
            continue
        passed += 1
        if verbose:
            print(f"  ok  {name}")

    print(f"\n{passed} passed, {len(failed)} failed, {len(cases)} total")
    for name, tb in failed:
        print(f"\nFAIL {name}\n{tb}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
