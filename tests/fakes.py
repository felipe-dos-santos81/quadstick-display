"""Test doubles for the display seam (quadstick_display.controller).

These fakes run on hosts without Raspberry Pi hardware: they record the
frames they are shown instead of driving a panel. The default size mirrors
the production wiring for the 4.2-inch panel: logical width 400 (the
driver's ``height``) x logical height 300 (the driver's ``width``).
"""

from quadstick_display.controller import DisplayFrame, DisplaySize

PRODUCTION_SIZE = DisplaySize(width=400, height=300)


class FakeDisplay:
    """In-memory ``DisplayDevice`` recording every frame it is shown."""

    def __init__(self, size: DisplaySize = PRODUCTION_SIZE):
        self._size = size
        self.frames: list[DisplayFrame] = []
        self.initialized = False

    @property
    def size(self) -> DisplaySize:
        return self._size

    def initialize(self) -> None:
        self.initialized = True

    def show(self, frame: DisplayFrame) -> None:
        self.frames.append(frame)
