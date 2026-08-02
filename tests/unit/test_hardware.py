"""Unit tests for the Waveshare hardware adapter (quadstick_display.hardware).

The real ``waveshare_epd`` driver imports Raspberry Pi GPIO/SPI libraries
at module import time, so these tests stub ``waveshare_epd.epd4in2bc`` in
``sys.modules`` with a recording fake EPD. They pin the lazy import, the
production dimension swap (logical width = driver height, logical height =
driver width), and the initialize/show call sequence.
"""
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/

from fakes import PRODUCTION_SIZE  # noqa: E402

from quadstick_display.controller import (  # noqa: E402
    DisplayDevice,
    DisplayFrame,
    DisplaySize,
)
from quadstick_display.hardware import WaveshareDisplay  # noqa: E402

# Driver-reported geometry for the 4.2-inch panel; the adapter must swap
# these into the logical production size (400 x 300).
DRIVER_WIDTH = 300
DRIVER_HEIGHT = 400


class FakeEPD:
    """Recording stand-in for ``waveshare_epd.epd4in2bc.EPD``."""

    def __init__(self):
        self.width = DRIVER_WIDTH
        self.height = DRIVER_HEIGHT
        self.calls = []

    def init(self):
        self.calls.append('init')

    def Clear(self):
        self.calls.append('Clear')

    def getbuffer(self, image):
        self.calls.append(('getbuffer', image.size))
        return f'buffer:{image.size[0]}x{image.size[1]}'

    def display(self, imageblack, imagered):
        self.calls.append(('display', imageblack, imagered))


@pytest.fixture
def fake_driver(monkeypatch):
    """Stub ``waveshare_epd.epd4in2bc`` so the lazy import resolves."""
    epd4in2bc = ModuleType('waveshare_epd.epd4in2bc')
    epd4in2bc.EPD = FakeEPD
    package = ModuleType('waveshare_epd')
    package.epd4in2bc = epd4in2bc
    monkeypatch.setitem(sys.modules, 'waveshare_epd', package)
    monkeypatch.setitem(sys.modules, 'waveshare_epd.epd4in2bc', epd4in2bc)
    return epd4in2bc


def make_frame():
    size = (PRODUCTION_SIZE.width, PRODUCTION_SIZE.height)
    return DisplayFrame(
        black=Image.new('1', size, 255),
        red=Image.new('1', size, 255),
    )


class TestDimensionSwap:
    def test_size_swaps_driver_dimensions(self, fake_driver):
        display = WaveshareDisplay()
        assert display.size == DisplaySize(width=DRIVER_HEIGHT, height=DRIVER_WIDTH)
        assert display.size == PRODUCTION_SIZE

    def test_size_property_is_stable(self, fake_driver):
        display = WaveshareDisplay()
        assert display.size is display.size


class TestDeviceBehavior:
    def test_satisfies_the_device_protocol(self, fake_driver):
        assert isinstance(WaveshareDisplay(), DisplayDevice)

    def test_initialize_inits_then_clears(self, fake_driver):
        display = WaveshareDisplay()
        display.initialize()
        assert display._epd.calls == ['init', 'Clear']

    def test_show_displays_both_planes_and_waits(self, fake_driver, monkeypatch):
        sleeps = []
        monkeypatch.setattr(time, 'sleep', sleeps.append)
        display = WaveshareDisplay()
        frame = make_frame()
        display.show(frame)
        assert display._epd.calls == [
            ('getbuffer', (400, 300)),
            ('getbuffer', (400, 300)),
            ('display', 'buffer:400x300', 'buffer:400x300'),
        ]
        assert sleeps == [2]

    def test_show_buffers_the_exact_frame_images(self, fake_driver, monkeypatch):
        monkeypatch.setattr(time, 'sleep', lambda _: None)
        display = WaveshareDisplay()
        seen = []
        display._epd.getbuffer = lambda image: seen.append(image) or image
        frame = make_frame()
        display.show(frame)
        assert seen == [frame.black, frame.red]


class TestHardwarePurity:
    def test_importing_hardware_does_not_import_the_driver(self):
        code = (
            'import sys;'
            'import quadstick_display.hardware;'
            'assert "waveshare_epd" not in sys.modules,'
            ' "hardware must import the driver lazily"'
        )
        subprocess.run([sys.executable, '-c', code], check=True)

    def test_only_hardware_imports_waveshare(self):
        code = (
            'import sys;'
            'import quadstick_display.controller;'
            'import quadstick_display.model;'
            'import quadstick_display.view;'
            'assert "waveshare_epd" not in sys.modules'
        )
        subprocess.run([sys.executable, '-c', code], check=True)
