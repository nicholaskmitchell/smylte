"""The app icon: one drawing, `brand/app-icon.svg`, and every platform's file
made from it by `backend/dev/build_app_icon.py`.

CI never writes with the generator. These run it in memory: the source and the
Field notes tokens must agree, the art must clear its floors, and every
committed output must be what the source makes now, so an edit to the drawing,
the tokens or the generator that nobody regenerated fails here rather than
shipping one icon on the web and another on the desktop.
"""
import re

import pytest

from dev import build_app_icon as B


@pytest.fixture(scope="module")
def built():
    return B.build()


def _source_with(tmp_path, old, new):
    (tmp_path / "brand").mkdir()
    text = open(f"{B.ROOT}/{B.SOURCE}", encoding="utf-8").read()
    assert old in text
    (tmp_path / B.SOURCE).write_text(text.replace(old, new, 1), encoding="utf-8")
    return str(tmp_path)


def test_the_tokens_come_from_both_field_notes_blocks():
    """Pinned on purpose: these are the colours AppIconTests and LinuxIconTests
    restate. If the design system moves one, this fails first, and the fix is
    to regenerate and update those two files too."""
    tokens = B.read_tokens()
    assert {k: tokens[B.LIGHT][k] for k in ("--bg", "--bg-elev", "--fg", "--accent", "--accent-fill")} == {
        "--bg": "#F3EDE1", "--bg-elev": "#FBF8F1", "--fg": "#2A2622",
        "--accent": "#A3432A", "--accent-fill": "#E27B5B"}
    assert {k: tokens[B.DARK][k] for k in ("--bg", "--fg", "--accent")} == {
        "--bg": "#272420", "--fg": "#EFE8DC", "--accent": "#F09C7E"}


def test_the_source_is_the_paper_variant_in_the_tokens_colours():
    plate, frame, tick = B.read_source()
    B.check_source_colours(B.read_tokens(), plate, frame, tick)
    assert (frame.full, frame.small, tick.full, tick.small) == (3.2, 4.8, 4.4, 6.4)


@pytest.mark.parametrize("extra", ['<circle cx="40" cy="40" r="3"/>', "<g/>",
                                   '<path class="swipe" d="M0 0L9 9"/>'])
def test_a_source_that_grew_a_shape_is_refused(tmp_path, extra):
    root = _source_with(tmp_path, "</svg>", extra + "</svg>")
    with pytest.raises(SystemExit, match="nothing else"):
        B.read_source(root)


def test_a_source_colour_off_the_tokens_is_refused(tmp_path):
    root = _source_with(tmp_path, 'stroke="#A3432A"', 'stroke="#C75A26"')
    plate, frame, tick = B.read_source(root)
    with pytest.raises(SystemExit, match="the tick is #C75A26"):
        B.check_source_colours(B.read_tokens(), plate, frame, tick)


def test_flatten_refuses_what_it_does_not_draw():
    for d in ("M0 0Q1 1 2 2", "m0 0c1 1 2 2 3 3", "M0 0A1 1 0 0 1 2 2"):
        with pytest.raises(SystemExit):
            B.flatten(d)


def test_the_art_clears_every_floor_and_keeps_clear_of_corners_and_masks(built):
    out, lines, bad = built
    assert bad == 0, "\n".join(lines)
    margin, reach = B.geometry(*B.read_source()[1:])
    assert margin >= B.RADIUS_PCT / 100 * B.UNIT
    assert reach <= B.SAFE_RADIUS_DP


def test_build_makes_every_platforms_file_and_nothing_else(built):
    out, _, _ = built
    expected = {B.FAVICON, B.TOUCH, B.COLORS, f"{B.DESKTOP}/app.ico",
                f"{B.DRAWABLE}/ic_launcher_foreground.xml", f"{B.DRAWABLE}/ic_launcher_monochrome.xml"}
    expected |= {f"{B.ICONS}/icon-{v}.ico" for v in ("ink", "accent", "mark")}
    for stem in ("paper", "ink", "accent", "mark"):
        expected.add(f"{B.LINUX}/{stem}.svg")
        expected |= {f"{B.LINUX}/{stem}-{size}.png" for size in B.LINUX_SIZES}
    assert set(out) == expected


def test_each_linux_raster_is_the_ico_frame_of_its_size(built):
    out, _, _ = built
    every = sorted(size for _, sizes in B.TIERS for size in sizes)
    for name, stem, *_ in B.VARIANTS:
        frames = B.ico_frames(out[f"{B.DESKTOP if name == 'app.ico' else B.ICONS}/{name}"])
        assert sorted(frames) == every
        for size in B.LINUX_SIZES:
            assert out[f"{B.LINUX}/{stem}-{size}.png"] == frames[size]


def test_every_committed_icon_is_what_the_source_makes_now(built):
    out, _, _ = built
    assert B.stale(B.ROOT, out) == [], "run: cd backend && python -m dev.build_app_icon"


def test_index_html_busts_every_icon_link_with_one_version():
    html = open(f"{B.ROOT}/frontend/index.html", encoding="utf-8").read()
    versions = re.findall(r'href="/(?:favicon\.svg|apple-touch-icon\.png)\?v=(\d+)"', html)
    assert len(versions) == 3 and len(set(versions)) == 1, versions
