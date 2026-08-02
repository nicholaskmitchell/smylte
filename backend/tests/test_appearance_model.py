"""Appearance / dashboard validation — the SettingsPatch models on their own.

These deliberately bypass HTTP. The equivalent round-trip tests in test_api.py
need the scratch Radicale and skip without it, but this is the boundary that
stops a stored theme from carrying a `url()` beacon into the CSSOM on the next
page load — it should be checked on every run, Docker or no Docker.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from tasksd.app import Appearance, CustomTheme, DashboardModule, SettingsPatch


def theme(**over):
    base = {"id": "t1", "name": "Mine", "light": {}, "dark": {}}
    base.update(over)
    return CustomTheme(**base)


# ── the token allowlist ─────────────────────────────────────────────────────


def test_known_tokens_survive():
    t = theme(light={
        "--accent": "#ff0000",
        "--bg": "oklch(0.60 0.19 42)",
        "--fg-muted": "rgba(20, 19, 26, 0.60)",
        "--radius": "6px",
        "--fs-scale": "1.1",
        "--serif": '"Lora", Georgia, serif',
    })
    assert len(t.light) == 6


def test_unknown_tokens_are_filtered_not_rejected():
    # A theme exported by a newer client may name tokens this build has never
    # heard of; it should still import the parts that do apply.
    t = theme(light={"--accent": "#ff0000", "--not-a-token": "red", "color": "red"})
    assert t.light == {"--accent": "#ff0000"}


@pytest.mark.parametrize("value", [
    "url(https://evil.example/beacon.png)",
    "image(//evil)",
    "red; background: url(//evil)",
    "red}html{display:none",
    "@import 'evil.css'",
    "expression(alert(1))",
    "javascript:alert(1)",
    "red<script>",
    "red\\0000",
    "/* comment */ red",
])
def test_css_injection_is_stripped(value):
    assert theme(light={"--accent": value}).light == {}


def test_oversized_values_are_stripped():
    assert theme(light={"--accent": "#" + "f" * 200}).light == {}


def test_blank_and_non_string_values_are_stripped():
    assert theme(light={"--accent": "", "--bg": "   "}).light == {}


def test_both_modes_are_validated():
    t = theme(light={"--bg": "url(//evil)"}, dark={"--bg": "url(//evil)"})
    assert t.light == {} and t.dark == {}


def test_values_are_trimmed():
    assert theme(light={"--accent": "  #ff0000  "}).light == {"--accent": "#ff0000"}


# ── theme + appearance shape ────────────────────────────────────────────────


def test_theme_requires_an_id_and_a_name():
    for bad in ({"id": "", "name": "x"}, {"id": "x", "name": ""}):
        with pytest.raises(ValidationError):
            CustomTheme(**bad)


def test_theme_base_defaults_to_light():
    assert theme().base == "light"
    with pytest.raises(ValidationError):
        theme(base="sepia")


def test_appearance_defaults_to_the_shipped_design():
    # None active, no themes — the shipped design is the absence of a theme,
    # never a stored one, which is what makes reset lossless.
    a = Appearance()
    assert a.active is None and a.themes == []


def test_appearance_caps_stored_themes():
    with pytest.raises(ValidationError):
        Appearance(themes=[theme(id=f"t{i}", name=f"n{i}") for i in range(30)])


# ── dashboard geometry ──────────────────────────────────────────────────────


def _module(**over):
    base = {"id": "m1", "kind": "today", "x": 0, "y": 0, "w": 4, "h": 6}
    base.update(over)
    return base


def test_valid_module_passes():
    m = DashboardModule(**_module())
    assert (m.x, m.y, m.w, m.h) == (0, 0, 4, 6)


@pytest.mark.parametrize("over", [
    {"x": 12}, {"x": -1},            # off the 12-column grid
    {"w": 0}, {"w": 13},             # impossible width
    {"h": 0}, {"h": 41},             # impossible height
    {"y": -1}, {"y": 999},           # absurd row
    {"kind": "nonsense"},            # a module the client cannot render
    {"id": ""},                      # unusable as a React key
])
def test_bad_geometry_is_rejected(over):
    with pytest.raises(ValidationError):
        DashboardModule(**_module(**over))


def test_settings_patch_caps_dashboard_modules():
    many = [_module(id=f"m{i}", y=i, h=1) for i in range(50)]
    with pytest.raises(ValidationError):
        SettingsPatch(dashboard=many)


# ── patch semantics ─────────────────────────────────────────────────────────


def test_omitted_keys_stay_unset_so_a_partial_patch_clears_nothing():
    # The store merge skips None, so an absent key must serialize away entirely
    # or writing the theme would wipe the layout.
    patch = SettingsPatch(theme="dark").model_dump(exclude_unset=True)
    assert patch == {"theme": "dark"}
    assert "appearance" not in patch and "dashboard" not in patch


def test_empty_dashboard_is_a_real_value():
    # Clearing the arrangement back to the stock one is an explicit [], and it
    # has to survive exclude_unset to reach the store.
    assert SettingsPatch(dashboard=[]).model_dump(exclude_unset=True) == {"dashboard": []}


def test_appearance_survives_a_dump_round_trip():
    patch = SettingsPatch(appearance=Appearance(
        active="t1",
        themes=[theme(dark={"--accent": "oklch(0.72 0.16 45)"})],
    ))
    dumped = patch.model_dump(exclude_unset=True)
    assert dumped["appearance"]["active"] == "t1"
    assert dumped["appearance"]["themes"][0]["dark"] == {"--accent": "oklch(0.72 0.16 45)"}


# ── the two allowlists must agree ───────────────────────────────────────────


def test_backend_allowlist_matches_the_frontend():
    """The token allowlist exists twice — here and in appearance.ts.

    They have to, since each guards a different boundary (this one the stored
    blob, that one the live CSSOM). A token allowed on one side but not the
    other is a control that silently does nothing, or a value that survives the
    server and is then dropped by the client. Compare them rather than trust.
    """
    import re
    from pathlib import Path

    from tasksd.app import _APPEARANCE_TOKENS

    src = Path(__file__).resolve().parents[2] / "frontend" / "src" / "appearance.ts"
    if not src.exists():                     # backend-only checkout
        pytest.skip("frontend sources not present")
    block = re.search(
        r"export const TOKENS: Record<string, TokenSpec> = \{(.*?)\n\}",
        src.read_text(), re.S,
    )
    assert block, "could not find the TOKENS map in appearance.ts"
    frontend = set(re.findall(r"'(--[\w-]+)':", block.group(1)))
    assert frontend == _APPEARANCE_TOKENS
