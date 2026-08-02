"""Integration tests for the M4 Flask MVC shell.

Pins the web-layer contract against the package interfaces through Flask's
test client with a recording ``FakeDisplay`` — no Raspberry Pi hardware,
no network calls:

- the application factory and its default configuration (resource/profile
  paths, 2 MiB upload limit) with components attached to ``app.extensions``
  and no hardware side effects at creation time;
- the exact route table (``/``, ``/upload``, ``/render``,
  ``/uploads/<filename>``), port 8080, and form fields ``file`` and
  ``selected_file``;
- index listing, selected status, empty state, and error display;
- successful upload redirect to ``/uploads/<filename>`` and successful
  render redirect to ``/``;
- the approved error mapping: unsafe/invalid requests 400, missing
  profile 404, invalid CSV content 422, oversized upload 413, hardware
  failure 503 — error responses render the index with an actionable
  message;
- the production composition root: hardware initialization and the
  startup screen happen before the server starts; ``qs_display.py``
  remains a working compatibility shim accepting ``httpd``.
"""
import io
import subprocess
import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/

from fakes import PRODUCTION_SIZE, FakeDisplay  # noqa: E402

from quadstick_display import create_app  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOURCES = REPO_ROOT / 'resources'
CSVS_DIR = RESOURCES / 'quadstick_csvs'
TWO_MIB = 2 * 1024 * 1024


def install_profile(directory, name='ad_infinitum.csv'):
    """Copy a bundled sample profile into the test profile directory."""
    target = Path(directory) / name
    target.write_bytes((CSVS_DIR / name).read_bytes())
    return target


class FlakyDisplay(FakeDisplay):
    """Display double raising a hardware-style error only when armed."""

    def __init__(self, error):
        super().__init__()
        self.error = error
        self.armed = False

    def show(self, frame):
        if self.armed:
            raise self.error
        super().show(frame)


@pytest.fixture
def display():
    return FakeDisplay()


@pytest.fixture
def app(tmp_path, display):
    return create_app({'PROFILE_DIR': tmp_path}, display=display)


@pytest.fixture
def client(app):
    return app.test_client()


def post_upload(client, payload, filename):
    return client.post(
        '/upload',
        data={'file': (io.BytesIO(payload), filename)},
        content_type='multipart/form-data',
    )


class TestFactory:
    def test_creation_has_no_hardware_side_effects(self, tmp_path, display):
        create_app({'PROFILE_DIR': tmp_path}, display=display)
        assert display.initialized is False
        assert display.frames == []
        assert 'waveshare_epd' not in sys.modules

    def test_default_configuration(self, display):
        app = create_app(display=display)
        assert app.config['RESOURCE_DIR'] == RESOURCES
        assert app.config['PROFILE_DIR'] == RESOURCES / 'quadstick_csvs'
        assert app.config['MAX_CONTENT_LENGTH'] == TWO_MIB

    def test_config_overrides(self, tmp_path, display):
        app = create_app(
            {'PROFILE_DIR': tmp_path, 'MAX_CONTENT_LENGTH': 64},
            display=display,
        )
        assert app.config['PROFILE_DIR'] == tmp_path
        assert app.config['MAX_CONTENT_LENGTH'] == 64

    def test_components_are_attached_to_app_extensions(self, app, display):
        components = app.extensions['quadstick_display']
        assert components.display is display
        assert components.store is not None
        assert components.renderer is not None
        assert components.controller.status.current_profile is None
        assert components.controller.status.last_error is None

    def test_package_import_stays_pure(self):
        # Importing the package must not pull Flask, pandas, or Pi
        # packages; ``create_app`` is exposed lazily.
        code = (
            'import sys;'
            'import quadstick_display;'
            'banned = [m for m in sys.modules if m.split(".")[0] in'
            ' {"flask", "pandas", "waveshare_epd", "spidev",'
            '  "gpiozero", "RPi", "lgpio", "Jetson"}];'
            'assert not banned, banned;'
            'from quadstick_display import create_app;'
            'assert callable(create_app)'
        )
        subprocess.run([sys.executable, '-c', code], check=True)


class TestRoutesAndPort:
    def test_port_is_8080(self):
        from quadstick_display.__main__ import HTTP_PORT

        assert HTTP_PORT == 8080

    def test_shim_delegates_to_the_package_entrypoint(self):
        import qs_display
        from quadstick_display import __main__ as package_main

        assert qs_display.HTTP_PORT == 8080
        assert qs_display.main is package_main.main

    def test_exact_routes_and_methods(self, app):
        rules = {rule.rule: rule.methods for rule in app.url_map.iter_rules()}
        assert set(rules) == {'/', '/render', '/upload', '/uploads/<filename>'}
        assert 'GET' in rules['/']
        assert 'POST' in rules['/render']
        assert 'POST' in rules['/upload']
        assert 'GET' in rules['/uploads/<filename>']


class TestIndex:
    def test_empty_state(self, client):
        response = client.get('/')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'No profiles uploaded yet' in html
        assert 'name="selected_file"' not in html
        # Uploading remains available in the empty state.
        assert 'action="/upload"' in html
        assert 'name="file"' in html

    def test_lists_profiles_sorted(self, client, tmp_path):
        (tmp_path / 'b.csv').write_text('b')
        (tmp_path / 'a.csv').write_text('a')
        (tmp_path / 'notes.txt').write_text('not a csv')

        response = client.get('/')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'a.csv' in html
        assert 'b.csv' in html
        assert html.index('a.csv') < html.index('b.csv')
        assert 'notes.txt' not in html

    def test_form_fields_and_url_for_actions(self, client, tmp_path):
        (tmp_path / 'a.csv').write_text('a')
        html = client.get('/').get_data(as_text=True)
        # Upload form posts a file field named 'file' to /upload.
        assert 'action="/upload"' in html
        assert 'name="file"' in html
        # Render form posts a radio field named 'selected_file' to /render.
        assert 'action="/render"' in html
        assert 'name="selected_file"' in html

    def test_initial_status_display(self, client):
        html = client.get('/').get_data(as_text=True)
        assert 'Current profile:' in html
        assert 'none' in html


class TestUpload:
    def test_upload_saves_csv_and_redirects_to_uploads(self, client, tmp_path):
        payload = b'QuadStick Configuration,Version 1.5,id,Test\n'
        response = post_upload(client, payload, 'My File.csv')
        assert response.status_code == 302
        assert response.headers['Location'] == '/uploads/My_File.csv'
        assert (tmp_path / 'My_File.csv').read_bytes() == payload

        confirmation = client.get('/uploads/My_File.csv')
        assert confirmation.status_code == 200
        assert confirmation.get_data(as_text=True) == (
            'File uploaded successfully: My_File.csv'
        )

    def test_upload_sanitizes_unsafe_filenames(self, client, tmp_path):
        response = post_upload(client, b'data', '../../evil.csv')
        assert response.status_code == 302
        assert response.headers['Location'] == '/uploads/evil.csv'
        assert (tmp_path / 'evil.csv').exists()

    def test_upload_rejects_non_csv_files(self, client, tmp_path):
        response = post_upload(client, b'data', 'notes.txt')
        assert response.status_code == 400
        assert not (tmp_path / 'notes.txt').exists()

    def test_upload_rejects_uppercase_extension(self, client, tmp_path):
        # The store's strict single-file-name policy requires a lowercase
        # '.csv' suffix; the legacy mixed-case acceptance is gone.
        response = post_upload(client, b'data', 'game.CSV')
        assert response.status_code == 400
        assert not (tmp_path / 'game.CSV').exists()

    def test_upload_without_file_part_is_400(self, client):
        response = client.post(
            '/upload', data={}, content_type='multipart/form-data'
        )
        assert response.status_code == 400

    def test_upload_with_empty_filename_is_400(self, client):
        response = post_upload(client, b'', '')
        assert response.status_code == 400

    def test_oversized_upload_is_413(self, tmp_path, display):
        app = create_app(
            {'PROFILE_DIR': tmp_path, 'MAX_CONTENT_LENGTH': 16},
            display=display,
        )
        client = app.test_client()
        response = post_upload(client, b'x' * 1024, 'big.csv')
        assert response.status_code == 413
        assert 'size limit' in response.get_data(as_text=True)
        assert not (tmp_path / 'big.csv').exists()

    def test_error_responses_render_the_index_view(self, client):
        response = post_upload(client, b'data', 'notes.txt')
        assert response.status_code == 400
        html = response.get_data(as_text=True)
        assert 'action="/upload"' in html
        assert 'role="alert"' in html

    def test_uploaded_profile_is_listed_and_renderable(self, client, tmp_path, display):
        payload = (CSVS_DIR / 'ad_infinitum.csv').read_bytes()
        response = post_upload(client, payload, 'ad_infinitum.csv')
        assert response.status_code == 302

        html = client.get('/').get_data(as_text=True)
        assert 'value="ad_infinitum.csv"' in html

        response = client.post('/render', data={'selected_file': 'ad_infinitum.csv'})
        assert response.status_code == 302
        assert len(display.frames) == 1


class TestRender:
    def test_render_displays_frame_and_redirects_to_index(
        self, client, display, tmp_path
    ):
        install_profile(tmp_path)
        response = client.post('/render', data={'selected_file': 'ad_infinitum.csv'})
        assert response.status_code == 302
        assert response.headers['Location'] == '/'

        (frame,) = display.frames
        for plane in (frame.black, frame.red):
            assert plane.mode == '1'
            assert plane.size == (PRODUCTION_SIZE.width, PRODUCTION_SIZE.height)

    def test_render_updates_the_selected_status_on_the_index(
        self, client, tmp_path
    ):
        install_profile(tmp_path)
        client.post('/render', data={'selected_file': 'ad_infinitum.csv'})
        html = client.get('/').get_data(as_text=True)
        assert 'value="ad_infinitum.csv" required checked' in html
        # The status panel reflects the displayed profile.
        status_panel = html.split('Current profile:')[1]
        assert 'ad_infinitum.csv' in status_panel

    def test_render_without_selection_is_400_and_draws_nothing(
        self, client, display
    ):
        response = client.post('/render', data={})
        assert response.status_code == 400
        assert 'Select a profile' in response.get_data(as_text=True)
        assert display.frames == []

    def test_render_missing_profile_is_404(self, client, app, display):
        response = client.post(
            '/render', data={'selected_file': 'does_not_exist.csv'}
        )
        assert response.status_code == 404
        html = response.get_data(as_text=True)
        assert 'does_not_exist.csv' in html
        assert 'role="alert"' in html
        assert display.frames == []

        status = app.extensions['quadstick_display'].controller.status
        assert status.current_profile is None
        assert 'does_not_exist.csv' in status.last_error

    def test_render_unsafe_name_is_400(self, client, app, display):
        response = client.post('/render', data={'selected_file': '../evil.csv'})
        assert response.status_code == 400
        assert display.frames == []
        status = app.extensions['quadstick_display'].controller.status
        assert status.current_profile is None
        assert status.last_error is not None

    def test_render_invalid_csv_is_422(self, client, display, tmp_path):
        (tmp_path / 'broken.csv').write_text('this is not a quadstick export\n')
        response = client.post('/render', data={'selected_file': 'broken.csv'})
        assert response.status_code == 422
        assert 'not a valid Quadstick CSV' in response.get_data(as_text=True)
        assert display.frames == []

    def test_hardware_failure_is_503_and_preserves_the_profile(self, tmp_path):
        display = FlakyDisplay(OSError('panel offline'))
        app = create_app({'PROFILE_DIR': tmp_path}, display=display)
        client = app.test_client()
        install_profile(tmp_path, 'ad_infinitum.csv')
        install_profile(tmp_path, 'alan_wake_II.csv')

        response = client.post(
            '/render', data={'selected_file': 'ad_infinitum.csv'}
        )
        assert response.status_code == 302

        display.armed = True
        response = client.post(
            '/render', data={'selected_file': 'alan_wake_II.csv'}
        )
        assert response.status_code == 503
        assert 'could not be updated' in response.get_data(as_text=True)
        assert len(display.frames) == 1  # nothing new was drawn

        status = app.extensions['quadstick_display'].controller.status
        assert status.current_profile == 'ad_infinitum.csv'
        assert 'panel offline' in status.last_error


class TestMainComposition:
    def test_main_initializes_shows_startup_then_serves(self, monkeypatch):
        import quadstick_display.__main__ as main_module

        events = []

        class OrderedFake(FakeDisplay):
            def initialize(self):
                events.append('initialize')
                super().initialize()

            def show(self, frame):
                events.append('show')
                super().show(frame)

        display = OrderedFake()
        monkeypatch.setattr(main_module, 'WaveshareDisplay', lambda: display)
        monkeypatch.setattr(
            main_module, '_get_local_ip_address', lambda: '192.0.2.1'
        )
        run_calls = []

        def fake_run(self, **kwargs):
            events.append('run')
            run_calls.append(kwargs)

        monkeypatch.setattr(Flask, 'run', fake_run)

        main_module.main(['httpd'])

        # Hardware init and the startup screen happen before the server
        # starts; no Waveshare driver was imported.
        assert events == ['initialize', 'show', 'run']
        (frame,) = display.frames
        assert frame.red.mode == '1'
        assert frame.red.size == (PRODUCTION_SIZE.width, PRODUCTION_SIZE.height)
        assert run_calls == [
            {'host': '0.0.0.0', 'port': 8080, 'use_reloader': False}
        ]
        assert 'waveshare_epd' not in sys.modules

    def test_main_accepts_the_legacy_httpd_argument(self, monkeypatch):
        import quadstick_display.__main__ as main_module

        display = FakeDisplay()
        monkeypatch.setattr(main_module, 'WaveshareDisplay', lambda: display)
        monkeypatch.setattr(
            main_module, '_get_local_ip_address', lambda: '192.0.2.1'
        )
        monkeypatch.setattr(Flask, 'run', lambda self, **kwargs: None)

        # No exception, no argument parsing failure.
        main_module.main(['httpd'])
        assert display.initialized
