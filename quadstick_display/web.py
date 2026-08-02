"""Flask blueprint and application factory for the Quadstick display.

One Blueprint (``web``) owns the four routes; its handlers only translate
HTTP requests into ``ProfileStore``/``DisplayController`` calls and known
errors into HTTP responses. ``create_app`` wires the store, renderer, and
controller around an injected ``DisplayDevice`` and attaches them to
``app.extensions`` — no globals, and no hardware initialization: creating
the application never touches the display.

Default configuration (overridable through the ``config`` mapping):

- ``RESOURCE_DIR``: the repository's ``resources/`` directory;
- ``PROFILE_DIR``: its ``quadstick_csvs`` child;
- ``MAX_CONTENT_LENGTH``: 2 MiB upload limit.

Error mapping (the approved design semantics): unsafe or invalid
requests 400, missing profile 404, invalid CSV content 422, oversized
upload 413, hardware failure 503. Error responses render the index view
with an actionable message; successful uploads redirect to
``/uploads/<filename>`` and successful renders redirect to ``/``.
"""
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

from flask import (
    Blueprint,
    Flask,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge

from quadstick_display.controller import (
    DisplayController,
    DisplayDevice,
    DisplayFailure,
)
from quadstick_display.model import (
    InvalidProfile,
    InvalidProfileName,
    ProfileNotFound,
    ProfileStore,
)
from quadstick_display.view import ProfileRenderer

_RESOURCES = Path(__file__).resolve().parent.parent / 'resources'

RESOURCE_DIR = _RESOURCES
PROFILE_DIR = _RESOURCES / 'quadstick_csvs'
MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MiB

DEFAULT_CONFIG: Mapping[str, object] = {
    'RESOURCE_DIR': RESOURCE_DIR,
    'PROFILE_DIR': PROFILE_DIR,
    'MAX_CONTENT_LENGTH': MAX_CONTENT_LENGTH,
}

bp = Blueprint('web', __name__)


def create_app(
    config: Mapping[str, object] | None = None,
    *,
    display: DisplayDevice,
) -> Flask:
    """Build the Flask application around an injected display device.

    The display is only stored for the controller's transactions;
    initialization and the startup screen are the composition root's
    job (``quadstick_display.__main__``), so creating a test app has no
    hardware side effects.
    """
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(DEFAULT_CONFIG)
    if config is not None:
        app.config.from_mapping(config)

    resource_dir = Path(app.config['RESOURCE_DIR'])
    profile_dir = Path(app.config['PROFILE_DIR'])
    app.template_folder = str(resource_dir / 'templates')

    store = ProfileStore(profile_dir)
    renderer = ProfileRenderer(resource_dir)
    controller = DisplayController(store=store, renderer=renderer, device=display)
    app.extensions['quadstick_display'] = SimpleNamespace(
        store=store,
        renderer=renderer,
        controller=controller,
        display=display,
    )

    app.register_blueprint(bp)
    return app


def _components() -> SimpleNamespace:
    return current_app.extensions['quadstick_display']


def _render_index(error: str | None = None, status_code: int = 200):
    """Render the index view with the live store listing and status."""
    components = _components()
    display_status = components.controller.status
    return render_template(
        'index.html',
        csv_files=components.store.list_names(),
        selected_file=display_status.current_profile,
        status=display_status,
        error=error,
    ), status_code


def _format_size(limit: int) -> str:
    if limit >= 1024 * 1024:
        return f'{limit / (1024 * 1024):g} MiB'
    if limit >= 1024:
        return f'{limit / 1024:g} KiB'
    return f'{limit} bytes'


@bp.app_errorhandler(RequestEntityTooLarge)
def request_entity_too_large(error):
    limit = current_app.config['MAX_CONTENT_LENGTH']
    message = f'The uploaded file exceeds the {_format_size(limit)} size limit.'
    logging.warning(f'Rejected oversized upload: {error}')
    return _render_index(message, 413)


@bp.route('/')
def index():
    return _render_index()


@bp.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return _render_index(
            'No file was uploaded. Choose a .csv file to upload.', 400
        )
    upload_file = request.files['file']
    if not upload_file.filename:
        return _render_index(
            'No file was selected. Choose a .csv file to upload.', 400
        )
    try:
        filename = _components().store.save_upload(
            upload_file.filename, upload_file.stream
        )
    except InvalidProfileName as exc:
        logging.warning(f'Rejected upload {upload_file.filename!r}: {exc}')
        return _render_index(f'Upload rejected: {exc}', 400)
    return redirect(url_for('web.uploaded_file', filename=filename))


@bp.route('/uploads/<filename>')
def uploaded_file(filename):
    return f'File uploaded successfully: {filename}'


@bp.route('/render', methods=['POST'])
def render():
    name = request.form.get('selected_file', '')
    if not name:
        return _render_index(
            'Select a profile to display before submitting.', 400
        )
    try:
        _components().controller.show_profile(name)
    except InvalidProfileName as exc:
        logging.warning(f'Rejected render request: {exc}')
        return _render_index(f'Invalid profile name: {exc}', 400)
    except ProfileNotFound as exc:
        logging.warning(f'Render request for a missing profile: {exc}')
        return _render_index(
            f'Profile {name!r} was not found. Upload it first.', 404
        )
    except InvalidProfile as exc:
        logging.warning(f'Render request for an invalid profile: {exc}')
        return _render_index(
            f'{name!r} is not a valid Quadstick CSV export: {exc}', 422
        )
    except DisplayFailure as exc:
        logging.error(f'Display failure while rendering {name!r}: {exc}')
        return _render_index(
            'The display could not be updated; the previous profile is '
            'still shown. Try again.',
            503,
        )
    return redirect(url_for('web.index'))
