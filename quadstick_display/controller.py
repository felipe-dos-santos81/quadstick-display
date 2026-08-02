"""Display seam: panel geometry, frames, device protocol, and status.

This module hosts the types shared between the view (which produces
``DisplayFrame`` images), the hardware adapter (which consumes them), and
the M3 display controller (which owns the serialized display transaction).
It must stay importable without Raspberry Pi packages.

``DisplayController`` itself arrives in M3; only its supporting types are
defined here.
"""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from PIL import Image


@dataclass(frozen=True)
class DisplaySize:
    """Logical panel geometry in production orientation.

    The Waveshare 4.2-inch panel is wired so that the logical width is the
    driver's ``height`` and the logical height is the driver's ``width``;
    ``hardware.WaveshareDisplay`` performs that swap, so the rest of the
    application always works in this logical orientation.
    """

    width: int
    height: int


@dataclass(frozen=True)
class DisplayFrame:
    """The two monochrome planes sent to the e-paper panel."""

    black: Image.Image
    red: Image.Image


@runtime_checkable
class DisplayDevice(Protocol):
    """The minimal hardware seam: size, one-time init, and frame output."""

    @property
    def size(self) -> DisplaySize: ...

    def initialize(self) -> None: ...

    def show(self, frame: DisplayFrame) -> None: ...


@dataclass(frozen=True)
class DisplayStatus:
    """Observable display state: the last shown profile and last error."""

    current_profile: str | None
    last_error: str | None


class DisplayFailure(RuntimeError):
    """The physical display rejected a frame."""
