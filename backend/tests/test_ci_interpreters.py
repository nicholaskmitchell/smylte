"""One interpreter set, stated in three places, checked against itself here.

Written after a production crash loop that a completely green CI run said
nothing about. `mcp/oauth.py` carried a lone surrogate in a docstring, which
raises `UnicodeEncodeError` at module exec on Python 3.13 and on no earlier
version. `pyproject.toml` advertised `>=3.12`; `ci.yml` tested 3.12 only;
production ran 3.13; and NOTHING in the repository said so — `deploy/setup.sh`
refused a missing venv but never looked at the one it found, and `docs/DEPLOY.md`
named no version at all. The interpreter production started under was whatever
`python3` was the day someone ran `venv`, and an OS upgrade moves that out from
under an existing venv silently.

tests/test_source_encodable.py closes the DEFECT. This closes the reason it
reached a deploy, which is the larger half: the same interpreter set is now
written down in three files, and each of the three is only as good as its
agreement with the other two.

* `backend/pyproject.toml`   — `requires-python`, the claim made to the world
* `.github/workflows/ci.yml` — the `backend` job matrix, what is actually run
* `deploy/setup.sh`          — the `case "$PYVER"` arm, what production may be

The rule, in one line: **the deploy accepts exactly what CI runs, and CI runs
everything `requires-python` admits.** Set EQUALITY against setup.sh is what
makes this non-circular — checking the matrix against `requires-python` alone
cannot notice a leg being dropped, because dropping the leg also lowers the
ceiling the check would compare against, and the shrunken matrix passes.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import tempfile
import tomllib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

CI = ".github/workflows/ci.yml"
SETUP = "deploy/setup.sh"
PYPROJECT = "backend/pyproject.toml"


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _ver(text: str) -> tuple[int, int]:
    major, minor = text.strip().strip("'\"").split(".")
    return int(major), int(minor)


def _show(v: tuple[int, int]) -> str:
    return f"{v[0]}.{v[1]}"


def _matrix_jobs() -> dict[str, list[tuple[int, int]]]:
    """Every job in ci.yml that RUNS THE SUITE, mapped to the interpreters it
    runs it on.

    Keyed on the pytest invocation rather than on the job being called
    `backend`, so a rename moves the guard with it instead of quietly emptying
    it.
    """
    wf = yaml.safe_load(_read(CI))
    found: dict[str, list[tuple[int, int]]] = {}
    for name, job in (wf.get("jobs") or {}).items():
        steps = job.get("steps") or []
        if not any("pytest" in str(st.get("run") or "") for st in steps):
            continue
        matrix = ((job.get("strategy") or {}).get("matrix") or {})
        versions = matrix.get("python-version") or []
        assert versions, (
            f"job {name!r} in {CI} runs the backend suite on a single, "
            f"hard-coded interpreter. That is the exact shape that let a "
            f"3.13-only import failure ship green — give it a "
            f"`strategy.matrix.python-version`"
        )
        # A matrix that no step reads is decoration: two legs, same interpreter,
        # both green, and the second one proves nothing.
        setup = [st for st in steps
                 if str(st.get("uses") or "").startswith("actions/setup-python@")]
        assert setup, f"job {name!r} matrixes python-version but never installs a Python"
        for st in setup:
            got = str((st.get("with") or {}).get("python-version") or "")
            assert "matrix.python-version" in got, (
                f"job {name!r} declares a python-version matrix but its "
                f"setup-python step pins {got!r} — every leg would run the same "
                f"interpreter and the matrix would be decoration"
            )
        found[name] = sorted(_ver(v) for v in versions)
    return found


def _deploy_versions() -> list[tuple[int, int]]:
    """The interpreters `deploy/setup.sh` will install onto, read out of its
    `case "$PYVER"` arm."""
    src = _read(SETUP)
    block = re.search(r'case\s+"\$PYVER"\s+in(.*?)esac', src, re.S)
    assert block, (
        f"{SETUP} no longer checks the venv's Python version. It does not "
        f"CREATE the venv, so without this check production runs whatever "
        f"`python3` was when someone made it — which is how a 3.13-only "
        f"failure reached a deploy"
    )
    arm = re.search(r"^\s*(3\.\d+(?:\|3\.\d+)*)\)", block.group(1), re.M)
    assert arm, (
        f"the `case` arm in {SETUP} is no longer a literal `3.x|3.y)` list, so "
        f"this guard can no longer tell what the deploy accepts:\n{block.group(1)}"
    )
    return sorted(_ver(v) for v in arm.group(1).split("|"))


def _requires_python() -> tuple[tuple[int, int], tuple[int, int] | None]:
    """`requires-python` as an inclusive floor and an exclusive ceiling.

    Deliberately narrow: an unrecognised clause raises rather than being
    ignored, because a specifier this cannot read is one it cannot check, and
    silently checking nothing is the failure mode this whole file exists to
    prevent.
    """
    spec = tomllib.loads(_read(PYPROJECT))["project"]["requires-python"]
    floor: tuple[int, int] | None = None
    ceiling: tuple[int, int] | None = None
    for clause in spec.split(","):
        clause = clause.strip()
        m = re.fullmatch(r"(>=|>|<=|<|==)\s*(\d+\.\d+)(?:\.\*)?", clause)
        assert m, f"cannot read {clause!r} in requires-python = {spec!r}"
        op, v = m.group(1), _ver(m.group(2))
        if op == ">=":
            floor = v
        elif op == ">":
            floor = (v[0], v[1] + 1)
        elif op == "<":
            ceiling = v
        elif op == "<=":
            ceiling = (v[0], v[1] + 1)
        else:
            floor, ceiling = v, (v[0], v[1] + 1)
    assert floor is not None, f"requires-python = {spec!r} sets no lower bound"
    return floor, ceiling


def test_the_three_files_are_all_still_readable():
    """Anti-vacuity, first. Every assertion below is a comparison between two
    parses, and two empty parses agree perfectly — this suite has shipped a
    guard that matched nothing before, twice."""
    jobs = _matrix_jobs()
    assert jobs, (
        f"no job in {CI} runs pytest at all — either the backend suite stopped "
        f"running in CI, or this guard has lost track of where it runs"
    )
    assert all(v for v in jobs.values())
    assert _deploy_versions(), f"parsed an empty accepted set out of {SETUP}"
    floor, _ = _requires_python()
    assert floor >= (3, 0)


def test_the_deploy_accepts_exactly_what_ci_runs():
    """The one that would have caught this, and the reason it is set EQUALITY.

    Both directions are real failures, and they fail differently:

    * deploy accepts more than CI runs → production can start on an interpreter
      no test has ever executed. That is the crash, exactly.
    * CI runs more than deploy accepts → the extra leg burns minutes proving
      something about a version `setup.sh` will refuse to install on, and the
      claim "CI covers production" quietly stops meaning anything.
    """
    deploy = _deploy_versions()
    for name, matrix in _matrix_jobs().items():
        assert matrix == deploy, (
            f"{SETUP} accepts {[_show(v) for v in deploy]} but the {name!r} job "
            f"in {CI} runs the suite on {[_show(v) for v in matrix]}. These have "
            f"to be the same set: whatever the deploy will start production on "
            f"is what CI has to have executed"
        )


def test_ci_runs_every_interpreter_the_package_claims_to_support():
    """`requires-python` is a promise, and an untested promise is how this went
    wrong: `>=3.12` advertised both 3.12 and 3.13 while only 3.12 ever ran.

    Note the direction. The matrix may run MORE than is claimed (testing an
    interpreter you do not promise is only generous); it may never run less,
    and it may not skip a version in the middle.
    """
    floor, ceiling = _requires_python()
    for name, matrix in _matrix_jobs().items():
        top = max(matrix)
        assert top >= floor, (
            f"the {name!r} matrix tops out at {_show(top)}, below the "
            f"{_show(floor)} floor `requires-python` sets — every supported "
            f"interpreter is untested"
        )
        missing = [
            (3, minor) for minor in range(floor[1], top[1] + 1)
            if (ceiling is None or (3, minor) < ceiling) and (3, minor) not in matrix
        ]
        assert not missing, (
            f"`requires-python` in {PYPROJECT} admits "
            f"{[_show(v) for v in missing]}, which the {name!r} job never runs. "
            f"Either add the leg or narrow the claim — the gap between the two "
            f"is where a version-specific failure lives"
        )


def test_the_supported_set_is_written_down_for_a_human():
    """The check in `setup.sh` refuses a bad interpreter at install time, which
    is too late to be the only telling: whoever built the venv had already
    chosen wrong, and nothing pointed them at the right answer. So the versions
    have to appear in the deploy doc as well, and the doc has to say the venv is
    not created for them — that omission is the whole mechanism."""
    doc = _read("docs/DEPLOY.md")
    deploy = _deploy_versions()
    for v in deploy:
        assert _show(v) in doc, (
            f"docs/DEPLOY.md never mentions Python {_show(v)}, which "
            f"{SETUP} accepts — the doc is where someone building the venv "
            f"looks, and it is the only place that can tell them BEFORE they "
            f"build it wrong"
        )
    assert re.search(r"\.venv|virtualenv|venv", doc), (
        "docs/DEPLOY.md says nothing about the venv at all"
    )


def test_setup_sh_actually_refuses_an_untested_interpreter():
    """The tests above compare parses; this one runs the script.

    A `case` arm that reads correctly and never fires would satisfy every
    static check here — so drive the real file with a venv that reports an
    untested version and require it to stop.

    Only the REFUSING arm is exercised, deliberately: an accepted version
    carries on into `install -d /etc/tasks` and a systemd unit, which is not
    something a test may do to the machine it runs on. The accepting arm is
    covered by `_run_setup_sh` in test_backlog_aug19_stage45.py, which runs the
    whole script to completion inside a sandbox with every system command
    stubbed — its stub answers with the first version of this same `case` arm.
    """
    accepted = _deploy_versions()
    untested = (3, min(accepted)[1] - 1)      # one below the floor, so never accepted
    assert untested not in accepted

    root = pathlib.Path(tempfile.mkdtemp(prefix="pyver-"))
    try:
        venv = root / "backend" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text(f"#!/bin/sh\necho {_show(untested)}\n")
        (venv / "python").chmod(0o755)

        script = re.sub(r"^BACKEND=.*$", f"BACKEND={root / 'backend'}",
                        _read(SETUP), flags=re.M)
        sh = root / "setup.sh"
        sh.write_text(script)
        proc = subprocess.run(["bash", str(sh)], text=True, capture_output=True,
                              input="", timeout=60)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        f"setup.sh installed onto a Python {_show(untested)} venv, which CI "
        f"never runs:\n{out}"
    )
    # Non-vacuity: it has to have stopped FOR THIS REASON. Several paths through
    # this script exit non-zero without root or a real venv, so a bare
    # returncode check would pass with the version guard deleted.
    assert _show(untested) in out and "docs/DEPLOY.md" in out, (
        f"setup.sh exited non-zero but not on the interpreter check, so this "
        f"proves nothing about it:\n{out}"
    )
