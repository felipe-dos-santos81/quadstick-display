"""Characterize Pillow rendering of the settings table.

M4 cutover: these pins previously targeted the legacy ``qs_display``
``ImageCreator``/``DrawMpButtons``; they now target the package view,
``ProfileRenderer``. The pinned invariants are unchanged: image mode and
dimensions, black/red plane responsibilities, mouthpiece button glyphs,
sip/puff arrow orientation, the text-only fallback, and overflow
resizing. Geometry is derived from the production constants and font
metrics rather than hard-coded pixel coordinates where practical.

The legacy ``DrawMpButtons.is_text_only`` attribute pin was dropped with
the legacy class; the observable text-only rendering fallback remains
pinned. Display geometry mirrors the production wiring for the 4.2-inch
panel: width 400 (``epd.height``) x height 300 (``epd.width``).
"""

import logging
from math import ceil
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from quadstick_display.controller import DisplaySize
from quadstick_display.model import Binding, Profile, ProfileStore
from quadstick_display.view import (
    IMAGE_MODE,
    MP_BUTTONS,
    TEXT_SIZE,
    TEXT_SIZE_OFFSET,
    ProfileRenderer,
)

RESOURCES = Path(__file__).resolve().parents[2] / "resources"
CSVS_DIR = RESOURCES / "quadstick_csvs"

DISPLAY_WIDTH = 400
DISPLAY_HEIGHT = 300
DISPLAY_SIZE = DisplaySize(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)

RADIUS = ceil(TEXT_SIZE / TEXT_SIZE_OFFSET)  # 7
BUTTON_STRIDE = (RADIUS * 2) + 4  # 18

# Verbatim copy of the production mouthpiece mapping table: three button
# bits (left, center, right), then the is_puff bit, then the soft bit.
EXPECTED_MP_BUTTONS = {
    "mp_left_sip": (1, 0, 0, 0, 0),
    "mp_left_puff": (1, 0, 0, 1, 0),
    "mp_left_sip_soft": (1, 0, 0, 0, 1),
    "mp_left_puff_soft": (1, 0, 0, 1, 1),
    "mp_center_sip": (0, 1, 0, 0, 0),
    "mp_center_puff": (0, 1, 0, 1, 0),
    "mp_center_sip_soft": (0, 1, 0, 0, 1),
    "mp_center_puff_soft": (0, 1, 0, 1, 1),
    "mp_right_sip": (0, 0, 1, 0, 0),
    "mp_right_puff": (0, 0, 1, 1, 0),
    "mp_right_sip_soft": (0, 0, 1, 0, 1),
    "mp_right_puff_soft": (0, 0, 1, 1, 1),
    "mp_left_center_sip": (1, 1, 0, 0, 0),
    "mp_left_center_puff": (1, 1, 0, 1, 0),
    "mp_left_center_sip_soft": (1, 1, 0, 0, 1),
    "mp_left_center_puff_soft": (1, 1, 0, 1, 1),
    "mp_right_center_sip": (0, 1, 1, 0, 0),
    "mp_right_center_puff": (0, 1, 1, 1, 0),
    "mp_right_center_sip_soft": (0, 1, 1, 0, 1),
    "mp_right_center_puff_soft": (0, 1, 1, 1, 1),
    "mp_triple_sip": (1, 1, 1, 0, 0),
    "mp_triple_puff": (1, 1, 1, 1, 0),
    "mp_triple_sip_soft": (1, 1, 1, 0, 1),
    "mp_triple_puff_soft": (1, 1, 1, 1, 1),
}

ONE_ROW = [("kb_space", "mp_center_sip")]


@pytest.fixture(scope="module")
def renderer():
    return ProfileRenderer(RESOURCES)


def make_profile(rows):
    return Profile(
        name="test",
        bindings=tuple(
            Binding(command, quadstick_input) for command, quadstick_input in rows
        ),
    )


def render(renderer, rows, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT):
    return renderer.render(make_profile(rows), DisplaySize(width=width, height=height))


def column_split(renderer, rows, width=DISPLAY_WIDTH):
    max_width, _ = renderer._format_bindings(make_profile(rows).bindings, width)
    return max_width


def mouthpiece_origin(renderer, rows, row_index=0):
    """Top-left reference for the mouthpiece cluster of a rendered row."""
    x2 = column_split(renderer, rows)
    x0 = int(x2 + TEXT_SIZE)
    y_center = int(
        float(row_index) * TEXT_SIZE + TEXT_SIZE - (TEXT_SIZE // TEXT_SIZE_OFFSET)
    )
    return x0, y_center


def dark_rows_in_band(image, x0, x1):
    """Row indices containing a dark pixel within columns [x0, x1)."""
    gray = image.convert("L")
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


class TestImageBasics:
    def test_planes_mode_and_dimensions(self, renderer):
        frame = render(renderer, [("kb_w", "up"), ("kb_s", "down")])
        assert frame.black is not frame.red
        for plane in (frame.black, frame.red):
            assert plane.mode == IMAGE_MODE == "1"
            assert plane.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
            # Nothing reaches the bottom-right corner at this content size.
            assert plane.getpixel((DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1)) == 255
        assert 0 in frame.black.getdata()  # content was drawn

    def test_separator_is_split_across_planes(self, renderer):
        rows = [("kb_w", "up"), ("kb_s", "down")]
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
    @pytest.mark.parametrize("button", sorted(EXPECTED_MP_BUTTONS))
    def test_button_glyphs_match_mapping_table(self, renderer, button):
        rows = [("kb_space", button)]
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

        # The sip/puff arrow is pasted into the black plane right after
        # the third circle for every mouthpiece mapping.
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
        rows = [("kb_space", "right_puff")]
        frame = render(renderer, rows)
        x0, _ = mouthpiece_origin(renderer, rows)

        text_zone = (x0 - RADIUS, 3, x0 + 93, 24)
        assert has_dark(frame.red, text_zone)
        assert all_white(frame.black, text_zone)


class TestArrowOrientation:
    def test_icons_are_resized_to_text_height(self, renderer):
        raw = Image.open(RESOURCES / "images" / "airflow_arrow_ltr.png")
        expected_width = int((raw.width / raw.height) * TEXT_SIZE)
        assert renderer.arrow_right_icon.size == (expected_width, TEXT_SIZE) == (28, 18)
        assert renderer.arrow_left_icon.size == renderer.arrow_right_icon.size

    def test_left_arrow_is_horizontal_flip_of_right_arrow(self, renderer):
        flipped = renderer.arrow_right_icon.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        diff = ImageChops.difference(
            renderer.arrow_left_icon.convert("L"), flipped.convert("L")
        )
        assert diff.getbbox() is None

    def test_source_art_points_right(self):
        # The bundled arrow points left-to-right: the narrow, vertically
        # centered tip is on the right edge; the wide tail mass is on the
        # left. So the unflipped icon points right and the flipped one
        # points left.
        raw = Image.open(RESOURCES / "images" / "airflow_arrow_ltr.png")
        left = dark_rows_in_band(raw, 0, 10)
        right = dark_rows_in_band(raw, raw.width - 10, raw.width)
        assert len(right) < len(left)
        assert min(right) < raw.height // 2 < max(right)

    def test_sip_points_left_and_puff_points_right(self, renderer):
        frame_sip = render(renderer, [("kb_space", "mp_center_sip")])
        frame_puff = render(renderer, [("kb_space", "mp_center_puff")])

        # Same command text and same circles: the black planes differ only
        # where the arrow icon was pasted.
        diff = ImageChops.difference(
            frame_sip.black.convert("L"), frame_puff.black.convert("L")
        )
        bbox = diff.getbbox()
        assert bbox is not None

        region_sip = frame_sip.black.crop(bbox)
        region_puff = frame_puff.black.crop(bbox)

        # The two pasted icons are exact horizontal mirrors.
        mirror = ImageChops.difference(
            region_sip.convert("L"),
            region_puff.transpose(Image.Transpose.FLIP_LEFT_RIGHT).convert("L"),
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
        profile = ProfileStore(CSVS_DIR).load("alan_wake_II.csv")
        with caplog.at_level(logging.INFO):
            frame = renderer.render(profile, DISPLAY_SIZE)
        for plane in (frame.black, frame.red):
            assert plane.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
            assert plane.mode == "1"
        assert "Resizing image to 400x432" in caplog.text
        assert "Resizing image back to the display size 400x300" in caplog.text

    def test_content_that_fits_is_not_resized(self, renderer, caplog):
        # 16 rows * 18px = 288px <= 300px: the image is drawn at display
        # size and no resize happens.
        profile = ProfileStore(CSVS_DIR).load("ad_infinitum.csv")
        with caplog.at_level(logging.INFO):
            frame = renderer.render(profile, DISPLAY_SIZE)
        for plane in (frame.black, frame.red):
            assert plane.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
        assert "Resizing image" not in caplog.text

    def test_taller_display_yields_taller_image(self, renderer, caplog):
        profile = ProfileStore(CSVS_DIR).load("alan_wake_II.csv")
        with caplog.at_level(logging.INFO):
            frame = renderer.render(profile, DisplaySize(width=400, height=500))
        assert frame.black.size == (400, 500)
        assert "Resizing image" not in caplog.text
