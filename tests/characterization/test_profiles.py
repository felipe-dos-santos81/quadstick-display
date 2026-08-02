"""Characterize CSV profile loading and text formatting.

Pins the current behavior of ``CSVLoader`` and ``TextFormatter`` against the
two bundled sample profiles. The semantic compatibility targets are 16
bindings for ``ad_infinitum.csv`` and 24 for ``alan_wake_II.csv``, with row
order and duplicate bindings preserved.
"""
import pandas as pd
import pytest
from PIL import ImageFont

from qs_display import (
    CSVLoader,
    FONT_PATHS,
    INPUT_CLEANUP,
    OUTPUT_CLEANUP,
    TEXT_SIZE,
    TextFormatter,
)

AD_INFINITUM = 'ad_infinitum.csv'
ALAN_WAKE_II = 'alan_wake_II.csv'

# Ordered (command, quadstick input) pairs produced by
# TextFormatter.format_text for each bundled profile. mp_* values pass
# through unchanged (lowercase); everything else is cleaned and uppercased.
AD_INFINITUM_BINDINGS = [
    ('W', 'UP'),
    ('S', 'DOWN'),
    ('A', 'LEFT'),
    ('D', 'RIGHT'),
    ('Q', 'R.PUFF'),
    ('R', 'mp_center_sip'),
    ('M.RIGHT.BTN', 'mp_center_puff'),
    ('SPACE', 'mp_center_sip_soft'),
    ('ENTER', 'LIP'),
    ('LEFT.SHIFT', 'mp_left_center_sip'),
    ('LEFT.CTRL', 'mp_left_center_puff'),
    ('TAB', 'mp_right_center_sip'),
    ('G', 'mp_right_center_puff'),
    ('RIGHT.ARROW', 'mp_right_sip'),
    ('LEFT.ARROW', 'mp_left_sip'),
    ('ESCAPE', 'R.SIP'),
]

ALAN_WAKE_II_BINDINGS = [
    ('W', 'UP'),
    ('S', 'DOWN'),
    ('A', 'LEFT'),
    ('D', 'RIGHT'),
    ('SPACE', 'mp_center_sip'),
    ('M.RIGHT.BTN', 'mp_center_puff'),
    ('R', 'mp_left_sip'),
    ('LEFT.SHIFT', 'mp_left_center_puff'),
    ('F', 'LIP'),
    ('E', 'mp_left_center_sip'),
    ('M.MIDDLE.BTN', 'mp_left_puff'),
    ('Q', 'mp_left_sip_soft'),
    ('M.WHL.UP', 'R.SIP.S'),
    ('M.WHL.DOWN', 'R.PUFF.S'),
    ('LEFT.CTRL', 'mp_right_center_sip'),
    ('TAB', 'mp_right_center_puff'),
    ('M', 'R.PUFF'),
    ('ESCAPE', 'R.SIP'),
    ('1', 'mp_left_center_sip_soft'),
    ('2', 'mp_left_center_puff_soft'),
    ('3', 'mp_right_center_sip_soft'),
    ('4', 'mp_right_center_puff_soft'),
    ('LEFT.ALT', 'mp_right_sip'),
    ('Z', 'mp_right_sip'),
]


@pytest.fixture(scope='module')
def font_text():
    return ImageFont.truetype(FONT_PATHS['verdana_bold'], TEXT_SIZE)


def load(filename):
    return CSVLoader(filename).load_csv()


def formatted(filename, font_text, width=400):
    data, _ = load(filename)
    return TextFormatter.format_text(data, font_text, width)


class TestProfileNames:
    def test_ad_infinitum_name_comes_from_last_header(self):
        _, name = load(AD_INFINITUM)
        assert name == 'Ad_Infinitum'

    def test_alan_wake_ii_name_comes_from_last_header(self):
        _, name = load(ALAN_WAKE_II)
        assert name == 'Alan Wake II'


class TestBindingCounts:
    def test_ad_infinitum_has_16_bindings(self, font_text):
        _, bindings = formatted(AD_INFINITUM, font_text)
        assert len(bindings) == 16

    def test_alan_wake_ii_has_24_bindings(self, font_text):
        _, bindings = formatted(ALAN_WAKE_II, font_text)
        assert len(bindings) == 24


class TestOrderedRows:
    def test_ad_infinitum_rows_in_order(self, font_text):
        _, bindings = formatted(AD_INFINITUM, font_text)
        assert bindings == AD_INFINITUM_BINDINGS

    def test_alan_wake_ii_rows_in_order(self, font_text):
        _, bindings = formatted(ALAN_WAKE_II, font_text)
        assert bindings == ALAN_WAKE_II_BINDINGS


class TestDuplicateBindings:
    def test_duplicate_quadstick_inputs_are_preserved(self, font_text):
        # kb_left_alt and kb_z both bind to mp_right_sip; both rows survive,
        # in file order, at the end of the mapping section.
        _, bindings = formatted(ALAN_WAKE_II, font_text)
        assert bindings[-2:] == [
            ('LEFT.ALT', 'mp_right_sip'),
            ('Z', 'mp_right_sip'),
        ]
        assert [b for b in bindings if b[1] == 'mp_right_sip'] == [
            ('LEFT.ALT', 'mp_right_sip'),
            ('Z', 'mp_right_sip'),
        ]


class TestLoaderOutput:
    @pytest.mark.parametrize(
        'filename,row_count',
        [(AD_INFINITUM, 20), (ALAN_WAKE_II, 28)],
    )
    def test_loader_keeps_rows_past_preferences(self, filename, row_count):
        # The raw loader output includes the Preferences section tail; the
        # formatter is responsible for stopping at 'Preferences'.
        data, _ = load(filename)
        assert len(data) == row_count
        tail = list(data.itertuples(index=False, name=None))[-4:]
        assert tail[0][0] == 'Preferences'
        assert pd.isna(tail[0][1])
        assert tail[1] == ('Preference', 'Units')
        assert tail[2] == ('digital_out_1', 'on/off')
        assert tail[3] == ('digital_out_2', 'on/off')

    def test_loader_column_names(self):
        data, _ = load(AD_INFINITUM)
        assert list(data.columns) == ['Command', 'Quadstick']


class TestColumnSplitWidth:
    @pytest.mark.parametrize(
        'filename,expected',
        [(AD_INFINITUM, 160.078125), (ALAN_WAKE_II, 161.8125)],
    )
    def test_max_width_drives_the_mouthpiece_column(self, font_text, filename, expected):
        # Font metrics come from the bundled Verdana Bold; allow a small
        # tolerance for FreeType variation across hosts.
        max_width, _ = formatted(filename, font_text, width=400)
        assert max_width == pytest.approx(expected, rel=0.01)
        assert max_width <= 400 // 2


class TestTextClean:
    @pytest.mark.parametrize(
        'raw,cleanup,expected',
        [
            ('kb_w', INPUT_CLEANUP, 'W'),
            ('kb_left_control', INPUT_CLEANUP, 'LEFT.CTRL'),
            ('mouse_right_button', INPUT_CLEANUP, 'M.RIGHT.BTN'),
            ('mouse_wheel_up', INPUT_CLEANUP, 'M.WHL.UP'),
            ('kb_1', INPUT_CLEANUP, '1'),
            # mp_* values pass through lowercase and unmodified.
            ('mp_center_sip', INPUT_CLEANUP, 'mp_center_sip'),
            ('MP_TRIPLE_PUFF_SOFT', OUTPUT_CLEANUP, 'mp_triple_puff_soft'),
            ('right_puff', OUTPUT_CLEANUP, 'R.PUFF'),
            ('right_sip_soft', OUTPUT_CLEANUP, 'R.SIP.S'),
            ('lip', OUTPUT_CLEANUP, 'LIP'),
            ('', INPUT_CLEANUP, ''),
            (None, OUTPUT_CLEANUP, ''),
        ],
    )
    def test_cleanup_rules(self, raw, cleanup, expected):
        assert TextFormatter._text_clean(raw, cleanup) == expected


class TestFormatTextEdges:
    def test_format_stops_at_preferences(self, font_text):
        data = pd.DataFrame(
            [
                ('kb_a', 'up'),
                ('Preferences', 'x'),
                ('kb_b', 'down'),
            ],
            columns=['Command', 'Quadstick'],
        )
        _, bindings = TextFormatter.format_text(data, font_text, 400)
        assert bindings == [('A', 'UP')]

    def test_format_skips_rows_with_empty_cells(self, font_text):
        data = pd.DataFrame(
            [
                ('kb_a', 'up'),
                ('', 'down'),
                ('kb_b', ''),
                ('kb_c', 'left'),
            ],
            columns=['Command', 'Quadstick'],
        )
        _, bindings = TextFormatter.format_text(data, font_text, 400)
        assert bindings == [('A', 'UP'), ('C', 'LEFT')]
