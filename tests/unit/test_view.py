"""Unit tests for the pure Pillow view (quadstick_display.view).

Pins the M2 renderer contract against the same invariants the
characterization suite pins for the legacy ``qs_display`` rendering:
image mode and dimensions, black/red plane responsibilities, mouthpiece
button glyphs, sip-left/puff-right arrow orientation, the text-only
fallback, soft-action text, overflow resizing, and the startup screen.

Geometry is derived from the view constants and font metrics rather than
hard-coded pixel coordinates where practical. Display geometry mirrors
the production wiring for the 4.2-inch panel: width 400 x height 300.
"""
import logging
import subprocess
import sys
from math import ceil
from pathlib import Path

import pytest
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/

from fakes import FakeDisplay  # noqa: E402

from quadstick_display.controller import DisplayFrame, DisplaySize  # noqa: E402
from quadstick_display.model import Binding, Profile, ProfileStore  # noqa: E402
from quadstick_display.view import (  # noqa: E402
    IMAGE_MODE,
    INPUT_CLEANUP,
    MP_BUTTONS,
    OUTPUT_CLEANUP,
    TEXT_SIZE,
    TEXT_SIZE_OFFSET,
    ProfileRenderer,
    _text_clean,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOURCES = REPO_ROOT / 'resources'
CSVS_DIR = RESOURCES / 'quadstick_csvs'

DISPLAY_WIDTH = 400
DISPLAY_HEIGHT = 300
DISPLAY_SIZE = DisplaySize(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)

RADIUS = int(ceil(TEXT_SIZE / TEXT_SIZE_OFFSET))  # 7
BUTTON_STRIDE = (RADIUS * 2) + 4  # 18

# Verbatim copy of the mouthpiece mapping table: three button bits (left,
# center, right), then the is_puff bit, then the soft bit.
EXPECTED_MP_BUTTONS = {
    'mp_left_sip': (1, 0, 0, 0, 0),
    'mp_left_puff': (1, 0, 0, 1, 0),
    'mp_left_sip_soft': (1, 0, 0, 0, 1),
    'mp_left_puff_soft': (1, 0, 0, 1, 1),
    'mp_center_sip': (0, 1, 0, 0, 0),
    'mp_center_puff': (0, 1, 0, 1, 0),
    'mp_center_sip_soft': (0, 1, 0, 0, 1),
    'mp_center_puff_soft': (0, 1, 0, 1, 1),
    'mp_right_sip': (0, 0, 1, 0, 0),
    'mp_right_puff': (0, 0, 1, 1, 0),
    'mp_right_sip_soft': (0, 0, 1, 0, 1),
    'mp_right_puff_soft': (0, 0, 1, 1, 1),
    'mp_left_center_sip': (1, 1, 0, 0, 0),
    'mp_left_center_puff': (1, 1, 0, 1, 0),
    'mp_left_center_sip_soft': (1, 1, 0, 0, 1),
    'mp_left_center_puff_soft': (1, 1, 0, 1, 1),
    'mp_right_center_sip': (0, 1, 1, 0, 0),
    'mp_right_center_puff': (0, 1, 1, 1, 0),
    'mp_right_center_sip_soft': (0, 1, 1, 0, 1),
    'mp_right_center_puff_soft': (0, 1, 1, 1, 1),
    'mp_triple_sip': (1, 1, 1, 0, 0),
    'mp_triple_puff': (1, 1, 1, 1, 0),
    'mp_triple_sip_soft': (1, 1, 1, 0, 1),
    'mp_triple_puff_soft': (1, 1, 1, 1, 1),
}

ONE_ROW = [('kb_space', 'mp_center_sip')]


@pytest.fixture(scope='module')
def renderer():
    return ProfileRenderer(RESOURCES)


def make_profile(rows, name='test'):
    return Profile(
        name=name,
        bindings=tuple(Binding(command, quadstick_input) for command, quadstick_input in rows),
    )


def render(renderer, rows, size=DISPLAY_SIZE):
    return renderer.render(make_profile(rows), size)


def column_split(renderer, rows, width=DISPLAY_WIDTH):
    max_width, _ = renderer._format_bindings(make_profile(rows).bindings, width)
    return max_width


def mouthpiece_origin(renderer, rows, row_index=0):
    """Top-left reference for the mouthpiece cluster of a rendered row."""
    x2 = column_split(renderer, rows)
    x0 = int(x2 + TEXT_SIZE)
    y_center = int(float(row_index) * TEXT_SIZE + TEXT_SIZE - (TEXT_SIZE // TEXT_SIZE_OFFSET))
    return x0, y_center


def dark_rows_in_band(image, x0, x1):
    """Row indices containing a dark pixel within columns [x0, x1)."""
    gray = image.convert('L')
    width, height = gray.size
    rows = set()
    for x in range(max(0, x0), min(x1, width)):
        for y in range(height):
            if gray.getpixel((x, y)) < 128:
                rows.add(y)
    return rows


def has_dark(image, box):
    return 0 in image.crop(box).getdata()


def all_white(image, box):
    return 0 not in image.crop(box).getdata()


class TestMouthpieceTable:
    def test_mapping_table_is_stable(self):
        assert MP_BUTTONS == EXPECTED_MP_BUTTONS
        assert len(MP_BUTTONS) == 24

    @pytest.mark.parametrize('button', sorted(EXPECTED_MP_BUTTONS))
    def test_fourth_bit_is_puff(self, button):
        # The fourth bit names puff: it is set exactly for the *_puff
        # mappings and clear for the *_sip ones.
        is_puff = EXPECTED_MP_BUTTONS[button][3]
        assert is_puff == (1 if '_puff' in button else 0)


class TestImageBasics:
    def test_planes_mode_and_dimensions(self, renderer):
        frame = render(renderer, [('kb_w', 'up'), ('kb_s', 'down')])
        assert isinstance(frame, DisplayFrame)
        assert frame.black is not frame.red
        for plane in (frame.black, frame.red):
            assert plane.mode == IMAGE_MODE == '1'
            assert plane.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
            # Nothing reaches the bottom-right corner at this content size.
            assert plane.getpixel((DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1)) == 255
        assert 0 in frame.black.getdata()  # content was drawn

    def test_separator_is_split_across_planes(self, renderer):
        rows = [('kb_w', 'up'), ('kb_s', 'down')]
        frame = render(renderer, rows)
        for row_index in range(2):
            y_line = row_index * TEXT_SIZE + 2
            # Left of the split the separator lives in the red plane...
            assert frame.red.getpixel((1, y_line)) == 0
            # ...and only there; right of the split it lives in black only.
            assert frame.red.getpixel((DISPLAY_WIDTH - 1, y_line)) == 255
            assert frame.black.getpixel((DISPLAY_WIDTH - 1, y_line)) == 0

    def test_command_text_only_in_black_plane(self, renderer):
        frame = render(renderer, ONE_ROW)
        x2 = column_split(renderer, ONE_ROW)
        text_zone = (0, 3, int(x2) - 1, TEXT_SIZE - 1)
        assert has_dark(frame.black, text_zone)
        assert all_white(frame.red, text_zone)


class TestMouthpieceRendering:
    @pytest.mark.parametrize('button', sorted(EXPECTED_MP_BUTTONS))
    def test_button_glyphs_match_mapping_table(self, renderer, button):
        rows = [('kb_space', button)]
        frame = render(renderer, rows)
        config = EXPECTED_MP_BUTTONS[button]
        x0, y_center = mouthpiece_origin(renderer, rows)

        # Three circles, filled per the first three config bits. Filled
        # circles are solid (center pixel dark); unfilled are rings (center
        # pixel white). Circles exist only in the red plane.
        for position in range(3):
            center = (x0 + position * BUTTON_STRIDE, y_center)
            expected = 0 if config[position] else 255
            assert frame.red.getpixel(center) == expected
            assert frame.black.getpixel(center) == 255

        # The sip/puff arrow is pasted into the black plane right after the
        # third circle for every mouthpiece mapping.
        icon_left = x0 + (3 * BUTTON_STRIDE) - RADIUS
        icon_zone = (icon_left, 3, icon_left + 28, 24)
        assert has_dark(frame.black, icon_zone)

        # 'soft' text is drawn in the black plane after the icon if and
        # only if the soft bit is set.
        soft_zone = (icon_left + 29, 3, icon_left + 93, 24)
        if config[4]:
            assert has_dark(frame.black, soft_zone)
        else:
            assert all_white(frame.black, soft_zone)

    def test_text_only_fallback_for_non_mouthpiece_outputs(self, renderer):
        # Outputs that are not mp_* buttons (e.g. 'right_puff' -> 'R.PUFF')
        # render as red-plane text: no circles, no black-plane icon.
        rows = [('kb_space', 'right_puff')]
        frame = render(renderer, rows)
        x0, _ = mouthpiece_origin(renderer, rows)

        text_zone = (x0 - RADIUS, 3, x0 + 93, 24)
        assert has_dark(frame.red, text_zone)
        assert all_white(frame.black, text_zone)


class TestArrowOrientation:
    def test_icons_are_resized_to_text_height(self, renderer):
        raw = Image.open(RESOURCES / 'images' / 'airflow_arrow_ltr.png')
        expected_width = int((raw.width / raw.height) * TEXT_SIZE)
        assert renderer.arrow_right_icon.size == (expected_width, TEXT_SIZE) == (28, 18)
        assert renderer.arrow_left_icon.size == renderer.arrow_right_icon.size

    def test_left_arrow_is_horizontal_flip_of_right_arrow(self, renderer):
        flipped = renderer.arrow_right_icon.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        diff = ImageChops.difference(
            renderer.arrow_left_icon.convert('L'), flipped.convert('L')
        )
        assert diff.getbbox() is None

    def test_sip_points_left_and_puff_points_right(self, renderer):
        frame_sip = render(renderer, [('kb_space', 'mp_center_sip')])
        frame_puff = render(renderer, [('kb_space', 'mp_center_puff')])

        # Same command text and same circles: the black planes differ only
        # where the arrow icon was pasted.
        diff = ImageChops.difference(
            frame_sip.black.convert('L'), frame_puff.black.convert('L')
        )
        bbox = diff.getbbox()
        assert bbox is not None

        region_sip = frame_sip.black.crop(bbox)
        region_puff = frame_puff.black.crop(bbox)

        # The two pasted icons are exact horizontal mirrors.
        mirror = ImageChops.difference(
            region_sip.convert('L'),
            region_puff.transpose(Image.Transpose.FLIP_LEFT_RIGHT).convert('L'),
        )
        assert mirror.getbbox() is None

        # Absolute direction on the final black plane: the arrow tip is the
        # narrow, vertically centered edge. Sip points left, puff right.
        width, _ = region_sip.size
        sip_left = dark_rows_in_band(region_sip, 0, 3)
        sip_right = dark_rows_in_band(region_sip, width - 3, width)
        assert len(sip_left) < len(sip_right)

        puff_left = dark_rows_in_band(region_puff, 0, 3)
        puff_right = dark_rows_in_band(region_puff, width - 3, width)
        assert len(puff_right) < len(puff_left)


class TestOverflowResizing:
    def test_oversized_content_is_downscaled_to_display_size(self, renderer, caplog):
        # 24 rows * 18px = 432px > 300px display height: the image is drawn
        # tall and then resized back with BOX resampling.
        profile = ProfileStore(CSVS_DIR).load('alan_wake_II.csv')
        with caplog.at_level(logging.INFO):
            frame = renderer.render(profile, DISPLAY_SIZE)
        for plane in (frame.black, frame.red):
            assert plane.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
            assert plane.mode == '1'
        assert 'Resizing image to 400x432' in caplog.text
        assert 'Resizing image back to the display size 400x300' in caplog.text

    def test_content_that_fits_is_not_resized(self, renderer, caplog):
        # 16 rows * 18px = 288px <= 300px: the image is drawn at display
        # size and no resize happens.
        profile = ProfileStore(CSVS_DIR).load('ad_infinitum.csv')
        with caplog.at_level(logging.INFO):
            frame = renderer.render(profile, DISPLAY_SIZE)
        for plane in (frame.black, frame.red):
            assert plane.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
        assert 'Resizing image' not in caplog.text

    def test_taller_display_yields_taller_image(self, renderer, caplog):
        profile = ProfileStore(CSVS_DIR).load('alan_wake_II.csv')
        with caplog.at_level(logging.INFO):
            frame = renderer.render(profile, DisplaySize(width=400, height=500))
        assert frame.black.size == (400, 500)
        assert 'Resizing image' not in caplog.text


class TestEmptyProfile:
    def test_zero_bindings_render_a_blank_frame(self, renderer):
        # A valid header with zero bindings parses as Profile(bindings=());
        # rendering it must be deterministic: a blank white frame.
        frame = renderer.render(Profile(name='empty', bindings=()), DISPLAY_SIZE)
        for plane in (frame.black, frame.red):
            assert plane.mode == '1'
            assert plane.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
            assert 0 not in plane.getdata()

    def test_zero_bindings_render_identically_every_time(self, renderer):
        first = renderer.render(Profile(name='empty', bindings=()), DISPLAY_SIZE)
        second = renderer.render(Profile(name='empty', bindings=()), DISPLAY_SIZE)
        for plane in ('black', 'red'):
            diff = ImageChops.difference(
                getattr(first, plane).convert('L'), getattr(second, plane).convert('L')
            )
            assert diff.getbbox() is None


class TestStartupScreen:
    STARTUP_URL = 'http://192.0.2.1:8080'

    def test_black_plane_is_the_bundled_logo(self, renderer):
        frame = renderer.render_startup(self.STARTUP_URL, DISPLAY_SIZE)
        logo = Image.open(RESOURCES / 'images' / 'qs_logo.png')
        assert frame.black.size == logo.size == (300, 400)
        assert frame.black.mode == logo.mode == 'L'
        diff = ImageChops.difference(frame.black.convert('L'), logo.convert('L'))
        assert diff.getbbox() is None

    def test_red_plane_is_monochrome_at_display_size(self, renderer):
        frame = renderer.render_startup(self.STARTUP_URL, DISPLAY_SIZE)
        assert frame.red.mode == '1'
        assert frame.red.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)

    def test_red_plane_draws_rows_with_production_clipping(self, renderer):
        # Rows are anchored at y = 267 and y = 267 + 30 with the title
        # font. On the 300px production panel the first row's glyphs land
        # inside the panel while the second row is clipped entirely —
        # exactly how the legacy startup screen renders in production.
        frame = renderer.render_startup(self.STARTUP_URL, DISPLAY_SIZE)
        assert has_dark(frame.red, (0, 267, DISPLAY_WIDTH, 296))
        assert all_white(frame.red, (0, 0, DISPLAY_WIDTH, 267))
        assert all_white(frame.red, (0, 296, DISPLAY_WIDTH, DISPLAY_HEIGHT))

    def test_second_row_is_visible_on_a_taller_panel(self, renderer):
        tall = DisplaySize(width=DISPLAY_WIDTH, height=340)
        frame = renderer.render_startup(self.STARTUP_URL, tall)
        assert has_dark(frame.red, (0, 267, DISPLAY_WIDTH, 296))
        assert has_dark(frame.red, (0, 306, DISPLAY_WIDTH, 326))

    def test_rows_are_instance_local(self, renderer):
        # The legacy InitScreen appended the URL to class state, so every
        # subsequent instance redrew all previous URLs. render_startup must
        # not accumulate rows: same input, same pixels, every time — even
        # when interleaved with renders of other URLs.
        first = renderer.render_startup(self.STARTUP_URL, DISPLAY_SIZE)
        renderer.render_startup('http://198.51.100.7:8080', DISPLAY_SIZE)
        second = renderer.render_startup(self.STARTUP_URL, DISPLAY_SIZE)
        diff = ImageChops.difference(first.red.convert('L'), second.red.convert('L'))
        assert diff.getbbox() is None

    def test_url_only_changes_the_second_row(self, renderer):
        # On a taller panel the second row is fully visible; the first row
        # is URL-independent.
        tall = DisplaySize(width=DISPLAY_WIDTH, height=340)
        first = renderer.render_startup('http://192.0.2.1:8080', tall)
        second = renderer.render_startup('http://198.51.100.7:8080', tall)
        # The shared first row is identical...
        first_row = (0, 0, DISPLAY_WIDTH, 300)
        diff = ImageChops.difference(
            first.red.crop(first_row).convert('L'),
            second.red.crop(first_row).convert('L'),
        )
        assert diff.getbbox() is None
        # ...while the URL row differs.
        second_row = (0, 301, DISPLAY_WIDTH, 340)
        diff = ImageChops.difference(
            first.red.crop(second_row).convert('L'),
            second.red.crop(second_row).convert('L'),
        )
        assert diff.getbbox() is not None


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
        ],
    )
    def test_cleanup_rules(self, raw, cleanup, expected):
        assert _text_clean(raw, cleanup) == expected


class TestColumnSplitWidth:
    @pytest.mark.parametrize(
        'filename,expected',
        [('ad_infinitum.csv', 160.078125), ('alan_wake_II.csv', 161.8125)],
    )
    def test_max_width_drives_the_mouthpiece_column(self, renderer, filename, expected):
        # Font metrics come from the bundled Verdana Bold; allow a small
        # tolerance for FreeType variation across hosts.
        profile = ProfileStore(CSVS_DIR).load(filename)
        max_width, _ = renderer._format_bindings(profile.bindings, DISPLAY_WIDTH)
        assert max_width == pytest.approx(expected, rel=0.01)
        assert max_width <= DISPLAY_WIDTH // 2


class TestDisplaySeam:
    def test_fake_display_satisfies_the_device_protocol(self):
        from quadstick_display.controller import DisplayDevice

        assert isinstance(FakeDisplay(), DisplayDevice)

    def test_rendered_frames_flow_into_a_display(self, renderer):
        display = FakeDisplay()
        display.initialize()
        display.show(render(renderer, ONE_ROW))
        display.show(renderer.render_startup('http://192.0.2.1:8080', DISPLAY_SIZE))
        assert display.initialized
        assert len(display.frames) == 2


class TestViewPurity:
    def test_view_and_controller_import_without_pi_packages(self):
        code = (
            'import sys;'
            'import quadstick_display.controller;'
            'import quadstick_display.view;'
            'banned = [m for m in sys.modules if m.split(".")[0] in'
            ' {"flask", "pandas", "waveshare_epd", "spidev",'
            '  "gpiozero", "RPi", "lgpio", "Jetson"}];'
            'assert not banned, banned'
        )
        subprocess.run([sys.executable, '-c', code], check=True)
