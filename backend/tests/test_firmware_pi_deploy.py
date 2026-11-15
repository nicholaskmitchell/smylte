"""The Pi panel's systemd unit and install script, held to the client.

`deploy/smylte-panel.service` and `deploy/panel-setup.sh` hold numbers and
names that only mean something next to the client: the credential's name, the
exit status that must not be retried, a stop timeout that has to outlast a
refresh, a watchdog that has to outlast a slow fetch, the list of files the
client is made of. Nothing else ever checks them: CI has no systemd and no Pi,
and the script is root-only. So this file never runs systemd and never runs
`panel-setup.sh`. It parses the unit, reads the script as text, and runs small
extracted pieces of the script (the token parser) in bash, and ties each
value to the constant in `panel.py` or `epd7in5_v2.py` that it depends on.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess

import pytest

import pi_panel_fakes as F

P = F.load_panel()
E = F.load_driver()


# ── the unit parser ──────────────────────────────────────────────────────────

def parse_unit(text: str) -> dict[str, list[tuple[str, str]]]:
    """Section name -> its (key, value) pairs in order. Repeated keys are kept."""
    sections: dict[str, list[tuple[str, str]]] = {}
    current: list[tuple[str, str]] | None = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in "#;":
            continue
        if s.startswith("[") and s.endswith("]"):
            current = sections.setdefault(s[1:-1], [])
            continue
        key, _, value = s.partition("=")
        assert current is not None, f"a setting outside any section: {line!r}"
        current.append((key.strip(), value.strip()))
    return sections


class Unit:
    def __init__(self, text: str):
        self.sections = parse_unit(text)

    def values(self, section: str, key: str) -> list[str]:
        return [v for k, v in self.sections.get(section, []) if k == key]

    def one(self, section: str, key: str) -> str:
        found = self.values(section, key)
        assert len(found) == 1, f"[{section}] {key} appears {len(found)} times, not once"
        return found[0]


@pytest.fixture(scope="module")
def unit() -> Unit:
    return Unit(F.UNIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def script() -> str:
    return F.SETUP_SH.read_text(encoding="utf-8")


# ── the unit ─────────────────────────────────────────────────────────────────

def test_the_service_runs_as_a_dynamic_user_in_the_gpio_and_spi_groups(unit):
    assert unit.one("Service", "DynamicUser") == "yes"
    assert set(unit.one("Service", "SupplementaryGroups").split()) == {"gpio", "spi"}
    assert unit.values("Service", "User") == []
    assert unit.values("Service", "Group") == []


def test_the_device_policy_allows_only_the_spi_and_gpiochip_nodes(unit):
    assert unit.one("Service", "DevicePolicy") == "closed"
    assert sorted(unit.values("Service", "DeviceAllow")) == ["char-gpiochip rw", "char-spi rw"]


def test_the_unit_sets_neither_private_devices_nor_private_users(unit):
    """Either would hide or unmap what the client needs: PrivateDevices hides
    /dev/spidev0.0 and /dev/gpiochip*, PrivateUsers unmaps SupplementaryGroups."""
    assert unit.values("Service", "PrivateDevices") == []
    assert unit.values("Service", "PrivateUsers") == []


def test_the_network_is_loopback_over_inet_and_unix_sockets_only(unit):
    assert unit.values("Service", "IPAddressDeny") == ["any"]
    assert unit.values("Service", "IPAddressAllow") == ["localhost"]
    assert set(unit.one("Service", "RestrictAddressFamilies").split()) == {"AF_INET", "AF_UNIX"}


def test_the_service_has_no_capabilities_and_cannot_gain_privileges(unit):
    assert unit.one("Service", "CapabilityBoundingSet") == ""
    assert unit.one("Service", "AmbientCapabilities") == ""
    assert unit.one("Service", "NoNewPrivileges") == "yes"


def test_the_token_arrives_as_a_credential_the_script_stores(unit, script):
    assert unit.values("Service", "LoadCredential") == \
        [f"{P.CREDENTIAL}:/etc/credstore/smylte-panel-token"]
    credstore = re.search(r"^CREDSTORE=(\S+)$", script, re.M)
    cred = re.search(r"^CRED=\$CREDSTORE/(\S+)$", script, re.M)
    assert credstore and credstore.group(1) == "/etc/credstore"
    assert cred and cred.group(1) == "smylte-panel-token"


def test_the_token_is_never_in_the_environment(unit, script):
    # The one EnvironmentFile is the optional PWR setting, which the script
    # also hands to its one-off runs. The token is only ever the credential.
    assert unit.values("Service", "EnvironmentFile") == ["-/etc/default/smylte-panel"]
    env = re.search(r"^PANEL_ENV=(\S+)$", script, re.M)
    assert env and env.group(1) == "/etc/default/smylte-panel"
    assert "$PANEL_ENV" not in "\n".join(
        line for line in script.splitlines() if "TOKEN" in line)
    for value in unit.values("Service", "Environment"):
        assert "token" not in value.lower(), value


def test_the_exec_lines_run_the_root_owned_copy_under_isolated_python(unit, script):
    assert unit.one("Service", "ExecStart") == \
        "/usr/bin/python3 -I -B /usr/local/lib/smylte-panel/panel.py"
    assert unit.one("Service", "ExecStopPost") == \
        "-/usr/bin/python3 -I -B /usr/local/lib/smylte-panel/panel.py --power-off"
    lib = re.search(r"^LIB=(\S+)$", script, re.M)
    py = re.search(r"^PY=(\S+)$", script, re.M)
    assert lib and lib.group(1) == "/usr/local/lib/smylte-panel"
    assert py and py.group(1) == "/usr/bin/python3"


def test_a_failure_restarts_but_a_configuration_error_does_not(unit):
    assert unit.one("Service", "Restart") == "on-failure"
    assert int(unit.one("Service", "RestartSec")) >= 1
    # 78 is the client's EX_CONFIG. 243 is systemd's EXIT_CREDENTIALS: a
    # missing token file fails the unit before the client runs.
    assert unit.one("Service", "RestartPreventExitStatus").split() == \
        [str(P.EX_CONFIG), "243"]


def test_stopping_waits_out_a_refresh_and_a_fetch(unit):
    timeout = float(unit.one("Service", "TimeoutStopSec"))
    assert timeout >= E.PAINT_WORST_S + E.DEEP_SLEEP_SETTLE_S + 15
    assert timeout >= P.FETCH_DEADLINE_S + 15


def test_the_watchdog_outlasts_the_longest_wait_between_pings(unit):
    assert unit.one("Service", "Type") == "notify"
    assert unit.one("Service", "NotifyAccess") == "main"
    watchdog = int(unit.one("Service", "WatchdogSec"))
    assert watchdog > P.SOCKET_TIMEOUT_S + P.PING_SLICE_S
    assert watchdog > 2 * P.PING_SLICE_S


def test_the_unit_is_not_coupled_to_the_server_unit(unit):
    for key in ("After", "Before", "Requires", "Wants", "PartOf", "BindsTo", "Requisite"):
        for value in unit.values("Unit", key):
            assert "smylte.service" not in value, f"[Unit] {key}={value}"


def _string_constants_outside_docstrings(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def test_proc_subset_is_pid_only_while_the_code_never_reads_proc(unit):
    """ProcSubset=pid hides /proc/cpuinfo and friends. That is safe only while
    neither the client nor the driver names a /proc path (Waveshare's own
    epdconfig reads /proc/cpuinfo at import; ours must not)."""
    assert unit.one("Service", "ProcSubset") == "pid"
    for path in (F.DRIVER_PY, F.PANEL_PY):
        for s in _string_constants_outside_docstrings(path):
            assert "/proc" not in s, f"{path.name} names {s!r}"


def test_the_state_directory_is_named_in_the_unit_and_the_script(unit, script):
    assert unit.one("Service", "StateDirectory") == "smylte-panel"
    assert "StateDirectory=smylte-panel" in script
    assert "/var/lib/private/smylte-panel" in script


def test_the_unit_is_installed_for_boot(unit):
    assert unit.one("Install", "WantedBy") == "multi-user.target"


def test_the_start_limit_is_in_the_unit_section_where_systemd_reads_it(unit):
    assert int(unit.one("Unit", "StartLimitBurst")) >= 1
    assert int(unit.one("Unit", "StartLimitIntervalSec")) >= 60
    assert unit.values("Service", "StartLimitBurst") == []
    assert unit.values("Service", "StartLimitIntervalSec") == []


# ── the script ───────────────────────────────────────────────────────────────

def test_the_script_passes_bash_syntax_check():
    if shutil.which("bash") is None:
        pytest.skip("no bash")
    result = subprocess.run(["bash", "-n", str(F.SETUP_SH)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_script_is_executable():
    assert os.stat(F.SETUP_SH).st_mode & 0o111


def test_the_token_is_read_without_echo(script):
    assert "IFS= read -rsp" in script


_TOKEN_ALLOWED = [
    re.compile(r"^\s*printf '%s\\n' \"\$TOKEN\" >\"\$tmp\"\s*$"),
    re.compile(r"printf '%s' \"\$TOKEN\" \| \"\$PY\""),
    re.compile(r"^\s*TOKEN=\$tok\s*$"),
    re.compile(r"^\s*TOKEN=\s*$"),
]
# read_token()'s own copies of the secret, and the only lines that may use them.
_LOCAL_OK = {
    'case "$raw" in',
    '*/display/*) tok=${raw#*/display/}; tok=${tok%%[.?/#]*} ;;',
    '*) tok=$raw ;;',
    'tok=${tok//[[:space:]]/}',
    '[[ $tok =~ ^[A-Za-z0-9_-]{22,128}$ ]] || die "that is not a display token (22–128 of A–Z a–z 0–9 _ -)"',
    'TOKEN=$tok',
}


def _token_expansions(text: str) -> tuple[int, list[str]]:
    """(lines that expand $TOKEN, lines that expand the token anywhere they
    should not). Every expansion form counts: $TOKEN, ${TOKEN}, ${TOKEN:...},
    ${TOKEN:-...}, and read_token()'s $raw and $tok. Only ${TOKEN:0:4} may be
    printed."""
    token = re.compile(r"\$\{?TOKEN\b")
    local = re.compile(r"\$\{?(raw|tok)\b")
    seen, bad = 0, []
    for line in text.splitlines():
        rest = line.replace("${TOKEN:0:4}", "")
        if token.search(rest):
            seen += 1
            if not any(r.search(rest) for r in _TOKEN_ALLOWED):
                bad.append(line)
        if local.search(line) and line.strip() not in _LOCAL_OK:
            bad.append(line)
    return seen, bad


def test_the_token_is_printed_only_as_its_first_four_characters(script):
    seen, bad = _token_expansions(script)
    assert seen, "no line expands the token: the check is looking at the wrong thing"
    assert bad == [], f"the token is expanded here: {bad!r}"


@pytest.mark.parametrize("old, new", [
    ("stored ${TOKEN:0:4}…", "stored ${TOKEN:0:43}…"),
    ("stored ${TOKEN:0:4}…", "stored ${TOKEN:-}…"),
    ("stored ${TOKEN:0:4}…", "stored ${TOKEN}…"),
    ("stored ${TOKEN:0:4}…", "stored ${TOKEN:0:4}${TOKEN:4}…"),
    ("  TOKEN=$tok\n}", '  echo "  read $tok" >&2\n  TOKEN=$tok\n}'),
    ('  IFS= read -rsp "Token: " raw; echo',
     '  IFS= read -rsp "Token: " raw; echo "got $raw"'),
], ids=["slice", "default", "braces", "two-slices", "tok-to-stderr", "raw-echoed"])
def test_the_token_check_catches_every_way_of_printing_it(script, old, new):
    assert script.count(old) == 1, old
    seen, bad = _token_expansions(script.replace(old, new))
    assert bad, f"{new!r} printed the token and the check missed it"


@pytest.mark.parametrize("line", [
    'install -d -m 0700 -o root -g root "$CREDSTORE"',
    'chmod 0600 "$tmp"',
    'chown root:root "$tmp"',
    'install -m 0644 -o root -g root "$SRC/$f" "$LIB/$f"',
    'install -m 0644 -o root -g root "$UNIT_SRC" "$UNIT"',
])
def test_the_script_sets_root_owned_modes_on_what_it_writes(script, line):
    assert line in script


def test_the_python_check_matches_the_servers_setup_script(script):
    arm = re.compile(r"^\s*(3\.\d+\|3\.\d+)\)", re.M)
    ours = arm.search(script)
    theirs = arm.search((F.REPO / "deploy" / "setup.sh").read_text(encoding="utf-8"))
    assert ours and theirs
    assert ours.group(1) == theirs.group(1)


def test_the_installed_files_are_exactly_the_clients_files(script):
    m = re.search(r'^FILES="([^"]+)"$', script, re.M)
    assert m
    files = set(m.group(1).split())
    assert files == {"panel.py", "epd7in5_v2.py"}
    assert files == {p.name for p in F.PI_DIR.glob("*.py")}


def _read_token_program(script: str) -> str:
    m = re.search(r"read_token\(\) \{\n(.*?)\n\}\n", script, re.S)
    assert m, "read_token() not found"
    lines = []
    for line in m.group(1).split("\n"):
        if "read -rsp" in line:
            line = "raw=$INPUT"
        elif line.lstrip().startswith('echo "Paste'):
            continue
        lines.append(line)
    body = "\n".join(lines)
    return 'die() { echo "DIE:$*"; exit 3; }\nTOKEN=\nf() {\n' + body + '\n}\nf\nprintf \'%s\' "$TOKEN"\n'


_TOK = "A1b2_" + "x" * 38


def _run_read_token(script: str, value: str):
    if shutil.which("bash") is None:
        pytest.skip("no bash")
    return subprocess.run(["bash", "-c", _read_token_program(script)],
                          env={"INPUT": value, "PATH": os.environ["PATH"]},
                          capture_output=True, text=True)


def _function(script: str, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{.*?\n\}}\n", script, re.S | re.M)
    assert m, f"{name}() not found"
    return m.group(0)


_FAKE_SYSTEMCTL = """#!/bin/bash
echo "$*" >> "$LOG"
if [ "$1" = show ]; then echo "$FAKE_STATE"; fi
exit 0
"""


def _run_with_systemctl(tmp_path, program: str, state: str = "inactive"):
    if shutil.which("bash") is None:
        pytest.skip("no bash")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "systemctl"
    fake.write_text(_FAKE_SYSTEMCTL)
    fake.chmod(0o755)
    log = tmp_path / "systemctl.log"
    log.write_text("")
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\nUNIT_NAME=smylte-panel.service\n" + program],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log),
             "FAKE_STATE": state},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result, log.read_text().splitlines()


@pytest.mark.parametrize("value", [
    _TOK,
    f"https://box.example/display/{_TOK}",
    f"https://box.example/api/public/display/{_TOK}.bin?invert=1",
    f"  {_TOK}  ",
    f"https://box.example/display/{_TOK}#frag",
], ids=["bare", "display-url", "api-url", "padded", "fragment"])
def test_a_pasted_url_is_cut_down_to_the_token(script, value):
    assert len(_TOK) == 43
    result = _run_read_token(script, value)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == _TOK


@pytest.mark.parametrize("value", [
    "https://box.example/display/short",
    "",
    _TOK + "!",
], ids=["too-short", "empty", "bad-character"])
def test_something_that_is_not_a_token_is_refused(script, value):
    result = _run_read_token(script, value)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "DIE:" in result.stdout


@pytest.mark.parametrize("state, stops, was_active", [
    ("active", True, "yes"),
    ("activating", True, "yes"),      # waiting out RestartSec after a fault
    ("reloading", True, "yes"),
    ("deactivating", True, "no"),
    ("inactive", False, "no"),
    ("failed", False, "no"),
])
def test_a_one_off_stops_any_unit_that_could_still_take_the_lines(
        tmp_path, script, state, stops, was_active):
    program = ("WAS_ACTIVE=no\n" + _function(script, "stop_service")
               + 'stop_service >/dev/null\necho "WAS_ACTIVE=$WAS_ACTIVE"\n')
    result, calls = _run_with_systemctl(tmp_path, program, state)
    assert calls[0] == "show -P ActiveState smylte-panel.service"
    assert ("stop smylte-panel.service" in calls) is stops, calls
    assert result.stdout.strip().endswith(f"WAS_ACTIVE={was_active}")


def test_every_start_the_script_makes_resets_the_start_count_first(tmp_path, script):
    program = _function(script, "start_service") + "start_service restart\n"
    _, calls = _run_with_systemctl(tmp_path, program)
    assert calls == ["reset-failed smylte-panel.service",
                     "restart smylte-panel.service"]
    body = _function(script, "start_service")
    for line in script.replace(body, "").splitlines():
        code = line.split("#", 1)[0]
        if "echo" in code:
            continue
        assert not re.search(r"\bsystemctl\s+(start|restart)\b", code), \
            f"starts the unit without start_service: {line!r}"


@pytest.mark.parametrize("content, expected", [
    (None, ""),
    ("", ""),
    ("SMYLTE_PANEL_PWR_PIN=18\n", "18"),
    ('SMYLTE_PANEL_PWR_PIN="18"\n', "18"),
    ("# a comment\nSMYLTE_PANEL_PWR_PIN=17\n  SMYLTE_PANEL_PWR_PIN = '18' \n", "18"),
    ("OTHER=1\n", ""),
], ids=["no-file", "empty", "plain", "quoted", "last-wins", "other"])
def test_the_pwr_setting_is_read_as_the_unit_reads_it(tmp_path, script, content, expected):
    env = tmp_path / "panel.env"
    if content is not None:
        env.write_text(content)
    program = (f"PANEL_ENV={env}\n" + _function(script, "pwr_setting")
               + 'printf "[%s]" "$(pwr_setting)"\n')
    result, _ = _run_with_systemctl(tmp_path, program)
    assert result.stdout == f"[{expected}]"
    assert P.PWR_PIN_ENV in _function(script, "pwr_setting")


def test_the_one_off_runs_get_the_services_pwr_setting(script, unit):
    body = _function(script, "run_oneoff")
    assert '-p "EnvironmentFile=-$PANEL_ENV"' in body
    assert f'{P.PWR_PIN_ENV}=$(pwr_setting) "$PY" -I -B "$LIB/panel.py" --power-off' in body
    assert unit.values("Service", "EnvironmentFile") == [
        "-" + re.search(r"^PANEL_ENV=(\S+)$", script, re.M).group(1)]


def _case_arm(script: str, label: str) -> str:
    m = re.search(rf"^\s*{re.escape(label)}\)\n(.*?)\n\s*;;\n", script, re.S | re.M)
    assert m, f"no case arm {label})"
    return m.group(1)


def test_uninstall_removes_the_drop_ins_and_the_pwr_file_after_the_clear(script):
    arm = _case_arm(script, "--uninstall")
    clear = arm.index("run_oneoff --clear")
    rm_env = re.search(r'^\s*rm -f .*"\$PANEL_ENV"', arm, re.M)
    rm_dropins = re.search(r'^\s*rm -rf .*"\$UNIT\.d"', arm, re.M)
    reload_ = arm.index("systemctl daemon-reload")
    assert rm_env and rm_dropins
    assert clear < rm_env.start() < reload_
    assert clear < rm_dropins.start() < reload_


def test_rotate_token_restarts_only_a_unit_that_is_running_or_failed(script):
    arm = _case_arm(script, "--rotate-token")
    assert "is-enabled" not in arm
    assert "show -P ActiveState" in arm
    m = re.search(r"^\s*([a-z|]+)\)\n\s*start_service restart", arm, re.M)
    assert m, arm
    assert set(m.group(1).split("|")) == {"active", "activating", "reloading",
                                          "refreshing", "failed"}


def test_clear_claims_success_only_when_it_succeeded(script):
    arm = _case_arm(script, "--selftest|--clear")
    assert re.search(r'if \[ "\$rc" -eq 0 \]; then echo "  ✓ cleared to white"', arm), arm


@pytest.mark.parametrize("mode", [
    "--rotate-token", "--selftest", "--clear", "--status", "--uninstall", "--no-selftest",
])
def test_every_mode_the_header_documents_is_handled(script, mode):
    lines = script.splitlines()
    header = [l for l in lines if l.startswith("#") and not l.startswith("#!")]
    code = "\n".join(l for l in lines if not l.lstrip().startswith("#"))
    assert any(mode in l for l in header), f"{mode} is not in the header comment"
    if mode == "--no-selftest":
        assert f'"{mode}"' in code
        return
    label = re.search(rf"^\s*(?:[\w-]+\|)*{re.escape(mode)}(?:\|[\w-]+)*\)", code, re.M)
    compare = re.search(rf"""=\s*["']?{re.escape(mode)}["']?""", code)
    assert label or compare, f"{mode} is documented but no case label or comparison handles it"


# ── licence and layout ───────────────────────────────────────────────────────

def test_the_firmware_is_mit_licensed_and_each_client_file_says_so():
    licence = F.REPO / "firmware" / "LICENSE"
    assert licence.exists()
    assert "MIT" in licence.read_text(encoding="utf-8")
    for path in F.PI_DIR.glob("*.py"):
        first = "\n".join(path.read_text(encoding="utf-8").splitlines()[:3])
        assert "SPDX-License-Identifier: MIT" in first, path.name
