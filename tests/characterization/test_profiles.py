"""Characterize CSV profile loading and text formatting.

M4 cutover: these pins previously targeted the legacy ``qs_display``
``CSVLoader``/``TextFormatter`` (pandas); they now target the package
interfaces — ``ProfileStore`` for loading and
``ProfileRenderer._format_bindings`` for presentation cleanup. The
semantic targets are unchanged: 16 bindings for ``ad_infinitum.csv`` and
24 for ``alan_wake_II.csv``, with titles, row order, and duplicate
bindings preserved. The legacy pandas-specific pins (loader row tail,
DataFrame column names) were dropped when M1 replaced the parser.
"""

from pathlib import Path

import pytest

from quadstick_display.model import Binding, Profile, ProfileStore
from quadstick_display.view import (
    INPUT_CLEANUP,
    OUTPUT_CLEANUP,
    ProfileRenderer,
    _text_clean,
)

RESOURCES = Path(__file__).resolve().parents[2] / "resources"
CSVS_DIR = RESOURCES / "quadstick_csvs"

AD_INFINITUM = "ad_infinitum.csv"
ALAN_WAKE_II = "alan_wake_II.csv"

# Ordered (command, quadstick input) pairs produced by
# ProfileRenderer._format_bindings for each bundled profile. mp_* values
# pass through unchanged (lowercase); everything else is cleaned and
# uppercased.
AD_INFINITUM_BINDINGS = [
    ("W", "UP"),
    ("S", "DOWN"),
    ("A", "LEFT"),
    ("D", "RIGHT"),
    ("Q", "R.PUFF"),
    ("R", "mp_center_sip"),
    ("M.RIGHT.BTN", "mp_center_puff"),
    ("SPACE", "mp_center_sip_soft"),
    ("ENTER", "LIP"),
    ("LEFT.SHIFT", "mp_left_center_sip"),
    ("LEFT.CTRL", "mp_left_center_puff"),
    ("TAB", "mp_right_center_sip"),
    ("G", "mp_right_center_puff"),
    ("RIGHT.ARROW", "mp_right_sip"),
    ("LEFT.ARROW", "mp_left_sip"),
    ("ESCAPE", "R.SIP"),
]

ALAN_WAKE_II_BINDINGS = [
    ("W", "UP"),
    ("S", "DOWN"),
    ("A", "LEFT"),
    ("D", "RIGHT"),
    ("SPACE", "mp_center_sip"),
    ("M.RIGHT.BTN", "mp_center_puff"),
    ("R", "mp_left_sip"),
    ("LEFT.SHIFT", "mp_left_center_puff"),
    ("F", "LIP"),
    ("E", "mp_left_center_sip"),
    ("M.MIDDLE.BTN", "mp_left_puff"),
    ("Q", "mp_left_sip_soft"),
    ("M.WHL.UP", "R.SIP.S"),
    ("M.WHL.DOWN", "R.PUFF.S"),
    ("LEFT.CTRL", "mp_right_center_sip"),
    ("TAB", "mp_right_center_puff"),
    ("M", "R.PUFF"),
    ("ESCAPE", "R.SIP"),
    ("1", "mp_left_center_sip_soft"),
    ("2", "mp_left_center_puff_soft"),
    ("3", "mp_right_center_sip_soft"),
    ("4", "mp_right_center_puff_soft"),
    ("LEFT.ALT", "mp_right_sip"),
    ("Z", "mp_right_sip"),
]


@pytest.fixture(scope="module")
def renderer():
    return ProfileRenderer(RESOURCES)


def load(filename):
    return ProfileStore(CSVS_DIR).load(filename)


def formatted(renderer, filename, width=400):
    profile = load(filename)
    return renderer._format_bindings(profile.bindings, width)


class TestProfileNames:
    def test_ad_infinitum_name_comes_from_last_header(self):
        assert load(AD_INFINITUM).name == "Ad_Infinitum"

    def test_alan_wake_ii_name_comes_from_last_header(self):
        assert load(ALAN_WAKE_II).name == "Alan Wake II"


class TestBindingCounts:
    def test_ad_infinitum_has_16_bindings(self, renderer):
        _, bindings = formatted(renderer, AD_INFINITUM)
        assert len(bindings) == 16

    def test_alan_wake_ii_has_24_bindings(self, renderer):
        _, bindings = formatted(renderer, ALAN_WAKE_II)
        assert len(bindings) == 24


class TestOrderedRows:
    def test_ad_infinitum_rows_in_order(self, renderer):
        _, bindings = formatted(renderer, AD_INFINITUM)
        assert bindings == AD_INFINITUM_BINDINGS

    def test_alan_wake_ii_rows_in_order(self, renderer):
        _, bindings = formatted(renderer, ALAN_WAKE_II)
        assert bindings == ALAN_WAKE_II_BINDINGS


class TestDuplicateBindings:
    def test_duplicate_quadstick_inputs_are_preserved(self, renderer):
        # kb_left_alt and kb_z both bind to mp_right_sip; both rows
        # survive, in file order, at the end of the mapping section.
        _, bindings = formatted(renderer, ALAN_WAKE_II)
        assert bindings[-2:] == [
            ("LEFT.ALT", "mp_right_sip"),
            ("Z", "mp_right_sip"),
        ]
        assert [b for b in bindings if b[1] == "mp_right_sip"] == [
            ("LEFT.ALT", "mp_right_sip"),
            ("Z", "mp_right_sip"),
        ]


class TestColumnSplitWidth:
    @pytest.mark.parametrize(
        "filename,expected",
        [(AD_INFINITUM, 160.078125), (ALAN_WAKE_II, 161.8125)],
    )
    def test_max_width_drives_the_mouthpiece_column(self, renderer, filename, expected):
        # Font metrics come from the bundled Verdana Bold; allow a small
        # tolerance for FreeType variation across hosts.
        max_width, _ = formatted(renderer, filename, width=400)
        assert max_width == pytest.approx(expected, rel=0.01)
        assert max_width <= 400 // 2


class TestTextClean:
    @pytest.mark.parametrize(
        "raw,cleanup,expected",
        [
            ("kb_w", INPUT_CLEANUP, "W"),
            ("kb_left_control", INPUT_CLEANUP, "LEFT.CTRL"),
            ("mouse_right_button", INPUT_CLEANUP, "M.RIGHT.BTN"),
            ("mouse_wheel_up", INPUT_CLEANUP, "M.WHL.UP"),
            ("kb_1", INPUT_CLEANUP, "1"),
            # mp_* values pass through lowercase and unmodified.
            ("mp_center_sip", INPUT_CLEANUP, "mp_center_sip"),
            ("MP_TRIPLE_PUFF_SOFT", OUTPUT_CLEANUP, "mp_triple_puff_soft"),
            ("right_puff", OUTPUT_CLEANUP, "R.PUFF"),
            ("right_sip_soft", OUTPUT_CLEANUP, "R.SIP.S"),
            ("lip", OUTPUT_CLEANUP, "LIP"),
            ("", INPUT_CLEANUP, ""),
            (None, OUTPUT_CLEANUP, ""),
        ],
    )
    def test_cleanup_rules(self, raw, cleanup, expected):
        assert _text_clean(raw, cleanup) == expected


class TestFormatBindingsEdges:
    def test_format_stops_at_preferences(self, renderer):
        profile = Profile(
            name="test",
            bindings=(
                Binding("kb_a", "up"),
                Binding("Preferences", "x"),
                Binding("kb_b", "down"),
            ),
        )
        _, bindings = renderer._format_bindings(profile.bindings, 400)
        assert bindings == [("A", "UP")]

    def test_format_skips_rows_with_empty_cells(self, renderer):
        profile = Profile(
            name="test",
            bindings=(
                Binding("kb_a", "up"),
                Binding("", "down"),
                Binding("kb_b", ""),
                Binding("kb_c", "left"),
            ),
        )
        _, bindings = renderer._format_bindings(profile.bindings, 400)
        assert bindings == [("A", "UP"), ("C", "LEFT")]
