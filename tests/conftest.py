"""Shared fixtures for the characterization test suite.

These tests run on hosts without Raspberry Pi hardware. They must never
instantiate ``qs_display.EPaperDisplay`` or import ``waveshare_epd``; the
fake display below records the black/red frames in memory instead.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import qs_display  # noqa: E402


class FakeEPaperDisplay:
    """In-memory stand-in for ``qs_display.EPaperDisplay``.

    The dimensions mirror the production wiring for the 4.2-inch panel:
    ``EPaperDisplay.width = epd.height`` (400) and
    ``EPaperDisplay.height = epd.width`` (300).
    """

    def __init__(self, width=400, height=300):
        self.width = width
        self.height = height
        self.frames = []  # recorded (image_black, image_red) pairs
        self.initialized = False

    def initialize_display(self):
        self.initialized = True

    def display_content(self, image_black, image_red):
        self.frames.append((image_black, image_red))


@pytest.fixture
def fake_display():
    return FakeEPaperDisplay()


@pytest.fixture(autouse=True, scope='session')
def _event_loop():
    # HttpMenu.__init__ calls asyncio.get_event_loop(); provide a loop so the
    # tests do not rely on implicit loop creation (deprecated on 3.12).
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture
def http_env(tmp_path, monkeypatch, fake_display):
    """HttpMenu wired to the fake display and an isolated upload folder.

    The startup-screen IP lookup is stubbed so the tests make no network
    calls, and uploads land in a temporary directory instead of the real
    ``resources/quadstick_csvs`` folder.
    """
    monkeypatch.setattr(
        qs_display.InitScreen,
        '_get_local_ip_address',
        staticmethod(lambda: '192.0.2.1'),
    )
    menu = qs_display.HttpMenu(fake_display)
    menu.upload_folder = str(tmp_path)
    menu.app.config['UPLOAD_FOLDER'] = str(tmp_path)
    return SimpleNamespace(
        menu=menu,
        display=fake_display,
        client=menu.app.test_client(),
        upload_dir=tmp_path,
    )
