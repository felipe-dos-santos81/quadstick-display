"""Shared test setup.

These tests run on hosts without Raspberry Pi hardware. The repository
root is placed on ``sys.path`` so the ``quadstick_display`` package and
the ``qs_display.py`` compatibility shim import the same way they do in
production. Tests must never instantiate ``hardware.WaveshareDisplay`` or
import ``waveshare_epd``; the ``FakeDisplay`` in ``tests/fakes.py``
records frames in memory instead.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
