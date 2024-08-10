import asyncio
import logging
import os
import re
import time

import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, render_template, request, redirect, url_for
from math import ceil
from werkzeug.utils import secure_filename

logging.basicConfig(level=logging.INFO)

HTTP_PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMG_PATHS = {
    'logo': f'{BASE_DIR}/resources/images/qs_logo.png',
    'airflow_arrow_ltr': f'{BASE_DIR}/resources/images/airflow_arrow_ltr.png'
}
FONT_PATHS = {
    'arial_black': f'{BASE_DIR}/resources/fonts/Arial Black.ttf',
    'verdana_bold': f'{BASE_DIR}/resources/fonts/Verdana Bold.ttf',
    'generale_mono': f'{BASE_DIR}/resources/fonts/GeneraleMonoA.ttf',
    'geforce_bold': f'{BASE_DIR}/resources/fonts/GeForce-Bold.ttf'
}
CSV_PATH = f'{BASE_DIR}/resources/quadstick_csvs'

# Modes: https://pillow.readthedocs.io/en/stable/handbook/concepts.html#modes
IMAGE_MODE = '1'
TITLE_SIZE = 24
TEXT_SIZE = 18
TEXT_SIZE_OFFSET = 2.6

# Quadstick button mapping
# The first 3 bits represent the left, center, and right buttons
# The 4th bit represents the sip/puff action
# The 5th bit represents the soft (for sip/puff) action
MP_BUTTONS = {
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


class DrawMpButtons:
    circle_border: int = 3

    def __init__(
            self,
            image_blk,
            draw_blk,
            image_red,
            draw_red,
            sip_icon,
            puff_icon,
            font_text,
            x, y
    ):
        self.image_blk = image_blk
        self.draw_blk = draw_blk
        self.image_red = image_red
        self.draw_red = draw_red
        self.sip_icon = sip_icon
        self.puff_icon = puff_icon
        self.font_text = font_text
        self.x = int(x)
        self.y = int(y)
        self.radius = int(ceil(TEXT_SIZE / TEXT_SIZE_OFFSET))
        self.is_text_only = False

    def draw_button(self, filled):
        area = [
            self.x - self.radius,
            self.y - self.radius,
            self.x + self.radius,
            self.y + self.radius
        ]
        fill = 0 if filled else 255
        self.draw_red.ellipse(xy=area, fill=fill, width=self.circle_border, outline=0)
        self.x += (self.radius * 2) + 4

    def draw_icon(self, is_sip):
        sip_puff_icon = self.sip_icon if is_sip else self.puff_icon
        logging.debug(f"Drawing sip/puff icon at {self.x}, {self.y}")
        self.image_blk.paste(
            im=sip_puff_icon,
            box=(self.x - self.radius, self.y - self.radius)
        )
        self.x += sip_puff_icon.width + self.circle_border

    def draw_text(self, text, draw=None):
        if not draw:
            draw = self.draw_red
        x_text = self.x - self.radius
        y_text = int(self.y)
        radius_offset = int(ceil(self.radius / TEXT_SIZE_OFFSET))
        y_text -= radius_offset
        draw.text((x_text, y_text), text, font=self.font_text, fill=0, anchor='lm')

    def draw_mp(self, button):
        if button not in MP_BUTTONS:
            logging.debug(f"Button {button} is not a mouthpiece button")
            self.is_text_only = True
            self.draw_text(button)
            return

        config = MP_BUTTONS[button]
        logging.debug(f"Drawing mouthpiece button {button} with config {config}")
        is_sip = config[3]
        is_soft = config[4]

        # Draw the button states
        for btn in config[:3]:
            self.draw_button(btn)

        # Draw sip/puff icon
        self.draw_icon(is_sip)

        # Draw the soft text if applicable
        if is_soft:
            self.draw_text('soft', self.draw_blk)


class CSVLoader:
    def __init__(self, file_path):
        self.file_path = os.path.join(CSV_PATH, file_path)

    def load_csv(self):
        csv_data = pd.read_csv(self.file_path)
        header = csv_data.columns
        name = header[-1]
        logging.info(f"Loaded CSV: {name}")
        filtered_data = csv_data.dropna(
            axis=1
        )[3:].index.dropna(
            how='all'
        ).to_frame(index=False)[[0, 2]]
        filtered_data.columns = ['Command', 'Quadstick']
        return filtered_data, name


class TextFormatter:
    @staticmethod
    def _text_clean(txt, cleanup):
        txt = str(txt).lower().strip() if txt else ''
        if not txt or txt.startswith('mp_'):
            return txt

        for old, new in cleanup:
            txt = re.sub(old, new, txt)
        return str(txt.strip()).upper()

    @classmethod
    def format_text(cls, data, font_text, width):
        max_width = 0
        formatted_data = []
        for index, row in data.iterrows():
            text_col1 = cls._text_clean(str(row['Command']), INPUT_CLEANUP)
            text_col2 = cls._text_clean(str(row['Quadstick']), OUTPUT_CLEANUP)
            if not text_col1 or not text_col2:
                continue

            if text_col1.casefold() == 'preferences':
                # The buttons mapping has finished
                break

            formatted_data.append((text_col1, text_col2))
            text_width = font_text.getlength(text_col1) + 10
            if text_width > max_width:
                max_width = min(text_width, width // 2)

        return max_width, formatted_data


class EPaperDisplay:
    def __init__(self):
        from waveshare_epd import epd4in2bc

        self.epd = epd4in2bc.EPD()
        self.width = self.epd.height
        self.height = self.epd.width

    def initialize_display(self):
        logging.info("Initializing e-Paper display")
        self.epd.init()
        self.epd.Clear()

    def display_content(self, image_black, image_red):
        logging.info("Displaying content on e-Paper display")
        self.epd.display(
            imageblack=self.epd.getbuffer(image_black),
            imagered=self.epd.getbuffer(image_red)
        )
        time.sleep(2)


class ImageCreator:
    def __init__(self):
        self.sip_icon = self.load_icon(
            IMG_PATHS['airflow_arrow_ltr'],
            flip_horizontal=True
        )
        self.puff_icon = self.load_icon(IMG_PATHS['airflow_arrow_ltr'])

    @staticmethod
    def load_icon(path, flip_horizontal=False):
        new_height = TEXT_SIZE
        icon = Image.open(path)
        if flip_horizontal:
            icon = icon.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        original_width, original_height = icon.size
        aspect_ratio = original_width / original_height
        new_width = int(aspect_ratio * new_height)
        return icon.resize((new_width, new_height))

    @staticmethod
    def _draw_horizontal_separator(draw_blk, draw_red, width, x2, y):
        y_line = y + 2
        draw_red.line((0, y_line, x2, y_line), fill=0)
        draw_blk.line((x2, y_line, width, y_line), fill=0)

    def create_image(self, data, font_text, width, height):
        x1 = 0
        x2, formatted_data = TextFormatter.format_text(data, font_text, width)
        draw_height = len(formatted_data) * TEXT_SIZE

        if draw_height > height:
            logging.warning(f"Resizing image to {width}x{draw_height} to fit all data")
            draw_height = len(formatted_data) * TEXT_SIZE
        else:
            draw_height = height

        image_blk = Image.new(IMAGE_MODE, (width, draw_height), 255)
        image_red = Image.new(IMAGE_MODE, (width, draw_height), 255)
        draw_blk = ImageDraw.Draw(image_blk)
        draw_red = ImageDraw.Draw(image_red)

        logging.info("Drawing Quadstick settings table")
        for index, row in enumerate(formatted_data):
            y = float(index) * TEXT_SIZE
            draw_blk.text(xy=(x1, y), text=row[0], font=font_text, fill=0)
            DrawMpButtons(
                image_blk=image_blk,
                draw_blk=draw_blk,
                image_red=image_red,
                draw_red=draw_red,
                sip_icon=self.sip_icon,
                puff_icon=self.puff_icon,
                font_text=font_text,
                x=x2 + TEXT_SIZE,
                y=(y + TEXT_SIZE) - (TEXT_SIZE // TEXT_SIZE_OFFSET)
            ).draw_mp(row[1])

            self._draw_horizontal_separator(draw_blk, draw_red, width, x2, y)

        if draw_height > height:
            logging.info(f"Resizing image back to the display size {width}x{height}")
            resample = Image.Resampling.BOX
            image_blk = image_blk.resize(size=(width, height), resample=resample)
            image_red = image_red.resize(size=(width, height), resample=resample)

        return image_blk, image_red


class InitScreen:
    text_rows = [
        "Access through browser"
    ]

    def __init__(self, epd):
        self.epd = epd

    def display_initial_screen(self):

        local_ip = self._get_local_ip_address()
        local_url = f"http://{local_ip}:{HTTP_PORT}"  # noqa
        self.text_rows.append(local_url)

        logging.debug("Displaying logo on e-Paper display")
        font_title = ImageFont.truetype(FONT_PATHS['geforce_bold'], TITLE_SIZE)
        image_blk = Image.open(IMG_PATHS['logo'])
        image_red = Image.new(IMAGE_MODE, (self.epd.width, self.epd.height), 255)
        draw_red = ImageDraw.Draw(image_red)

        for i, row in enumerate(self.text_rows):
            draw_red.text((5, 267 + (i * 30)), row, font=font_title, fill=0)

        self.epd.display_content(image_blk, image_red)
        # time.sleep(4)
        # self.epd.epd.sleep()

    @staticmethod
    def _get_local_ip_address():
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception as e:
            logging.error(f"An error occurred: {e}")
            return f"error-ip-address"


class HttpMenu:
    def __init__(self, epd):
        self.epd = epd
        self.app = Flask(__name__)
        self.upload_folder = CSV_PATH
        self.allowed_extensions = {'csv'}
        self.selected_file = None
        self.app.config['UPLOAD_FOLDER'] = self.upload_folder
        self.app.template_folder = os.path.join(BASE_DIR, 'resources/templates')

        os.makedirs(self.upload_folder, exist_ok=True)

        # Define routes
        self.app.add_url_rule('/', 'index', self.index)
        self.app.add_url_rule('/render', 'render', self.render, methods=['POST'])
        self.app.add_url_rule('/upload', 'upload', self.upload, methods=['POST'])
        self.app.add_url_rule('/uploads/<filename>', 'uploaded_file', self.uploaded_file)

        self.loop = asyncio.get_event_loop()

        # Display the initial screen
        InitScreen(epd).display_initial_screen()

    def allowed_file(self, filename):
        return '.' in filename and \
            filename.rsplit('.', 1)[1].lower() in self.allowed_extensions

    def index(self):
        csv_files = [f for f in os.listdir(self.app.config['UPLOAD_FOLDER']) if f.endswith('.csv')]
        csv_files = sorted(csv_files)
        return render_template('index.html', csv_files=csv_files, selected_file=self.selected_file)

    def upload(self):
        if 'file' not in request.files:
            return redirect(url_for('index'))

        file = request.files['file']
        if file.filename == '':
            return redirect(url_for('index'))

        if file and self.allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(self.upload_folder, filename)
            file.save(filepath)
            return redirect(url_for('uploaded_file', filename=filename))

        return redirect(url_for('index'))

    def uploaded_file(self, filename):  # noqa
        return f'File uploaded successfully: {filename}'

    async def render(self):
        self.selected_file = request.form.get('selected_file')
        if not self.selected_file:
            return redirect(url_for('index'))

        await asyncio.get_running_loop().create_task(self.render_csv())
        return redirect(url_for('index'))

    async def render_csv(self):
        try:
            csv_loader = CSVLoader(self.selected_file)
            data, name = await asyncio.to_thread(csv_loader.load_csv)
            font_text = ImageFont.truetype(FONT_PATHS['verdana_bold'], TEXT_SIZE)
            image_creator = ImageCreator()
            image_blk, image_red = await asyncio.to_thread(image_creator.create_image, data, font_text, self.epd.width,
                                                           self.epd.height)
            await asyncio.to_thread(self.epd.display_content, image_blk, image_red)
        except IOError as e:
            logging.error(f"IOError: {e}")
        except Exception as e:
            logging.error(f"An error occurred: {e}")

    def run(self, host='0.0.0.0', port=HTTP_PORT, debug=False):
        self.app.run(debug=debug, host=host, port=port, use_reloader=False)


def main():
    epd = EPaperDisplay()
    epd.initialize_display()
    http_menu = HttpMenu(epd)
    http_menu.run()


if __name__ == '__main__':
    main()
