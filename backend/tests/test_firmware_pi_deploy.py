"""The Pi panel's systemd unit and install script, held to the client.

`deploy/smylte-panel.service`, `deploy/panel-setup.sh` and the files beside them
(the udev rule, the power-off path and service, the logind drop-in) hold numbers
and names that only mean something next to the client: the credential's name, the
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
import pathlib
import re
import shutil
import signal
import subprocess
import time

import pytest

import pi_panel_fakes as F

P = F.load_panel()
E = F.load_driver()

DEPLOY = F.REPO / "deploy"
KEY_GROUP = "smylte-panel-key"


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

def test_the_service_runs_as_a_dynamic_user_in_the_gpio_spi_and_key_groups(unit):
    assert unit.one("Service", "DynamicUser") == "yes"
    groups = set(unit.one("Service", "SupplementaryGroups").split())
    assert groups == {"gpio", "spi", KEY_GROUP}
    assert "input" not in groups      # it would open every keyboard
    assert unit.values("Service", "User") == []
    assert unit.values("Service", "Group") == []


def test_the_device_policy_allows_only_the_spi_gpiochip_and_input_nodes(unit):
    assert unit.one("Service", "DevicePolicy") == "closed"
    assert sorted(unit.values("Service", "DeviceAllow")) == \
        ["char-gpiochip rw", "char-input r", "char-spi rw"]


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
    # The one EnvironmentFile is the settings file, which the script also hands
    # to its one-off runs. The token is only ever the credential.
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
    'install -m "$1" -o root -g root -- "$2" "$3.new" && mv -f -- "$3.new" "$3"',
    'put 0644 "$SRC/$f" "$LIB/$f"',
    'put 0644 "$UNIT_SRC" "$UNIT"',
    'put 0644 "$UPDATER_SRC" "$UPDATER"',
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
        # Only the panel unit's own starts need the reset: the power-off path
        # unit has no start limit, and is started with its own command.
        if '"$UNIT_NAME"' not in code:
            continue
        assert not re.search(r"\bsystemctl\s+(start|restart|enable\s+--now)\b", code), \
            f"starts the unit without start_service: {line!r}"


@pytest.mark.parametrize("content, expected", [
    (None, "18"),
    ("", "18"),
    ("SMYLTE_PANEL_PWR_PIN=\n", "18"),
    ("SMYLTE_PANEL_PWR_PIN=18\n", "18"),
    ('SMYLTE_PANEL_PWR_PIN="18"\n', "18"),
    ("SMYLTE_PANEL_PWR_PIN=none\n", "none"),
    ("# a comment\nSMYLTE_PANEL_PWR_PIN=17\n  SMYLTE_PANEL_PWR_PIN = '19' \n", "19"),
    ("OTHER=1\n", "18"),
], ids=["no-file", "empty", "blank-value", "plain", "quoted", "none", "last-wins", "other"])
def test_the_pwr_setting_is_read_as_the_unit_reads_it(tmp_path, script, content, expected):
    env = tmp_path / "panel.env"
    if content is not None:
        env.write_text(content)
    program = (f"PANEL_ENV={env}\n" + _function(script, "setting")
               + _function(script, "pwr_setting")
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


def test_clear_leaves_the_unit_inactive_so_rotate_token_keeps_it_stopped(script):
    arm = _case_arm(script, "--selftest|--clear")
    branch = arm[arm.index('if [ "$MODE" = --clear ]; then'):]
    reset = branch.find('systemctl reset-failed "$UNIT_NAME"')
    assert 0 < reset < branch.index('if [ "$rc" -eq 0 ]'), branch


@pytest.mark.parametrize("label, before, after", [
    ("install", "stop_service", "run_oneoff --selftest"),
    ("--selftest|--clear", "stop_service", 'run_oneoff "$MODE"'),
    ("--uninstall", "systemctl disable --now", "run_oneoff --clear"),
])
def test_every_one_off_runs_with_the_service_stopped(script, label, before, after):
    arm = _case_arm(script, label)
    assert before in arm and after in arm, arm
    assert arm.index(before) < arm.index(after)


@pytest.mark.parametrize("mode", [
    "--rotate-token", "--selftest", "--clear", "--keytest", "--reset-refresh",
    "--update", "--status", "--uninstall", "--no-selftest",
])
def test_every_mode_the_header_documents_is_handled(script, mode):
    lines = script.splitlines()
    header = [l for l in lines if l.startswith("#") and not l.startswith("#!")]
    code = "\n".join(l for l in lines if not l.lstrip().startswith("#"))
    assert any(mode in l for l in header), f"{mode} is not in the header comment"
    if mode == "--update":
        assert any(mode in l and "desk key runs" in l for l in header), header
    if mode == "--no-selftest":
        assert f'"{mode}"' in code
        return
    label = re.search(rf"^\s*(?:[\w-]+\|)*{re.escape(mode)}(?:\|[\w-]+)*\)", code, re.M)
    compare = re.search(rf"""=\s*["']?{re.escape(mode)}["']?""", code)
    assert label or compare, f"{mode} is documented but no case label or comparison handles it"


# ── the view key: group, udev rule, power-off units, logind ──────────────────

def _deploy_text(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def _active_lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]


def test_the_unit_has_a_run_directory_only_it_can_use(unit):
    assert unit.one("Service", "RuntimeDirectory") == "smylte-panel"
    assert unit.one("Service", "RuntimeDirectoryMode") == "0700"


def test_the_poweroff_path_watches_the_clients_request_file(unit):
    path = Unit(_deploy_text("smylte-panel-poweroff.path"))
    watched = "/run/" + unit.one("Service", "RuntimeDirectory") + "/" + P.POWEROFF_NAME
    assert path.one("Path", "PathExists") == watched
    assert path.one("Path", "Unit") == "smylte-panel-poweroff.service"
    assert path.one("Unit", "Description") == "Power off when the Smylte desk panel asks"
    assert path.one("Install", "WantedBy") == "multi-user.target"
    assert list(path.sections) == ["Unit", "Path", "Install"]


def test_the_poweroff_service_deletes_the_request_before_it_powers_off(unit):
    off = Unit(_deploy_text("smylte-panel-poweroff.service"))
    watched = Unit(_deploy_text("smylte-panel-poweroff.path")).one("Path", "PathExists")
    assert off.one("Unit", "Description") == "Power off at the Smylte desk panel's request"
    assert off.one("Service", "Type") == "oneshot"
    # PathExists= is level-triggered: a request left in place would start this
    # unit again as soon as it finished.
    assert off.values("Service", "ExecStart") == [
        f"/usr/bin/rm -f {watched}",
        "/usr/bin/systemctl --no-block poweroff",
    ]
    assert off.values("Install", "WantedBy") == []     # started by the path only
    assert list(off.sections) == ["Unit", "Service"]


def test_the_udev_rule_gives_only_the_power_key_to_the_key_group(unit):
    rules = _active_lines(_deploy_text("70-smylte-panel-key.rules"))
    assert len(rules) == 1
    rule = rules[0]
    assert f'ATTRS{{name}}=="{P.KEY_DEVICE_NAME}"' in rule
    assert 'SUBSYSTEM=="input"' in rule and 'KERNEL=="event*"' in rule
    # `:=` is final: 99-com.rules sets GROUP="input" on every input node.
    assert f'GROUP:="{KEY_GROUP}"' in rule
    assert 'MODE:="0640"' in rule
    key_groups = set(unit.one("Service", "SupplementaryGroups").split()) - {"gpio", "spi"}
    assert key_groups == {KEY_GROUP}


def test_the_logind_drop_in_ignores_the_power_key_and_nothing_else(script):
    logind = Unit(_deploy_text("logind-smylte-panel.conf"))
    assert logind.sections == {"Login": [("HandlePowerKey", "ignore"),
                                         ("HandlePowerKeyLongPress", "ignore")]}
    installed = re.search(r"^LOGIND=(\S+)$", script, re.M)
    assert installed and installed.group(1) == P.LOGIND_DROPIN


@pytest.mark.parametrize("var, src, dst", [
    ("RULES", "70-smylte-panel-key.rules", "/etc/udev/rules.d/70-smylte-panel-key.rules"),
    ("PATH_UNIT", "smylte-panel-poweroff.path", "/etc/systemd/system/smylte-panel-poweroff.path"),
    ("OFF_UNIT", "smylte-panel-poweroff.service", "/etc/systemd/system/smylte-panel-poweroff.service"),
    ("LOGIND", "logind-smylte-panel.conf", "/etc/systemd/logind.conf.d/50-smylte-panel.conf"),
    ("UPD_PATH_UNIT", "smylte-panel-update.path", "/etc/systemd/system/smylte-panel-update.path"),
    ("UPD_UNIT", "smylte-panel-update.service", "/etc/systemd/system/smylte-panel-update.service"),
    ("UPDATER", "smylte-panel-update.sh", "$LIB/update.sh"),
])
def test_the_script_installs_each_new_file_from_the_checkout_to_its_place(script, var, src, dst):
    assert (DEPLOY / src).exists()
    assert re.search(rf"^{var}={re.escape(dst)}$", script, re.M)
    src_var = {"PATH_UNIT": "PATH_SRC", "OFF_UNIT": "OFF_SRC",
               "RULES": "RULES_SRC", "LOGIND": "LOGIND_SRC", "UPD_PATH_UNIT": "UPD_PATH_SRC",
               "UPD_UNIT": "UPD_SRC", "UPDATER": "UPDATER_SRC"}[var]
    assert re.search(rf"^{src_var}=\$REPO/deploy/{re.escape(src)}$", script, re.M)
    assert re.search(r"^KEY_GROUP=" + KEY_GROUP + "$", script, re.M)
    # The path unit's variable is not PATH: that is the shell's own.
    assert not re.search(r"^PATH=", script, re.M)


# ── fake systemd for running pieces of the script ────────────────────────────

_FAKES = {
    "systemctl": """#!/bin/bash
echo "systemctl $*" >> "$LOG"
st=$(cat "$STATE_FILE")
case "$1" in
  show) echo "$st" ;;
  is-active) [ "$st" = active ] || exit 3 ;;
  stop) case "${2:-}" in
          smylte-panel-*) rm -f "${MARKER:-/nonexistent}" ;;    # a one-off's own unit
          *) echo inactive > "$STATE_FILE" ;;
        esac ;;
  start|restart) [ ! -e "${MARKER:-/nonexistent}" ] || echo "START-WHILE-ONEOFF-RUNNING" >> "$LOG"
                 echo active > "$STATE_FILE" ;;
esac
exit 0
""",
    # Answers only for the exact call logind_running makes, so a wrong object,
    # interface or a missing --value reads as a failure. RUNNING and RUNNING_LONG
    # are what the running logind says; RUNNING_FAILS makes the call fail.
    "busctl": """#!/bin/bash
[ -z "${RUNNING_FAILS:-}" ] || exit 1
[ "$1 $2 $3 $4 $5" = "--value get-property org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager" ] || exit 1
case "$6" in
  HandlePowerKey) printf '%s\\n' "${RUNNING-ignore}" ;;
  HandlePowerKeyLongPress) printf '%s\\n' "${RUNNING_LONG-ignore}" ;;
  *) exit 1 ;;
esac
""",
    "systemd-run": """#!/bin/bash
echo "systemd-run $*" >> "$LOG"
if [ -n "${FAKE_RUN_SIGNAL:-}" ]; then kill -TERM "$PPID"; sleep 0.2; fi
exit "${FAKE_RUN_RC:-0}"
""",
    "systemd-analyze": """#!/bin/bash
if [ "$1" = cat-config ]; then printf '%s' "$CAT"; else echo "systemd-analyze $*" >> "$LOG"; fi
""",
    "python3": """#!/bin/bash
echo "python3 $*" >> "$LOG"
""",
    "chown": "#!/bin/bash\nexit 0\n",
}


def _run_fake(tmp_path, program, *, state="inactive", cat="", env=None, fakes=None):
    """Run `program` in bash with fake systemctl, systemd-run, systemd-analyze,
    python3 and chown first on PATH. Returns (result, the log's lines)."""
    if shutil.which("bash") is None:
        pytest.skip("no bash")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in {**_FAKES, **(fakes or {})}.items():
        fake = bin_dir / name
        fake.write_text(body)
        fake.chmod(0o755)
    log = tmp_path / "fake.log"
    log.write_text("")
    state_file = tmp_path / "state"
    state_file.write_text(state)
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + program],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log),
             "STATE_FILE": str(state_file), "CAT": cat, **(env or {})},
        capture_output=True, text=True)
    return result, log.read_text().splitlines()


def _arm_program(tmp_path, script, label, functions):
    """The case arm `label`, with the variables and helpers it needs, as a
    program. LIB holds a panel.py so that the 'not installed' check passes."""
    lib = tmp_path / "lib"
    lib.mkdir(exist_ok=True)
    (lib / "panel.py").write_text("")
    head = (f"UNIT_NAME=smylte-panel.service\nLIB={lib}\nPY={tmp_path / 'bin' / 'python3'}\n"
            f"PANEL_ENV={tmp_path / 'panel.env'}\nKEY_GROUP={KEY_GROUP}\nWAS_ACTIVE=no\nONEOFF=\n"
            'die() { echo "DIE:$*"; exit 3; }\nsay() { echo "== $* =="; }\n'
            "take_lock() { :; }\n")
    return head + "".join(_function(script, f) for f in functions) + _case_arm(script, label) + "\n"


_ONEOFF_FUNCTIONS = ["setting", "pwr_setting", "stop_service", "start_service",
                     "restart_if_was_active", "arm_restart_trap", "disarm_restart_trap",
                     "run_oneoff"]


def _index(calls, prefix, start=0):
    for i, line in enumerate(calls):
        if i >= start and line.startswith(prefix):
            return i
    raise AssertionError(f"no {prefix!r} after {start} in {calls}")


# ── the settings ─────────────────────────────────────────────────────────────

_DEFAULTS = {"SMYLTE_PANEL_PWR_PIN": "18", "SMYLTE_PANEL_REFRESH": "fast",
             "SMYLTE_PANEL_IDLE_RETURN_S": "0", "SMYLTE_PANEL_KEY": "auto"}


@pytest.mark.parametrize("content, expected", [
    (None, "fast"),
    ("", "fast"),
    ("SMYLTE_PANEL_REFRESH=\n", "fast"),
    ("SMYLTE_PANEL_REFRESH=full\n", "full"),
    ('SMYLTE_PANEL_REFRESH = "full"\n', "full"),
    ("SMYLTE_PANEL_REFRESH=full\n# SMYLTE_PANEL_REFRESH=slow\nSMYLTE_PANEL_REFRESH=fast\n", "fast"),
    ("SMYLTE_PANEL_REFRESH_X=full\n", "fast"),
], ids=["no-file", "empty", "blank-value", "plain", "quoted-spaced", "last-wins", "other-name"])
def test_any_setting_is_read_like_the_pwr_pin_with_its_own_default(tmp_path, script, content, expected):
    env = tmp_path / "panel.env"
    if content is not None:
        env.write_text(content)
    program = (f"PANEL_ENV={env}\n" + _function(script, "setting")
               + 'printf "[%s]" "$(setting SMYLTE_PANEL_REFRESH fast)"\n')
    result, _ = _run_fake(tmp_path, program)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"[{expected}]"


def _check_settings(tmp_path, script, content):
    env = tmp_path / "panel.env"
    env.write_text(content)
    program = (f"PANEL_ENV={env}\n" + _function(script, "setting")
               + _function(script, "pwr_setting") + _function(script, "check_settings")
               + 'rc=0; check_settings || rc=$?\necho "rc=$rc"\n')
    result, _ = _run_fake(tmp_path, program)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("content", [
    "",
    "SMYLTE_PANEL_PWR_PIN=none\n",
    "SMYLTE_PANEL_PWR_PIN=18\nSMYLTE_PANEL_REFRESH=full\n",
    "SMYLTE_PANEL_IDLE_RETURN_S=0\n",
    "SMYLTE_PANEL_IDLE_RETURN_S=60\n",
    "SMYLTE_PANEL_IDLE_RETURN_S=86400\n",
    "SMYLTE_PANEL_KEY=off\n",
], ids=["defaults", "pwr-none", "full", "idle-0", "idle-60", "idle-86400", "key-off"])
def test_preflight_accepts_what_the_client_accepts(tmp_path, script, content):
    out = _check_settings(tmp_path, script, content)
    assert out.rstrip().endswith("rc=0"), out
    assert "✗" not in out
    assert len([l for l in out.splitlines() if l.startswith("  ✓")]) == 4   # one line each


@pytest.mark.parametrize("content, name", [
    ("SMYLTE_PANEL_PWR_PIN=abc\n", "SMYLTE_PANEL_PWR_PIN"),
    ("SMYLTE_PANEL_PWR_PIN=123\n", "SMYLTE_PANEL_PWR_PIN"),
    ("SMYLTE_PANEL_REFRESH=slow\n", "SMYLTE_PANEL_REFRESH"),
    ("SMYLTE_PANEL_IDLE_RETURN_S=30\n", "SMYLTE_PANEL_IDLE_RETURN_S"),
    ("SMYLTE_PANEL_IDLE_RETURN_S=86401\n", "SMYLTE_PANEL_IDLE_RETURN_S"),
    ("SMYLTE_PANEL_IDLE_RETURN_S=-1\n", "SMYLTE_PANEL_IDLE_RETURN_S"),
    ("SMYLTE_PANEL_IDLE_RETURN_S=soon\n", "SMYLTE_PANEL_IDLE_RETURN_S"),
    ("SMYLTE_PANEL_KEY=maybe\n", "SMYLTE_PANEL_KEY"),
], ids=["pwr-text", "pwr-3-digits", "refresh", "idle-30", "idle-86401", "idle-negative",
        "idle-text", "key"])
def test_preflight_refuses_a_bad_setting_and_names_it(tmp_path, script, content, name):
    out = _check_settings(tmp_path, script, content)
    assert out.rstrip().endswith("rc=1"), out
    assert any(l.startswith("  ✗") and name in l and "sudoedit" in l for l in out.splitlines()), out


@pytest.mark.parametrize("value", ["", "none"] + [str(n) for n in range(100)]
                         + ["02", "08", "007", "027", "028", "00", "None"])
def test_preflight_accepts_a_pwr_pin_exactly_when_the_client_does(
        tmp_path, script, monkeypatch, value):
    out = _check_settings(tmp_path, script, f"SMYLTE_PANEL_PWR_PIN={value}\n")
    monkeypatch.setenv(P.PWR_PIN_ENV, value)
    try:
        P.pwr_pin_from_env()
        client_accepts = True
    except P.ConfigError:
        client_accepts = False
    assert out.rstrip().endswith("rc=0" if client_accepts else "rc=1"), (value, out)


def test_the_script_names_the_settings_the_client_reads(script):
    for const in (P.PWR_PIN_ENV, P.REFRESH_ENV, P.IDLE_ENV, P.KEY_ENV):
        assert const in _function(script, "check_settings") or const in _function(script, "pwr_setting")
        assert const in _function(script, "write_settings")


def _write_settings(tmp_path, script, existing):
    env = tmp_path / "default" / "smylte-panel"
    env.parent.mkdir(exist_ok=True)
    if existing is not None:
        env.write_text(existing)
    program = (f"PANEL_ENV={env}\n" + _function(script, "write_settings") + "write_settings\n")
    result, _ = _run_fake(tmp_path, program)
    assert result.returncode == 0, result.stderr
    return env, result.stdout


def test_the_settings_file_is_written_once_with_the_defaults(tmp_path, script):
    env, out = _write_settings(tmp_path, script, None)
    assert out.startswith("  wrote ") and str(env) in out
    assert oct(env.stat().st_mode & 0o777) == "0o644"
    text = env.read_text(encoding="utf-8")
    assert "sudoedit /etc/default/smylte-panel" in text
    assignments = dict(l.split("=", 1) for l in text.splitlines() if re.match(r"^[A-Z_]+=", l))
    assert assignments == _DEFAULTS
    assert set(assignments) == {P.PWR_PIN_ENV, P.REFRESH_ENV, P.IDLE_ENV, P.KEY_ENV}
    assert [p.name for p in env.parent.iterdir()] == ["smylte-panel"]    # no temp file left
    # What it says is what the client does with no file at all.
    assert P.pwr_pin_from_env() == 18


def test_an_existing_settings_file_is_kept(tmp_path, script):
    env, out = _write_settings(tmp_path, script, "SMYLTE_PANEL_KEY=off\n")
    assert out.startswith("  kept ") and "(yours)" in out
    assert env.read_text() == "SMYLTE_PANEL_KEY=off\n"


# ── the install, in order ────────────────────────────────────────────────────

def test_install_orders_settings_files_key_check_logind_path_unit_token_selftest_then_service(script):
    """The path unit is up before the trap or a failed self-test can start the
    new service, which would otherwise run with nothing to act on a power-off."""
    arm = _case_arm(script, "install")
    steps = ["take_lock", "preflight ||", "write_settings", "install_files", "check_key_node",
             "apply_logind",
             "systemctl enable smylte-panel-poweroff.path",
             "systemctl start smylte-panel-poweroff.path",
             "systemctl enable smylte-panel-update.path",
             "systemctl start smylte-panel-update.path",
             "sc=$(server_checkout)",
             'TOKEN=$(tr -d', "probe_token", "arm_restart_trap", "run_oneoff --selftest",
             'systemctl enable "$UNIT_NAME"', "start_service restart"]
    at = [arm.index(step) for step in steps]
    assert at == sorted(at), dict(zip(steps, at))
    assert arm.count("apply_logind") == 1


def test_install_probes_the_token_on_every_run_and_reads_a_stored_one_as_root(script):
    arm = _case_arm(script, "install")
    assert arm.count("probe_token") == 2          # stored token, and a pasted one
    stored = arm[arm.index('if [ -s "$CRED" ]'):arm.index("else")]
    assert """TOKEN=$(tr -d '\\r\\n' <"$CRED")""" in stored
    assert stored.index("TOKEN=$(tr") < stored.index("probe_token")
    assert "store_token" not in stored            # it is already stored
    assert "echo" not in stored.split("probe_token")[0].split("TOKEN=$(tr")[1]


@pytest.mark.parametrize("label", ["install", "--update"])
def test_the_path_units_are_enabled_and_started_with_two_commands_not_enable_now(script, label):
    arm = _case_arm(script, label)
    code = "\n".join(l for l in arm.splitlines() if not l.lstrip().startswith("#"))
    assert "enable --now" not in code
    for path in ("smylte-panel-poweroff.path", "smylte-panel-update.path"):
        assert arm.count(f"systemctl enable {path}") == 1
        assert arm.count(f"systemctl start {path}") == 1
        assert arm.index(f"systemctl enable {path}") < arm.index(f"systemctl start {path}")


def test_install_files_does_the_group_the_rule_the_units_logind_then_the_unit(script):
    body = _function(script, "install_files")
    steps = ['bash -n "$UPDATER_SRC" || die',
             'getent group "$KEY_GROUP" >/dev/null || groupadd --system "$KEY_GROUP"',
             'put 0644 "$RULES_SRC" "$RULES"',
             "udevadm control --reload",
             "udevadm trigger --action=change --subsystem-match=input",
             "udevadm settle",
             'put 0644 "$PATH_SRC" "$PATH_UNIT"',
             'put 0644 "$OFF_SRC" "$OFF_UNIT"',
             'put 0644 "$UPD_PATH_SRC" "$UPD_PATH_UNIT"',
             'put 0644 "$UPD_SRC" "$UPD_UNIT"',
             'install -d -m 0755 -o root -g root "${LOGIND%/*}"',
             'put 0644 "$LOGIND_SRC" "$LOGIND"',
             'install -d -m 0755 -o root -g root "$LIB"',
             'for f in $FILES; do put 0644 "$SRC/$f" "$LIB/$f"; done',
             'put 0644 "$UPDATER_SRC" "$UPDATER"',
             'put 0644 "$UNIT_SRC" "$UNIT"',
             'systemd-analyze verify "$UNIT" "$PATH_UNIT" "$OFF_UNIT" "$UPD_PATH_UNIT" "$UPD_UNIT"',
             "systemctl daemon-reload"]
    at = [body.index(step) for step in steps]
    assert at == sorted(at), dict(zip(steps, at))
    # Every file goes through put: the only install calls left make directories.
    code = body.replace(_function(script, "put"), "")
    for line in code.splitlines():
        if re.match(r"\s*install ", line):
            assert line.strip().startswith("install -d "), line


def test_key_off_removes_the_logind_drop_in_instead_of_installing_it(script):
    body = _function(script, "install_files")
    assert re.search(
        r'if \[ "\$\(setting SMYLTE_PANEL_KEY auto\)" != off \]; then\n'
        r'\s*install -d -m 0755 -o root -g root "\$\{LOGIND%/\*\}"\n'
        r'\s*put 0644 "\$LOGIND_SRC" "\$LOGIND"\n'
        r'\s*else\n\s*rm -f "\$LOGIND"\n\s*fi', body), body


def test_apply_logind_reports_a_failed_reload_and_carries_on(tmp_path, script):
    program = (_function(script, "apply_logind") + "apply_logind\necho after\n")
    result, calls = _run_fake(tmp_path, program, state="active",
                              fakes={"systemctl": '#!/bin/bash\necho "systemctl $*" >> "$LOG"\nexit 1\n'})
    assert result.returncode == 0, result.stderr
    assert calls == ["systemctl reload systemd-logind"]
    assert "✗ logind did not reload: a press may still power the box off until the next boot" in result.stdout
    assert result.stdout.rstrip().endswith("after")


# ── the key node ─────────────────────────────────────────────────────────────

def _key_node(tmp_path, script, names, group):
    sys_dir, dev_dir = tmp_path / "sys", tmp_path / "dev"
    for n, name in names.items():
        (sys_dir / n / "device").mkdir(parents=True)
        (sys_dir / n / "device" / "name").write_text(name + "\n")
    dev_dir.mkdir()
    for n in names:
        (dev_dir / n).write_text("")
    # The function reads /sys/class/input and /dev/input; point both at tmp.
    body = _function(script, "check_key_node") \
        .replace("/sys/class/input", str(sys_dir)).replace("/dev/input", str(dev_dir))
    result, _ = _run_fake(tmp_path, f"KEY_GROUP={group}\n" + body + "check_key_node\necho rc=$?\n")
    assert result.returncode == 0, result.stderr
    return result.stdout


def _my_group(tmp_path):
    probe = tmp_path / "probe"
    probe.write_text("")
    return subprocess.run(["stat", "-c", "%G", str(probe)], capture_output=True, text=True).stdout.strip()


def test_the_key_node_check_passes_when_the_node_is_in_the_key_group(tmp_path, script):
    group = _my_group(tmp_path)
    out = _key_node(tmp_path, script, {"event0": "Keyboard", "event3": "pwr_button"}, group)
    assert f"✓ " in out and f"/event3 (pwr_button) is group {group}" in out
    assert "!" not in out and out.rstrip().endswith("rc=0")


def test_the_key_node_check_warns_but_does_not_fail_on_the_wrong_group(tmp_path, script):
    out = _key_node(tmp_path, script, {"event3": "pwr_button"}, "no-such-group")
    assert "! " in out and "not no-such-group — the udev rule did not apply" in out
    assert out.rstrip().endswith("rc=0")


def test_the_key_node_check_warns_when_there_is_no_power_key(tmp_path, script):
    out = _key_node(tmp_path, script, {"event0": "Keyboard"}, KEY_GROUP)
    assert "! no pwr_button input device (gpio_keys not loaded?)" in out
    assert out.rstrip().endswith("rc=0")
    assert "pwr_button" in _function(script, "check_key_node")
    assert P.KEY_DEVICE_NAME == "pwr_button"


def test_the_key_node_is_checked_after_install_not_in_preflight(script):
    assert "check_key_node" not in _function(script, "preflight")
    assert "check_key_node" not in _function(script, "check_settings")


# ── drift ────────────────────────────────────────────────────────────────────

def _drift(tmp_path, script, *, key="auto", tamper=(), remove=()):
    """Run drift() on a fake tree where every installed copy matches its source,
    after changing (`tamper`) or deleting (`remove`) some installed copies."""
    t = tmp_path / "d"
    (t / "src").mkdir(parents=True)
    (t / "lib").mkdir()
    for f in ("panel.py", "epd7in5_v2.py"):
        (t / "src" / f).write_text(f)
        (t / "lib" / f).write_text(f)
    installed = {"UNIT": "smylte-panel.service", "RULES": "70-smylte-panel-key.rules",
                 "PATH_UNIT": "smylte-panel-poweroff.path",
                 "OFF_UNIT": "smylte-panel-poweroff.service",
                 "LOGIND": "50-smylte-panel.conf",
                 "UPD_PATH_UNIT": "smylte-panel-update.path",
                 "UPD_UNIT": "smylte-panel-update.service",
                 "UPDATER": "update.sh"}
    for var, name in installed.items():
        (t / f"{var}.src").write_text(name)
        (t / name).write_text("changed" if var in tamper else name)
        if var in remove:
            (t / name).unlink()
    env = t / "panel.env"
    env.write_text(f"SMYLTE_PANEL_KEY={key}\n")
    src_vars = {"UNIT": "UNIT_SRC", "RULES": "RULES_SRC", "PATH_UNIT": "PATH_SRC",
                "OFF_UNIT": "OFF_SRC", "LOGIND": "LOGIND_SRC", "UPD_PATH_UNIT": "UPD_PATH_SRC",
                "UPD_UNIT": "UPD_SRC", "UPDATER": "UPDATER_SRC"}
    sources = "".join(f"{src_vars[v]}={t}/{v}.src\n" for v in installed)
    places = "".join(f"{v}={t}/{n}\n" for v, n in installed.items())
    program = (f'FILES="panel.py epd7in5_v2.py"\nSRC={t}/src\nLIB={t}/lib\n'
               f"UNIT_NAME=smylte-panel.service\nPANEL_ENV={env}\n" + sources + places
               + _function(script, "setting") + _function(script, "drift") + "drift\n")
    result, _ = _run_fake(tmp_path, program)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize("kwargs, expected", [
    ({}, ""),
    ({"tamper": ["RULES"]}, "70-smylte-panel-key.rules"),
    ({"tamper": ["PATH_UNIT"]}, "smylte-panel-poweroff.path"),
    ({"tamper": ["OFF_UNIT"]}, "smylte-panel-poweroff.service"),
    ({"tamper": ["UNIT"]}, "smylte-panel.service"),
    ({"tamper": ["LOGIND"]}, "50-smylte-panel.conf"),
    ({"remove": ["LOGIND"]}, "50-smylte-panel.conf"),
    ({"remove": ["RULES"]}, "70-smylte-panel-key.rules"),
    ({"key": "off", "remove": ["LOGIND"]}, ""),
    ({"key": "off", "tamper": ["LOGIND"]}, "50-smylte-panel.conf(present, but KEY is off)"),
    ({"tamper": ["UPD_PATH_UNIT"]}, "smylte-panel-update.path"),
    ({"tamper": ["UPD_UNIT"]}, "smylte-panel-update.service"),
    ({"tamper": ["UPDATER"]}, "update.sh"),
    ({"remove": ["UPDATER"]}, "update.sh"),
], ids=["clean", "rules", "path", "off-unit", "unit", "logind", "logind-missing", "rules-missing",
        "key-off-absent", "key-off-present", "update-path", "update-unit", "updater",
        "updater-missing"])
def test_drift_covers_the_rule_the_power_off_and_update_units_the_updater_and_logind(
        tmp_path, script, kwargs, expected):
    out = _drift(tmp_path, script, **kwargs)
    if expected:
        assert expected in out, out
    else:
        assert out == ""


# ── --keytest and --reset-refresh ────────────────────────────────────────────

_CAT = "# /etc/systemd/logind.conf\n[Login]\n#HandlePowerKey=poweroff\n{lines}"


@pytest.mark.parametrize("env, cat_lines", [
    ({"RUNNING": "poweroff"}, ""),
    ({"RUNNING": "poweroff"}, "HandlePowerKey=ignore\n"),     # the files say ignore, logind has not reloaded
    ({"RUNNING": "ignore-not"}, "HandlePowerKey=ignore\n"),
    ({"RUNNING": ""}, "HandlePowerKey=ignore\n"),              # an empty answer
    ({"RUNNING_FAILS": "1"}, "HandlePowerKey=ignore\n"),       # busctl failed
], ids=["poweroff", "files-ignore-running-poweroff", "not-exactly-ignore", "empty", "busctl-fails"])
def test_keytest_refuses_unless_the_running_logind_says_ignore(tmp_path, script, env, cat_lines):
    program = _arm_program(tmp_path, script, "--keytest",
                           ["logind_running", "stop_service", "start_service", "restart_if_was_active"])
    result, calls = _run_fake(tmp_path, program, state="active",
                              cat=_CAT.format(lines=cat_lines), env=env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "✗ logind (running) would power the box off on the first press" in result.stdout
    assert "systemctl reload systemd-logind" in result.stdout
    # Refused before anything is stopped or run.
    assert calls == [], calls


def test_keytest_goes_ahead_when_the_running_logind_says_ignore_whatever_the_files_say(tmp_path, script):
    result, calls = _run_fake(tmp_path, _keytest_arm(tmp_path, script), state="inactive",
                              cat=_CAT.format(lines="HandlePowerKey=poweroff\n"),
                              env={"RUNNING": "ignore", "RUNNING_LONG": "poweroff"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert _index(calls, "systemd-run") >= 0


def _keytest_arm(tmp_path, script):
    return _arm_program(tmp_path, script, "--keytest",
                        ["logind_running"] + _ONEOFF_FUNCTIONS)


@pytest.mark.parametrize("state, restarts", [("active", True), ("inactive", False)])
def test_keytest_runs_a_key_only_one_off_with_the_service_stopped_around_it(
        tmp_path, script, state, restarts):
    result, calls = _run_fake(tmp_path, _keytest_arm(tmp_path, script), state=state)
    assert result.returncode == 0, result.stdout + result.stderr
    run = _index(calls, "systemd-run")
    line = calls[run]
    assert "--unit=smylte-panel-keytest" in line
    assert f"-p SupplementaryGroups={KEY_GROUP}" in line
    assert "-p DeviceAllow=char-input r" in line
    assert "-p DevicePolicy=closed" in line and "-p DynamicUser=yes" in line
    assert "gpio" not in line and "spi" not in line and "StateDirectory" not in line
    assert line.endswith("-I -B " + str(tmp_path / "lib" / "panel.py") + " --keytest")
    if restarts:
        stop = _index(calls, "systemctl stop")
        start = _index(calls, "systemctl start", run)
        assert stop < run < start
        assert calls[start - 1] == "systemctl reset-failed smylte-panel.service"
        assert _index(calls, "systemctl start") == start      # only once
    else:
        assert not [c for c in calls if c.startswith(("systemctl stop", "systemctl start"))]


def test_keytest_restarts_the_service_even_when_the_one_off_fails(tmp_path, script):
    result, calls = _run_fake(tmp_path, _keytest_arm(tmp_path, script), state="active",
                              env={"FAKE_RUN_RC": "7"})
    assert result.returncode == 7
    assert _index(calls, "systemctl start", _index(calls, "systemd-run")) > 0


def test_keytest_one_off_has_no_gpio_spi_or_state_in_the_script_text(script):
    arm = _case_arm(script, "--keytest")
    run = arm[arm.index("systemd-run"):arm.index("--keytest || rc=$?")]
    assert f'"SupplementaryGroups=$KEY_GROUP"' in run and '"DeviceAllow=char-input r"' in run
    assert "gpio" not in run and "spi" not in run and "StateDirectory" not in run
    assert "ProtectSystem=strict" in run and "NoNewPrivileges=yes" in run
    assert '"EnvironmentFile=-$PANEL_ENV"' in run
    assert arm.index("logind_running HandlePowerKey") < arm.index("stop_service") < arm.index("systemd-run")
    assert "logind_setting" not in arm       # the files are not what acts on a press


def _status_lines(tmp_path, script, *, cat, env):
    """The --status arm's lines for the two HandlePowerKey settings, run."""
    arm = _case_arm(script, "--status")
    loop = arm[arm.index("for k in HandlePowerKey"):]
    loop = loop[:loop.index("\n    done") + len("\n    done")]
    program = (_function(script, "logind_setting") + _function(script, "logind_running") + loop + "\n")
    result, _ = _run_fake(tmp_path, program, cat=cat, env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


@pytest.mark.parametrize("cat_lines, env, expected", [
    ("HandlePowerKey=ignore\n", {"RUNNING": "ignore"},
     ["  logind HandlePowerKey=ignore (file) / ignore (running)",
      "  logind HandlePowerKeyLongPress=(unset) (file) / ignore (running)"]),
    # The drop-in is on disk but logind has not reloaded: both are shown.
    ("HandlePowerKey=ignore\n", {"RUNNING": "poweroff", "RUNNING_LONG": "ignore"},
     ["  logind HandlePowerKey=ignore (file) / poweroff (running)",
      "  logind HandlePowerKeyLongPress=(unset) (file) / ignore (running)"]),
    ("", {"RUNNING_FAILS": "1"},
     ["  logind HandlePowerKey=(unset) (file) / unreadable (running)",
      "  logind HandlePowerKeyLongPress=(unset) (file) / unreadable (running)"]),
], ids=["both-ignore", "file-ahead-of-running", "nothing-set-busctl-fails"])
def test_status_shows_loginds_file_and_running_values_and_unset_when_there_is_none(
        tmp_path, script, cat_lines, env, expected):
    assert _status_lines(tmp_path, script, cat=_CAT.format(lines=cat_lines), env=env) == expected


@pytest.mark.parametrize("state", ["active", "inactive"])
def test_reset_refresh_stops_runs_the_one_off_and_restarts_if_it_was_running(tmp_path, script, state):
    program = _arm_program(tmp_path, script, "--reset-refresh", _ONEOFF_FUNCTIONS)
    result, calls = _run_fake(tmp_path, program, state=state)
    assert result.returncode == 0, result.stdout + result.stderr
    run = _index(calls, "systemd-run")
    assert "--unit=smylte-panel-reset-refresh" in calls[run]
    assert calls[run].endswith("--reset-refresh")
    for prop in ("-p DynamicUser=yes", "-p StateDirectory=smylte-panel",
                 "-p SupplementaryGroups=gpio spi"):      # the same sandbox as --selftest
        assert prop in calls[run]
    if state == "active":
        assert _index(calls, "systemctl stop") < run < _index(calls, "systemctl start", run)
    else:
        assert not [c for c in calls if c.startswith(("systemctl stop", "systemctl start"))]


def test_a_signal_during_a_one_off_still_restarts_the_service(tmp_path, script):
    """A TERM that lands while the one-off runs reaches the trap. The arm is
    cut short right after the one-off, so its own restart cannot be what starts
    the service."""
    program = _arm_program(tmp_path, script, "--reset-refresh", _ONEOFF_FUNCTIONS)
    program = program.replace('rc=0; run_oneoff --reset-refresh || rc=$?',
                              'rc=0; run_oneoff --reset-refresh || rc=$?\nexit "$rc"')
    result, calls = _run_fake(tmp_path, program, state="active", env={"FAKE_RUN_SIGNAL": "1"})
    assert "systemctl start smylte-panel.service" in calls, calls
    assert _index(calls, "systemctl stop") < _index(calls, "systemd-run") < \
        _index(calls, "systemctl start")


# systemd-run with --pipe and no tty does not pass a Ctrl-C on: it dies, and the
# transient unit it started carries on. The fake leaves a marker for that unit,
# which only `systemctl stop` on it removes, then interrupts the script.
_FAKE_RUN_INTERRUPTED = """#!/bin/bash
echo "systemd-run $*" >> "$LOG"
touch "$MARKER"
kill -INT "$PPID"
sleep 0.2
exit 130
"""


@pytest.mark.parametrize("label, extra, unit_name", [
    ("--reset-refresh", "", "smylte-panel-reset-refresh.service"),
    ("--selftest|--clear", "MODE=--selftest\n", "smylte-panel-selftest.service"),
    ("--selftest|--clear", "MODE=--clear\n", "smylte-panel-clear.service"),
    ("--keytest", "", "smylte-panel-keytest.service"),
], ids=["reset-refresh", "selftest", "clear", "keytest"])
def test_a_ctrl_c_during_a_one_off_stops_it_and_powers_off_before_the_service_starts(
        tmp_path, script, label, extra, unit_name):
    program = extra + _arm_program(tmp_path, script, label,
                                   ["logind_running"] + _ONEOFF_FUNCTIONS)
    result, calls = _run_fake(
        tmp_path, program, state="active",
        env={"MARKER": str(tmp_path / "transient")},
        fakes={"systemd-run": _FAKE_RUN_INTERRUPTED})
    assert result.returncode == 130, result.stdout + result.stderr
    stop = _index(calls, f"systemctl stop {unit_name}")
    power_off = _index(calls, "python3", stop)
    assert calls[power_off].endswith("--power-off")
    start = _index(calls, "systemctl start smylte-panel.service", power_off)
    assert stop < power_off < start
    assert "START-WHILE-ONEOFF-RUNNING" not in calls, calls


def test_a_finished_one_off_is_not_stopped_or_powered_off_again_by_the_exit_trap(tmp_path, script):
    """A failed --clear leaves the trap armed; it restarts the panel at exit
    and must not stop the unit that has already finished."""
    program = "MODE=--clear\n" + _arm_program(tmp_path, script, "--selftest|--clear", _ONEOFF_FUNCTIONS)
    result, calls = _run_fake(tmp_path, program, state="active", env={"FAKE_RUN_RC": "1"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert [c for c in calls if c.startswith("systemctl stop")] == ["systemctl stop smylte-panel.service"]
    assert len([c for c in calls if c.endswith("--power-off")]) == 1      # run_oneoff's own
    assert _index(calls, "systemctl start smylte-panel.service") > 0


def test_the_one_offs_get_a_stop_timeout_that_outlasts_a_refresh(tmp_path, script):
    """The default 90 s could kill a one-off that a stop caught mid-refresh."""
    unit_timeout = int(re.search(r"^TimeoutStopSec=(\d+)$",
                                 F.UNIT.read_text(encoding="utf-8"), re.M).group(1))
    program = _arm_program(tmp_path, script, "--reset-refresh", _ONEOFF_FUNCTIONS)
    _, calls = _run_fake(tmp_path, program, state="inactive")
    assert f"-p TimeoutStopSec={unit_timeout}" in calls[_index(calls, "systemd-run")]


@pytest.mark.parametrize("was_active, state, starts", [
    ("yes", "inactive", True),
    ("yes", "failed", True),
    ("yes", "active", False),
    ("no", "inactive", False),
])
def test_the_trap_restarts_only_a_panel_that_was_running_and_is_not(
        tmp_path, script, was_active, state, starts):
    program = ("UNIT_NAME=smylte-panel.service\nONEOFF=\n" f"WAS_ACTIVE={was_active}\n"
               + _function(script, "start_service") + _function(script, "restart_if_was_active")
               + "restart_if_was_active\n")
    _, calls = _run_fake(tmp_path, program, state=state)
    started = "systemctl start smylte-panel.service" in calls
    assert started is starts, calls
    if starts:
        assert "systemctl reset-failed smylte-panel.service" in calls


def test_every_arm_that_stops_the_service_sets_the_trap_right_before(script):
    """A Ctrl-C while `systemctl stop` waits for a refresh must still restart
    the panel, so the trap is armed before the stop, not after it returns."""
    trap = "arm_restart_trap"
    for label in ("install", "--selftest|--clear", "--keytest", "--reset-refresh"):
        arm = _case_arm(script, label)
        stop = arm.index("stop_service")
        assert arm.index(trap) < stop, label
        # Nothing runs between the trap and the stop but the stop's own line.
        assert arm[arm.index(trap):stop].strip().splitlines() == ["arm_restart_trap"], label
        assert "disarm_restart_trap" in arm, label
        assert arm.index("disarm_restart_trap") > arm.index(trap), label
    assert "stop_service" not in _case_arm(script, "--status")
    assert script.count("restart_if_was_active() {") == 1


def test_a_failed_self_test_clears_the_trap_and_leaves_the_service_not_started(script):
    arm = _case_arm(script, "install")
    failed = arm[arm.index("if ! run_oneoff --selftest"):]
    failed = failed[:failed.index("exit 1")]
    assert "disarm_restart_trap" in failed
    assert "installed but NOT started" in failed


def test_a_successful_clear_clears_the_trap_before_it_says_so(script):
    arm = _case_arm(script, "--selftest|--clear")
    ok = re.search(r'if \[ "\$rc" -eq 0 \]; then disarm_restart_trap; fi', arm)
    assert ok, arm
    assert ok.start() < arm.index('echo "  ✓ cleared to white"')
    # ... and the self-test restarts the service itself, then lets go of the trap.
    selftest = arm[arm.index("elif"):]
    assert selftest.index("start_service start") < selftest.index("disarm_restart_trap")


# ── uninstall ────────────────────────────────────────────────────────────────

def test_uninstall_takes_the_key_apart_in_order_and_drops_the_group_last(script):
    arm = _case_arm(script, "--uninstall")
    steps = ['systemctl disable --now "$UNIT_NAME"',
             "run_oneoff --clear",
             "systemctl disable --now smylte-panel-poweroff.path",
             'rm -f "$PATH_UNIT" "$OFF_UNIT"',
             "systemctl disable --now smylte-panel-update.path",
             'rm -f "$UPD_PATH_UNIT" "$UPD_UNIT"',
             'rm -rf "$UPDATE_RUN"',
             'rm -f "$LOGIND"',
             "apply_logind",
             'rm -f "$RULES"',
             "udevadm control --reload",
             "udevadm trigger --action=change --subsystem-match=input",
             "udevadm settle",
             'groupdel "$KEY_GROUP" 2>/dev/null || true',
             '"$PANEL_ENV"',
             "systemctl daemon-reload"]
    at = [arm.index(step) for step in steps]
    assert at == sorted(at), dict(zip(steps, at))
    assert arm.count("apply_logind") == 1


# ── the token probe ──────────────────────────────────────────────────────────

def _probe_python(script: str) -> str:
    m = re.search(r"-c '\n(.*?)\n' 2>/dev/null", _function(script, "probe_token"), re.S)
    assert m
    return m.group(1)


def test_the_probe_asks_for_the_clients_real_view_target(script):
    code = _probe_python(script)
    ast.parse(code)
    assert '"/api/public/display/%s.bin?invert=1&w=800&h=480&mode=habits&tabs=1" % t' in code
    assert code.count("HEAD") == 1 and "sys.stdin.read()" in code
    assert "X-Display-Mode" in code and "X-Display-Error" in code
    # The token reaches Python on stdin and nowhere else.
    assert """printf '%s' "$TOKEN" | "$PY" -I -c""" in _function(script, "probe_token")


_FAKE_PY = """#!/bin/bash
cat > /dev/null
echo "$CANNED"
"""


@pytest.mark.parametrize("canned, expected", [
    ("200 habits - mono-hlsb-inverted", "✓ the server knows " + _TOK[:4] + "… and serves this panel's format, and Desk key is on"),
    ("422 - views-off -", "! Desk key is off for this display: turn it on in Settings → Displays "
                          "(the panel shows the display's own view until then)"),
    ("200 - - mono-hlsb-inverted", "! smylted is too old for the desk key: pull and restart it"),
    ("404 - - -", "! the server does not know " + _TOK[:4] + "… (404)"),
    ("down URLError", "! smylted is not answering on 127.0.0.1:8080"),
    ("500 - - -", "! unexpected answer from the server: 500 - - -"),
], ids=["on", "views-off", "too-old", "unknown-token", "down", "other"])
def test_the_probe_says_what_to_do_for_each_answer(tmp_path, script, canned, expected):
    program = (f"PY={tmp_path / 'bin' / 'fake-python'}\nTOKEN={_TOK}\n"
               + _function(script, "probe_token") + "probe_token\n")
    result, _ = _run_fake(tmp_path, program, env={"CANNED": canned},
                          fakes={"fake-python": _FAKE_PY})
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout, result.stdout
    assert _TOK not in result.stdout + result.stderr      # four characters only


# ── licence and layout ───────────────────────────────────────────────────────

def test_the_firmware_is_mit_licensed_and_each_client_file_says_so():
    licence = F.REPO / "firmware" / "LICENSE"
    assert licence.exists()
    assert "MIT" in licence.read_text(encoding="utf-8")
    for path in F.PI_DIR.glob("*.py"):
        first = "\n".join(path.read_text(encoding="utf-8").splitlines()[:3])
        assert "SPDX-License-Identifier: MIT" in first, path.name


def test_a_signal_ends_the_script_after_restarting_the_service(tmp_path, script):
    """A bash trap that returns lets the script run on; the INT/TERM traps
    restart the panel and then exit, so nothing after the signal runs."""
    program = ("UNIT_NAME=smylte-panel.service\nONEOFF=\nWAS_ACTIVE=yes\n"
               + _function(script, "start_service") + _function(script, "restart_if_was_active")
               + _function(script, "arm_restart_trap") + _function(script, "disarm_restart_trap")
               + "arm_restart_trap\nkill -TERM $$\necho after-the-signal\n")
    result, calls = _run_fake(tmp_path, program, state="inactive")
    assert "after-the-signal" not in result.stdout
    assert result.returncode == 143
    assert "systemctl start smylte-panel.service" in calls


def test_settings_accept_none_in_any_case(tmp_path, script):
    env = tmp_path / "panel.env"
    env.write_text("SMYLTE_PANEL_PWR_PIN=NONE\n")
    program = (f"PANEL_ENV={env}\n" + _function(script, "setting") + _function(script, "pwr_setting")
               + _function(script, "check_settings") + "check_settings\n")
    result, _ = _run_fake(tmp_path, program)
    assert "PWR pin: none" in result.stdout, result.stdout


# ── the key's update: units ──────────────────────────────────────────────────

UPDATER_SH = DEPLOY / "smylte-panel-update.sh"


@pytest.fixture(scope="module")
def updater() -> str:
    return UPDATER_SH.read_text(encoding="utf-8")


def _globals(text: str) -> dict[str, str]:
    """The script's top-level NAME=value lines, the first of each, with $NAME
    references to earlier ones expanded."""
    out: dict[str, str] = {}
    for m in re.finditer(r"^([A-Z_0-9]+)=(\S*)$", text, re.M):
        value = re.sub(r"\$(\w+)", lambda g: out.get(g.group(1), g.group(0)), m.group(2))
        out.setdefault(m.group(1), value)
    return out


def _update_units():
    return (Unit(_deploy_text("smylte-panel-update.path")),
            Unit(_deploy_text("smylte-panel-update.service")))


def test_the_update_path_watches_the_clients_request_file(unit):
    path, _ = _update_units()
    watched = "/run/" + unit.one("Service", "RuntimeDirectory") + "/" + P.UPDATE_NAME
    assert path.one("Path", "PathExists") == watched
    assert path.one("Path", "Unit") == "smylte-panel-update.service"
    assert path.one("Unit", "Description") == "Update Smylte when the desk panel asks"
    assert path.one("Install", "WantedBy") == "multi-user.target"
    assert list(path.sections) == ["Unit", "Path", "Install"]


def test_the_update_service_is_a_root_oneshot_started_only_by_the_path():
    _, svc = _update_units()
    assert svc.one("Unit", "Description") == "Update Smylte at the desk panel's request"
    assert svc.sections["Service"] == [
        ("Type", "oneshot"),
        ("UMask", "0022"),
        ("RuntimeDirectory", "smylte-panel-update"),
        ("RuntimeDirectoryMode", "0755"),
        ("RuntimeDirectoryPreserve", "yes"),
        ("TimeoutStartSec", "30min"),
        ("TimeoutStopSec", "180"),
        ("ExecStartPre", "-/usr/bin/mv -fT /run/smylte-panel/update /run/smylte-panel-update/request"),
        ("ExecStart", "/usr/bin/bash /usr/local/lib/smylte-panel/update.sh"),
    ]
    assert list(svc.sections) == ["Unit", "Service"]        # not enabled itself


def test_the_request_is_moved_into_the_updaters_directory_before_the_script_runs(updater):
    path, svc = _update_units()
    pre = svc.one("Service", "ExecStartPre").split()
    # rename(2): the entry is moved, never opened or followed, and a missing
    # one (the leading -) does not stop the script.
    assert pre[:2] == ["-/usr/bin/mv", "-fT"] and len(pre) == 4
    g = _globals(updater)
    out = "/run/" + svc.one("Service", "RuntimeDirectory")
    assert pre[2] == path.one("Path", "PathExists") == g["PANEL_REQ"]
    assert pre[3] == g["REQ"] == out + "/request"
    assert g["OUT"] == out
    assert svc.one("Service", "ExecStart") == "/usr/bin/bash " + g["LIB"] + "/update.sh"


def test_the_updater_the_units_the_setup_script_and_the_client_agree(updater, script, unit):
    g, s = _globals(updater), _globals(script)
    _, svc = _update_units()
    assert g["RESULT"] == P.UPDATE_RESULT == s["RESULT"]
    assert s["UPDATE_RUN"] == g["OUT"]
    assert P.UPDATE_UNIT == s["UPD_PATH_UNIT"]
    assert g["SETUP_LOCK"] == s["SETUP_LOCK"] == "/run/smylte-panel-setup.lock"
    assert g["LIB"] == s["LIB"] and s["UPDATER"] == s["LIB"] + "/update.sh"
    assert g["PANEL"] == s["UNIT_NAME"] and g["PANEL_UNIT"] == s["UNIT"]
    # The client gives up on a running update only after systemd would have
    # stopped it, the stop's own timeout included.
    assert svc.one("Service", "TimeoutStartSec") == "30min"
    assert P.UPDATE_MAX_S >= 30 * 60 + int(svc.one("Service", "TimeoutStopSec"))
    # The watch outlasts the new client's first paint and its watchdog.
    assert int(g["WATCH_S"]) == P.PAINT_MAX_S + int(unit.one("Service", "WatchdogSec"))
    assert int(g["BUDGET_S"]) + int(g["WATCH_S"]) < 30 * 60
    assert g["HEALTH_URL"] == "http://127.0.0.1:8080/healthz" and g["HEALTH_S"] == "300"


# ── the key's update: update.sh as text ──────────────────────────────────────

def test_the_updater_passes_bash_syntax_check():
    result = subprocess.run(["bash", "-n", str(UPDATER_SH)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_updater_calls_main_on_its_last_line_only(updater):
    """panel-setup.sh --update replaces the file while it runs, so bash must
    have read all of it before anything runs."""
    lines = updater.rstrip("\n").split("\n")
    assert lines[-1] == 'main "$@"; exit $?'
    assert updater.endswith('main "$@"; exit $?\n')
    code = [l for l in lines[:-1] if l.strip() and not l.lstrip().startswith("#")]
    assert not [l for l in code if re.match(r"main\b(?!\(\))", l)], "main is called before the end"
    assert "set -u" in code and not [l for l in code if l.startswith("set -e")]
    assert not re.search(r"^\s*(export )?PATH=", updater, re.M)   # systemd's, or the tests' fakes


def test_the_updater_never_touches_the_display_token(updater):
    code = "\n".join(l for l in updater.splitlines() if not l.lstrip().startswith("#"))
    for word in ("credstore", "smylte-panel-token", "TOKEN", "CREDENTIALS_DIRECTORY"):
        assert word not in code, word


# ── the key's update: update.sh, run ─────────────────────────────────────────

_UPD_FAKES = {
    # `show -P PROP UNIT` answers from $SYSD/UNIT.PROP, or from UNIT.PROP.seq
    # one line per call (the last repeats). Each look at the panel's
    # ActiveState also logs what the result file says at that moment.
    "systemctl": """#!/bin/bash
echo "systemctl $*" >> "$LOG"
case "$1" in
  show)
    f="$SYSD/$4.$3"
    if [ "$4.$3" = smylte-panel.service.ActiveState ]; then
      echo "result-now: $(cat "$RESULT_FILE" 2>/dev/null)" >> "$LOG"
    fi
    if [ -s "$f.seq" ]; then
      head -n 1 "$f.seq"
      [ "$(wc -l < "$f.seq")" -le 1 ] || sed -i 1d "$f.seq"
    elif [ -f "$f" ]; then
      cat "$f"
    fi ;;
  is-system-running) cat "$SYSD/system" ;;
esac
exit 0
""",
    "runuser": """#!/bin/bash
echo "runuser ${*:1:7}" >> "$LOG"
[ "$1" = -u ] && [ "$3" = -- ] || exit 99
shift 3
exec "$@"
""",
    "id": """#!/bin/bash
[ -z "${FAKE_ID_FAIL:-}" ] || exit 1
case "$1" in -u) echo "$FAKE_UID" ;; -g) echo "$FAKE_GID" ;; *) exit 1 ;; esac
""",
    "getent": """#!/bin/bash
case "$1" in
  passwd)
    if [ $# -ge 2 ]; then echo "$2:x:$FAKE_UID:$FAKE_GID::$FAKE_HOME:/bin/bash"
    else echo "owner:x:$FAKE_UID:$FAKE_GID::$FAKE_HOME:/bin/bash"; printf '%b' "${FAKE_PASSWD_MORE:-}"; fi ;;
  group) [ -n "$FAKE_GROUP" ] || exit 2; echo "$FAKE_GROUP" ;;
esac
""",
    # The ownership read answers from $STAT_TABLE (path<TAB>uid gid mode), or
    # as the owner's 755; any other stat is the real one.
    "stat": """#!/bin/bash
if [ "$1" = -c ] && [ "$2" = '%u %g %a' ]; then
  v=$(awk -F'\\t' -v p="${!#}" '$1 == p { print $2; exit }' "$STAT_TABLE")
  echo "${v:-$FAKE_UID $FAKE_GID 755}"
  exit 0
fi
exec @REALSTAT@ "$@"
""",
    "flock": """#!/bin/bash
echo "flock $*" >> "$LOG"
exit "${FAKE_FLOCK_RC:-0}"
""",
    "git": """#!/bin/bash
echo "git $*" >> "$LOG"
f="$SYSD/git.seq"
head -n 1 "$f"
[ "$(wc -l < "$f")" -le 1 ] || sed -i 1d "$f"
""",
}

# The checkout's own scripts. autopull is run as text, so $0 is what the
# updater names it.
_FAKE_AUTOPULL = """echo "autopull: repo=$SMYLTE_AUTOPULL_REPO report=$SMYLTE_AUTOPULL_REPORT no_restart=$SMYLTE_AUTOPULL_NO_RESTART name=$0" >> "$LOG"
echo "this run's log line" >> "$FAKE_HOME/smylte-autopull.log"
echo "autopull noise"
[ -z "$FAKE_OUTCOME" ] || echo "autopull: $FAKE_OUTCOME"
exit "${FAKE_AUTOPULL_RC:-0}"
"""

_FAKE_SETUP = """echo "panel-setup $* locked=${SMYLTE_PANEL_SETUP_LOCKED:-}" >> "$LOG"
echo "== preflight =="
if [ -n "${FAKE_SETUP_CHANGE:-}" ]; then
  echo "new panel" > "$FAKE_LIB/panel.py"
  echo "new driver" > "$FAKE_LIB/epd7in5_v2.py"
  printf '%s\\n' $FAKE_SETUP_INV > "$SYSD/smylte-panel.service.InvocationID.seq"
fi
echo "$FAKE_SETUP_LAST"
exit "${FAKE_SETUP_RC:-0}"
"""

_RID = "123.456"


def _updater_text(updater: str) -> str:
    """update.sh without its last line: the globals and the functions."""
    lines = updater.rstrip("\n").split("\n")
    assert lines[-1] == 'main "$@"; exit $?'
    return "\n".join(lines[:-1]) + "\n"


class _Updater:
    """A box for update.sh: its directories, the checkout, fake commands, and
    the globals pointed at them. `run` composes update.sh's functions with the
    overrides and whatever the test adds, then calls `call`."""

    def __init__(self, root, updater: str, *, real=()):
        if shutil.which("bash") is None:
            pytest.skip("no bash")
        self.updater = updater
        r = root.resolve()
        self.root = r
        self.out, self.panel_run, self.lib = r / "out", r / "panel-run", r / "lib"
        self.unit_file = r / "etc" / "smylte-panel.service"
        self.home = r / "home"
        self.repo = self.home / "smylte"
        self.bin, self.sysd = r / "bin", r / "sysd"
        self.log = r / "log"
        for d in (self.out, self.panel_run, self.lib, self.unit_file.parent, self.bin, self.sysd,
                  self.repo / ".git", self.repo / "deploy", self.repo / "backend"):
            d.mkdir(parents=True, exist_ok=True)
        (self.lib / "panel.py").write_text("old panel\n")
        (self.lib / "epd7in5_v2.py").write_text("old driver\n")
        self.unit_file.write_text("old unit\n")
        (self.repo / "deploy" / "smylte-autopull.sh").write_text(_FAKE_AUTOPULL)
        (self.repo / "deploy" / "panel-setup.sh").write_text(_FAKE_SETUP)
        (self.home / "smylte-autopull.log").write_text("an older run's line\n")
        (self.out / "request").write_text(_RID + "\n")
        self.stat_table = r / "stat-table"
        self.stat_table.write_text("")
        self.clock = r / "clock"
        self.clock.write_text("100")
        self.health = r / "health"
        self.health.write_text("ok\n")
        self.log.write_text("")
        real_stat = shutil.which("stat")
        for name, body in _UPD_FAKES.items():
            if name in real:
                continue
            fake = self.bin / name
            fake.write_text(body.replace("@REALSTAT@", real_stat or "/usr/bin/stat"))
            fake.chmod(0o755)
        self.set("smylte.service", LoadState="loaded", User="owner",
                 WorkingDirectory=f"{self.repo}/backend", ActiveState="active")
        self.set("smylte-panel.service", InvocationID="inv-1", ActiveState="active")
        (self.sysd / "system").write_text("running\n")
        self.seq("git", ["a" * 40])
        self.overrides = ""
        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}", "LOG": str(self.log),
            "SYSD": str(self.sysd), "RESULT_FILE": str(self.out / "result"),
            "FAKE_UID": "1000", "FAKE_GID": "1000", "FAKE_HOME": str(self.home),
            "FAKE_GROUP": "owner:x:1000:", "STAT_TABLE": str(self.stat_table),
            "CLOCK": str(self.clock), "HEALTH": str(self.health), "FAKE_LIB": str(self.lib),
            "FAKE_OUTCOME": "current", "FAKE_SETUP_LAST": "panel: up to date",
            "FAKE_SETUP_INV": "inv-2",
        }

    def set(self, unit, **props):
        for prop, value in props.items():
            (self.sysd / f"{unit}.{prop}").write_text(value + "\n")

    def seq(self, name, values):
        (self.sysd / f"{name}.seq").write_text("".join(v + "\n" for v in values))

    def stat(self, path, answer):
        with self.stat_table.open("a") as f:
            f.write(f"{path}\t{answer}\n")

    def program(self, call="main", extra=""):
        return (_updater_text(self.updater)
                + f"OUT={self.out}\nREQ=$OUT/request\nRESULT=$OUT/result\n"
                + f"PANEL_REQ={self.panel_run}/update\nLIB={self.lib}\n"
                + f"PANEL_UNIT={self.unit_file}\nSETUP_LOCK={self.root}/setup.lock\n"
                + "HEALTH_S=0\nWATCH_S=0\n"
                + 'pause() { echo "pause $1" >> "$LOG"; }\n'
                + 'now_bt() { local n; n=$(cat "$CLOCK"); echo $((n + 1)) >"$CLOCK"; printf "%d.000\\n" "$n"; }\n'
                + 'health_ok() { local v; echo health >> "$LOG"; v=$(head -n 1 "$HEALTH")\n'
                + '  [ "$(wc -l < "$HEALTH")" -le 1 ] || sed -i 1d "$HEALTH"; [ "$v" = ok ]; }\n'
                + self.overrides + extra + "\n" + call + "\n")

    def run(self, call="main", extra="", timeout=60, **env):
        return subprocess.run(["bash", "-c", self.program(call, extra)],
                              env={**self.env, **env}, capture_output=True, text=True,
                              timeout=timeout)

    def popen(self, call="main", extra="", **env):
        return subprocess.Popen(["bash", "-c", self.program(call, extra)],
                                env={**self.env, **env}, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    def calls(self):
        return self.log.read_text().splitlines()

    def result(self):
        """The result file as the client reads it."""
        return P.read_update_result(str(self.out / "result"))


@pytest.fixture
def upd(tmp_path, updater):
    return _Updater(tmp_path, updater)


def _says(result, line):
    assert f"update: {line}\n" in result.stdout, result.stdout + result.stderr


def _after(calls, prefix, start=0):
    return _index(calls, prefix, start)


def test_a_full_update_runs_every_step_in_order(upd):
    r = upd.run(FAKE_OUTCOME="updated", FAKE_SETUP_CHANGE="1", FAKE_SETUP_LAST="panel: updated")
    assert r.returncode == 0, r.stdout + r.stderr
    calls, repo = upd.calls(), upd.repo
    steps = [f"runuser -u owner -- cat -- {repo}/deploy/smylte-autopull.sh",
             f"runuser -u owner -- env SMYLTE_AUTOPULL_REPO={repo} SMYLTE_AUTOPULL_REPORT=1 "
             "SMYLTE_AUTOPULL_NO_RESTART=1",
             f"autopull: repo={repo} report=1 no_restart=1 name=smylte-autopull",
             f"git -C {repo} rev-parse HEAD",
             "systemctl restart smylte.service",
             "systemctl show -P ActiveState smylte.service",
             "health",
             "flock -w 600 8",
             f"git -C {repo} rev-parse HEAD",
             "systemctl show -P InvocationID smylte-panel.service",
             "panel-setup --update locked=1",
             "systemctl show -P ActiveState smylte-panel.service"]
    at, i = [], 0
    for step in steps:
        i = _after(calls, step, i)
        at.append(i)
        i += 1
    assert at == sorted(at)
    assert not [c for c in calls if c.startswith("systemctl stop")], calls
    assert upd.result() == P.UpdateResult(_RID, upd.result().at, "updated")
    assert (upd.lib / "panel.py").read_text() == "new panel\n"     # kept
    assert not list(upd.out.glob("work.*"))                        # WORK removed
    _says(r, "autopull log: this run's log line")
    assert "an older run's line" not in r.stdout                   # only what this run added
    assert "autopull noise" in r.stdout                            # streamed to the journal
    for line in r.stdout.splitlines():
        assert line.startswith(("update: ", "autopull", "== preflight ==", "panel: ")), line


def test_the_final_result_is_written_before_the_watch_looks_at_the_panel(upd):
    """The new code's first paint is the notice, so a client that cannot paint
    fails inside the watch."""
    upd.overrides = "WATCH_S=1\npause() { sleep 0.3; }\n"
    r = upd.run(FAKE_OUTCOME="updated", FAKE_SETUP_CHANGE="1", FAKE_SETUP_LAST="panel: updated")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = upd.calls()
    looks = [c for c in calls[_after(calls, "panel-setup"):] if c.startswith("result-now: ")]
    assert len(looks) >= 2, calls
    for look in looks:
        assert look.startswith(f"result-now: {_RID} ") and look.endswith(" updated"), looks
    assert (upd.lib / "panel.py").read_text() == "new panel\n"


@pytest.mark.parametrize("outcome, setup_last, final", [
    ("current", "panel: up to date", "up-to-date"),
    ("updated", "panel: up to date", "updated"),
])
def test_nothing_new_for_the_panel_ends_without_a_watch(upd, outcome, setup_last, final):
    r = upd.run(FAKE_OUTCOME=outcome, FAKE_SETUP_LAST=setup_last)
    assert r.returncode == 0, r.stdout + r.stderr
    assert upd.result().state == final and upd.result().rid == _RID
    calls = upd.calls()
    assert "systemctl show -P ActiveState smylte-panel.service" not in calls
    assert "systemctl restart smylte.service" in calls          # for current too
    assert not [c for c in calls if c.startswith(("systemctl stop", "systemctl start"))]


@pytest.mark.parametrize("seqs", [
    {"InvocationID": ["inv-2", "inv-2", "inv-3"]},
    {"ActiveState": ["active", "activating"]},
], ids=["restarted", "not-active"])
def test_a_panel_that_does_not_stay_up_is_rolled_back_and_the_result_rewritten(upd, seqs):
    if "InvocationID" in seqs:
        env = {"FAKE_SETUP_INV": " ".join(seqs["InvocationID"])}
    else:
        upd.seq("smylte-panel.service.ActiveState", seqs["ActiveState"])
        env = {}
    upd.overrides = "WATCH_S=60\n"
    r = upd.run(FAKE_OUTCOME="current", FAKE_SETUP_CHANGE="1", FAKE_SETUP_LAST="panel: updated", **env)
    assert r.returncode == 1, r.stdout + r.stderr
    _says(r, "the new panel code stopped within 60 s")
    calls = upd.calls()
    stop = _after(calls, "systemctl stop smylte-panel.service")
    assert _after(calls, "systemctl daemon-reload", stop) < \
        _after(calls, "systemctl reset-failed smylte-panel.service", stop) < \
        _after(calls, "systemctl start smylte-panel.service", stop)
    assert (upd.lib / "panel.py").read_text() == "old panel\n"
    assert (upd.lib / "epd7in5_v2.py").read_text() == "old driver\n"
    final = upd.result()
    assert final.state == "update-failed" and final.rid == _RID
    shown = [c for c in calls if c.startswith("result-now: ")][0].split()
    assert shown[3] == "updated"
    assert final.at > float(shown[2])        # after the new code's paints


@pytest.mark.parametrize("system, restarts", [("running", True), ("stopping", False)])
def test_a_sigterm_during_the_watch_puts_the_panel_back(upd, system, restarts):
    (upd.sysd / "system").write_text(system + "\n")
    upd.overrides = "WATCH_S=60\npause() { sleep 0.1; }\n"
    proc = upd.popen(FAKE_OUTCOME="current", FAKE_SETUP_CHANGE="1", FAKE_SETUP_LAST="panel: updated")
    try:
        deadline = time.monotonic() + 30
        while not [c for c in upd.calls() if c.startswith("result-now: ") and c.endswith("updated")]:
            assert proc.poll() is None, proc.communicate()
            assert time.monotonic() < deadline, upd.calls()
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode in (-signal.SIGTERM, 128 + signal.SIGTERM), out + err
    calls = upd.calls()
    stop = _after(calls, "systemctl stop smylte-panel.service")
    assert (upd.lib / "panel.py").read_text() == "old panel\n"
    assert upd.result().state == "update-failed"
    assert ("systemctl start smylte-panel.service" in calls[stop:]) is restarts
    assert not list(upd.out.glob("work.*"))


def test_a_refusal_fails_without_touching_the_panel(upd):
    r = upd.run(FAKE_SETUP_RC="3", FAKE_SETUP_LAST="panel: refused: no token stored — run panel-setup.sh")
    assert r.returncode == 1, r.stdout + r.stderr
    _says(r, "panel-setup.sh refused: panel: refused: no token stored — run panel-setup.sh")
    calls = upd.calls()
    assert not [c for c in calls if c.startswith(("systemctl stop", "systemctl start",
                                                   "systemctl reset-failed", "systemctl daemon-reload"))]
    assert upd.result().state == "update-failed" and upd.result().rid == _RID
    assert (upd.lib / "panel.py").read_text() == "old panel\n"


@pytest.mark.parametrize("rc, last, says", [
    ("1", "panel-setup: something broke", "panel-setup.sh --update failed (exit 1)"),
    ("0", "something else", "panel-setup.sh gave no outcome"),
], ids=["rc-1", "no-outcome"])
def test_a_failed_install_is_rolled_back(upd, rc, last, says):
    (upd.lib / "epd7in5_v2.py").unlink()          # absent before: removed again
    r = upd.run(FAKE_SETUP_RC=rc, FAKE_SETUP_CHANGE="1", FAKE_SETUP_LAST=last)
    assert r.returncode == 1, r.stdout + r.stderr
    _says(r, says)
    calls = upd.calls()
    stop = _after(calls, "systemctl stop smylte-panel.service")
    assert _after(calls, "systemctl daemon-reload", stop) < _after(calls, "systemctl start smylte-panel.service", stop)
    assert (upd.lib / "panel.py").read_text() == "old panel\n"
    assert not (upd.lib / "epd7in5_v2.py").exists()
    assert upd.unit_file.read_text() == "old unit\n"
    assert upd.result().state == "update-failed"
    assert "systemctl show -P ActiveState smylte-panel.service" not in calls    # no watch


def test_a_failed_install_that_changed_nothing_still_ends_the_wait(upd):
    # Nothing to put back, so restore_panel leaves the panel alone. The EXIT
    # trap must still turn `running` into update-failed, or the glass would
    # say Updating… until the panel gives up on its own (UPDATE_MAX_S).
    r = upd.run(FAKE_SETUP_RC="1", FAKE_SETUP_LAST="panel-setup: died early")
    assert r.returncode == 1, r.stdout + r.stderr
    _says(r, "panel-setup.sh --update failed (exit 1)")
    calls = upd.calls()
    assert not [c for c in calls if c.startswith(("systemctl stop", "systemctl start",
                                                   "systemctl reset-failed", "systemctl daemon-reload"))]
    assert upd.result().state == "update-failed" and upd.result().rid == _RID
    assert (upd.lib / "panel.py").read_text() == "old panel\n"


@pytest.mark.parametrize("outcome, rc, says", [
    ("blocked", "0", "a migration needs root: sudo {repo}/deploy/migrate.sh"),
    ("failed fetch", "1", "autopull failed: fetch (see above)"),
    ("failed npm", "1", "autopull failed: npm (see above)"),
    ("", "5", "autopull gave no outcome (exit 5)"),
    ("whatever", "0", "autopull gave no outcome (exit 0)"),
], ids=["blocked", "fetch", "npm", "none", "unknown"])
def test_an_autopull_that_does_not_go_on_fails_before_the_restart(upd, outcome, rc, says):
    r = upd.run(FAKE_OUTCOME=outcome, FAKE_AUTOPULL_RC=rc)
    assert r.returncode == 1, r.stdout + r.stderr
    _says(r, says.format(repo=upd.repo))
    _says(r, "autopull log: this run's log line")
    assert "systemctl restart smylte.service" not in upd.calls()
    assert upd.result().state == "update-failed"


def test_the_server_is_restarted_and_waited_for(upd):
    upd.overrides = "HEALTH_S=60\n"
    upd.seq("smylte.service.ActiveState", ["activating", "active"])
    upd.health.write_text("fail\nok\n")
    r = upd.run()
    assert r.returncode == 0, r.stdout + r.stderr
    calls = upd.calls()
    restart = _after(calls, "systemctl restart smylte.service")
    assert calls[restart:].count("health") == 2
    assert calls[restart:].count("pause 2") == 1
    _says(r, "smylted answers /healthz")


@pytest.mark.parametrize("state, health, says", [
    ("failed", "ok", "smylte.service is failed after the restart (journalctl -u smylte)"),
    ("inactive", "ok", "smylte.service is inactive after the restart (journalctl -u smylte)"),
    ("active", "fail", "smylted did not answer /healthz within 0 s"),
], ids=["unit-failed", "unit-inactive", "timeout"])
def test_a_server_that_does_not_come_back_fails_before_the_panel_step(upd, state, health, says):
    upd.set("smylte.service", ActiveState=state)
    upd.health.write_text(health + "\n")
    r = upd.run()
    assert r.returncode == 1, r.stdout + r.stderr
    _says(r, says)
    assert not [c for c in upd.calls() if c.startswith(("flock", "panel-setup"))]
    assert upd.result().state == "update-failed"


def test_the_health_timeout_is_health_s(updater):
    assert re.search(r'fail "smylted did not answer /healthz within \$HEALTH_S s"', updater)


def test_a_run_out_of_time_stops_before_the_panel_step(upd):
    upd.overrides = "BUDGET_S=-1\n"
    r = upd.run()
    assert r.returncode == 1
    _says(r, "ran out of time before the panel step")
    assert not [c for c in upd.calls() if c.startswith(("flock", "panel-setup"))]


def test_a_setup_run_by_hand_holding_the_lock_fails_the_update(upd):
    r = upd.run(FAKE_FLOCK_RC="1")
    assert r.returncode == 1
    _says(r, "panel-setup.sh is running by hand; press again when it is done")
    calls = upd.calls()
    assert "flock -w 600 8" in calls
    assert not [c for c in calls if c.startswith("panel-setup")]
    assert (upd.root / "setup.lock").exists()
    assert upd.result().state == "update-failed"


def test_a_checkout_that_moved_after_the_pull_fails_the_update(upd):
    upd.seq("git", ["a" * 40, "b" * 40])
    r = upd.run()
    assert r.returncode == 1
    _says(r, "the checkout moved during the update; press again")
    assert not [c for c in upd.calls() if c.startswith("panel-setup")]


@pytest.mark.parametrize("extra", [
    "",
    'restart_server() { echo "$NO_SUCH_VARIABLE"; }\n',      # a set -u trip
], ids=["fail", "unbound-variable"])
def test_the_exit_trap_writes_the_failure_and_removes_the_work_directory(upd, extra):
    if not extra:
        upd.set("smylte.service", LoadState="not-found")
    r = upd.run(extra=extra)
    assert r.returncode != 0
    assert upd.result() == P.UpdateResult(_RID, upd.result().at, "update-failed")
    assert upd.result().at > 100          # rewritten after `running` (the clock's first value)
    assert not list(upd.out.glob("work.*"))
    assert not (upd.out / "request").exists()


def test_the_result_is_running_while_the_update_runs(upd):
    """And the client reads it."""
    r = upd.run(extra='restart_server() { cat "$RESULT"; exit 0; }\n')
    assert f"{_RID} 100.000 running\n" in r.stdout
    assert P.UPDATE_RESULT_RE.fullmatch(f"{_RID} 100.000 running\n")


# ── the request ──────────────────────────────────────────────────────────────

def _request(upd, kind):
    req = upd.out / "request"
    req.unlink()
    if kind == "valid":
        req.write_text(_RID + "\n")
    elif kind == "no-newline":
        req.write_text(_RID)
    elif kind == "symlink":
        target = upd.root / "target"
        target.write_text("999.000\n")
        req.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(req)
    elif kind == "directory":
        req.mkdir()
        (req / "x").write_text("999.000\n")
    elif kind == "oversized":
        req.write_text("1" * 10 + ".000" + "0" * 4000 + "\n")
    elif kind == "empty":
        req.write_text("")
    elif kind == "text":
        req.write_text("hello\n")
    elif kind == "too-many-digits":
        req.write_text("12345678901.000\n")


@pytest.mark.parametrize("kind, rid, says", [
    ("valid", _RID, None),
    ("no-newline", _RID, None),
    ("absent", "0.000", "started without a request"),
    ("symlink", "0.000", "started without a request"),
    ("fifo", "0.000", "started without a request"),
    ("directory", "0.000", "started without a request"),
    ("oversized", "0.000", "the request was malformed"),
    ("empty", "0.000", "the request was malformed"),
    ("text", "0.000", "the request was malformed"),
    ("too-many-digits", "0.000", "the request was malformed"),
])
def test_the_request_is_read_only_from_a_regular_file_and_then_removed(upd, kind, rid, says):
    _request(upd, kind)
    (upd.panel_run / "update").mkdir()            # whatever the ExecStartPre left
    (upd.panel_run / "update" / "f").write_text("x")
    r = upd.run(call='take_request\necho "id=$id"', timeout=10)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == f"id={rid}"
    if says:
        _says(r, says)
    else:
        assert r.stdout.splitlines() == [f"id={rid}"]
    assert not os.path.lexists(upd.out / "request")
    assert not os.path.lexists(upd.panel_run / "update")
    if kind == "symlink":
        assert (upd.root / "target").read_text() == "999.000\n"   # the link went, not its target


# ── the checkout checks ──────────────────────────────────────────────────────

def _symlinked_checkout(upd):
    link = upd.home / "link"
    link.symlink_to(upd.repo)
    upd.set("smylte.service", WorkingDirectory=f"{link}/backend")
    return f"{link} is a symlink"


def _no_real_path(upd):
    wd = f"{upd.home}/../home/smylte"
    upd.set("smylte.service", WorkingDirectory=wd + "/backend")
    return f"{wd} is not its own real path"


_CHECKOUT_FAILS = {
    "not-installed": (lambda u: u.set("smylte.service", LoadState="not-found"),
                      "the key updates the checkout smylte.service runs, and it is not installed"),
    "no-user": (lambda u: u.set("smylte.service", User=""), "smylte.service has no User="),
    "root-user": (lambda u: u.set("smylte.service", User="root"),
                  "smylte.service runs as root; the key updates only a user's checkout"),
    "no-wd": (lambda u: u.set("smylte.service", WorkingDirectory=""),
              "smylte.service has no WorkingDirectory="),
    "wd-not-backend": (lambda u: u.set("smylte.service", WorkingDirectory=str(u.repo)),
                       "smylte.service's WorkingDirectory {repo} does not end in /backend"),
    "no-such-user": (lambda u: u.env.update(FAKE_ID_FAIL="1"),
                     "owner, smylte.service's User=, does not exist"),
    "uid-0": (lambda u: u.env.update(FAKE_UID="0"),
              "owner has uid '0'; the key updates only a user's checkout"),
    "relative": (lambda u: u.set("smylte.service", WorkingDirectory="home/smylte/backend"),
                 "home/smylte is not an absolute path"),
    "symlink": (_symlinked_checkout, None),
    "not-real-path": (_no_real_path, None),
    "no-git": (lambda u: shutil.rmtree(u.repo / ".git"), "{repo}/.git is not a directory"),
    "setup-symlink": (lambda u: ((u.repo / "deploy" / "panel-setup.sh").unlink(),
                                 (u.repo / "deploy" / "panel-setup.sh").symlink_to(u.root / "log")),
                      "{repo}/deploy/panel-setup.sh is a symlink"),
    "autopull-dir": (lambda u: ((u.repo / "deploy" / "smylte-autopull.sh").unlink(),
                                (u.repo / "deploy" / "smylte-autopull.sh").mkdir()),
                     "{repo}/deploy/smylte-autopull.sh is not a file"),
    "deploy-other-owner": (lambda u: u.stat(f"{u.repo}/deploy", "2000 1000 755"),
                           "{repo}/deploy is owned by uid 2000, not owner (1000)"),
    "repo-world-writable": (lambda u: u.stat(str(u.repo), "1000 1000 777"),
                            "{repo} is writable by everyone"),
    "file-group-other": (lambda u: u.stat(f"{u.repo}/deploy/panel-setup.sh", "1000 2000 664"),
                         "{repo}/deploy/panel-setup.sh is group-writable, and its group is not owner's own"),
    "group-has-others": (lambda u: (u.stat(f"{u.repo}/.git", "1000 1000 775"),
                                    u.env.update(FAKE_GROUP="owner:x:1000:owner,mallory")),
                         "{repo}/.git is group-writable, and its group has mallory in it too"),
    "group-is-primary-for-others": (lambda u: (u.stat(f"{u.repo}/.git", "1000 1000 775"),
                                               u.env.update(FAKE_PASSWD_MORE="eve:x:1001:1000::/home/eve:/bin/bash\\n")),
                                    "{repo}/.git is group-writable, and eve has it as their own group too"),
    "group-unreadable": (lambda u: (u.stat(f"{u.repo}/.git", "1000 1000 775"),
                                    u.env.update(FAKE_GROUP="")),
                         "{repo}/.git is group-writable, and its group cannot be read"),
    "ancestor-other-owner": (lambda u: u.stat(str(u.home), "2000 2000 755"),
                             "{home} is owned by uid 2000, not root or owner"),
    "ancestor-world-writable": (lambda u: u.stat(str(u.home), "0 0 1777"),
                                "{home} is writable by everyone"),
    "root-world-writable": (lambda u: u.stat("/", "0 0 777"), "/ is writable by everyone"),
    "ancestor-group-other": (lambda u: u.stat(str(u.home), "0 50 775"),
                             "{home} is group-writable, and its group is not owner's own"),
}


@pytest.mark.parametrize("name", list(_CHECKOUT_FAILS))
def test_every_checkout_check_fails_before_anything_runs_as_the_owner(upd, name):
    arrange, says = _CHECKOUT_FAILS[name]
    said = arrange(upd)
    r = upd.run()
    assert r.returncode == 1, r.stdout + r.stderr
    _says(r, (says or said).format(repo=upd.repo, home=upd.home))
    assert not [c for c in upd.calls() if c.startswith("runuser")], upd.calls()
    assert upd.result().state == "update-failed"


@pytest.mark.parametrize("members", ["", "owner"])
def test_group_write_is_allowed_for_the_owners_own_group_alone(upd, members):
    upd.stat(f"{upd.repo}/.git", "1000 1000 2775")
    upd.stat(str(upd.home), "1000 1000 775")
    upd.env["FAKE_GROUP"] = f"owner:x:1000:{members}"
    r = upd.run(extra='pull() { say "reached the pull"; exit 0; }\n')
    _says(r, f"checkout {upd.repo}, owner owner")
    _says(r, "reached the pull")


def _safe_for_the_walk(path, uid):
    """Why `path` would fail the real walk, or None."""
    st = os.stat(path)
    if st.st_uid not in (0, uid):
        return f"{path} is owned by uid {st.st_uid}"
    if st.st_mode & 0o022:
        return f"{path} is group- or world-writable"
    return None


@pytest.fixture
def walk(updater):
    """A checkout on the real filesystem, owned by a real non-root account, in a
    directory under backend/ whose ancestors are root's or ours and not writable
    by others (tmp is world-writable, so the walk would rightly refuse it). As
    root it is chowned to nobody; as a user it is simply ours."""
    import pwd
    import tempfile
    if os.geteuid() == 0:
        try:
            pw = pwd.getpwuid(65534)
        except KeyError:
            pytest.skip("running as root, and there is no uid 65534 to own the checkout")
    else:
        try:
            pw = pwd.getpwuid(os.getuid())
        except KeyError:
            pytest.skip("this uid has no passwd entry, so the real `id` cannot name it")
    try:
        base = pathlib.Path(tempfile.mkdtemp(prefix=".update-walk-", dir=F.REPO / "backend"))
    except PermissionError:
        pytest.skip("backend/ is not writable here, so there is nowhere safe to build the checkout")
    try:
        for p in [*reversed(base.parents), base]:
            why = _safe_for_the_walk(p, pw.pw_uid)
            if why:
                pytest.skip(f"the real ownership walk cannot pass here: {why}")
        box = _Updater(base / "box", updater, real=("id", "getent", "stat"))
        for p in [box.root, box.home]:
            p.chmod(0o755)
        for d in (box.repo, box.repo / ".git", box.repo / "deploy", box.repo / "backend"):
            d.chmod(0o755)
        for f in ("panel-setup.sh", "smylte-autopull.sh"):
            (box.repo / "deploy" / f).chmod(0o644)
        if os.geteuid() == 0:
            for p in [box.repo, *box.repo.rglob("*")]:
                os.chown(p, pw.pw_uid, pw.pw_gid, follow_symlinks=False)
        box.set("smylte.service", User=pw.pw_name)
        box.owner = pw.pw_name
        yield box
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_the_real_ownership_walk_passes_a_checkout_its_owner_holds(walk):
    r = walk.run(extra='pull() { say "reached the pull"; exit 0; }\n')
    _says(r, f"checkout {walk.repo}, owner {walk.owner}")
    _says(r, "reached the pull")


def test_the_real_ownership_walk_refuses_a_world_writable_ancestor(walk):
    walk.home.chmod(0o777)
    r = walk.run(extra='pull() { say "reached the pull"; exit 0; }\n')
    assert r.returncode == 1
    _says(r, f"{walk.home} is writable by everyone")
    assert "reached the pull" not in r.stdout


# ── the stubbed pieces, for real ─────────────────────────────────────────────

def test_now_bt_prints_the_boot_clock_with_three_decimals(updater, tmp_path):
    if shutil.which("python3") is None:
        pytest.skip("no python3")
    r = subprocess.run(["bash", "-c", _updater_text(updater) + "now_bt\n"],
                       capture_output=True, text=True)
    assert re.fullmatch(r"\d{1,10}\.\d{3}\n", r.stdout), r.stdout + r.stderr
    assert abs(float(r.stdout) - time.clock_gettime(time.CLOCK_BOOTTIME)) < 10


def test_the_health_probe_wants_a_2xx_from_the_url(updater):
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/healthz" else 404)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        def probe(url):
            return subprocess.run(["bash", "-c", _updater_text(updater) + f"HEALTH_URL={url}\nhealth_ok\n"],
                                  capture_output=True, text=True, timeout=20).returncode
        assert probe(f"http://127.0.0.1:{port}/healthz") == 0
        assert probe(f"http://127.0.0.1:{port}/nope") != 0
    finally:
        server.shutdown()
        server.server_close()
    assert probe(f"http://127.0.0.1:{port}/healthz") != 0       # nothing listening


# ── panel-setup.sh: what the key's update needs ──────────────────────────────

_FAKE_INSTALL = """#!/bin/bash
echo "install $*" >> "$LOG"
[ -z "${FAIL_INSTALL:-}" ] || exit 1
cp -- "${@: -2:1}" "${@: -1}"
"""


@pytest.mark.parametrize("fails", [False, True])
def test_put_writes_beside_the_old_copy_and_renames_it_over(tmp_path, script, fails):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.write_text("new\n")
    dst.write_text("old\n")
    program = _function(script, "put") + f'put 0644 {src} {dst} || echo "put failed"\n'
    result, calls = _run_fake(tmp_path, program, fakes={"install": _FAKE_INSTALL},
                              env={"FAIL_INSTALL": "1"} if fails else {})
    assert result.returncode == 0, result.stderr
    assert calls == [f"install -m 0644 -o root -g root -- {src} {dst}.new"]
    assert dst.read_text() == ("old\n" if fails else "new\n")
    assert ("put failed" in result.stdout) is fails
    if not fails:
        assert not (tmp_path / "dst.new").exists()


def test_an_updater_that_does_not_parse_is_never_installed(tmp_path, script):
    broken = tmp_path / "update.sh"
    broken.write_text("main() {\n")
    program = (f"UPDATER_SRC={broken}\n" 'die() { echo "DIE:$*"; exit 3; }\n'
               + _function(script, "install_files") + "install_files\n")
    result, calls = _run_fake(tmp_path, program)
    assert result.returncode == 3
    assert f"DIE:{broken} does not parse (above); nothing installed" in result.stdout
    assert calls == []


def _update_arm(tmp_path, script):
    stubs = "".join(
        f'{name}() {{ echo {name} >> "$LOG"; {body} }}\n' for name, body in [
            ("take_lock", ""),
            ("preflight", 'return "${PREFLIGHT_RC:-0}";'),
            ("server_checkout", 'printf "%s\\n" "${CHECKOUT-/srv/smylte}";'),
            ("drift", 'printf "%s\\n" "${DRIFT-}";'),
            ("write_settings", ""),
            ("install_files", 'return "${INSTALL_RC:-0}";'),
            ("check_key_node", ""),
            ("apply_logind", ""),
        ])
    return ("UNIT_NAME=smylte-panel.service\nREPO=/srv/smylte\n"
            f"CRED={tmp_path / 'cred'}\n"
            'die() { echo "DIE:$*"; exit 1; }\nsay() { echo "== $* =="; }\n'
            + stubs + _function(script, "start_service") + _case_arm(script, "--update") + "\n")


@pytest.mark.parametrize("setup, env, last, calls", [
    ("token", {"PREFLIGHT_RC": "1"}, "panel: refused: preflight failed (above)",
     ["take_lock", "preflight"]),
    ("none", {}, "panel: refused: no token stored — run panel-setup.sh", ["take_lock", "preflight"]),
    ("empty", {}, "panel: refused: no token stored — run panel-setup.sh", ["take_lock", "preflight"]),
    ("token", {"CHECKOUT": "/home/x/other"}, "panel: refused: smylte.service runs /home/x/other, not /srv/smylte",
     ["take_lock", "preflight", "server_checkout"]),
    ("token", {"CHECKOUT": ""}, "panel: refused: smylte.service runs , not /srv/smylte",
     ["take_lock", "preflight", "server_checkout"]),
], ids=["preflight", "no-token", "empty-token", "other-checkout", "no-server"])
def test_update_refuses_with_exit_3_before_changing_anything(tmp_path, script, setup, env, last, calls):
    if setup != "none":
        (tmp_path / "cred").write_text("" if setup == "empty" else "x" * 43 + "\n")
    result, log = _run_fake(tmp_path, _update_arm(tmp_path, script), env=env)
    assert result.returncode == 3, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == last
    assert log == calls


def test_update_with_no_drift_is_up_to_date_and_changes_nothing(tmp_path, script):
    (tmp_path / "cred").write_text("x" * 43 + "\n")
    result, log = _run_fake(tmp_path, _update_arm(tmp_path, script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == "panel: up to date"
    assert log == ["take_lock", "preflight", "server_checkout", "drift"]


def test_update_with_drift_installs_enables_and_restarts_in_order(tmp_path, script):
    (tmp_path / "cred").write_text("x" * 43 + "\n")
    result, log = _run_fake(tmp_path, _update_arm(tmp_path, script), env={"DRIFT": "panel.py"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == "panel: updated"
    assert log == ["take_lock", "preflight", "server_checkout", "drift", "write_settings",
                   "install_files", "check_key_node", "apply_logind",
                   "systemctl enable smylte-panel-poweroff.path",
                   "systemctl start smylte-panel-poweroff.path",
                   "systemctl enable smylte-panel-update.path",
                   "systemctl start smylte-panel-update.path",
                   "systemctl enable smylte-panel.service",
                   "systemctl reset-failed smylte-panel.service",
                   "systemctl restart smylte-panel.service"]


def test_a_failure_after_the_refusals_is_not_exit_3(tmp_path, script):
    (tmp_path / "cred").write_text("x" * 43 + "\n")
    result, log = _run_fake(tmp_path, _update_arm(tmp_path, script),
                            env={"DRIFT": "panel.py", "INSTALL_RC": "1"})
    assert result.returncode == 1
    assert "panel: updated" not in result.stdout


def test_update_reads_no_token_probes_nothing_and_sets_no_trap(script):
    arm = _case_arm(script, "--update")
    code = "\n".join(l for l in arm.splitlines() if not l.lstrip().startswith("#"))
    for word in ("read_token", "probe_token", "store_token", "TOKEN", "run_oneoff",
                 "trap", "stop_service", "read "):
        assert word not in code, word


@pytest.mark.parametrize("label", ["install", "--update", "--rotate-token", "--selftest|--clear",
                                   "--keytest", "--reset-refresh", "--uninstall"])
def test_every_arm_but_status_takes_the_lock_first(script, label):
    arm = _case_arm(script, label)
    first = [l.strip() for l in arm.splitlines() if l.strip() and not l.lstrip().startswith("#")][0]
    assert first == "take_lock", (label, first)


def test_status_takes_no_lock_and_every_arm_is_covered(script):
    assert "take_lock" not in _case_arm(script, "--status")
    labels = re.findall(r"^  ([\w|-]+)\)$", script[script.index('case "$MODE" in'):], re.M)
    assert set(labels) == {"install", "--update", "--rotate-token", "--selftest|--clear",
                           "--keytest", "--reset-refresh", "--status", "--uninstall"}


def _take_lock(tmp_path, script, **env):
    lock = tmp_path / "setup.lock"
    program = (f"SETUP_LOCK={lock}\n" 'die() { echo "DIE:$*"; exit 3; }\n' + _function(script, "take_lock")
               + 'take_lock\nif flock -n "$SETUP_LOCK" true; then echo free; else echo held; fi\n')
    return lock, program


def test_take_lock_holds_the_setup_lock_until_exit(tmp_path, script):
    lock, program = _take_lock(tmp_path, script)
    result, _ = _run_fake(tmp_path, program)
    assert (result.returncode, result.stdout) == (0, "held\n")


def test_take_lock_refuses_while_the_key_update_holds_it(tmp_path, script):
    import fcntl
    lock, program = _take_lock(tmp_path, script)
    with open(lock, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result, _ = _run_fake(tmp_path, program)
        assert result.returncode == 3
        assert result.stdout == ("DIE:an update from the key is running (journalctl -u smylte-panel-update -f); "
                                 "run this again when it is done\n")
        # The updater's own --update says it holds the lock already.
        result, _ = _run_fake(tmp_path, program, env={"SMYLTE_PANEL_SETUP_LOCKED": "1"})
        assert (result.returncode, result.stdout) == (0, "held\n")


_FAKE_SERVER_UNIT = """#!/bin/bash
echo "systemctl $*" >> "$LOG"
case "$*" in
  "show -P LoadState smylte.service") echo "$LOADSTATE" ;;
  "show -P WorkingDirectory smylte.service") echo "$WD" ;;
  "show -P User smylte.service") echo "${OWNER_NAME-}" ;;
  "is-enabled "*) echo enabled ;;
  "is-active "*) echo active ;;
esac
"""


@pytest.mark.parametrize("load, wd, expected", [
    ("loaded", "/home/pi/smylte/backend", "/home/pi/smylte\n"),
    ("not-found", "", ""),
    ("loaded", "/srv/elsewhere", "/srv/elsewhere\n"),
])
def test_server_checkout_is_smylte_services_checkout(tmp_path, script, load, wd, expected):
    result, _ = _run_fake(tmp_path, _function(script, "server_checkout") + "server_checkout\n",
                          fakes={"systemctl": _FAKE_SERVER_UNIT}, env={"LOADSTATE": load, "WD": wd})
    assert (result.returncode, result.stdout) == (0, expected)


@pytest.mark.parametrize("checkout, warning", [
    ("/srv/smylte", None),
    ("/home/pi/other", "  ! smylte.service runs /home/pi/other: the key updates that checkout, not this one"),
    ("", "  ! smylte.service is not installed: the key cannot update this box"),
])
def test_install_warns_when_the_key_would_update_another_checkout_or_none(tmp_path, script, checkout, warning):
    arm = _case_arm(script, "install")
    block = arm[arm.index("sc=$(server_checkout)"):]
    block = block[:block.index("\n    fi\n") + len("\n    fi\n")]
    program = ("REPO=/srv/smylte\n" f"server_checkout() {{ printf '%s\\n' '{checkout}'; }}\n" + block)
    result, _ = _run_fake(tmp_path, program)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (warning + "\n" if warning else "")


_FAKE_STATUS = {
    "systemctl": _FAKE_SERVER_UNIT,
    "journalctl": '#!/bin/bash\necho "journalctl $*" >> "$LOG"\n',
    "getent": '#!/bin/bash\necho "$2:x:1000:1000::$FAKE_HOME:/bin/bash"\n',
    "runuser": '#!/bin/bash\necho "runuser $*" >> "$LOG"\nshift 3\nexec "$@"\n',
}


@pytest.mark.parametrize("result_kind", ["regular", "symlink", "absent"])
def test_status_shows_the_update_path_the_result_the_journal_and_the_owners_log(
        tmp_path, script, result_kind):
    arm = _case_arm(script, "--status")
    block = arm[arm.index('say "update from the key"'):arm.index('say "service"')]
    home = tmp_path / "home"
    home.mkdir()
    (home / "smylte-autopull.log").write_text("".join(f"line {n}\n" for n in range(25)))
    res = tmp_path / "result"
    if result_kind == "regular":
        res.write_text(f"{_RID} 200.000 updated\n")
    elif result_kind == "symlink":
        (tmp_path / "elsewhere").write_text("secret\n")
        res.symlink_to(tmp_path / "elsewhere")
    program = f"RESULT={res}\n" 'say() { echo "== $* =="; }\n' + block
    result, calls = _run_fake(tmp_path, program, fakes=_FAKE_STATUS,
                              env={"OWNER_NAME": "owner", "FAKE_HOME": str(home)})
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "  smylte-panel-update.path: enabled=enabled active=active" in out
    assert (f"  last result: {_RID} 200.000 updated" in out) is (result_kind == "regular")
    assert "secret" not in out
    assert "journalctl --no-pager -u smylte-panel-update -n 15" in calls
    assert f"runuser -u owner -- tail -n 20 -- {home}/smylte-autopull.log" in calls
    assert "line 5\n" in out and "line 24\n" in out and "line 4\n" not in out


def test_status_reads_no_owners_log_without_a_server_unit(tmp_path, script):
    arm = _case_arm(script, "--status")
    block = arm[arm.index('say "update from the key"'):arm.index('say "service"')]
    program = f"RESULT={tmp_path / 'none'}\n" 'say() { echo "== $* =="; }\n' + block
    result, calls = _run_fake(tmp_path, program, fakes=_FAKE_STATUS,
                              env={"OWNER_NAME": "", "FAKE_HOME": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert not [c for c in calls if c.startswith("runuser")]


def test_uninstall_removes_the_update_units_and_their_run_directory(script):
    arm = _case_arm(script, "--uninstall")
    assert arm.index("systemctl disable --now smylte-panel-update.path") \
        < arm.index('rm -f "$UPD_PATH_UNIT" "$UPD_UNIT"') < arm.index('rm -rf "$UPDATE_RUN"') \
        < arm.index("systemctl daemon-reload")
    assert re.search(r"^UPDATE_RUN=/run/smylte-panel-update$", script, re.M)
    # update.sh lives in $LIB, which goes too.
    assert re.search(r'^\s*rm -rf .*"\$LIB"', arm, re.M)
