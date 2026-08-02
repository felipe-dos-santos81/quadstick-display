"""Characterize the HTTP surface of ``HttpMenu``.

Pins the current routes, form field names, redirect targets, upload
handling, and render behavior using Flask's test client with a fake e-paper
display. No hardware is touched and no network calls are made (the startup
screen's IP lookup is stubbed by the ``http_env`` fixture).
"""
import inspect
import io
import logging
import sys

import qs_display
from qs_display import HTTP_PORT, HttpMenu


class TestRoutesAndPort:
    def test_port_is_8080(self):
        assert HTTP_PORT == 8080

    def test_run_defaults(self):
        signature = inspect.signature(HttpMenu.run)
        assert signature.parameters['host'].default == '0.0.0.0'
        assert signature.parameters['port'].default == 8080
        assert signature.parameters['debug'].default is False

    def test_routes_and_methods(self, http_env):
        rules = {rule.rule: rule.methods for rule in http_env.menu.app.url_map.iter_rules()}
        assert 'GET' in rules['/']
        assert 'POST' in rules['/render']
        assert 'POST' in rules['/upload']
        assert 'GET' in rules['/uploads/<filename>']

    def test_startup_screen_is_displayed_on_construction(self, http_env):
        # HttpMenu.__init__ renders the initial screen once through the
        # display: black plane is the bundled logo, red plane is a mode '1'
        # image at display size with the access URL.
        frames = http_env.display.frames
        assert len(frames) == 1
        _, image_red = frames[0]
        assert image_red.mode == '1'
        assert image_red.size == (400, 300)

    def test_waveshare_driver_is_not_imported(self):
        assert 'waveshare_epd' not in sys.modules


class TestIndex:
    def test_get_index_lists_csv_files_sorted(self, http_env):
        (http_env.upload_dir / 'b.csv').write_text('b')
        (http_env.upload_dir / 'a.csv').write_text('a')
        (http_env.upload_dir / 'notes.txt').write_text('not a csv')

        response = http_env.client.get('/')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'a.csv' in html
        assert 'b.csv' in html
        assert html.index('a.csv') < html.index('b.csv')
        assert 'notes.txt' not in html

    def test_get_index_form_fields(self, http_env):
        # The selected_file radios only render when CSV files are present.
        (http_env.upload_dir / 'a.csv').write_text('a')
        html = http_env.client.get('/').get_data(as_text=True)
        # Upload form posts a file field named 'file' to /upload.
        assert 'action="/upload"' in html
        assert 'name="file"' in html
        # Render form posts a radio field named 'selected_file' to /render.
        assert 'action="/render"' in html
        assert 'name="selected_file"' in html

    def test_get_index_marks_selected_file_checked(self, http_env):
        (http_env.upload_dir / 'a.csv').write_text('a')
        http_env.menu.selected_file = 'a.csv'
        html = http_env.client.get('/').get_data(as_text=True)
        assert 'value="a.csv" required checked' in html


class TestUpload:
    def test_upload_saves_csv_and_redirects_to_uploads(self, http_env):
        payload = b'QuadStick Configuration,Version 1.5,id,Test\n'
        response = http_env.client.post(
            '/upload',
            data={'file': (io.BytesIO(payload), 'My File.CSV')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 302
        assert response.headers['Location'] == '/uploads/My_File.CSV'
        saved = http_env.upload_dir / 'My_File.CSV'
        assert saved.read_bytes() == payload

        confirmation = http_env.client.get('/uploads/My_File.CSV')
        assert confirmation.status_code == 200
        assert confirmation.get_data(as_text=True) == (
            'File uploaded successfully: My_File.CSV'
        )

    def test_upload_sanitizes_unsafe_filenames(self, http_env):
        response = http_env.client.post(
            '/upload',
            data={'file': (io.BytesIO(b'data'), '../../evil.csv')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 302
        assert response.headers['Location'] == '/uploads/evil.csv'
        assert (http_env.upload_dir / 'evil.csv').exists()

    def test_upload_rejects_non_csv_files(self, http_env):
        response = http_env.client.post(
            '/upload',
            data={'file': (io.BytesIO(b'data'), 'notes.txt')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 302
        assert response.headers['Location'] == '/'
        assert not (http_env.upload_dir / 'notes.txt').exists()

    def test_upload_without_file_part_redirects_to_index(self, http_env):
        response = http_env.client.post(
            '/upload', data={}, content_type='multipart/form-data'
        )
        assert response.status_code == 302
        assert response.headers['Location'] == '/'

    def test_upload_with_empty_filename_redirects_to_index(self, http_env):
        response = http_env.client.post(
            '/upload',
            data={'file': (io.BytesIO(b''), '')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 302
        assert response.headers['Location'] == '/'

    def test_allowed_file_extensions(self, http_env):
        assert http_env.menu.allowed_file('profile.csv')
        assert http_env.menu.allowed_file('profile.CSV')
        assert not http_env.menu.allowed_file('profile.txt')
        assert not http_env.menu.allowed_file('noextension')


class TestRender:
    def test_render_selected_profile_displays_frame(self, http_env):
        response = http_env.client.post(
            '/render', data={'selected_file': 'ad_infinitum.csv'}
        )
        assert response.status_code == 302
        assert response.headers['Location'] == '/'
        assert http_env.menu.selected_file == 'ad_infinitum.csv'

        # The startup screen frame plus the freshly rendered profile frame.
        frames = http_env.display.frames
        assert len(frames) == 2
        image_blk, image_red = frames[-1]
        for plane in (image_blk, image_red):
            assert plane.mode == '1'
            assert plane.size == (400, 300)

        # The selection is reflected on the index page. The index lists the
        # (isolated) upload folder, so make the same profile visible there.
        (http_env.upload_dir / 'ad_infinitum.csv').write_text('stub')
        html = http_env.client.get('/').get_data(as_text=True)
        assert 'value="ad_infinitum.csv" required checked' in html

    def test_render_without_selection_redirects_and_draws_nothing(self, http_env):
        response = http_env.client.post('/render', data={})
        assert response.status_code == 302
        assert response.headers['Location'] == '/'
        assert len(http_env.display.frames) == 1  # startup screen only

    def test_render_unknown_profile_logs_error_and_draws_nothing(self, http_env, caplog):
        with caplog.at_level(logging.ERROR):
            response = http_env.client.post(
                '/render', data={'selected_file': 'does_not_exist.csv'}
            )
        assert response.status_code == 302
        assert response.headers['Location'] == '/'
        assert len(http_env.display.frames) == 1
        # M3: a missing profile surfaces as the model's typed ProfileNotFound
        # (an IOError subclass), so the log keeps the legacy 'IOError' prefix
        # but names the file without the legacy errno path text.
        assert 'IOError' in caplog.text
        assert 'does_not_exist.csv' in caplog.text
        # The failed write does not become the current profile.
        status = http_env.menu.controller.status
        assert status.current_profile is None
        assert 'does_not_exist.csv' in status.last_error

    def test_render_display_failure_preserves_previous_profile(self, http_env, monkeypatch):
        # First render succeeds and becomes the current profile.
        response = http_env.client.post(
            '/render', data={'selected_file': 'ad_infinitum.csv'}
        )
        assert response.status_code == 302
        assert http_env.menu.controller.status.current_profile == 'ad_infinitum.csv'

        # A hardware failure on the next render redirects like a success,
        # draws nothing new, and keeps the previous profile.
        def broken_display_content(image_black, image_red):
            raise OSError('panel offline')

        monkeypatch.setattr(
            http_env.display, 'display_content', broken_display_content
        )
        response = http_env.client.post(
            '/render', data={'selected_file': 'alan_wake_II.csv'}
        )
        assert response.status_code == 302
        assert response.headers['Location'] == '/'
        assert len(http_env.display.frames) == 2  # startup + first render only
        status = http_env.menu.controller.status
        assert status.current_profile == 'ad_infinitum.csv'
        assert 'panel offline' in status.last_error
