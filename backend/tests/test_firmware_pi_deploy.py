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
import re
import shutil
import subprocess

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
    "--status", "--uninstall", "--no-selftest",
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
])
def test_the_script_installs_each_new_file_from_the_checkout_to_its_place(script, var, src, dst):
    assert (DEPLOY / src).exists()
    assert re.search(rf"^{var}={re.escape(dst)}$", script, re.M)
    src_var = {"PATH_UNIT": "PATH_SRC", "OFF_UNIT": "OFF_SRC",
               "RULES": "RULES_SRC", "LOGIND": "LOGIND_SRC"}[var]
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
            'die() { echo "DIE:$*"; exit 3; }\nsay() { echo "== $* =="; }\n')
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
    steps = ["preflight ||", "write_settings", "install_files", "check_key_node",
             "apply_logind",
             "systemctl enable smylte-panel-poweroff.path",
             "systemctl start smylte-panel-poweroff.path",
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


def test_the_path_unit_is_enabled_and_started_with_two_commands_not_enable_now(script):
    arm = _case_arm(script, "install")
    code = "\n".join(l for l in arm.splitlines() if not l.lstrip().startswith("#"))
    assert "enable --now" not in code
    assert arm.count("systemctl enable smylte-panel-poweroff.path") == 1
    assert arm.count("systemctl start smylte-panel-poweroff.path") == 1


def test_install_files_does_the_group_the_rule_the_units_logind_then_the_unit(script):
    body = _function(script, "install_files")
    steps = ['getent group "$KEY_GROUP" >/dev/null || groupadd --system "$KEY_GROUP"',
             'install -m 0644 -o root -g root "$RULES_SRC" "$RULES"',
             "udevadm control --reload",
             "udevadm trigger --action=change --subsystem-match=input",
             "udevadm settle",
             'install -m 0644 -o root -g root "$PATH_SRC" "$PATH_UNIT"',
             'install -m 0644 -o root -g root "$OFF_SRC" "$OFF_UNIT"',
             'install -D -m 0644 -o root -g root "$LOGIND_SRC" "$LOGIND"',
             'install -m 0644 -o root -g root "$UNIT_SRC" "$UNIT"',
             'systemd-analyze verify "$UNIT" "$PATH_UNIT" "$OFF_UNIT"',
             "systemctl daemon-reload"]
    at = [body.index(step) for step in steps]
    assert at == sorted(at), dict(zip(steps, at))


def test_key_off_removes_the_logind_drop_in_instead_of_installing_it(script):
    body = _function(script, "install_files")
    assert re.search(
        r'if \[ "\$\(setting SMYLTE_PANEL_KEY auto\)" != off \]; then\n'
        r'\s*install -D -m 0644 -o root -g root "\$LOGIND_SRC" "\$LOGIND"\n'
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
                 "LOGIND": "50-smylte-panel.conf"}
    for var, name in installed.items():
        (t / f"{var}.src").write_text(name)
        (t / name).write_text("changed" if var in tamper else name)
        if var in remove:
            (t / name).unlink()
    env = t / "panel.env"
    env.write_text(f"SMYLTE_PANEL_KEY={key}\n")
    src_vars = {"UNIT": "UNIT_SRC", "RULES": "RULES_SRC", "PATH_UNIT": "PATH_SRC",
                "OFF_UNIT": "OFF_SRC", "LOGIND": "LOGIND_SRC"}
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
], ids=["clean", "rules", "path", "off-unit", "unit", "logind", "logind-missing", "rules-missing",
        "key-off-absent", "key-off-present"])
def test_drift_covers_the_rule_both_power_off_units_and_the_logind_drop_in(
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
