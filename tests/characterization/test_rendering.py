"""Characterize Pillow rendering of the settings table.

Pins the current behavior of ``ImageCreator`` and ``DrawMpButtons``: image
mode and dimensions, black/red plane responsibilities, mouthpiece button
glyphs, sip/puff arrow orientation, the text-only fallback, and overflow
resizing. Geometry is derived from the production constants and font metrics
rather than hard-coded pixel coordinates where practical.

Display geometry mirrors the production wiring for the 4.2-inch panel:
width 400 (``epd.height``) x height 300 (``epd.width``).
"""
import logging
from math import ceil

import pandas as pd
import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont

from qs_display import (
    CSVLoader,
    FONT_PATHS,
    IMAGE_MODE,
    IMG_PATHS,
    MP_BUTTONS,
    TEXT_SIZE,
    TEXT_SIZE_OFFSET,
    DrawMpButtons,
    ImageCreator,
    TextFormatter,
)

DISPLAY_WIDTH = 400
DISPLAY_HEIGHT = 300

RADIUS = int(ceil(TEXT_SIZE / TEXT_SIZE_OFFSET))  # 7
BUTTON_STRIDE = (RADIUS * 2) + 4  # 18

# Verbatim copy of the production mouthpiece mapping table: three button
# bits (left, center, right), then the sip/puff bit, then the soft bit.
EXPECTED_MP_BUTTONS = {
    'mp_left_sip': [1, 0, 0, 0, 0],
    'mp_left_puff': [1, 0, 0, 1, 0],
    'mp_left_sip_soft': [1, 0, 0, 0, 1],
    'mp_left_puff_soft': [1, 0, 0, 1, 1],
    'mp_center_sip': [0, 1, 0, 0, 0],
    'mp_center_puff': [0, 1, 0, 1, 0],
    'mp_center_sip_soft': [0, 1, 0, 0, 1],
    'mp_center_puff_soft': [0, 1, 0, 1, 1],
    'mp_right_sip': [0, 0, 1, 0, 0],
    'mp_right_puff': [0, 0, 1, 1, 0],
    'mp_right_sip_soft': [0, 0, 1, 0, 1],
    'mp_right_puff_soft': [0, 0, 1, 1, 1],
    'mp_left_center_sip': [1, 1, 0, 0, 0],
    'mp_left_center_puff': [1, 1, 0, 1, 0],
    'mp_left_center_sip_soft': [1, 1, 0, 0, 1],
    'mp_left_center_puff_soft': [1, 1, 0, 1, 1],
    'mp_right_center_sip': [0, 1, 1, 0, 0],
    'mp_right_center_puff': [0, 1, 1, 1, 0],
    'mp_right_center_sip_soft': [0, 1, 1, 0, 1],
    'mp_right_center_puff_soft': [0, 1, 1, 1, 1],
    'mp_triple_sip': [1, 1, 1, 0, 0],
    'mp_triple_puff': [1, 1, 1, 1, 0],
    'mp_triple_sip_soft': [1, 1, 1, 0, 1],
    'mp_triple_puff_soft': [1, 1, 1, 1, 1],
}

ONE_ROW = [('kb_space', 'mp_center_sip')]


@pytest.fixture(scope='module')
def font_text():
    return ImageFont.truetype(FONT_PATHS['verdana_bold'], TEXT_SIZE)


def render(font_text, rows, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT):
    data = pd.DataFrame(rows, columns=['Command', 'Quadstick'])
    return ImageCreator().create_image(data, font_text, width, height)


def column_split(font_text, rows, width=DISPLAY_WIDTH):
    data = pd.DataFrame(rows, columns=['Command', 'Quadstick'])
    x2, _ = TextFormatter.format_text(data, font_text, width)
    return x2


def mouthpiece_origin(font_text, rows, row_index=0):
    """Top-left reference for the mouthpiece cluster of a rendered row."""
    x2 = column_split(font_text, rows)
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


class TestImageBasics:
    def test_planes_mode_and_dimensions(self, font_text):
        image_blk, image_red = render(font_text, [('kb_w', 'up'), ('kb_s', 'down')])
        assert image_blk is not image_red
        for plane in (image_blk, image_red):
            assert plane.mode == IMAGE_MODE == '1'
            assert plane.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
            # Nothing reaches the bottom-right corner at this content size.
            assert plane.getpixel((DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1)) == 255
        assert 0 in image_blk.getdata()  # content was drawn

    def test_separator_is_split_across_planes(self, font_text):
        rows = [('kb_w', 'up'), ('kb_s', 'down')]
        image_blk, image_red = render(font_text, rows)
        for row_index in range(2):
            y_line = row_index * TEXT_SIZE + 2
            # Left of the split the separator lives in the red plane...
            assert image_red.getpixel((1, y_line)) == 0
            # ...and only there; right of the split it lives in black only.
            assert image_red.getpixel((DISPLAY_WIDTH - 1, y_line)) == 255
            assert image_blk.getpixel((DISPLAY_WIDTH - 1, y_line)) == 0

    def test_command_text_only_in_black_plane(self, font_text):
        image_blk, image_red = render(font_text, ONE_ROW)
        x2 = column_split(font_text, ONE_ROW)
        text_zone = (0, 3, int(x2) - 1, TEXT_SIZE - 1)
        assert has_dark(image_blk, text_zone)
        assert all_white(image_red, text_zone)


class TestMouthpieceRendering:
    @pytest.mark.parametrize('button', sorted(EXPECTED_MP_BUTTONS))
    def test_button_glyphs_match_mapping_table(self, font_text, button):
        rows = [('kb_space', button)]
        image_blk, image_red = render(font_text, rows)
        config = EXPECTED_MP_BUTTONS[button]
        x0, y_center = mouthpiece_origin(font_text, rows)

        # Three circles, filled per the first three config bits. Filled
        # circles are solid (center pixel dark); unfilled are rings (center
        # pixel white). Circles exist only in the red plane.
        for position in range(3):
            center = (x0 + position * BUTTON_STRIDE, y_center)
            expected = 0 if config[position] else 255
            assert image_red.getpixel(center) == expected
            assert image_blk.getpixel(center) == 255

        # The sip/puff icon is pasted into the black plane right after the
        # third circle for every mouthpiece mapping.
        icon_left = x0 + (3 * BUTTON_STRIDE) - RADIUS
        icon_zone = (icon_left, 3, icon_left + 28, 24)
        assert has_dark(image_blk, icon_zone)

        # 'soft' text is drawn in the black plane after the icon if and only
        # if the soft bit is set.
        soft_zone = (icon_left + 29, 3, icon_left + 93, 24)
        if config[4]:
            assert has_dark(image_blk, soft_zone)
        else:
            assert all_white(image_blk, soft_zone)

    def test_text_only_fallback_for_non_mouthpiece_outputs(self, font_text):
        # Outputs that are not mp_* buttons (e.g. 'right_puff' -> 'R.PUFF')
        # render as red-plane text: no circles, no black-plane icon.
        rows = [('kb_space', 'right_puff')]
        image_blk, image_red = render(font_text, rows)
        x0, _ = mouthpiece_origin(font_text, rows)

        text_zone = (x0 - RADIUS, 3, x0 + 93, 24)
        assert has_dark(image_red, text_zone)
        assert all_white(image_blk, text_zone)

    def test_draw_mp_flags_text_only_for_unknown_buttons(self, font_text):
        creator = ImageCreator()
        image = Image.new('1', (200, 50), 255)
        buttons = DrawMpButtons(
            image_blk=image,
            draw_blk=ImageDraw.Draw(image),
            image_red=image,
            draw_red=ImageDraw.Draw(image),
            sip_icon=creator.sip_icon,
            puff_icon=creator.puff_icon,
            font_text=font_text,
            x=20,
            y=20,
        )
        assert buttons.is_text_only is False
        buttons.draw_mp('R.PUFF')
        assert buttons.is_text_only is True

        buttons = DrawMpButtons(
            image_blk=image,
            draw_blk=ImageDraw.Draw(image),
            image_red=image,
            draw_red=ImageDraw.Draw(image),
            sip_icon=creator.sip_icon,
            puff_icon=creator.puff_icon,
            font_text=font_text,
            x=20,
            y=20,
        )
        buttons.draw_mp('mp_center_sip')
        assert buttons.is_text_only is False


class TestArrowOrientation:
    def test_icons_are_resized_to_text_height(self):
        creator = ImageCreator()
        raw = Image.open(IMG_PATHS['airflow_arrow_ltr'])
        expected_width = int((raw.width / raw.height) * TEXT_SIZE)
        assert creator.sip_icon.size == (expected_width, TEXT_SIZE) == (28, 18)
        assert creator.puff_icon.size == creator.sip_icon.size

    def test_puff_icon_is_horizontal_flip_of_sip_icon(self):
        creator = ImageCreator()
        flipped = creator.sip_icon.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        diff = ImageChops.difference(
            creator.puff_icon.convert('L'), flipped.convert('L')
        )
        assert diff.getbbox() is None

    def test_source_art_points_right(self):
        # The bundled arrow points left-to-right: the narrow, vertically
        # centered tip is on the right edge; the wide tail mass is on the
        # left. So sip_icon (unflipped) points right and puff_icon (flipped)
        # points left.
        raw = Image.open(IMG_PATHS['airflow_arrow_ltr'])
        left = dark_rows_in_band(raw, 0, 10)
        right = dark_rows_in_band(raw, raw.width - 10, raw.width)
        assert len(right) < len(left)
        assert min(right) < raw.height // 2 < max(right)

    def test_sip_points_left_and_puff_points_right(self, font_text):
        image_sip, _ = render(font_text, [('kb_space', 'mp_center_sip')])
        image_puff, _ = render(font_text, [('kb_space', 'mp_center_puff')])

        # Same command text and same circles: the black planes differ only
        # where the arrow icon was pasted.
        diff = ImageChops.difference(image_sip.convert('L'), image_puff.convert('L'))
        bbox = diff.getbbox()
        assert bbox is not None

        region_sip = image_sip.crop(bbox)
        region_puff = image_puff.crop(bbox)

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
    def test_oversized_content_is_downscaled_to_display_size(self, font_text, caplog):
        # 24 rows * 18px = 432px > 300px display height: the image is drawn
        # tall and then resized back with BOX resampling.
        data, _ = CSVLoader('alan_wake_II.csv').load_csv()
        with caplog.at_level(logging.INFO):
            image_blk, image_red = ImageCreator().create_image(
                data, font_text, DISPLAY_WIDTH, DISPLAY_HEIGHT
            )
        for plane in (image_blk, image_red):
            assert plane.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
            assert plane.mode == '1'
        assert 'Resizing image to 400x432' in caplog.text
        assert 'Resizing image back to the display size 400x300' in caplog.text

    def test_content_that_fits_is_not_resized(self, font_text, caplog):
        # 16 rows * 18px = 288px <= 300px: the image is drawn at display
        # size and no resize happens.
        data, _ = CSVLoader('ad_infinitum.csv').load_csv()
        with caplog.at_level(logging.INFO):
            image_blk, image_red = ImageCreator().create_image(
                data, font_text, DISPLAY_WIDTH, DISPLAY_HEIGHT
            )
        for plane in (image_blk, image_red):
            assert plane.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
        assert 'Resizing image' not in caplog.text

    def test_taller_display_yields_taller_image(self, font_text, caplog):
        data, _ = CSVLoader('alan_wake_II.csv').load_csv()
        with caplog.at_level(logging.INFO):
            image_blk, _ = ImageCreator().create_image(data, font_text, 400, 500)
        assert image_blk.size == (400, 500)
        assert 'Resizing image' not in caplog.text
