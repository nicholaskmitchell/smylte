r"""Every string literal in the backend must survive `.encode("utf-8")`.

Written after a production crash loop, and the shape is worth keeping in mind:
`mcp/oauth.py`'s `wire_safe` — the function whose entire job is to stop
unencodable text reaching the wire — had a lone surrogate baked into its own
docstring, because the docstring quoted `"\ud800"` in a NON-raw string. Python
decodes that escape at compile time, so `wire_safe.__doc__` did not describe a
surrogate, it CONTAINED one, at position 97.

Nothing in the module notices. It imports, it compiles, the tests pass, and the
function itself is correct. It fails only where something encodes the docstring
— a `tools/list` description, a log handler, a serializer, a traceback report —
and on the import path that is a service that will not start. The report was
`UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position
97`, raised from `from .oauth import SCOPE_READ, SCOPE_WRITE`, with no frame of
ours below it.

So this reads the SOURCE rather than any one module's `__doc__`: the class of
defect is "a literal that cannot go on the wire", and it can be introduced by
any docstring, message or constant, by anyone quoting an escape they meant as
an example. A test that only checked `wire_safe` would have passed the day
before the crash.

TWO RULES, because one would be wrong in one direction or the other:

* **Shipped source (`tasksd/`) carries no lone surrogate in any literal.** That
  is where an unencodable string becomes a running service's problem.
* **No DOCSTRING anywhere carries one, tests included.** A docstring is read by
  tooling that encodes it — pytest reporting, `--co -q`, pydoc, an IDE — so it
  is never the right place for one.

THIS FILE'S OWN DOCSTRING IS RAW for the same reason, and it did not start that
way: the first run of the guard below failed on the module docstring you are
reading, at position 340. Two independent authors made the identical mistake
within an hour, in the function warning about it and in the test guarding it,
which is the argument for checking this mechanically rather than by care.

Test DATA is deliberately exempt from the first rule: `test_backlog_stage1.py`
feeds a real `"\ud800"` to prove the XML backstop rejects it, and that
surrogate has to be real to test anything. A guard that failed it would be
telling the suite to stop testing the case this whole file is about.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _sources(sub: str = "") -> list[pathlib.Path]:
    root = BACKEND / sub if sub else BACKEND
    return sorted(
        p for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and ".venv" not in p.parts
    )


def _surrogates(text: str) -> list[tuple[int, str]]:
    return [(i, ch) for i, ch in enumerate(text) if 0xD800 <= ord(ch) <= 0xDFFF]


def _parse(path: pathlib.Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as e:
        pytest.fail(f"{path.relative_to(BACKEND)} does not even parse: {e}")


def test_the_sweep_actually_reads_files():
    """Anti-vacuity. A glob that matched nothing would pass every assertion
    below, and this suite has been bitten by exactly that before."""
    files = _sources()
    assert len(files) > 40, f"only found {len(files)} sources to check"
    assert any(p.name == "oauth.py" for p in files)
    assert len(_sources("tasksd")) > 20, "the shipped-source sweep matched almost nothing"


def test_no_shipped_string_carries_a_lone_surrogate():
    """The guard itself, over `tasksd/` — reported per-offender, because the
    failure is invisible at the site: the source looks like an ordinary escape."""
    offenders = []
    for path in _sources("tasksd"):
        for node in ast.walk(_parse(path)):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            found = _surrogates(node.value)
            if found:
                i, ch = found[0]
                offenders.append(
                    f"{path.relative_to(BACKEND)}:{node.lineno} carries {ch!r} at "
                    f"position {i} of a string literal")

    assert offenders == [], (
        "a shipped string literal contains a real lone surrogate, which cannot "
        "be UTF-8 encoded; anything that encodes it raises UnicodeEncodeError, "
        "and on an import path that is a service that will not start. Write the "
        "string raw (r\"\"\"…\"\"\") so the escape stays six characters:\n  "
        + "\n  ".join(offenders))


def test_no_docstring_anywhere_carries_a_lone_surrogate():
    """Docstrings, tests included. Test DATA may hold a surrogate — one file
    deliberately does — but a docstring is read by tooling that encodes it."""
    offenders = []
    for path in _sources():
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            doc = ast.get_docstring(node, clean=False)
            if not doc:
                continue
            found = _surrogates(doc)
            if found:
                i, ch = found[0]
                where = getattr(node, "name", "<module>")
                # A Module node has no lineno; its docstring starts at line 1.
                line = getattr(node, "lineno", 1)
                offenders.append(
                    f"{path.relative_to(BACKEND)}:{line} {where} docstring "
                    f"carries {ch!r} at position {i}")

    assert offenders == [], (
        "a docstring contains a real lone surrogate — write it raw:\n  "
        + "\n  ".join(offenders))


def test_every_docstring_encodes():
    """The same property one layer out, read off the IMPORTED objects rather
    than the source: it catches a docstring assembled at runtime, or one a
    decorator rewrote, which the AST pass above cannot see."""
    import importlib
    import pkgutil

    import tasksd

    bad = []
    for mod in pkgutil.walk_packages(tasksd.__path__, prefix="tasksd."):
        try:
            m = importlib.import_module(mod.name)
        except Exception:                                   # noqa: BLE001
            continue        # an optional dependency, not this test's business
        for name, obj in vars(m).items():
            doc = getattr(obj, "__doc__", None)
            if not isinstance(doc, str):
                continue
            try:
                doc.encode("utf-8")
            except UnicodeEncodeError as e:
                bad.append(f"{mod.name}.{name}: {e}")
    assert bad == [], "docstrings that cannot be encoded:\n  " + "\n  ".join(bad)
