"""Production composition root.

Initializes the Waveshare display, renders the startup screen with the
local access URL and shows it, then builds and runs the Flask
application. Importing this module is side-effect free; every side
effect lives in ``main()``.
"""

import logging
import socket
import sys

from quadstick_display import create_app
from quadstick_display.hardware import WaveshareDisplay
from quadstick_display.view import ProfileRenderer
from quadstick_display.web import RESOURCE_DIR

HTTP_PORT = 8080
HTTP_HOST = "0.0.0.0"

logger = logging.getLogger(__name__)


def _get_local_ip_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError as exc:
        logger.error(f"An error occurred: {exc}")
        return "error-ip-address"


def main(argv=None):
    """Run the production server.

    Accepts the optional legacy ``httpd`` argv item (the shipped systemd
    launcher invokes ``python qs_display.py httpd``); it carries no
    behavior. Any other argument is ignored with a warning.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    unknown = [arg for arg in args if arg != "httpd"]
    if unknown:
        logger.warning(f"Ignoring unrecognized arguments: {unknown}")

    logging.basicConfig(level=logging.INFO)

    display = WaveshareDisplay()
    display.initialize()

    # The startup screen renders before the server starts.
    url = f"http://{_get_local_ip_address()}:{HTTP_PORT}"
    renderer = ProfileRenderer(RESOURCE_DIR)
    display.show(renderer.render_startup(url, display.size))

    app = create_app(display=display)
    app.run(host=HTTP_HOST, port=HTTP_PORT, use_reloader=False)


if __name__ == "__main__":
    main()
