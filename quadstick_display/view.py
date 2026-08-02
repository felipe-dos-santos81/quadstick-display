"""Pure Pillow rendering for Quadstick profiles and the startup screen.

``ProfileRenderer`` turns the domain model into ``DisplayFrame`` images —
the black and red monochrome planes of the e-paper panel — without
touching hardware, Flask, or pandas. Resource paths (fonts and images)
are injected as a ``Path`` so the view stays free of application wiring.

Rendering invariants preserved from the legacy single-file application:

- both planes are mode ``'1'`` images at the logical display size;
- command text and the sip/puff arrow live in the black plane; button
  circles, non-mouthpiece output text, and the left half of each row
  separator live in the red plane;
- the fourth mouthpiece bit is ``is_puff``: sip draws the left-pointing
  arrow and puff the right-pointing one;
- content taller than the display is drawn at full height and then
  downscaled with BOX resampling.
"""
import logging
import re
from math import ceil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from quadstick_display.controller import DisplayFrame, DisplaySize
from quadstick_display.model import Binding, Profile

# Modes: https://pillow.readthedocs.io/en/stable/handbook/concepts.html#modes
IMAGE_MODE = '1'
TITLE_SIZE = 24
TEXT_SIZE = 18
TEXT_SIZE_OFFSET = 2.6

FONT_VERDANA_BOLD = 'Verdana Bold.ttf'
FONT_GEFORCE_BOLD = 'GeForce-Bold.ttf'
IMAGE_ARROW = 'airflow_arrow_ltr.png'
IMAGE_LOGO = 'qs_logo.png'

STARTUP_FIRST_ROW = 'Access through browser'
STARTUP_TEXT_X = 5
STARTUP_TEXT_Y = 267
STARTUP_ROW_STRIDE = 30

# Quadstick button mapping
# The first 3 bits represent the left, center, and right buttons
# The 4th bit represents the puff action (clear means sip)
# The 5th bit represents the soft (for sip/puff) action
MP_BUTTONS = {
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

INPUT_CLEANUP = (
    ('kb_', ''), ('_', '.'), ('mouse', 'm'), ('button', 'btn'), ('control', 'ctrl'),
    ('delete', 'del'), ('back_space', 'bks'), ('pag_eup', 'pgup'), ('page_down', 'pgdn'),
    ('caps_lock', 'caps'), ('num_lock', 'num'), ('scroll_lock', 'scroll'), ('print_screen', 'prt'),
    ('pause_break', 'pause'), ('insert', 'ins'), ('wheel', 'whl')
)
OUTPUT_CLEANUP = (
    ('_', '.'), ('soft', 's'), ('.left', '.L'), ('right.', 'R.'), ('center', 'C'), ('L.C.', 'LC.'),
    ('R.C.', 'RC.'), ('L.R.', 'LR.')
)

_PREFERENCES_MARKER = 'preferences'


def _text_clean(txt, cleanup):
    """Normalize one cell: lowercase, apply regex cleanup pairs, uppercase.

    ``mp_*`` mouthpiece values pass through lowercase and unmodified.
    """
    txt = str(txt).lower().strip() if txt else ''
    if not txt or txt.startswith('mp_'):
        return txt

    for old, new in cleanup:
        txt = re.sub(old, new, txt)
    return str(txt.strip()).upper()


class _MouthpiecePainter:
    """Draws one mouthpiece glyph cluster (circles, arrow, soft label).

    Coordinates and plane choices mirror the legacy ``DrawMpButtons``:
    circles on the red plane, the arrow and the ``soft`` label on the
    black plane, and non-mouthpiece outputs as red-plane text.
    """

    circle_border: int = 3

    def __init__(self, image_blk, draw_blk, draw_red, arrow_left, arrow_right, font_text, x, y):
        self.image_blk = image_blk
        self.draw_blk = draw_blk
        self.draw_red = draw_red
        self.arrow_left = arrow_left
        self.arrow_right = arrow_right
        self.font_text = font_text
        self.x = int(x)
        self.y = int(y)
        self.radius = int(ceil(TEXT_SIZE / TEXT_SIZE_OFFSET))

    def draw_button(self, pressed):
        area = [
            self.x - self.radius,
            self.y - self.radius,
            self.x + self.radius,
            self.y + self.radius
        ]
        fill = 0 if pressed else 255
        self.draw_red.ellipse(xy=area, fill=fill, width=self.circle_border, outline=0)
        self.x += (self.radius * 2) + 4

    def draw_arrow(self, is_puff):
        # Sip draws the left-pointing arrow (towards the mouthpiece); puff
        # draws the right-pointing one (away from it).
        arrow = self.arrow_right if is_puff else self.arrow_left
        logging.debug(f"Drawing sip/puff arrow at {self.x}, {self.y}")
        self.image_blk.paste(
            im=arrow,
            box=(self.x - self.radius, self.y - self.radius)
        )
        self.x += arrow.width + self.circle_border

    def draw_text(self, text, draw=None):
        if not draw:
            draw = self.draw_red
        x_text = self.x - self.radius
        y_text = int(self.y)
        radius_offset = int(ceil(self.radius / TEXT_SIZE_OFFSET))
        y_text -= radius_offset
        draw.text((x_text, y_text), text, font=self.font_text, fill=0, anchor='lm')

    def draw(self, button):
        if button not in MP_BUTTONS:
            logging.debug(f"Button {button} is not a mouthpiece button")
            self.draw_text(button)
            return

        left, center, right, is_puff, is_soft = MP_BUTTONS[button]
        logging.debug(f"Drawing mouthpiece button {button}")

        # Draw the button states
        for pressed in (left, center, right):
            self.draw_button(pressed)

        # Draw the sip/puff arrow
        self.draw_arrow(is_puff)

        # Draw the soft text if applicable
        if is_soft:
            self.draw_text('soft', self.draw_blk)


class ProfileRenderer:
    """Renders ``Profile`` models and the startup screen into frames.

    ``resources`` is the repository's existing ``resources/`` directory;
    injecting it keeps the view independent of the web application.
    """

    def __init__(self, resources: Path):
        self._resources = Path(resources)
        fonts = self._resources / 'fonts'
        images = self._resources / 'images'
        self.font_text = ImageFont.truetype(str(fonts / FONT_VERDANA_BOLD), TEXT_SIZE)
        self.font_title = ImageFont.truetype(str(fonts / FONT_GEFORCE_BOLD), TITLE_SIZE)
        self.arrow_right_icon = self._load_icon(images / IMAGE_ARROW)
        self.arrow_left_icon = self._load_icon(images / IMAGE_ARROW, flip_horizontal=True)
        self._logo_path = images / IMAGE_LOGO

    @staticmethod
    def _load_icon(path, flip_horizontal=False):
        new_height = TEXT_SIZE
        icon = Image.open(path)
        if flip_horizontal:
            icon = icon.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        original_width, original_height = icon.size
        aspect_ratio = original_width / original_height
        new_width = int(aspect_ratio * new_height)
        return icon.resize((new_width, new_height))

    def render(self, profile: Profile, size: DisplaySize) -> DisplayFrame:
        """Render a profile's bindings as the two-panel settings table."""
        width, height = size.width, size.height
        x2, formatted_rows = self._format_bindings(profile.bindings, width)
        draw_height = len(formatted_rows) * TEXT_SIZE

        if draw_height > height:
            logging.warning(f"Resizing image to {width}x{draw_height} to fit all data")
        else:
            draw_height = height

        image_blk = Image.new(IMAGE_MODE, (width, draw_height), 255)
        image_red = Image.new(IMAGE_MODE, (width, draw_height), 255)
        draw_blk = ImageDraw.Draw(image_blk)
        draw_red = ImageDraw.Draw(image_red)

        logging.info("Drawing Quadstick settings table")
        for index, row in enumerate(formatted_rows):
            y = float(index) * TEXT_SIZE
            draw_blk.text(xy=(0, y), text=row[0], font=self.font_text, fill=0)
            _MouthpiecePainter(
                image_blk=image_blk,
                draw_blk=draw_blk,
                draw_red=draw_red,
                arrow_left=self.arrow_left_icon,
                arrow_right=self.arrow_right_icon,
                font_text=self.font_text,
                x=x2 + TEXT_SIZE,
                y=(y + TEXT_SIZE) - (TEXT_SIZE // TEXT_SIZE_OFFSET)
            ).draw(row[1])

            self._draw_horizontal_separator(draw_blk, draw_red, width, x2, y)

        if draw_height > height:
            logging.info(f"Resizing image back to the display size {width}x{height}")
            resample = Image.Resampling.BOX
            image_blk = image_blk.resize(size=(width, height), resample=resample)
            image_red = image_red.resize(size=(width, height), resample=resample)

        return DisplayFrame(black=image_blk, red=image_red)

    def render_startup(self, url: str, size: DisplaySize) -> DisplayFrame:
        """Render the startup screen: logo in black, access info in red.

        The text rows are local to each call — the legacy ``InitScreen``
        kept them in class state and appended the URL on every instance,
        duplicating rows across renders.
        """
        text_rows = (STARTUP_FIRST_ROW, url)

        logging.debug("Rendering startup screen")
        image_blk = Image.open(self._logo_path).copy()
        image_red = Image.new(IMAGE_MODE, (size.width, size.height), 255)
        draw_red = ImageDraw.Draw(image_red)

        for i, row in enumerate(text_rows):
            draw_red.text(
                (STARTUP_TEXT_X, STARTUP_TEXT_Y + (i * STARTUP_ROW_STRIDE)),
                row, font=self.font_title, fill=0,
            )

        return DisplayFrame(black=image_blk, red=image_red)

    def _format_bindings(self, bindings: tuple[Binding, ...], width: int):
        """Clean and filter raw bindings into display rows.

        Returns ``(max_width, rows)`` where ``max_width`` is the widest
        cleaned command text plus padding, capped at half the display
        width, and ``rows`` are the cleaned ``(command, output)`` pairs.
        """
        max_width = 0
        formatted_rows = []
        for binding in bindings:
            text_col1 = _text_clean(binding.command, INPUT_CLEANUP)
            text_col2 = _text_clean(binding.quadstick_input, OUTPUT_CLEANUP)
            if not text_col1 or not text_col2:
                continue

            if text_col1.casefold() == _PREFERENCES_MARKER:
                # The buttons mapping has finished
                break

            formatted_rows.append((text_col1, text_col2))
            text_width = self.font_text.getlength(text_col1) + 10
            if text_width > max_width:
                max_width = min(text_width, width // 2)

        return max_width, formatted_rows

    @staticmethod
    def _draw_horizontal_separator(draw_blk, draw_red, width, x2, y):
        y_line = y + 2
        draw_red.line((0, y_line, x2, y_line), fill=0)
        draw_blk.line((x2, y_line, width, y_line), fill=0)
